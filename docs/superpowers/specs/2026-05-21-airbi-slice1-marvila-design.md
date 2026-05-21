# AirBI — Slice 1: „Marvila-Durchstich" — Design / Spec

> **Status:** Design abgestimmt, bereit für Implementierungsplanung
> **Datum:** 2026-05-21
> **Grundlage:** `BRIEFING-airbnb-bi-v0.3.0.md`
> **Auftraggeber:** Michael Alber (Remote Republic Labs)
> **Deployment-Ziel:** gehosteter Ubuntu-VPS (Single-Host)

---

## 1. Einordnung: Wo Slice 1 im Gesamtprojekt steht

Das im Briefing beschriebene MVP ist zu groß für **einen** Spec/Plan. Es wird in **5 Teilprojekte** zerlegt, die zugleich die Code-Struktur bilden:

| # | Teilprojekt | Inhalt |
|---|---|---|
| 1 | Fundament: Datenmodell & Geo | Postgres-Schema, Multi-City-Gerüst, GeoJSON-Bezirke, Point-in-Polygon |
| 2 | Scraper | Stufe A Search-Crawl + Stufe B Detail-Crawl, Anti-Detection, Scheduling |
| 3 | Klassifikation & Insights | size/price/amenity/luxury-Klassen, Review-Velocity, Segment-Matrix u. a. |
| 4 | Dashboard / UI | FastAPI+HTMX+Tailwind, alle Views |
| 5 | Deployment & Betrieb | systemd, APScheduler, Backup, Logging/Alerting |

**Build-Reihenfolge: vertikaler Durchstich.** Statt Teilprojekt für Teilprojekt wird zuerst ein dünner, durchgehender Pfad bis zum Acceptance-Test gebaut — dieser Pfad ist **Slice 1**. Danach vertiefen Folgerunden jede Schicht (Detail-Crawl, Amenity-Score, weitere Insights, Betriebshärtung).

**Slice 1 ist die erste Spec→Plan→Umsetzungs-Runde.** Die 5 Teilprojekte bleiben die Code-Struktur; Slice 1 schneidet einen dünnen vertikalen Streifen durch #1–#4.

## 2. Ziel von Slice 1

Den **Acceptance-Test aus Briefing §12** (Objekt R. Cap. Leitão 86, Bezirk Marvila) mit **echten Daten** zum Laufen bringen — bewusst so dünn wie möglich. Slice 1 beantwortet die Leitfrage #1 des Briefings (welche Größe × Luxusklasse) und validiert damit die Nachfrage÷Wettbewerb-Kernlogik.

Erfüllung von §12 in Slice 1:
- **Punkt 1 (Segment-Matrix):** voll erfüllt.
- **Punkt 2 (Wettbewerbsdichte je Segment):** voll erfüllt.
- **Punkt 3 (Top-Performer):** in Grundform — Liste je Segment aus Card-Daten, **ohne** Merkmals-Analyse aus Detail-Crawl.
- **Punkt 4 (Empfehlung in Worten):** voll erfüllt, inkl. Proxy-Kennzeichnung.
- **Bonus (Marvila ↔ Nachbarbezirk):** erfüllt — Beato ist von Anfang an als zweiter Bezirk dabei.

## 3. Getroffene Entscheidungen (Decision Log)

| Entscheidung | Wahl | Begründung |
|---|---|---|
| Build-Strategie | Vertikaler Durchstich | De-riskt Scraper UND Kernlogik früh, schnelles vorzeigbares Ergebnis am echten Use Case |
| Slice-1-Zuschnitt | **Ohne** Detail-Crawl (Stufe B) | Dünnster echter Durchstich; Luxus-Achse = `price_tier`. Detail-Crawl/`amenity_score`/`luxury_class` folgen in Vertiefungsrunde |
| Proxy-Infrastruktur | Slice 1 **ohne** Proxy | Ein einziger, kleiner Crawl-Lauf; Transport-Schicht bleibt proxy-fähig vorbereitet |
| Crawl-Methode | API-Interception im echten Browser | Strukturierte, vollständige Daten (`review_count`, Lat/Lng exakt), robust gegen DOM-Änderungen, briefing-konform (kein reiner HTTP-Request) |
| Server-Typ | Gehosteter VPS (Datacenter-IP) | Bestimmt die Slice-1-Topologie (siehe §11) |

## 4. Architektur & Code-Struktur

Eine Python-Anwendung; die Pakete spiegeln die 5 Teilprojekte, damit Folgerunden ohne Umbau wachsen.

