# `airbi crawl` Resilience — Design

> Status: freigegeben (2026-06-04)
> Anschluss an `2026-06-02-refresh-details-resilience` (refresh-details ist
> bereits resilient). Schließt die Hygiene-Schuld aus dem Memory-File
> `airbi-crawl-sleep-fragility`.

## 1. Ziel

`airbi crawl` (vollständiger Lauf: 5 konzentrische Boxen + Detail-Phase)
soll unterbrechungsfest werden — analog zu `refresh-details`. Ein Abbruch
(Sleep, Hang, Kill) verliert maximal eine Box bzw. ein Detail-Listing,
nicht den ganzen Lauf. Wiederholen → resumiert nahtlos.

## 2. Architektur

Refactor splittet den Lauf in zwei Phasen, beide resilient:

### 2.1 Search-Phase (Box-weise)
- Pro Box: paginieren, parsen, **Entire-Home- und Distanz-Filter**, dann
  `persist_results` + `session.commit()`.
- Listings persistieren mit `bedrooms=None`, `amenities=[]`, `description=None`
  (Search-only Daten). `size_class` bleibt vorerst `"unclassified"`, der
  `amenity_score` ist nahe 0 — beide werden in der Detail-Phase korrekt.
- Granularität: ein Box-Abbruch verliert nur diese Box; Boxen davor sind
  fest im DB.

### 2.2 Detail-Phase (delegiert)
- Nach der Search-Phase ruft `run_search_crawl` direkt `refresh_details(
  session, search_config)` auf.
- `refresh_details` ist bereits resilient (per-Listing-Commit, Resume via
  `bedrooms IS NOT NULL`, Browser-Restart alle 50). Keine Duplikat-Logik
  nötig.

### 2.3 Auto-Resume
- Beim Start sucht `run_search_crawl` einen `status="running"`-CrawlRun für
  die gleiche `SearchConfig`. Existiert einer → fortsetzen statt neu anlegen.
- Sonst: neuer CrawlRun, sofort committet (damit ein späteres Resume ihn
  findet).

### 2.4 Snapshot-Dedup
- `persist_results` prüft beim Anlegen eines Snapshots, ob bereits einer
  für `(listing.id, crawl_run.id)` existiert. Wenn ja → Snapshot wird nicht
  neu angelegt (Listing-Stammdaten werden trotzdem geupdated).
- Macht **Re-Persist** während Resume oder Box-Überlapp ungefährlich.

## 3. Auswirkungen

- Listings-Daten in der DB sind **konsistent**, aber **temporär partiell**
  zwischen Search-Phase-Ende und Detail-Phase-Ende. Das Dashboard sieht
  unclassified Größen, bis die Detail-Phase durch ist.
- Run-Status:
  - `running` während Search-Phase und Detail-Phase
  - `completed` erst, wenn beide durch sind
  - Bei Crash mitten in Phase: `running` bleibt → Resume möglich

## 4. CLI

- Keine neuen Flags. `airbi crawl --config NAME` ist unverändert — Resume
  ist automatisch.

## 5. Tests

- `test_persist_results_dedupes_snapshot_per_run`: per-Run-Snapshot-Dedup.
- Bestehende `persist_results`-Tests bleiben grün (Single-Call-Pfad ohne
  Duplikate).
- `run_search_crawl` selbst bleibt browser-abhängig und ist nicht unit-
  testbar; Verifikation via Live-Lauf.

## 6. Bewusst NICHT im Scope

- Cluster-Coordinator für parallele Crawls.
- Persistierung der `parsed_listings`-Zwischenstände auf Disk (DB reicht).
- Telemetry/Metrics-Backend.
