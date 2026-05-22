import json
from decimal import Decimal
from pathlib import Path

from airbi.scraper.models import ParsedListing
from airbi.scraper.parser import parse_listing_detail, parse_search_results


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


SEARCH_FIXTURE = Path(__file__).parent / "fixtures" / "scraper" / "stays_search_page1.json"


def _search_payload():
    return json.loads(SEARCH_FIXTURE.read_text(encoding="utf-8"))


def test_search_parser_returns_all_18_results():
    assert len(parse_search_results(_search_payload())) == 18


def test_search_parser_core_fields_present_and_typed():
    for pl in parse_search_results(_search_payload()):
        assert pl.airbnb_id and pl.airbnb_id.isdigit()
        assert pl.lat is not None and pl.lng is not None
        assert pl.review_count >= 0
        assert isinstance(pl.is_superhost, bool)
        assert pl.bedrooms is None
        assert pl.max_guests is None


def test_search_parser_assigns_1_based_positions():
    listings = parse_search_results(_search_payload())
    assert [pl.search_position for pl in listings] == list(range(1, 19))


def test_search_parser_first_result_within_lisbon_bbox():
    first = parse_search_results(_search_payload())[0]
    assert 38.70 < first.lat < 38.78
    assert -9.17 < first.lng < -9.05


def test_search_parser_extracts_property_type_and_url():
    listings = parse_search_results(_search_payload())
    assert any(pl.property_type and "partment" in pl.property_type.lower()
               for pl in listings)
    for pl in listings:
        assert pl.url and pl.airbnb_id in pl.url


def test_search_parser_returns_empty_list_on_unexpected_shape():
    assert parse_search_results({}) == []


def test_price_helper_handles_thousands_and_decimal_separators():
    from airbi.scraper.parser import _parse_price
    from decimal import Decimal
    assert _parse_price("€ 817") == Decimal("817")
    assert _parse_price("€1,234") == Decimal("1234")
    assert _parse_price("€1,234.56") == Decimal("1234.56")
    assert _parse_price("€1.234,56") == Decimal("1234.56")
    assert _parse_price("€1.234") == Decimal("1234")
    assert _parse_price("") is None
    assert _parse_price(None) is None


DETAIL_FIXTURE = Path(__file__).parent / "fixtures" / "scraper" / "listing_detail.json"


def _detail_payload():
    return json.loads(DETAIL_FIXTURE.read_text(encoding="utf-8"))


def test_detail_parser_extracts_room_counts():
    detail = parse_listing_detail(_detail_payload())
    assert detail.bedrooms is not None
    assert detail.bedrooms >= 0
    assert detail.max_guests is not None and detail.max_guests >= 1


def test_detail_parser_tolerates_unexpected_shape():
    detail = parse_listing_detail({})
    assert detail.bedrooms is None
    assert detail.max_guests is None
