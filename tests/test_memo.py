from decimal import Decimal

from airbi.db.models import CrawlRun, Listing, SearchConfig, Snapshot
from airbi.insights.memo import (
    CONFIDENCE_BELASTBAR,
    CONFIDENCE_DUENN,
    CONFIDENCE_SOLIDE,
    AnchorStats,
    Fragment,
    Memo,
    MemoChapter,
    compute_anchor_stats,
    compute_confidence,
)


def test_confidence_belastbar_needs_velocity_fresh_data_and_sample():
    assert compute_confidence(
        data_age_days=3, n=5, min_sample=3, velocity_available=True, multiplier=1.5,
    ) == CONFIDENCE_BELASTBAR


def test_confidence_downgrades_to_solide_when_multiplier_below_threshold():
    """Memo-Review 11.08.2026: 1,1x Median ist nahe am Rauschen -- selbst mit
    frischen Daten und Velocity-Signal reicht das nicht für 'belastbar'."""
    assert compute_confidence(
        data_age_days=3, n=5, min_sample=3, velocity_available=True, multiplier=1.1,
    ) == CONFIDENCE_SOLIDE


def test_confidence_belastbar_boundary_multiplier_exactly_at_threshold():
    assert compute_confidence(
        data_age_days=3, n=5, min_sample=3, velocity_available=True, multiplier=1.3,
    ) == CONFIDENCE_BELASTBAR


def test_confidence_missing_multiplier_does_not_qualify_for_belastbar():
    """Ohne Multiplikator-Angabe kann die Zusatzbedingung nicht geprüft
    werden -- konservativ auf 'solide Indizien' statt unbelegt 'belastbar'."""
    assert compute_confidence(
        data_age_days=3, n=5, min_sample=3, velocity_available=True, multiplier=None,
    ) == CONFIDENCE_SOLIDE


def test_confidence_multiplier_threshold_is_configurable():
    assert compute_confidence(
        data_age_days=3, n=5, min_sample=3, velocity_available=True,
        multiplier=1.25, min_multiplier=1.2,
    ) == CONFIDENCE_BELASTBAR


def test_confidence_solide_without_velocity():
    assert compute_confidence(
        data_age_days=3, n=5, min_sample=3, velocity_available=False
    ) == CONFIDENCE_SOLIDE


def test_confidence_solide_boundary_age_14_and_n_equals_min_sample():
    assert compute_confidence(
        data_age_days=14, n=3, min_sample=3, velocity_available=False
    ) == CONFIDENCE_SOLIDE


def test_confidence_duenn_when_stale_or_thin_or_age_unknown():
    assert compute_confidence(
        data_age_days=15, n=5, min_sample=3, velocity_available=False
    ) == CONFIDENCE_DUENN
    assert compute_confidence(
        data_age_days=3, n=2, min_sample=3, velocity_available=False
    ) == CONFIDENCE_DUENN
    assert compute_confidence(
        data_age_days=None, n=5, min_sample=3, velocity_available=False
    ) == CONFIDENCE_DUENN


def test_confidence_velocity_with_stale_data_is_not_belastbar():
    assert compute_confidence(
        data_age_days=8, n=5, min_sample=3, velocity_available=True
    ) == CONFIDENCE_SOLIDE


def test_chapter_plain_text_joins_fragments():
    ch = MemoChapter(number="02", title="Wo die Nachfrage hinläuft", fragments=[
        Fragment(kind="text", text="Premium sammelt"),
        Fragment(kind="chip", text="37 Bewertungen je Apartment"),
    ])
    assert "Premium sammelt 37 Bewertungen je Apartment" == ch.plain_text


def _mk_listing(session, airbnb_id, lat, lng, size_class="1BR", bedrooms=1):
    listing = Listing(
        airbnb_id=airbnb_id, url=f"https://x/{airbnb_id}", title=f"L{airbnb_id}",
        city_slug="lisboa", lat=lat, lng=lng,
        size_class=size_class, bedrooms=bedrooms,
    )
    session.add(listing)
    session.flush()
    return listing


def test_compute_anchor_stats_counts_only_listings_near_anchor(db_session):
    cfg = SearchConfig(name="Anker-Test", city_slug="lisboa",
                       center_lat=38.7390, center_lng=-9.1044)
    db_session.add(cfg)
    db_session.flush()
    run = CrawlRun(search_config_id=cfg.id, status="completed")
    db_session.add(run)
    db_session.flush()

    # Zwei Listings am Anker (Alfama, ~38.714/-9.128), eins weit weg.
    near1 = _mk_listing(db_session, "a1", 38.714, -9.128)
    near2 = _mk_listing(db_session, "a2", 38.715, -9.127)
    far = _mk_listing(db_session, "f1", 38.768, -9.094)
    for listing, price in ((near1, "100"), (near2, "200"), (far, "150")):
        db_session.add(Snapshot(listing_id=listing.id, crawl_run_id=run.id,
                                price=Decimal(price), review_count=10))
    db_session.flush()

    market = {"name": "Alfama/Graça", "lat": 38.714, "lng": -9.128, "radius_km": 1.2}
    stats = compute_anchor_stats(db_session, cfg, run, market, segment=None)
    assert stats.name == "Alfama/Graça"
    assert stats.listing_count == 2          # far liegt außerhalb des Anker-Radius


