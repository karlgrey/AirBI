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

from airbi.classification.price import price_tier as _price_tier

# Reihenfolge bestimmt die Render-Reihenfolge in der Matrix.
SIZE_CLASSES: list[str] = ["Studio", "1BR", "2BR", "3BR+"]
PRICE_TIERS: list[str] = ["Budget", "Mid", "Premium", "Luxury"]

# Defaults für die Insight-spezifischen Knöpfe in SearchConfig.classification_config.
DEFAULT_INSIGHT_CONFIG: dict = {
    "min_sample": 3,        # Zellen mit weniger Listings gelten als "zu dünn".
    "review_rate": 0.40,    # Anteil bewertender Gäste (Briefing §3, ~30-50 %).
    "top_performers_per_segment": 2,
}


@dataclass
class ListingRow:
    """Ein Listing + sein Snapshot aus einem CrawlRun, bereits einem Bezirk
    zugeordnet. Der reine Builder konsumiert nur diese Records."""

    airbnb_id: str
    title: str | None
    url: str | None
    size_class: str            # aus airbi.classification.size.size_class
    price: Decimal | None      # Nacht-Preis aus dem Snapshot
    review_count: int
    rating: float | None


@dataclass
class Cell:
    """Eine Zelle der Matrix (eine Kombination Größe × price_tier)."""

    size_class: str
    price_tier: str
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
    price_tier: str
    review_count: int
    rating: float | None


@dataclass
class SegmentMatrix:
    """Vollständiges Insight-Ergebnis für genau einen Bezirk + einen CrawlRun."""

    district_slug: str
    crawl_run_id: int | None
    size_classes: list[str] = field(default_factory=lambda: list(SIZE_CLASSES))
    price_tiers: list[str] = field(default_factory=lambda: list(PRICE_TIERS))
    cells: dict[tuple[str, str], Cell] = field(default_factory=dict)
    best_cell: tuple[str, str] | None = None
    recommendation: str = ""
    top_performers: list[TopPerformer] = field(default_factory=list)
    listing_count: int = 0
    review_rate: float = DEFAULT_INSIGHT_CONFIG["review_rate"]
    min_sample: int = DEFAULT_INSIGHT_CONFIG["min_sample"]

    def cell(self, size_class: str, price_tier: str) -> Cell:
        """Template-freundlicher Zugriff (Jinja kann keine Tuple-Subscripts)."""
        return self.cells[(size_class, price_tier)]


def _merge_config(config: dict | None) -> dict:
    return {**DEFAULT_INSIGHT_CONFIG, **(config or {})}


def _empty_grid() -> dict[tuple[str, str], Cell]:
    return {
        (size, tier): Cell(size_class=size, price_tier=tier)
        for size in SIZE_CLASSES
        for tier in PRICE_TIERS
    }


def _district_label(slug: str) -> str:
    """Hübscher Anzeigename für einen Bezirks-Slug ('marvila' -> 'Marvila')."""
    return slug.replace("-", " ").replace("_", " ").title()


def _build_recommendation(matrix: SegmentMatrix) -> str:
    """Formuliert den Empfehlungssatz aus der gefüllten Matrix."""
    label = _district_label(matrix.district_slug)
    if matrix.best_cell is None:
        return (
            f"Für {label} liefert dieser Crawl noch keine Zelle mit mindestens "
            f"{matrix.min_sample} vergleichbaren Objekten — die Datenbasis ist "
            f"für eine belastbare Empfehlung zu dünn."
        )
    size, tier = matrix.best_cell
    cell = matrix.cell(size, tier)
    score = cell.score or 0.0
    adr = int(cell.adr) if cell.adr is not None else 0
    rate_pct = int(round(matrix.review_rate * 100))
    return (
        f"Für {label} ist {size}-{tier} am attraktivsten — Ø {score:.0f} "
        f"Reviews je Listing bei {cell.n} Wettbewerber-Listings, "
        f"Median-ADR €{adr}. Nachfrage ist ein Proxy aus Review-Count "
        f"(~{rate_pct}% der Gäste bewerten), keine gemessene Auslastung."
    )


def _pick_top_performers(
    rows_by_cell: dict[tuple[str, str], list[ListingRow]],
    per_segment: int,
) -> list[TopPerformer]:
    """Top-N je Größenklasse, sortiert nach review_count desc, dann rating desc."""
    by_size: dict[str, list[tuple[ListingRow, str]]] = {s: [] for s in SIZE_CLASSES}
    for (size, tier), group in rows_by_cell.items():
        for r in group:
            by_size[size].append((r, tier))

    result: list[TopPerformer] = []
    for size in SIZE_CLASSES:
        candidates = by_size[size]
        candidates.sort(
            key=lambda rt: (-rt[0].review_count, -(rt[0].rating or 0.0), rt[0].airbnb_id)
        )
        for r, tier in candidates[:per_segment]:
            result.append(
                TopPerformer(
                    airbnb_id=r.airbnb_id,
                    title=r.title,
                    url=r.url,
                    size_class=size,
                    price_tier=tier,
                    review_count=r.review_count,
                    rating=r.rating,
                )
            )
    return result


def build_segment_matrix(
    rows: list[ListingRow],
    *,
    config: dict | None,
    district_slug: str,
    crawl_run_id: int | None,
) -> SegmentMatrix:
    """Reine Aggregation der Segment-Matrix für genau einen Bezirk.

    - Verteilt jeden ListingRow auf eine (size_class, price_tier)-Zelle.
    - `price_tier` wird aus dem Preis-Kohort *dieser* rows berechnet (Spec
      §5.5/§8: immer innerhalb des Bezirks).
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
        tier = _price_tier(r.price, cohort, cfg)
        if tier not in PRICE_TIERS:
            continue
        cell_rows.setdefault((r.size_class, tier), []).append(r)
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
        district_slug=district_slug,
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
    return matrix
