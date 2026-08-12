"""Empfehlungs-Historie: Changelog + Hysterese fürs Investment-Memo
(SmartTasks #151, Memo-Review 11.08.2026).

Problem: das Memo wechselte am 10.08. still von "3+ Schlafzimmer · Mid" zu
"1 Schlafzimmer · Luxury", ohne den Wechsel auszuweisen — ein
Glaubwürdigkeitsproblem für ein Investment-Memo. Dieses Modul liefert:

- Persistenz der Empfehlung je Memo-Lauf (`RecommendationRun`, ein
  Datensatz je SearchConfig+CrawlRun, idempotent).
- Hysterese: ein neues Segment wird erst zur ANGEZEIGTEN Empfehlung, wenn es
  `hysteresis_n` aufeinanderfolgende Läufe lang das rohe Best-Cell-Segment
  war (Default 2).

Drei Schichten wie `segment_matrix.py` / `velocity.py`:
- Datacontainer: RecommendationEntry (Eingabe für den reinen Kern).
- Reiner Kern: `apply_hysteresis` — keine DB.
- DB-Anbindung: `record_recommendation` / `load_recommendation_history`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from airbi.db.models import CrawlRun, RecommendationRun, SearchConfig

# Default aus dem Briefing (Memo-Review 11.08.2026): erst nach 2 Läufen in
# Folge wechselt die angezeigte Empfehlung.
DEFAULT_HYSTERESIS_N = 2


@dataclass
class RecommendationEntry:
    """Ein vergangener Memo-Lauf, wie ihn `apply_hysteresis` und der
    Changelog-Text brauchen. `run_date` ist das Datum des CrawlRuns (nicht
    der Zeitpunkt der DB-Schreibung)."""

    crawl_run_id: int
    run_date: datetime | None
    raw_size_class: str
    raw_luxury_class: str
    displayed_size_class: str
    displayed_luxury_class: str


@dataclass
class HysteresisResult:
    """Ergebnis der Hysterese-Filterung für den aktuellen Lauf."""

    displayed_size_class: str
    displayed_luxury_class: str
    switched: bool
    previous_size_class: str | None = None
    previous_luxury_class: str | None = None
    challenger_size_class: str | None = None
    challenger_luxury_class: str | None = None
    challenger_streak: int = 0


def apply_hysteresis(
    raw_size_class: str,
    raw_luxury_class: str,
    history: list[RecommendationEntry],
    *,
    hysteresis_n: int = DEFAULT_HYSTERESIS_N,
) -> HysteresisResult:
    """Wendet die Hysterese-Regel auf das rohe Best-Cell-Segment des
    aktuellen Laufs an.

    `history` muss älteste → neueste Reihenfolge haben und darf den
    aktuellen Lauf NICHT enthalten (das letzte Element ist der unmittelbar
    vorangegangene Lauf).

    - Ohne Historie (erster Lauf): das rohe Segment wird direkt angezeigt.
    - Stimmt das rohe Segment mit der zuletzt ANGEZEIGTEN Empfehlung
      überein: keine Änderung, kein Herausforderer.
    - Andernfalls ist das rohe Segment ein Herausforderer. Die Streak zählt
      rückwärts durch die Historie, wie viele Läufe IN FOLGE (den aktuellen
      eingeschlossen) genau dieses Segment das rohe Best-Cell-Segment war.
      Erreicht die Streak `hysteresis_n`, wechselt die angezeigte Empfehlung
      (`switched=True`); sonst bleibt die bisherige Empfehlung stehen und
      der Herausforderer wird mit seiner Streak ausgewiesen.
    """
    if not history:
        return HysteresisResult(
            displayed_size_class=raw_size_class,
            displayed_luxury_class=raw_luxury_class,
            switched=False,
        )

    last = history[-1]
    prev_size = last.displayed_size_class
    prev_lux = last.displayed_luxury_class

    if (raw_size_class, raw_luxury_class) == (prev_size, prev_lux):
        return HysteresisResult(
            displayed_size_class=prev_size,
            displayed_luxury_class=prev_lux,
            switched=False,
        )

    streak = 1  # der aktuelle Lauf zählt mit
    for entry in reversed(history):
        if (entry.raw_size_class, entry.raw_luxury_class) == (
            raw_size_class,
            raw_luxury_class,
        ):
            streak += 1
        else:
            break

    if streak >= hysteresis_n:
        return HysteresisResult(
            displayed_size_class=raw_size_class,
            displayed_luxury_class=raw_luxury_class,
            switched=True,
            previous_size_class=prev_size,
            previous_luxury_class=prev_lux,
        )

    return HysteresisResult(
        displayed_size_class=prev_size,
        displayed_luxury_class=prev_lux,
        switched=False,
        challenger_size_class=raw_size_class,
        challenger_luxury_class=raw_luxury_class,
        challenger_streak=streak,
    )


def record_recommendation(
    session: Session,
    search_config: SearchConfig,
    crawl_run: CrawlRun,
    *,
    raw_size_class: str,
    raw_luxury_class: str,
    raw_score: float | None,
    raw_multiplier: float | None,
    used_velocity: bool,
    displayed_size_class: str,
    displayed_luxury_class: str,
    confidence: str,
) -> RecommendationRun:
    """Persistiert den Memo-Lauf idempotent — ein Datensatz je
    SearchConfig+CrawlRun (die Dashboard-Route ruft compute_memo bei jedem
    Reload neu auf, ohne dass sich der CrawlRun ändert)."""
    existing = session.execute(
        select(RecommendationRun).where(
            RecommendationRun.search_config_id == search_config.id,
            RecommendationRun.crawl_run_id == crawl_run.id,
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing

    row = RecommendationRun(
        search_config_id=search_config.id,
        crawl_run_id=crawl_run.id,
        raw_size_class=raw_size_class,
        raw_luxury_class=raw_luxury_class,
        raw_score=raw_score,
        raw_multiplier=raw_multiplier,
        used_velocity=used_velocity,
        displayed_size_class=displayed_size_class,
        displayed_luxury_class=displayed_luxury_class,
        confidence=confidence,
    )
    session.add(row)
    session.flush()
    return row


def load_recommendation_history(
    session: Session,
    search_config: SearchConfig,
    *,
    before_crawl_run: CrawlRun,
    limit: int = 20,
) -> list[RecommendationEntry]:
    """Vergangene Memo-Läufe dieser SearchConfig, älteste → neueste, ohne den
    übergebenen CrawlRun selbst. `limit` deckelt, wie weit zurück eine
    Herausforderer-Streak maximal gezählt werden kann."""
    stmt = (
        select(RecommendationRun, CrawlRun.started_at)
        .join(CrawlRun, CrawlRun.id == RecommendationRun.crawl_run_id)
        .where(RecommendationRun.search_config_id == search_config.id)
        .where(RecommendationRun.crawl_run_id != before_crawl_run.id)
        .order_by(CrawlRun.started_at.desc(), RecommendationRun.id.desc())
        .limit(limit)
    )
    rows = session.execute(stmt).all()
    entries = [
        RecommendationEntry(
            crawl_run_id=rec.crawl_run_id,
            run_date=started_at,
            raw_size_class=rec.raw_size_class,
            raw_luxury_class=rec.raw_luxury_class,
            displayed_size_class=rec.displayed_size_class,
            displayed_luxury_class=rec.displayed_luxury_class,
        )
        for rec, started_at in rows
    ]
    entries.reverse()  # -> älteste zuerst
    return entries