def test_compute_anchor_stats_segment_uses_local_cohort(db_session):
    """Klassifikation relativ zum ANKER-Markt, nicht zum Heimmarkt: Das
    teuerste Anker-Listing landet in der lokalen Top-Preisklasse."""
    cfg = SearchConfig(name="Anker-Kohorte-Test", city_slug="lisboa",
                       center_lat=38.7390, center_lng=-9.1044,
                       classification_config={"luxury_weights": {"price": 1.0, "amenity": 0.0}, "min_sample": 1})
    db_session.add(cfg)
    db_session.flush()
    run = CrawlRun(search_config_id=cfg.id, status="completed")
    db_session.add(run)
    db_session.flush()

    prices = ["80", "90", "100", "110", "300"]   # 300 = lokales Top-Quartil
    for i, price in enumerate(prices):
        listing = _mk_listing(db_session, f"k{i}", 38.714 + i * 0.0004, -9.128)
        db_session.add(Snapshot(listing_id=listing.id, crawl_run_id=run.id,
                                price=Decimal(price), review_count=20))
    db_session.flush()

    market = {"name": "Alfama/Graça", "lat": 38.714, "lng": -9.128, "radius_km": 1.2}
    stats = compute_anchor_stats(db_session, cfg, run, market, segment=("1BR", "Luxury"))
    assert stats.segment_n >= 1               # das 300er-Listing ist lokal Luxury


def test_compute_anchor_stats_reports_segment_velocity_from_history(db_session):
    """compute_anchor_stats soll segment_velocity aus der Snapshot-Historie der
    Anker-Listings befuellen (Teilprojekt 3) -- nicht nur den Bestands-Score."""
    from datetime import datetime, timedelta

    cfg = SearchConfig(name="Anker-Velocity-Test", city_slug="lisboa",
                       center_lat=38.7390, center_lng=-9.1044,
                       classification_config={"min_sample": 1})
    db_session.add(cfg)
    db_session.flush()
    run_old = CrawlRun(search_config_id=cfg.id, status="completed",
                       started_at=datetime(2026, 6, 1))
    db_session.add(run_old)
    db_session.flush()
    run_new = CrawlRun(search_config_id=cfg.id, status="completed",
                       started_at=datetime(2026, 6, 1) + timedelta(days=28))
    db_session.add(run_new)
    db_session.flush()

    a1 = _mk_listing(db_session, "va1", 38.714, -9.128)
    a2 = _mk_listing(db_session, "va2", 38.715, -9.127)
    db_session.add(Snapshot(listing_id=a1.id, crawl_run_id=run_old.id,
                            captured_at=datetime(2026, 6, 1),
                            price=Decimal("100"), review_count=10))
    db_session.add(Snapshot(listing_id=a1.id, crawl_run_id=run_new.id,
                            captured_at=datetime(2026, 6, 1) + timedelta(days=28),
                            price=Decimal("100"), review_count=38))  # 7/Woche
    db_session.add(Snapshot(listing_id=a2.id, crawl_run_id=run_new.id,
                            captured_at=datetime(2026, 6, 1) + timedelta(days=28),
                            price=Decimal("100"), review_count=5))   # kein Verlauf
    db_session.flush()

    market = {"name": "Alfama/Graça", "lat": 38.714, "lng": -9.128, "radius_km": 1.2}
    stats = compute_anchor_stats(db_session, cfg, run_new, market, segment=("1BR", "Budget"))
    assert stats.segment_velocity == 7.0
    assert stats.segment_velocity_n == 1


# ---------------------------------------------------------------------------
# Task 4: Kapitel-Generator build_memo + Jargon-Vertrag
# ---------------------------------------------------------------------------

from airbi.insights.segment_matrix import build_segment_matrix, ListingRow
from airbi.insights.memo import build_memo


def _row(airbnb_id, size_class, price, review_count, weekly_velocity=None):
    return ListingRow(
        airbnb_id=airbnb_id, title=f"L{airbnb_id}", url=f"https://x/{airbnb_id}",
        size_class=size_class, price=Decimal(str(price)),
        review_count=review_count, rating=4.8, weekly_velocity=weekly_velocity,
    )