```
airbi/
  airbi/
    config.py            App-Konfiguration (DB-URL etc.)
    db/        models.py (SQLAlchemy 2.0), session.py
    geo/       districts.py (GeoJSON laden + Point-in-Polygon)
               data/lisboa/*.geojson
    scraper/   browser.py (Playwright + Stealth, Transport-/Proxy-Schicht)
               search_crawl.py (Stufe A: StaysSearch-Interception, Pagination, Pacing)
               parser.py (StaysSearch-JSON -> Listing/Snapshot-Felder, browser-unabhängig)
               pacing.py (randomisiertes menschliches Timing)
    classification/  size.py (size_class), price.py (price_tier)
    insights/  segment_matrix.py
    web/       app.py (FastAPI), routes.py, templates/, static/
    cli.py               manueller Crawl-Trigger, Klassifikations-/Insight-Aufrufe
  alembic/               DB-Migrationen
  tests/
  pyproject.toml
```

- **Stack:** Python, SQLAlchemy 2.0 ORM + Alembic (Multi-City-Schema soll stabil migrierbar sein), `uv` als Paket-/Env-Manager.
- **YAGNI — Insight-Plugin-System:** Das Briefing will perspektivisch ein Plugin-/Registry-System für Insights. Bei **einer** Insight in Slice 1 wird die Segment-Matrix als eigenständiges Modul mit sauberem Funktions-Interface gebaut, **aber noch keine** Registry/Discovery-Maschinerie. Das thin `Insight`-Interface entsteht, wenn Insight #2/#3 dazukommen.

## 5. Datenmodell

PostgreSQL (vanilla, kein PostGIS). Vier Tabellen. Multi-City über `city_slug` an allen relevanten Entitäten; in Slice 1 existiert nur `lisboa`.

### 5.1 SearchConfig
Benannter, gespeicherter Suchkontext.
- `name`, `city_slug` (default `lisboa`)
- `district_slugs[]` — in Slice 1 `["marvila", "beato"]`
- `property_filter` (JSON) — Zimmer-Range, Property-Type, Preis-Range; in Slice 1 minimal genutzt
- `classification_config` (JSON) — konfigurierbare Tier-Grenzen, Größen-Mapping (später Amenity-Gewichte); sinnvolle Defaults, nicht hartkodiert
- `crawl_schedule` (nullable) — **für Vertiefungsrunde reserviert**, in Slice 1 ungenutzt
- `created_at`

### 5.2 CrawlRun
*Abweichung vom Briefing: vierte Entität, nicht in den „drei Haupt-Entities" genannt.* Notwendig, damit das UI Lauf-Status/Monitoring zeigen kann und Snapshots eindeutig einem Lauf zuordenbar sind.
- `search_config_id` (FK), `started_at`, `finished_at`, `status` (`running`/`completed`/`failed`), `listings_seen`, Fehlerinfo/Meldung

### 5.3 Listing
Relativ statische Stammdaten, global je Stadt (`airbnb_id` unique je `city_slug`). Ein Listing kann von mehreren SearchConfigs/CrawlRuns referenziert werden.
- `airbnb_id`, `city_slug`, `district_slug` (von uns per Point-in-Polygon berechnet; `unassigned` wenn in keinem Polygon)
- `url`, `title`, `lat`, `lng`, `property_type`, Zimmer/Betten/Bäder, `max_guests`, Host-Infos, `superhost`-Flag
- `size_class` — abgeleitet, **gespeichert** (stabil, hängt nur an der Zimmerzahl)
- **Reserviert/nullable (Phase 2 bzw. Detail-Crawl):** `license_number`, `al_status`, `description`, `amenities`

### 5.4 Snapshot
Zeitreihe pro Listing; jeder Eintrag gehört zu genau einem CrawlRun.
- `listing_id` (FK), `crawl_run_id` (FK), `captured_at`
- `price`, `fees`, `review_count`, `rating`, `search_position`

### 5.5 Abweichung: `price_tier` nicht gespeichert
Das Briefing listet `price_tier` als abgeleitetes Feld auf Listing. `price_tier` ist jedoch ein **Perzentil innerhalb eines Bezirks-Kohorts** und hängt an den konfigurierbaren Schwellen in `classification_config` — also kein stabiles Listing-Attribut. Daher:
- `size_class` → auf `Listing` gespeichert (stabil).
- `price_tier` → **zur Abfragezeit berechnet** (immer konsistent mit aktueller `classification_config`, keine veraltbaren Felder). Bei Slice-1-Datenmengen unkritisch; Materialisierung ist eine spätere Optimierung, falls das Datenvolumen wächst.

