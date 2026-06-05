from decimal import Decimal

from airbi.db.models import CrawlRun, Listing, SearchConfig, Snapshot
from airbi.insights.segment_matrix import (
    LUXURY_CLASSES,
    SIZE_CLASSES,
    Cell,
    ListingRow,
    MapListing,
    SegmentMatrix,
    TopPerformer,
    TopPerformerProfile,
    GapCandidate,
    Kernthese,
    UnderservedSegment,
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


def test_top_performers_picks_top_n_from_best_cell_sorted_by_reviews():
    """Top-Apartments sind die Top-N aus dem empfohlenen Segment (Best-Cell),
    sortiert nach review_count desc. Listings ANDERER Cells erscheinen nicht
    — sie sind konkrete Beispiele für die Hero-Empfehlung."""
    rows = [
        _row("a", "1BR", 100, 5,  rating=4.5),
        _row("b", "1BR", 100, 90, rating=4.9),
        _row("c", "1BR", 100, 50, rating=4.7),
        _row("d", "2BR", 100, 30, rating=4.6),     # andere Cell -- soll WEG sein
    ]
    matrix = _build(rows, config={"top_performers_count": 3, "min_sample": 1})
    # Best-Cell: höchster Score → 1BR-Budget (3 Listings, score 48.3)
    # vor 2BR-Budget (1 Listing, score 30).
    assert matrix.best_cell == ("1BR", "Budget")
    perfs = matrix.top_performers
    assert [p.airbnb_id for p in perfs] == ["b", "c", "a"]
    assert all(p.size_class == "1BR" for p in perfs)
    assert all(p.luxury_class == "Budget" for p in perfs)


def test_top_performers_fall_back_to_radius_top_when_no_best_cell():
    """Ohne Best-Cell (thin data): Top-N im gesamten Umkreis cross-size,
    sortiert nach Bewertungen."""
    rows = [
        _row("a", "1BR", 100, 30),
        _row("b", "2BR", 100, 90),
        _row("c", "Studio", 100, 50),
    ]
    matrix = _build(rows, config={"top_performers_count": 5, "min_sample": 10})
    assert matrix.best_cell is None
    perfs = matrix.top_performers
    assert [p.airbnb_id for p in perfs] == ["b", "c", "a"]


def test_top_performers_ignore_unclassified_size_class():
    rows = [
        _row("a", "unclassified", 100, 999),
        _row("b", "1BR", 100, 5),
    ]
    matrix = _build(rows, config={"min_sample": 1, "top_performers_count": 5})
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
    # 4 Listings, alle im selben Cell (identische Preise → alle Budget),
    # 3 davon Superhost, alle mit "Wifi", 3 von 4 mit "River view",
    # 1 mit "Pool" (25% < threshold).
    rows = [
        _row("a", "1BR", 100, 90, amenities=["Wifi", "River view"], bedrooms=1, beds=2, max_guests=3, is_superhost=True),
        _row("b", "1BR", 100, 80, amenities=["Wifi", "River view"], bedrooms=1, beds=2, max_guests=3, is_superhost=True),
        _row("c", "1BR", 100, 70, amenities=["Wifi", "River view", "Pool"], bedrooms=1, beds=3, max_guests=4, is_superhost=True),
        _row("d", "1BR", 100, 60, amenities=["Wifi"], bedrooms=2, beds=2, max_guests=3, is_superhost=False),
    ]
    matrix = build_segment_matrix(
        rows,
        config={"min_sample": 1, "amenity_share_threshold": 0.5, "common_amenities_max": 4},
        radius_km=2.0, center_label=_LABEL, crawl_run_id=1,
    )
    assert matrix.best_cell == ("1BR", "Budget")
    profile = matrix.top_performer_profile
    assert profile is not None
    assert profile.count == 4
    assert profile.superhost_share == 0.75
    assert profile.median_bedrooms == 1   # median([1,1,1,2]) = 1
    assert profile.median_beds == 2       # median([2,2,3,2]) = 2
    shares = dict(profile.common_amenities)
    assert shares.get("Wifi") == 1.0
    assert shares.get("River view") == 0.75
    assert "Pool" not in shares           # 0.25 < threshold 0.5
    assert profile.price_min == Decimal("100")
    assert profile.price_max == Decimal("100")


def test_top_performer_profile_caps_common_amenities_at_max():
    rows = [
        _row(str(i), "1BR", 100, 50, amenities=["A","B","C","D","E","F","G","H"], bedrooms=1, beds=1)
        for i in range(3)
    ]
    matrix = build_segment_matrix(
        rows,
        config={"min_sample": 1, "top_performers_count": 3,
                "amenity_share_threshold": 0.5, "common_amenities_max": 3},
        radius_km=2.0, center_label=_LABEL, crawl_run_id=1,
    )
    assert len(matrix.top_performer_profile.common_amenities) == 3


def test_top_performer_profile_is_none_when_no_top_performers():
    matrix = build_segment_matrix(
        [], config={}, radius_km=2.0, center_label=_LABEL, crawl_run_id=1,
    )
    assert matrix.top_performer_profile is None


def test_underserved_excludes_best_cell_and_sorts_by_score(db_session=None):
    """Unterversorgungs-Sicht rangiert Cells nach Bew./Apt desc, lässt die
    Best-Cell weg (steht im Hero), inkludiert thin-Cells mit Markierung."""
    # 3x 1BR-Budget (Reviews 30 je) — Best-Cell (Score 30, n=3, nicht-thin)
    # 3x Studio-Budget (Reviews 100 je) — würde besser scoren, wenn nicht
    #     thin: setzen wir auf nicht-thin durch min_sample=1.
    # Mit min_sample=1 sind alle Cells eligible. Score-Reihenfolge:
    #   Studio-Budget=100 > 1BR-Budget=30 > ... → Best=Studio-Budget,
    #   underserved Top=1BR-Budget.
    rows = (
        [_row(f"o{i}", "1BR", 50, 30) for i in range(3)]
        + [_row(f"s{i}", "Studio", 50, 100) for i in range(3)]
    )
    matrix = build_segment_matrix(
        rows, config={"min_sample": 1, "underserved_max": 3},
        radius_km=2.0, center_label=_LABEL, crawl_run_id=1,
    )
    assert matrix.best_cell == ("Studio", "Budget")
    # Best-Cell ist NICHT in der underserved-Liste
    assert all((u.size_class, u.luxury_class) != matrix.best_cell
               for u in matrix.underserved)
    # An erster Stelle: 1BR-Budget (zweithöchster Score 30)
    assert matrix.underserved[0].size_class == "1BR"
    assert matrix.underserved[0].luxury_class == "Budget"
    assert matrix.underserved[0].score == 30.0
    # Absteigend sortiert
    scores = [u.score for u in matrix.underserved]
    assert scores == sorted(scores, reverse=True)


def test_underserved_respects_max_count_and_marks_thin():
    """Max-Count wird respektiert; dünn besetzte Cells erscheinen mit
    is_thin=True (UI rendert Spekulativ-Label)."""
    # Mehr Cells als max_count, einige davon thin.
    rows = (
        # 3x 1BR-Budget (nicht thin, Score 50)
        [_row(f"a{i}", "1BR", 50, 50) for i in range(3)]
        # 1x 1BR-Mid (thin, Score 100)
        + [_row("b", "1BR", 250, 100)]
        # 1x 2BR-Mid (thin, Score 80)
        + [_row("c", "2BR", 250, 80)]
        # 1x 2BR-Budget (thin, Score 70)
        + [_row("d", "2BR", 50, 70)]
    )
    matrix = build_segment_matrix(
        rows, config={"min_sample": 3, "underserved_max": 2},
        radius_km=2.0, center_label=_LABEL, crawl_run_id=1,
    )
    # Best-Cell ist 1BR-Budget (n=3, nicht thin, score=50).
    assert matrix.best_cell == ("1BR", "Budget")
    # max_count=2 → genau 2 Einträge.
    assert len(matrix.underserved) == 2
    # Top-Score-thin-Cells: 1BR-Mid (100), 2BR-Mid (80).
    assert matrix.underserved[0].score == 100.0
    assert matrix.underserved[0].is_thin is True
    assert matrix.underserved[1].score == 80.0
    assert matrix.underserved[1].is_thin is True


def test_underserved_segment_enriched_with_comparison_profile_and_exemplar():
    """Chancen-Cell wird mit Vergleich zur Best-Cell, Profil und konkretem
    Top-Vertreter angereichert — Belastbarkeit der Investment-Aussage."""
    # 3x 1BR-Premium als Best-Cell (Score 100), 3x Studio-Mid als Chancen-Cell (Score 50)
    rows = (
        [_row(f"b{i}", "1BR", 200, 100, bedrooms=1, beds=2, is_superhost=True,
              amenities=["Wifi", "Pool"], max_guests=3) for i in range(3)]
        + [_row(f"c{i}", "Studio", 100, 50, bedrooms=0, beds=1,
                is_superhost=(i == 0), amenities=["Wifi"], max_guests=2)
           for i in range(3)]
    )
    matrix = build_segment_matrix(
        rows,
        config={"min_sample": 1, "underserved_max": 3, "amenity_share_threshold": 0.5},
        radius_km=2.0, center_label=_LABEL, crawl_run_id=1,
    )
    assert len(matrix.underserved) >= 1
    seg = matrix.underserved[0]
    # vs.-Empfehlung-Deltas gesetzt (Studio hat gleichen N=3 → vs_best_n=0,
    # niedrigerer Preis → vs_best_adr<0, niedrigerer Score → vs_best_score<0)
    assert seg.vs_best_n == 0.0
    assert seg.vs_best_adr is not None and seg.vs_best_adr < 0
    assert seg.vs_best_score is not None and seg.vs_best_score < 0
    # Profil aus den 3 Cell-Rows
    assert seg.profile is not None
    assert seg.profile.count == 3
    # 1 von 3 Superhost → 33 %
    assert abs(seg.profile.superhost_share - 1 / 3) < 0.01
    # Stärkster Vertreter: höchste review_count im Cell (alle 50, also der erste alphabetisch)
    assert seg.top_exemplar is not None
    assert seg.top_exemplar.review_count == 50


def test_underserved_rationale_solid_cell_mentions_demand_signal_and_adr():
    """Belastbare Cells erhalten 'solides Demand-Signal' + ADR im Satz."""
    rows = (
        [_row(f"o{i}", "1BR", 100, 30) for i in range(3)]
        + [_row(f"s{i}", "Studio", 100, 50) for i in range(3)]
    )
    matrix = build_segment_matrix(
        rows, config={"min_sample": 1, "underserved_max": 2},
        radius_km=2.0, center_label=_LABEL, crawl_run_id=1,
    )
    # 1BR-Budget (Score 30) ist eine belastbare Chancen-Cell.
    target = next(u for u in matrix.underserved if (u.size_class, u.luxury_class) == ("1BR", "Budget"))
    assert target.is_thin is False
    assert "solides Demand-Signal" in target.rationale
    assert "€100" in target.rationale       # Median-ADR
    assert "Wettbewerber" in target.rationale


def test_underserved_rationale_thin_cell_warns_about_sample_size():
    """Dünne Cells bekommen einen Vorbehalts-Satz."""
    # 3x 1BR-Budget (nicht thin) + 1x 2BR-Mid (thin, hoher Score)
    rows = (
        [_row(f"a{i}", "1BR", 50, 30) for i in range(3)]
        + [_row("b", "2BR", 250, 90)]
    )
    matrix = build_segment_matrix(
        rows, config={"min_sample": 3, "underserved_max": 3},
        radius_km=2.0, center_label=_LABEL, crawl_run_id=1,
    )
    thin = next(u for u in matrix.underserved if u.is_thin)
    assert "stark unterversorgt" in thin.rationale
    assert "Stichprobe zu klein" in thin.rationale


def test_underserved_is_empty_when_no_cell_has_score():
    """Ohne Listings sind alle Cells leer → keine Chancen-Segmente."""
    matrix = build_segment_matrix(
        [], config={}, radius_km=2.0, center_label=_LABEL, crawl_run_id=1,
    )
    assert matrix.underserved == []


def test_gap_cell_detects_white_spot_with_strong_neighbor():
    """Pionier-Alternative: leere Cell, deren direkter Matrix-Nachbar starke
    Demand zeigt — Adjazenz-Demand-Score > Median qualifiziert sie als Lücke."""
    # luxury_weights so wählen, dass amenity_score allein die Luxusklasse
    # bestimmt — damit der Test-Aufbau deterministisch ist.
    cfg = {
        "min_sample": 3,
        "luxury_weights": {"price": 0.0, "amenity": 1.0},
        "underserved_max": 0,  # Underserved hier irrelevant
    }
    # 1BR Luxury: 5 Listings, Reviews=200 → starker Nachbar.
    # 1BR Premium: 5 Listings, Reviews=50  → eligible neighbor, geringer Score.
    # 1BR Mid:     5 Listings, Reviews=80  → Best-Cell (Score 80, n=5, ungating).
    # Studio Luxury: KEINE Listings → Lücken-Kandidat, Nachbarn:
    #   - unten 1BR Luxury (Score 200)
    #   - links Studio Premium (leer) → kein Beitrag
    # → adj_score = 200, einziger Nachbar.
    rows = (
        [_row(f"a{i}", "1BR", 100, 200, amenity_score=0.9) for i in range(5)]
        + [_row(f"b{i}", "1BR", 100, 50, amenity_score=0.6) for i in range(5)]
        + [_row(f"c{i}", "1BR", 100, 80, amenity_score=0.4) for i in range(5)]
    )
    matrix = build_segment_matrix(
        rows, config=cfg, radius_km=2.0, center_label=_LABEL, crawl_run_id=1,
    )
    assert matrix.gap_cell is not None
    gap = matrix.gap_cell
    # Studio Luxury hat 1BR Luxury als stärksten Nachbarn.
    assert gap.size_class == "Studio"
    assert gap.luxury_class == "Luxury"
    assert gap.n == 0
    assert gap.adjacency_score == 200.0
    assert "1 Schlafzimmer" in gap.strongest_neighbor_label
    assert "Luxury" in gap.strongest_neighbor_label
    assert gap.strongest_neighbor_n == 5
    assert "0 Wettbewerber" in gap.rationale
    assert "First-Mover" in gap.rationale


def test_kernthesen_generated_from_best_cell_and_profile():
    """Kernthesen-Generator füllt These 1 (stärkste Position), These 2
    (Preisniveau) und These 3 (Profil) aus den vorhandenen Matrix-Feldern.
    Label-Format: 'These N', kein 'T1'-Jargon."""
    cfg = {
        "min_sample": 3,
        "luxury_weights": {"price": 0.0, "amenity": 1.0},
        "underserved_max": 0,
    }
    rows = [
        _row(f"x{i}", "1BR", 150, 100, amenity_score=0.4,
             bedrooms=1, beds=2, max_guests=3,
             amenities=["River view", "Air conditioning", "Wifi"])
        for i in range(5)
    ]
    matrix = build_segment_matrix(
        rows, config=cfg, radius_km=2.0, center_label=_LABEL, crawl_run_id=1,
    )
    labels = [t.label for t in matrix.kernthesen]
    assert labels[:3] == ["These 1", "These 2", "These 3"]
    # These 1 nennt Größe + Luxus-Segment + Radius
    t1 = matrix.kernthesen[0]
    assert "1 Schlafzimmer" in t1.headline
    assert "Mid" in t1.headline
    assert "2 km" in t1.headline
    # These 2 nennt den Median-Preis
    t2 = matrix.kernthesen[1]
    assert "150" in t2.headline and "€" in t2.headline
    # These 3 nennt das Profil aus dem Top-Performer-Aggregat
    t3 = matrix.kernthesen[2]
    assert "1-Schlafzimmer" in t3.headline or "Studios" in t3.headline


def test_kernthesen_have_no_internal_jargon():
    """Stakeholder-Sprache: keine Tool-Begriffe wie 'Nachbar-Cell', 'Demand-
    Signal', 'Pricing-Window', 'TL;DR'."""
    cfg = {
        "min_sample": 3,
        "luxury_weights": {"price": 0.0, "amenity": 1.0},
        "underserved_max": 0,
    }
    # Best-Cell + Gap-Kandidat — damit These 4 mitgetestet wird.
    rows = [
        _row(f"a{i}", "1BR", 200, 200, amenity_score=0.9,
             bedrooms=1, beds=2, max_guests=3,
             amenities=["River view", "Wifi"])
        for i in range(5)
    ]
    matrix = build_segment_matrix(
        rows, config=cfg, radius_km=2.0, center_label=_LABEL, crawl_run_id=1,
    )
    assert matrix.gap_cell is not None  # sonst greift These 4 nicht
    forbidden = ("Nachbar-Cell", "Demand-Signal", "TL;DR", "Sweet-Spot",
                 "Best-Cell", "Bew./Apt", "First-Mover", "Pricing-Window")
    for t in matrix.kernthesen:
        full = t.headline + " " + t.detail
        for token in forbidden:
            assert token not in full, (
                f"{t.label}: enthält Jargon-Begriff '{token}' — {full}"
            )


def test_kernthesen_t3_skips_generic_amenities():
    """T3 darf nicht 'Bed linens' oder 'Carbon monoxide alarm' nennen —
    diese Items sind überall vorhanden und liefern Stakeholdern keinen
    Differenzierungswert. Stattdessen die nächste relevante Amenity."""
    cfg = {
        "min_sample": 3,
        "luxury_weights": {"price": 0.0, "amenity": 1.0},
        "underserved_max": 0,
        "common_amenities_max": 6,
    }
    # Alle 4 Listings haben die generischen Items + Wifi + River view.
    # 'River view' hat 100 % Share und ist differenzierend → soll auftauchen.
    # 'Bed linens' hat 100 % Share, ist aber generisch → NICHT auftauchen.
    rows = [
        _row(f"r{i}", "1BR", 150, 100, amenity_score=0.4,
             bedrooms=1, beds=2, max_guests=3,
             amenities=[
                 "Bed linens", "Carbon monoxide alarm", "Smoke alarm",
                 "Wifi", "River view", "Air conditioning",
             ])
        for i in range(4)
    ]
    matrix = build_segment_matrix(
        rows, config=cfg, radius_km=2.0, center_label=_LABEL, crawl_run_id=1,
    )
    t3 = next(t for t in matrix.kernthesen if t.label == "These 3")
    # Generische Amenities dürfen weder in Headline noch Detail erscheinen
    full = t3.headline + " " + t3.detail
    assert "Bed linens" not in full
    assert "Carbon monoxide" not in full
    assert "Smoke alarm" not in full
    # Differenzierende Amenities sollen erscheinen (im Detail-Teil)
    has_distinctive = any(
        a in full for a in ("Wifi", "River view", "Air conditioning")
    )
    assert has_distinctive, f"keine differenzierende Amenity in These 3: {full}"


def test_kernthesen_include_gap_when_pioneer_alternative_exists():
    """Wenn der Lücken-Finder eine Pionier-Alternative meldet, wird sie als
    Tn (nach den Mainstream-Thesen) ins TL;DR aufgenommen."""
    cfg = {
        "min_sample": 3,
        "luxury_weights": {"price": 0.0, "amenity": 1.0},
        "underserved_max": 0,
    }
    rows = (
        # Best-Cell: 1BR Luxury, n=5, Score 200
        [_row(f"a{i}", "1BR", 200, 200, amenity_score=0.9,
              bedrooms=1, beds=2, max_guests=3) for i in range(5)]
        # Studio Luxury → Gap-Kandidat (n=0, Nachbar 1BR Luxury stark)
    )
    matrix = build_segment_matrix(
        rows, config=cfg, radius_km=2.0, center_label=_LABEL, crawl_run_id=1,
    )
    # Gap muss erkannt sein, sonst greift der Test nicht.
    assert matrix.gap_cell is not None
    gap_thesen = [t for t in matrix.kernthesen
                  if "Marktlücke" in t.headline or "Lücke" in t.headline]
    assert len(gap_thesen) == 1
    assert "Studio" in gap_thesen[0].headline
    assert "Luxury" in gap_thesen[0].headline


def test_kernthesen_empty_when_no_best_cell():
    """Ohne Datenbasis (Best-Cell) gibt es keine Kernthesen — kein Rauschen."""
    matrix = build_segment_matrix(
        [], config={}, radius_km=2.0, center_label=_LABEL, crawl_run_id=1,
    )
    assert matrix.kernthesen == []


def test_gap_cell_none_when_no_listings():
    """Leere Matrix → keine Pionier-Alternative."""
    matrix = build_segment_matrix(
        [], config={}, radius_km=2.0, center_label=_LABEL, crawl_run_id=1,
    )
    assert matrix.gap_cell is None


def test_builder_profile_is_scoped_to_best_cell_not_cross_size():
    """Das Profil aggregiert nur Listings IM empfohlenen Segment (Best-Cell),
    nicht die größenübergreifenden Top-Performer — damit das Brief-Profil
    konsistent zur Hero-Empfehlung bleibt."""
    # 3 Studio-Budget (Reviews 5 je) + 3 1BR-Mid (Reviews 100 je) →
    # Best-Cell ist klar 1BR-Mid (höherer Score).
    rows = (
        [_row(f"s{i}", "Studio", 50, 5,
              bedrooms=0, beds=1, max_guests=2, is_superhost=False,
              amenities=["Wifi"])
         for i in range(3)]
        + [_row(f"o{i}", "1BR", 200, 100,
                bedrooms=1, beds=2, max_guests=3, is_superhost=True,
                amenities=["Wifi", "Pool"])
           for i in range(3)]
    )
    matrix = build_segment_matrix(
        rows, config={"min_sample": 1},
        radius_km=2.0, center_label=_LABEL, crawl_run_id=1,
    )
    assert matrix.best_cell == ("1BR", "Mid")
    profile = matrix.top_performer_profile
    # Nur die 3 1BR-Mid-Listings im Profil; keine Studio-Daten.
    assert profile.count == 3
    assert profile.median_bedrooms == 1     # nicht 0 (Studio würde 0 ergeben)
    assert profile.superhost_share == 1.0   # nur 1BR sind Superhost
    # "Pool" ist nur bei 1BR (100% dort), Studio hat ihn nicht.
    assert dict(profile.common_amenities).get("Pool") == 1.0


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
    # Zwei Listings im selben Cell (identische Preise -> beide Budget),
    # damit beide ins Best-Cell-Profil eingehen.
    _seed(db_session, size_class="1BR", price=100, reviews=10, airbnb_id="X1",
          run=run, amenities=["Wifi", "River view"], bedrooms_field=1, beds=2,
          max_guests=3, is_superhost=True)
    _seed(db_session, size_class="1BR", price=100, reviews=20, airbnb_id="X2",
          run=run, amenities=["Wifi"], bedrooms_field=1, beds=2,
          max_guests=3, is_superhost=True)
    matrix = compute_segment_matrix(db_session, cfg, 2.0, run)
    assert matrix.top_performer_profile is not None
    profile = matrix.top_performer_profile
    assert profile.count == 2
    assert profile.superhost_share == 1.0
    # Wifi auf beiden → 100%
    assert dict(profile.common_amenities).get("Wifi") == 1.0
    assert profile.median_bedrooms == 1


def test_compute_segment_matrix_exposes_luxury_price_threshold(db_session):
    """Die Luxury-Preis-Schwelle (75. Perzentil der Aktiv-Radius-Kohorte)
    wird auf der Matrix gesetzt — Brief macht sie für den Nutzer sichtbar,
    damit die Verschiebung zwischen Radien erklärbar bleibt."""
    from airbi.db.models import SearchConfig
    cfg = SearchConfig(
        name="ThresholdCfg",
        center_lat=38.7382, center_lng=-9.1055, center_label="X",
        classification_config={"min_sample": 1},
    )
    run = CrawlRun(search_config=cfg, status="completed")
    db_session.add(run)
    db_session.flush()
    # 4 Listings mit Preisen 50, 100, 150, 250 -> 75. Perz. (idx=3) = 250
    for i, p in enumerate([50, 100, 150, 250]):
        _seed(db_session, size_class="1BR", price=p, reviews=10,
              airbnb_id=f"T{i}", run=run, lat=38.7385, lng=-9.1057)
    matrix = compute_segment_matrix(db_session, cfg, 2.0, run)
    assert matrix.luxury_price_threshold == 250


def test_compute_segment_matrix_populates_map_listings_with_max_radius_pool(db_session):
    """map_listings enthält alle Listings im max(band_radii_km)-Umkreis, auch
    außerhalb des aktiven Radius. is_best wird nur für Listings innerhalb des
    Aktiv-Radius gesetzt (Best-Cell-Match)."""
    from airbi.db.models import SearchConfig
    cfg = SearchConfig(
        name="MapCfg",
        center_lat=38.7382, center_lng=-9.1055, center_label="R. Cap. Leitão 86",
        band_radii_km=[1, 2, 10],
        classification_config={"min_sample": 1},
    )
    run = CrawlRun(search_config=cfg, status="completed")
    db_session.add(run)
    db_session.flush()
    # 2 nahe Listings (~50m vom Center) im 1-km-Umkreis
    _seed(db_session, size_class="1BR", price=100, reviews=10, airbnb_id="N1",
          run=run, lat=38.7385, lng=-9.1057, amenities=["Wifi"], bedrooms_field=1)
    _seed(db_session, size_class="1BR", price=100, reviews=12, airbnb_id="N2",
          run=run, lat=38.7384, lng=-9.1054, amenities=["Wifi"], bedrooms_field=1)
    # 1 fernes Listing (~5km weg) im 10-km-Umkreis, aber NICHT im 2-km
    _seed(db_session, size_class="1BR", price=100, reviews=20, airbnb_id="FAR",
          run=run, lat=38.79, lng=-9.10, amenities=["Wifi"], bedrooms_field=1)

    matrix = compute_segment_matrix(db_session, cfg, 2.0, run)

    assert len(matrix.map_listings) == 3        # alle 3 im 10-km-Pool
    near_ids = {m.airbnb_id for m in matrix.map_listings if m.distance_km <= 2.0}
    assert near_ids == {"N1", "N2"}
    far = next(m for m in matrix.map_listings if m.airbnb_id == "FAR")
    assert far.distance_km > 2.0
    # is_best nur für aktive-Radius-Best-Cell-Mitglieder
    assert far.is_best is False
    # Best-Cell ist (1BR, Budget) → die beiden Near-Listings sind best
    bests = [m for m in matrix.map_listings if m.is_best]
    assert len(bests) == 2
    assert {m.airbnb_id for m in bests} == {"N1", "N2"}


def test_map_listing_truncates_amenities_and_description(db_session):
    """amenities auf 10 gekappt, description auf 300 Zeichen."""
    from airbi.db.models import SearchConfig
    cfg = SearchConfig(
        name="TruncCfg",
        center_lat=38.7382, center_lng=-9.1055, center_label="X",
        classification_config={"min_sample": 1},
    )
    run = CrawlRun(search_config=cfg, status="completed")
    db_session.add(run); db_session.flush()
    many_amenities = [f"Item{i}" for i in range(20)]
    long_desc = "x" * 500
    listing = Listing(
        airbnb_id="T1", city_slug="lisboa", district_slug=None,
        lat=38.7385, lng=-9.1057, property_type="Apartment",
        bedrooms=1, size_class="1BR", title="T1", url="https://x/T1",
        amenities=many_amenities, description=long_desc, is_superhost=False,
    )
    db_session.add(listing); db_session.flush()
    db_session.add(Snapshot(listing_id=listing.id, crawl_run_id=run.id,
                            price=Decimal("100"), review_count=5, rating=4.7))
    # zweites Listing, damit price_percentile berechenbar
    _seed(db_session, size_class="1BR", price=120, reviews=5, airbnb_id="T2",
          run=run, lat=38.7384, lng=-9.1054, bedrooms_field=1)

    matrix = compute_segment_matrix(db_session, cfg, 2.0, run)
    target = next(m for m in matrix.map_listings if m.airbnb_id == "T1")
    assert len(target.amenities) == 10
    assert len(target.description) == 300


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
