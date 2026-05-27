# AirBI — Slice-1-Parser-Cleanup — Design / Spec

> **Status:** Design abgestimmt, bereit für Implementierungsplanung
> **Datum:** 2026-05-27
> **Grundlage:** `BRIEFING-airbnb-bi-v0.3.0.md`, Slice-1-Spec `2026-05-21-airbi-slice1-marvila-design.md`
> **Auftraggeber:** Michael Alber (Remote Republic Labs)
> **Vorausgesetzt:** Slice 1 (Plan 1 + 2 + 3) ist auf `main` gemerged. Ein Plan-2-Crawl liegt in der DB.

---

## 1. Einordnung

Diese Runde ist **kein** neuer Slice (kein vertikaler Durchstich) und auch keine Vertiefungsrunde aus der Spec §14-Backlog-Liste. Sie repariert zwei **Datenqualitäts-Bugs aus Plan 2**, die der erste echte Crawl sichtbar gemacht hat:

- **Befund B (Haupt-Bug):** 7 von 23 Listings (30%) haben im Snapshot keinen Preis. Der Such-Parser deckt nur eine `primaryLine`-Variante ab (`structuredDisplayPrice → primaryLine → price`) und gibt für alle anderen `None` zurück. Diese Listings fallen mit `price_tier="unclassified"` aus der Segment-Matrix.
- **Befund A (Sekundär-Bug):** 1 dieser 7 Listings hat `property_type="Guesthouse"` und im Titel „Private Room with AC..." — also faktisch ein Privatzimmer in einem Guesthouse, kein ganzes Apartment. Der Plan-2-Filter `is_entire_home` prüft nur `property_type` (`"room"`/`"hostel"`) und lässt Guesthouse-Privatzimmer durch.

Beide Fixes betreffen `airbi/scraper/`. Sie werden in einem gemeinsamen Plan umgesetzt, weil sie dieselbe Re-Crawl-Verifikation am Ende teilen.

## 2. Ziel

- `Snapshot.price IS NULL`-Anteil nach Re-Crawl **deutlich unter** 30% (Erwartung <10%, idealerweise 0%).
- Guesthouse-Privatzimmer fließen nicht mehr als „ganzes Apartment" in die Matrix.
- Existierende Tests bleiben grün; neue Tests decken jede entdeckte Strukturvariante und den Guesthouse-Fall ab.
- Slice-1-Spec, Datenmodell, Insight und Dashboard bleiben **unverändert**.

## 3. Getroffene Entscheidungen (Decision Log)

| Entscheidung | Wahl | Begründung |
|---|---|---|
| Befunde bündeln | Beide in einem Plan | Geteilte Re-Crawl-Verifikation; beide sind Plan-2-Scraper-Datenqualitäts-Bugs. |
| Approach | Discovery-First | Mirror Plan-2-Stil: frische Such-Antwort aufnehmen → Struktur sehen → gezielt fixen. Nicht „blind" auf vermutete Varianten patchen. |
| Bestehende Fixture | Ersetzen, nicht parallel führen | Halten die Test-Suite stabil an einem bekannten Pfad. Die alte Fixture bleibt in der Git-Historie verfügbar. |
| Existierende no-price-Snapshots in der DB | Kein Retrofit | `Snapshot` ist eine immutable Zeitreihe. Der nächste CrawlRun erzeugt neue Snapshots mit Preisen; `compute_segment_matrix` nutzt nur den letzten CrawlRun. |
| Scope-Grenzen | Nur Parser + Filter + Fixture + Tests + Re-Crawl-Verifikation | Keine Schema-Änderungen, keine UI, keine Klassifikations-Erweiterungen. |

## 4. Architektur & Code-Struktur

Die Slice-1-Struktur bleibt. Diese Runde ändert nur Code unter `airbi/scraper/` und die zugehörigen Tests + Fixture.

```
airbi/
  scraper/
    parser.py            ← Preis-Pfad-Erweiterung in parse_search_results
    search_crawl.py      ← is_entire_home Title-Heuristik
scripts/
  record_stays_search.py ← unverändert; einmal ausführen für die frische Aufnahme
tests/
  fixtures/scraper/stays_search_page1.json  ← ERSETZT durch frische Aufnahme
  test_scraper_parser.py                   ← neue Variant-Tests
  test_search_crawl.py                     ← neuer Guesthouse-Filter-Test
```