## 6. Geo-System

- Marvila + Beato als **GeoJSON-Polygone** in `airbi/geo/data/lisboa/` — initial aus den öffentlichen Freguesia-Grenzen abgeleitet, dann kuratiert. Kuratierte Tourismus-/Quartiers-Bezirke, keine Live-Quelle.
- Beim App-Start in `shapely`-Geometrien laden, gekeyt nach `district_slug`.
- Jedes Listing per **Point-in-Polygon** über `lat`/`lng` einem `district_slug` zuordnen; Treffer in keinem Polygon → `unassigned`.
- **Crawl-Bezug:** Airbnbs eigener Orts-Gruppierung wird nicht vertraut. Stufe A crawlt eine **Bounding-Box über Marvila+Beato** (mit kleinem Rand); die Bezirkszuordnung macht AirBI selbst per Point-in-Polygon. `unassigned`-Listings fließen nicht in die Bezirks-Insights ein.
- **Bekannte, akzeptierte Limitierung:** Airbnb verschleiert Listing-Koordinaten (~100–200 m Jitter). Für Bezirks-Level-Zuordnung unkritisch, außer direkt an Bezirksgrenzen — passt zum „richtungssicher, nicht bilanzsicher"-Anspruch des Briefings.
- Format so, dass eine neue Stadt später nur neue GeoJSONs + Crawl-Config braucht, keinen Code.

## 7. Scraper — Stufe A (Search-Crawl)

Oberstes Prinzip: so menschlich wie möglich, so wenig Requests wie nötig.

- **Playwright (Python) + Chromium**, Stealth-gehärtet (Fingerprint, `navigator.webdriver` etc.).
- **Persistenter Browser-Context** (`user_data_dir`) → Session/Cookies überleben Läufe (Briefing: Session-Persistenz).
- **Transport-/Proxy-Schicht** in `browser.py`: dünne Abstraktion, in Slice 1 „direkt" (kein Proxy); in der Vertiefungsrunde kommt der Residential-Proxy per Config dazu — kein Umbau.
- **Ablauf:** Browser öffnet die Airbnb-Suche für die Bounding-Box über Marvila+Beato. Über `page.on("response")` werden die `StaysSearch`-JSON-Antworten abgefangen, die der Browser beim Laden/Scrollen/Blättern selbst auslöst. Menschliches Scrollen + Pagination durch alle Ergebnisseiten, Dedup über `airbnb_id`.
- **Pacing** (`pacing.py`): randomisierte, menschliche Verzögerungen zwischen Aktionen, gelegentlich längere Pausen — kein gleichmäßiges Polling. Slice 1 = zwei kleine Bezirke, ein Lauf, geringes Volumen.
- **Parser getrennt** (`parser.py`): reine Funktion `StaysSearch`-JSON → Listing-/Snapshot-Felder, **browser-unabhängig** und gegen gespeicherte JSON-Fixtures testbar. Erwartete Felder: `airbnb_id`, Preis/Nacht, `rating`, `review_count`, `lat`/`lng`, Zimmer/Betten/Bäder, Titel, `property_type`.
- **Lauf-Lebenszyklus:** Jeder Crawl = eine `CrawlRun`-Zeile. Pro gesehenem Listing: Upsert `Listing` (+ Bezirkszuordnung), Insert `Snapshot`.
- **Block-Erkennung:** Bei erkannter CAPTCHA-/Block-Seite oder 0 Treffern bricht der Lauf sauber ab → `CrawlRun.status = failed` mit klarer Meldung, kein Weiterhämmern. Volles Monitoring/Alerting = Vertiefungsrunde.
- **Robustheit:** defensives Retry/Backoff bei transienten Fehlern. Da sich die interne `StaysSearch`-API ändern kann (Schema/Operation-Hash), ist die Parsing-Schicht isoliert und durch Fixtures regressionsabgesichert.
- **Trigger in Slice 1:** CLI vom Dev-Rechner (`airbi crawl --config "..."`). Kein UI-Crawl-Button (siehe §11).
- **Calendar-Crawling bleibt ausgeschlossen.**

## 8. Klassifikation

