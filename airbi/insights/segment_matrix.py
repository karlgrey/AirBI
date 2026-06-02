"""Segment-Matrix-Insight (Spec §9).

Drei Schichten:
- Datacontainer: ListingRow (Eingabe), Cell / TopPerformer / SegmentMatrix
  (Ausgabe).
- Reiner Builder: build_segment_matrix(rows, config) — keine DB, kein HTTP.
- DB-Anbindung: compute_segment_matrix(session, ...) zieht die Daten und
  ruft den reinen Builder. Lebt im selben Modul, ist aber sauber getrennt.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from statistics import median

from sqlalchemy import select
from sqlalchemy.orm import Session

from airbi.classification.luxury import LUXURY_CLASSES, luxury_class as _luxury_class
from airbi.classification.price import price_percentile as _price_percentile
from airbi.db.models import CrawlRun, Listing, SearchConfig, Snapshot
from airbi.geo.distance import haversine_km

# Reihenfolge bestimmt die Render-Reihenfolge in der Matrix.
SIZE_CLASSES: list[str] = ["Studio", "1BR", "2BR", "3BR+"]

# Defaults für die Insight-spezifischen Knöpfe in SearchConfig.classification_config.
DEFAULT_INSIGHT_CONFIG: dict = {
    "min_sample": 3,        # Zellen mit weniger Listings gelten als "zu dünn".
    "review_rate": 0.40,    # Anteil bewertender Gäste (Briefing §3, ~30-50 %).
    "top_performers_per_segment": 2,
    "amenity_share_threshold": 0.5,   # Anteil-Schwelle für "common amenities".
    "common_amenities_max": 6,         # Max Items in TopPerformerProfile.common_amenities.
    "underserved_max": 3,              # Max Einträge in der Unterversorgungs-Sicht.
}


@dataclass
class ListingRow:
    """Ein Listing + sein Snapshot aus einem CrawlRun. Der reine Builder
    konsumiert nur diese Records."""

    airbnb_id: str
    title: str | None
    url: str | None
    size_class: str            # aus airbi.classification.size.size_class
    price: Decimal | None      # Nacht-Preis aus dem Snapshot
    review_count: int
    rating: float | None
    amenity_score: float = 0.0
    # Detail-Felder für TopPerformerProfile-Aggregation:
    amenities: list = field(default_factory=list)
    bedrooms: int | None = None
    beds: int | None = None
    max_guests: int | None = None
    is_superhost: bool = False


@dataclass
class Cell:
    """Eine Zelle der Matrix (eine Kombination Größe × luxury_class)."""

    size_class: str
    luxury_class: str
    n: int = 0                         # Wettbewerbsdichte
    review_sum: int = 0                # Nachfrage-Proxy R
    score: float | None = None         # R / N = Ø Reviews je Listing
    adr: Decimal | None = None         # Median-Nacht-Preis der Zelle
    is_thin: bool = True               # N < min_sample
    heat: int = 0                      # 0-4, relativ zum besten nicht-dünnen Score


@dataclass
class TopPerformer:
    airbnb_id: str
    title: str | None
    url: str | None
    size_class: str
    luxury_class: str
    review_count: int
    rating: float | None


@dataclass
class UnderservedSegment:
    """Eine 'Chancen-Zelle' aus der Matrix: hohe Nachfrage je Wettbewerber
    (Brief §8.2). Wird in der Ranking-Liste unter dem Brief gezeigt."""

    size_class: str
    luxury_class: str
    n: int
    adr: "Decimal | None"
    score: float
    is_thin: bool
    rationale: str = ""           # Kurze Prosa-Begründung (1-2 Sätze).


@dataclass
class TopPerformerProfile:
    """Aggregierte Merkmale der ausgewählten Top-Performer einer Matrix —
    'was zeichnet sie aus' (Briefing §8.3)."""

    count: int = 0
    superhost_share: float | None = None        # 0..1
    price_median: Decimal | None = None
    price_min: Decimal | None = None
    price_max: Decimal | None = None
    median_bedrooms: int | None = None
    median_beds: int | None = None
    median_max_guests: int | None = None
    # (Amenity-Name, Anteil 0..1), absteigend nach Anteil.
    common_amenities: list = field(default_factory=list)


@dataclass
class SegmentMatrix:
    """Vollständiges Insight-Ergebnis für genau einen Umkreis + einen CrawlRun."""

    radius_km: float | None
    crawl_run_id: int | None
    center_label: str | None = None
    size_classes: list[str] = field(default_factory=lambda: list(SIZE_CLASSES))
    luxury_classes: list[str] = field(default_factory=lambda: list(LUXURY_CLASSES))
    cells: dict[tuple[str, str], Cell] = field(default_factory=dict)
    best_cell: tuple[str, str] | None = None
    recommendation: str = ""
    top_performers: list[TopPerformer] = field(default_factory=list)
    top_performer_profile: TopPerformerProfile | None = None
    underserved: list[UnderservedSegment] = field(default_factory=list)
    listing_count: int = 0
    review_rate: float = DEFAULT_INSIGHT_CONFIG["review_rate"]
    min_sample: int = DEFAULT_INSIGHT_CONFIG["min_sample"]

    def cell(self, size_class: str, luxury_class: str) -> Cell:
        """Template-freundlicher Zugriff (Jinja kann keine Tuple-Subscripts)."""
        return self.cells[(size_class, luxury_class)]


def _merge_config(config: dict | None) -> dict:
    return {**DEFAULT_INSIGHT_CONFIG, **(config or {})}


def _empty_grid() -> dict[tuple[str, str], Cell]:
    return {
        (size, lux): Cell(size_class=size, luxury_class=lux)
        for size in SIZE_CLASSES
        for lux in LUXURY_CLASSES
    }


def _build_recommendation(matrix: SegmentMatrix) -> str:
    """Formuliert den Empfehlungssatz aus der gefüllten Matrix."""
    label = matrix.center_label or "dem Zielobjekt"
    radius = f"{matrix.radius_km:g}"
    if matrix.best_cell is None:
        return (
            f"Im Umkreis von {radius} km um {label} liefert dieser Crawl noch "
            f"keine Zelle mit mindestens {matrix.min_sample} vergleichbaren "
            f"Objekten — die Datenbasis ist für eine belastbare Empfehlung zu "
            f"dünn."
        )
    size, luxury = matrix.best_cell
    cell = matrix.cell(size, luxury)
    score = cell.score or 0.0
    adr = int(cell.adr) if cell.adr is not None else 0
    rate_pct = int(round(matrix.review_rate * 100))
    return (
        f"Im Umkreis von {radius} km um {label} ist {size}-{luxury} am "
        f"attraktivsten — Ø {score:.0f} Reviews je Listing bei {cell.n} "
        f"Wettbewerber-Listings, Median-ADR €{adr}. Nachfrage ist ein Proxy "
        f"aus Review-Count (~{rate_pct}% der Gäste bewerten), keine gemessene "
        f"Auslastung."
    )


def _compute_top_performer_profile(
    rows: list[ListingRow],
    config: dict,
) -> TopPerformerProfile | None:
    """Aggregiert gemeinsame Merkmale der gegebenen Listings — Räume-Median,
    Superhost-Quote, Preis-Spanne, häufigste Amenities.

    Wird vom Builder mit den Listings des empfohlenen Best-Cells aufgerufen
    (damit das Profil konsistent zur Hero-Empfehlung ist). Bei leerer Eingabe
    Rückgabe ``None``.
    """
    if not rows:
        return None
    tp_rows = rows

    n = len(tp_rows)
    superhost_count = sum(1 for r in tp_rows if r.is_superhost)
    prices = [r.price for r in tp_rows if r.price is not None]
    bedrooms = [r.bedrooms for r in tp_rows if r.bedrooms is not None]
    beds = [r.beds for r in tp_rows if r.beds is not None]
    guests = [r.max_guests for r in tp_rows if r.max_guests is not None]

    threshold = float(config.get("amenity_share_threshold", 0.5))
    max_count = int(config.get("common_amenities_max", 6))
    amenity_counts: dict[str, int] = {}
    for r in tp_rows:
        for a in (r.amenities or []):
            if isinstance(a, str):
                amenity_counts[a] = amenity_counts.get(a, 0) + 1
    common = sorted(
        ((name, count / n) for name, count in amenity_counts.items() if count / n >= threshold),
        key=lambda x: (-x[1], x[0]),
    )[:max_count]

    return TopPerformerProfile(
        count=n,
        superhost_share=superhost_count / n,
        price_median=Decimal(median(prices)).quantize(Decimal("1")) if prices else None,
        price_min=min(prices) if prices else None,
        price_max=max(prices) if prices else None,
        median_bedrooms=int(median(bedrooms)) if bedrooms else None,
        median_beds=int(median(beds)) if beds else None,
        median_max_guests=int(median(guests)) if guests else None,
        common_amenities=common,
    )


def _underserved_rationale(n: int, score: float, adr, is_thin: bool) -> str:
    """Kurze Prosa-Begründung pro Chancen-Segment: Demand-Signal in Worten.

    Zwei Varianten — eine für belastbare, eine für thin Cells. Bezieht den
    Median-ADR ein, sofern vorhanden.
    """
    score_int = int(round(score))
    n_label = f"{n} Wettbewerber" if n != 1 else "1 Wettbewerber"
    adr_part = f", Median €{int(adr)}/Nacht" if adr is not None else ""
    if is_thin:
        return (
            f"Nur {n_label}, aber im Schnitt {score_int} Bewertungen je "
            f"Apartment — sieht stark unterversorgt aus{adr_part}. Stichprobe "
            f"zu klein für eine belastbare Aussage."
        )
    return (
        f"{n_label}, je Ø {score_int} Bewertungen — solides Demand-Signal"
        f"{adr_part}."
    )


def _rank_underserved_segments(
    cells: dict,
    best_cell: tuple | None,
    max_count: int,
) -> list[UnderservedSegment]:
    """Rangiert alle Cells mit Score absteigend nach Bew./Apt (= Nachfrage je
    Wettbewerber), exkludiert die Best-Cell und gibt die Top ``max_count``
    zurück. Thin-Zellen sind eingeschlossen (Briefing §8.2: 'Hebt die
    Segmente hervor, in denen Nachfrage und Angebot am stärksten auseinander-
    laufen' — gerade dünn besetzte Cells können stark unterversorgt sein).
    Ihre ``is_thin``-Markierung steuert in der UI das Spekulativ-Label.
    """
    eligible = [
        (key, cell) for key, cell in cells.items()
        if cell.score is not None and key != best_cell
    ]
    eligible.sort(key=lambda kv: (-kv[1].score, kv[0][0], kv[0][1]))
    return [
        UnderservedSegment(
            size_class=key[0],
            luxury_class=key[1],
            n=cell.n,
            adr=cell.adr,
            score=cell.score,
            is_thin=cell.is_thin,
            rationale=_underserved_rationale(cell.n, cell.score, cell.adr, cell.is_thin),
        )
        for key, cell in eligible[:max_count]
    ]


def _pick_top_performers(
    rows_by_cell: dict[tuple[str, str], list[ListingRow]],
    per_segment: int,
) -> list[TopPerformer]:
    """Top-N je Größenklasse, sortiert nach review_count desc, dann rating desc."""
    by_size: dict[str, list[tuple[ListingRow, str]]] = {s: [] for s in SIZE_CLASSES}
    for (size, lux), group in rows_by_cell.items():
        for r in group:
            by_size[size].append((r, lux))

    result: list[TopPerformer] = []
    for size in SIZE_CLASSES:
        candidates = by_size[size]
        candidates.sort(
            key=lambda rt: (-rt[0].review_count, -(rt[0].rating or 0.0), rt[0].airbnb_id)
        )
        for r, lux in candidates[:per_segment]:
            result.append(
                TopPerformer(
                    airbnb_id=r.airbnb_id,
                    title=r.title,
                    url=r.url,
                    size_class=size,
                    luxury_class=lux,
                    review_count=r.review_count,
                    rating=r.rating,
                )
            )
    return result


def build_segment_matrix(
    rows: list[ListingRow],
    *,
    config: dict | None,
    radius_km: float | None,
    center_label: str | None,
    crawl_run_id: int | None,
) -> SegmentMatrix:
    """Reine Aggregation der Segment-Matrix für genau einen Umkreis.

    - Verteilt jeden ListingRow auf eine (size_class, luxury_class)-Zelle.
    - `luxury_class` wird aus price_percentile (Umkreis-Kohorte) × amenity_score
      berechnet (Spec §8: immer innerhalb des gewählten Umkreises).
    - Zellen unter cfg['min_sample'] gelten als 'dünn' und scheiden aus der
      Best-Cell-Wahl aus.
    - `heat` 0-4 skaliert relativ zum besten nicht-dünnen Score.
    """
    cfg = _merge_config(config)
    cells = _empty_grid()
    cohort = [r.price for r in rows if r.price is not None]

    # Listings auf Zellen verteilen.
    cell_rows: dict[tuple[str, str], list[ListingRow]] = {}
    listing_count = 0
    for r in rows:
        if r.size_class not in SIZE_CLASSES:
            continue
        if r.price is None:
            continue
        pct = _price_percentile(r.price, cohort)
        if pct is None:
            continue
        lux = _luxury_class(pct, r.amenity_score, cfg)
        if lux not in LUXURY_CLASSES:
            continue
        cell_rows.setdefault((r.size_class, lux), []).append(r)
        listing_count += 1

    # Pro Zelle: N, R, Score, ADR, is_thin.
    min_sample = int(cfg["min_sample"])
    for key, group in cell_rows.items():
        cell = cells[key]
        cell.n = len(group)
        cell.review_sum = sum(r.review_count for r in group)
        cell.score = cell.review_sum / cell.n if cell.n else None
        prices = [r.price for r in group if r.price is not None]
        cell.adr = (
            Decimal(median(prices)).quantize(Decimal("1")) if prices else None
        )
        cell.is_thin = cell.n < min_sample

    # Best-Cell: höchster Score unter den nicht-dünnen Zellen.
    eligible = [
        (key, cell) for key, cell in cells.items()
        if not cell.is_thin and cell.score is not None
    ]
    best_cell = max(eligible, key=lambda kv: kv[1].score, default=(None, None))[0]

    # Heat 0-4 relativ zum besten nicht-dünnen Score.
    max_score = max((c.score for _, c in eligible), default=None)
    for cell in cells.values():
        if cell.is_thin or cell.score is None or not max_score:
            cell.heat = 0
        else:
            cell.heat = max(1, min(4, round(cell.score / max_score * 4)))

    matrix = SegmentMatrix(
        radius_km=radius_km,
        center_label=center_label,
        crawl_run_id=crawl_run_id,
        cells=cells,
        best_cell=best_cell,
        listing_count=listing_count,
        review_rate=float(cfg["review_rate"]),
        min_sample=min_sample,
    )
    matrix.recommendation = _build_recommendation(matrix)
    matrix.top_performers = _pick_top_performers(
        cell_rows, int(cfg["top_performers_per_segment"])
    )
    # Profil aggregiert über die Listings IM EMPFOHLENEN SEGMENT (Best-Cell) —
    # damit das Profil konsistent zur Hero-Empfehlung ist. Cross-size Top-N
    # bleiben für die Top-Apartments-Liste reserviert (matrix.top_performers).
    best_cell_rows = cell_rows.get(matrix.best_cell, []) if matrix.best_cell else []
    matrix.top_performer_profile = _compute_top_performer_profile(best_cell_rows, cfg)
    # Unterversorgungs-Sicht: weitere Chancen-Segmente neben der Best-Cell.
    matrix.underserved = _rank_underserved_segments(
        cells, matrix.best_cell, int(cfg.get("underserved_max", 3))
    )
    return matrix


def latest_completed_run(
    session: Session, search_config: SearchConfig
) -> CrawlRun | None:
    """Letzter erfolgreich abgeschlossener CrawlRun einer SearchConfig (oder None)."""
    stmt = (
        select(CrawlRun)
        .where(CrawlRun.search_config_id == search_config.id)
        .where(CrawlRun.status == "completed")
        .order_by(CrawlRun.started_at.desc(), CrawlRun.id.desc())
        .limit(1)
    )
    return session.execute(stmt).scalar_one_or_none()


def compute_segment_matrix(
    session: Session,
    search_config: SearchConfig,
    radius_km: float,
    crawl_run: CrawlRun,
) -> SegmentMatrix:
    """Lädt alle Listings+Snapshots des Runs und filtert per Distanz zum
    Zielobjekt auf den gewählten Umkreis, dann ruft den reinen Builder."""
    # SessionLocal nutzt autoflush=False — Pending Writes der gleichen
    # Unit-of-Work müssen vor dem SELECT explizit sichtbar gemacht werden,
    # damit Tests/Routen, die direkt vor der Insight schreiben, das Ergebnis
    # auch lesen können.
    session.flush()
    stmt = (
        select(Listing, Snapshot)
        .join(Snapshot, Snapshot.listing_id == Listing.id)
        .where(Snapshot.crawl_run_id == crawl_run.id)
        .where(Listing.city_slug == search_config.city_slug)
    )
    center_lat = search_config.center_lat
    center_lng = search_config.center_lng
    rows: list[ListingRow] = []
    if center_lat is not None and center_lng is not None:
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
    return build_segment_matrix(
        rows,
        config=search_config.classification_config or {},
        radius_km=radius_km,
        center_label=search_config.center_label,
        crawl_run_id=crawl_run.id,
    )