## 5. Discovery-Flow

Plan 2 hat das Aufnahme-Skript `scripts/record_stays_search.py` etabliert; es wird unverändert wiederverwendet.

1. **Frische Such-Antwort aufnehmen** über die existierende Marvila+Beato-Bounding-Box. Das Skript zieht heute nur Seite 1. Für die Discovery genügt das — 30% no-price-Anteil im echten Sample bedeutet, dass in einem 18er-Ergebnis statistisch 5–6 Beispiele zu erwarten sind.
2. **Wenn Seite 1 trotzdem keinen no-price-Listing zeigt:** zweite Aufnahme mit erweitertem Bezirksraster (z.B. ganz Lisboa) als Plan-B. Vorab nicht eingeplant; nur wenn nötig.
3. **Strukturvergleich** mit-Preis vs. ohne-Preis: die Pfade hinter `structuredDisplayPrice` werden dokumentiert.
4. **Befund als Kopfkommentar in `record_stays_search.py`** ablegen — gleicher Stil wie die Discovery-Tasks in Plan 2.

**Risiken:**
- **CAPTCHA / Block:** Plan-2-Befund — ein einzelner Lauf mit menschlichem Pacing war bisher unblocked, aber das Risiko ist real. Eskalieren, nicht still raten.
- **Listings haben legitim keinen Preis:** Wenn `structuredDisplayPrice = null` echt ist (z.B. Listing nicht buchbar, „long-term only", neu/inaktiv), bleibt `price=None` korrekt. Das Plan-Outcome ist dann ein **Teil-Erfolg**, kein voller Fix.

## 6. Parser-Fixes

### 6.1 No-price-Pfad-Erweiterung (`parser.py`)

Die konkrete Liste der zu prüfenden Pfade hängt vom Discovery-Befund ab und wird im Plan **erst nach Task 1 verbindlich festgelegt**. Die Architektur ist eine geordnete Pfad-Liste:

```python
PRICE_PATHS = [
    ("structuredDisplayPrice", "primaryLine", "price"),            # heute
    ("structuredDisplayPrice", "primaryLine", "discountedPrice"),  # vermutet
    ("structuredDisplayPrice", "primaryLine", "displayString"),    # Text-Fallback
    # weitere nach Discovery-Befund
]
```

Loop: erste Variante mit nicht-None-Rückgabe gewinnt; `_parse_price` extrahiert die Zahl aus dem String. Wenn alle Pfade `None` liefern, bleibt `price=None` — das ist korrekt für Listings ohne publizierten Preis.

Begründete Kandidaten basierend auf Airbnb-API-Konventionen:
- `primaryLine.discountedPrice` (rabattierte Listings: durchgestrichener Originalpreis im `originalPrice`, aktueller Preis im `discountedPrice`)
- `primaryLine.qualifiedPrice` / `primaryLine.qualifier`
- `primaryLine.displayString` (textbasiert; `_parse_price` kann es bereits parsen)
- `displayPrice` direkt unter `structuredDisplayPrice`

`_dig` und `_parse_price` existieren bereits — sie navigieren bzw. extrahieren defensiv. Pro entdeckter Variante kommt ein TDD-Test gegen die aktualisierte Fixture.

### 6.2 Guesthouse-Privatzimmer-Filter (`search_crawl.py`)

`is_entire_home` heute:

```python
def is_entire_home(pl: ParsedListing) -> bool:
    if pl.property_type is None:
        return False
    pt = pl.property_type.lower()
    return not ("room" in pt or pt == "hostel")
```

Erweiterung — zusätzlich Title-Heuristik:

```python
def is_entire_home(pl: ParsedListing) -> bool:
    if pl.property_type is None:
        return False
    pt = pl.property_type.lower()
    if "room" in pt or pt == "hostel":
        return False
    title = (pl.title or "").lower()
    if any(needle in title for needle in (
        "private room", "shared room", "room with", "room in",
    )):
        return False
    return True
```

Begründung: Plan-2 extrahiert `property_type` aus `r["title"]` (vor „ in "). „Private Room with AC – Lisbon" → `property_type` aus Tile-Field kann „Guesthouse" sein (Airbnb-Klassifikation der Unterkunfts-Art), aber der Titel-Anfang signalisiert klar Privatzimmer-Vermietung. Die Heuristik bleibt konservativ — Apartment-Titel wie „Room with a view" wären False Negatives, aber: a) die englischsprachige Phrase „room with" im Sinne „mit Zimmer" ist auf Airbnb-Titeln untypisch, b) der Property-Type-Filter fängt offensichtliche „Room"-Klassifikationen schon vorher ab, die Title-Heuristik ist nur die zusätzliche Sicherung für Guesthouse/B&B.

