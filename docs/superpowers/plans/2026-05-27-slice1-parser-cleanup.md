# AirBI Slice-1 Parser-Cleanup — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Zwei Plan-2-Parser-/Filter-Bugs beheben — (B) no-price-Extraktion im Such-Parser (30% no-price im echten Crawl) und (A) Guesthouse-Privatzimmer-Filter in `is_entire_home` — und durch einen frischen Re-Crawl validieren.

**Architecture:** Discovery-First (Mirror Plan-2-Stil): Frische Such-Antwort aufnehmen, Strukturvarianten der no-price Listings im aufgezeichneten Befund dokumentieren, Parser gegen den realen Befund erweitern. Filter-Fix mit zwei zusätzlichen Title-Needles. E2E-Verifikation gegen die lokale DB.

**Tech Stack:** Python ≥3.11, Playwright (vorhandenes Aufnahme-Skript), pytest, SQLAlchemy 2.0.

**Bezug:** Umsetzung von `docs/superpowers/specs/2026-05-27-slice1-parser-cleanup-design.md`. Baut auf Slice-1-Code (`airbi/scraper/parser.py`, `airbi/scraper/search_crawl.py`) auf.

---

## Voraussetzungen

- Slice 1 (Plan 1 + 2 + 3) auf `main` gemerged. `airbi/scraper/parser.py`, `airbi/scraper/search_crawl.py`, `scripts/record_stays_search.py` vorhanden.
- `tests/fixtures/scraper/stays_search_page1.json` existiert (Plan-2-Aufnahme, 18 Listings).
- Lokales PostgreSQL läuft; in der DB liegt ein bestehender CrawlRun mit 23 Listings (darunter 7 no-price).
- `uv` auf dem PATH. Worktree/Feature-Branch über `superpowers:using-git-worktrees`.

## Wichtige Hinweise

- **Discovery-First.** Task 1 nimmt die frische Such-Antwort auf und legt den Strukturbefund fest. Task 2 schreibt den Parser-Fix erst, nachdem Task 1 zeigt, *welche* alternativen Preis-Pfade real vorkommen. Nicht „blind" patchen.
- **Fixture wird ersetzt.** `tests/fixtures/scraper/stays_search_page1.json` wird durch die frische Aufnahme **überschrieben** (Plan-2 hat die alte erzeugt; sie bleibt in der Git-Historie verfügbar). Damit ändern sich Listing-Count und ggf. einzelne Werte; Count-Tests müssen mitziehen.
- **Realistisches Outcome.** Wenn alle no-price Listings legitim sind (`structuredDisplayPrice = null`, kein anderer Preis-Pfad), bleibt der Parser ohne Pfad-Erweiterung — dann ist Task 2 eine reine Doku-Aufgabe (keine Pfad-Liste zu erweitern, aber Defensiv-Test gegen Null-Payload). Beide Pfade sind im Plan beschrieben.
- **Block-Risiko.** Plan-2 hat dokumentiert, dass die Aufnahme bisher unblocked war. Ein CAPTCHA-Block würde Task 1 fehlschlagen lassen; in dem Fall NICHT mit alter Fixture weitermachen, sondern eskalieren.

## Dateistruktur

| Datei | Status | Verantwortung |
|---|---|---|
| `scripts/record_stays_search.py` | ✏️ T1 | Kopfkommentar um Discovery-Befund erweitern |
| `tests/fixtures/scraper/stays_search_page1.json` | ✏️ T1 | Durch frische Aufnahme ersetzen |
| `tests/test_scraper_parser.py` | ✏️ T1 / ✏️ T2 | Count-Tests an neue Fixture anpassen (T1) + Variant-Tests (T2) |
| `airbi/scraper/parser.py` | ✏️ T2 | Preis-Pfad-Erweiterung (bedingt; falls Discovery alternative Pfade zeigt) |
| `airbi/scraper/search_crawl.py` | ✏️ T3 | `is_entire_home`-Title-Heuristik |
| `tests/test_search_crawl.py` | ✏️ T3 | `_parsed`-Helper um `title=`-Parameter + Guesthouse-Filter-Test |

---

## Task 1: Discovery — frische Such-Antwort + Test-Counts anpassen

