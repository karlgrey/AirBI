"""Tests für die harte Browser-Deadline (#151 Datenuhr-Resilienz)."""

import time

from airbi.scraper.watchdog import hard_deadline


def test_on_timeout_feuert_wenn_deadline_ueberschritten():
    fired = []
    with hard_deadline(0.05, lambda: fired.append(True)) as timed_out:
        time.sleep(0.2)
    assert fired == [True]
    assert timed_out.is_set()


def test_on_timeout_feuert_nicht_bei_rechtzeitigem_ende():
    fired = []
    with hard_deadline(0.5, lambda: fired.append(True)) as timed_out:
        pass
    time.sleep(0.1)  # Watchdog-Thread hätte Zeit zu feuern, darf aber nicht
    assert fired == []
    assert not timed_out.is_set()


def test_exception_im_body_setzt_deadline_trotzdem_zurueck():
    fired = []
    try:
        with hard_deadline(0.5, lambda: fired.append(True)):
            raise ValueError("boom")
    except ValueError:
        pass
    time.sleep(0.1)
    assert fired == []


def test_fehler_im_on_timeout_callback_bleibt_im_watchdog_thread():
    def kaputt():
        raise RuntimeError("kill fehlgeschlagen")

    # Darf weder den Body noch den Interpreter abschießen.
    with hard_deadline(0.05, kaputt) as timed_out:
        time.sleep(0.2)
    assert timed_out.is_set()
