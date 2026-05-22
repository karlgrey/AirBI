# AirBI Slice 1 — Plan 2: Scraper Stufe A + minimaler Detail-Crawl — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> **Revision v1.1 (2026-05-22):** Task 4 (Aufnahme einer echten Airbnb-Antwort) hat ergeben, dass die Stufe-A-Suchdaten **keine Zimmerzahl** enthalten und Airbnb die Ergebnisse serverseitig ins Seiten-HTML einbettet (kein `StaysSearch`-XHR). Konsequenz (vom Auftraggeber so entschieden): Slice 1 bekommt einen **minimalen Detail-Crawl** für die Raumzahlen. Tasks 1–4 sind bereits abgeschlossen; Tasks 5–10 sind gegenüber der ersten Planfassung überarbeitet und um den Detail-Crawl erweitert. Siehe Spec v1.1 §7.

**Goal:** Ein Playwright-gesteuerter Browser liest die in die Airbnb-Suchseite eingebetteten Ergebnisse für die Marvila+Beato-Bounding-Box, holt für jedes Ganz-Apartment-Listing zusätzlich die Detailseite (nur Raumzahlen), und ein CLI-Befehl füllt die lokale Postgres-DB mit `Listing`- + `Snapshot`-Daten inkl. `size_class`.

**Architecture:** Browser-Automation mit Playwright (echter Chromium, Stealth-gehärtet, persistenter Context). Airbnb rendert Suchergebnisse serverseitig ins HTML (`data-deferred-state`); wir lesen das eingebettete JSON. Reine Parser übersetzen Such-JSON → `ParsedListing` und Detail-JSON → `ListingDetail` — beide gegen aufgezeichnete Fixtures testbar. Der Crawl-Orchestrator: Such-Crawl → Filter auf Ganz-Apartments → Detail-Crawl je Listing → Raumzahlen mergen → `CrawlRun`-Lebenszyklus, Bezirkszuordnung, `size_class`, DB-Upsert.

**Tech Stack:** Python ≥3.11, `uv`, Playwright (Chromium), SQLAlchemy 2.0, pytest.

**Bezug:** Umsetzung von `docs/superpowers/specs/2026-05-21-airbi-slice1-marvila-design.md` §7 (v1.1). Baut auf Plan 1 auf (`airbi/db/`, `airbi/geo/`, `airbi/classification/`).

---

## Voraussetzungen

- Plan 1 in `main` gemerged. `airbi/db/models.py`, `airbi/db/session.py`, `airbi/geo/districts.py` (`load_districts`, `assign_district` → liefert Slug oder `"unassigned"`), `airbi/classification/size.py` (`size_class`) vorhanden.
- Lokales PostgreSQL läuft; DBs `airbi` + `airbi_test`, Rolle `airbi`/`airbi`, Migration auf `head`.
- `uv` auf dem PATH; Worktree/Feature-Branch über `superpowers:using-git-worktrees`.

## Wichtige Hinweise

- **Slice 1 = lokale Entwicklung.** Der Crawl schreibt in die **lokale** `airbi`-DB. Die VPS-/SSH-Tunnel-Topologie ist Deployment-Sache, nicht Teil dieses Plans.
- **Kein Proxy** in Slice 1; `browser.py` hat aber den `proxy`-Parameter.
- **Geringes Volumen.** Marvila/Beato sind Emerging-Bezirke mit geringer Listing-Dichte. Menschliches Pacing, defensiv. Ein geblockter Scraper ist schlimmer als ein langsamer.
- **Undokumentierte JSON-Struktur.** Tasks 4 + 6 zeichnen echte Antworten als Fixtures auf; die Parser (Tasks 5 + 7) werden gegen diese Fixtures geschrieben. Exakte Feldpfade liefern die Aufnahme-Schritte, nicht dieser Plan.

## Dateistruktur

