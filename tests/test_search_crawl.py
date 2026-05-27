from decimal import Decimal

from airbi.db.models import CrawlRun, Listing, SearchConfig, Snapshot
from airbi.geo.districts import load_districts
from airbi.scraper.models import ListingDetail, ParsedListing
from airbi.scraper.search_crawl import (
    bounding_box_for,
    is_entire_home,
    merge_detail,
    persist_results,
)


def _parsed(airbnb_id, lat, lng, property_type="Apartment", review_count=10, title="T"):
    return ParsedListing(
        airbnb_id=airbnb_id, title=title, url=f"u/{airbnb_id}", lat=lat, lng=lng,
        property_type=property_type, bedrooms=None, beds=None, bathrooms=None,
        max_guests=None, host_name=None, is_superhost=False,
        price=Decimal("100.00"), fees=None, review_count=review_count,
        rating=4.5, search_position=1,
    )


def test_bounding_box_covers_all_district_polygons():
    districts = load_districts()
    sw_lat, sw_lng, ne_lat, ne_lng = bounding_box_for(districts, margin=0.0)
    assert sw_lat <= 38.7390 <= ne_lat
    assert sw_lng <= -9.1044 <= ne_lng
    assert ne_lat > sw_lat and ne_lng > sw_lng


def test_is_entire_home_accepts_apartments_rejects_rooms():
    assert is_entire_home(_parsed("1", 38.74, -9.10, property_type="Apartment"))
    assert is_entire_home(_parsed("2", 38.74, -9.10, property_type="Loft"))
    assert not is_entire_home(_parsed("3", 38.74, -9.10, property_type="Room"))
    assert not is_entire_home(_parsed("4", 38.74, -9.10, property_type="Shared room"))


def test_is_entire_home_rejects_guesthouse_with_private_room_title():
    """Plan-2-Befund: Airbnb klassifiziert manche Privatzimmer-Vermietungen
    als property_type='Guesthouse'. Der Title verrät die Tatsache ('Private
    Room with AC ...'). Property-Type-Filter allein reicht nicht."""
    assert not is_entire_home(_parsed(
        "X", 38.74, -9.10,
        property_type="Guesthouse",
        title="Private Room with AC & Self Check-in – Lisbon",
    ))
    # Auch 'shared room' im Titel filtert
    assert not is_entire_home(_parsed(
        "Y", 38.74, -9.10,
        property_type="Bed and breakfast",
        title="Cozy shared room near the center",
    ))


def test_is_entire_home_allows_apartment_with_unrelated_title():
    """Die Title-Heuristik darf normale Apartment-Titel nicht filtern."""
    assert is_entire_home(_parsed(
        "Z", 38.74, -9.10,
        property_type="Apartment",
        title="Bright Lisbon Riverside Cozy Apartment",
    ))
    # 'bedroom' im Titel ist KEIN Privatzimmer-Signal
    assert is_entire_home(_parsed(
        "W", 38.74, -9.10,
        property_type="Apartment",
        title="Lovely Loft - Master Bedroom Faces River",
    ))


def test_merge_detail_fills_room_counts():
    pl = _parsed("1", 38.74, -9.10)
    detail = ListingDetail(bedrooms=2, beds=3, bathrooms=1.5, max_guests=4)
    merged = merge_detail(pl, detail)
    assert merged.bedrooms == 2
    assert merged.beds == 3
    assert merged.bathrooms == 1.5
    assert merged.max_guests == 4
    assert merged.airbnb_id == "1"
    assert merged.review_count == 10


def test_persist_results_creates_listing_snapshot_district_and_size_class(db_session):
    cfg = SearchConfig(name="Marvila Crawl", district_slugs=["marvila", "beato"])
    run = CrawlRun(search_config=cfg, status="running")
    db_session.add(run)
    db_session.flush()
    districts = load_districts()

    pl = merge_detail(
        _parsed("A1", 38.7390, -9.1044),
        ListingDetail(bedrooms=1, beds=2, bathrooms=1.0, max_guests=2),
    )
    persist_results(db_session, run, [pl], districts)

    listing = db_session.query(Listing).filter_by(airbnb_id="A1").one()
    assert listing.district_slug == "marvila"
    assert listing.size_class == "1BR"
    assert listing.bedrooms == 1
    snap = db_session.query(Snapshot).filter_by(listing_id=listing.id).one()
    assert snap.crawl_run_id == run.id
    assert snap.review_count == 10


def test_persist_results_upserts_listing_on_second_crawl(db_session):
    cfg = SearchConfig(name="Marvila Crawl", district_slugs=["marvila"])
    districts = load_districts()
    run1 = CrawlRun(search_config=cfg, status="running")
    db_session.add(run1)
    db_session.flush()
    persist_results(db_session, run1, [_parsed("A1", 38.7390, -9.1044, review_count=10)], districts)

    run2 = CrawlRun(search_config=cfg, status="running")
    db_session.add(run2)
    db_session.flush()
    persist_results(db_session, run2, [_parsed("A1", 38.7390, -9.1044, review_count=25)], districts)

    assert db_session.query(Listing).filter_by(airbnb_id="A1").count() == 1
    assert db_session.query(Snapshot).count() == 2
    assert db_session.query(Snapshot).filter_by(crawl_run_id=run2.id).one().review_count == 25


def test_persist_results_marks_point_outside_polygons_unassigned(db_session):
    cfg = SearchConfig(name="X", district_slugs=["marvila"])
    run = CrawlRun(search_config=cfg, status="running")
    db_session.add(run)
    db_session.flush()
    persist_results(db_session, run, [_parsed("OUT", 38.5, -9.5)], load_districts())
    assert db_session.query(Listing).filter_by(airbnb_id="OUT").one().district_slug == "unassigned"
