# AirBI Slice 1 — Plan 2: Scraper Stufe A — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Den Stufe-A-Search-Crawl bauen — ein Playwright-gesteuerter Browser fängt die `StaysSearch`-JSON-Antworten von Airbnb für die Marvila+Beato-Bounding-Box ab; ein CLI-Befehl füllt die lokale Postgres-DB mit echten `Listing`- und `Snapshot`-Daten.

**Architecture:** Browser-Automation mit Playwright (echter Chromium, Stealth-gehärtet, persistenter Context). Der Browser löst die interne Such-API selbst aus; wir fangen die Antworten per Response-Interception ab. Ein reiner Parser übersetzt die JSON-Antwort in ein `ParsedListing`-Datenobjekt — gegen aufgezeichnete Fixtures testbar. Der Crawl-Orchestrator verwaltet den `CrawlRun`-Lebenszyklus, dedupliziert, ordnet Bezirke zu (`assign_district`), klassifiziert (`size_class`) und schreibt per Upsert in die DB. Eine Proxy-fähige Transport-Schicht ist vorbereitet, in Slice 1 aber „direkt" (kein Proxy).

**Tech Stack:** Python ≥3.11, `uv`, Playwright (Chromium), SQLAlchemy 2.0 (Fundament aus Plan 1), pytest.

**Bezug:** Umsetzung von `docs/superpowers/specs/2026-05-21-airbi-slice1-marvila-design.md` §7 (Scraper Stufe A) und §11 (Topologie). Baut auf Plan 1 auf (`airbi/db/`, `airbi/geo/`, `airbi/classification/` sind vorhanden und gemerged in `main`).

---

## Voraussetzungen

- Plan 1 ist in `main` gemerged. `airbi/db/models.py` (`SearchConfig`, `CrawlRun`, `Listing`, `Snapshot`), `airbi/db/session.py`, `airbi/geo/districts.py` (`load_districts`, `assign_district`), `airbi/classification/size.py` (`size_class`) sind vorhanden.
- Lokales PostgreSQL läuft; DBs `airbi` + `airbi_test`, Rolle `airbi`/`airbi`. Migration ist auf `head`.
- `uv` auf dem PATH.
- Vor Beginn: Feature-Branch / Worktree über `superpowers:using-git-worktrees` anlegen — nicht direkt auf `main`.

## Wichtige Hinweise für die Umsetzung

- **Slice 1 = lokale Entwicklung.** Der Crawl schreibt in die **lokale** `airbi`-DB. Die in Spec §11 beschriebene VPS-Topologie (SSH-Tunnel) ist eine Deployment-Frage und gehört NICHT in diesen Plan.
- **Kein Proxy.** Slice 1 läuft ohne Residential-Proxy (Spec-Entscheidung). `browser.py` bekommt aber einen optionalen `proxy`-Parameter, damit die Vertiefungsrunde ihn ohne Umbau nachrüsten kann.
- **Geringes Volumen.** Slice 1 crawlt zwei kleine Bezirke, ein Lauf. Menschliches Pacing, defensiv. Ein geblockter Scraper ist schlimmer als ein langsamer.
- **Die `StaysSearch`-API ist undokumentiert.** Task 4 zeichnet eine echte Antwort als Fixture auf; Task 5 (Parser) wird gegen diese Fixture geschrieben. Die exakten JSON-Feldpfade stehen NICHT in diesem Plan, weil sie sich ändern — der Aufnahme-Schritt liefert sie.

## Dateistruktur (in diesem Plan erstellt/geändert)

| Datei | Verantwortung |
|---|---|
| `pyproject.toml` | Modify: `playwright`-Dependency + `[project.scripts]`-Eintrag ergänzen |
| `airbi/scraper/__init__.py` | Paket-Marker |
| `airbi/scraper/models.py` | `ParsedListing` — Datenkontrakt der Parser-Ausgabe |
| `airbi/scraper/pacing.py` | Randomisiertes menschliches Timing |
| `airbi/scraper/browser.py` | Playwright-Setup (Stealth, persistenter Context, Proxy-fähige Transport-Schicht) |
| `airbi/scraper/parser.py` | `StaysSearch`-JSON → `list[ParsedListing]` (browser-unabhängig) |
| `airbi/scraper/search_crawl.py` | Stufe-A-Orchestrator: Bounding-Box, Interception, Pagination, CrawlRun-Lebenszyklus, DB-Upsert |
| `airbi/cli.py` | CLI-Befehl `airbi crawl` |
| `tests/fixtures/scraper/stays_search_page1.json` | aufgezeichnete echte `StaysSearch`-Antwort |
| `tests/test_scraper_pacing.py` | Tests für Pacing |
| `tests/test_scraper_parser.py` | Tests für den Parser (gegen Fixture) |
| `tests/test_search_crawl.py` | Tests für Bounding-Box-Logik und DB-Persistenz |

