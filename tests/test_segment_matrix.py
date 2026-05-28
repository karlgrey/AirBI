from decimal import Decimal

from airbi.db.models import CrawlRun, Listing, SearchConfig, Snapshot
from airbi.insights.segment_matrix import (
    LUXURY_CLASSES,
    SIZE_CLASSES,
    Cell,
    ListingRow,
    SegmentMatrix,
    TopPerformer,
    build_segment_matrix,
    compute_segment_matrix,
    latest_completed_run,
)

_LABEL = "R. Cap. Leitão 86"


def test_dataclasses_construct_with_minimal_args():
    row = ListingRow(
        airbnb_id="1", title="T", url="u", size_class="1BR",
        price=Decimal("100"), review_count=5, rating=4.7,
    )
    assert row.airbnb_id == "1"

    cell = Cell(size_class="1BR", luxury_class="Mid")
    assert cell.n == 0 and cell.is_thin is True and cell.heat == 0

    perf = TopPerformer(
        airbnb_id="1", title="T", url="u", size_class="1BR",
        luxury_class="Mid", review_count=5, rating=4.7,
    )
    assert perf.size_class == "1BR"


def test_matrix_axes_have_expected_order():
    assert SIZE_CLASSES == ["Studio", "1BR", "2BR", "3BR+"]
    assert LUXURY_CLASSES == ["Budget", "Mid", "Premium", "Luxury"]


def test_segment_matrix_cell_lookup_returns_stored_cell():
    matrix = SegmentMatrix(radius_km=2.0, crawl_run_id=1)
    cell = Cell(size_class="1BR", luxury_class="Premium", n=3, is_thin=False)
    matrix.cells[("1BR", "Premium")] = cell
    assert matrix.cell("1BR", "Premium") is cell


def _row(airbnb_id, size_class, price, review_count, rating=4.5, amenity_score=0.0):
    return ListingRow(
        airbnb_id=airbnb_id, title=f"L{airbnb_id}", url=f"https://x/{airbnb_id}",
        size_class=size_class,
        price=Decimal(str(price)) if price is not None else None,
        review_count=review_count, rating=rating, amenity_score=amenity_score,
    )


def _build(rows, **kwargs):
    """Builder-Aufruf mit Umkreis-Defaults (radius_km/center_label)."""
    kwargs.setdefault("radius_km", 2.0)
    kwargs.setdefault("center_label", _LABEL)
    kwargs.setdefault("crawl_run_id", 1)
    return build_segment_matrix(rows, **kwargs)


def test_builder_returns_full_4x4_grid_with_radius_and_run_id():
    matrix = _build([], config={}, radius_km=2.0, crawl_run_id=42)
    assert matrix.radius_km == 2.0
    assert matrix.crawl_run_id == 42
    assert len(matrix.cells) == 16
    for size in SIZE_CLASSES:
        for lux in LUXURY_CLASSES:
            assert (size, lux) in matrix.cells


def test_builder_counts_listings_per_cell_and_sums_reviews():
    # 5er-Cohort [60, 65, 90, 200, 300]: ranks 0.0 / 0.2 / 0.4 / 0.6 / 0.8.
    rows = [
        _row("1", "1BR", 60, 10),   # Budget (rank 0.0)
        _row("2", "1BR", 65, 20),   # Budget (rank 0.2)
        _row("3", "1BR", 300, 50),  # Mid (rank 0.8)
        _row("4", "1BR", 200, 7),   # Mid (rank 0.6)
        _row("5", "2BR", 90, 5),    # Budget (rank 0.4)
    ]
    matrix = _build(rows, config={})
    budget_1br = matrix.cell("1BR", "Budget")
    assert budget_1br.n == 2
    assert budget_1br.review_sum == 30
    assert budget_1br.score == 15.0  # 30 / 2


def test_builder_median_adr_per_cell():
    # Cohort [60, 100, 200]: ranks 0.0 / 0.333 / 0.667.
    rows = [
        _row("0", "1BR", 60, 5),    # Budget
        _row("1", "1BR", 100, 5),   # Budget
        _row("2", "1BR", 200, 5),   # Mid
    ]
    matrix = _build(rows, config={})
    budget_cell = matrix.cell("1BR", "Budget")
    assert budget_cell.n == 2
    assert budget_cell.adr == Decimal("80")


def test_builder_marks_cells_below_min_sample_as_thin():
    rows = [_row("1", "1BR", 100, 5), _row("2", "1BR", 100, 7)]
    matrix = _build(rows, config={"min_sample": 3})
    populated = next(c for c in matrix.cells.values() if c.n > 0)
    assert populated.n == 2
    assert populated.is_thin is True


