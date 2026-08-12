"""Investment-Memo: komponiert Heimmarkt-Matrix + Vergleichsmarkt-Anker zu
einem erzählenden Memo (Urteil, Kapitel, Vertrauens-Stufe).

Spec: docs/superpowers/specs/2026-06-11-investment-memo-redesign-design.md.
`segment_matrix.py` bleibt der Rechen-Kern; dieses Modul erzeugt daraus
die Erzähl-Schicht."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from airbi.db.models import CrawlRun, Listing, SearchConfig, Snapshot
from airbi.geo.distance import haversine_km
from airbi.insights.segment_matrix import (
    ListingRow,
    SegmentMatrix,
    _size_klartext,
    build_segment_matrix,
    compute_segment_matrix,
)
from airbi.insights.recommendation_history import (
    DEFAULT_HYSTERESIS_N,
    HysteresisResult,
    RecommendationEntry,
    apply_hysteresis,
    load_recommendation_history,
    record_recommendation,
)
from airbi.insights.velocity import attach_velocities

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

# Memo-Review 11.08.2026: "belastbar" nur an Datenmenge zu koppeln reicht
# nicht -- bei z.B. 1,1x Median ist das Signal nahe am Rauschen. Default:
# das empfohlene Segment muss mindestens das 1,3-Fache des lokalen
# Zellen-Medians erreichen (Score oder Velocity, je nach Kapitel-2-Weiche).
DEFAULT_MIN_CONFIDENCE_MULTIPLIER = 1.3


def compute_confidence(
    *,
    data_age_days: int | None,
    n: int,
    min_sample: int,
    velocity_available: bool,
    multiplier: float | None = None,
    min_multiplier: float = DEFAULT_MIN_CONFIDENCE_MULTIPLIER,
) -> str:
    """Regelbasierte Vertrauens-Stufe (Spec §4 + Multiplikator-Kopplung
    Memo-Review 11.08.2026). `multiplier` ist das Vielfache des lokalen
    Zellen-Medians, das die Empfehlung erreicht -- fehlt es (None), lässt
    sich die Zusatzbedingung nicht belegen und die Stufe bleibt konservativ
    bei 'solide Indizien'."""
    if data_age_days is None or n < min_sample:
        return CONFIDENCE_DUENN
    if velocity_available and data_age_days < 7:
        if multiplier is not None and multiplier >= min_multiplier:
            return CONFIDENCE_BELASTBAR
        return CONFIDENCE_SOLIDE
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
    # Velocity (Teilprojekt 3): Ø wöchentliche Review-Zunahme im Segment,
    # analog zu segment_score, nur belastbar wenn segment_velocity_n groß genug.
    segment_velocity: float | None = None
    segment_velocity_n: int = 0


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
    # Empfehlungs-Changelog + Hysterese (Memo-Review 11.08.2026, SmartTasks #151):
    changelog: MemoChapter | None = None            # None = erster Lauf, kein Vergleichswert
    verdict_size_class: str | None = None            # Roh-Code der ANGEZEIGTEN Empfehlung ("1BR")
    # Rohes Best-Cell-Segment dieses Laufs — unabhängig von der Hysterese-
    # Haltung, Basis für den Persistenz-Aufruf in compute_memo.
    raw_verdict_size_class: str | None = None
    raw_verdict_luxury_class: str | None = None
    raw_score: float | None = None                   # Score oder Velocity, je nach Weiche
    raw_multiplier: float | None = None               # Vielfaches des lokalen Zellen-Medians
    used_velocity: bool = False                       # welche Metrik raw_score/raw_multiplier meint


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
                listing_id=listing.id,
            )
        )
    attach_velocities(session, rows)
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
    Empfehlung (size, lux), deren Pendant im Anker gesucht wird.
    Vergleichsmärkte müssen in derselben Stadt liegen wie die SearchConfig
    (city_slug-Filter) — ein Anker in einer anderen Stadt liefert still 0 Listings."""
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
        stats.segment_velocity = cell.velocity
        stats.segment_velocity_n = cell.velocity_n
    return stats


