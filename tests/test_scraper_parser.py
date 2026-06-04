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


def test_search_parser_returns_all_results_in_fixture():
    # Aktuelle Fixture: 18 Listings (siehe Aufnahme-Befund in
    # scripts/record_stays_search.py Kopfkommentar). Bei neuer Aufnahme
    # diese Zahl an die tatsächliche Listing-Anzahl anpassen.
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
    assert [pl.search_position for pl in listings] == list(range(1, len(listings) + 1))


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
    assert detail.bedrooms == 1
    assert detail.beds == 1
    assert detail.bathrooms == 1.0
    assert detail.max_guests == 2


def _detail_payload_with_overview(items: list) -> dict:
    """Minimaler Payload, der die exakte Verschachtelung nachbildet,
    die _collect_overview_items erwartet."""
    section = {"sectionData": {"overviewItems": items}}
    return {
        "niobeClientData": [
            [
                None,
                {
                    "data": {
                        "presentation": {
                            "stayProductDetailPage": {
                                "sections": {
                                    "sbuiData": {
                                        "sectionConfiguration": {
                                            "root": {
                                                "sections": [section]
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }
                },
            ]
        ]
    }


def test_detail_parser_handles_plural_and_studio():
    # Plural-Titel ("3 bedrooms", "2 beds", "2.5 baths", "4 guests")
    payload = _detail_payload_with_overview([
        {"title": "4 guests"}, {"title": "3 bedrooms"},
        {"title": "2 beds"}, {"title": "2.5 baths"},
    ])
    detail = parse_listing_detail(payload)
    assert detail.bedrooms == 3
    assert detail.beds == 2
    assert detail.bathrooms == 2.5
    assert detail.max_guests == 4


def test_detail_parser_studio_is_zero_bedrooms():
    payload = _detail_payload_with_overview([
        {"title": "2 guests"}, {"title": "Studio"}, {"title": "1 bed"},
    ])
    assert parse_listing_detail(payload).bedrooms == 0


def test_detail_parser_tolerates_unexpected_shape():
    detail = parse_listing_detail({})
    assert detail.bedrooms is None
    assert detail.max_guests is None


def test_detail_parser_reads_pdp_overview_items_string_list():
    """Aktuelles Airbnb-Schema (Stand 2026-06): ``pdpPresentation.overview.items``
    ist eine flache Liste von Strings, kein Dict mehr. Der Parser muss diese
    Quelle als primär nutzen — sonst bleibt ``bedrooms`` immer ``None``."""
    payload = {
        "niobeClientData": [
            [
                None,
                {
                    "data": {
                        "node": {
                            "pdpPresentation": {
                                "overview": {
                                    "items": ["4 guests", "1 bedroom", "2 beds", "1 bath"]
                                }
                            }
                        }
                    }
                },
            ]
        ]
    }
    detail = parse_listing_detail(payload)
    assert detail.bedrooms == 1
    assert detail.beds == 2
    assert detail.bathrooms == 1.0
    assert detail.max_guests == 4


def test_search_parser_extracts_price_from_discounted_line():
    """Listings mit primaryLine.__typename = DiscountedDisplayPriceLine
    haben weiterhin einen Preis (jetzt der Pro-Nacht-Preis aus explanationData,
    nicht der rabattierte Aufenthalts-Total).
    Plan: 2026-05-27 Parser-Cleanup, Discovery Task 1.
    """
    listings = parse_search_results(_search_payload())
    target = next(pl for pl in listings if pl.airbnb_id == "17346774")
    assert target.price is not None
    assert target.price > 0
    # Pro-Nacht (explanationData "5 nights x €94.17"), NICHT der Total €450:
    assert target.price == Decimal("94.17")


def test_search_parser_price_is_per_night_not_stay_total():
    """Root-Cause-Regression: primaryLine.price trägt qualifier='total' (5-Nächte-
    Aufenthalt). Der Parser MUSS den Pro-Nacht-Preis aus explanationData nehmen.
    Für jedes Listing: gespeicherter Preis == Pro-Nacht und strikt < Aufenthalts-Total."""
    from airbi.scraper.parser import _decode_listing_id, _parse_price

    payload = _search_payload()
    by_id = {pl.airbnb_id: pl for pl in parse_search_results(payload)}
    results = payload["data"]["presentation"]["staysSearch"]["results"]["searchResults"]

    checked = 0
    for r in results:
        sdp = r.get("structuredDisplayPrice") or {}
        primary = sdp.get("primaryLine") or {}
        try:
            desc = sdp["explanationData"]["priceDetails"][0]["items"][0]["description"]
        except (KeyError, IndexError, TypeError):
            continue
        if " x " not in desc:
            continue
        expected_per_night = _parse_price(desc.split(" x ", 1)[1])
        total = _parse_price(primary.get("price") or primary.get("discountedPrice"))

        aid = _decode_listing_id(r["demandStayListing"]["id"])
        pl = by_id.get(aid)
        assert pl is not None and pl.price is not None, f"{aid}: kein Preis"
        assert pl.price == expected_per_night, f"{aid}: {pl.price} != per-night {expected_per_night}"
        if total is not None:
            assert pl.price < total, f"{aid}: Preis {pl.price} ist der Total {total}!"
        checked += 1
    assert checked >= 15


def test_detail_parser_extracts_available_amenities():
    detail = parse_listing_detail(_detail_payload())
    assert detail.amenities is not None
    assert any("river view" in a.lower() for a in detail.amenities)
    assert any("air conditioning" in a.lower() for a in detail.amenities)
    assert not any("smoke alarm" == a.lower() for a in detail.amenities)
    assert 20 <= len(detail.amenities) <= 44


def test_detail_parser_extracts_description():
    detail = parse_listing_detail(_detail_payload())
    # Die Fixture HAT eine Beschreibung — sie muss extrahiert werden.
    assert detail.description is not None
    assert len(detail.description) > 0
    assert "<" not in detail.description  # HTML-Tags gestrippt


def test_detail_parser_description_none_on_unexpected_shape():
    assert parse_listing_detail({}).description is None


def test_detail_parser_amenities_empty_on_unexpected_shape():
    detail = parse_listing_detail({})
    assert detail.amenities == [] or detail.amenities is None