def _home_matrix():
    """Heimmarkt mit klarer Best-Cell. WICHTIG: die drei 1BR-Zeilen haben
    bewusst IDENTISCHE Preise — gleiches Preis-Perzentil heißt gleiche
    Luxusklasse, nur so erreicht die Zelle n=3 (sonst keine Best-Cell)."""
    rows = [
        _row("h1", "1BR", 100, 40), _row("h2", "1BR", 100, 35), _row("h3", "1BR", 100, 45),
        _row("h4", "2BR", 200, 5), _row("h5", "2BR", 210, 8), _row("h6", "2BR", 190, 2),
        _row("h7", "Studio", 60, 1),
    ]
    return build_segment_matrix(
        rows, config={}, radius_km=2.0,
        center_label="R. Cap. Leitão 86", crawl_run_id=1,
    )


def _anchors():
    return [
        AnchorStats(name="Alfama/Graça", radius_km=1.2, listing_count=240,
                    segment_n=30, segment_score=52.0, segment_adr=120.0),
        AnchorStats(name="Parque das Nações", radius_km=1.5, listing_count=150,
                    segment_n=12, segment_score=41.0, segment_adr=110.0),
    ]


def _home_matrix_with_velocity():
    """Wie _home_matrix, aber die Best-Cell (1BR) hat auf allen drei Zeilen
    ein Velocity-Signal -> velocity_n=3 >= min_sample(3)."""
    rows = [
        _row("h1", "1BR", 100, 40, weekly_velocity=4.0),
        _row("h2", "1BR", 100, 35, weekly_velocity=6.0),
        _row("h3", "1BR", 100, 45, weekly_velocity=5.0),
        _row("h4", "2BR", 200, 5), _row("h5", "2BR", 210, 8), _row("h6", "2BR", 190, 2),
        _row("h7", "Studio", 60, 1),
    ]
    return build_segment_matrix(
        rows, config={}, radius_km=2.0,
        center_label="R. Cap. Leitão 86", crawl_run_id=1,
    )


def _anchors_with_velocity():
    return [
        AnchorStats(name="Alfama/Graça", radius_km=1.2, listing_count=240,
                    segment_n=30, segment_score=52.0, segment_adr=120.0,
                    segment_velocity=3.0, segment_velocity_n=10),
        AnchorStats(name="Parque das Nações", radius_km=1.5, listing_count=150,
                    segment_n=12, segment_score=41.0, segment_adr=110.0,
                    segment_velocity=2.0, segment_velocity_n=5),
    ]


def test_build_memo_verdict_names_segment_and_confidence():
    memo = build_memo(_home_matrix(), _anchors(), data_age_days=2)
    assert memo.verdict_size_label == "1 Schlafzimmer"
    assert memo.verdict_luxury_class in ("Budget", "Mid", "Premium", "Luxury")
    assert memo.confidence == CONFIDENCE_SOLIDE
    assert memo.confidence_dots == 2


def test_build_memo_has_four_chapters_with_gap_else_three():
    memo = build_memo(_home_matrix(), _anchors(), data_age_days=2)
    titles = [c.title for c in memo.chapters]
    assert titles[0] == "Der Markt vor Ort"
    assert titles[1] == "Wo die Nachfrage hinläuft"
    assert titles[-1] == "Was dagegen spricht"
    # Kapitel "Die Alternative" nur, wenn der Lücken-Finder fündig wurde:
    if _home_matrix().gap_cell:
        assert "Die Alternative" in titles


def test_build_memo_chapter1_anchors_density():
    memo = build_memo(_home_matrix(), _anchors(), data_age_days=2)
    ch1 = memo.chapters[0].plain_text
    assert "7" in ch1                  # Heimmarkt-Dichte (listing_count)
    assert "Alfama/Graça" in ch1       # Anker benannt
    assert "240" in ch1                # Anker-Dichte


def test_build_memo_chapter2_has_value_chip_with_median_factor_and_anchor_chips():
    memo = build_memo(_home_matrix(), _anchors(), data_age_days=2)
    ch2 = memo.chapters[1]
    chips = [f for f in ch2.fragments if f.kind == "chip"]
    muted = [f for f in ch2.fragments if f.kind == "chip_muted"]
    assert any("Bewertungen je Apartment" in c.text for c in chips)
    assert any("×" in c.text for c in chips)            # Median-Faktor
    assert any("Alfama/Graça" in m.text for m in muted)  # Anker-Chip
    assert any("52" in m.text for m in muted)


def test_build_memo_chapter2_stock_wording_without_velocity():
    memo = build_memo(_home_matrix(), _anchors(), data_age_days=2)
    ch2 = memo.chapters[1].plain_text
    assert "gesammelt" in ch2          # Bestands-Formulierung (Teil-3-Weiche)


def test_build_memo_chapter2_trend_wording_and_velocity_chip_when_available():
    memo = build_memo(
        _home_matrix_with_velocity(), _anchors_with_velocity(),
        data_age_days=2, velocity_available=True,
    )
    ch2 = memo.chapters[1]
    assert "wird aktuell am stärksten gebucht" in ch2.plain_text
    assert "gesammelt" not in ch2.plain_text
    chips = [f for f in ch2.fragments if f.kind == "chip"]
    assert any("Bewertungen/Woche je Apartment" in c.text for c in chips)
    # 5.0 = Ø(4.0, 6.0, 5.0) der Best-Cell-Zeilen.
    assert any("5.0" in c.text for c in chips)