| Datei | Status | Verantwortung |
|---|---|---|
| `pyproject.toml` | ✅ Task 1 | `playwright`-Dependency + `[project.scripts]` |
| `airbi/scraper/__init__.py` | ✅ Task 1 | Paket-Marker |
| `airbi/scraper/models.py` | ✅ T1 / ✏️ T7 | `ParsedListing` (T1) + `ListingDetail` (T7) |
| `airbi/scraper/pacing.py` | ✅ Task 2 | Randomisiertes menschliches Timing |
| `airbi/scraper/browser.py` | ✅ Task 3 | Playwright-Setup (Stealth, persistent, proxy-fähig) |
| `scripts/record_stays_search.py` | ✅ Task 4 | Such-Antwort aufzeichnen |
| `tests/fixtures/scraper/stays_search_page1.json` | ✅ Task 4 | aufgezeichnete Such-Antwort |
| `airbi/scraper/parser.py` | ✏️ T5 / ✏️ T7 | `parse_search_results` (T5) + `parse_listing_detail` (T7) |
| `scripts/record_listing_detail.py` | T6 | Detailseite aufzeichnen |
| `tests/fixtures/scraper/listing_detail.json` | T6 | aufgezeichnete Detailseite |
| `airbi/scraper/search_crawl.py` | T8 | Orchestrator: Bounding-Box, Filter, Detail-Crawl, Merge, Upsert |
| `airbi/cli.py` | T9 | CLI `airbi crawl` |
| `tests/test_scraper_parser.py` | ✅ T1 / ✏️ T5 / ✏️ T7 | Parser-Tests |
| `tests/test_search_crawl.py` | T8 | Tests für Bounding-Box, Filter, Merge, Persistenz |

---

## Tasks 1–4 — ✅ ABGESCHLOSSEN

Diese Tasks sind umgesetzt, reviewt und committet. Nicht erneut bearbeiten.

- **Task 1 — Scraper-Paket, Dependencies & Datenkontrakt** (Commit `5c275c3`): `playwright`-Dependency, `[project.scripts] airbi = "airbi.cli:main"`, `airbi/scraper/` Paket, `ParsedListing`-Dataclass (17 Felder), Smoke-Test.
- **Task 2 — Pacing** (Commit `599b595`): `airbi/scraper/pacing.py` mit `pick_delay`, `human_delay` (injizierbare `rng`/`sleeper`), Default-Spannen-Konstanten.
- **Task 3 — Browser-Infrastruktur** (Commit `4753c99`): `airbi/scraper/browser.py` mit `browser_context()` — Stealth-gehärteter, persistenter Chromium-Context, Proxy-Parameter.
- **Task 4 — Such-Antwort als Fixture** (Commit `5326b37`): `scripts/record_stays_search.py` + `tests/fixtures/scraper/stays_search_page1.json` (18 `searchResults`). Befund dokumentiert: Ergebnisse liegen unter `data.presentation.staysSearch.results.searchResults`; ein Ergebnis `r` hat `r["title"]` (Property-Typ + Stadtteil), `r["demandStayListing"]` (id base64-kodiert, `description.name`, `location.coordinate`), `r["structuredDisplayPrice"]`, `r["avgRatingLocalized"]` ("4.86 (245)"), `r["badges"]`. **Zimmer/Betten/Bäder/Gäste sind NICHT enthalten** → Detail-Crawl nötig (Tasks 6–8).

---

## Task 5: Such-Parser — `parse_search_results`

**Files:**
- Modify: `airbi/scraper/parser.py` (neu anlegen, falls noch nicht vorhanden)
- Modify: `tests/test_scraper_parser.py`

TDD gegen die in Task 4 aufgezeichnete Fixture `tests/fixtures/scraper/stays_search_page1.json` und den dort im `record_stays_search.py`-Kopfkommentar dokumentierten Feld-Pfad.

- [ ] **Step 1: Failing Tests in `tests/test_scraper_parser.py` ergänzen**

Importzeile oben ergänzen:

```python
import json
from pathlib import Path

from airbi.scraper.parser import parse_search_results
```

Am Dateiende anhängen:

```python
SEARCH_FIXTURE = Path(__file__).parent / "fixtures" / "scraper" / "stays_search_page1.json"


def _search_payload():
    return json.loads(SEARCH_FIXTURE.read_text(encoding="utf-8"))


def test_search_parser_returns_all_18_results():
    assert len(parse_search_results(_search_payload())) == 18


def test_search_parser_core_fields_present_and_typed():
    for pl in parse_search_results(_search_payload()):
        assert pl.airbnb_id and pl.airbnb_id.isdigit()
        assert pl.lat is not None and pl.lng is not None
        assert pl.review_count >= 0
        assert isinstance(pl.is_superhost, bool)
        # Zimmerzahl kommt NICHT aus den Suchdaten — bleibt None bis Detail-Crawl:
        assert pl.bedrooms is None
        assert pl.max_guests is None


def test_search_parser_assigns_1_based_positions():
    listings = parse_search_results(_search_payload())
    assert [pl.search_position for pl in listings] == list(range(1, 19))


def test_search_parser_first_result_within_lisbon_bbox():
    first = parse_search_results(_search_payload())[0]
    assert 38.70 < first.lat < 38.78
    assert -9.17 < first.lng < -9.05


def test_search_parser_extracts_property_type_and_url():
    listings = parse_search_results(_search_payload())
    assert any(pl.property_type and "partment" in pl.property_type.lower()
               for pl in listings)
    for pl in listings:
        assert pl.url and pl.airbnb_id in pl.url


def test_search_parser_returns_empty_list_on_unexpected_shape():
    assert parse_search_results({}) == []
```

- [ ] **Step 2: Test laufen lassen, Fehlschlag verifizieren**

Run: `uv run pytest tests/test_scraper_parser.py -v`
Expected: FAIL — `ImportError` für `parse_search_results` aus `airbi.scraper.parser`.

- [ ] **Step 3: `parse_search_results` in `airbi/scraper/parser.py` schreiben**

