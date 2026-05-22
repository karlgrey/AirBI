from decimal import Decimal

from airbi.scraper.models import ParsedListing


def test_parsed_listing_holds_listing_and_snapshot_fields():
    pl = ParsedListing(
        airbnb_id="12345",
        title="Loft in Marvila",
        url="https://www.airbnb.com/rooms/12345",
        lat=38.739,
        lng=-9.104,
        property_type="Entire loft",
        bedrooms=1,
        beds=2,
        bathrooms=1.0,
        max_guests=3,
        host_name="Ana",
        is_superhost=True,
        price=Decimal("120.00"),
        fees=None,
        review_count=42,
        rating=4.9,
        search_position=1,
    )
    assert pl.airbnb_id == "12345"
    assert pl.review_count == 42
    assert pl.price == Decimal("120.00")