- **`size.py` — `size_class`** aus Schlafzimmerzahl: `Studio` / `1BR` / `2BR` / `3BR+`. Mapping mit sinnvollem Default in `classification_config`, justierbar. Auf `Listing` gespeichert. Listing ohne verwertbare Zimmerangabe → `unclassified`.
- **`price.py` — `price_tier`** aus ADR-Perzentilen **innerhalb des jeweiligen Bezirks**. ADR in Slice 1 = der Nacht-Preis aus dem Snapshot. Perzentile über die Crawl-Kohorte je Bezirk. Default-Tier-Grenzen z. B. Budget < P25 / Mid P25–P75 / Premium P75–P90 / Luxury > P90 — alle in `classification_config` justierbar. Zur Abfragezeit berechnet (§5.5).
- Klare Trennung: `size.py` rein Listing-lokal, `price.py` kohorten- und configabhängig.
- **Emerging-Bezirke:** Die in Briefing §5b/§7 erwähnte stärkere Amenity-Gewichtung für Marvila/Beato greift erst, wenn der `amenity_score` existiert (Vertiefungsrunde mit Detail-Crawl). In Slice 1 ist die Luxus-Achse bewusst rein `price_tier`.

## 9. Insight: Segment-Matrix

Modul `insights/segment_matrix.py`, eigenständig, klares Funktions-Interface: `SearchConfig` + Filter (Bezirk, `CrawlRun`) → strukturiertes Matrix-Ergebnis + Empfehlungstext.

- **Matrix:** Zeilen = `size_class` (Studio/1BR/2BR/3BR+), Spalten = `price_tier` (Budget/Mid/Premium/Luxury).
- **Pro Zelle:**
  - **Wettbewerbsdichte** `N` = Anzahl Listings in der Zelle.
  - **Nachfrage-Proxy** `R` = Summe `review_count` der Listings in der Zelle.
  - **Attraktivitäts-Score** = `R ÷ N` = Ø Reviews je Listing — wie viel Nachfrage jedes existierende Objekt im Schnitt zieht. Hoher Score bei zugleich niedrigem `N` = unterversorgter Sweet Spot.
  - **ADR** = Median-Nacht-Preis der Zelle, danebengestellt.
- **Empfehlungstext:** wählt die Zelle mit dem besten Attraktivitäts-Score unter den Zellen mit ausreichender Stichprobe und formuliert einen Satz, der `N` (Konkurrenz) und ADR (Preisniveau) explizit mitnennt — der Mensch beurteilt diese zwei weichen Kriterien selbst. Beispiel: *„Für Marvila ist Premium-1BR am attraktivsten — Ø Y Reviews/Objekt bei nur Z Wettbewerbern, ADR €W."* Inkl. Proxy-Kennzeichnung. Die Empfehlungs-Heuristik ist bewusst einfach und justierbar; ein explizit gewichtetes Modell ist Vertiefungs-Thema.
- **Dünne Zellen (kritisch für Marvila):** Marvila ist ein Emerging-Bezirk → viele Zellen mit `N = 0` oder sehr klein. Zellen unter einem konfigurierbaren Schwellwert `min_sample` werden als „zu dünn für belastbare Aussage" markiert und aus der Empfehlungsauswahl ausgeschlossen.
- **Top-Performer (schlank, inline):** keine eigenständige Plugin-Insight in Slice 1, sondern eine schlanke Liste — die stärksten Listings je Segment nach `review_count`/`rating` aus Card-Daten. Merkmals-Analyse aus Detail-Crawl = Vertiefungsrunde.
- **Unterversorgung:** in Slice 1 direkt aus der Matrix ablesbar (hoher Score + niedriges `N`); eine eigene Ranking-Sicht kommt später.
- **Demand-Proxy-Annahme:** Nur ein Bruchteil der Gäste bewertet (Briefing: ~30–50 %). Als konfigurierbarer Parameter anlegen; abgeleitete Nachfrage überall als **Proxy** kennzeichnen.

## 10. Dashboard / UI

- **FastAPI + HTMX + Tailwind**, kein Build-Step (Tailwind via Standalone-CLI-Binary — kein Node; HTMX via CDN). Läuft direkt auf dem VPS.
- **Eine Dashboard-Seite:**
  - SearchConfig auswählen/anlegen (Slice 1: die Marvila-Config; Anlegen minimal, Schema kann mehr).
  - **Segment-Matrix** als farbcodierte HTML-Tabelle (Heatmap-Stil — klarer als ein Chart bei 4×4), Filter auf Bezirk (Marvila / Beato / beide). Pro Zelle: Attraktivitäts-Score, `N`, ADR; dünne Zellen ausgegraut/markiert.
  - **Empfehlungstext** prominent.
  - **Top-Performer-Liste** (schlank, je Segment).
  - **CrawlRun-Status-Panel:** letzter Lauf, Zeitpunkt, Status, Listing-Anzahl.