# ---------------------------------------------------------------------------
# Task 4: Kapitel-Generator build_memo
# ---------------------------------------------------------------------------


def _fmt_score(score: float) -> str:
    return f"{score:.0f}"


def _fmt_velocity(velocity: float) -> str:
    return f"{velocity:.1f}"


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


def _median_cell_velocity(matrix: SegmentMatrix) -> float | None:
    velocities = sorted(
        c.velocity for c in matrix.cells.values()
        if c.velocity is not None and c.velocity_n > 0
    )
    if not velocities:
        return None
    mid = len(velocities) // 2
    if len(velocities) % 2:
        return velocities[mid]
    return (velocities[mid - 1] + velocities[mid]) / 2


def _fmt_date(dt: datetime | None) -> str:
    """Datum für den Changelog-Text: '10.08.2026'."""
    if dt is None:
        return "unbekanntem Datum"
    return dt.strftime("%d.%m.%Y")


def _lauf_plural(n: int) -> str:
    return "Lauf" if n == 1 else "Läufe"


def _lauf_dative_plural(n: int) -> str:
    return "Lauf" if n == 1 else "Läufen"


def _segment_metrics(
    matrix: SegmentMatrix, size: str, lux: str, velocity_available: bool
) -> tuple[bool, float | None, float | None]:
    """Liefert (use_velocity, eigener Wert, Vielfaches des lokalen Zellen-
    Medians) für ein Segment — Basis für Kapitel-2-Chip, Vertrauensstufe UND
    die persistierten raw_score/raw_multiplier-Felder."""
    cell = matrix.cell(size, lux)
    use_velocity = velocity_available and cell.velocity is not None
    if use_velocity:
        value = cell.velocity
        median_value = _median_cell_velocity(matrix)
    else:
        value = cell.score
        median_value = _median_cell_score(matrix)
    multiplier = (
        value / median_value
        if value is not None and median_value is not None and median_value > 0
        else None
    )
    return use_velocity, value, multiplier


def _build_changelog(
    *,
    size_label: str,
    lux: str,
    history: list[RecommendationEntry],
    hysteresis: HysteresisResult,
    hysteresis_n: int,
    run_date: datetime | None,
) -> MemoChapter | None:
    """Empfehlungs-Changelog (Memo-Review 11.08.2026, SmartTasks #151): ein
    Empfehlungswechsel wird explizit ausgewiesen statt still zu passieren.
    Ohne Historie (erster Lauf) gibt es keinen Vergleichswert -> kein
    Abschnitt."""
    if not history:
        return None

    label_new = f"{size_label} · {lux}"

    if hysteresis.switched:
        old_label = (
            f"{_size_klartext(hysteresis.previous_size_class)} · "
            f"{hysteresis.previous_luxury_class}"
        )
        if hysteresis_n == 1:
            reason = f"{label_new} lag im aktuellen Lauf vorn"
        else:
            reason = (
                f"{label_new} lag {hysteresis_n} {_lauf_plural(hysteresis_n)} "
                f"in Folge vorn"
            )
        text = (
            f"Empfehlung geändert am {_fmt_date(run_date)}: von {old_label} zu "
            f"{label_new}. Grund: {reason}."
        )
    elif hysteresis.challenger_size_class is not None:
        challenger_label = (
            f"{_size_klartext(hysteresis.challenger_size_class)} · "
            f"{hysteresis.challenger_luxury_class}"
        )
        streak = hysteresis.challenger_streak
        text = (
            f"Empfehlung unverändert: {label_new}. Herausforderer: "
            f"{challenger_label}, führt seit {streak} {_lauf_dative_plural(streak)}."
        )
    else:
        text = (
            f"Empfehlung unverändert seit dem letzten Lauf "
            f"({_fmt_date(history[-1].run_date)}): {label_new}."
        )

    return MemoChapter("", "Empfehlungs-Verlauf", [Fragment("text", text)])


