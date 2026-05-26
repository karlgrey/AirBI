from decimal import Decimal

from airbi.insights.segment_matrix import (
    PRICE_TIERS,
    SIZE_CLASSES,
    Cell,
    ListingRow,
    SegmentMatrix,
    TopPerformer,
)


def test_dataclasses_construct_with_minimal_args():
    row = ListingRow(
        airbnb_id="1", title="T", url="u", size_class="1BR",
        price=Decimal("100"), review_count=5, rating=4.7,
    )
    assert row.airbnb_id == "1"

    cell = Cell(size_class="1BR", price_tier="Mid")
    assert cell.n == 0 and cell.is_thin is True and cell.heat == 0

    perf = TopPerformer(
        airbnb_id="1", title="T", url="u", size_class="1BR",
        price_tier="Mid", review_count=5, rating=4.7,
    )
    assert perf.size_class == "1BR"


def test_matrix_axes_have_expected_order():
    assert SIZE_CLASSES == ["Studio", "1BR", "2BR", "3BR+"]
    assert PRICE_TIERS == ["Budget", "Mid", "Premium", "Luxury"]


def test_segment_matrix_cell_lookup_returns_stored_cell():
    matrix = SegmentMatrix(district_slug="marvila", crawl_run_id=1)
    cell = Cell(size_class="1BR", price_tier="Premium", n=3, is_thin=False)
    matrix.cells[("1BR", "Premium")] = cell
    assert matrix.cell("1BR", "Premium") is cell