- **Proxy-Kennzeichnung durchgängig:** jeder Nachfrage-Wert mit Badge/Tooltip „Proxy — basiert auf Review-Count, keine gemessene Auslastung".
- **Kein UI-Crawl-Button** in Slice 1 (CLI-only, siehe §11). Plotly erst, wenn ein echter Chart Mehrwert bringt — YAGNI.

## 11. Slice-1-Topologie & Deployment

Server-Typ: gehosteter VPS mit Datacenter-IP. Daraus folgt:

- **Auf dem VPS:** PostgreSQL + Web-App (FastAPI/uvicorn).
- **Auf dem Dev-Rechner:** der Crawl (CLI). Der proxy-lose Slice-1-Crawl braucht eine Residential-IP — der VPS hat keine. Der Crawl läuft daher vom Dev-Rechner.
- **DB-Zugriff des Crawls:** über einen **SSH-Tunnel** zum VPS-Postgres (Postgres bleibt nach außen geschlossen).
- **Crawl-Trigger:** CLI-only vom Dev-Rechner. Der UI-Crawl-Button entsteht erst, wenn in der Vertiefungsrunde der Residential-Proxy auf dem Server sitzt.
- **Noch nicht in Slice 1 (Vertiefungsrunde #5):** systemd-Units (Auto-Restart, Boot-Persistenz), APScheduler (automatische Crawls), Backup-Konzept, volles Logging/Alerting. Die App *funktioniert* auf dem VPS auch ohne diese Härtung; sie ist nur noch nicht betriebsabgesichert.

## 12. Testing

- **Vorgehen:** TDD.
- **Unit-Tests:** `size_class`-Mapping; `price_tier`-Perzentil-Logik; Point-in-Polygon (Fixture-Polygone + bekannte Punkte); Segment-Matrix-Aggregation (Fixture-Listings/Snapshots → bekannte Matrix); Empfehlungsauswahl inkl. `min_sample`-Verhalten.
- **Parser-Tests:** gegen einmalig aufgezeichnete echte `StaysSearch`-JSON-Fixtures → Parser-Output geprüft. Sichert den fragilsten Teil regressionsfest.
- **Browser-/Crawl-Schicht:** nicht deterministisch unit-testbar → dünner Smoke-Test + manuelle Verifikation.
- **DB:** Tests gegen Test-Postgres, Transaktions-Rollback pro Test.
- **Acceptance-Test (§13):** manuelle End-to-End-Abnahme zum Abschluss von Slice 1.

## 13. Acceptance-Kriterien (aus Briefing §12)

Slice 1 ist abgenommen, wenn:

1. Ein CLI-Crawl vom Dev-Rechner für die Marvila+Beato-Bounding-Box durchläuft, einen `CrawlRun` mit `status = completed` erzeugt und Listings/Snapshots in die VPS-DB schreibt.
2. Im Dashboard für Bezirk **Marvila** die **Segment-Matrix** (Größe × `price_tier`) erscheint, mit dem attraktivsten Feld klar markiert.
3. Die **Wettbewerbsdichte** `N` je Segment sichtbar ist.
4. Eine schlanke **Top-Performer-Liste** je Segment angezeigt wird (aus Card-Daten).
5. Eine **Empfehlung in Worten** erscheint („Für diese Lage ist Segment X am attraktivsten, weil …"), mit Proxy-Kennzeichnung der Nachfragewerte.
6. Der **Bonus** erfüllt ist: Marvila und Beato lassen sich nebeneinander vergleichen.
7. Dünn besetzte Zellen sind als „zu dünn für belastbare Aussage" gekennzeichnet und nicht Teil der Empfehlung.

## 14. Bewusst NICHT in Slice 1

- Detail-Crawl Stufe B, `amenity_score`, kombinierte `luxury_class`.
- Review-Velocity (braucht mehrwöchige Snapshot-Historie).
- APScheduler, systemd-Units, Backup, volles Monitoring/Alerting.
- Residential-Proxy-Provider (Transport-Schicht ist vorbereitet, kein Provider angebunden).
- UI-Crawl-Button.
- Eigenständige Unterversorgungs- und Top-Performer-Insight-Module mit Detail-Tiefe.
- Insight-Plugin-Registry/Discovery.
- Mehrere SearchConfigs / Cross-Search-Vergleiche (Schema erlaubt es, Slice 1 nutzt eine Config).
- Multi-City über Lissabon hinaus.
- AirDNA / externe Performance-Daten, Saisonalität, AL-Lizenz-Layer, PostGIS, automatisches Pricing (alles Phase 2 lt. Briefing).
