from decimal import Decimal

from airbi.insights.segment_matrix import (
    PRICE_TIERS,
    SIZE_CLASSES,
    Cell,
    ListingRow,
    SegmentMatrix,
    TopPerformer,
    build_segment_matrix,
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


def _row(airbnb_id, size_class, price, review_count, rating=4.5):
    return ListingRow(
        airbnb_id=airbnb_id, title=f"L{airbnb_id}", url=f"https://x/{airbnb_id}",
        size_class=size_class,
        price=Decimal(str(price)) if price is not None else None,
        review_count=review_count, rating=rating,
    )


def test_builder_returns_full_4x4_grid_with_district_and_run_id():
    matrix = build_segment_matrix([], config={}, district_slug="marvila", crawl_run_id=42)
    assert matrix.district_slug == "marvila"
    assert matrix.crawl_run_id == 42
    assert len(matrix.cells) == 16
    for size in SIZE_CLASSES:
        for tier in PRICE_TIERS:
            assert (size, tier) in matrix.cells


def test_builder_counts_listings_per_cell_and_sums_reviews():
    rows = [
        _row("1", "1BR", 60, 10),   # Budget
        _row("2", "1BR", 65, 20),   # Budget
        _row("3", "1BR", 200, 50),  # Luxury
        _row("4", "2BR", 90, 5),    # Mid (mit dieser Kohorte)
    ]
    matrix = build_segment_matrix(rows, config={}, district_slug="m", crawl_run_id=1)
    budget_1br = matrix.cell("1BR", "Budget")
    assert budget_1br.n == 2
    assert budget_1br.review_sum == 30
    assert budget_1br.score == 15.0  # 30 / 2


def test_builder_median_adr_per_cell():
    rows = [
        _row("1", "1BR", 100, 5),
        _row("2", "1BR", 200, 5),  # gleicher Tier wie 1 in dieser 2er-Kohorte
    ]
    matrix = build_segment_matrix(rows, config={}, district_slug="m", crawl_run_id=1)
    # Beide landen über die Kohorten-Perzentile in derselben Zelle ->
    # Median = (100+200)/2 = 150.
    populated = [c for c in matrix.cells.values() if c.n > 0]
    assert len(populated) == 1
    assert populated[0].adr == Decimal("150")


def test_builder_marks_cells_below_min_sample_as_thin():
    rows = [_row("1", "1BR", 100, 5), _row("2", "1BR", 110, 7)]
    matrix = build_segment_matrix(rows, config={"min_sample": 3},
                                  district_slug="m", crawl_run_id=1)
    populated = next(c for c in matrix.cells.values() if c.n > 0)
    assert populated.n == 2
    assert populated.is_thin is True


def test_builder_skips_rows_with_unclassified_size_or_no_price():
    rows = [
        _row("1", "unclassified", 100, 5),
        _row("2", "1BR", None, 5),
        _row("3", "1BR", 100, 5),
    ]
    matrix = build_segment_matrix(rows, config={"min_sample": 1},
                                  district_slug="m", crawl_run_id=1)
    assert matrix.listing_count == 1
    assert sum(c.n for c in matrix.cells.values()) == 1


def test_builder_picks_best_cell_with_highest_score_above_min_sample():
    rows = [
        # Studio Mid: 3 Listings, je 20 Reviews -> score = 20.
        _row("a1", "Studio", 100, 20), _row("a2", "Studio", 110, 20), _row("a3", "Studio", 120, 20),
        # 1BR Mid: 3 Listings, je 50 Reviews -> score = 50  (Gewinner).
        _row("b1", "1BR", 100, 50), _row("b2", "1BR", 110, 50), _row("b3", "1BR", 120, 50),
        # 2BR Mid: nur 1 Listing mit 999 Reviews -> dünn, fliegt raus.
        _row("c1", "2BR", 105, 999),
    ]
    matrix = build_segment_matrix(rows, config={"min_sample": 3},
                                  district_slug="m", crawl_run_id=1)
    assert matrix.best_cell == ("1BR", "Mid")


def test_builder_returns_no_best_cell_when_all_cells_thin():
    rows = [_row("1", "1BR", 100, 5)]
    matrix = build_segment_matrix(rows, config={"min_sample": 3},
                                  district_slug="m", crawl_run_id=1)
    assert matrix.best_cell is None


def test_builder_heat_is_zero_for_empty_or_thin_cells():
    rows = [_row("1", "1BR", 100, 5)]
    matrix = build_segment_matrix(rows, config={"min_sample": 3},
                                  district_slug="m", crawl_run_id=1)
    for cell in matrix.cells.values():
        assert cell.heat == 0


def test_builder_heat_scales_1_to_4_for_eligible_cells():
    # Drei nicht-dünne Zellen mit aufsteigenden Scores: 1, 5, 20.
    rows = []
    # Studio Mid: 3 x 1 Review.
    rows += [_row(f"s{i}", "Studio", 100, 1) for i in range(3)]
    # 1BR Mid: 3 x 5 Reviews.
    rows += [_row(f"o{i}", "1BR", 100, 5) for i in range(3)]
    # 2BR Mid: 3 x 20 Reviews -> der Top, heat = 4.
    rows += [_row(f"t{i}", "2BR", 100, 20) for i in range(3)]
    matrix = build_segment_matrix(rows, config={"min_sample": 3},
                                  district_slug="m", crawl_run_id=1)
    assert matrix.cell("2BR", "Mid").heat == 4
    assert 1 <= matrix.cell("Studio", "Mid").heat <= 4
    assert 1 <= matrix.cell("1BR", "Mid").heat <= 4
    assert matrix.cell("Studio", "Mid").heat < matrix.cell("2BR", "Mid").heat