def test_builder_skips_rows_with_unclassified_size_or_no_price():
    rows = [
        _row("1", "unclassified", 100, 5),
        _row("2", "1BR", None, 5),
        _row("3", "1BR", 100, 5),
    ]
    matrix = _build(rows, config={"min_sample": 1})
    assert matrix.listing_count == 1
    assert sum(c.n for c in matrix.cells.values()) == 1


def test_builder_picks_best_cell_with_highest_score_above_min_sample():
    rows = [
        _row("a1", "Studio", 100, 20), _row("a2", "Studio", 100, 20), _row("a3", "Studio", 100, 20),
        _row("b1", "1BR", 100, 50), _row("b2", "1BR", 100, 50), _row("b3", "1BR", 100, 50),
        _row("c1", "2BR", 100, 999),
    ]
    matrix = _build(rows, config={"min_sample": 3})
    assert matrix.best_cell == ("1BR", "Budget")


def test_builder_returns_no_best_cell_when_all_cells_thin():
    rows = [_row("1", "1BR", 100, 5)]
    matrix = _build(rows, config={"min_sample": 3})
    assert matrix.best_cell is None


def test_builder_heat_is_zero_for_empty_or_thin_cells():
    rows = [_row("1", "1BR", 100, 5)]
    matrix = _build(rows, config={"min_sample": 3})
    for cell in matrix.cells.values():
        assert cell.heat == 0


def test_builder_heat_scales_1_to_4_for_eligible_cells():
    rows = []
    rows += [_row(f"s{i}", "Studio", 100, 1) for i in range(3)]    # score = 1
    rows += [_row(f"o{i}", "1BR", 100, 5) for i in range(3)]       # score = 5
    rows += [_row(f"t{i}", "2BR", 100, 20) for i in range(3)]      # score = 20 (Top)
    matrix = _build(rows, config={"min_sample": 3})
    assert matrix.cell("2BR", "Budget").heat == 4
    assert 1 <= matrix.cell("Studio", "Budget").heat <= 4
    assert 1 <= matrix.cell("1BR", "Budget").heat <= 4
    assert matrix.cell("Studio", "Budget").heat < matrix.cell("2BR", "Budget").heat


def test_recommendation_names_umkreis_size_tier_score_n_adr_and_proxy_note():
    rows = [_row(f"l{i}", "1BR", 100, review_count=80) for i in range(3)]
    matrix = build_segment_matrix(
        rows, config={"min_sample": 3},
        radius_km=2.0, center_label=_LABEL, crawl_run_id=1,
    )
    rec = matrix.recommendation
    assert "Umkreis" in rec
    assert "2 km" in rec
    assert _LABEL in rec
    assert "1BR" in rec
    assert "Budget" in rec
    assert "80" in rec
    assert "3 Wettbewerber" in rec
    assert "€100" in rec
    assert "Proxy" in rec
    assert "40%" in rec


def test_recommendation_falls_back_when_no_cell_meets_min_sample():
    rows = [_row("1", "1BR", 100, 5)]
    matrix = build_segment_matrix(
        rows, config={"min_sample": 3},
        radius_km=5.0, center_label=_LABEL, crawl_run_id=1,
    )
    assert matrix.best_cell is None
    assert "Umkreis" in matrix.recommendation
    assert "5 km" in matrix.recommendation
    assert "zu dünn" in matrix.recommendation


def test_top_performers_grouped_by_size_class_sorted_by_review_count():
    rows = [
        _row("a", "1BR", 100, 5,  rating=4.5),
        _row("b", "1BR", 100, 90, rating=4.9),  # Top 1
        _row("c", "1BR", 100, 50, rating=4.7),  # Top 2
        _row("d", "2BR", 100, 30, rating=4.6),  # einziger 2BR
    ]
    matrix = _build(rows, config={"top_performers_per_segment": 2, "min_sample": 1})
    perfs = matrix.top_performers
    one_br = [p for p in perfs if p.size_class == "1BR"]
    assert [p.airbnb_id for p in one_br] == ["b", "c"]
    two_br = [p for p in perfs if p.size_class == "2BR"]
    assert [p.airbnb_id for p in two_br] == ["d"]
    assert [p.size_class for p in perfs] == ["1BR", "1BR", "2BR"]


def test_top_performers_ignore_unclassified_size_class():
    rows = [
        _row("a", "unclassified", 100, 999),
        _row("b", "1BR", 100, 5),
    ]
    matrix = _build(rows, config={"min_sample": 1, "top_performers_per_segment": 2})
    assert all(p.size_class in SIZE_CLASSES for p in matrix.top_performers)
    assert any(p.airbnb_id == "b" for p in matrix.top_performers)
    assert all(p.airbnb_id != "a" for p in matrix.top_performers)


