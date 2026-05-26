from decimal import Decimal

from airbi.db.models import CrawlRun, Listing, SearchConfig, Snapshot
from airbi.insights.segment_matrix import (
    PRICE_TIERS,
    SIZE_CLASSES,
    Cell,
    ListingRow,
    SegmentMatrix,
    TopPerformer,
    build_segment_matrix,
    compute_segment_matrix,
    latest_completed_run,
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
    # 5er-Cohort [60, 65, 90, 200, 300]: ranks 0.0 / 0.2 / 0.4 / 0.6 / 0.8.
    # 60 und 65 -> Budget (rank < 0.25), Rest verteilt sich.
    rows = [
        _row("1", "1BR", 60, 10),   # Budget (rank 0.0)
        _row("2", "1BR", 65, 20),   # Budget (rank 0.2)
        _row("3", "1BR", 300, 50),  # Premium (rank 0.8)
        _row("4", "1BR", 200, 7),   # Mid (rank 0.6) — Kohorten-Anker
        _row("5", "2BR", 90, 5),    # Mid (rank 0.4)
    ]
    matrix = build_segment_matrix(rows, config={}, district_slug="m", crawl_run_id=1)
    budget_1br = matrix.cell("1BR", "Budget")
    assert budget_1br.n == 2
    assert budget_1br.review_sum == 30
    assert budget_1br.score == 15.0  # 30 / 2


def test_builder_median_adr_per_cell():
    # Cohort [60, 100, 200]: ranks 0.0 / 0.333 / 0.667.
    # 100 und 200 landen beide in Mid -> Median = (100+200)/2 = 150.
    rows = [
        _row("0", "1BR", 60, 5),    # Budget — Kohorten-Anker
        _row("1", "1BR", 100, 5),   # Mid (rank 1/3)
        _row("2", "1BR", 200, 5),   # Mid (rank 2/3)
    ]
    matrix = build_segment_matrix(rows, config={}, district_slug="m", crawl_run_id=1)
    mid_cell = matrix.cell("1BR", "Mid")
    assert mid_cell.n == 2
    assert mid_cell.adr == Decimal("150")


def test_builder_marks_cells_below_min_sample_as_thin():
    # Identischer Preis -> rank 0.0 -> beide in Budget.
    rows = [_row("1", "1BR", 100, 5), _row("2", "1BR", 100, 7)]
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
    # Identischer Preis -> alle in (size, Budget). Höchster Score gewinnt.
    rows = [
        # Studio Budget: 3 Listings, je 20 Reviews -> score = 20.
        _row("a1", "Studio", 100, 20), _row("a2", "Studio", 100, 20), _row("a3", "Studio", 100, 20),
        # 1BR Budget: 3 Listings, je 50 Reviews -> score = 50  (Gewinner).
        _row("b1", "1BR", 100, 50), _row("b2", "1BR", 100, 50), _row("b3", "1BR", 100, 50),
        # 2BR Budget: nur 1 Listing mit 999 Reviews -> dünn, fliegt raus.
        _row("c1", "2BR", 100, 999),
    ]
    matrix = build_segment_matrix(rows, config={"min_sample": 3},
                                  district_slug="m", crawl_run_id=1)
    assert matrix.best_cell == ("1BR", "Budget")


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
    # Drei nicht-dünne Budget-Zellen mit aufsteigenden Scores: 1, 5, 20.
    # (Alle Preise gleich -> rank 0.0 -> Budget.)
    rows = []
    rows += [_row(f"s{i}", "Studio", 100, 1) for i in range(3)]    # score = 1
    rows += [_row(f"o{i}", "1BR", 100, 5) for i in range(3)]       # score = 5
    rows += [_row(f"t{i}", "2BR", 100, 20) for i in range(3)]      # score = 20 (Top)
    matrix = build_segment_matrix(rows, config={"min_sample": 3},
                                  district_slug="m", crawl_run_id=1)
    assert matrix.cell("2BR", "Budget").heat == 4
    assert 1 <= matrix.cell("Studio", "Budget").heat <= 4
    assert 1 <= matrix.cell("1BR", "Budget").heat <= 4
    assert matrix.cell("Studio", "Budget").heat < matrix.cell("2BR", "Budget").heat


def test_recommendation_names_district_size_tier_score_n_adr_and_proxy_note():
    # 3 identische 1BR-Listings -> Cohort = [100,100,100] -> rank(100) = 0.0
    # -> alle landen mit DEFAULT_PRICE_TIERS in der (1BR, Budget)-Zelle.
    # N=3 = min_sample -> nicht dünn -> Best-Cell = (1BR, Budget).
    rows = [_row(f"l{i}", "1BR", 100, review_count=80) for i in range(3)]
    matrix = build_segment_matrix(rows, config={"min_sample": 3},
                                  district_slug="marvila", crawl_run_id=1)
    rec = matrix.recommendation
    assert "Marvila" in rec
    assert "1BR" in rec
    assert "Budget" in rec           # Gewinner aus der Konstruktion
    assert "80" in rec               # Ø Reviews je Listing
    assert "3 Wettbewerber" in rec   # N = 3 Wettbewerber-Listings
    assert "€100" in rec             # Median-ADR
    assert "Proxy" in rec
    assert "40%" in rec              # review_rate * 100


def test_recommendation_falls_back_when_no_cell_meets_min_sample():
    rows = [_row("1", "1BR", 100, 5)]  # nur 1 Listing -> alle Zellen dünn
    matrix = build_segment_matrix(rows, config={"min_sample": 3},
                                  district_slug="beato", crawl_run_id=1)
    assert matrix.best_cell is None
    assert "Beato" in matrix.recommendation
    assert "zu dünn" in matrix.recommendation


def test_top_performers_grouped_by_size_class_sorted_by_review_count():
    rows = [
        _row("a", "1BR", 100, 5,  rating=4.5),
        _row("b", "1BR", 100, 90, rating=4.9),  # Top 1
        _row("c", "1BR", 100, 50, rating=4.7),  # Top 2
        _row("d", "2BR", 100, 30, rating=4.6),  # einziger 2BR
    ]
    matrix = build_segment_matrix(rows, config={"top_performers_per_segment": 2,
                                                "min_sample": 1},
                                  district_slug="m", crawl_run_id=1)
    perfs = matrix.top_performers
    # Reihenfolge: nach SIZE_CLASSES, innerhalb nach review_count desc.
    one_br = [p for p in perfs if p.size_class == "1BR"]
    assert [p.airbnb_id for p in one_br] == ["b", "c"]
    two_br = [p for p in perfs if p.size_class == "2BR"]
    assert [p.airbnb_id for p in two_br] == ["d"]
    # Reihenfolge gesamt: 1BR-Block kommt vor 2BR-Block.
    assert [p.size_class for p in perfs] == ["1BR", "1BR", "2BR"]


def test_top_performers_ignore_unclassified_size_class():
    rows = [
        _row("a", "unclassified", 100, 999),
        _row("b", "1BR", 100, 5),
    ]
    matrix = build_segment_matrix(rows, config={"min_sample": 1,
                                                "top_performers_per_segment": 2},
                                  district_slug="m", crawl_run_id=1)
    assert all(p.size_class in SIZE_CLASSES for p in matrix.top_performers)
    assert any(p.airbnb_id == "b" for p in matrix.top_performers)
    assert all(p.airbnb_id != "a" for p in matrix.top_performers)


def _seed(db_session, *, district, size_class, price, reviews, airbnb_id, run):
    listing = Listing(
        airbnb_id=airbnb_id, city_slug="lisboa", district_slug=district,
        lat=38.74, lng=-9.10, property_type="Apartment",
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
    cfg = SearchConfig(name=f"Cfg-{status}-{id(db_session)}",
                       district_slugs=["marvila", "beato"])
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
    cfg = SearchConfig(name="None", district_slugs=["marvila"])
    db_session.add(CrawlRun(search_config=cfg, status="failed"))
    db_session.flush()
    assert latest_completed_run(db_session, cfg) is None


def test_compute_segment_matrix_pulls_only_rows_for_district_and_run(db_session):
    cfg, run = _seed_run(db_session)
    # marvila: 3 1BR-Listings.
    for i, (p, rev) in enumerate([(80, 10), (90, 12), (100, 8)]):
        _seed(db_session, district="marvila", size_class="1BR",
              price=p, reviews=rev, airbnb_id=f"M{i}", run=run)
    # beato: 2 2BR-Listings (sollen NICHT auftauchen).
    for i, (p, rev) in enumerate([(150, 50), (160, 60)]):
        _seed(db_session, district="beato", size_class="2BR",
              price=p, reviews=rev, airbnb_id=f"B{i}", run=run)
    # Anderer Run: gehört nicht in dieses Ergebnis.
    other_run = CrawlRun(search_config=cfg, status="completed")
    db_session.add(other_run)
    db_session.flush()
    _seed(db_session, district="marvila", size_class="1BR",
          price=200, reviews=999, airbnb_id="OTHER", run=other_run)

    matrix = compute_segment_matrix(db_session, cfg, "marvila", run)
    assert matrix.listing_count == 3
    assert matrix.crawl_run_id == run.id
    assert matrix.district_slug == "marvila"


def test_compute_segment_matrix_respects_search_config_classification_config(db_session):
    cfg, run = _seed_run(db_session)
    cfg.classification_config = {"min_sample": 2}
    db_session.flush()
    # Zwei Listings mit demselben Preis -> selbe Zelle -> N = 2.
    for i, (p, rev) in enumerate([(100, 10), (100, 20)]):
        _seed(db_session, district="marvila", size_class="1BR",
              price=p, reviews=rev, airbnb_id=f"M{i}", run=run)
    matrix = compute_segment_matrix(db_session, cfg, "marvila", run)
    # min_sample=2 -> die Zelle mit 2 Listings ist gerade nicht mehr dünn
    # (mit dem Default 3 wäre sie es).
    populated = next(c for c in matrix.cells.values() if c.n > 0)
    assert populated.n == 2
    assert populated.is_thin is False
