from datetime import datetime
from decimal import Decimal

from airbi.db.models import CrawlRun, Listing, SearchConfig, Snapshot


def test_search_config_persists_with_defaults(db_session):
    cfg = SearchConfig(name="Marvila Slice 1", district_slugs=["marvila", "beato"])
    db_session.add(cfg)
    db_session.flush()

    assert cfg.id is not None
    assert cfg.city_slug == "lisboa"
    assert cfg.district_slugs == ["marvila", "beato"]


def test_crawl_run_links_to_search_config(db_session):
    cfg = SearchConfig(name="Marvila Slice 1")
    run = CrawlRun(search_config=cfg, status="running")
    db_session.add(run)
    db_session.flush()

    assert run.id is not None
    assert run.status == "running"
    assert run.listings_seen == 0
    assert run.search_config.name == "Marvila Slice 1"


def test_listing_unique_per_city_and_airbnb_id(db_session):
    from sqlalchemy.exc import IntegrityError

    db_session.add(Listing(airbnb_id="123", city_slug="lisboa", lat=38.74, lng=-9.10))
    db_session.flush()
    db_session.add(Listing(airbnb_id="123", city_slug="lisboa", lat=38.75, lng=-9.11))
    try:
        db_session.flush()
        assert False, "erwartete IntegrityError wegen Unique-Constraint"
    except IntegrityError:
        pass


def test_snapshot_links_listing_and_crawl_run(db_session):
    cfg = SearchConfig(name="Marvila Slice 1")
    run = CrawlRun(search_config=cfg, status="running")
    listing = Listing(airbnb_id="999", city_slug="lisboa", lat=38.74, lng=-9.10)
    snap = Snapshot(
        listing=listing,
        crawl_run=run,
        captured_at=datetime(2026, 5, 21, 12, 0, 0),
        price=Decimal("120.00"),
        review_count=42,
        rating=4.8,
    )
    db_session.add(snap)
    db_session.flush()

    assert snap.id is not None
    assert snap.price == Decimal("120.00")
    assert snap.review_count == 42
    assert snap.listing.airbnb_id == "999"


def test_listing_stores_amenity_score_and_amenities(db_session):
    from airbi.db.models import Listing
    listing = Listing(
        airbnb_id="AS1", city_slug="lisboa", lat=38.74, lng=-9.10,
        amenity_score=0.73, amenities=["River view", "Pool"],
        description="Tolle Aussicht",
    )
    db_session.add(listing)
    db_session.flush()
    got = db_session.query(Listing).filter_by(airbnb_id="AS1").one()
    assert got.amenity_score == 0.73
    assert got.amenities == ["River view", "Pool"]
    assert got.description == "Tolle Aussicht"
