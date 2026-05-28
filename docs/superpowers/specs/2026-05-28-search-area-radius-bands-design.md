# Suchgebiet: Umkreis-Bänder ums Zielobjekt — Design

> Status: freigegeben (Brainstorming 2026-05-28)
> Ersetzt die bezirksbasierte Eingrenzung (Marvila/Beato-Freguesias) durch
> distanzbasierte Bänder um das Investitionsobjekt.

## 1. Ziel

Das Suchgebiet wird nicht mehr über administrative Bezirke (Freguesia-Polygone)
definiert, sondern als **konzentrische Bänder um das Zielobjekt** (R. Cap.
Leitão 86, Marvila). Der Crawl sammelt Listings in mehreren Rechtecken um das
Objekt; die Auswertung gruppiert nach **Distanz-Umkreis** und ist im Backend/
Dashboard **umschaltbar** (1 / 2 / 3 / 5 / 10 km) — ohne Re-Crawl.

**Motivation:** Bezirke sind investment-irrelevant und administrativ grob
geschnitten; die große Bezirks-Bounding-Box liefert dünne Daten im eigentlich
wichtigen Nahbereich. Vergleichbarkeit bemisst sich an der Distanz zum Objekt,
nicht an der Freguesia-Zugehörigkeit.

## 2. Kernidee in zwei Schritten

Airbnb akzeptiert nur **rechteckige Karten-Viewports** (`ne_lat/ne_lng/sw_lat/
sw_lng`), kein Polygon und keinen Radius. Daraus folgen zwei getrennte Schritte:

1. **Crawl (senden):** Pro Band-Radius ein quadratisches Rechteck um das Objekt
   (Strategie B — konzentrische Rechtecke). Jede Box einzeln gecrawlt +
   paginiert, über alle Boxen per `airbnb_id` dedupliziert. Kleine Boxen
   (1/2/3 km) liefern dichten Nahbereich; große (5/10 km) Kontext-Stichprobe.
