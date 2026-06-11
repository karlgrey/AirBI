"""Investment-Memo: komponiert Heimmarkt-Matrix + Vergleichsmarkt-Anker zu
einem erzählenden Memo (Urteil, Kapitel, Vertrauens-Stufe).

Spec: docs/superpowers/specs/2026-06-11-investment-memo-redesign-design.md.
`segment_matrix.py` bleibt der Rechen-Kern; dieses Modul erzeugt daraus
die Erzähl-Schicht."""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from airbi.db.models import CrawlRun, Listing, SearchConfig, Snapshot
from airbi.geo.distance import haversine_km
from airbi.insights.segment_matrix import (
    ListingRow,
    SegmentMatrix,
    _size_klartext,
    build_segment_matrix,
)

# Teil-3-Hook (Velocity-Modul): solange False, formuliert Kapitel 2 im
# Bestand ("hat gesammelt"); mit True wechselt es auf Buchungs-Trend.
VELOCITY_AVAILABLE = False

CONFIDENCE_BELASTBAR = "belastbar"
CONFIDENCE_SOLIDE = "solide Indizien"
CONFIDENCE_DUENN = "dünne Datenlage"

_CONFIDENCE_DOTS = {
    CONFIDENCE_BELASTBAR: 3,
    CONFIDENCE_SOLIDE: 2,
    CONFIDENCE_DUENN: 1,
}


def compute_confidence(
    *, data_age_days: int | None, n: int, min_sample: int, velocity_available: bool
) -> str:
    """Regelbasierte Vertrauens-Stufe (Spec §4)."""
    if data_age_days is None or n < min_sample:
        return CONFIDENCE_DUENN
    if velocity_available and data_age_days < 7:
        return CONFIDENCE_BELASTBAR
    if data_age_days <= 14:
        return CONFIDENCE_SOLIDE
    return CONFIDENCE_DUENN


@dataclass
class Fragment:
    """Ein Stück Kapitel-Inhalt: Fließtext oder Kennzahlen-Chip."""

    kind: str  # "text" | "chip" | "chip_muted"
    text: str


@dataclass
class AnchorStats:
    """Statistik eines benannten Vergleichsmarkts, lokal klassifiziert."""

    name: str
    radius_km: float
    listing_count: int
    segment_n: int = 0
    segment_score: float | None = None
    segment_adr: float | None = None


@dataclass
class MemoChapter:
    number: str  # "01" .. "04"
    title: str
    fragments: list[Fragment] = field(default_factory=list)

    @property
    def plain_text(self) -> str:
        """Kapitel als reiner Text — Grundlage des Jargon-Tests."""
        return " ".join(f.text for f in self.fragments)


@dataclass
class Memo:
    crawl_run_id: int | None
    home_radius_km: float
    center_label: str | None
    verdict_size_label: str | None      # "2 Schlafzimmer" — None = Memo schweigt
    verdict_luxury_class: str | None
    verdict_subline: str
    confidence: str
    confidence_dots: int                # 1..3, fürs ●●○-Rendering
    chapters: list[MemoChapter] = field(default_factory=list)
    home_matrix: SegmentMatrix | None = None
    anchors: list[AnchorStats] = field(default_factory=list)
    data_age_days: int | None = None


def _load_rows_for_center(
    session: Session,
    search_config: SearchConfig,
    crawl_run: CrawlRun,
    center_lat: float,
    center_lng: float,
    radius_km: float,
) -> list[ListingRow]:
    """Listings+Snapshots des Runs im Umkreis eines beliebigen Zentrums —
    gleiche Zeilen-Abbildung wie compute_segment_matrix, aber mit freiem
    Mittelpunkt (für Vergleichsmärkte)."""
    session.flush()
    stmt = (
        select(Listing, Snapshot)
        .join(Snapshot, Snapshot.listing_id == Listing.id)
        .where(Snapshot.crawl_run_id == crawl_run.id)
        .where(Listing.city_slug == search_config.city_slug)
    )
    rows: list[ListingRow] = []
    for listing, snap in session.execute(stmt).all():
        if listing.lat is None or listing.lng is None:
            continue
        if haversine_km(center_lat, center_lng, listing.lat, listing.lng) > radius_km:
            continue
        rows.append(
            ListingRow(
                airbnb_id=listing.airbnb_id,
                title=listing.title,
                url=listing.url,
                size_class=listing.size_class or "unclassified",
                price=snap.price,
                review_count=snap.review_count or 0,
                rating=snap.rating,
                amenity_score=listing.amenity_score or 0.0,
                amenities=listing.amenities or [],
                bedrooms=listing.bedrooms,
                beds=listing.beds,
                max_guests=listing.max_guests,
                is_superhost=bool(listing.is_superhost),
            )
        )
    return rows