---

## Task 1: Scraper-Paket, Dependencies & Datenkontrakt

**Files:**
- Modify: `pyproject.toml`
- Create: `airbi/scraper/__init__.py`
- Create: `airbi/scraper/models.py`
- Test: `tests/test_scraper_parser.py` (nur ein Smoke-Test in diesem Task; Task 5 erweitert ihn)

- [ ] **Step 1: `playwright` und den CLI-Script-Eintrag in `pyproject.toml` ergänzen**

In `pyproject.toml` im `dependencies`-Array `"playwright>=1.40"` ergänzen (die bestehende Kommentarzeile `# Plan 2 ergänzt hier playwright; ...` darf entfallen oder bleiben). Außerdem nach dem `[project]`-Block diesen Abschnitt einfügen:

```toml
[project.scripts]
airbi = "airbi.cli:main"
```

- [ ] **Step 2: Dependencies installieren und Playwright-Chromium beziehen**

Run: `uv sync && uv run playwright install chromium`
Expected: `uv sync` installiert `playwright`; `playwright install chromium` lädt den Chromium-Browser herunter (kein Fehler).

- [ ] **Step 3: `airbi/scraper/__init__.py` anlegen**

Leere Datei.

- [ ] **Step 4: Failing Test in `tests/test_scraper_parser.py` schreiben**

```python
from decimal import Decimal

from airbi.scraper.models import ParsedListing


def test_parsed_listing_holds_listing_and_snapshot_fields():
    pl = ParsedListing(
        airbnb_id="12345",
        title="Loft in Marvila",
        url="https://www.airbnb.com/rooms/12345",
        lat=38.739,
        lng=-9.104,
        property_type="Entire loft",
        bedrooms=1,
        beds=2,
        bathrooms=1.0,
        max_guests=3,
        host_name="Ana",
        is_superhost=True,
        price=Decimal("120.00"),
        fees=None,
        review_count=42,
        rating=4.9,
        search_position=1,
    )
    assert pl.airbnb_id == "12345"
    assert pl.review_count == 42
    assert pl.price == Decimal("120.00")
```

- [ ] **Step 5: Test laufen lassen, Fehlschlag verifizieren**

Run: `uv run pytest tests/test_scraper_parser.py -v`
Expected: FAIL — `ModuleNotFoundError` für `airbi.scraper.models`.

- [ ] **Step 6: `airbi/scraper/models.py` schreiben**

```python
from dataclasses import dataclass
from decimal import Decimal


@dataclass
class ParsedListing:
    """Ergebnis des StaysSearch-Parsers für ein einzelnes Listing.

    Enthält sowohl relativ statische Stammdaten (werden zu Listing-Feldern)
    als auch Momentaufnahme-Werte (werden zu Snapshot-Feldern). Der
    Crawl-Orchestrator teilt das beim Schreiben auf die beiden Tabellen auf."""

    airbnb_id: str
    title: str | None
    url: str | None
    lat: float | None
    lng: float | None
    property_type: str | None
    bedrooms: int | None
    beds: int | None
    bathrooms: float | None
    max_guests: int | None
    host_name: str | None
    is_superhost: bool
    price: Decimal | None
    fees: Decimal | None
    review_count: int
    rating: float | None
    search_position: int | None
```

- [ ] **Step 7: Test laufen lassen, Erfolg verifizieren**

Run: `uv run pytest tests/test_scraper_parser.py -v`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add pyproject.toml uv.lock airbi/scraper/__init__.py airbi/scraper/models.py tests/test_scraper_parser.py
git commit -m "feat: Scraper-Paket, playwright-Dependency und ParsedListing-Datenkontrakt"
```

---

## Task 2: Pacing — randomisiertes menschliches Timing

**Files:**
- Create: `airbi/scraper/pacing.py`
- Test: `tests/test_scraper_pacing.py`

- [ ] **Step 1: Failing Test in `tests/test_scraper_pacing.py` schreiben**

```python
import random

from airbi.scraper.pacing import human_delay, pick_delay