2. **Auswertung (filtern):** Keine gespeicherte Band-Zuordnung. Pro Listing wird
   zur Query-Zeit die echte Distanz (Haversine) zum Objekt berechnet. Ein
   Parameter `radius_km` definiert die Kohorte = alle Listings des letzten Runs
   mit Distanz ≤ radius_km (**kumulativ** = „im Umkreis").

## 3. Konfiguration (SearchConfig)

Neue Felder auf `SearchConfig` (alle additiv, keine destruktive Migration):

| Feld | Typ | Default | Bedeutung |
|------|-----|---------|-----------|
| `center_lat` | Float, nullable | NULL | Breite des Zielobjekts |
| `center_lng` | Float, nullable | NULL | Länge des Zielobjekts |
| `center_label` | String(200), nullable | NULL | Anzeigename, z. B. „R. Cap. Leitão 86" |
| `band_radii_km` | JSON | `[1, 2, 3, 5, 10]` | Radien für Crawl-Boxen + Dashboard-Schalter |

Das bestehende `district_slugs` bleibt als ungenutzte Spalte erhalten
(Rückwärtskompatibilität, keine Daten-Löschung).

**Konkrete Werte für „Marvila Slice 1" (geocodiert):**
`center_lat = 38.7391`, `center_lng = -9.1048`,
`center_label = "R. Cap. Leitão 86"`, `band_radii_km = [1, 2, 3, 5, 10]`.

## 4. Geo-Helfer (neues Modul `airbi/geo/distance.py`)

Reine, browser-/DB-freie Funktionen:

- `haversine_km(lat1, lng1, lat2, lng2) -> float`
  Großkreis-Distanz in km (Erdradius 6371.0088 km).
- `bbox_around(center_lat, center_lng, radius_km) -> tuple[sw_lat, sw_lng, ne_lat, ne_lng]`
  Bounding-Box (Quadrat) eines Kreises mit Radius `radius_km`:
  `dlat = radius_km / 110.574`,
  `dlng = radius_km / (111.320 * cos(radians(center_lat)))`.
  Rückgabe in derselben Reihenfolge wie das bisherige `bounding_box_for`.
- `concentric_boxes(center_lat, center_lng, radii_km) -> list[tuple[...]]`
  `[bbox_around(center_lat, center_lng, r) for r in radii_km]` — eine Box pro
  Radius (für den Crawl werden ALLE Boxen gesendet, nicht nur die äußerste).

`airbi/geo/districts.py` bleibt bestehen (von `test_geo.py` getestet), wird aber
aus dem aktiven Crawl-/Insight-Pfad entfernt. GeoJSON-Dateien bleiben liegen.

## 5. Crawl (`airbi/scraper/search_crawl.py`)

- **Entfernt:** `bounding_box_for(districts)` und alle `load_districts` /
  `assign_district`-Aufrufe aus `run_search_crawl` und `persist_results`.
- **`run_search_crawl`:**
  - liest `center_lat/center_lng/band_radii_km` aus der SearchConfig; fehlen
    `center_lat`/`center_lng`, bricht der Lauf mit `status="failed"` und einer
    klaren Message ab.
  - `boxes = concentric_boxes(center_lat, center_lng, band_radii_km)`.
  - Für **jede** Box: Such-URL bauen (`ne_lat/ne_lng/sw_lat/sw_lng&search_by_map
    =true&zoom=14`), Seite 1 + Cursor-Pagination (bestehende Logik), Ergebnisse
    in das gemeinsame `parsed_listings`-Dict (Dedup per `airbnb_id` über alle
    Boxen) einlesen. Block-/0-Treffer-Erkennung pro Box; eine leere Box bricht
    den Gesamtlauf nicht ab.
  - **Vorfilter** statt District: `is_entire_home(pl) and haversine_km(center,
    pl) <= max(band_radii_km)` (verwirft Overshoot aus den Box-Ecken).
  - Detail-Crawl + `merge_detail` wie bisher, nur auf den vorgefilterten
    Listings.
- **`persist_results`:** `districts`-Parameter entfällt. `listing.district_slug`
  wird auf `None` gesetzt (Spalte bleibt, Wert ungenutzt). Alles andere (Upsert,
  size_class, amenity_score, Snapshot) unverändert. `lat`/`lng` werden wie bisher
  gespeichert (Grundlage der Distanzrechnung).
- **Such-URL:** Stadt-Slug bleibt aus dem bestehenden Muster
  (`/s/Lisboa--Portugal/homes`).

## 6. Auswertung (`airbi/insights/segment_matrix.py`)

Der reine Aggregations-Builder bleibt im Kern gleich (Zellen, Score, ADR, heat,
best_cell, top_performers). Geändert wird die Gruppierungs-Achse von „Bezirk" zu
„Umkreis":

- **`SegmentMatrix`:** Feld `district_slug` → entfällt; neu `radius_km: float |
  None` und `center_label: str | None`.
- **`build_segment_matrix(rows, *, config, radius_km, center_label,
  crawl_run_id)`:** Signatur statt `district_slug`. Aggregation unverändert;
  `cohort` = Preise der übergebenen `rows` (sind bereits die Umkreis-Kohorte).
- **`_build_recommendation`:** formuliert auf den Umkreis:
  - Best-Cell vorhanden: „Im Umkreis von {radius_km} km um {center_label} ist
    {size}-{luxury} am attraktivsten — Ø {score} Reviews je Listing bei {n}
    Wettbewerber-Listings, Median-ADR €{adr}. …Proxy…".
  - keine Best-Cell: „Im Umkreis von {radius_km} km um {center_label} liefert
    dieser Crawl noch keine Zelle mit mindestens {min_sample} vergleichbaren
    Objekten — die Datenbasis ist zu dünn." (`center_label` None → „dem
    Zielobjekt").
- **`compute_segment_matrix(session, search_config, radius_km, crawl_run)`:**
  Signatur `radius_km` statt `district_slug`.
  - lädt **alle** Listing+Snapshot des Runs für `city_slug` (kein District-
    Filter mehr).
  - filtert in Python: behalte Zeile, wenn `center_lat/center_lng` gesetzt sind
    und `haversine_km(center, listing) <= radius_km`. Fehlt das Center, ist die
    Kohorte leer (Dashboard zeigt Leerzustand).
  - baut `ListingRow` (unverändert) und ruft den Builder mit `radius_km` +
    `center_label = search_config.center_label`.
- **`latest_completed_run`** unverändert.

`price_percentile`, `luxury_class`, `amenity_score` bleiben unverändert. Die
Luxusklasse nutzt weiterhin die Gewichte aus
`search_config.classification_config` (kein Bezirks-Lookup mehr nötig).

## 7. Dashboard (`airbi/web/routes.py` + Templates)

- **Routen `/` und `/matrix`:** Parameter `district: str` → `radius_km: float =
  2.0`. `_matrices_for(...)` wird zu einer Funktion, die **genau eine** Matrix
  für den gewählten Radius liefert (zurückgegeben als Liste mit einem Element,
  damit `_matrix_region.html` unverändert iterieren kann). Der „both/Vergleich"-
  Zweig entfällt.
- **`dashboard.html`:**
  - „Untersuchungsbereich"-Block zeigt `search_config.center_label` +
    „Umkreis-Auswertung" statt der Bezirksliste.
  - Die Bezirks-Filterleiste wird zur **Umkreis-Schalterleiste**: ein Button je
    Radius aus `search_config.band_radii_km` (Label „{r} km"), HTMX wie bisher
    (`hx-get="/matrix?config_id=…&radius_km={r}"`, `hx-target="#matrix-region"`).
    Aktiver Button = `radius_km == r`. Default-aktiv: 2 km.
- **`_matrix_region.html`:** Karten-Header „Marktübersicht · Umkreis
  {{ matrix.radius_km|int }} km" statt `matrix.district_slug.title()`. Leerzustand-
  Text „Im gewählten Umkreis liegen keine Apartments vor." Restliche Tabelle/
  Top-Apartments/Empfehlung unverändert.

## 8. Migration & Seed

- **Alembic-Revision** (nach `e15724acc87a`): vier Spalten zu `search_config`
  hinzufügen (`center_lat` Float null, `center_lng` Float null, `center_label`
  String(200) null, `band_radii_km` JSON, `server_default='[1, 2, 3, 5, 10]'`).
- **Seed/Update der bestehenden Config** (lokal + Prod, separater Schritt, keine
  Daten der anderen Apps berührt):
  `UPDATE search_config SET center_lat=38.7391, center_lng=-9.1048,
  center_label='R. Cap. Leitão 86', band_radii_km='[1,2,3,5,10]'
  WHERE name='Marvila Slice 1';`

## 9. Tests

- **Neu `tests/test_distance.py`:** `haversine_km` (bekannte Referenzdistanz,
  Symmetrie, Null bei identischem Punkt), `bbox_around` (Center liegt in der Box,
  Box ist ~2·r breit/hoch, Reihenfolge sw/ne korrekt), `concentric_boxes`
  (Anzahl = Anzahl Radien, äußerste Box umschließt die innerste).
- **`tests/test_search_crawl.py`:** `concentric_boxes`-Geometrie; `persist_results`
  ohne `districts`-Parameter (district_slug bleibt None, Listing/Snapshot werden
  geschrieben).
- **`tests/test_segment_matrix.py`:** Builder/Compute auf `radius_km` +
  `center_label` umstellen; neue Compute-Tests mit Listings auf
  unterschiedlichen Distanzen, die der Radius-Filter ein-/ausschließt.
- **`tests/test_web.py`:** Seeds setzen `center_lat/center_lng/center_label`;
  Umkreis-Schalter statt Bezirksfilter; Header „Umkreis … km".
- Bestehende Tests, die `district_slug` referenzieren, werden entsprechend
  angepasst.

## 10. Bewusst nicht im Scope (YAGNI)

- Mehrere Radien gleichzeitig nebeneinander vergleichen (der Schalter genügt).
- Persistierte Distanz/Band-Spalte (Query-Zeit-Berechnung reicht).
- Entfernen von `districts.py` / GeoJSON (bleibt, nur inaktiv).
- Mehrere Zielobjekte pro Config.
- Auto-Crawl/Scheduling (unverändert ausgeschlossen).