## 7. Test-Strategie

- **TDD pro Variante.** Discovery liefert N Strukturvarianten; pro Variante ein Test.
- **Bestehende Parser-Tests** (z.B. „returns 18 results", „first result in lisbon bbox") werden mit der neuen Fixture neu ausgelotet — Counts/Lat-Range-Asserts werden ggf. an die neue Aufnahme angepasst. Tests, die *Verhalten* prüfen (Felder typisiert, Position 1-basiert, keine Crash auf leerem Input), bleiben strukturell.
- **Neuer Test** `test_is_entire_home_rejects_guesthouse_with_private_room_title` in `tests/test_search_crawl.py`.
- **Negativtest** `test_search_parser_returns_none_for_truly_priceless_listing` — wenn `structuredDisplayPrice=null` in der Fixture als legitimer Fall vorkommt, ist `price=None` korrekt.

## 8. E2E-Verifikation

Letzter Plan-Task:

1. Echten Re-Crawl ausführen: `uv run airbi crawl --config "Marvila Slice 1"` — neuer CrawlRun.
2. DB-Check: `Snapshot.price IS NULL`-Anteil im neuen Run **<10%** (Ziel; <30% ist Mindesterfolg).
3. Guesthouse-Listing `id=868163894295620757` („Private Room with AC...") **nicht mehr** im neuen Run.
4. Dashboard prüfen: falls jetzt Zellen `N≥3` erreichen, erscheint ein Best-Cell-Highlight und echter Empfehlungstext. Falls weiterhin dünn, dokumentieren — das ist dann ein Datenmengen-, kein Datenqualitäts-Problem mehr (Slice-2-Thema).

## 9. Akzeptanz-Outcomes

| Outcome | Definition | Aktion |
|---|---|---|
| **Voller Erfolg** | 0 no-price im neuen Run; Guesthouse-Listing weg; Best-Cell-Highlight sichtbar. | Plan abnehmen, mergen. |
| **Teil-Erfolg** | no-price-Anteil deutlich gesunken (z.B. 30% → <10%); verbleibende Cases dokumentiert. | Plan abnehmen, mergen; verbleibende Strukturvarianten im Repo notieren (z.B. Issue-Backlog). |
| **Misserfolg / Block** | Re-Crawl liefert CAPTCHA oder unveränderten no-price-Anteil. | NICHT mergen ohne Eskalation. Plan-Outcome-Kommentar im Repo. |

## 10. Out of Scope (bewusst NICHT in dieser Runde)

- Voller Detail-Crawl für `amenity_score` / kombinierte `luxury_class` (das wäre Slice 2).
- Retrofit der existierenden 7 no-price Snapshots (immutable Zeitreihen).
- Schema-Änderungen, Datenmodell-Erweiterungen, UI-Änderungen.
- HTMX-Active-State-Sync (Slice-1-UX-Issue, separate Runde).
- Tailwind-Rebuild-Dokumentation (separate Hygiene-Runde).
- Andere Code-Quality-Items aus den Slice-1-Reviews (Edge-Case-Tests, `not max_score`-Truthiness, etc.).

---

*Diese Runde ist klein und mechanisch. Sie bringt die Slice-1-Datenbasis auf ein Niveau, das die nächste Vertiefungsrunde (Slice 2 = voller Detail-Crawl + Amenity-Score + Luxury-Class) auf sauberen Daten aufsetzen lässt.*