def test_pick_delay_stays_within_bounds():
    rng = random.Random(42)
    for _ in range(200):
        d = pick_delay(0.5, 2.0, rng=rng)
        assert 0.5 <= d <= 2.0


def test_pick_delay_is_deterministic_with_seeded_rng():
    assert pick_delay(0.5, 2.0, rng=random.Random(1)) == pick_delay(
        0.5, 2.0, rng=random.Random(1)
    )


def test_human_delay_sleeps_for_the_picked_duration():
    slept = []
    duration = human_delay(0.1, 0.2, rng=random.Random(7), sleeper=slept.append)
    assert 0.1 <= duration <= 0.2
    assert slept == [duration]
```

- [ ] **Step 2: Test laufen lassen, Fehlschlag verifizieren**

Run: `uv run pytest tests/test_scraper_pacing.py -v`
Expected: FAIL — `ModuleNotFoundError` für `airbi.scraper.pacing`.

- [ ] **Step 3: `airbi/scraper/pacing.py` schreiben**

```python
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
```

- [ ] **Step 4: Test laufen lassen, Erfolg verifizieren**

Run: `uv run pytest tests/test_scraper_pacing.py -v`
Expected: PASS — alle 3 Tests grün.

- [ ] **Step 5: Commit**

```bash
git add airbi/scraper/pacing.py tests/test_scraper_pacing.py
git commit -m "feat: Pacing-Modul (randomisiertes menschliches Timing)"
```

---

## Task 3: Browser-Infrastruktur (Playwright + Stealth)

**Files:**
- Create: `airbi/scraper/browser.py`

Dieser Task lässt sich nicht deterministisch unit-testen (er startet einen echten Browser). Verifikation = ein Smoke-Lauf (Step 3).

- [ ] **Step 1: `airbi/scraper/browser.py` schreiben**

```python
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
```

- [ ] **Step 2: Smoke-Test-Skript anlegen — `scripts/browser_smoke.py`** (temporär, wird nicht committet)

```python
from airbi.scraper.browser import browser_context

with browser_context(headless=True) as ctx:
    page = ctx.new_page()
    page.goto("https://example.com", timeout=30000)
    print("TITLE:", page.title())
```

- [ ] **Step 3: Smoke-Lauf ausführen**

Run: `uv run python scripts/browser_smoke.py`
Expected: gibt `TITLE: Example Domain` aus, kein Fehler. Danach `scripts/browser_smoke.py` wieder löschen (`rm scripts/browser_smoke.py`; falls `scripts/` leer ist, mitlöschen) — es wird nicht committet.

- [ ] **Step 4: Commit**

```bash
git add airbi/scraper/browser.py
git commit -m "feat: Playwright-Browser-Infrastruktur (Stealth, persistenter Context)"
```

---

## Task 4: Echte `StaysSearch`-Antwort als Fixture aufzeichnen (Discovery)

**Files:**
- Create: `tests/fixtures/scraper/stays_search_page1.json`
- Create: `scripts/record_stays_search.py` (Hilfsskript — WIRD committet, dient auch zur späteren Neu-Aufnahme)

Dieser Task ist ein **Entdeckungs-Schritt**: er beschafft die echte API-Antwort, gegen die Task 5 den Parser schreibt. Es gibt hier keine vorab fixierbaren Feldwerte.

- [ ] **Step 1: Aufnahme-Skript `scripts/record_stays_search.py` schreiben**

```python
"""Öffnet die Airbnb-Suche für die Marvila+Beato-Bounding-Box, fängt die
StaysSearch-API-Antworten ab und speichert die erste als Fixture.

Aufruf: uv run python scripts/record_stays_search.py
"""
import json
from pathlib import Path

from airbi.scraper.browser import browser_context

# Bounding-Box über Marvila + Beato (aus den GeoJSON-Bounds, mit Rand).
SW_LAT, SW_LNG = 38.721, -9.133
NE_LAT, NE_LNG = 38.766, -9.090

SEARCH_URL = (
    "https://www.airbnb.com/s/Lisboa--Portugal/homes"
    f"?ne_lat={NE_LAT}&ne_lng={NE_LNG}&sw_lat={SW_LAT}&sw_lng={SW_LNG}"
    "&search_by_map=true&zoom=14"
)

OUT = Path("tests/fixtures/scraper/stays_search_page1.json")


