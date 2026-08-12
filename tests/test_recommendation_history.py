from datetime import datetime, timedelta

from airbi.db.models import CrawlRun, SearchConfig
from airbi.insights.recommendation_history import (
    RecommendationEntry,
    apply_hysteresis,
    load_recommendation_history,
    record_recommendation,
)


def _entry(crawl_run_id, run_date, raw, displayed=None):
    """`raw`/`displayed` sind (size, lux)-Tupel; displayed=None -> = raw."""
    displayed = displayed or raw
    return RecommendationEntry(
        crawl_run_id=crawl_run_id,
        run_date=run_date,
        raw_size_class=raw[0],
        raw_luxury_class=raw[1],
        displayed_size_class=displayed[0],
        displayed_luxury_class=displayed[1],
    )


# ---------------------------------------------------------------------------
# apply_hysteresis (reiner Kern)
# ---------------------------------------------------------------------------


def test_apply_hysteresis_no_history_shows_raw_segment_immediately():
    result = apply_hysteresis("1BR", "Luxury", [])
    assert (result.displayed_size_class, result.displayed_luxury_class) == ("1BR", "Luxury")
    assert result.switched is False


def test_apply_hysteresis_same_as_last_displayed_is_unchanged():
    history = [_entry(1, datetime(2026, 7, 30), ("3BR+", "Mid"))]
    result = apply_hysteresis("3BR+", "Mid", history)
    assert result.displayed_size_class == "3BR+"
    assert result.switched is False
    assert result.challenger_size_class is None


def test_apply_hysteresis_holds_previous_recommendation_below_threshold():
    """Neues Segment war erst 1 Lauf lang vorn (< Default N=2) -> alte
    Empfehlung bleibt, Herausforderer wird ausgewiesen."""
    history = [_entry(1, datetime(2026, 7, 30), ("3BR+", "Mid"))]
    result = apply_hysteresis("1BR", "Luxury", history)
    assert (result.displayed_size_class, result.displayed_luxury_class) == ("3BR+", "Mid")
    assert result.switched is False
    assert (result.challenger_size_class, result.challenger_luxury_class) == ("1BR", "Luxury")
    assert result.challenger_streak == 1


def test_apply_hysteresis_switches_after_n_consecutive_raw_wins():
    """Herausforderer war in Lauf 2 UND Lauf 3 (aktuell) roh vorn -> Streak
    2 erreicht Default-Schwelle -> Wechsel."""
    history = [
        _entry(1, datetime(2026, 7, 30), ("3BR+", "Mid")),
        _entry(2, datetime(2026, 8, 5), ("1BR", "Luxury"), displayed=("3BR+", "Mid")),
    ]
    result = apply_hysteresis("1BR", "Luxury", history)
    assert (result.displayed_size_class, result.displayed_luxury_class) == ("1BR", "Luxury")
    assert result.switched is True
    assert (result.previous_size_class, result.previous_luxury_class) == ("3BR+", "Mid")


def test_apply_hysteresis_streak_resets_when_raw_flips_back():
    """Herausforderer führte in Lauf 2, aber Lauf 3 (roh) war wieder das
    alte Segment vorn -> Streak für den (neuen) Herausforderer in Lauf 4
    zählt nur 1, kein Wechsel."""
    history = [
        _entry(1, datetime(2026, 7, 30), ("3BR+", "Mid")),
        _entry(2, datetime(2026, 8, 5), ("1BR", "Luxury"), displayed=("3BR+", "Mid")),
        _entry(3, datetime(2026, 8, 8), ("3BR+", "Mid")),
    ]
    result = apply_hysteresis("1BR", "Luxury", history)
    assert result.switched is False
    assert result.challenger_streak == 1


def test_apply_hysteresis_configurable_n():
    """hysteresis_n=1 -> sofortiger Wechsel wie ohne Hysterese."""
    history = [_entry(1, datetime(2026, 7, 30), ("3BR+", "Mid"))]
    result = apply_hysteresis("1BR", "Luxury", history, hysteresis_n=1)
    assert result.switched is True
    assert result.displayed_size_class == "1BR"


def test_apply_hysteresis_configurable_n_higher_needs_more_runs():
    """hysteresis_n=3 -> nach 2 Läufen in Folge (Streak 2) noch kein Wechsel."""
    history = [
        _entry(1, datetime(2026, 7, 30), ("3BR+", "Mid")),
        _entry(2, datetime(2026, 8, 5), ("1BR", "Luxury"), displayed=("3BR+", "Mid")),
    ]
    result = apply_hysteresis("1BR", "Luxury", history, hysteresis_n=3)
    assert result.switched is False
    assert result.challenger_streak == 2


