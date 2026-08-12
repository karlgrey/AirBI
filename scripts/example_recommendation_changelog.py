"""Beleg-Skript (nicht Teil der Test-Suite): zeigt Empfehlungs-Changelog +
Hysterese + die an den Multiplikator gekoppelte Vertrauensstufe am Memo
(Memo-Review 11.08.2026, SmartTasks #151).

Simuliert drei CrawlRuns einer synthetischen SearchConfig gegen die
Test-DB (`settings.test_database_url`): Lauf 1 setzt "1 Schlafzimmer" als
Empfehlung, Lauf 2 dreht das Kräfteverhältnis auf "2 Schlafzimmer" (aber
nur einmal -> die Hysterese hält die alte Empfehlung, weist aber den
Herausforderer aus), Lauf 3 bestätigt "2 Schlafzimmer" ein zweites Mal in
Folge -> die Empfehlung wechselt jetzt EXPLIZIT ausgewiesen im Changelog.

Räumt seine synthetische SearchConfig am Ende wieder auf, damit die
geteilte Test-DB sauber bleibt.

Aufruf: uv run python scripts/example_recommendation_changelog.py
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from airbi.config import settings
from airbi.db import models  # noqa: F401 -- Modelle registrieren bei Base.metadata
from airbi.db.models import CrawlRun, Listing, RecommendationRun, SearchConfig, Snapshot
from airbi.db.session import Base, make_engine, make_session_factory
from airbi.insights.memo import build_memo
from airbi.insights.memo import compute_memo
from airbi.insights.segment_matrix import ListingRow, build_segment_matrix

CONFIG_NAME = "Beleg-Empfehlungs-Changelog (Skript, löscht sich selbst)"


def _print_confidence_multiplier_demo() -> None:
    """Task 3 (Vertrauensstufe an Multiplikator gekoppelt) braucht kein
    CrawlRun-Setup -- reiner build_memo()-Aufruf reicht, um den Gate-Effekt
    zu zeigen (1,1x Median reicht nicht für 'belastbar')."""
    rows = [
        ListingRow(airbnb_id=f"v{i}", title=f"L{i}", url=f"https://x/{i}",
                  size_class="1BR", price=Decimal("100"), review_count=30,
                  rating=4.8, weekly_velocity=v)
        for i, v in enumerate([0.6, 0.7, 0.5])   # Best-Cell: Ø 0.6/Woche
    ] + [
        ListingRow(airbnb_id=f"o{i}", title=f"O{i}", url=f"https://x/o{i}",
                  size_class="2BR", price=Decimal("200"), review_count=10,
                  rating=4.5, weekly_velocity=v)
        for i, v in enumerate([0.5, 0.6])   # lokaler Median liegt bei ~0.55
    ]
    matrix = build_segment_matrix(rows, config={}, radius_km=2.0,
                                  center_label="Beleg-Objekt", crawl_run_id=None)

    memo_default = build_memo(matrix, [], data_age_days=2, velocity_available=True)
    memo_lowered_bar = build_memo(matrix, [], data_age_days=2, velocity_available=True,
                                  min_confidence_multiplier=1.0)
    print("=== Task 3: Vertrauensstufe an Multiplikator gekoppelt ===")
    print(f"Best-Cell-Multiplikator liegt bei ~1,04x des lokalen Medians (nahe am Rauschen).")
    print(f"Default-Schwelle 1.3x -> {memo_default.confidence} (NICHT belastbar trotz frischer Daten):")
    print(f"  {memo_default.chapters[-1].plain_text}")
    print(f"Konfigurierbarkeit: min_confidence_multiplier=1.0 -> {memo_lowered_bar.confidence}")
    print()


def _mk_listing(session, airbnb_id, lat, lng, size_class, bedrooms):
    listing = Listing(
        airbnb_id=airbnb_id, url=f"https://x/{airbnb_id}", title=f"L{airbnb_id}",
        city_slug="lisboa", lat=lat, lng=lng,
        size_class=size_class, bedrooms=bedrooms,
    )
    session.add(listing)
    session.flush()
    return listing


def _mk_two_segment_run(session, cfg, prefix, started_at, *, one_br_reviews, two_br_reviews, n=4):
    run = CrawlRun(search_config_id=cfg.id, status="completed", started_at=started_at)
    session.add(run)
    session.flush()
    for i in range(n):
        listing = _mk_listing(session, f"{prefix}-1br-{i}", 38.7390 + i * 0.0003, -9.1044, "1BR", 1)
        session.add(Snapshot(listing_id=listing.id, crawl_run_id=run.id,
                             price=Decimal("100"), review_count=one_br_reviews))
    for i in range(n):
        listing = _mk_listing(session, f"{prefix}-2br-{i}", 38.7395 + i * 0.0003, -9.1044, "2BR", 2)
        session.add(Snapshot(listing_id=listing.id, crawl_run_id=run.id,
                             price=Decimal("150"), review_count=two_br_reviews))
    session.flush()
    return run


def _print_memo(label: str, memo) -> None:
    print(f"=== {label} ===")
    print(f"Urteil: {memo.verdict_size_label} · {memo.verdict_luxury_class}")
    dots = "●" * memo.confidence_dots + "○" * (3 - memo.confidence_dots)
    print(f"Vertrauen: {dots} {memo.confidence}")
    if memo.changelog:
        print(f"Empfehlungs-Verlauf: {memo.changelog.plain_text}")
    else:
        print("Empfehlungs-Verlauf: (kein Vergleichswert -- erster Lauf)")
    for ch in memo.chapters:
        if ch.title == "Wo die Nachfrage hinläuft":
            print(f"Kapitel {ch.number} — {ch.title}: {ch.plain_text}")
    print()


def main() -> None:
    _print_confidence_multiplier_demo()

    engine = make_engine(settings.test_database_url)
    Base.metadata.create_all(engine)  # idempotent, legt recommendation_run mit an
    session = make_session_factory(engine)()
    try:
        session.query(SearchConfig).filter_by(name=CONFIG_NAME).delete()
        session.commit()

        cfg = SearchConfig(
            name=CONFIG_NAME, city_slug="lisboa",
            center_lat=38.7390, center_lng=-9.1044, home_radius_km=2.0,
        )
        session.add(cfg)
        session.flush()

        # Lauf 1 (analog 30.07.): 1BR klar stärker -> Empfehlung "1 Schlafzimmer".
        run1 = _mk_two_segment_run(session, cfg, "r1", datetime(2026, 7, 30),
                                   one_br_reviews=40, two_br_reviews=5)
        memo1 = compute_memo(session, cfg, run1)
        _print_memo("Lauf 1 — 30.07.2026", memo1)

        # Lauf 2 (analog 10.08., der ungewiesene Wechsel im Review): 2BR roh
        # vorn, aber erst 1x -> Hysterese hält die alte Empfehlung.
        run2 = _mk_two_segment_run(session, cfg, "r2", datetime(2026, 8, 5),
                                   one_br_reviews=30, two_br_reviews=45)
        memo2 = compute_memo(session, cfg, run2)
        _print_memo("Lauf 2 — 05.08.2026", memo2)

        # Lauf 3: 2BR bestätigt sich ein zweites Mal in Folge -> Wechsel,
        # jetzt EXPLIZIT im Changelog ausgewiesen statt still zu passieren.
        run3 = _mk_two_segment_run(session, cfg, "r3", datetime(2026, 8, 10),
                                   one_br_reviews=30, two_br_reviews=50)
        memo3 = compute_memo(session, cfg, run3)
        _print_memo("Lauf 3 — 10.08.2026", memo3)

        print("Risiko-Kapitel Lauf 3 (Tag/Tage-Fix + Multiplikator-Begründung, falls gedeckelt):")
        print(memo3.chapters[-1].plain_text)
    finally:
        # Aufräumen: Skript soll die geteilte Test-DB nicht dauerhaft verändern.
        session.query(RecommendationRun).filter(
            RecommendationRun.search_config_id == cfg.id
        ).delete()
        session.query(Snapshot).filter(
            Snapshot.crawl_run_id.in_(
                session.query(CrawlRun.id).filter(CrawlRun.search_config_id == cfg.id)
            )
        ).delete(synchronize_session=False)
        session.query(CrawlRun).filter(CrawlRun.search_config_id == cfg.id).delete()
        session.query(Listing).filter(Listing.airbnb_id.like("r%-1br-%") | Listing.airbnb_id.like("r%-2br-%")).delete(synchronize_session=False)
        session.query(SearchConfig).filter_by(name=CONFIG_NAME).delete()
        session.commit()
        session.close()


if __name__ == "__main__":
    main()