**Files:**
- Modify: `scripts/record_stays_search.py` (Kopfkommentar)
- Replace: `tests/fixtures/scraper/stays_search_page1.json` (durch frische Aufnahme)
- Modify: `tests/test_scraper_parser.py` (Count-Tests)

- [ ] **Step 1: Aufnahme ausführen**

Run:

```bash
uv run python scripts/record_stays_search.py
```

Expected: Skript läuft 10-30s, gibt am Ende `Fixture gespeichert: tests/fixtures/scraper/stays_search_page1.json (<N> Bytes, <K> Suchergebnisse)` aus, mit `K >= 10`.

Bei CAPTCHA/Block: Aufnahme bricht mit `ValueError: Script-Tag 'data-deferred-state-0' nicht im HTML gefunden` oder `searchResults ist leer` ab. NICHT die alte Fixture wiederherstellen — eskalieren mit dem Skript-Output, eine Retry-Strategie wäre ggf. mit `headless=False`-Debug + manueller Inspektion zu klären.

- [ ] **Step 2: no-price-Listings in der Fixture identifizieren**

Run:

```bash
uv run python - <<'PY'
import json
from pathlib import Path
payload = json.loads(Path("tests/fixtures/scraper/stays_search_page1.json").read_text())
results = payload["data"]["presentation"]["staysSearch"]["results"]["searchResults"]
print(f"Total: {len(results)}")
no_price = []
for i, r in enumerate(results):
    sdp = r.get("structuredDisplayPrice")
    if sdp is None:
        no_price.append((i, r.get("title"), "structuredDisplayPrice=null", None))
        continue
    primary = sdp.get("primaryLine") or {}
    typename = primary.get("__typename")
    price_field = primary.get("price")
    if price_field:
        continue
    # Kein direkter price-Wert — alle alternative Felder enumerieren
    no_price.append((i, r.get("title"), typename, sorted(primary.keys())))
print(f"no-price: {len(no_price)}")
for entry in no_price:
    print(f"  idx={entry[0]} title={entry[1]!r}")
    print(f"    typename={entry[2]}  primaryLine-keys={entry[3]}")
PY
```

Expected: Liste der no-price Listings inkl. ihrer `primaryLine.__typename` und allen vorhandenen Schlüsseln in `primaryLine`. Wenn 0 no-price Listings: Fixture deckt den Fall nicht ab → Task 1 als „voll abgedeckt, kein Parser-Fix nötig" markieren und Task 2 wird konditional reduziert (siehe dortige Anleitung).

- [ ] **Step 3: Strukturvergleich mit-Preis vs. ohne-Preis**

Für jedes no-price Listing aus Step 2: schauen, wo der Preis in `r["structuredDisplayPrice"]` *tatsächlich* sitzt (falls überhaupt). Typische Kandidaten:

- `structuredDisplayPrice.primaryLine.discountedPrice`  (zusammen mit `originalPrice` als durchgestrichener Wert)
- `structuredDisplayPrice.primaryLine.displayString`     (Text-Form als Fallback)
- `structuredDisplayPrice.primaryLine.qualifiedPrice`    (alternative Felder-Namensvariante)
- `structuredDisplayPrice.displayPrice`                  (eine Ebene höher)
- `structuredDisplayPrice.secondaryLine.price`           (manchmal in der Total-Zeile statt Per-Nacht-Zeile)

Diagnose-Snippet (für jeden no-price Listing):

```bash
uv run python - <<'PY'
import json, sys
from pathlib import Path
payload = json.loads(Path("tests/fixtures/scraper/stays_search_page1.json").read_text())
results = payload["data"]["presentation"]["staysSearch"]["results"]["searchResults"]
IDX = int(sys.argv[1]) if len(sys.argv) > 1 else 0  # Index anpassen
sdp = results[IDX].get("structuredDisplayPrice")
print(json.dumps(sdp, indent=2, ensure_ascii=False)[:2000])
PY 0   # IDX als Argument; 0 durch den Index aus Step 2 ersetzen
```

Für jeden no-price Listing: notieren, welcher Pfad (falls überhaupt) den Preis enthält.

- [ ] **Step 4: Befund als Kopfkommentar in `scripts/record_stays_search.py` festhalten**

