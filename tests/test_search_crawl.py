from decimal import Decimal

from airbi.db.models import CrawlRun, Listing, SearchConfig, Snapshot
from airbi.geo.distance import concentric_boxes
from airbi.scraper.models import ListingDetail, ParsedListing
from airbi.scraper.search_crawl import (
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


def test_concentric_boxes_center_inside_each_box():
    boxes = concentric_boxes(38.7391, -9.1048, [1, 2, 3, 5, 10])
    assert len(boxes) == 5
    for sw_lat, sw_lng, ne_lat, ne_lng in boxes:
        assert sw_lat < 38.7391 < ne_lat
        assert sw_lng < -9.1048 < ne_lng


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


def test_persist_results_creates_listing_snapshot_and_size_class(db_session):
    cfg = SearchConfig(name="Marvila Crawl", district_slugs=["marvila", "beato"])
    run = CrawlRun(search_config=cfg, status="running")
    db_session.add(run)
    db_session.flush()

    pl = merge_detail(
        _parsed("A1", 38.7390, -9.1044),
        ListingDetail(bedrooms=1, beds=2, bathrooms=1.0, max_guests=2),
    )
    persist_results(db_session, run, [pl])

    listing = db_session.query(Listing).filter_by(airbnb_id="A1").one()
    assert listing.district_slug is None
    assert listing.size_class == "1BR"
    assert listing.bedrooms == 1
    snap = db_session.query(Snapshot).filter_by(listing_id=listing.id).one()
    assert snap.crawl_run_id == run.id
    assert snap.review_count == 10


def test_persist_results_dedupes_snapshot_per_run(db_session):
    """Wird persist_results für DASSELBE Listing innerhalb DESSELBEN Runs
    mehrfach aufgerufen, darf nur EIN Snapshot entstehen — Voraussetzung für
    den per-Box-Commit + Resume-Pfad in run_search_crawl."""
    cfg = SearchConfig(name="Dedup", district_slugs=["marvila"])
    run = CrawlRun(search_config=cfg, status="running")
    db_session.add(run)
    db_session.flush()
    pl = _parsed("D1", 38.7390, -9.1044, review_count=10)
    persist_results(db_session, run, [pl])
    # Zweiter Aufruf mit demselben Listing → upsert auf Listing, aber KEIN
    # zweiter Snapshot für (listing, run).
    persist_results(db_session, run, [pl])
    snap_count = db_session.query(Snapshot).filter_by(crawl_run_id=run.id).count()
    assert snap_count == 1
    assert db_session.query(Listing).filter_by(airbnb_id="D1").count() == 1


def test_persist_results_upserts_listing_on_second_crawl(db_session):
    cfg = SearchConfig(name="Marvila Crawl", district_slugs=["marvila"])
    run1 = CrawlRun(search_config=cfg, status="running")
    db_session.add(run1)
    db_session.flush()
    persist_results(db_session, run1, [_parsed("A1", 38.7390, -9.1044, review_count=10)])

    run2 = CrawlRun(search_config=cfg, status="running")
    db_session.add(run2)
    db_session.flush()
    persist_results(db_session, run2, [_parsed("A1", 38.7390, -9.1044, review_count=25)])

    assert db_session.query(Listing).filter_by(airbnb_id="A1").count() == 1
    assert db_session.query(Snapshot).count() == 2
    assert db_session.query(Snapshot).filter_by(crawl_run_id=run2.id).one().review_count == 25


def test_merge_detail_fills_amenities_and_description():
    pl = _parsed("1", 38.74, -9.10)
    detail = ListingDetail(
        bedrooms=2, beds=3, bathrooms=1.5, max_guests=4,
        amenities=["River view", "Air conditioning"], description="Schöne Wohnung",
    )
    merged = merge_detail(pl, detail)
    assert merged.amenities == ["River view", "Air conditioning"]
    assert merged.description == "Schöne Wohnung"
    assert merged.bedrooms == 2 and merged.max_guests == 4


def test_persist_results_writes_amenities_and_amenity_score(db_session):
    cfg = SearchConfig(name="Lux", district_slugs=["marvila"])
    run = CrawlRun(search_config=cfg, status="running")
    db_session.add(run)
    db_session.flush()

    pl = merge_detail(
        _parsed("LX1", 38.7390, -9.1044),
        ListingDetail(bedrooms=2, beds=2, bathrooms=1.0, max_guests=2,
                      amenities=["River view", "Air conditioning", "Pool"],
                      description="Loft mit Blick"),
    )
    persist_results(db_session, run, [pl])

    listing = db_session.query(Listing).filter_by(airbnb_id="LX1").one()
    assert listing.amenities == ["River view", "Air conditioning", "Pool"]
    assert listing.description == "Loft mit Blick"
    assert listing.amenity_score is not None and 0.0 <= listing.amenity_score <= 1.0
    assert listing.amenity_score > 0.2


# ---------------------------------------------------------------------------
# extract_results_and_cursors — None-Sicherheit gegen Airbnb-JSON-null
# (Regression: Run 19 vom 13.07.2026 starb an `"staysSearch": null`)
# ---------------------------------------------------------------------------

def test_extract_results_happy_path():
    from airbi.scraper.search_crawl import extract_results_and_cursors
    stays_data = {"data": {"presentation": {"staysSearch": {"results": {
        "searchResults": [{"id": "x"}],
        "paginationInfo": {"pageCursors": ["c1", "c2"]},
    }}}}}
    results, cursors = extract_results_and_cursors(stays_data)
    assert results == [{"id": "x"}]
    assert cursors == ["c1", "c2"]


def test_extract_results_survives_json_null_at_every_level():
    from airbi.scraper.search_crawl import extract_results_and_cursors
    cases = [
        None,
        {},
        {"data": None},
        {"data": {"presentation": None}},
        {"data": {"presentation": {"staysSearch": None}}},          # Crash-Fall 13.07.
        {"data": {"presentation": {"staysSearch": {"results": None}}}},
        {"data": {"presentation": {"staysSearch": {"results": {
            "searchResults": None, "paginationInfo": None}}}}},
    ]
    for stays_data in cases:
        results, cursors = extract_results_and_cursors(stays_data)
        assert results == [], f"results nicht leer für {stays_data!r}"
        assert cursors == [], f"cursors nicht leer für {stays_data!r}"