def test_build_memo_chapter2_velocity_anchor_comparison_when_available():
    memo = build_memo(
        _home_matrix_with_velocity(), _anchors_with_velocity(),
        data_age_days=2, velocity_available=True,
    )
    ch2 = memo.chapters[1]
    muted = [f for f in ch2.fragments if f.kind == "chip_muted"]
    assert any("Alfama/Graça" in m.text and "Bewertungen/Woche" in m.text for m in muted)
    # Heimmarkt-Velocity (5.0) liegt über beiden Ankern (3.0 / 2.0).
    assert "-Fachen" in ch2.plain_text or "%" in ch2.plain_text


def test_build_memo_chapter2_falls_back_to_stock_when_velocity_flag_true_but_no_signal():
    """velocity_available=True, aber die Best-Cell selbst hat kein Signal
    (z.B. Grenzfall/Datenlücke) -> Chip faellt defensiv auf den Bestands-Wert
    zurueck statt eine leere/None-Velocity zu zeigen."""
    memo = build_memo(_home_matrix(), _anchors(), data_age_days=2, velocity_available=True)
    ch2 = memo.chapters[1]
    chips = [f for f in ch2.fragments if f.kind == "chip"]
    assert any("Bewertungen je Apartment" in c.text for c in chips)
    assert not any("Bewertungen/Woche" in c.text for c in chips)


def test_build_memo_risk_chapter_names_age_proxy_and_al():
    memo = build_memo(_home_matrix(), _anchors(), data_age_days=9)
    risk = memo.chapters[-1].plain_text
    assert "9 Tage" in risk
    assert "Indikator" in risk         # Proxy-Annahme
    assert "AL-Lizenz" in risk         # ungeprüft (al_zone_status=None)


def test_build_memo_risk_chapter_uses_singular_for_one_day():
    """Kleinbug (Memo-Review 11.08.2026): 'Der Datenstand ist 1 Tage alt'
    muss Singular 'Tag' verwenden."""
    memo = build_memo(_home_matrix(), _anchors(), data_age_days=1)
    risk = memo.chapters[-1].plain_text
    assert "1 Tag alt" in risk
    assert "1 Tage alt" not in risk


def test_build_memo_risk_chapter_uses_plural_for_zero_and_many_days():
    memo0 = build_memo(_home_matrix(), _anchors(), data_age_days=0)
    assert "0 Tage alt" in memo0.chapters[-1].plain_text
    memo9 = build_memo(_home_matrix(), _anchors(), data_age_days=9)
    assert "9 Tage alt" in memo9.chapters[-1].plain_text


def test_build_memo_risk_chapter_skips_al_when_zone_known():
    memo = build_memo(_home_matrix(), _anchors(), data_age_days=2,
                      al_zone_status="ABSORCAO")
    assert "AL-Lizenz" not in memo.chapters[-1].plain_text


def test_build_memo_silent_without_best_cell():
    rows = [_row("x1", "1BR", 100, 5)]   # nur 1 Listing -> alles thin
    matrix = build_segment_matrix(rows, config={}, radius_km=2.0,
                                  center_label="X", crawl_run_id=1)
    memo = build_memo(matrix, [], data_age_days=2)
    assert memo.verdict_size_label is None
    assert memo.chapters == []
    assert "3" in memo.verdict_subline   # nennt die min_sample-Schwelle


def test_build_memo_anchorless_renders_without_anchor_chips():
    memo = build_memo(_home_matrix(), [], data_age_days=2)
    ch2 = memo.chapters[1]
    assert not [f for f in ch2.fragments if f.kind == "chip_muted"]
    assert "zu dünn besetzt" not in ch2.plain_text


def test_build_memo_stale_data_yields_confidence_duenn():
    """data_age_days=20 (>14) → CONFIDENCE_DUENN, nicht SOLIDE.
    Stellt sicher, dass der Template-Zweig '{% if memo.confidence == "solide Indizien" %}'
    (Velocity-Hinweis) bei DUENN-Stufe schweigt — veraltete Daten ≠ fehlende
    Verlaufsdaten, der Hinweis wäre irreführend."""
    memo = build_memo(_home_matrix(), [], data_age_days=20)
    assert memo.confidence == CONFIDENCE_DUENN
    assert memo.confidence != CONFIDENCE_SOLIDE


JARGON_BLACKLIST = [
    "Nachbar-Cell",
    "Demand-Signal",
    "TL;DR",
    "Sweet-Spot",
    "Best-Cell",
    "Bew./Apt",
    "First-Mover",
    "Pricing-Window",
    "Pricing-Fenster",
    "Dedicated workspace",
    "Dining table",
]