def main() -> None:
    captured: list[dict] = []

    with browser_context(headless=True) as ctx:
        page = ctx.new_page()

        def on_response(response):
            if "StaysSearch" in response.url and response.request.method == "POST":
                try:
                    captured.append(response.json())
                except Exception:
                    pass

        page.on("response", on_response)
        page.goto(SEARCH_URL, timeout=60000, wait_until="networkidle")
        page.wait_for_timeout(5000)

    if not captured:
        raise SystemExit("Keine StaysSearch-Antwort abgefangen — siehe Task-4-Hinweise.")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(captured[0], indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Fixture gespeichert: {OUT} ({OUT.stat().st_size} Bytes)")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Aufnahme ausführen**

Run: `uv run python scripts/record_stays_search.py`
Expected: `tests/fixtures/scraper/stays_search_page1.json` wird angelegt und ist > 10 KB groß.

**Wenn keine Antwort abgefangen wird:** Airbnb hat evtl. ein anderes URL-Muster oder eine Block-/CAPTCHA-Seite ausgeliefert. Diagnose: `browser_context(headless=False)` im Skript setzen und zusehen; prüfen, welche XHR-URLs mit `api/v3` auftauchen und den Filter `"StaysSearch" in response.url` ggf. anpassen. Wenn eine CAPTCHA-Seite erscheint, ist das ein echter Blocker → als BLOCKED eskalieren (das ist genau das Scraper-Risiko aus dem Briefing).

- [ ] **Step 3: Struktur der Fixture inspizieren und dokumentieren**

Die Fixture in Python laden und die Struktur erkunden — finde heraus:
- Wo liegt das Array der Suchergebnisse? (typisch: ein verschachtelter Pfad unter `data` → `presentation` → `staysSearch` → `results` → ein Ergebnis-Array; die genauen Schlüssel können abweichen)
- Welche Felder hat ein einzelnes Ergebnis? Wo stehen: Listing-ID, Titel, Koordinaten (lat/lng), Property-Type/Room-Type, Schlafzimmer/Betten/Bäder, max. Gäste, Host/Superhost, Preis, Bewertungsanzahl, Rating?

Schreibe die Erkenntnisse als Kommentarblock an den Anfang von `scripts/record_stays_search.py` (Pfad zum Ergebnis-Array + Feld-Mapping). Dieser Kommentar ist die Spezifikation für Task 5.

- [ ] **Step 4: Commit**

```bash
git add scripts/record_stays_search.py tests/fixtures/scraper/stays_search_page1.json
git commit -m "chore: echte StaysSearch-Antwort als Fixture aufgezeichnet"
```

---

## Task 5: Parser — `StaysSearch`-JSON → `ParsedListing`

**Files:**
- Create: `airbi/scraper/parser.py`
- Modify: `tests/test_scraper_parser.py`

TDD gegen die in Task 4 aufgezeichnete Fixture und das dort dokumentierte Feld-Mapping.

- [ ] **Step 1: Fixture inspizieren und konkrete Testwerte ablesen**

Lade `tests/fixtures/scraper/stays_search_page1.json` und lies für **das erste Ergebnis-Listing** die echten Werte ab: `airbnb_id`, `title`, `lat`, `lng`, `review_count`, `rating`. Notiere außerdem die Gesamtzahl der Ergebnis-Listings in der Fixture. Diese echten Werte werden zu den Assertions in Step 2.

- [ ] **Step 2: Failing Tests in `tests/test_scraper_parser.py` ergänzen**

Importzeile oben ergänzen:

```python
import json
from pathlib import Path

from airbi.scraper.parser import parse_stays_search
```

Am Dateiende anhängen (die mit `# <aus Fixture>` markierten Werte durch die in Step 1 abgelesenen ECHTEN Werte ersetzen):

```python
FIXTURE = Path(__file__).parent / "fixtures" / "scraper" / "stays_search_page1.json"


def _payload():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_parser_returns_all_listings_from_fixture():
    listings = parse_stays_search(_payload())
    assert len(listings) == 0  # <aus Fixture: tatsächliche Anzahl einsetzen>


def test_parser_extracts_core_fields_of_first_listing():
    listings = parse_stays_search(_payload())
    first = listings[0]
    assert first.airbnb_id == ""        # <aus Fixture>
    assert first.lat is not None
    assert first.lng is not None
    assert first.review_count >= 0
    assert first.search_position == 1


def test_parser_assigns_increasing_search_positions():
    listings = parse_stays_search(_payload())
    positions = [pl.search_position for pl in listings]
    assert positions == list(range(1, len(listings) + 1))


def test_parser_tolerates_missing_optional_fields():
    # Ein minimales Ergebnis ohne optionale Felder darf den Parser nicht
    # crashen lassen — fehlende Werte werden zu None bzw. 0 (review_count).
    minimal = {"listing": {"id": "999"}}
    listings = parse_stays_search(_wrap_results([minimal]))
    assert listings[0].airbnb_id == "999"
    assert listings[0].review_count == 0
```

Außerdem eine Hilfsfunktion `_wrap_results(results: list[dict]) -> dict` ergänzen, die eine Liste von Roh-Ergebnis-Objekten in dieselbe verschachtelte Struktur einbettet, die die echte Fixture hat (Pfad aus dem Task-4-Kommentar). So testet `test_parser_tolerates_missing_optional_fields` denselben Code-Pfad wie die echte Antwort.

- [ ] **Step 3: Tests laufen lassen, Fehlschlag verifizieren**

Run: `uv run pytest tests/test_scraper_parser.py -v`
Expected: FAIL — `ModuleNotFoundError` für `airbi.scraper.parser`.

- [ ] **Step 4: `airbi/scraper/parser.py` schreiben**

`parse_stays_search(payload: dict) -> list[ParsedListing]` implementieren. Vorgaben:
- Signatur: `def parse_stays_search(payload: dict) -> list[ParsedListing]:`
- Den Pfad zum Ergebnis-Array aus dem Task-4-Kommentar verwenden. Fehlt der Pfad (leere/unerwartete Antwort), eine leere Liste zurückgeben — nicht crashen.
- Pro Ergebnis ein `ParsedListing` bauen; `search_position` ist der 1-basierte Index in der Ergebnisliste.
- **Defensiv extrahieren:** jedes Feld über `.get(...)` mit Fallback `None`; `review_count` fällt auf `0` zurück, `is_superhost` auf `False`. Der Parser darf an einem unvollständigen Ergebnis nicht abstürzen (siehe `test_parser_tolerates_missing_optional_fields`).
- `airbnb_id` immer als `str`. `price`/`fees` als `Decimal` (aus dem rohen Preis-String die Ziffern/Dezimalstellen extrahieren); wenn nicht ermittelbar → `None`.
- Reine Funktion: kein Netzwerk, keine DB, kein Browser.

Eine kleine Helferfunktion zum sicheren Navigieren verschachtelter dicts (`_dig(obj, *keys)`) ist erlaubt und empfohlen.

- [ ] **Step 5: Tests laufen lassen, Erfolg verifizieren**

Run: `uv run pytest tests/test_scraper_parser.py -v`
Expected: PASS — alle Parser-Tests grün.

- [ ] **Step 6: Commit**

```bash
git add airbi/scraper/parser.py tests/test_scraper_parser.py
git commit -m "feat: StaysSearch-Parser (JSON -> ParsedListing)"
```

---

## Task 6: Crawl-Orchestrator — Bounding-Box & DB-Persistenz

**Files:**
- Create: `airbi/scraper/search_crawl.py`
- Test: `tests/test_search_crawl.py`

Der Orchestrator besteht aus zwei klar getrennten Teilen: (a) **reine/DB-Logik** — Bounding-Box-Berechnung und Persistenz der geparsten Ergebnisse — vollständig testbar; (b) **browser-getriebener Lauf** — nicht deterministisch testbar, in Task 8 real verifiziert.

- [ ] **Step 1: Failing Tests in `tests/test_search_crawl.py` schreiben**

```python
from decimal import Decimal

from airbi.db.models import CrawlRun, Listing, SearchConfig, Snapshot
from airbi.geo.districts import load_districts
from airbi.scraper.models import ParsedListing
from airbi.scraper.search_crawl import bounding_box_for, persist_results


def _parsed(airbnb_id, lat, lng, bedrooms=1, review_count=10):
    return ParsedListing(
        airbnb_id=airbnb_id, title="T", url="u", lat=lat, lng=lng,
        property_type="Entire loft", bedrooms=bedrooms, beds=1, bathrooms=1.0,
        max_guests=2, host_name="H", is_superhost=False,
        price=Decimal("100.00"), fees=None, review_count=review_count,
        rating=4.5, search_position=1,
    )


def test_bounding_box_covers_all_district_polygons():
    districts = load_districts()  # echte Marvila+Beato-Polygone
    sw_lat, sw_lng, ne_lat, ne_lng = bounding_box_for(districts, margin=0.0)
    # Marvila-Zielpunkt muss innerhalb der Box liegen.
    assert sw_lat <= 38.7390 <= ne_lat
    assert sw_lng <= -9.1044 <= ne_lng
    assert ne_lat > sw_lat and ne_lng > sw_lng


def test_persist_results_creates_listing_snapshot_and_assigns_district(db_session):
    cfg = SearchConfig(name="Marvila Crawl", district_slugs=["marvila", "beato"])
    run = CrawlRun(search_config=cfg, status="running")
    db_session.add(run)
    db_session.flush()
    districts = load_districts()

    # Punkt in Marvila.
    persist_results(db_session, run, [_parsed("A1", 38.7390, -9.1044)], districts)

    listing = db_session.query(Listing).filter_by(airbnb_id="A1").one()
    assert listing.district_slug == "marvila"
    assert listing.size_class == "1BR"
    snap = db_session.query(Snapshot).filter_by(listing_id=listing.id).one()
    assert snap.crawl_run_id == run.id
    assert snap.review_count == 10


def test_persist_results_upserts_listing_on_second_crawl(db_session):
    cfg = SearchConfig(name="Marvila Crawl", district_slugs=["marvila"])
    districts = load_districts()
    run1 = CrawlRun(search_config=cfg, status="running")
    db_session.add(run1)
    db_session.flush()
    persist_results(db_session, run1, [_parsed("A1", 38.7390, -9.1044, review_count=10)], districts)

    run2 = CrawlRun(search_config=cfg, status="running")
    db_session.add(run2)
    db_session.flush()
    persist_results(db_session, run2, [_parsed("A1", 38.7390, -9.1044, review_count=25)], districts)

    # Genau EIN Listing (upsert), aber ZWEI Snapshots (Zeitreihe).
    assert db_session.query(Listing).filter_by(airbnb_id="A1").count() == 1
    assert db_session.query(Snapshot).count() == 2
    latest = db_session.query(Snapshot).filter_by(crawl_run_id=run2.id).one()
    assert latest.review_count == 25


def test_persist_results_marks_point_outside_polygons_unassigned(db_session):
    cfg = SearchConfig(name="X", district_slugs=["marvila"])
    run = CrawlRun(search_config=cfg, status="running")
    db_session.add(run)
    db_session.flush()
    districts = load_districts()
    # Punkt weit außerhalb (Atlantik).
    persist_results(db_session, run, [_parsed("OUT", 38.5, -9.5)], districts)
    listing = db_session.query(Listing).filter_by(airbnb_id="OUT").one()
    assert listing.district_slug == "unassigned"
```

- [ ] **Step 2: Tests laufen lassen, Fehlschlag verifizieren**

Run: `uv run pytest tests/test_search_crawl.py -v`
Expected: FAIL — `ModuleNotFoundError` für `airbi.scraper.search_crawl`.

- [ ] **Step 3: `airbi/scraper/search_crawl.py` schreiben**

Das Modul enthält:

**(a) `bounding_box_for(districts, margin=0.003)`** — reine Funktion. Nimmt das `dict[str, BaseGeometry]` von `load_districts()`, vereinigt die `.bounds` aller Geometrien (`shapely`-Geometrien haben `.bounds` = `(minx, miny, maxx, maxy)` = `(min_lng, min_lat, max_lng, max_lat)`), addiert `margin` (Grad) als Rand und gibt `(sw_lat, sw_lng, ne_lat, ne_lng)` zurück.

**(b) `persist_results(session, crawl_run, parsed_listings, districts)`** — schreibt geparste Ergebnisse in die DB:
- Für jedes `ParsedListing`: Listing per `(city_slug, airbnb_id)` suchen (`city_slug` = `crawl_run.search_config.city_slug`). Existiert es → Stammdaten aktualisieren; sonst neu anlegen.
- `district_slug` über `assign_district(lat, lng, districts)` setzen (gibt `"unassigned"` bei keinem Treffer; bei fehlenden Koordinaten ebenfalls `"unassigned"`).
- `size_class` über `size_class(bedrooms)` aus `airbi.classification.size` setzen.
- Für jedes Listing einen neuen `Snapshot` mit `crawl_run_id`, Preis, Gebühren, `review_count`, `rating`, `search_position` anlegen.
- `session.flush()` am Ende; nicht committen (der Aufrufer bzw. die Test-Fixture steuert die Transaktion).
- Gibt die Anzahl verarbeiteter Listings zurück.

**(c) `run_search_crawl(session, search_config, *, headless=True)`** — der browser-getriebene Lauf:
- Legt einen `CrawlRun` (`status="running"`) für die `search_config` an, `flush`.
- Lädt `load_districts()`, filtert auf `search_config.district_slugs`, berechnet die Bounding-Box.
- Öffnet `browser_context()`, registriert einen `response`-Handler, der `StaysSearch`-POST-Antworten sammelt (wie in `scripts/record_stays_search.py`).
- Navigiert zur Map-Bounds-Such-URL; blättert/scrollt menschlich (`pacing.human_delay`) durch die Ergebnisseiten, bis keine neuen Ergebnisse mehr kommen oder ein Sicherheits-Limit erreicht ist.
- Parst alle gesammelten Antworten mit `parse_stays_search`, dedupliziert über `airbnb_id` (erste Sichtung gewinnt, behält deren `search_position`).
- Ruft `persist_results` auf.
- **Block-Erkennung:** Wird eine CAPTCHA-/Block-Seite erkannt oder kommen 0 Ergebnisse → `CrawlRun.status="failed"` mit klarer `message`, sonst `status="completed"`, `listings_seen` setzen, `finished_at` setzen.
- Bei einer Exception: `CrawlRun.status="failed"`, `message` mit dem Fehler; Exception nicht verschlucken (loggen/erneut werfen nach dem Statussetzen ist ok).
- `session.commit()` am Ende dieses Laufs (anders als `persist_results` verwaltet `run_search_crawl` seine Transaktion selbst).

Hinweis: `run_search_crawl` wird in den Unit-Tests NICHT aufgerufen (Browser). Teil (a) und (b) sind durch Task-6-Tests abgedeckt; Teil (c) wird in Task 8 real verifiziert. Halte (c) dünn — die testbare Logik liegt in (a) und (b).

- [ ] **Step 4: Tests laufen lassen, Erfolg verifizieren**

Run: `uv run pytest tests/test_search_crawl.py -v`
Expected: PASS — alle 4 Tests grün.

- [ ] **Step 5: Commit**

```bash
git add airbi/scraper/search_crawl.py tests/test_search_crawl.py
git commit -m "feat: Crawl-Orchestrator (Bounding-Box, DB-Upsert, Lauf)"
```

---

## Task 7: CLI — `airbi crawl`

**Files:**
- Create: `airbi/cli.py`

- [ ] **Step 1: `airbi/cli.py` schreiben**

Ein `argparse`-basiertes CLI mit einem `crawl`-Unterbefehl und einer `main()`-Funktion (Einstiegspunkt aus `[project.scripts]`).

- `main(argv=None)` — parst Argumente; Unterbefehl `crawl` mit Option `--config NAME` (Name der zu verwendenden `SearchConfig`) und Flag `--headful` (Browser sichtbar, default headless).
- `crawl`-Logik: eine DB-Session über `SessionLocal` aus `airbi.db.session` öffnen; die `SearchConfig` per `name` laden. Existiert sie nicht → Fehlermeldung auf stderr, Exit-Code 1. Sonst `run_search_crawl(session, config, headless=not args.headful)` aufrufen. Danach den resultierenden `CrawlRun`-Status + `listings_seen` auf stdout ausgeben.
- Wenn keine `SearchConfig` mit dem Namen existiert, dem Nutzer den Hinweis geben, dass sie zuerst angelegt werden muss (in Slice 1 kann das ein kurzer Hinweistext sein — eine UI zum Anlegen kommt in Plan 3).
- `main` gibt einen Exit-Code zurück bzw. ruft `sys.exit` mit ihm auf.

- [ ] **Step 2: CLI-Hilfe verifizieren**

Run: `uv run airbi crawl --help`
Expected: zeigt die Hilfe für den `crawl`-Befehl mit `--config` und `--headful`, kein Fehler. (Dies bestätigt zugleich, dass der `[project.scripts]`-Eintrag aus Task 1 funktioniert.)

- [ ] **Step 3: Verhalten bei fehlender SearchConfig verifizieren**

Run: `uv run airbi crawl --config "Gibt-es-nicht"`
Expected: klare Fehlermeldung auf stderr, Exit-Code 1 (kein Stacktrace).

- [ ] **Step 4: Commit**

```bash
git add airbi/cli.py
git commit -m "feat: CLI-Befehl 'airbi crawl'"
```

---

## Task 8: End-to-End-Crawl gegen die echte Suche

**Files:** keine neuen — dieser Task ist die reale Verifikation des Gesamt-Crawls.

- [ ] **Step 1: Eine Marvila-`SearchConfig` in der lokalen DB anlegen**

Einen kleinen Einmal-Befehl ausführen, der über `SessionLocal` eine `SearchConfig` anlegt und committet:

```bash
uv run python -c "
from airbi.db.session import SessionLocal
from airbi.db.models import SearchConfig
s = SessionLocal()
if not s.query(SearchConfig).filter_by(name='Marvila Slice 1').first():
    s.add(SearchConfig(name='Marvila Slice 1', district_slugs=['marvila','beato']))
    s.commit()
    print('SearchConfig angelegt')
else:
    print('SearchConfig existiert bereits')
s.close()
"
```

- [ ] **Step 2: Den echten Crawl ausführen**

Run: `uv run airbi crawl --config "Marvila Slice 1"`
Expected: Der Lauf öffnet einen Browser (headless), crawlt die Bounding-Box und gibt am Ende `CrawlRun`-Status `completed` mit `listings_seen > 0` aus.

**Wenn der Lauf `failed` meldet** (Block/CAPTCHA/0 Ergebnisse): das ist das im Briefing benannte Scraper-Risiko. Diagnose mit `--headful` und zusehen. Lässt es sich nicht ohne Proxy lösen, ist das ein Befund, der eskaliert werden muss (NICHT durch Daten-Fälschung „grün machen"). Dokumentiere, was passiert ist.

- [ ] **Step 3: Die geschriebenen Daten verifizieren**

Run:
```bash
uv run python -c "
from airbi.db.session import SessionLocal
from airbi.db.models import Listing, Snapshot, CrawlRun
s = SessionLocal()
print('CrawlRuns:', s.query(CrawlRun).count())
print('Listings :', s.query(Listing).count())
print('Snapshots:', s.query(Snapshot).count())
for slug in ('marvila','beato','unassigned'):
    print(f'  {slug}:', s.query(Listing).filter_by(district_slug=slug).count())
s.close()
"
```
Expected: `CrawlRuns` ≥ 1, `Listings` > 0, `Snapshots` == Anzahl im letzten Lauf gesehener Listings, und ein plausibler Teil der Listings ist `marvila` bzw. `beato` zugeordnet.

- [ ] **Step 4: Volle Test-Suite + Commit (falls in diesem Task etwas geändert wurde)**

Run: `uv run pytest -q`
Expected: alle Tests grün (Plan-1-Tests + die neuen Scraper-Tests aus Plan 2; die Browser-/Crawl-getriebenen Teile sind nicht in der Suite).

Falls in Task 8 Korrekturen am Code nötig waren, committen. Sonst ist Task 8 reine Verifikation ohne Commit.

---

## Definition of Done (Plan 2)

- [ ] `uv run pytest -q` — alle Tests grün (Plan-1- + Plan-2-Unit-Tests: `ParsedListing`, Pacing, Parser gegen Fixture, Bounding-Box, `persist_results`-DB-Logik).
- [ ] `uv run airbi crawl --help` funktioniert; der `[project.scripts]`-Eintrag ist aktiv.
- [ ] Ein echter Crawl (`airbi crawl --config "Marvila Slice 1"`) erzeugt einen `CrawlRun` mit Status `completed` und schreibt `Listing`- + `Snapshot`-Zeilen in die lokale `airbi`-DB; Bezirke sind zugeordnet.
- [ ] Die aufgezeichnete `StaysSearch`-Fixture liegt im Repo; der Parser ist dagegen getestet.
- [ ] Alle Tasks committet; `scripts/browser_smoke.py` ist NICHT im Repo (Task 3 löscht es wieder), `scripts/record_stays_search.py` IST im Repo.

Damit füllt der Scraper die DB mit echten Daten. **Plan 3 (Insight & Dashboard)** wird danach geschrieben — Segment-Matrix, Empfehlungstext und das minimale FastAPI/HTMX-Dashboard, die den §12-Acceptance-Test erfüllen.

## Bekannte, bewusst aufgeschobene Punkte (aus Plan 1 übernommen)

Beim Schreiben von Plan-2-Tests, die `db_session` nutzen, gilt weiterhin: die Test-Fixture nutzt das einfache Transaktions-Rollback-Muster (eine benigne `SAWarning` ist möglich, kein Daten-Leak). Eine savepoint-basierte Fixture bleibt ein optionaler Härtungs-Punkt für später — in Plan 2 nicht angehen.
