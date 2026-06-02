from decimal import Decimal

from airbi.db.models import CrawlRun, Listing, SearchConfig, Snapshot
from airbi.insights.segment_matrix import (
    LUXURY_CLASSES,
    SIZE_CLASSES,
    Cell,
    ListingRow,
    SegmentMatrix,
    TopPerformer,
    TopPerformerProfile,
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


def _row(airbnb_id, size_class, price, review_count, rating=4.5, amenity_score=0.0,
         amenities=None, bedrooms=None, beds=None, max_guests=None, is_superhost=False):
    return ListingRow(
        airbnb_id=airbnb_id, title=f"L{airbnb_id}", url=f"https://x/{airbnb_id}",
        size_class=size_class,
        price=Decimal(str(price)) if price is not None else None,
        review_count=review_count, rating=rating, amenity_score=amenity_score,
        amenities=list(amenities or []),
        bedrooms=bedrooms, beds=beds, max_guests=max_guests,
        is_superhost=is_superhost,
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


def test_top_performer_profile_aggregates_medians_superhost_amenities():
    # 4 Top-Performer-Listings im selben Segment, 3 davon Superhost,
    # alle mit "Wifi", 3 von 4 mit "River view", 1 mit "Pool".
    rows = [
        _row("a", "1BR", 100, 90, amenities=["Wifi","River view"], bedrooms=1, beds=2, max_guests=3, is_superhost=True),
        _row("b", "1BR", 120, 80, amenities=["Wifi","River view"], bedrooms=1, beds=2, max_guests=3, is_superhost=True),
        _row("c", "1BR", 180, 70, amenities=["Wifi","River view","Pool"], bedrooms=1, beds=3, max_guests=4, is_superhost=True),
        _row("d", "1BR", 260, 60, amenities=["Wifi"],                    bedrooms=2, beds=2, max_guests=3, is_superhost=False),
    ]
    matrix = build_segment_matrix(
        rows,
        config={"min_sample": 1, "top_performers_per_segment": 4,
                "amenity_share_threshold": 0.5, "common_amenities_max": 4},
        radius_km=2.0, center_label=_LABEL, crawl_run_id=1,
    )
    profile = matrix.top_performer_profile
    assert profile is not None
    assert profile.count == 4
    assert profile.superhost_share == 0.75
    # Median bedrooms aus [1,1,1,2] = 1
    assert profile.median_bedrooms == 1
    # Median beds aus [2,2,3,2] = 2
    assert profile.median_beds == 2
    # Common amenities: Wifi 100%, River view 75% — Pool 25% fällt unter threshold raus.
    names = [name for name, _ in profile.common_amenities]
    shares = dict(profile.common_amenities)
    assert "Wifi" in names and shares["Wifi"] == 1.0
    assert "River view" in names and shares["River view"] == 0.75
    assert "Pool" not in names
    # Preis-Spanne über [100,120,180,260]
    assert profile.price_min == Decimal("100")
    assert profile.price_max == Decimal("260")


def test_top_performer_profile_caps_common_amenities_at_max():
    rows = [
        _row(str(i), "1BR", 100, 50, amenities=["A","B","C","D","E","F","G","H"], bedrooms=1, beds=1)
        for i in range(3)
    ]
    matrix = build_segment_matrix(
        rows,
        config={"min_sample": 1, "top_performers_per_segment": 3,
                "amenity_share_threshold": 0.5, "common_amenities_max": 3},
        radius_km=2.0, center_label=_LABEL, crawl_run_id=1,
    )
    assert len(matrix.top_performer_profile.common_amenities) == 3


def test_top_performer_profile_is_none_when_no_top_performers():
    matrix = build_segment_matrix(
        [], config={}, radius_km=2.0, center_label=_LABEL, crawl_run_id=1,
    )
    assert matrix.top_performer_profile is None


def _seed(db_session, *, size_class, price, reviews, airbnb_id, run,
          lat=38.7391, lng=-9.1048, amenities=None, bedrooms_field=1,
          is_superhost=False, beds=None, max_guests=None):
    listing = Listing(
        airbnb_id=airbnb_id, city_slug="lisboa", district_slug=None,
        lat=lat, lng=lng, property_type="Apartment",
        bedrooms=bedrooms_field, beds=beds, max_guests=max_guests,
        size_class=size_class, title=f"L{airbnb_id}",
        url=f"https://x/{airbnb_id}",
        amenities=list(amenities or []),
        is_superhost=is_superhost,
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


def test_compute_segment_matrix_populates_listing_row_detail_fields(db_session):
    """compute_segment_matrix soll amenities/bedrooms/beds/max_guests/is_superhost
    aus Listing in ListingRow übernehmen — Voraussetzung für TopPerformerProfile."""
    cfg, run = _seed_run(db_session)
    cfg.classification_config = {"min_sample": 1}
    db_session.flush()
    # Zwei Listings (sonst Kohorte zu klein für price_percentile -> unclassified)
    _seed(db_session, size_class="1BR", price=100, reviews=10, airbnb_id="X1",
          run=run, amenities=["Wifi", "River view"], bedrooms_field=1, beds=2,
          max_guests=3, is_superhost=True)
    _seed(db_session, size_class="1BR", price=200, reviews=20, airbnb_id="X2",
          run=run, amenities=["Wifi"], bedrooms_field=2, beds=3,
          max_guests=4, is_superhost=True)
    matrix = compute_segment_matrix(db_session, cfg, 2.0, run)
    assert matrix.top_performer_profile is not None
    profile = matrix.top_performer_profile
    assert profile.count == 2
    assert profile.superhost_share == 1.0
    # Wifi auf beiden → 100% → erscheint immer
    assert "Wifi" in dict(profile.common_amenities)
    # Median-Felder gesetzt (nicht None)
    assert profile.median_bedrooms is not None
    assert profile.median_beds is not None
    assert profile.median_max_guests is not None


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