def _density_phrase(home_count: int, home_radius_km: float, anchor: AnchorStats) -> str:
    import math
    home_area = math.pi * home_radius_km ** 2
    anchor_area = math.pi * anchor.radius_km ** 2
    if anchor.listing_count <= 0 or anchor_area <= 0 or home_area <= 0:
        return ""
    ratio = (home_count / home_area) / (anchor.listing_count / anchor_area)
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
    history: list[RecommendationEntry] | None = None,
    hysteresis_n: int = DEFAULT_HYSTERESIS_N,
    min_confidence_multiplier: float = DEFAULT_MIN_CONFIDENCE_MULTIPLIER,
    run_date: datetime | None = None,
) -> Memo:
    """Erzeugt das Memo aus der fertigen Heimmarkt-Matrix + Anker-Statistik.
    Ohne Best-Cell schweigt das Memo (kein Urteil, keine Kapitel).

    `history` (älteste → neueste, ohne den aktuellen Lauf) steuert zwei
    Dinge aus dem Memo-Review 11.08.2026 (SmartTasks #151): die Hysterese
    (ein neues Segment wird erst nach `hysteresis_n` Läufen in Folge zur
    angezeigten Empfehlung) und den Changelog-Abschnitt (`Memo.changelog`),
    der jeden Wechsel explizit ausweist statt ihn still passieren zu
    lassen."""
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

    history = history or []

    # Rohes Best-Cell-Segment dieses Laufs — unabhängig von der Hysterese-
    # Haltung, Basis für Persistenz (compute_memo) und Streak-Zählung.
    raw_size, raw_lux = home_matrix.best_cell
    raw_use_velocity, raw_value, raw_multiplier = _segment_metrics(
        home_matrix, raw_size, raw_lux, velocity_available
    )

    hysteresis = apply_hysteresis(raw_size, raw_lux, history, hysteresis_n=hysteresis_n)
    size, lux = hysteresis.displayed_size_class, hysteresis.displayed_luxury_class
    bcell = home_matrix.cell(size, lux)

    if bcell.n == 0:
        # Das gehaltene Segment hat in diesem Lauf keine Wettbewerber mehr
        # (aus der Matrix verschwunden) — Hysterese kann nichts mehr halten,
        # zurück auf die rohe Best-Cell. Grenzfall (Datenbruch), kein
        # normaler Wechsel -> kein Changelog-Eintrag dafür.
        size, lux = raw_size, raw_lux
        bcell = home_matrix.cell(size, lux)
        hysteresis = HysteresisResult(
            displayed_size_class=size, displayed_luxury_class=lux, switched=False
        )
        history = []  # unterdrückt den Changelog-Abschnitt für diesen Grenzfall

    size_label = _size_klartext(size)
    use_velocity, own_value, multiplier = _segment_metrics(
        home_matrix, size, lux, velocity_available
    )
    confidence = compute_confidence(
        data_age_days=data_age_days, n=bcell.n,
        min_sample=home_matrix.min_sample,
        velocity_available=use_velocity,
        multiplier=multiplier,
        min_multiplier=min_confidence_multiplier,
    )
    changelog = _build_changelog(
        size_label=size_label, lux=lux, history=history, hysteresis=hysteresis,
        hysteresis_n=hysteresis_n, run_date=run_date,
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
        phrase = _density_phrase(home_matrix.listing_count, radius, first)
        if phrase:
            frags.append(Fragment("text", (
                f"— auf die Fläche gerechnet hat der Heimmarkt {phrase}, typisch für eine junge Lage "
                f"mit Raum für neue Anbieter."
            )))
    chapters.append(MemoChapter(f"{len(chapters) + 1:02d}", "Der Markt vor Ort", frags))

    # ---- Kapitel 2: Wo die Nachfrage hinläuft ------------------------
    # Teil-3-Weiche: Bestand (Ø Bewertungen je Apartment, kumuliert) vs.
    # Trend (Ø wöchentliche Bewertungs-Zunahme) — real, sobald die Best-Cell
    # genug Listings mit belastbarem Velocity-Signal hat (home_matrix.velocity_
    # available bzw. der übergebene Flag). Fällt defensiv auf Bestand zurück,
    # wenn der Flag zwar True ist, die Best-Cell aber (noch) kein Signal hat.
    # use_velocity/own_value/multiplier bereits oben via _segment_metrics
    # berechnet (auch Basis für die Vertrauensstufe, Task 3).
    verb = (
        "wird aktuell am stärksten gebucht"
        if use_velocity
        else "hat je Apartment die meisten Bewertungen gesammelt"
    )
    frags = [Fragment("text", f"{size_label} im {lux}-Segment {verb}:")]
    unit = " Bewertungen/Woche je Apartment" if use_velocity else " Bewertungen je Apartment"
    fmt_own = _fmt_velocity(own_value) if use_velocity else _fmt_score(own_value)
    chip = f"{fmt_own}{unit}"
    if multiplier is not None:
        chip += f" — {multiplier:.1f}× des lokalen Medians"
    frags.append(Fragment("chip", chip))

    if use_velocity:
        scored = [
            a for a in anchors
            if a.segment_velocity is not None
            and a.segment_velocity > 0
            and a.segment_velocity_n >= home_matrix.min_sample
        ]
    else:
        scored = [
            a for a in anchors
            if a.segment_score is not None
            and a.segment_score > 0
            and a.segment_n >= home_matrix.min_sample
        ]
    if scored:
        frags.append(Fragment("text", "Dieselbe Klasse erreicht in"))
        for i, a in enumerate(scored):
            value = a.segment_velocity if use_velocity else a.segment_score
            fmt_value = _fmt_velocity(value) if use_velocity else _fmt_score(value)
            if i == 0:
                unit = " Bewertungen/Woche je Apartment" if use_velocity else " Bewertungen je Apartment"
                chip_text = f"{a.name}: {fmt_value}{unit}"
            else:
                chip_text = f"{a.name}: {fmt_value}"
            frags.append(Fragment("chip_muted", chip_text))
        own_value = bcell.velocity if use_velocity else bcell.score
        strongest = max(
            scored,
            key=lambda a: a.segment_velocity if use_velocity else a.segment_score,
        )
        strongest_value = strongest.segment_velocity if use_velocity else strongest.segment_score
        ratio = own_value / strongest_value
        if ratio > 1.0:
            closing = (
                f"— der Heimmarkt liegt damit beim {ratio:.1f}-Fachen von {strongest.name}."
            )
        else:
            pct = int(round(100 * ratio))
            closing = (
                f"— der Heimmarkt erreicht damit {pct} % des Niveaus von {strongest.name}."
            )
        competitor = (
            f" Dabei stehen hier {bcell.n} Anbieter im Wettbewerb, dort {strongest.segment_n}."
        )
        frags.append(Fragment("text", closing + competitor))
    elif anchors:
        frags.append(Fragment("text", (
            "In den Vergleichsmärkten ist dieselbe Klasse bislang zu dünn besetzt "
            "für einen belastbaren Vergleich."
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
        day_word = "Tag" if data_age_days == 1 else "Tage"
        age_text = f"Der Datenstand ist {data_age_days} {day_word} alt."
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
    elif al_zone_status in ("CONTENCAO", "CONTENCAO_ABSOLUTA"):
        frags.append(Fragment("text", (
            "Die Adresse liegt in einer Zona de Contenção — neue Alojamento-"
            "Local-Lizenzen sind dort eingeschränkt oder ausgesetzt. Ohne eine "
            "bestehende, übertragbare Lizenz ist das ein hartes Ausschluss-Risiko "
            "und vor allem anderen zu klären."
        )))
    if bcell.n < 2 * home_matrix.min_sample:
        frags.append(Fragment("text", (
            f"Die Stichprobe im empfohlenen Segment ist mit {bcell.n} Apartments "
            f"überschaubar — einzelne Ausreißer können das Bild verschieben."
        )))
    # Vertrauensstufen-Begründung (Task 3, Memo-Review 11.08.2026): greift
    # genau dann, wenn Datenmenge + Frische für "belastbar" gereicht hätten,
    # der Multiplikator gegenüber dem lokalen Median aber zu gering war.
    if (
        use_velocity
        and confidence != CONFIDENCE_BELASTBAR
        and data_age_days is not None
        and data_age_days < 7
        and bcell.n >= home_matrix.min_sample
    ):
        if multiplier is not None:
            frags.append(Fragment("text", (
                f"Die Nachfrage im empfohlenen Segment liegt beim {multiplier:.1f}-fachen "
                f"des lokalen Medians — für die Vertrauensstufe belastbar wäre "
                f"mindestens das {min_confidence_multiplier:.1f}-fache nötig, deshalb "
                f"bleibt es vorerst bei solide Indizien."
            )))
        else:
            frags.append(Fragment("text", (
                "Der Vergleich zum lokalen Median lässt sich für dieses Segment nicht "
                "bilden, deshalb bleibt es vorerst bei solide Indizien statt belastbar."
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
        changelog=changelog,
        verdict_size_class=size,
        raw_verdict_size_class=raw_size,
        raw_verdict_luxury_class=raw_lux,
        raw_score=raw_value,
        raw_multiplier=raw_multiplier,
        used_velocity=raw_use_velocity,
        chapters=chapters,
        home_matrix=home_matrix,
        anchors=anchors,
        data_age_days=data_age_days,
    )


# ---------------------------------------------------------------------------
# Task 5: compute_memo Orchestrierung
# ---------------------------------------------------------------------------


def _data_age_days(crawl_run: CrawlRun) -> int | None:
    if crawl_run.started_at is None:
        return None
    started = crawl_run.started_at
    now = datetime.now(started.tzinfo) if started.tzinfo else datetime.now()
    return max(0, (now.date() - started.date()).days)


def compute_memo(
    session: Session, search_config: SearchConfig, crawl_run: CrawlRun
) -> Memo:
    """Memo für eine SearchConfig: Heimmarkt-Matrix + Anker + Kapitel.

    Lädt die Empfehlungs-Historie (Changelog + Hysterese, Memo-Review
    11.08.2026 / SmartTasks #151) und persistiert die Empfehlung dieses
    Laufs im Anschluss idempotent — je SearchConfig+CrawlRun ein Eintrag."""
    home_radius = search_config.home_radius_km or min(
        search_config.band_radii_km or [2.0]
    )
    home_matrix = compute_segment_matrix(
        session, search_config, float(home_radius), crawl_run
    )
    anchors = [
        compute_anchor_stats(
            session, search_config, crawl_run, market, home_matrix.best_cell
        )
        for market in (search_config.comparison_markets or [])
    ]
    insight_config = search_config.classification_config or {}
    hysteresis_n = int(insight_config.get("hysteresis_n", DEFAULT_HYSTERESIS_N))
    min_confidence_multiplier = float(
        insight_config.get("min_confidence_multiplier", DEFAULT_MIN_CONFIDENCE_MULTIPLIER)
    )
    history = load_recommendation_history(session, search_config, before_crawl_run=crawl_run)

    memo = build_memo(
        home_matrix,
        anchors,
        data_age_days=_data_age_days(crawl_run),
        al_zone_status=search_config.al_zone_status,
        # Teil-3-Hook (vormals VELOCITY_AVAILABLE=False fest verdrahtet):
        # jetzt real aus der Snapshot-Historie der Best-Cell abgeleitet
        # (siehe SegmentMatrix.velocity_available in segment_matrix.py).
        velocity_available=home_matrix.velocity_available,
        history=history,
        hysteresis_n=hysteresis_n,
        min_confidence_multiplier=min_confidence_multiplier,
        run_date=crawl_run.started_at,
    )

    if home_matrix.best_cell is not None:
        record_recommendation(
            session, search_config, crawl_run,
            raw_size_class=memo.raw_verdict_size_class,
            raw_luxury_class=memo.raw_verdict_luxury_class,
            raw_score=memo.raw_score,
            raw_multiplier=memo.raw_multiplier,
            used_velocity=memo.used_velocity,
            displayed_size_class=memo.verdict_size_class,
            displayed_luxury_class=memo.verdict_luxury_class,
            confidence=memo.confidence,
        )

    return memo