def test_builder_amenity_score_shifts_listing_into_higher_luxury_class():
    cfg = {"min_sample": 1, "luxury_weights": {"price": 0.35, "amenity": 0.65}}
    rows = [
        _row("a", "1BR", 100, 10, amenity_score=0.0),
        _row("b", "1BR", 100, 10, amenity_score=0.0),
        _row("c", "1BR", 100, 10, amenity_score=0.0),
        _row("d", "1BR", 100, 10, amenity_score=0.95),
    ]
    matrix = _build(rows, config=cfg)
    classes_with_d = [lux for (sz, lux), cell in matrix.cells.items()
                      if cell.n > 0 and sz == "1BR"]
    assert "Premium" in classes_with_d or "Luxury" in classes_with_d


def _seed(db_session, *, size_class, price, reviews, airbnb_id, run,
          lat=38.7391, lng=-9.1048):
    listing = Listing(
        airbnb_id=airbnb_id, city_slug="lisboa", district_slug=None,
        lat=lat, lng=lng, property_type="Apartment",
        bedrooms=1, size_class=size_class, title=f"L{airbnb_id}",
        url=f"https://x/{airbnb_id}",
    )
    db_session.add(listing)
    db_session.flush()
    db_session.add(Snapshot(
        listing_id=listing.id, crawl_run_id=run.id,
        price=Decimal(str(price)), review_count=reviews, rating=4.7,
    ))


def _seed_run(db_session, *, status="completed"):
    cfg = SearchConfig(
        name=f"Cfg-{status}-{id(db_session)}",
        center_lat=38.7391, center_lng=-9.1048, center_label=_LABEL,
    )
    run = CrawlRun(search_config=cfg, status=status)
    db_session.add(run)
    db_session.flush()
    return cfg, run


def test_latest_completed_run_returns_most_recent_completed(db_session):
    cfg, completed_old = _seed_run(db_session, status="completed")
    completed_new = CrawlRun(search_config=cfg, status="completed")
    failed = CrawlRun(search_config=cfg, status="failed")
    db_session.add_all([completed_new, failed])
    db_session.flush()
    latest = latest_completed_run(db_session, cfg)
    assert latest.id == completed_new.id


def test_latest_completed_run_returns_none_when_no_completed_run(db_session):
    cfg = SearchConfig(name="None", center_lat=38.7391, center_lng=-9.1048)
    db_session.add(CrawlRun(search_config=cfg, status="failed"))
    db_session.flush()
    assert latest_completed_run(db_session, cfg) is None


def test_compute_segment_matrix_filters_by_radius_and_run(db_session):
    cfg, run = _seed_run(db_session)
    # 3 Listings nah am Zentrum (<1 km).
    for i, (p, rev) in enumerate([(80, 10), (90, 12), (100, 8)]):
        _seed(db_session, size_class="1BR", price=p, reviews=rev,
              airbnb_id=f"NEAR{i}", run=run, lat=38.7395, lng=-9.1050)
    # 1 Listing weit weg (~10 km südlich) -> bei radius 2 km ausgeschlossen.
    _seed(db_session, size_class="1BR", price=200, reviews=999,
          airbnb_id="FAR", run=run, lat=38.65, lng=-9.10)
    # Anderer Run -> nicht in diesem Ergebnis.
    other_run = CrawlRun(search_config=cfg, status="completed")
    db_session.add(other_run)
    db_session.flush()
    _seed(db_session, size_class="1BR", price=120, reviews=5,
          airbnb_id="OTHER", run=other_run)

    matrix = compute_segment_matrix(db_session, cfg, 2.0, run)
    assert matrix.listing_count == 3        # nur die nahen, nicht FAR/OTHER
    assert matrix.crawl_run_id == run.id
    assert matrix.radius_km == 2.0


def test_compute_segment_matrix_respects_search_config_classification_config(db_session):
    cfg, run = _seed_run(db_session)
    cfg.classification_config = {"min_sample": 2}
    db_session.flush()
    for i, (p, rev) in enumerate([(100, 10), (100, 20)]):
        _seed(db_session, size_class="1BR", price=p, reviews=rev,
              airbnb_id=f"M{i}", run=run)
    matrix = compute_segment_matrix(db_session, cfg, 2.0, run)
    populated = next(c for c in matrix.cells.values() if c.n > 0)
    assert populated.n == 2
    assert populated.is_thin is False
