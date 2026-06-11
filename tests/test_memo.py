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
        data_age_days=3, n=5, min_sample=3, velocity_available=True
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


# ---------------------------------------------------------------------------
# Task 4: Kapitel-Generator build_memo + Jargon-Vertrag
# ---------------------------------------------------------------------------

from airbi.insights.segment_matrix import build_segment_matrix, ListingRow
from airbi.insights.memo import build_memo


def _row(airbnb_id, size_class, price, review_count):
    return ListingRow(
        airbnb_id=airbnb_id, title=f"L{airbnb_id}", url=f"https://x/{airbnb_id}",
        size_class=size_class, price=Decimal(str(price)),
        review_count=review_count, rating=4.8,
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


def test_build_memo_risk_chapter_names_age_proxy_and_al():
    memo = build_memo(_home_matrix(), _anchors(), data_age_days=9)
    risk = memo.chapters[-1].plain_text
    assert "9 Tage" in risk
    assert "Indikator" in risk         # Proxy-Annahme
    assert "AL-Lizenz" in risk         # ungeprüft (al_zone_status=None)


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