def test_memo_texts_have_no_internal_jargon():
    memo = build_memo(_home_matrix(), _anchors(), data_age_days=2)
    texts = [memo.verdict_subline] + [c.plain_text for c in memo.chapters]
    for text in texts:
        for term in JARGON_BLACKLIST:
            assert term.lower() not in text.lower(), f"Jargon '{term}' in: {text}"


def test_build_memo_survives_anchor_with_zero_segment_score():
    """Anker-Segment ohne Bewertungen (Score 0.0) darf keinen Crash und
    keinen Prozent-Vergleich erzeugen."""
    anchors = [AnchorStats(name="Totes Viertel", radius_km=1.0, listing_count=40,
                           segment_n=5, segment_score=0.0, segment_adr=90.0)]
    memo = build_memo(_home_matrix(), anchors, data_age_days=2)
    ch2 = memo.chapters[1].plain_text
    assert "Totes Viertel" not in ch2 or "%" not in ch2


# ---------------------------------------------------------------------------
# Task 5: compute_memo Orchestrierung
# ---------------------------------------------------------------------------

from airbi.insights.memo import compute_memo


def test_compute_memo_uses_home_radius_and_config_anchors(db_session):
    cfg = SearchConfig(
        name="Memo-E2E-Test", city_slug="lisboa",
        center_lat=38.7390, center_lng=-9.1044,
        band_radii_km=[1, 2, 3], home_radius_km=2.0,
        comparison_markets=[
            {"name": "Alfama/Graça", "lat": 38.714, "lng": -9.128, "radius_km": 1.2},
        ],
    )
    db_session.add(cfg)
    db_session.flush()
    run = CrawlRun(search_config_id=cfg.id, status="completed")
    db_session.add(run)
    db_session.flush()
    # 4 Listings im Heimmarkt (~Zielobjekt), damit eine Best-Cell entsteht:
    for i in range(4):
        listing = _mk_listing(db_session, f"e{i}", 38.7390 + i * 0.0005, -9.1044)
        db_session.add(Snapshot(listing_id=listing.id, crawl_run_id=run.id,
                                price=Decimal("100"), review_count=30))
    db_session.flush()

    memo = compute_memo(db_session, cfg, run)
    assert memo.home_radius_km == 2.0
    assert memo.verdict_size_label is not None
    assert [a.name for a in memo.anchors] == ["Alfama/Graça"]


# ---------------------------------------------------------------------------
# Fix 1: _density_phrase flächennormiert
# ---------------------------------------------------------------------------

from airbi.insights.memo import _density_phrase


def test_density_phrase_normalizes_by_area():
    """Anker mit kleinerem Radius aber ähnlicher Roh-Anzahl ist pro km²
    deutlich dichter — die Formulierung muss das widerspiegeln."""
    anchor = AnchorStats(name="Alfama/Graça", radius_km=1.2, listing_count=131)
    # Heimmarkt: 148 Listings in 2.0 km -> ~11.8/km²; Anker: ~29/km²
    # -> Heimmarkt hat ~0.4 der Anker-Dichte, NICHT "vergleichbar"
    phrase = _density_phrase(148, 2.0, anchor)
    assert "vergleichbare" not in phrase
    assert phrase != ""


def test_density_phrase_equal_density_is_comparable():
    anchor = AnchorStats(name="X", radius_km=1.0, listing_count=25)
    # 100 Listings in 2.0 km = 100/12.57 ≈ 8/km²; Anker 25/3.14 ≈ 8/km²
    assert "vergleichbare" in _density_phrase(100, 2.0, anchor)


# ---------------------------------------------------------------------------
# Fix 2: Zona de Contenção Warnung im Risiko-Kapitel
# ---------------------------------------------------------------------------


def test_build_memo_risk_chapter_warns_on_contencao_zone():
    memo = build_memo(_home_matrix(), _anchors(), data_age_days=2,
                      al_zone_status="CONTENCAO")
    risk = memo.chapters[-1].plain_text
    assert "Zona de Contenção" in risk
    assert "Lizenz" in risk


def test_build_memo_risk_chapter_quiet_on_absorcao_zone():
    memo = build_memo(_home_matrix(), _anchors(), data_age_days=2,
                      al_zone_status="ABSORCAO")
    risk = memo.chapters[-1].plain_text
    assert "Zona de Contenção" not in risk
    assert "ungeprüft" not in risk


# ---------------------------------------------------------------------------
# Kapitel-2-Vergleich: Mindest-Stichprobe, Richtungs-Logik, Einheiten
# ---------------------------------------------------------------------------


def test_chapter2_excludes_anchor_segments_below_min_sample():
    """Anker-Segment mit n < min_sample darf nicht als Vergleichsbasis dienen."""
    anchors = [AnchorStats(name="Parque das Nações", radius_km=1.5, listing_count=17,
                           segment_n=2, segment_score=15.0, segment_adr=100.0)]
    memo = build_memo(_home_matrix(), anchors, data_age_days=2)
    ch2 = memo.chapters[1].plain_text
    assert "Parque das Nações" not in ch2
    assert "zu dünn besetzt" in ch2


