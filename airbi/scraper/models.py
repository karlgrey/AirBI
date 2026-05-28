from dataclasses import dataclass
from decimal import Decimal


@dataclass
class ParsedListing:
    """Ergebnis des StaysSearch-Parsers für ein einzelnes Listing.

    Enthält sowohl relativ statische Stammdaten (werden zu Listing-Feldern)
    als auch Momentaufnahme-Werte (werden zu Snapshot-Feldern). Der
    Crawl-Orchestrator teilt das beim Schreiben auf die beiden Tabellen auf."""

    airbnb_id: str
    title: str | None
    url: str | None
    lat: float | None
    lng: float | None
    property_type: str | None
    bedrooms: int | None
    beds: int | None
    bathrooms: float | None
    max_guests: int | None
    host_name: str | None
    is_superhost: bool
    price: Decimal | None
    fees: Decimal | None
    review_count: int
    rating: float | None
    search_position: int | None


@dataclass
class ListingDetail:
    """Aus der Airbnb-Detailseite extrahierte Daten (Detail-Crawl)."""

    bedrooms: int | None
    beds: int | None
    bathrooms: float | None
    max_guests: int | None
    amenities: list[str] | None = None
    description: str | None = None
