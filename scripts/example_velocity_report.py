"""Beleg-Skript (nicht Teil der Test-Suite): rendert das Investment-Memo
gegen die ECHTE lokale Postgres-DB und druckt Kapitel 2 + die Velocity-Werte
je Zelle der Segment-Matrix — Beweis, dass die Snapshot-Zeitreihe seit
01.06.2026 fürs Velocity-Modul (Teilprojekt 3) trägt.

Aufruf: uv run python scripts/example_velocity_report.py
"""

from __future__ import annotations

from airbi.db.models import SearchConfig
from airbi.db.session import SessionLocal
from airbi.insights.memo import compute_memo
from airbi.insights.segment_matrix import (
    LUXURY_CLASSES,
    SIZE_CLASSES,
    compute_segment_matrix,
    latest_completed_run,
)


def main() -> None:
    session = SessionLocal()
    try:
        config = session.query(SearchConfig).filter_by(name="Marvila Slice 1").one()
        run = latest_completed_run(session, config)
        print(f"SearchConfig: {config.name}  |  CrawlRun: {run.id} ({run.started_at})")
        print()

        matrix = compute_segment_matrix(session, config, config.home_radius_km or 2.0, run)
        print(f"Heimmarkt-Matrix ({matrix.radius_km} km um {matrix.center_label}):")
        print(f"  listing_count={matrix.listing_count}  best_cell={matrix.best_cell}")
        print(f"  velocity_available={matrix.velocity_available}")
        print()
        print(f"{'Größe':<8} {'Klasse':<9} {'n':>4} {'score':>8} {'velocity':>10} {'velocity_n':>11}")
        for size in SIZE_CLASSES:
            for lux in LUXURY_CLASSES:
                cell = matrix.cell(size, lux)
                if cell.n == 0:
                    continue
                score = f"{cell.score:.1f}" if cell.score is not None else "-"
                vel = f"{cell.velocity:.2f}" if cell.velocity is not None else "-"
                print(f"{size:<8} {lux:<9} {cell.n:>4} {score:>8} {vel:>10} {cell.velocity_n:>11}")
        print()

        memo = compute_memo(session, config, run)
        print(f"Memo-Vertrauen: {memo.confidence}  (velocity_available={matrix.velocity_available})")
        print()
        for ch in memo.chapters:
            print(f"--- {ch.number} {ch.title} ---")
            print(ch.plain_text)
            print()
    finally:
        session.close()


if __name__ == "__main__":
    main()
