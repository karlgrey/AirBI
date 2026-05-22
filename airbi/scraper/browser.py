from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from playwright.sync_api import BrowserContext, sync_playwright

# Persistenter Profil-Ordner -> Session/Cookies überleben Läufe (Spec §7).
DEFAULT_USER_DATA_DIR = Path(".playwright/airbi-profile")

# Realistischer Desktop-Fingerprint.
_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
_VIEWPORT = {"width": 1440, "height": 900}

# Entfernt das auffälligste Automations-Signal (navigator.webdriver).
_STEALTH_INIT_SCRIPT = """
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
"""


@contextmanager
def browser_context(
    user_data_dir: Path | str = DEFAULT_USER_DATA_DIR,
    headless: bool = True,
    proxy: dict | None = None,
) -> Iterator[BrowserContext]:
    """Startet einen Stealth-gehärteten, persistenten Chromium-Context.

    `proxy` ist die Transport-Schicht: in Slice 1 None (direkt). Zum
    Nachrüsten eines Residential-Proxys später genügt hier ein dict
    wie {"server": "http://host:port", "username": ..., "password": ...}
    — kein weiterer Umbau nötig."""
    Path(user_data_dir).mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(user_data_dir),
            headless=headless,
            user_agent=_USER_AGENT,
            viewport=_VIEWPORT,
            locale="en-US",
            timezone_id="Europe/Lisbon",
            proxy=proxy,
        )
        context.add_init_script(_STEALTH_INIT_SCRIPT)
        try:
            yield context
        finally:
            context.close()
