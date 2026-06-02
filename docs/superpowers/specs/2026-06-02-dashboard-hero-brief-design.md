# Dashboard UX-Refresh: Hero + Investment-Brief — Design

> Status: freigegeben (Brainstorming 2026-06-02 mit Visual Companion)
> Mockup-Referenz: `.superpowers/brainstorm/.../dashboard-a-plus-brief.html`

## 1. Ziel

Die Empfehlung wird Schlagzeile (XXL Hero-Card oben), nicht mehr Fußzeile. Die
Marktübersicht-Matrix rutscht in die Rolle des Evidenz-Blocks. Ein
**ausklappbarer Investment-Brief** liefert die volle Begründung, das
**Top-Performer-Profil** (gemeinsame Merkmale) und die Methodik on-demand —
ohne den Schnelleinstieg zu überladen.

## 2. Backend

### 2.1 `ListingRow` — zusätzliche Felder

Damit der Builder das Profil aggregieren kann, bekommt `ListingRow`:

- `amenities: list[str] = field(default_factory=list)`
- `bedrooms: int | None = None`
- `beds: int | None = None`
- `max_guests: int | None = None`
- `is_superhost: bool = False`

`compute_segment_matrix` füllt diese Felder aus dem `Listing`.

### 2.2 `TopPerformerProfile` (neu, im selben Modul)

```python
@dataclass
class TopPerformerProfile:
    count: int = 0
    superhost_share: float | None = None           # 0..1
    price_median: Decimal | None = None
    price_min: Decimal | None = None
    price_max: Decimal | None = None
    median_bedrooms: int | None = None
    median_beds: int | None = None
    median_max_guests: int | None = None
    common_amenities: list[tuple[str, float]] = field(default_factory=list)
    # (Name, Anteil 0..1), absteigend; max common_amenities_max Items mit
    # share >= amenity_share_threshold
```

### 2.3 Aggregation in `build_segment_matrix`

Nach `_pick_top_performers`: zurück-mappen über `airbnb_id` auf die rohen
`ListingRow`-Objekte und aus dieser Untermenge das Profil berechnen.

- `superhost_share` = `mean(is_superhost)` (None bei count=0).
- Median über alle nicht-None Werte je Feld (None bei leerer Liste).
- `common_amenities`: für jede Amenity der Anteil unter den Top-Performern;
  sortiert desc; gefiltert auf `share >= amenity_share_threshold`; gekappt auf
  `common_amenities_max`.
- Preis aus `ListingRow.price` (= Snapshot-Nacht-Preis).

### 2.4 Konfiguration

Erweitert `DEFAULT_INSIGHT_CONFIG`:

- `amenity_share_threshold: 0.5`
- `common_amenities_max: 6`

Beide über `classification_config` überschreibbar (analog zu `min_sample` etc.).

### 2.5 `SegmentMatrix`

Neues Feld:
- `top_performer_profile: TopPerformerProfile | None = None`

## 3. Frontend

### 3.1 `dashboard.html`

- **Onboarding-Box „So liest du dieses Dashboard" entfällt.** Methodik wandert
  in den Investment-Brief (§3.2 Paragraph 3).
- **Header schlank**: links Untersuchungsbereich-Label + `center_label`, rechts
  klein Datenstand + `listings_seen` (was heute im Footer steht).
- **Footer minimal** (nur Status-Hinweis, falls Run nicht completed).
- Umkreis-Switch + Click-Highlighter-Skript bleiben unverändert.
- Bindet `_matrix_region.html` wie bisher ein.

### 3.2 `_matrix_region.html` — Restrukturierung

Render-Reihenfolge **innerhalb** der eingebundenen Matrix-Region:

1. **Hero-Empfehlung** (dunkel, primär).
   - Best-Cell-Variante: XXL Schlagzeile aus `size_class · luxury_class`,
     darunter Untertitel „die attraktivste Kombination im Umkreis von
     {radius_km} km um {center_label}", darunter 3 KPI-Spalten:
     `cell.n` Wettbewerber · `€{cell.adr}` Median pro Nacht · `cell.score`
     Ø Bewertungen je Apt.
   - Thin-Daten-Variante (kein Best-Cell oder `listing_count == 0`): grauer
     Stil, Schlagzeile „Datenbasis zu dünn", Untertitel mit Hinweis auf
     größeren Umkreis. Keine KPIs.

2. **Investment-Brief** als `<details>`-Block direkt unter dem Hero.
   `<summary>`: kompakte Trigger-Zeile („📄 Investment-Brief — volle
   Begründung, Top-Performer-Profil und Methodik"). Inhalt:
   - Absatz 1 — Begründung mit Bezug zu `radius_km`, `listing_count`,
     `cell.n`, `cell.score`.
   - Absatz 2 — Top-Performer-Profil: Median Räume/Betten/Gäste,
     `common_amenities` als Inline-Tags mit Prozent, Superhost-Quote
     („X von Y"), Preis-Spanne. Wird übersprungen, wenn `top_performer_profile`
     leer ist.
   - Absatz 3 — Methodik (statisch im Template): Review-Proxy mit
     `review_rate` und Luxusklasse-Definition.
   Thin-Daten-Fall: Brief enthält nur den Methodik-Absatz.

3. **Marktübersicht** (bisherige Tabelle, visuell sekundär: kleinere Schrift,
   ruhigere Farben, schlankere Header-Zeile). Best-Cell bleibt goldumrandet.
   Heatmap-Klassen bleiben.

4. **Top-Apartments** als kompakte Listenform (eine Zeile je Apartment statt
   eines breiten Cards). Sortier-Erklärung als kleine `<p>` darüber.

5. **Alter „Empfehlung — am attraktivsten" / „noch nicht möglich"-Block am
   Ende entfällt.** Hero ersetzt ihn vollständig.

## 4. Tests

- Backend (`tests/test_segment_matrix.py`):
  - `ListingRow` mit neuen Feldern konstruierbar; Defaults sind sinnvoll.
  - `TopPerformerProfile`-Berechnung: Median, Superhost-Quote, common
    amenities mit Threshold/Cap.
  - `compute_segment_matrix` füllt neue ListingRow-Felder aus `Listing`.
  - `top_performer_profile` ist auf der Matrix gesetzt, wenn Top-Performer
    existieren; sonst leer/None.
- Frontend (`tests/test_web.py`):
  - Onboarding-Box-Text („So liest du dieses Dashboard") ist NICHT mehr im
    Body.
  - Hero rendert mit Best-Cell-Schlagzeile, KPIs sichtbar.
  - Thin-Daten-Variante rendert mit „Datenbasis zu dünn".
  - `<details>`-Trigger für den Investment-Brief vorhanden.
  - Profil-Aussagen im Brief: Median-Werte, mindestens eine `common_amenity`
    mit Prozent, Superhost-Quote.
  - Methodik-Absatz vorhanden.
  - Alter Empfehlungs-Block-Header („Empfehlung — am attraktivsten") nicht
    mehr im HTML.
  - Umkreis-Schalter + Click-Highlighter weiterhin da (Regression).

## 5. Bewusst NICHT im Scope

- Print-/PDF-Export, „Drucken"-Buttons im Brief.
- Karten/Heatmap-Visualisierung.
- „Top-Performer vs. Durchschnitt"-Vergleichsansicht.
- Brief als eigene Route/Endpunkt.
- Onboarding-Tour, neue Sprache-/Tonalitäts-Optionen.
