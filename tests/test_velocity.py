"""Velocity-Modul (Teilprojekt 3, Spec-Nachtrag 2026-07-30).

Review-Velocity = Buchungs-Rate-Signal aus dem Delta der Bewertungsanzahl
zwischen Snapshots eines Listings (Briefing §3). Erst über mehrere Wochen
Snapshot-Historie belastbar -> `MIN_SPAN_DAYS`-Schwelle."""

from datetime import datetime, timedelta

from airbi.db.models import CrawlRun, Listing, SearchConfig, Snapshot
from airbi.insights.velocity import (
    MIN_SPAN_DAYS,
    attach_velocities,
    compute_velocities,
    compute_weekly_velocity,
)
from airbi.insights.segment_matrix import ListingRow
from decimal import Decimal


def _t(days_ago):
    return datetime(2026, 7, 30) - timedelta(days=days_ago)


def test_weekly_velocity_needs_at_least_two_snapshots():
    assert compute_weekly_velocity([(_t(0), 10)]) is None
    assert compute_weekly_velocity([]) is None


def test_weekly_velocity_needs_minimum_span():
    # Nur 5 Tage Spanne < MIN_SPAN_DAYS -> kein belastbares Signal.
    snaps = [(_t(5), 10), (_t(0), 12)]
    assert compute_weekly_velocity(snaps) is None


def test_weekly_velocity_computes_rate_per_week():
    # 21 Tage Spanne, +21 Reviews -> 7 Reviews/Woche.
    snaps = [(_t(21), 10), (_t(0), 31)]
    assert compute_weekly_velocity(snaps) == 7.0


def test_weekly_velocity_sorts_unordered_input():
    snaps = [(_t(0), 31), (_t(21), 10)]
    assert compute_weekly_velocity(snaps) == 7.0


def test_weekly_velocity_clips_negative_delta_to_zero():
    # Rückläufige Review-Anzahl (z.B. Parser-Rauschen) -> nie negative Velocity.
    snaps = [(_t(21), 40), (_t(0), 31)]
    assert compute_weekly_velocity(snaps) == 0.0


def test_weekly_velocity_uses_first_and_last_of_multiple_snapshots():
    snaps = [(_t(21), 10), (_t(14), 15), (_t(7), 9999), (_t(0), 31)]
    assert compute_weekly_velocity(snaps) == 7.0


def test_min_span_days_constant_matches_briefing_threshold():
    # Wiki-Stand (13.07.2026): "571 Listings >=21 Tage Spanne" war die
    # Referenzschwelle fuer Velocity-Reife.
    assert MIN_SPAN_DAYS == 21


def _mk_listing(session, airbnb_id, lat=38.7390, lng=-9.1044):
    listing = Listing(
        airbnb_id=airbnb_id, url=f"https://x/{airbnb_id}", title=f"L{airbnb_id}",
        city_slug="lisboa", lat=lat, lng=lng, size_class="1BR",
    )
    session.add(listing)
    session.flush()
    return listing


def _mk_run(session, cfg, started_at):
    run = CrawlRun(search_config_id=cfg.id, status="completed", started_at=started_at)
    session.add(run)
    session.flush()
    return run


def test_compute_velocities_returns_only_qualifying_listings(db_session):
    cfg = SearchConfig(name="Velocity-Test", city_slug="lisboa")
    db_session.add(cfg)
    db_session.flush()

    ok = _mk_listing(db_session, "ok1")
    thin = _mk_listing(db_session, "thin1")   # nur ein Snapshot

    run_old = _mk_run(db_session, cfg, _t(21))
    run_new = _mk_run(db_session, cfg, _t(0))

    db_session.add_all([
        Snapshot(listing_id=ok.id, crawl_run_id=run_old.id,
                 captured_at=_t(21), price=Decimal("100"), review_count=10),
        Snapshot(listing_id=ok.id, crawl_run_id=run_new.id,
                 captured_at=_t(0), price=Decimal("100"), review_count=31),
        Snapshot(listing_id=thin.id, crawl_run_id=run_new.id,
                 captured_at=_t(0), price=Decimal("100"), review_count=5),
    ])
    db_session.flush()

    result = compute_velocities(db_session, [ok.id, thin.id])
    assert result[ok.id] == 7.0
    assert thin.id not in result


def test_attach_velocities_sets_weekly_velocity_on_matching_rows(db_session):
    cfg = SearchConfig(name="Attach-Test", city_slug="lisboa")
    db_session.add(cfg)
    db_session.flush()
    listing = _mk_listing(db_session, "att1")
    run_old = _mk_run(db_session, cfg, _t(21))
    run_new = _mk_run(db_session, cfg, _t(0))
    db_session.add_all([
        Snapshot(listing_id=listing.id, crawl_run_id=run_old.id,
                 captured_at=_t(21), price=Decimal("100"), review_count=10),
        Snapshot(listing_id=listing.id, crawl_run_id=run_new.id,
                 captured_at=_t(0), price=Decimal("100"), review_count=31),
    ])
    db_session.flush()

    row = ListingRow(
        airbnb_id="att1", title="T", url="u", size_class="1BR",
        price=Decimal("100"), review_count=31, rating=4.8, listing_id=listing.id,
    )
    other = ListingRow(
        airbnb_id="noid", title="T2", url="u2", size_class="1BR",
        price=Decimal("100"), review_count=5, rating=4.5, listing_id=None,
    )
    attach_velocities(db_session, [row, other])
    assert row.weekly_velocity == 7.0
    assert other.weekly_velocity is None
