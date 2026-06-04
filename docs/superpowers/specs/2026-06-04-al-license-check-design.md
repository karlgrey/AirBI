# AL-Lizenz-Check (Phase 2 vorgezogen) — Design

> Status: freigegeben (2026-06-04 mit Visual-Companion-Mockup)
> Briefing-Bezug: §11 ("AL-Lizenz-Layer (Portugal): Investitionsentscheidend
> für Lissabon"). Schema-Felder `Listing.license_number` und
> `Listing.al_status` sind bereits reserviert.

## 1. Ziel

Vor jeder Akquise muss die Frage „Darf hier überhaupt eine **neue**
Kurzzeitvermietung legal entstehen?" beantwortet sein. Wenn das Zielobjekt
in einer Zona de Contenção absoluta liegt, ist die ganze Investment-These
„Airbnb hier aufbauen" rechtlich gesperrt — die Wirtschaftlichkeitsrechnung
müsste auf Mid-Term-Vermietung umgestellt werden.

## 2. UX

### 2.1 Variante A: Kompakte Status-Strip unter dem Hero

Eine farbig hinterlegte 2-Zeilen-Strip direkt zwischen Investment-Brief und
Marktübersicht. Eine Zeile Status-Headline, eine Zeile Belege.

| Status | Farbe | Headline | Belege |
|---|---|---|---|
| `ABSORCAO` | grün | „Neue AL möglich · Zona de Absorção" | „X % der N Konkurrenten zeigen eine sichtbare Lizenz" |
| `CONTENCAO` | gelb | „Neue AL eingeschränkt · Zona de Contenção" | „Quoten-/Kontingent-Beschränkung. AL-Quote der Konkurrenten: X %" |
| `CONTENCAO_ABSOLUTA` | rot | „Neue AL gesperrt · Zona de Contenção absoluta" | „Kurzzeitvermietung rechtlich nicht umsetzbar. Pivot zu Mid-Term oder Bestandslizenz nötig." |
| `NULL` (nicht geprüft) | grau-gelb | „AL-Status nicht geprüft" | „Bitte über SearchConfig manuell setzen oder GeoJSON-Daten einspielen." |

### 2.2 Hero-Dimmung bei Rot

Wenn `al_zone_status == "CONTENCAO_ABSOLUTA"`:
- Hero-Card bekommt `opacity-60 grayscale` → die Empfehlung wird optisch
  abgewertet, weil sie rechtlich nicht erreichbar ist.
- Brief-Block ebenfalls gedimmt.
- Eine Overlay-Notiz oben mittig: „Empfehlung rechtlich gesperrt — siehe
  AL-Status unten".

Bei Grün/Gelb/Unknown bleibt der Hero normal.

## 3. Datenmodell

### 3.1 `SearchConfig` Erweiterung (neue Spalten)

- `al_zone_status: str | None` — Enum: `ABSORCAO`, `CONTENCAO`,
  `CONTENCAO_ABSOLUTA`. `NULL` = nicht geprüft.
- `al_zone_label: str | None` — Anzeige-Text, z. B. "Zona de Absorção" oder
  "Zona de Contenção (Stufe 2)". Optional, fällt sonst auf Default zurück.

Beides ist primär manuelle Eintragung (per `airbi config set-al ...` CLI
oder Direkt-SQL), kann aber später auto-bestimmt werden (siehe §6).

### 3.2 `Listing.license_number` / `Listing.al_status`

Bereits im Schema. Werden via Regex aus `description` extrahiert:

Erkannte Muster (case-insensitive, dedupliziert):
- `RNAL\s*[:.-]?\s*(\d{3,7})/AL`
- `AL\s*n[º°.:]*\s*(\d{3,7})`
- `Alojamento\s+Local\s*[:.-]?\s*(\d{3,7})`
- `\b(\d{4,7})\s*/\s*AL\b` (generischer Fallback)

Wenn Match → `license_number = "<id>/AL"`, `al_status = "extracted"` (gesetzt,
aber nicht gegen das Register validiert).

### 3.3 `SegmentMatrix` Erweiterung

Neue Felder, gefüllt aus `SearchConfig` + Listing-Aggregat:

- `al_zone_status: str | None`
- `al_zone_label: str | None`
- `al_license_density: float | None` — Anteil 0..1 der Listings im aktiven
  Umkreis mit nicht-leerem `license_number`. `None` wenn keine Listings.
- `al_license_count: int` — absolute Anzahl

## 4. Backend-Logik

### 4.1 License-Extraktion
- Neuer Helper `airbi/scraper/parser.py::extract_al_license(text) -> str|None`
- Wird in `_extract_description` und/oder als Post-Step in
  `parse_listing_detail` aufgerufen → setzt `ListingDetail.license_number`.
- `persist_results` reicht das Feld auf `Listing.license_number` durch
  (und setzt `al_status = "extracted"` wenn Lizenz gefunden).
- **Backfill**: bestehende Listings über eine Migration oder ein One-Off-
  Script nachträglich verarbeiten.

### 4.2 AL-Density in `compute_segment_matrix`

Über die `map_pool`-Listings (alle innerhalb max-Radius) bzw. die
Aktiv-Radius-Listings (besser, weil mit der gezeigten Auswertung
konsistent):

```python
in_radius = [r for r in rows if r.distance_km <= radius_km]
licensed = sum(1 for r in in_radius if r.license_number)
matrix.al_license_count = licensed
matrix.al_license_density = licensed / len(in_radius) if in_radius else None
```

(Dazu muss `ListingRow.license_number` und ein `distance_km` mitgeführt
werden — oder die Aggregation auf der ursprünglichen Listing+Snapshot-Liste
gemacht werden, das ist sauberer.)

### 4.3 Zone-Status aus `SearchConfig`

`compute_segment_matrix` liest `search_config.al_zone_status` und
`search_config.al_zone_label` und stellt sie unverändert auf der Matrix
bereit.

## 5. Tests

- License-Extraktion: vier Patterns + Edge-Cases (kein Match, mehrere
  Matches → erstes nehmen, Fallback-Pattern).
- License-Persistierung: `persist_results` setzt `Listing.license_number`
  + `al_status` wenn ParsedListing eine Lizenz hat.
- `compute_segment_matrix` exponiert die richtigen al_*-Felder.
- Template rendert die richtige Strip-Farbe je Status; Hero-Dimm-Klassen
  greifen bei CONTENCAO_ABSOLUTA.

## 6. Bewusst NICHT im Scope (Phase 2.2)

- Automatische Zone-Bestimmung aus CML-GeoJSON (Polygon-Point-in-Polygon).
  Vorbereitete Code-Struktur erlaubt späteres Nachrüsten ohne Schema-
  Migration.
- Validierung gegen das öffentliche Turismo-de-Portugal-Register (per Lizenz
  Look-up). Markiert wäre `al_status = "verified"` / `"expired"` / `"revoked"`.
- Backend-/Frontend-Editing-UI für `al_zone_status` (CLI / Direkt-SQL reicht).
- Per-Listing-Detail-View „Lizenz ↗" mit Live-Lookup.
