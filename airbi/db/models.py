from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    JSON,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from airbi.db.session import Base


class SearchConfig(Base):
    """Benannter, gespeicherter Suchkontext (Spec §5.1)."""

    __tablename__ = "search_config"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), unique=True)
    city_slug: Mapped[str] = mapped_column(String(80), default="lisboa")
    district_slugs: Mapped[list] = mapped_column(JSON, default=list)
    property_filter: Mapped[dict] = mapped_column(JSON, default=dict)
    classification_config: Mapped[dict] = mapped_column(JSON, default=dict)
    crawl_schedule: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    crawl_runs: Mapped[list["CrawlRun"]] = relationship(back_populates="search_config")


class CrawlRun(Base):
    """Ein Scraper-Lauf einer SearchConfig (Spec §5.2)."""

    __tablename__ = "crawl_run"

    id: Mapped[int] = mapped_column(primary_key=True)
    search_config_id: Mapped[int] = mapped_column(ForeignKey("search_config.id"))
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    status: Mapped[str] = mapped_column(String(20), default="running")
    listings_seen: Mapped[int] = mapped_column(Integer, default=0)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)

    search_config: Mapped["SearchConfig"] = relationship(back_populates="crawl_runs")
    snapshots: Mapped[list["Snapshot"]] = relationship(back_populates="crawl_run")


class Listing(Base):
    """Relativ statische Stammdaten eines Airbnb-Objekts (Spec §5.3)."""

    __tablename__ = "listing"
    __table_args__ = (
        UniqueConstraint("city_slug", "airbnb_id", name="uq_listing_city_airbnb"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    airbnb_id: Mapped[str] = mapped_column(String(40))
    city_slug: Mapped[str] = mapped_column(String(80), default="lisboa")
    district_slug: Mapped[str | None] = mapped_column(String(80), nullable=True)
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    lat: Mapped[float] = mapped_column(Float)
    lng: Mapped[float] = mapped_column(Float)
    property_type: Mapped[str | None] = mapped_column(String(120), nullable=True)
    bedrooms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    beds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    bathrooms: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_guests: Mapped[int | None] = mapped_column(Integer, nullable=True)
    host_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    is_superhost: Mapped[bool] = mapped_column(Boolean, default=False)
    size_class: Mapped[str | None] = mapped_column(String(20), nullable=True)
    amenity_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Reserviert für Phase 2 / Detail-Crawl (Spec §5.3)
    license_number: Mapped[str | None] = mapped_column(String(80), nullable=True)
    al_status: Mapped[str | None] = mapped_column(String(40), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    amenities: Mapped[list | None] = mapped_column(JSON, nullable=True)

    snapshots: Mapped[list["Snapshot"]] = relationship(back_populates="listing")


class Snapshot(Base):
    """Zeitreihen-Eintrag pro Listing und CrawlRun (Spec §5.4)."""

    __tablename__ = "snapshot"

    id: Mapped[int] = mapped_column(primary_key=True)
    listing_id: Mapped[int] = mapped_column(ForeignKey("listing.id"))
    crawl_run_id: Mapped[int] = mapped_column(ForeignKey("crawl_run.id"))
    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    price: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    fees: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    review_count: Mapped[int] = mapped_column(Integer, default=0)
    rating: Mapped[float | None] = mapped_column(Float, nullable=True)
    search_position: Mapped[int | None] = mapped_column(Integer, nullable=True)

    listing: Mapped["Listing"] = relationship(back_populates="snapshots")
    crawl_run: Mapped["CrawlRun"] = relationship(back_populates="snapshots")
