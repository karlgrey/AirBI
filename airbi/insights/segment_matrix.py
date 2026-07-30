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
from airbi.insights.velocity import attach_velocities

# Reihenfolge bestimmt die Render-Reihenfolge in der Matrix.
SIZE_CLASSES: list[str] = ["Studio", "1BR", "2BR", "3BR+"]

# Defaults für die Insight-spezifischen Knöpfe in SearchConfig.classification_config.
DEFAULT_INSIGHT_CONFIG: dict = {
    "min_sample": 3,        # Zellen mit weniger Listings gelten als "zu dünn".
    "review_rate": 0.40,    # Anteil bewertender Gäste (Briefing §3, ~30-50 %).
    "top_performers_count": 5,   # Anzahl Top-Apartments im empfohlenen Segment.
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
    # Velocity-Anbindung (Teilprojekt 3): listing_id ist die interne DB-PK,
    # nur für den Velocity-Lookup gebraucht (compute_segment_matrix füllt
    # sie; reine Fixtures/Tests lassen sie None). weekly_velocity wird von
    # airbi.insights.velocity.attach_velocities in-place gesetzt.
    listing_id: int | None = None
    weekly_velocity: float | None = None


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
    # Velocity (Teilprojekt 3): Ø wöchentliche Review-Zunahme der Listings in
    # der Zelle, die ein belastbares Signal haben (siehe airbi.insights.velocity).
    velocity: float | None = None
    velocity_n: int = 0                # wie viele Listings der Zelle liefern ein Signal


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
class MapListing:
    """Pro-Listing-Datenstruktur für die räumliche Sicht (Karte).
    Enthält alle Felder, die Marker-Tooltip + Detail-Panel füllen."""

    airbnb_id: str
    lat: float
    lng: float
    title: str | None
    url: str | None
    size_class: str
    luxury_class: str
    price: "Decimal | None"
    reviews: int
    rating: float | None
    bedrooms: int | None
    beds: int | None
    max_guests: int | None
    is_superhost: bool
    amenities: list           # auf max. 10 gekappt
    description: str | None   # auf 300 Zeichen gekappt
    distance_km: float
    amenity_score: float | None
    is_best: bool


@dataclass
class GapCandidate:
    """Ein 'weißer Fleck' in der Matrix: Cell ohne (oder kaum) Angebot, deren
    Nachbar-Cells aber starke Demand zeigen — Hinweis auf Pionier-Position
    (statt 'join the winners' der Best-Cell-Empfehlung)."""

    size_class: str
    luxury_class: str
    n: int                                  # eigene Cell-Anzahl (meist 0 oder dünn)
    adjacency_score: float                  # Mittelwert der Nachbar-Scores
    strongest_neighbor_size_class: str      # rohe Größenklasse des stärksten Nachbarn
    strongest_neighbor_luxury_class: str    # rohe Luxusklasse des stärksten Nachbarn
    strongest_neighbor_label: str           # z.B. "1 Schlafzimmer · Luxury"
    strongest_neighbor_n: int
    strongest_neighbor_score: float
    rationale: str                          # vollständige Begründung


@dataclass
class UnderservedSegment:
    """Eine 'Chancen-Zelle' aus der Matrix: hohe Nachfrage je Wettbewerber
    (Brief §8.2). Wird in der Ranking-Liste unter dem Brief gezeigt — mit
    Vergleich zur Empfehlung, Profil und konkretem Top-Vertreter, damit die
    Investment-Argumentation belastbar wird."""

    size_class: str
    luxury_class: str
    n: int
    adr: "Decimal | None"
    score: float
    is_thin: bool
    rationale: str = ""                                # Kurze Prosa-Conclusion.
    # NEU: Argumentations-Bausteine
    vs_best_n: float | None = None                     # Relative Delta vs. Best-Cell (z.B. -0.68 = -68%).
    vs_best_adr: float | None = None
    vs_best_score: float | None = None
    profile: "TopPerformerProfile | None" = None       # Wie best_cell-Profil, aber auf diese Cell bezogen.
    top_exemplar: "TopPerformer | None" = None         # Stärkster konkreter Vertreter der Cell.


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
    gap_cell: GapCandidate | None = None             # Pionier-Alternative zur Best-Cell
    map_listings: list[MapListing] = field(default_factory=list)
    map_data: dict = field(default_factory=dict)   # JSON-fertig fürs Template
    luxury_price_threshold: float | None = None    # €/Nacht ab dem Top-Quartil
    listing_count: int = 0
    review_rate: float = DEFAULT_INSIGHT_CONFIG["review_rate"]
    min_sample: int = DEFAULT_INSIGHT_CONFIG["min_sample"]
    # Teil-3-Hook, jetzt real berechnet (statt der Konstante in memo.py):
    # True, wenn die Best-Cell genug Listings mit belastbarem Velocity-Signal
    # hat (>= min_sample). compute_memo liest dies statt VELOCITY_AVAILABLE.
    velocity_available: bool = False

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


def _size_klartext(size: str) -> str:
    """Klartext-Größen-Label fürs UI/Rationale."""
    return {
        "Studio": "Studio",
        "1BR": "1 Schlafzimmer",
        "2BR": "2 Schlafzimmer",
        "3BR+": "3+ Schlafzimmer",
    }.get(size, size)


def _find_gap_cell(cells: dict, min_sample: int) -> GapCandidate | None:
    """Sucht den stärksten 'weißen Fleck' in der Matrix.

    Eine Cell ist Gap-Kandidat, wenn ``n < min_sample`` (kein/kaum Angebot).
    Adjazenz-Score = Mittelwert der Scores ihrer direkten Nachbarn (gleiche
    Größe ± 1 Luxusklasse oder gleiche Luxusklasse ± 1 Größe). Ist dieser
    über dem Median aller populierten Cell-Scores im Lauf, lohnt sich die
    Cell als Pionier-Position.

    Gibt nur den TOP-1 Kandidaten zurück oder ``None``, wenn kein qualifi-
    zierter Gap gefunden wurde.
    """
    populated_scores = [
        c.score for c in cells.values() if c.n > 0 and c.score is not None
    ]
    if not populated_scores:
        return None
    threshold = sorted(populated_scores)[len(populated_scores) // 2]

    size_idx = {s: i for i, s in enumerate(SIZE_CLASSES)}
    lux_idx = {l: i for i, l in enumerate(LUXURY_CLASSES)}
    candidates: list[tuple[float, str, str, int, tuple]] = []

    for (size, lux), cell in cells.items():
        if cell.n >= min_sample:
            continue   # genug Angebot, keine Lücke
        si, li = size_idx[size], lux_idx[lux]
        neighbors: list[tuple[str, str, int, float]] = []
        for ds, dl in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            ni, nj = si + ds, li + dl
            if 0 <= ni < len(SIZE_CLASSES) and 0 <= nj < len(LUXURY_CLASSES):
                ncell = cells.get((SIZE_CLASSES[ni], LUXURY_CLASSES[nj]))
                if ncell and ncell.n > 0 and ncell.score is not None:
                    neighbors.append(
                        (SIZE_CLASSES[ni], LUXURY_CLASSES[nj], ncell.n, ncell.score)
                    )
        if not neighbors:
            continue
        adj_score = sum(n[3] for n in neighbors) / len(neighbors)
        strongest = max(neighbors, key=lambda n: n[3])
        candidates.append((adj_score, size, lux, cell.n, strongest))

    candidates.sort(key=lambda c: -c[0])
    for adj_score, size, lux, own_n, strongest in candidates:
        if adj_score < threshold:
            break
        s_label = f"{_size_klartext(strongest[0])} · {strongest[1]}"
        rationale = (
            f"Im Segment selbst gibt es bislang {own_n} Anbieter, direkt "
            f"benachbarte Klassen zeigen aber starke Nachfrage — das benachbarte "
            f"Segment {s_label} kommt auf {int(round(strongest[3]))} Bewertungen "
            f"je Apartment bei {strongest[2]} Anbietern. Wer hier zuerst anbietet, "
            f"startet ohne direkten Wettbewerb."
        )
        return GapCandidate(
            size_class=size,
            luxury_class=lux,
            n=own_n,
            adjacency_score=adj_score,
            strongest_neighbor_size_class=strongest[0],
            strongest_neighbor_luxury_class=strongest[1],
            strongest_neighbor_label=s_label,
            strongest_neighbor_n=strongest[2],
            strongest_neighbor_score=strongest[3],
            rationale=rationale,
        )
    return None



def _rank_underserved_segments(
    cells: dict,
    cell_rows: dict,
    best_cell: tuple | None,
    max_count: int,
    config: dict,
) -> list[UnderservedSegment]:
    """Rangiert alle Cells mit Score absteigend nach Bew./Apt (= Nachfrage je
    Wettbewerber), exkludiert die Best-Cell und gibt die Top ``max_count``
    zurück, jeweils angereichert mit:

    - Vergleich zur Best-Cell (relative Delta-Werte für n/adr/score)
    - ``TopPerformerProfile`` der Cell (gleiche Aggregations-Logik wie
      Best-Cell-Profil)
    - Stärkster Vertreter der Cell als ``TopPerformer`` (Top nach review_count).

    Thin-Cells sind eingeschlossen (Briefing §8.2); ``is_thin`` steuert in
    der UI das Spekulativ-Label.
    """
    eligible = [
        (key, cell) for key, cell in cells.items()
        if cell.score is not None and key != best_cell
    ]
    eligible.sort(key=lambda kv: (-kv[1].score, kv[0][0], kv[0][1]))

    # Best-Cell-Referenzwerte für die relative Delta-Berechnung.
    best_n = cells[best_cell].n if best_cell and best_cell in cells else None
    best_adr_raw = cells[best_cell].adr if best_cell and best_cell in cells else None
    best_adr = float(best_adr_raw) if best_adr_raw is not None else None
    best_score = cells[best_cell].score if best_cell and best_cell in cells else None

    result: list[UnderservedSegment] = []
    for key, cell in eligible[:max_count]:
        rows = cell_rows.get(key, [])
        profile = _compute_top_performer_profile(rows, config)
        top_exemplar = None
        if rows:
            top = sorted(
                rows,
                key=lambda r: (-r.review_count, -(r.rating or 0.0), r.airbnb_id),
            )[0]
            top_exemplar = TopPerformer(
                airbnb_id=top.airbnb_id,
                title=top.title,
                url=top.url,
                size_class=top.size_class,
                luxury_class=key[1],
                review_count=top.review_count,
                rating=top.rating,
            )
        vs_n = (cell.n - best_n) / best_n if best_n else None
        vs_adr = (
            (float(cell.adr) - best_adr) / best_adr
            if (best_adr and cell.adr is not None) else None
        )
        vs_score = (cell.score - best_score) / best_score if best_score else None

        result.append(UnderservedSegment(
            size_class=key[0],
            luxury_class=key[1],
            n=cell.n,
            adr=cell.adr,
            score=cell.score,
            is_thin=cell.is_thin,
            rationale=_underserved_rationale(cell.n, cell.score, cell.adr, cell.is_thin),
            vs_best_n=vs_n,
            vs_best_adr=vs_adr,
            vs_best_score=vs_score,
            profile=profile,
            top_exemplar=top_exemplar,
        ))
    return result


def _pick_top_performers(
    rows_by_cell: dict[tuple[str, str], list[ListingRow]],
    best_cell: tuple[str, str] | None,
    count: int,
) -> list[TopPerformer]:
    """Top-N Apartments **aus dem empfohlenen Segment** (Best-Cell), sortiert
    nach review_count desc, dann rating desc — als konkrete Beispiele für die
    Hero-Empfehlung.

    Fällt zurück auf die Top-N im aktiven Umkreis insgesamt (cross-size), wenn
    keine Best-Cell existiert (thin data).
    """
    candidates: list[tuple[ListingRow, str]] = []
    if best_cell is not None:
        for r in rows_by_cell.get(best_cell, []):
            candidates.append((r, best_cell[1]))
    else:
        for (_, lux), group in rows_by_cell.items():
            for r in group:
                candidates.append((r, lux))

    candidates.sort(
        key=lambda rt: (-rt[0].review_count, -(rt[0].rating or 0.0), rt[0].airbnb_id)
    )
    result: list[TopPerformer] = []
    for r, lux in candidates[:count]:
        result.append(
            TopPerformer(
                airbnb_id=r.airbnb_id,
                title=r.title,
                url=r.url,
                size_class=r.size_class,
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
        velocities = [r.weekly_velocity for r in group if r.weekly_velocity is not None]
        cell.velocity_n = len(velocities)
        cell.velocity = sum(velocities) / len(velocities) if velocities else None

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
    matrix.velocity_available = bool(
        best_cell is not None and cells[best_cell].velocity_n >= min_sample
    )
    matrix.recommendation = _build_recommendation(matrix)
    matrix.top_performers = _pick_top_performers(
        cell_rows, matrix.best_cell, int(cfg.get("top_performers_count", 5))
    )
    # Profil aggregiert über die Listings IM EMPFOHLENEN SEGMENT (Best-Cell) —
    # damit das Profil konsistent zur Hero-Empfehlung ist. Cross-size Top-N
    # bleiben für die Top-Apartments-Liste reserviert (matrix.top_performers).
    best_cell_rows = cell_rows.get(matrix.best_cell, []) if matrix.best_cell else []
    matrix.top_performer_profile = _compute_top_performer_profile(best_cell_rows, cfg)
    # Unterversorgungs-Sicht: weitere Chancen-Segmente neben der Best-Cell.
    matrix.underserved = _rank_underserved_segments(
        cells, cell_rows, matrix.best_cell, int(cfg.get("underserved_max", 3)), cfg
    )
    # Pionier-Alternative: weiße Flecken mit starkem Nachbar-Demand-Signal.
    matrix.gap_cell = _find_gap_cell(cells, min_sample)
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
    Zielobjekt:
    - **Builder-Input**: Listings ≤ ``radius_km`` (Aktiv-Radius).
    - **Map-Pool**: Listings ≤ ``max(band_radii_km)`` (alle 10 km für die
      räumliche Sicht), `luxury_class` gegen die Aktiv-Radius-Kohorte.
    """
    # SessionLocal nutzt autoflush=False — Pending Writes der gleichen
    # Unit-of-Work müssen vor dem SELECT explizit sichtbar gemacht werden.
    session.flush()
    stmt = (
        select(Listing, Snapshot)
        .join(Snapshot, Snapshot.listing_id == Listing.id)
        .where(Snapshot.crawl_run_id == crawl_run.id)
        .where(Listing.city_slug == search_config.city_slug)
    )
    center_lat = search_config.center_lat
    center_lng = search_config.center_lng
    radii = search_config.band_radii_km or [radius_km]
    max_radius = max(radii)

    rows: list[ListingRow] = []                              # Aktiv-Radius (Builder)
    map_pool: list[tuple[Listing, Snapshot, float]] = []     # Max-Radius (Map)

    if center_lat is not None and center_lng is not None:
        for listing, snap in session.execute(stmt).all():
            if listing.lat is None or listing.lng is None:
                continue
            dist = haversine_km(center_lat, center_lng, listing.lat, listing.lng)
            if dist > max_radius:
                continue
            map_pool.append((listing, snap, dist))
            if dist <= radius_km:
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

    # Velocity (Teilprojekt 3): über die GESAMTE Snapshot-Historie der
    # betroffenen Listings, nicht nur den aktuellen Run — die Zeitreihe ist
    # der Punkt. Mutiert `rows` in-place (weekly_velocity).
    attach_velocities(session, rows)

    matrix = build_segment_matrix(
        rows,
        config=search_config.classification_config or {},
        radius_km=radius_km,
        center_label=search_config.center_label,
        crawl_run_id=crawl_run.id,
    )

    # Preis-Schwelle ans Top-Quartil (default 75. Perzentil) der Aktiv-Radius-
    # Kohorte berechnen — macht im Brief sichtbar, warum sich die Luxusklasse-
    # Zellen je nach Umkreis verschieben.
    luxury_pct = float(
        ((search_config.classification_config or {}).get("luxury_thresholds")
         or [0.25, 0.5, 0.75])[-1]
    )
    sorted_prices = sorted(float(r.price) for r in rows if r.price is not None)
    if sorted_prices:
        idx = min(int(luxury_pct * len(sorted_prices)), len(sorted_prices) - 1)
        matrix.luxury_price_threshold = sorted_prices[idx]

    # Map-Listings nachträglich aus dem Max-Radius-Pool bauen — luxury_class
    # gegen die Aktiv-Radius-Kohorte, is_best nur für Mitglieder im aktiven Radius.
    cohort_prices = [r.price for r in rows if r.price is not None]
    cls_config = search_config.classification_config or {}
    map_listings: list[MapListing] = []
    for listing, snap, dist in map_pool:
        pct = _price_percentile(snap.price, cohort_prices) if snap.price is not None else None
        lux = _luxury_class(pct, listing.amenity_score, cls_config) if pct is not None else "unclassified"
        size = listing.size_class or "unclassified"
        is_best = (
            matrix.best_cell is not None
            and (size, lux) == matrix.best_cell
            and dist <= radius_km
        )
        desc = (listing.description or "")[:300] or None
        map_listings.append(MapListing(
            airbnb_id=listing.airbnb_id,
            lat=listing.lat,
            lng=listing.lng,
            title=listing.title,
            url=listing.url,
            size_class=size,
            luxury_class=lux,
            price=snap.price,
            reviews=snap.review_count or 0,
            rating=snap.rating,
            bedrooms=listing.bedrooms,
            beds=listing.beds,
            max_guests=listing.max_guests,
            is_superhost=bool(listing.is_superhost),
            amenities=(listing.amenities or [])[:10],
            description=desc,
            distance_km=round(dist, 2),
            amenity_score=round(listing.amenity_score, 2) if listing.amenity_score is not None else None,
            is_best=is_best,
        ))
    matrix.map_listings = map_listings
    # JSON-fertige Repräsentation für das Template (Decimal -> float, etc.).
    matrix.map_data = {
        "center": {
            "lat": float(center_lat) if center_lat is not None else None,
            "lng": float(center_lng) if center_lng is not None else None,
            "label": search_config.center_label or "Zielobjekt",
        },
        "radii_km": list(radii),
        "active_radius_km": float(radius_km),
        "listings": [
            {
                "id": m.airbnb_id,
                "lat": m.lat,
                "lng": m.lng,
                "title": m.title,
                "url": m.url,
                "size_class": m.size_class,
                "luxury_class": m.luxury_class,
                "price": float(m.price) if m.price is not None else None,
                "reviews": m.reviews,
                "rating": m.rating,
                "bedrooms": m.bedrooms,
                "beds": m.beds,
                "max_guests": m.max_guests,
                "is_superhost": m.is_superhost,
                "amenities": m.amenities,
                "description": m.description,
                "distance_km": m.distance_km,
                "amenity_score": m.amenity_score,
                "is_best": m.is_best,
            }
            for m in map_listings
        ],
    }
    return matrix
