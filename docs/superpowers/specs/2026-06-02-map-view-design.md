# Karten-View (Leaflet + OSM) — Design

> Status: freigegeben (2026-06-02, mit Live-Mockup im Companion bestätigt)
> Briefing-Bezug: §9 ("Charts via Plotly o. Ä.") — wir nutzen Leaflet für die
> räumliche Sicht; Plotly bleibt offen für andere Visualisierungen.

## 1. Ziel

Räumliche Sicht auf die Listings im Umkreis des Zielobjekts. Macht die
Verteilung der Konkurrenz unmittelbar greifbar, hebt Best-Cell-Mitglieder
visuell hervor und liefert über ein Klick-Detail-Panel die volle Listing-
Information ohne separaten Tab. Position: **Section A** — integriert
zwischen Investment-Brief und „Andere Chancen-Segmente".

## 2. Backend

### 2.1 `MapListing` (neu, in `airbi/insights/segment_matrix.py`)

```python
@dataclass
class MapListing:
    airbnb_id: str
    lat: float
    lng: float
    title: str | None
    url: str | None
    size_class: str
    luxury_class: str
    price: Decimal | None
    reviews: int
    rating: float | None
    bedrooms: int | None
    beds: int | None
    max_guests: int | None
    is_superhost: bool
    amenities: list[str]              # auf max. 10 gekappt
    description: str | None           # auf 300 Zeichen gekappt
    distance_km: float
    amenity_score: float | None
    is_best: bool
```

### 2.2 `SegmentMatrix.map_listings: list[MapListing]`

Neues Feld, leere Liste als Default. Wird in `compute_segment_matrix`
populiert.

### 2.3 Aggregation in `compute_segment_matrix`

Für die Karte werden ALLE Listings des Runs innerhalb der äußersten
Band-Radius (`max(band_radii_km)`) geladen — unabhängig vom aktiven Radius —
damit die Map immer den spatialen Kontext zeigt. Pro Listing:

- `luxury_class` wird gegen die **Aktiv-Radius-Kohorte** berechnet
  (konsistent zur Matrix und zum Hero).
- `is_best` = `(size_class, luxury_class) == matrix.best_cell` und
  `distance_km ≤ aktiver radius_km` (also nur Best-Cell-Mitglieder im
  aktiven Umkreis).
- `amenities` wird auf max. 10 Einträge gekappt, `description` auf 300
  Zeichen — Payload bleibt überschaubar.

## 3. Frontend

### 3.1 Section im Template

Neue Section in `_matrix_region.html`, eingeklemmt **zwischen Investment-Brief
und „Andere Chancen-Segmente"**.

```
Header "Marktkarte" + Untertitel
Legende (Luxury / Premium / Mid / Budget / Best-Cell / Zielobjekt)
[Map links (#airbi-map)] [Detail-Panel rechts (#map-detail)]
```

Layout: `grid-cols-1 sm:grid-cols-[1fr_340px]`, Karte 540px hoch, Panel
scroll-bar. Auf Mobile stapelt das Panel unter die Karte.

### 3.2 Leaflet + OSM

- Leaflet CSS + JS von `https://unpkg.com/leaflet@1.9.4/...` (CDN). HTMX und
  Tailwind kommen ebenfalls per CDN — kein neuer Build-Step.
- Tiles: `https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png`.
- Konzentrische Kreise (alle 5 Radien) als semi-transparente Layer um das
  Zentrum.
- Listings als `circleMarker`, Color-Coding nach Luxusklasse:
  Budget=`#94a3b8`, Mid=`#3b82f6`, Premium=`#22c55e`, Luxury=`#a855f7`.
- Best-Cell-Mitglieder: zusätzlich goldener Outline (`#f59e0b`, weight 2.5).
- Zielobjekt: roter divIcon-Marker mit weißem Rand, dauerhaft sichtbar.
- Tooltip beim Hover: Titel · Größe · Luxusklasse · Preis · Bewertungen.

### 3.3 Detail-Panel rechts

Beim Klick auf einen Marker füllt sich `#map-detail` mit:

- Titel + Chips (Größe·Luxus, Best-Cell, Superhost)
- 3-KPI-Strip: Preis · Bewertungen · Rating
- Räume-Zeile: Schlafzimmer · Betten · Gäste
- Distanz zum Zielobjekt
- Amenity-Score
- Top-10-Amenity-Chips
- Beschreibungs-Auszug (300 Zeichen)
- „Bei Airbnb öffnen"-Button (Direkt-Link)

### 3.4 Daten-Einbettung

`matrix.map_listings` wird als JSON inline in einen `<script>`-Tag
geschrieben (`window.AIRBI_MAP_DATA = …;`). Beim HTMX-Partial-Swap durch
Radius-Wechsel kommt die ganze Section frisch — Leaflet reinitialisiert
auf den neuen Daten. ~100 KB Payload pro Swap ist akzeptabel.

## 4. Tests

- `MapListing` lässt sich konstruieren; `SegmentMatrix.map_listings`
  populiert.
- `compute_segment_matrix` setzt `map_listings` mit allen 10-km-Listings;
  `is_best`-Flag korrekt nur für aktive-Radius-Best-Cell-Mitglieder.
- `_matrix_region.html` rendert das Map-Container-Div mit `id="airbi-map"`
  und das Detail-Panel; Leaflet-JS-Script-Tag ist drin.
- Snapshot-light: Window-Variable `AIRBI_MAP_DATA` enthält gültiges JSON
  mit `center`, `radii_km`, `listings`.

## 5. Bewusst NICHT im Scope

- Filter-UI (Größe/Luxusklasse als Toggles).
- Custom-Polygon-Zeichnen.
- Heatmap-Layer.
- Cluster-Ansicht (Leaflet.markercluster) — bei 632 Markern noch nicht nötig.
- Selbsthosten von Leaflet (CDN ist robust genug).
- Lazy-Loading des Map-JS.