# ---------------------------------------------------------------------------
# record_recommendation / load_recommendation_history (DB-Anbindung)
# ---------------------------------------------------------------------------


def _mk_cfg_and_run(session, started_at=None):
    cfg = SearchConfig(name=f"RecHist-{started_at}", city_slug="lisboa",
                       center_lat=38.7390, center_lng=-9.1044)
    session.add(cfg)
    session.flush()
    run = CrawlRun(search_config_id=cfg.id, status="completed", started_at=started_at)
    session.add(run)
    session.flush()
    return cfg, run


def test_record_recommendation_persists_row(db_session):
    cfg, run = _mk_cfg_and_run(db_session, datetime(2026, 8, 10))
    row = record_recommendation(
        db_session, cfg, run,
        raw_size_class="1BR", raw_luxury_class="Luxury",
        raw_score=0.6, raw_multiplier=1.1, used_velocity=True,
        displayed_size_class="1BR", displayed_luxury_class="Luxury",
        confidence="solide Indizien",
    )
    assert row.id is not None
    assert row.search_config_id == cfg.id
    assert row.crawl_run_id == run.id


def test_record_recommendation_is_idempotent_per_config_and_run(db_session):
    """Die Dashboard-Route ruft compute_memo bei jedem Reload neu auf --
    zweimaliges Aufrufen für denselben CrawlRun darf keinen Doppel-Eintrag
    erzeugen."""
    cfg, run = _mk_cfg_and_run(db_session, datetime(2026, 8, 10))
    first = record_recommendation(
        db_session, cfg, run,
        raw_size_class="1BR", raw_luxury_class="Luxury",
        raw_score=0.6, raw_multiplier=1.1, used_velocity=True,
        displayed_size_class="1BR", displayed_luxury_class="Luxury",
        confidence="solide Indizien",
    )
    second = record_recommendation(
        db_session, cfg, run,
        raw_size_class="1BR", raw_luxury_class="Luxury",
        raw_score=0.6, raw_multiplier=1.1, used_velocity=True,
        displayed_size_class="1BR", displayed_luxury_class="Luxury",
        confidence="solide Indizien",
    )
    assert first.id == second.id

    history = load_recommendation_history(db_session, cfg, before_crawl_run=run)
    assert len(history) == 0   # der eigene Lauf zählt nicht als "Historie"


def test_load_recommendation_history_orders_oldest_first_and_excludes_current(db_session):
    cfg, run1 = _mk_cfg_and_run(db_session, datetime(2026, 7, 30))
    run2 = CrawlRun(search_config_id=cfg.id, status="completed", started_at=datetime(2026, 8, 5))
    db_session.add(run2)
    db_session.flush()
    run3 = CrawlRun(search_config_id=cfg.id, status="completed", started_at=datetime(2026, 8, 10))
    db_session.add(run3)
    db_session.flush()

    for run, seg in ((run1, ("3BR+", "Mid")), (run2, ("1BR", "Luxury"))):
        record_recommendation(
            db_session, cfg, run,
            raw_size_class=seg[0], raw_luxury_class=seg[1],
            raw_score=1.0, raw_multiplier=1.5, used_velocity=True,
            displayed_size_class=seg[0], displayed_luxury_class=seg[1],
            confidence="solide Indizien",
        )

    history = load_recommendation_history(db_session, cfg, before_crawl_run=run3)
    assert [(e.raw_size_class, e.raw_luxury_class) for e in history] == [
        ("3BR+", "Mid"), ("1BR", "Luxury"),
    ]
    assert history[0].run_date < history[1].run_date


def test_load_recommendation_history_respects_limit(db_session):
    cfg, run1 = _mk_cfg_and_run(db_session, datetime(2026, 1, 1))
    runs = [run1]
    for i in range(1, 5):
        r = CrawlRun(search_config_id=cfg.id, status="completed",
                    started_at=datetime(2026, 1, 1) + timedelta(days=i))
        db_session.add(r)
        db_session.flush()
        runs.append(r)
    for r in runs[:-1]:
        record_recommendation(
            db_session, cfg, r,
            raw_size_class="1BR", raw_luxury_class="Mid",
            raw_score=1.0, raw_multiplier=1.5, used_velocity=True,
            displayed_size_class="1BR", displayed_luxury_class="Mid",
            confidence="solide Indizien",
        )
    history = load_recommendation_history(db_session, cfg, before_crawl_run=runs[-1], limit=2)
    assert len(history) == 2