def compute_anchor_stats(
    session: Session,
    search_config: SearchConfig,
    crawl_run: CrawlRun,
    market: dict,
    segment: tuple[str, str] | None,
) -> AnchorStats:
    """Statistik eines Vergleichsmarkts. Klassifikation in der EIGENEN
    Kohorte des Anker-Markts (Spec §2.2); `segment` ist die Heimmarkt-
    Empfehlung (size, lux), deren Pendant im Anker gesucht wird."""
    rows = _load_rows_for_center(
        session, search_config, crawl_run,
        market["lat"], market["lng"], market["radius_km"],
    )
    matrix = build_segment_matrix(
        rows,
        config=search_config.classification_config or {},
        radius_km=market["radius_km"],
        center_label=market["name"],
        crawl_run_id=crawl_run.id,
    )
    stats = AnchorStats(
        name=market["name"],
        radius_km=float(market["radius_km"]),
        listing_count=matrix.listing_count,
    )
    if segment is not None:
        cell = matrix.cell(*segment)
        stats.segment_n = cell.n
        stats.segment_score = cell.score
        stats.segment_adr = float(cell.adr) if cell.adr is not None else None
    return stats


# ---------------------------------------------------------------------------
# Task 4: Kapitel-Generator build_memo
# ---------------------------------------------------------------------------


def _fmt_score(score: float) -> str:
    return f"{score:.0f}"


def _median_cell_score(matrix: SegmentMatrix) -> float | None:
    scores = sorted(
        c.score for c in matrix.cells.values() if c.score is not None and c.n > 0
    )
    if not scores:
        return None
    mid = len(scores) // 2
    if len(scores) % 2:
        return scores[mid]
    return (scores[mid - 1] + scores[mid]) / 2


def _density_phrase(home_count: int, anchor: AnchorStats) -> str:
    if anchor.listing_count <= 0:
        return ""
    ratio = home_count / anchor.listing_count
    if ratio < 0.15:
        return "ein Bruchteil dieser Dichte"
    if ratio < 0.45:
        return f"rund ein {'Drittel' if ratio >= 0.28 else 'Viertel'} dieser Dichte"
    if ratio < 0.8:
        return "etwa die Hälfte dieser Dichte"
    return "eine vergleichbare Dichte"


