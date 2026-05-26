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