Im bestehenden Kopfkommentar von `scripts/record_stays_search.py` (nach dem „Preis-Pfad heute"-Abschnitt) einen neuen Block einfügen:

```python
"""
...

=== Aufnahme 2026-05-27: no-price-Discovery (Plan: 2026-05-27 Parser-Cleanup) ===

Aufnahme über die Marvila+Beato-Bounding-Box am 2026-05-27.
Total Listings: <K>
no-price Listings: <N> von <K>

Strukturvarianten der no-price Listings:

  Variante A: <z.B. structuredDisplayPrice = null>
    Vorkommen: <M> Listings (titles: ...)
    Recovery: <keiner / über displayPrice / etc.>

  Variante B: <z.B. primaryLine.__typename = DiscountedDisplayPriceLine>
    Vorkommen: <M> Listings
    Recovery: primaryLine.discountedPrice    (oder discountedPriceQualifier+price)

  Variante C: <weitere — pro entdeckter Variante>

Beobachtung: <freie Notiz zur Gesamtsituation, z.B.: "5 Listings sind genuinly
ohne Preis (structuredDisplayPrice=null) — wahrscheinlich ausgebucht oder neue
Listings; 2 Listings haben primaryLine.discountedPrice statt .price">
"""
```

Konkret die Werte aus Step 2 + 3 eintragen. Die Variante-Sektion ist die Spezifikation für Task 2.

- [ ] **Step 5: Bestehende Parser-Tests laufen lassen, brechende Counts ermitteln**

Run:

```bash
uv run pytest tests/test_scraper_parser.py -v
```

Expected: Mindestens diese Tests brechen, weil die Fixture jetzt nicht mehr 18 Listings hat:
- `test_search_parser_returns_all_18_results` (Count-Assertion auf 18)
- `test_search_parser_assigns_1_based_positions` (`range(1, 19)`)

Andere Tests (Felder typisiert, BBox, Property-Type, leeres Payload, `_parse_price`-Helper) sollten weiterhin grün sein.

- [ ] **Step 6: Counts an die neue Fixture anpassen**

In `tests/test_scraper_parser.py` die beiden Tests an die tatsächliche Listing-Anzahl `K` aus Step 1 anpassen. Der Funktionsname mit dem Literal `18` ist OK, aber inhaltlich an `K` koppeln:

Den Test

```python
def test_search_parser_returns_all_18_results():
    assert len(parse_search_results(_search_payload())) == 18
```

ersetzen durch (Funktionsname umbenennen, die `18` durch die konkrete Listing-Anzahl `K` aus Task 1 Step 1 ersetzen):

```python
def test_search_parser_returns_all_results_in_fixture():
    # Aktuelle Fixture: 18 Listings (siehe Aufnahme-Befund in
    # scripts/record_stays_search.py Kopfkommentar). Bei neuer Aufnahme
    # diese Zahl an die tatsächliche Listing-Anzahl anpassen.
    assert len(parse_search_results(_search_payload())) == 18
```

Den Test

```python
def test_search_parser_assigns_1_based_positions():
    listings = parse_search_results(_search_payload())
    assert [pl.search_position for pl in listings] == list(range(1, 19))
```

ersetzen durch:

```python
def test_search_parser_assigns_1_based_positions():
    listings = parse_search_results(_search_payload())
    assert [pl.search_position for pl in listings] == list(range(1, len(listings) + 1))
```

Diese Variante ist robust gegen weitere Fixture-Ersetzungen.

- [ ] **Step 7: Tests laufen lassen, alle grün**

Run:

```bash
uv run pytest tests/test_scraper_parser.py -v
```

Expected: PASS — alle Parser-Tests grün gegen die neue Fixture. Das ist die saubere Baseline für Task 2.

- [ ] **Step 8: Commit**

```bash
git add scripts/record_stays_search.py tests/fixtures/scraper/stays_search_page1.json tests/test_scraper_parser.py
git commit -m "chore: frische Such-Fixture + Test-Counts angepasst; no-price-Befund dokumentiert"
```

---

## Task 2: Parser-Pfad-Erweiterung (no-price)

**Files:**
- Modify: `airbi/scraper/parser.py`
- Modify: `tests/test_scraper_parser.py`

**Konditional:** Wenn Task 1 Step 4 zeigt, dass *keine* alternativen Preis-Pfade existieren (z.B. alle no-price Listings haben `structuredDisplayPrice = null` ohne anderswo nutzbaren Preis), wird Task 2 zu einer reinen Defensiv-Doku-Aufgabe. Beide Wege sind unten erklärt.

### Pfad A: Mindestens eine alternative Preis-Variante in der Fixture (häufigster Fall)

- [ ] **Step 1: Failing Test pro entdeckter Variante in `tests/test_scraper_parser.py` ergänzen**

Am Dateiende anhängen, **pro Variante einen Test**. Beispiel-Template — die konkrete `airbnb_id` und der erwartete Preis stammen aus dem Befund von Task 1 Step 4:

```python
def test_search_parser_extracts_price_from_discounted_line():
    """Listings mit primaryLine.__typename = DiscountedDisplayPriceLine
    haben den Preis unter primaryLine.discountedPrice statt .price.

    Die airbnb_id und die erwartete Preis-Eigenschaft stammen aus dem
    Discovery-Befund (Task 1 Step 4) — konkrete reale ID einsetzen, die
    in der aktuellen Fixture als Vertreter dieser Variante vorkommt.
    """
    listings = parse_search_results(_search_payload())
    target = next(pl for pl in listings if pl.airbnb_id == "REAL_ID_AUS_FIXTURE")
    assert target.price is not None
    assert target.price > 0
```

Den String `"REAL_ID_AUS_FIXTURE"` durch eine echte `airbnb_id` aus der aktuellen Fixture ersetzen (z.B. eine der in Task 1 Step 2 als no-price gelisteten IDs, deren Preis nach Pfad-Erweiterung extrahierbar sein wird). Pro identifizierter Variante (Discounted, displayString-Fallback, secondaryLine, …) ein eigener Test mit einer realen `airbnb_id`. Wenn Discovery zwei Varianten zeigt → zwei Tests.

Zusätzlich ein Defensiv-Test gegen Listings, die wirklich keinen Preis haben (auch wenn er heute schon grün ist):

```python
def test_search_parser_returns_none_price_when_structuredDisplayPrice_is_null():
    """Listings ohne strukturierten Preis (z.B. ausgebucht, nicht buchbar)
    bekommen price=None — kein Crash. Reale airbnb_id eines solchen
    Listings aus dem Discovery-Befund einsetzen; falls die Fixture keinen
    `structuredDisplayPrice=null`-Fall enthält, diesen Test weglassen.
    """
    listings = parse_search_results(_search_payload())
    target = next(pl for pl in listings if pl.airbnb_id == "REAL_NULL_SDP_ID_AUS_FIXTURE")
    assert target.price is None
```

- [ ] **Step 2: Tests laufen lassen, Fehlschlag verifizieren**

Run: `uv run pytest tests/test_scraper_parser.py -v`
Expected: FAIL — die neuen Variant-Tests scheitern (Parser nutzt nur den heute gültigen Pfad).

- [ ] **Step 3: `parser.py` — PRICE_PATHS-Konstante + Loop**

In `airbi/scraper/parser.py` **vor** `_parse_result` (z.B. nach `_parse_property_type`) eine Konstante einfügen:

```python
# Geordnete Liste der Preis-Pfade unter einem searchResult-Eintrag.
# Erste Variante mit nicht-None-Treffer gewinnt. Liste basiert auf
# Discovery-Befund (siehe scripts/record_stays_search.py Kopfkommentar).
PRICE_PATHS: tuple[tuple[str, ...], ...] = (
    ("structuredDisplayPrice", "primaryLine", "price"),
    # Nach Discovery-Befund weitere Pfade ergänzen, z.B.:
    # ("structuredDisplayPrice", "primaryLine", "discountedPrice"),
    # ("structuredDisplayPrice", "primaryLine", "displayString"),
)
```

Konkret die in Task 1 Step 4 dokumentierten Pfade in der Reihenfolge der Spezifität ergänzen (genauer Pfad zuerst, generischer Fallback wie `displayString` zuletzt).

In `_parse_result` die Zeile

```python
    price_str = _dig(r, "structuredDisplayPrice", "primaryLine", "price")
    price = _parse_price(price_str)
```

ersetzen durch:

```python
    price = None
    for path in PRICE_PATHS:
        price_str = _dig(r, *path)
        if price_str:
            price = _parse_price(price_str)
            if price is not None:
                break
```

Damit:
- Erste Variante mit String-Treffer wird via `_parse_price` zu `Decimal` gewandelt.
- Liefert `_parse_price(None)` oder `_parse_price("")` → `None`, dann weitersuchen.
- Wenn alle Pfade `None` liefern, bleibt `price=None` — korrekt für legitim preislose Listings.

- [ ] **Step 4: Tests laufen lassen, alle grün**

Run: `uv run pytest tests/test_scraper_parser.py -v`
Expected: PASS — Variant-Tests + Defensiv-Test + alle vorhergehenden Tests grün.

- [ ] **Step 5: Volle Test-Suite**

Run: `uv run pytest -q`
Expected: PASS — alle 65+ Tests grün.

- [ ] **Step 6: Commit**

```bash
git add airbi/scraper/parser.py tests/test_scraper_parser.py
git commit -m "feat: Such-Parser deckt zusätzliche Preis-Pfade ab (no-price-Fix)"
```

### Pfad B: KEINE alternativen Pfade — alle no-price sind genuinly preislos

In diesem Fall (Task 1 Step 4 zeigt nur `structuredDisplayPrice=null` ohne anderswo nutzbaren Preis):

- [ ] **Step 1: Defensiv-Test (gleicher wie Pfad A, nur dieser):**

In `tests/test_scraper_parser.py` am Dateiende (reale `airbnb_id` aus der Discovery einsetzen):

```python
def test_search_parser_returns_none_price_when_structuredDisplayPrice_is_null():
    """Bestätigt: Listings ohne strukturierten Preis bekommen price=None
    ohne Crash. Discovery 2026-05-27 zeigte mehrere Listings in der
    Marvila+Beato-Aufnahme in diesem Zustand (genuinly preislos —
    typischerweise ausgebucht oder inaktiv). Parser-Verhalten ist korrekt.
    Die airbnb_id stammt aus dem Discovery-Befund (Task 1 Step 4).
    """
    listings = parse_search_results(_search_payload())
    target = next(pl for pl in listings if pl.airbnb_id == "REAL_ID_AUS_FIXTURE")
    assert target.price is None
```

- [ ] **Step 2: Test laufen lassen, grün** (er ist bereits grün, weil das aktuelle Verhalten genau das ist — der Test dient als Regressionsschutz).

Run: `uv run pytest tests/test_scraper_parser.py -v`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/test_scraper_parser.py
git commit -m "test: Regression-Test für legitim preislose Listings (no-price-Discovery)"
```

In `parser.py` bleibt der bestehende Pfad unverändert. Plan-Outcome: dokumentierter Teil-Erfolg.

---

## Task 3: `is_entire_home` — Title-Heuristik gegen Guesthouse-Privatzimmer

**Files:**
- Modify: `airbi/scraper/search_crawl.py`
- Modify: `tests/test_search_crawl.py`

- [ ] **Step 1: `_parsed`-Helper in `tests/test_search_crawl.py` um `title=`-Parameter erweitern**

Die existierende Definition

```python
def _parsed(airbnb_id, lat, lng, property_type="Apartment", review_count=10):
    return ParsedListing(
        airbnb_id=airbnb_id, title="T", url=f"u/{airbnb_id}", lat=lat, lng=lng,
        property_type=property_type, bedrooms=None, beds=None, bathrooms=None,
        max_guests=None, host_name=None, is_superhost=False,
        price=Decimal("100.00"), fees=None, review_count=review_count,
        rating=4.5, search_position=1,
    )
```

durch folgende ersetzen (neuer `title`-Parameter mit Default `"T"`, damit bestehende Aufrufer unverändert weiterlaufen):

```python
def _parsed(airbnb_id, lat, lng, property_type="Apartment", review_count=10, title="T"):
    return ParsedListing(
        airbnb_id=airbnb_id, title=title, url=f"u/{airbnb_id}", lat=lat, lng=lng,
        property_type=property_type, bedrooms=None, beds=None, bathrooms=None,
        max_guests=None, host_name=None, is_superhost=False,
        price=Decimal("100.00"), fees=None, review_count=review_count,
        rating=4.5, search_position=1,
    )
```

- [ ] **Step 2: Failing Test in `tests/test_search_crawl.py` ergänzen**

Direkt nach `test_is_entire_home_accepts_apartments_rejects_rooms` (Zeile ~36) einfügen:

```python
def test_is_entire_home_rejects_guesthouse_with_private_room_title():
    """Plan-2-Befund: Airbnb klassifiziert manche Privatzimmer-Vermietungen
    als property_type='Guesthouse'. Der Title verrät die Tatsache ('Private
    Room with AC ...'). Property-Type-Filter allein reicht nicht."""
    assert not is_entire_home(_parsed(
        "X", 38.74, -9.10,
        property_type="Guesthouse",
        title="Private Room with AC & Self Check-in – Lisbon",
    ))
    # Auch 'shared room' im Titel filtert
    assert not is_entire_home(_parsed(
        "Y", 38.74, -9.10,
        property_type="Bed and breakfast",
        title="Cozy shared room near the center",
    ))


def test_is_entire_home_allows_apartment_with_unrelated_title():
    """Die Title-Heuristik darf normale Apartment-Titel nicht filtern."""
    assert is_entire_home(_parsed(
        "Z", 38.74, -9.10,
        property_type="Apartment",
        title="Bright Lisbon Riverside Cozy Apartment",
    ))
    # 'bedroom' im Titel ist KEIN Privatzimmer-Signal
    assert is_entire_home(_parsed(
        "W", 38.74, -9.10,
        property_type="Apartment",
        title="Lovely Loft - Master Bedroom Faces River",
    ))
```

- [ ] **Step 3: Tests laufen lassen, Fehlschlag verifizieren**

Run: `uv run pytest tests/test_search_crawl.py -v`
Expected: FAIL — `test_is_entire_home_rejects_guesthouse_with_private_room_title` scheitert, weil der heutige Filter nur `property_type` prüft. Der zweite Test (`allows_apartment_with_unrelated_title`) sollte schon grün sein.

- [ ] **Step 4: `is_entire_home` erweitern**

In `airbi/scraper/search_crawl.py` die Funktion

```python
def is_entire_home(parsed_listing: ParsedListing) -> bool:
    """True wenn das Listing eine ganze Unterkunft ist (kein Zimmer).

    Heuristik: False wenn `property_type` (case-insensitiv) das Wort "room"
    enthält oder exakt "hostel" ist; sonst True. None → False.
    """
    pt = parsed_listing.property_type
    if pt is None:
        return False
    lower = pt.lower().strip()
    if "room" in lower:
        return False
    if lower == "hostel":
        return False
    return True
```

ersetzen durch:

```python
# Title-Signale, die auf eine Privatzimmer-Vermietung hindeuten — zusätzlich
# zur property_type-Prüfung. Plan-2-Befund: Airbnb klassifiziert manche
# Privatzimmer in Guesthouses / B&Bs unter property_type='Guesthouse' o.ä.;
# der Listing-Name verrät den Privatzimmer-Charakter trotzdem.
_PRIVATE_ROOM_TITLE_NEEDLES: tuple[str, ...] = (
    "private room",
    "shared room",
)


def is_entire_home(parsed_listing: ParsedListing) -> bool:
    """True wenn das Listing eine ganze Unterkunft ist (kein Zimmer).

    Heuristik in zwei Stufen:
    1. False wenn ``property_type`` (case-insensitiv) das Wort "room" enthält
       oder exakt "hostel" ist.
    2. Zusätzlich False wenn der ``title`` (Listing-Name) ein Privatzimmer-
       Signal enthält (z.B. 'Private Room with AC ...' bei einem
       Guesthouse-Listing).

    ``property_type=None`` → False.
    """
    pt = parsed_listing.property_type
    if pt is None:
        return False
    lower_pt = pt.lower().strip()
    if "room" in lower_pt or lower_pt == "hostel":
        return False
    title = (parsed_listing.title or "").lower()
    if any(needle in title for needle in _PRIVATE_ROOM_TITLE_NEEDLES):
        return False
    return True
```

- [ ] **Step 5: Tests laufen lassen, alle grün**

Run: `uv run pytest tests/test_search_crawl.py -v`
Expected: PASS — neue Tests + alle bestehenden Tests grün.

- [ ] **Step 6: Volle Test-Suite**

Run: `uv run pytest -q`
Expected: PASS — alle Tests grün (Plan-1 + Plan-2 + Plan-3 + Cleanup-Plan).

- [ ] **Step 7: Commit**

```bash
git add airbi/scraper/search_crawl.py tests/test_search_crawl.py
git commit -m "feat: is_entire_home filtert Guesthouse-Privatzimmer via Title-Heuristik"
```

---

## Task 4: E2E — Re-Crawl-Verifikation

**Files:** keine neuen — reale Verifikation gegen die lokale DB.

- [ ] **Step 1: no-price-Anteil VOR dem Re-Crawl notieren**

Run:

```bash
uv run python - <<'PY'
from airbi.db.session import SessionLocal
from airbi.db.models import CrawlRun, Snapshot
s = SessionLocal()
latest = s.query(CrawlRun).filter_by(status="completed").order_by(CrawlRun.id.desc()).first()
total = s.query(Snapshot).filter_by(crawl_run_id=latest.id).count()
no_price = s.query(Snapshot).filter_by(crawl_run_id=latest.id).filter(Snapshot.price.is_(None)).count()
print(f"Vor-Crawl: crawl_run_id={latest.id}, total={total}, no-price={no_price} ({no_price/total*100:.1f}%)")
s.close()
PY
```

Expected: gibt die heutige Baseline aus (z.B. 7 von 23 = 30.4%).

- [ ] **Step 2: Re-Crawl ausführen**

Run:

```bash
uv run airbi crawl --config "Marvila Slice 1"
```

Expected: `Status: completed  |  listings_seen: <K>` mit `K > 0`. Falls `failed`: Skript-Output prüfen (CAPTCHA-Block?) — wenn ja, NICHT die Daten manipulieren, sondern eskalieren und dokumentieren.

- [ ] **Step 3: no-price-Anteil NACH dem Re-Crawl prüfen**

Run dasselbe Skript wie in Step 1 erneut:

```bash
uv run python - <<'PY'
from airbi.db.session import SessionLocal
from airbi.db.models import CrawlRun, Snapshot
s = SessionLocal()
latest = s.query(CrawlRun).filter_by(status="completed").order_by(CrawlRun.id.desc()).first()
total = s.query(Snapshot).filter_by(crawl_run_id=latest.id).count()
no_price = s.query(Snapshot).filter_by(crawl_run_id=latest.id).filter(Snapshot.price.is_(None)).count()
print(f"Nach-Crawl: crawl_run_id={latest.id}, total={total}, no-price={no_price} ({no_price/total*100:.1f}%)")
s.close()
PY
```

Expected: no-price-Anteil **deutlich gesunken** gegenüber Step 1. Zielwert: <10%. Mindesterfolg: <30%.

- [ ] **Step 4: Guesthouse-Listing prüfen**

Run:

```bash
uv run python - <<'PY'
from airbi.db.session import SessionLocal
from airbi.db.models import CrawlRun, Listing, Snapshot
s = SessionLocal()
latest = s.query(CrawlRun).filter_by(status="completed").order_by(CrawlRun.id.desc()).first()
# Das ursprüngliche Guesthouse-Listing aus Plan-2-Crawl
guesthouse_id = "868163894295620757"
in_latest = (
    s.query(Snapshot)
    .filter_by(crawl_run_id=latest.id)
    .join(Listing, Snapshot.listing_id == Listing.id)
    .filter(Listing.airbnb_id == guesthouse_id)
    .count()
)
print(f"Guesthouse-Listing id={guesthouse_id} im letzten Run: {'JA (FEHLER!)' if in_latest else 'NEIN (OK)'}")
s.close()
PY
```

Expected: `NEIN (OK)` — das Guesthouse-Listing taucht im neuen Snapshot-Set nicht auf, weil der erweiterte `is_entire_home`-Filter es jetzt rauswirft.

Wenn das Listing seit Plan 2 von Airbnb entfernt wurde (oder nicht mehr in der Such-Antwort ist), ist der Filter-Check inkonklusiv — in dem Fall dokumentieren als „Listing nicht mehr verfügbar, Filter-Verhalten via Unit-Test (`test_is_entire_home_rejects_guesthouse_with_private_room_title`) abgedeckt".

- [ ] **Step 5: Dashboard kurz öffnen**

Run im Hintergrund:

```bash
uv run airbi web --port 8000
```

Dann im Browser http://127.0.0.1:8000/ öffnen. Erwartung: deutlich mehr nicht-graue Zellen, eventuell auch ein Best-Cell-Highlight + echter Empfehlungssatz (statt „zu dünn"-Fallback), wenn der gesteigerte verwertbare Anteil zu mindestens einer Zelle mit `N ≥ 3` führt.

Falls weiterhin alles dünn: das ist ein Datenmengen-Problem (zu wenige Listings pro Bezirk × Zelle), nicht mehr ein Datenqualitäts-Problem. Plan-Outcome dokumentieren.

Server beenden:

```bash
pkill -f "airbi.web.app"
```

- [ ] **Step 6: Volle Test-Suite + Plan-Outcome dokumentieren**

Run: `uv run pytest -q`
Expected: PASS — alle Tests grün.

Wenn in Task 4 keine Code-Änderungen nötig waren, kein Commit. Sonst: eventuelle Korrekturen mit klarem Bezug zur §13-Re-Crawl-Verifikation committen.

---

## Definition of Done

- [ ] `uv run pytest -q` — alle Tests grün, inkl. der neuen Parser- und Filter-Tests.
- [ ] `scripts/record_stays_search.py` enthält im Kopfkommentar einen dokumentierten Discovery-Befund (Datum, Listing-Anzahl, no-price-Anteil, Strukturvarianten).
- [ ] `tests/fixtures/scraper/stays_search_page1.json` ist die frische Aufnahme; alte Counts in Tests angepasst.
- [ ] `airbi/scraper/parser.py` deckt die in Discovery entdeckten Preis-Pfade ab (oder enthält einen Defensiv-Test gegen `structuredDisplayPrice=null`, falls keine alternativen Pfade existieren).
- [ ] `airbi/scraper/search_crawl.py::is_entire_home` filtert Guesthouse-Privatzimmer per Title-Heuristik (`private room` / `shared room`).
- [ ] Re-Crawl-Verifikation: no-price-Anteil im neuen CrawlRun deutlich unter Baseline (Ziel <10%, Mindesterfolg <30%); Guesthouse-Listing nicht mehr im neuen Snapshot-Set (oder als „nicht mehr verfügbar" dokumentiert).
- [ ] Alle Tasks committet.

## Akzeptanz-Outcomes (aus Spec §9)

| Outcome | Definition | Aktion |
|---|---|---|
| **Voller Erfolg** | 0 no-price im neuen Run; Guesthouse-Listing weg; Best-Cell-Highlight sichtbar im Dashboard. | Plan mergen, fertig. |
| **Teil-Erfolg** | no-price-Anteil deutlich gesunken (z.B. 30% → <10%); verbleibende Cases als legitim genuinly preislos dokumentiert. | Plan mergen, fertig. |
| **Misserfolg / Block** | Re-Crawl liefert CAPTCHA oder unveränderten no-price-Anteil. | NICHT mergen. Plan-Outcome-Notiz im Repo, Eskalation. |

## Bewusst NICHT in diesem Plan (Spec §10)

- Voller Detail-Crawl für `amenity_score` / kombinierte `luxury_class` (das wäre Slice 2).
- Retrofit der bestehenden 7 no-price-Snapshots (immutable Zeitreihen).
- Schema-Änderungen, Datenmodell-Erweiterungen, UI-Änderungen.
- HTMX-Active-State-Sync (separate Slice-1-Hygiene-Runde).
- Tailwind-Rebuild-Dokumentation (separate Hygiene-Runde).
- Andere Code-Quality-Items aus den Slice-1-Reviews.