def test_chapter2_names_market_and_uses_factor_when_home_is_stronger():
    anchors = [AnchorStats(name="Alfama/Graça", radius_km=1.2, listing_count=240,
                           segment_n=30, segment_score=10.0, segment_adr=120.0)]
    memo = build_memo(_home_matrix(), anchors, data_age_days=2)
    ch2 = memo.chapters[1].plain_text
    assert "Alfama/Graça" in ch2
    assert "4.0-Fachen von Alfama/Graça" in ch2   # 40 / 10
    assert "%" not in ch2                          # keine Prozent über 100


def test_chapter2_uses_percent_when_home_is_weaker():
    anchors = [AnchorStats(name="Alfama/Graça", radius_km=1.2, listing_count=240,
                           segment_n=30, segment_score=52.0, segment_adr=120.0)]
    memo = build_memo(_home_matrix(), anchors, data_age_days=2)
    ch2 = memo.chapters[1].plain_text
    assert "77 % des Niveaus von Alfama/Graça" in ch2   # 40/52 = 0.769
    assert "Anbieter" in ch2


def test_chapter2_first_anchor_chip_spells_unit():
    memo = build_memo(_home_matrix(), _anchors(), data_age_days=2)
    muted = [f.text for f in memo.chapters[1].fragments if f.kind == "chip_muted"]
    assert muted[0].endswith("Bewertungen je Apartment")


def test_compute_memo_falls_back_to_smallest_band_radius(db_session):
    cfg = SearchConfig(name="Memo-Fallback-Test", city_slug="lisboa",
                       center_lat=38.7390, center_lng=-9.1044,
                       band_radii_km=[3, 1, 5])
    db_session.add(cfg)
    db_session.flush()
    run = CrawlRun(search_config_id=cfg.id, status="completed")
    db_session.add(run)
    db_session.flush()
    memo = compute_memo(db_session, cfg, run)
    assert memo.home_radius_km == 1.0
    assert memo.anchors == []


# ---------------------------------------------------------------------------
# Task 1+2 (Memo-Review 11.08.2026): Empfehlungs-Changelog + Hysterese
# ---------------------------------------------------------------------------

from datetime import datetime

from airbi.insights.recommendation_history import RecommendationEntry

_RAW_SEGMENT = _home_matrix().best_cell   # ("1BR", <luxury_class>) -- die rohe Best-Cell
_OTHER_SEGMENT = ("2BR", "Mid" if _RAW_SEGMENT[1] != "Mid" else "Budget")


def _history_entry(crawl_run_id, run_date, raw, displayed=None):
    displayed = displayed or raw
    return RecommendationEntry(
        crawl_run_id=crawl_run_id, run_date=run_date,
        raw_size_class=raw[0], raw_luxury_class=raw[1],
        displayed_size_class=displayed[0], displayed_luxury_class=displayed[1],
    )


def test_build_memo_without_history_has_no_changelog():
    """Erster Lauf ohne Vergleichswert -- kein Changelog-Abschnitt, keine
    stille Vorspiegelung von Kontinuität."""
    memo = build_memo(_home_matrix(), _anchors(), data_age_days=2)
    assert memo.changelog is None


def test_build_memo_changelog_confirms_unchanged_recommendation():
    history = [_history_entry(1, datetime(2026, 8, 5), _RAW_SEGMENT)]
    memo = build_memo(_home_matrix(), _anchors(), data_age_days=2, history=history)
    assert memo.changelog is not None
    text = memo.changelog.plain_text
    assert "geändert" not in text
    assert "unverändert" in text


def test_build_memo_changelog_flags_explicit_switch_after_hysteresis_confirms():
    """Herausforderer (= aktuelle rohe Best-Cell) war schon im vorigen Lauf
    roh vorn -> Streak 2 erreicht Default-Schwelle -> Wechsel, explizit im
    Changelog ausgewiesen (Kern von Task 1: kein stiller Wechsel mehr)."""
    history = [
        _history_entry(1, datetime(2026, 7, 30), _OTHER_SEGMENT),
        _history_entry(2, datetime(2026, 8, 5), _RAW_SEGMENT, displayed=_OTHER_SEGMENT),
    ]
    memo = build_memo(
        _home_matrix(), _anchors(), data_age_days=2, history=history,
        run_date=datetime(2026, 8, 10),
    )
    # Die Empfehlung wechselt jetzt tatsächlich auf die rohe Best-Cell:
    from airbi.insights.segment_matrix import _size_klartext
    assert memo.verdict_size_label == _size_klartext(_RAW_SEGMENT[0])
    assert memo.verdict_luxury_class == _RAW_SEGMENT[1]
    assert memo.changelog is not None
    text = memo.changelog.plain_text
    assert "geändert am 10.08.2026" in text
    assert _size_klartext(_OTHER_SEGMENT[0]) in text
    assert _size_klartext(_RAW_SEGMENT[0]) in text
    assert "Grund" in text


