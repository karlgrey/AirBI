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