`def parse_search_results(payload: dict) -> list[ParsedListing]:` implementieren. Vorgaben:
- Den Ergebnis-Array-Pfad aus dem Task-4-Kommentar verwenden (`data` → `presentation` → `staysSearch` → `results` → `searchResults`). Fehlt der Pfad → leere Liste zurückgeben (nicht crashen). Eine Helferfunktion `_dig(obj, *keys)` zum sicheren Navigieren ist empfohlen.
- Pro Ergebnis ein `ParsedListing` (aus `airbi.scraper.models`):
  - `airbnb_id`: aus `demandStayListing["id"]` (base64-kodiert „DemandStayListing:NNN") — dekodieren, numerischen Teil nehmen, als `str`.
  - `url`: `f"https://www.airbnb.com/rooms/{airbnb_id}"`.
  - `title`: der Listing-Name (`demandStayListing.description.name.localizedStringWithTranslationPreference`).
  - `property_type`: der Teil **vor** „ in " aus `r["title"]` (z. B. „Apartment", „Room", „Boat", „Guesthouse"). Falsch geformt → `r["title"]` ganz bzw. `None`.
  - `lat`/`lng`: aus `demandStayListing.location.coordinate`.
  - `price`: aus dem formatierten Preis-String in `structuredDisplayPrice` die Zahl extrahieren → `Decimal`; nicht ermittelbar → `None`.
  - `rating` + `review_count`: aus `avgRatingLocalized` (z. B. „4.86 (245)"): Rating = Zahl vorn, `review_count` = Zahl in Klammern. Ohne Klammer-Angabe → `review_count = 0`, `rating = None` wenn nichts da.
  - `is_superhost`: `True`, wenn ein `badge` den `SUPERHOST`-Typ trägt, sonst `False`.
  - `bedrooms`, `beds`, `bathrooms`, `max_guests`, `fees`: `None` (nicht in Suchdaten).
  - `search_position`: 1-basierter Index in der Ergebnisliste.
- **Defensiv:** jedes Feld über sicheres Navigieren mit Fallback; ein unvollständiges Ergebnis darf den Parser nicht abstürzen lassen. Reine Funktion — kein Netzwerk, keine DB, kein Browser.

- [ ] **Step 4: Tests laufen lassen, Erfolg verifizieren**

Run: `uv run pytest tests/test_scraper_parser.py -v`
Expected: PASS — alle Tests grün (Task-1-Smoke-Test + die 6 neuen Such-Parser-Tests).

- [ ] **Step 5: Commit**

```bash
git add airbi/scraper/parser.py tests/test_scraper_parser.py
git commit -m "feat: Such-Parser (eingebettetes Such-JSON -> ParsedListing)"
```

---

## Task 6: Detailseite als Fixture aufzeichnen (Discovery)

**Files:**
- Create: `scripts/record_listing_detail.py`
- Create: `tests/fixtures/scraper/listing_detail.json`

Discovery-Schritt: beschafft eine echte Airbnb-Detailseite, gegen die Task 7 den Detail-Parser schreibt.

- [ ] **Step 1: Eine Ganz-Apartment-Listing-ID aus der Such-Fixture wählen**

`tests/fixtures/scraper/stays_search_page1.json` laden, ein Ergebnis mit `title` der Form „Apartment in …" (ein ganzes Apartment, kein „Room in …") wählen und dessen `airbnb_id` (base64-dekodiert) notieren.

- [ ] **Step 2: Aufnahme-Skript `scripts/record_listing_detail.py` schreiben**

```python
"""Lädt eine Airbnb-Detailseite (/rooms/<id>), extrahiert das eingebettete
JSON aus dem Seiten-HTML und speichert es als Fixture.

Aufruf: uv run python scripts/record_listing_detail.py <listing_id>
"""
import json
import sys
from pathlib import Path

from airbi.scraper.browser import browser_context

OUT = Path("tests/fixtures/scraper/listing_detail.json")


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit("Aufruf: record_listing_detail.py <listing_id>")
    listing_id = sys.argv[1]
    url = f"https://www.airbnb.com/rooms/{listing_id}"

    with browser_context(headless=True) as ctx:
        page = ctx.new_page()
        page.goto(url, timeout=60000, wait_until="networkidle")
        page.wait_for_timeout(4000)
        # Eingebettetes JSON aus den data-deferred-state-Script-Tags lesen.
        blobs = page.eval_on_selector_all(
            "script[id^='data-deferred-state']",
            "els => els.map(e => e.textContent)",
        )

    if not blobs:
        raise SystemExit("Kein eingebettetes JSON gefunden — siehe Task-6-Hinweise.")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(blobs[0], encoding="utf-8")
    print(f"Fixture gespeichert: {OUT} ({OUT.stat().st_size} Bytes)")


if __name__ == "__main__":
    main()
```

Hinweis: Wenn die `data-deferred-state`-Script-ID auf der Detailseite anders heißt, im Browser (`headless=False`) prüfen, welches `<script type="application/json">`-Tag die PDP-Daten trägt, und den Selektor anpassen. Erscheint eine CAPTCHA-/Block-Seite → als BLOCKED eskalieren.

- [ ] **Step 3: Aufnahme ausführen**

Run: `uv run python scripts/record_listing_detail.py <gewählte_listing_id>`
Expected: `tests/fixtures/scraper/listing_detail.json` wird angelegt, > 10 KB.

- [ ] **Step 4: Struktur inspizieren und dokumentieren**

Die Fixture laden und finden, wo **Schlafzimmer-, Betten-, Bäder- und maximale Gästezahl** stehen (typisch in einem PDP-„overview"/„sharingConfig"-Abschnitt, oder als Sätze wie „2 bedrooms" / „Sleeps 4" in einer Sektionsliste). Die Pfade bzw. das Extraktionsverfahren als Kopfkommentar in `scripts/record_listing_detail.py` dokumentieren — das ist die Spezifikation für Task 7.

- [ ] **Step 5: Commit**

```bash
git add scripts/record_listing_detail.py tests/fixtures/scraper/listing_detail.json
git commit -m "chore: echte Airbnb-Detailseite als Fixture aufgezeichnet"
```

---

## Task 7: Detail-Parser — `parse_listing_detail`

**Files:**
- Modify: `airbi/scraper/models.py` (`ListingDetail` ergänzen)
- Modify: `airbi/scraper/parser.py` (`parse_listing_detail` ergänzen)
- Modify: `tests/test_scraper_parser.py`

- [ ] **Step 1: `ListingDetail`-Dataclass in `airbi/scraper/models.py` ergänzen**

Am Dateiende von `models.py` anhängen (der bestehende `ParsedListing` bleibt unverändert):

```python
@dataclass
class ListingDetail:
    """Aus der Airbnb-Detailseite extrahierte Raumzahlen (minimaler
    Detail-Crawl). Wird vom Orchestrator in ein ParsedListing gemergt."""

    bedrooms: int | None
    beds: int | None
    bathrooms: float | None
    max_guests: int | None
```

- [ ] **Step 2: Failing Tests in `tests/test_scraper_parser.py` ergänzen**

Importzeile oben erweitern um `parse_listing_detail`:

```python
from airbi.scraper.parser import parse_listing_detail, parse_search_results
```

Am Dateiende anhängen:

```python
DETAIL_FIXTURE = Path(__file__).parent / "fixtures" / "scraper" / "listing_detail.json"


def _detail_payload():
    return json.loads(DETAIL_FIXTURE.read_text(encoding="utf-8"))


def test_detail_parser_extracts_room_counts():
    detail = parse_listing_detail(_detail_payload())
    # Eine echte Apartment-Detailseite muss eine plausible Zimmerzahl liefern.
    assert detail.bedrooms is not None
    assert detail.bedrooms >= 0
    assert detail.max_guests is not None and detail.max_guests >= 1


def test_detail_parser_tolerates_unexpected_shape():
    detail = parse_listing_detail({})
    assert detail.bedrooms is None
    assert detail.max_guests is None
```

- [ ] **Step 3: Test laufen lassen, Fehlschlag verifizieren**

Run: `uv run pytest tests/test_scraper_parser.py -v`
Expected: FAIL — `ImportError` für `parse_listing_detail`.

- [ ] **Step 4: `parse_listing_detail` in `airbi/scraper/parser.py` schreiben**

`def parse_listing_detail(payload: dict) -> ListingDetail:` implementieren. Vorgaben:
- Die in Task 6 dokumentierten Pfade/Verfahren verwenden, um `bedrooms`, `beds`, `bathrooms`, `max_guests` zu extrahieren.
- Stehen die Werte als Text („2 bedrooms", „Studio", „Sleeps 4"): die Zahl per Regex herauslösen; „Studio" → `bedrooms = 0`.
- Jeder Wert defensiv: nicht ermittelbar → `None`. Bei unerwarteter/leerer Struktur ein `ListingDetail` mit lauter `None` zurückgeben — nicht crashen.
- Reine Funktion — kein Netzwerk, keine DB, kein Browser.

- [ ] **Step 5: Tests laufen lassen, Erfolg verifizieren**

Run: `uv run pytest tests/test_scraper_parser.py -v`
Expected: PASS — alle Parser-Tests grün (Such- + Detail-Parser).

- [ ] **Step 6: Commit**

```bash
git add airbi/scraper/models.py airbi/scraper/parser.py tests/test_scraper_parser.py
git commit -m "feat: Detail-Parser (Detailseiten-JSON -> ListingDetail Raumzahlen)"
```

---

## Task 8: Crawl-Orchestrator — Bounding-Box, Filter, Detail-Crawl, Persistenz

**Files:**
- Create: `airbi/scraper/search_crawl.py`
- Test: `tests/test_search_crawl.py`

Der Orchestrator besteht aus **reinen/DB-Funktionen** (vollständig testbar) und dem **browser-getriebenen Lauf** (in Task 10 real verifiziert).

- [ ] **Step 1: Failing Tests in `tests/test_search_crawl.py` schreiben**

```python
from decimal import Decimal

from airbi.db.models import CrawlRun, Listing, SearchConfig, Snapshot
from airbi.geo.districts import load_districts
from airbi.scraper.models import ListingDetail, ParsedListing
from airbi.scraper.search_crawl import (
    bounding_box_for,
    is_entire_home,
    merge_detail,
    persist_results,
)


def _parsed(airbnb_id, lat, lng, property_type="Apartment", review_count=10):
    return ParsedListing(
        airbnb_id=airbnb_id, title="T", url=f"u/{airbnb_id}", lat=lat, lng=lng,
        property_type=property_type, bedrooms=None, beds=None, bathrooms=None,
        max_guests=None, host_name=None, is_superhost=False,
        price=Decimal("100.00"), fees=None, review_count=review_count,
        rating=4.5, search_position=1,
    )


def test_bounding_box_covers_all_district_polygons():
    districts = load_districts()
    sw_lat, sw_lng, ne_lat, ne_lng = bounding_box_for(districts, margin=0.0)
    assert sw_lat <= 38.7390 <= ne_lat
    assert sw_lng <= -9.1044 <= ne_lng
    assert ne_lat > sw_lat and ne_lng > sw_lng


def test_is_entire_home_accepts_apartments_rejects_rooms():
    assert is_entire_home(_parsed("1", 38.74, -9.10, property_type="Apartment"))
    assert is_entire_home(_parsed("2", 38.74, -9.10, property_type="Loft"))
    assert not is_entire_home(_parsed("3", 38.74, -9.10, property_type="Room"))
    assert not is_entire_home(_parsed("4", 38.74, -9.10, property_type="Shared room"))


def test_merge_detail_fills_room_counts():
    pl = _parsed("1", 38.74, -9.10)
    detail = ListingDetail(bedrooms=2, beds=3, bathrooms=1.5, max_guests=4)
    merged = merge_detail(pl, detail)
    assert merged.bedrooms == 2
    assert merged.beds == 3
    assert merged.bathrooms == 1.5
    assert merged.max_guests == 4
    # Andere Felder unverändert.
    assert merged.airbnb_id == "1"
    assert merged.review_count == 10


def test_persist_results_creates_listing_snapshot_district_and_size_class(db_session):
    cfg = SearchConfig(name="Marvila Crawl", district_slugs=["marvila", "beato"])
    run = CrawlRun(search_config=cfg, status="running")
    db_session.add(run)
    db_session.flush()
    districts = load_districts()

    pl = merge_detail(
        _parsed("A1", 38.7390, -9.1044),
        ListingDetail(bedrooms=1, beds=2, bathrooms=1.0, max_guests=2),
    )
    persist_results(db_session, run, [pl], districts)

    listing = db_session.query(Listing).filter_by(airbnb_id="A1").one()
    assert listing.district_slug == "marvila"
    assert listing.size_class == "1BR"
    assert listing.bedrooms == 1
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

    assert db_session.query(Listing).filter_by(airbnb_id="A1").count() == 1
    assert db_session.query(Snapshot).count() == 2
    assert db_session.query(Snapshot).filter_by(crawl_run_id=run2.id).one().review_count == 25


def test_persist_results_marks_point_outside_polygons_unassigned(db_session):
    cfg = SearchConfig(name="X", district_slugs=["marvila"])
    run = CrawlRun(search_config=cfg, status="running")
    db_session.add(run)
    db_session.flush()
    persist_results(db_session, run, [_parsed("OUT", 38.5, -9.5)], load_districts())
    assert db_session.query(Listing).filter_by(airbnb_id="OUT").one().district_slug == "unassigned"
```

- [ ] **Step 2: Test laufen lassen, Fehlschlag verifizieren**

Run: `uv run pytest tests/test_search_crawl.py -v`
Expected: FAIL — `ModuleNotFoundError` für `airbi.scraper.search_crawl`.

- [ ] **Step 3: `airbi/scraper/search_crawl.py` schreiben**

Das Modul enthält:

**(a) `bounding_box_for(districts, margin=0.003)`** — reine Funktion. Vereinigt die `.bounds` (`(min_lng, min_lat, max_lng, max_lat)`) aller `shapely`-Geometrien aus `load_districts()`, addiert `margin` (Grad) als Rand, gibt `(sw_lat, sw_lng, ne_lat, ne_lng)` zurück.

**(b) `is_entire_home(parsed_listing) -> bool`** — reine Funktion. `True`, wenn `property_type` ein ganzes Objekt bezeichnet (Apartment, Loft, Condo, Home, Rental unit, Townhouse, Place, Villa, Cottage, …); `False` für „Room", „Shared room", „Private room", „Hostel" o. ä. Heuristik: `False`, wenn `property_type` (case-insensitiv) das Wort „room" enthält oder „hostel" ist; sonst `True`. `property_type is None` → `False`.

**(c) `merge_detail(parsed_listing, detail) -> ParsedListing`** — reine Funktion. Gibt ein neues `ParsedListing` zurück, bei dem `bedrooms`/`beds`/`bathrooms`/`max_guests` aus dem `ListingDetail` übernommen sind; alle anderen Felder unverändert (`dataclasses.replace` verwenden).

**(d) `persist_results(session, crawl_run, parsed_listings, districts)`** — schreibt in die DB:
- Pro `ParsedListing`: Listing per `(city_slug, airbnb_id)` suchen (`city_slug` = `crawl_run.search_config.city_slug`); existiert → Stammdaten aktualisieren, sonst neu anlegen.
- `district_slug` via `assign_district(lat, lng, districts)` (liefert `"unassigned"` bei keinem Treffer; bei fehlenden Koordinaten ebenfalls `"unassigned"`).
- `size_class` via `size_class(bedrooms)` aus `airbi.classification.size`.
- Pro Listing einen neuen `Snapshot` (`crawl_run_id`, Preis, Gebühren, `review_count`, `rating`, `search_position`).
- `session.flush()` am Ende; nicht committen (Aufrufer steuert die Transaktion). Gibt die Anzahl verarbeiteter Listings zurück.

**(e) `run_search_crawl(session, search_config, *, headless=True)`** — browser-getriebener Lauf:
- Legt einen `CrawlRun` (`status="running"`) an, `flush`.
- `load_districts()`, Filter auf `search_config.district_slugs`, `bounding_box_for(...)`.
- `browser_context()` öffnen, zur Map-Bounds-Such-URL navigieren (Muster siehe `scripts/record_stays_search.py`), das eingebettete Such-JSON aller Ergebnisseiten einlesen, `parse_search_results` anwenden, über `airbnb_id` deduplizieren.
- Mit `is_entire_home` auf Ganz-Apartments filtern.
- Für jedes gefilterte Listing: `/rooms/<id>` laden, eingebettetes Detail-JSON lesen, `parse_listing_detail`, per `merge_detail` die Raumzahlen einmergen. Menschliches Pacing (`pacing.human_delay`) zwischen Detailseiten.
- `persist_results(...)` aufrufen.
- **Block-Erkennung:** CAPTCHA-/Block-Seite erkannt oder 0 Suchergebnisse → `CrawlRun.status="failed"` mit klarer `message`; sonst `status="completed"`, `listings_seen` setzen, `finished_at` setzen.
- Bei Exception: `status="failed"`, `message` mit Fehler.
- `session.commit()` am Ende (anders als `persist_results` verwaltet `run_search_crawl` seine Transaktion selbst).
- `run_search_crawl` wird in den Unit-Tests NICHT aufgerufen (Browser); es bleibt dünn, die testbare Logik liegt in (a)–(d).

- [ ] **Step 4: Tests laufen lassen, Erfolg verifizieren**

Run: `uv run pytest tests/test_search_crawl.py -v`
Expected: PASS — alle 6 Tests grün.

- [ ] **Step 5: Commit**

```bash
git add airbi/scraper/search_crawl.py tests/test_search_crawl.py
git commit -m "feat: Crawl-Orchestrator (Bounding-Box, Entire-Home-Filter, Detail-Merge, Upsert)"
```

---

## Task 9: CLI — `airbi crawl`

**Files:**
- Create: `airbi/cli.py`

- [ ] **Step 1: `airbi/cli.py` schreiben**

Ein `argparse`-basiertes CLI mit `main(argv=None)` (Einstiegspunkt aus `[project.scripts]`):
- Unterbefehl `crawl` mit Option `--config NAME` (Name der `SearchConfig`) und Flag `--headful` (Browser sichtbar; default headless).
- `crawl`-Logik: DB-Session über `SessionLocal` aus `airbi.db.session`; `SearchConfig` per `name` laden. Nicht gefunden → klare Fehlermeldung auf stderr + Hinweis, dass die `SearchConfig` zuerst angelegt werden muss, Exit-Code 1. Sonst `run_search_crawl(session, config, headless=not args.headful)`; danach `CrawlRun`-Status + `listings_seen` auf stdout ausgeben.
- `main` liefert/setzt einen Exit-Code (0 bei `completed`, 1 bei `failed`/Fehler).

- [ ] **Step 2: CLI-Hilfe verifizieren**

Run: `uv run airbi crawl --help`
Expected: zeigt die Hilfe mit `--config` und `--headful`, kein Fehler.

- [ ] **Step 3: Verhalten bei fehlender SearchConfig verifizieren**

Run: `uv run airbi crawl --config "Gibt-es-nicht"`
Expected: klare Fehlermeldung auf stderr, Exit-Code 1, kein Stacktrace.

- [ ] **Step 4: Commit**

```bash
git add airbi/cli.py
git commit -m "feat: CLI-Befehl 'airbi crawl'"
```

---

## Task 10: End-to-End-Crawl gegen die echte Suche

**Files:** keine neuen — reale Verifikation des Gesamt-Crawls.

- [ ] **Step 1: Eine Marvila-`SearchConfig` in der lokalen DB anlegen**

```bash
uv run python -c "
from airbi.db.session import SessionLocal
from airbi.db.models import SearchConfig
s = SessionLocal()
if not s.query(SearchConfig).filter_by(name='Marvila Slice 1').first():
    s.add(SearchConfig(name='Marvila Slice 1', district_slugs=['marvila','beato']))
    s.commit(); print('SearchConfig angelegt')
else:
    print('SearchConfig existiert bereits')
s.close()
"
```

- [ ] **Step 2: Den echten Crawl ausführen**

Run: `uv run airbi crawl --config "Marvila Slice 1"`
Expected: Der Lauf öffnet einen Browser (headless), liest die Suchergebnisse, detail-crawlt die Ganz-Apartment-Listings und gibt am Ende `CrawlRun`-Status `completed` mit `listings_seen > 0` aus.

**Wenn der Lauf `failed` meldet** (Block/CAPTCHA/0 Ergebnisse): das ist das im Briefing benannte Scraper-Risiko. Mit `--headful` diagnostizieren. Lässt es sich nicht ohne Proxy lösen → eskalieren (NICHT durch Daten-Fälschung „grün machen"). Dokumentieren, was passiert ist.

- [ ] **Step 3: Die geschriebenen Daten verifizieren**

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
for sc in ('Studio','1BR','2BR','3BR+','unclassified'):
    print(f'  size {sc}:', s.query(Listing).filter_by(size_class=sc).count())
s.close()
"
```
Expected: `CrawlRuns` ≥ 1, `Listings` > 0, `Snapshots` == Anzahl im letzten Lauf gesehener Listings; ein plausibler Teil ist `marvila`/`beato` zugeordnet; die meisten Listings haben eine echte `size_class` (nicht `unclassified`) — das beweist, dass der Detail-Crawl die Zimmerzahlen geliefert hat.

- [ ] **Step 4: Volle Test-Suite + Commit (falls in diesem Task etwas geändert wurde)**

Run: `uv run pytest -q`
Expected: alle Tests grün (Plan-1- + Plan-2-Unit-Tests). Falls in Task 10 Korrekturen nötig waren, committen; sonst reine Verifikation.

---

## Definition of Done (Plan 2)

- [ ] `uv run pytest -q` — alle Tests grün (Plan 1 + Plan 2: `ParsedListing`/`ListingDetail`, Pacing, Such-Parser & Detail-Parser gegen Fixtures, Bounding-Box, `is_entire_home`, `merge_detail`, `persist_results`).
- [ ] `uv run airbi crawl --help` funktioniert.
- [ ] Ein echter Crawl (`airbi crawl --config "Marvila Slice 1"`) erzeugt einen `CrawlRun` mit Status `completed`, schreibt `Listing`- + `Snapshot`-Zeilen mit zugeordneten Bezirken UND echten `size_class`-Werten in die lokale `airbi`-DB.
- [ ] Such- und Detail-Fixtures liegen im Repo; beide Parser sind dagegen getestet.
- [ ] Alle Tasks committet; `scripts/record_stays_search.py` und `scripts/record_listing_detail.py` sind im Repo, `.playwright/` ist es nicht.

Damit füllt der Scraper die DB mit echten, größen-klassifizierten Daten. **Plan 3 (Insight & Dashboard)** wird danach geschrieben — Segment-Matrix (Größe × `price_tier`), Empfehlungstext, minimales FastAPI/HTMX-Dashboard, §12-Acceptance-Test.

## Bekannte, bewusst aufgeschobene Punkte

- `db_session`-Test-Fixture nutzt weiter das einfache Rollback-Muster (benigne `SAWarning` möglich, kein Daten-Leak) — savepoint-basierte Fixture bleibt optionaler Härtungspunkt.
- Voller Detail-Crawl für `amenity_score`/`luxury_class` bleibt Vertiefungsrunde (Slice 1 holt nur Raumzahlen).
