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