def test_build_memo_holds_previous_recommendation_with_challenger_note():
    """Herausforderer erst 1 Lauf lang roh vorn (< Default N=2) -> die alte
    Empfehlung bleibt Verdict UND bestimmt Kapitel 2/4, nur ein
    Herausforderer-Hinweis erscheint im Changelog."""
    history = [_history_entry(1, datetime(2026, 8, 5), _OTHER_SEGMENT)]
    memo = build_memo(_home_matrix(), _anchors(), data_age_days=2, history=history)
    from airbi.insights.segment_matrix import _size_klartext
    assert memo.verdict_size_label == _size_klartext(_OTHER_SEGMENT[0])
    assert memo.verdict_luxury_class == _OTHER_SEGMENT[1]
    assert memo.changelog is not None
    text = memo.changelog.plain_text
    assert "geändert" not in text
    assert "Herausforderer" in text
    assert _size_klartext(_RAW_SEGMENT[0]) in text
    assert "seit 1 Lauf" in text


def test_build_memo_hysteresis_n_is_configurable():
    """hysteresis_n=1 -> sofortiger Wechsel wie ohne Hysterese."""
    history = [_history_entry(1, datetime(2026, 8, 5), _OTHER_SEGMENT)]
    memo = build_memo(
        _home_matrix(), _anchors(), data_age_days=2, history=history, hysteresis_n=1,
        run_date=datetime(2026, 8, 10),
    )
    assert memo.verdict_luxury_class == _RAW_SEGMENT[1]
    assert "geändert am 10.08.2026" in memo.changelog.plain_text


def test_build_memo_exposes_raw_segment_and_metrics_for_persistence():
    """compute_memo braucht die ROHEN Werte (unabhängig von der Hysterese-
    Haltung), um record_recommendation() aufzurufen."""
    history = [_history_entry(1, datetime(2026, 8, 5), _OTHER_SEGMENT)]
    memo = build_memo(_home_matrix(), _anchors(), data_age_days=2, history=history)
    assert memo.raw_verdict_size_class == _RAW_SEGMENT[0]
    assert memo.raw_verdict_luxury_class == _RAW_SEGMENT[1]
    assert memo.raw_score is not None
    assert memo.raw_multiplier is not None


# ---------------------------------------------------------------------------
# Task 3 (Memo-Review 11.08.2026): Vertrauensstufe an Multiplikator gekoppelt
# ---------------------------------------------------------------------------


def test_build_memo_confidence_downgrades_when_multiplier_too_low():
    """1,1x Median (Kapitel-2-Chip) darf trotz frischer Daten + Velocity
    nicht 'belastbar' ergeben."""
    memo = build_memo(
        _home_matrix_with_velocity(), _anchors_with_velocity(),
        data_age_days=2, velocity_available=True,
    )
    # 5.0 / Median(2.0,3.0) je nach Zellen -> in diesem Fixture liegt der
    # Multiplikator weit über der Schwelle, siehe Gegentest unten für den
    # Downgrade-Fall über eine explizite min_confidence_multiplier-Anhebung.
    memo_high_bar = build_memo(
        _home_matrix_with_velocity(), _anchors_with_velocity(),
        data_age_days=2, velocity_available=True, min_confidence_multiplier=100.0,
    )
    assert memo_high_bar.confidence != CONFIDENCE_BELASTBAR
    assert memo_high_bar.confidence == CONFIDENCE_SOLIDE


def test_build_memo_confidence_reason_names_multiplier_gap_in_risk_chapter():
    memo = build_memo(
        _home_matrix_with_velocity(), _anchors_with_velocity(),
        data_age_days=2, velocity_available=True, min_confidence_multiplier=100.0,
    )
    risk = memo.chapters[-1].plain_text
    assert "belastbar" in risk
    assert "100" in risk or "100.0" in risk


# ---------------------------------------------------------------------------
# compute_memo-Integration: Changelog + Hysterese über echte CrawlRuns
# ---------------------------------------------------------------------------

from airbi.db.models import RecommendationRun


def _mk_run_with_listings(session, cfg, run_id_prefix, started_at, size_class, bedrooms, n=4):
    run = CrawlRun(search_config_id=cfg.id, status="completed", started_at=started_at)
    session.add(run)
    session.flush()
    for i in range(n):
        listing = _mk_listing(
            session, f"{run_id_prefix}-{i}", 38.7390 + i * 0.0003, -9.1044,
            size_class=size_class, bedrooms=bedrooms,
        )
        session.add(Snapshot(listing_id=listing.id, crawl_run_id=run.id,
                             price=Decimal("100"), review_count=30))
    session.flush()
    return run


