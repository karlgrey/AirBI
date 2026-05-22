import random
import time
from collections.abc import Callable

# Default-Spannen (Sekunden) für menschliches Pacing. Bewusst großzügig.
DEFAULT_ACTION_DELAY = (1.5, 4.0)   # zwischen normalen Aktionen (Scroll, Klick)
DEFAULT_PAGE_DELAY = (4.0, 9.0)     # zwischen Ergebnisseiten
DEFAULT_LONG_PAUSE = (15.0, 35.0)   # gelegentliche längere Pause


def pick_delay(
    min_seconds: float, max_seconds: float, rng: random.Random | None = None
) -> float:
    """Wählt eine zufällige Dauer im Intervall [min, max]. Reine Funktion."""
    generator = rng or random
    return generator.uniform(min_seconds, max_seconds)


def human_delay(
    min_seconds: float,
    max_seconds: float,
    rng: random.Random | None = None,
    sleeper: Callable[[float], None] = time.sleep,
) -> float:
    """Wählt eine Dauer und schläft sie ab. Gibt die gewählte Dauer zurück.
    `sleeper` ist injizierbar, damit Tests nicht real warten müssen."""
    duration = pick_delay(min_seconds, max_seconds, rng=rng)
    sleeper(duration)
    return duration