def build_memo(
    home_matrix: SegmentMatrix,
    anchors: list[AnchorStats],
    *,
    data_age_days: int | None,
    al_zone_status: str | None = None,
    velocity_available: bool = VELOCITY_AVAILABLE,
) -> Memo:
    """Erzeugt das Memo aus der fertigen Heimmarkt-Matrix + Anker-Statistik.
    Ohne Best-Cell schweigt das Memo (kein Urteil, keine Kapitel)."""
    radius = home_matrix.radius_km or 0.0
    center = home_matrix.center_label or "das Zielobjekt"

    if home_matrix.best_cell is None:
        return Memo(
            crawl_run_id=home_matrix.crawl_run_id,
            home_radius_km=radius,
            center_label=home_matrix.center_label,
            verdict_size_label=None,
            verdict_luxury_class=None,
            verdict_subline=(
                f"Im Heimmarkt ({radius:g} km um {center}) erreicht noch keine "
                f"Kombination aus Größe und Luxusklasse {home_matrix.min_sample} "
                f"vergleichbare Apartments — das Memo trifft deshalb kein Urteil."
            ),
            confidence=CONFIDENCE_DUENN,
            confidence_dots=_CONFIDENCE_DOTS[CONFIDENCE_DUENN],
            home_matrix=home_matrix,
            anchors=anchors,
            data_age_days=data_age_days,
        )

    size, lux = home_matrix.best_cell
    bcell = home_matrix.cell(size, lux)
    size_label = _size_klartext(size)
    confidence = compute_confidence(
        data_age_days=data_age_days, n=bcell.n,
        min_sample=home_matrix.min_sample,
        velocity_available=velocity_available,
    )

    chapters: list[MemoChapter] = []

    # ---- Kapitel 1: Der Markt vor Ort -------------------------------
    frags = [Fragment("text", (
        f"Im Heimmarkt — {radius:g} km um {center} — stehen "
        f"{home_matrix.listing_count} vergleichbare Apartments im Wettbewerb."
    ))]
    if anchors:
        first = anchors[0]
        frags.append(Fragment("text", "Zum Vergleich:"))
        for a in anchors:
            frags.append(Fragment("chip_muted", f"{a.name} {a.listing_count} Apartments"))
        phrase = _density_phrase(home_matrix.listing_count, first)
        if phrase:
            frags.append(Fragment("text", (
                f"— der Heimmarkt hat {phrase}, typisch für eine junge Lage "
                f"mit Raum für neue Anbieter."
            )))
    chapters.append(MemoChapter(f"{len(chapters) + 1:02d}", "Der Markt vor Ort", frags))

    # ---- Kapitel 2: Wo die Nachfrage hinläuft ------------------------
    verb = (
        "wird aktuell am stärksten gebucht"
        if velocity_available
        else "hat je Apartment die meisten Bewertungen gesammelt"
    )
    frags = [Fragment("text", f"{size_label} im {lux}-Segment {verb}:")]
    median = _median_cell_score(home_matrix)
    chip = f"{_fmt_score(bcell.score)} Bewertungen je Apartment"
    if median is not None and median > 0:
        chip += f" — {bcell.score / median:.1f}× des lokalen Medians"
    frags.append(Fragment("chip", chip))
    scored = [a for a in anchors if a.segment_score is not None and a.segment_score > 0]
    if scored:
        frags.append(Fragment("text", "Dieselbe Klasse erreicht in"))
        for a in scored:
            frags.append(Fragment("chip_muted", f"{a.name} {_fmt_score(a.segment_score)}"))
        strongest = max(scored, key=lambda a: a.segment_score)
        pct = int(round(100 * bcell.score / strongest.segment_score))
        frags.append(Fragment("text", (
            f"— der Heimmarkt liegt damit bei {pct} % des stärksten "
            f"Vergleichsmarkts, bei deutlich weniger Wettbewerbern "
            f"({bcell.n} gegenüber {strongest.segment_n})."
        )))
    chapters.append(MemoChapter(f"{len(chapters) + 1:02d}", "Wo die Nachfrage hinläuft", frags))

    # ---- Kapitel 3: Die Alternative (nur mit Lücken-Fund) -------------
    gap = home_matrix.gap_cell
    if gap is not None:
        neighbor_label = _size_klartext(gap.strongest_neighbor_size_class)
        neighbor_full = f"{neighbor_label} · {gap.strongest_neighbor_luxury_class}"
        frags = [
            Fragment("text", (
                f"{_size_klartext(gap.size_class)} · {gap.luxury_class} ist im "
                f"Heimmarkt bislang praktisch unbesetzt."
            )),
            Fragment("text", (
                f"Das angrenzende Segment {neighbor_full} zeigt mit "
                f"{gap.strongest_neighbor_n} Apartments und durchschnittlich "
                f"{int(round(gap.strongest_neighbor_score))} Bewertungen je Apartment "
                f"starke Nachfrage — ein Hinweis, dass diese Lücke echte Zahlungsbereitschaft "
                f"hat. Vorteil: kaum Wettbewerb. Nachteil: weniger Erfahrungswerte."
            )),
        ]
        chapters.append(MemoChapter(f"{len(chapters) + 1:02d}", "Die Alternative", frags))

    # ---- Kapitel 4: Was dagegen spricht (immer) -----------------------
    rate_pct = int(round(home_matrix.review_rate * 100))
    frags = []
    if data_age_days is not None:
        age_text = f"Der Datenstand ist {data_age_days} Tage alt."
        if data_age_days > 14:
            age_text += " Das ist zu alt für ein belastbares Urteil — ein frischer Datenlauf steht aus."
        frags.append(Fragment("text", age_text))
    frags.append(Fragment("text", (
        f"Alle Nachfrage-Werte sind aus Bewertungen abgeleitet (Annahme: rund "
        f"{rate_pct} % der Gäste bewerten) — ein Indikator, keine gemessene Auslastung."
    )))
    if al_zone_status is None:
        frags.append(Fragment("text", (
            "Die AL-Lizenz-Lage (Zonas de Contenção) ist für diese Adresse noch "
            "ungeprüft — vor einer Investitionsentscheidung zwingend zu klären."
        )))
    if bcell.n < 2 * home_matrix.min_sample:
        frags.append(Fragment("text", (
            f"Die Stichprobe im empfohlenen Segment ist mit {bcell.n} Apartments "
            f"überschaubar — einzelne Ausreißer können das Bild verschieben."
        )))
    if confidence == CONFIDENCE_DUENN:
        frags.append(Fragment("text", (
            "Insgesamt ist die Datenlage dünn; dieses Memo ist als erster "
            "Hinweis zu lesen, nicht als Entscheidungsgrundlage."
        )))
    chapters.append(MemoChapter(f"{len(chapters) + 1:02d}", "Was dagegen spricht", frags))

    return Memo(
        crawl_run_id=home_matrix.crawl_run_id,
        home_radius_km=radius,
        center_label=home_matrix.center_label,
        verdict_size_label=size_label,
        verdict_luxury_class=lux,
        verdict_subline=(
            f"die stärkste Kombination im Heimmarkt — {radius:g} km um {center}"
        ),
        confidence=confidence,
        confidence_dots=_CONFIDENCE_DOTS[confidence],
        chapters=chapters,
        home_matrix=home_matrix,
        anchors=anchors,
        data_age_days=data_age_days,
    )