def _mk_two_segment_run(session, cfg, run_id_prefix, started_at, *, one_br_reviews, two_br_reviews, n=4):
    """Ein CrawlRun mit BEIDEN Segmenten (1BR und 2BR) belegt -- damit ein
    'Wechsel der roh stärksten Zelle' zwischen Läufen simuliert werden kann,
    ohne dass das jeweils andere Segment auf n=0 fällt (das würde die
    Hysterese-Fallback-Logik für 'Segment aus der Matrix verschwunden'
    auslösen, nicht den normalen Wechsel-Pfad)."""
    run = CrawlRun(search_config_id=cfg.id, status="completed", started_at=started_at)
    session.add(run)
    session.flush()
    for i in range(n):
        listing = _mk_listing(session, f"{run_id_prefix}-1br-{i}", 38.7390 + i * 0.0003, -9.1044,
                              size_class="1BR", bedrooms=1)
        session.add(Snapshot(listing_id=listing.id, crawl_run_id=run.id,
                             price=Decimal("100"), review_count=one_br_reviews))
    for i in range(n):
        listing = _mk_listing(session, f"{run_id_prefix}-2br-{i}", 38.7395 + i * 0.0003, -9.1044,
                              size_class="2BR", bedrooms=2)
        session.add(Snapshot(listing_id=listing.id, crawl_run_id=run.id,
                             price=Decimal("150"), review_count=two_br_reviews))
    session.flush()
    return run


def test_compute_memo_persists_recommendation_idempotently(db_session):
    cfg = SearchConfig(name="Memo-Persist-Test", city_slug="lisboa",
                       center_lat=38.7390, center_lng=-9.1044, home_radius_km=2.0)
    db_session.add(cfg)
    db_session.flush()
    run = _mk_run_with_listings(db_session, cfg, "p", datetime(2026, 8, 10), "1BR", 1)

    compute_memo(db_session, cfg, run)
    compute_memo(db_session, cfg, run)   # Dashboard-Reload -- kein Doppel-Eintrag

    rows = db_session.query(RecommendationRun).filter_by(search_config_id=cfg.id).all()
    assert len(rows) == 1


def test_compute_memo_holds_then_switches_recommendation_across_runs(db_session):
    """End-to-End über drei CrawlRuns: Lauf 1 setzt 1BR (stärker), Lauf 2
    dreht das Kräfteverhältnis (2BR roh vorn, aber erst 1x) -> Empfehlung
    bleibt 1BR mit Herausforderer-Hinweis, Lauf 3 bestätigt 2BR ein zweites
    Mal in Folge -> expliziter Wechsel."""
    cfg = SearchConfig(
        name="Memo-Hysterese-E2E", city_slug="lisboa",
        center_lat=38.7390, center_lng=-9.1044, home_radius_km=2.0,
    )
    db_session.add(cfg)
    db_session.flush()

    run1 = _mk_two_segment_run(db_session, cfg, "r1", datetime(2026, 7, 30),
                               one_br_reviews=40, two_br_reviews=5)
    memo1 = compute_memo(db_session, cfg, run1)
    assert memo1.verdict_size_class == "1BR"
    assert memo1.changelog is None   # erster Lauf, kein Vergleichswert

    run2 = _mk_two_segment_run(db_session, cfg, "r2", datetime(2026, 8, 5),
                               one_br_reviews=30, two_br_reviews=45)
    memo2 = compute_memo(db_session, cfg, run2)
    assert memo2.verdict_size_class == "1BR"        # gehalten
    assert memo2.raw_verdict_size_class == "2BR"     # aber roh bereits vorn
    assert memo2.changelog is not None
    assert "Herausforderer" in memo2.changelog.plain_text
    assert "geändert" not in memo2.changelog.plain_text

    run3 = _mk_two_segment_run(db_session, cfg, "r3", datetime(2026, 8, 10),
                               one_br_reviews=30, two_br_reviews=50)
    memo3 = compute_memo(db_session, cfg, run3)
    assert memo3.verdict_size_class == "2BR"
    assert memo3.changelog is not None
    assert "geändert am 10.08.2026" in memo3.changelog.plain_text


def test_compute_memo_reads_hysteresis_n_from_classification_config(db_session):
    """hysteresis_n=1 in der SearchConfig -> sofortiger Wechsel, keine
    Haltephase (Konfigurierbarkeit laut Briefing)."""
    cfg = SearchConfig(
        name="Memo-Hysterese-Config-Test", city_slug="lisboa",
        center_lat=38.7390, center_lng=-9.1044, home_radius_km=2.0,
        classification_config={"hysteresis_n": 1},
    )
    db_session.add(cfg)
    db_session.flush()

    run1 = _mk_two_segment_run(db_session, cfg, "c1", datetime(2026, 7, 30),
                               one_br_reviews=40, two_br_reviews=5)
    compute_memo(db_session, cfg, run1)

    run2 = _mk_two_segment_run(db_session, cfg, "c2", datetime(2026, 8, 5),
                               one_br_reviews=30, two_br_reviews=45)
    memo2 = compute_memo(db_session, cfg, run2)
    assert memo2.verdict_size_class == "2BR"   # sofort gewechselt
