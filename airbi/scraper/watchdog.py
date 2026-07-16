"""Harte Deadline für Browser-Operationen (#151 Datenuhr-Resilienz).

Playwright-Evaluate-Calls haben KEIN Timeout: Dreht eine Seite eine
JS-Endlosschleife (Renderer 100 % CPU), wartet der Treiber ewig — Vorfall
16.07.2026: Detail-Refresh 69/639 hing 7 h auf einem Airbnb-Listing.
`hard_deadline` erzwingt die Obergrenze von außen: Nach Ablauf feuert
`on_timeout` (im Crawl: Chromium-Prozesse des Profils killen); der
hängende Playwright-Call schlägt dann als TargetClosedError auf und wird
vom regulären Except der Refresh-Schleife gefangen.
"""

from __future__ import annotations

import logging
import subprocess
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager

logger = logging.getLogger(__name__)


@contextmanager
def hard_deadline(seconds: float, on_timeout: Callable[[], None]) -> Iterator[threading.Event]:
    """Führt den Body unter einer harten Deadline aus.

    Läuft der Body länger als ``seconds``, wird ``on_timeout`` im
    Watchdog-Thread aufgerufen (Fehler dort werden geloggt, nie geworfen).
    Yields das ``fired``-Event: gesetzt = Deadline wurde gerissen.
    """
    done = threading.Event()
    fired = threading.Event()

    def _watch() -> None:
        if not done.wait(seconds):
            fired.set()
            try:
                on_timeout()
            except Exception:  # noqa: BLE001 — Watchdog darf nie selbst sterben
                logger.exception("Watchdog: on_timeout-Callback fehlgeschlagen")

    thread = threading.Thread(target=_watch, name="airbi-hard-deadline", daemon=True)
    thread.start()
    try:
        yield fired
    finally:
        done.set()


def kill_profile_browsers(profile_marker: str = "airbi-profile") -> None:
    """Killt alle Chromium-Prozesse, deren Kommandozeile das Profil trägt.

    Grob, aber sicher gefangen: Der laufende Playwright-Call bricht mit
    TargetClosedError ab, der nächste Browser-Batch startet frisch.
    """
    logger.warning("Watchdog: kille Chromium-Prozesse (%s) — Seite hing über der Deadline", profile_marker)
    subprocess.run(["pkill", "-f", profile_marker], check=False)
