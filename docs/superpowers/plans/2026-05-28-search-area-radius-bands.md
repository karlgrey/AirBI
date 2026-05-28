# Suchgebiet Umkreis-Bänder — Implementierungsplan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Suchgebiet von Bezirks-Polygonen auf distanzbasierte Umkreis-Bänder um das Zielobjekt umstellen — konzentrische Crawl-Rechtecke + im Dashboard umschaltbare Umkreis-Auswertung (1/2/3/5/10 km).

**Architecture:** Neues reines Geo-Modul (`haversine_km`, `bbox_around`, `concentric_boxes`). `SearchConfig` bekommt Center + Radien. Crawl sendet pro Radius eine Box, dedupt, filtert per Distanz. Insights gruppieren nach Umkreis statt Bezirk (Filter in Python zur Query-Zeit). Dashboard ersetzt Bezirksfilter durch Umkreis-Schalter.

**Tech Stack:** Python 3.11+, SQLAlchemy 2.0, Alembic, FastAPI + Jinja2 + HTMX, pytest. Stdlib `math` für Distanz (kein PostGIS, kein shapely-Neueinsatz).

**Spec:** `docs/superpowers/specs/2026-05-28-search-area-radius-bands-design.md`

## Dateien

- Neu: `airbi/geo/distance.py`, `tests/test_distance.py`
- Ändern: `airbi/db/models.py`, `airbi/scraper/search_crawl.py`, `airbi/insights/segment_matrix.py`, `airbi/web/routes.py`, `airbi/web/templates/dashboard.html`, `airbi/web/templates/_matrix_region.html`
- Neu: `alembic/versions/b2c3d4e5f6a7_search_config_umkreis.py`
- Ändern (Tests): `tests/test_models.py`, `tests/test_search_crawl.py`, `tests/test_segment_matrix.py`, `tests/test_web.py`

---

### Task 1: Geo-Distanz-Modul

**Files:**
- Create: `airbi/geo/distance.py`
- Test: `tests/test_distance.py`

- [ ] **Step 1: Failing test schreiben**

`tests/test_distance.py`:
```python
import math

from airbi.geo.distance import bbox_around, concentric_boxes, haversine_km


def test_haversine_zero_for_identical_point():
    assert haversine_km(38.7391, -9.1048, 38.7391, -9.1048) == 0.0


def test_haversine_symmetric():
    a = haversine_km(38.74, -9.10, 38.70, -9.20)
    b = haversine_km(38.70, -9.20, 38.74, -9.10)
    assert math.isclose(a, b)


def test_haversine_one_degree_lat_about_111km():
    d = haversine_km(38.0, -9.0, 39.0, -9.0)
    assert 110.0 < d < 112.0


def test_bbox_around_contains_center_and_is_about_2r_high():
    sw_lat, sw_lng, ne_lat, ne_lng = bbox_around(38.7391, -9.1048, 2.0)
    assert sw_lat < 38.7391 < ne_lat
    assert sw_lng < -9.1048 < ne_lng
    # halbe Höhe in km ~ Radius
    assert math.isclose((ne_lat - sw_lat) / 2 * 110.574, 2.0, rel_tol=0.05)


def test_concentric_boxes_one_per_radius_and_nested():
    boxes = concentric_boxes(38.7391, -9.1048, [1, 2, 5])
    assert len(boxes) == 3
    inner, _mid, outer = boxes
    assert outer[0] < inner[0] and outer[1] < inner[1]   # sw weiter außen
    assert outer[2] > inner[2] and outer[3] > inner[3]   # ne weiter außen
```

- [ ] **Step 2: Test fails verifizieren**

Run: `uv run pytest tests/test_distance.py -q`
Expected: FAIL (ModuleNotFoundError: airbi.geo.distance)

- [ ] **Step 3: Modul implementieren**

`airbi/geo/distance.py`:
```python
"""Distanz- und Bounding-Box-Helfer für die Umkreis-Suche.

Reine Funktionen ohne Browser/DB. Airbnb akzeptiert nur rechteckige
Karten-Viewports; ``concentric_boxes`` liefert pro Band-Radius eine
quadratische Box um das Zielobjekt.
"""

from __future__ import annotations

from math import asin, cos, radians, sin, sqrt

_EARTH_RADIUS_KM = 6371.0088
_KM_PER_DEG_LAT = 110.574
_KM_PER_DEG_LNG_EQ = 111.320


def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Großkreis-Distanz zwischen zwei Punkten in Kilometern."""
    phi1, phi2 = radians(lat1), radians(lat2)
    d_phi = radians(lat2 - lat1)
    d_lambda = radians(lng2 - lng1)
    a = sin(d_phi / 2) ** 2 + cos(phi1) * cos(phi2) * sin(d_lambda / 2) ** 2
    return 2 * _EARTH_RADIUS_KM * asin(sqrt(a))


def bbox_around(
    center_lat: float, center_lng: float, radius_km: float
) -> tuple[float, float, float, float]:
    """Quadratische Bounding-Box um einen Kreis mit ``radius_km``.

    Rückgabe (sw_lat, sw_lng, ne_lat, ne_lng) — dieselbe Reihenfolge, die die
    Airbnb-Such-URL erwartet.
    """
    d_lat = radius_km / _KM_PER_DEG_LAT
    d_lng = radius_km / (_KM_PER_DEG_LNG_EQ * cos(radians(center_lat)))
    return (
        center_lat - d_lat,
        center_lng - d_lng,
        center_lat + d_lat,
        center_lng + d_lng,
    )


def concentric_boxes(
    center_lat: float, center_lng: float, radii_km: list[float]
) -> list[tuple[float, float, float, float]]:
    """Eine Bounding-Box je Radius, alle um dasselbe Zentrum."""
    return [bbox_around(center_lat, center_lng, r) for r in radii_km]
```

- [ ] **Step 4: Tests grün**

Run: `uv run pytest tests/test_distance.py -q`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add airbi/geo/distance.py tests/test_distance.py
git commit -m "feat(geo): haversine + konzentrische Bounding-Boxen"
```

---

### Task 2: SearchConfig-Umkreis-Felder + Migration

**Files:**
- Modify: `airbi/db/models.py` (Klasse `SearchConfig`)
- Create: `alembic/versions/b2c3d4e5f6a7_search_config_umkreis.py`
- Test: `tests/test_models.py`

- [ ] **Step 1: Failing test ergänzen**

In `tests/test_models.py` ans Ende anfügen:
```python
def test_search_config_center_and_band_fields(db_session):
    cfg = SearchConfig(
        name="Umkreis Cfg",
        center_lat=38.7391, center_lng=-9.1048,
        center_label="R. Cap. Leitão 86",
    )
    db_session.add(cfg)
    db_session.flush()
    assert cfg.center_lat == 38.7391
    assert cfg.center_lng == -9.1048
    assert cfg.center_label == "R. Cap. Leitão 86"
    assert cfg.band_radii_km == [1, 2, 3, 5, 10]  # Default
```

- [ ] **Step 2: Test fails verifizieren**

Run: `uv run pytest tests/test_models.py::test_search_config_center_and_band_fields -q`
Expected: FAIL (TypeError: unexpected keyword argument 'center_lat')

- [ ] **Step 3: Modellfelder ergänzen**

In `airbi/db/models.py`, Klasse `SearchConfig`, direkt nach der Zeile
`district_slugs: Mapped[list] = mapped_column(JSON, default=list)` einfügen:
```python
    center_lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    center_lng: Mapped[float | None] = mapped_column(Float, nullable=True)
    center_label: Mapped[str | None] = mapped_column(String(200), nullable=True)
    band_radii_km: Mapped[list] = mapped_column(
        JSON, default=lambda: [1, 2, 3, 5, 10]
    )
```
(`Float`, `String`, `JSON` sind in `models.py` bereits importiert.)

- [ ] **Step 4: Test grün**

Run: `uv run pytest tests/test_models.py -q`
Expected: PASS (alle test_models)

- [ ] **Step 5: Alembic-Migration anlegen**

`alembic/versions/b2c3d4e5f6a7_search_config_umkreis.py`:
```python
"""search_config umkreis-felder

Revision ID: b2c3d4e5f6a7
Revises: e15724acc87a
Create Date: 2026-05-28
"""
from alembic import op
import sqlalchemy as sa

revision = "b2c3d4e5f6a7"
down_revision = "e15724acc87a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("search_config", sa.Column("center_lat", sa.Float(), nullable=True))
    op.add_column("search_config", sa.Column("center_lng", sa.Float(), nullable=True))
    op.add_column(
        "search_config",
        sa.Column("center_label", sa.String(length=200), nullable=True),
    )
    op.add_column(
        "search_config",
        sa.Column(
            "band_radii_km",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[1, 2, 3, 5, 10]'"),
        ),
    )


def downgrade() -> None:
    op.drop_column("search_config", "band_radii_km")
    op.drop_column("search_config", "center_label")
    op.drop_column("search_config", "center_lng")
    op.drop_column("search_config", "center_lat")
```

- [ ] **Step 6: Migration prüft sauber (offline)**

Run: `uv run python -c "import ast; ast.parse(open('alembic/versions/b2c3d4e5f6a7_search_config_umkreis.py').read()); print('ok')"`
Expected: `ok`
(Anwendung auf die echte DB erfolgt in Task 7.)

- [ ] **Step 7: Commit**

```bash
git add airbi/db/models.py alembic/versions/b2c3d4e5f6a7_search_config_umkreis.py tests/test_models.py
git commit -m "feat(db): SearchConfig center_lat/lng/label + band_radii_km"
```

---

### Task 3: persist_results ohne District-Zuordnung

**Files:**
- Modify: `airbi/scraper/search_crawl.py` (`persist_results` + Aufrufstelle in `run_search_crawl`)
- Test: `tests/test_search_crawl.py`

- [ ] **Step 1: Tests anpassen (failing)**

In `tests/test_search_crawl.py`:

(a) Die vier `persist_results`-Aufrufe verlieren das `districts`-Argument. Ersetze die Funktion `test_persist_results_creates_listing_snapshot_district_and_size_class` komplett durch:
```python
def test_persist_results_creates_listing_snapshot_and_size_class(db_session):
    cfg = SearchConfig(name="Marvila Crawl", district_slugs=["marvila", "beato"])
    run = CrawlRun(search_config=cfg, status="running")
    db_session.add(run)
    db_session.flush()

    pl = merge_detail(
        _parsed("A1", 38.7390, -9.1044),
        ListingDetail(bedrooms=1, beds=2, bathrooms=1.0, max_guests=2),
    )
    persist_results(db_session, run, [pl])

    listing = db_session.query(Listing).filter_by(airbnb_id="A1").one()
    assert listing.district_slug is None
    assert listing.size_class == "1BR"
    assert listing.bedrooms == 1
    snap = db_session.query(Snapshot).filter_by(listing_id=listing.id).one()
    assert snap.crawl_run_id == run.id
    assert snap.review_count == 10
```

(b) In `test_persist_results_upserts_listing_on_second_crawl`: entferne die Zeile
`districts = load_districts()` und ändere beide Aufrufe zu
`persist_results(db_session, run1, [_parsed(...)])` bzw. `run2` (ohne `districts`).

(c) Entferne `test_persist_results_marks_point_outside_polygons_unassigned` komplett (District-Logik gibt es nicht mehr).

(d) In `test_persist_results_writes_amenities_and_amenity_score`: entferne
`districts = load_districts()` und ändere den Aufruf zu
`persist_results(db_session, run, [pl])`.

- [ ] **Step 2: Test fails verifizieren**

Run: `uv run pytest tests/test_search_crawl.py -q`
Expected: FAIL (persist_results bekommt zu wenige Argumente bzw. district_slug is not None)

- [ ] **Step 3: persist_results umbauen**

In `airbi/scraper/search_crawl.py`:

(a) Signatur von `persist_results` ändern — `districts`-Parameter entfernen:
```python
def persist_results(
    session: "Session",
    crawl_run: "CrawlRun",
    parsed_listings: list[ParsedListing],
) -> int:
```
(b) Den Docstring-Satz zur District-Zuordnung entfernen und im Schleifenkörper
den District-Block ersetzen. Lösche:
```python
        # District-Zuweisung
        if pl.lat is not None and pl.lng is not None:
            district = assign_district(pl.lat, pl.lng, districts)
        else:
            district = "unassigned"

        # Größenklasse
        sc = _size_class(pl.bedrooms)
```
und ersetze durch:
```python
        # Größenklasse
        sc = _size_class(pl.bedrooms)
```
(c) Die Zuweisung `listing.district_slug = district` ersetzen durch:
```python
        listing.district_slug = None
```
(d) Die Aufrufstelle in `run_search_crawl` (am Ende, im try-Block) ändern von
`count = persist_results(session, run, final_listings, all_districts)` zu:
```python
        count = persist_results(session, run, final_listings)
```
(Der Rest von `run_search_crawl` — `all_districts`, bbox, Vorfilter — bleibt in
diesem Task unverändert und wird in Task 5 ersetzt.)

- [ ] **Step 4: Tests grün**

Run: `uv run pytest tests/test_search_crawl.py -q`
Expected: PASS (alle verbliebenen test_search_crawl)

- [ ] **Step 5: Commit**

```bash
git add airbi/scraper/search_crawl.py tests/test_search_crawl.py
git commit -m "refactor(crawl): persist_results ohne District-Zuordnung"
```

---

### Task 4: Insights auf Umkreis-Kohorte umstellen

**Files:**
- Modify: `airbi/insights/segment_matrix.py`
- Test: `tests/test_segment_matrix.py`

- [ ] **Step 1: Tests anpassen (failing)**

In `tests/test_segment_matrix.py`:

(a) `test_segment_matrix_cell_lookup_returns_stored_cell`: ersetze
`SegmentMatrix(district_slug="marvila", crawl_run_id=1)` durch
`SegmentMatrix(radius_km=2.0, crawl_run_id=1)`.

(b) In allen `build_segment_matrix(...)`-Aufrufen `district_slug=<x>` ersetzen
durch `radius_km=2.0, center_label="R. Cap. Leitão 86"`. Konkret betrifft das
die Aufrufe in: `test_builder_returns_full_4x4_grid_with_district_and_run_id`
(zusätzlich Assertions `matrix.district_slug == "marvila"` → `matrix.radius_km
== 2.0`), `test_builder_counts_listings_per_cell_and_sums_reviews`,
`test_builder_median_adr_per_cell`, `test_builder_marks_cells_below_min_sample_as_thin`,
`test_builder_skips_rows_with_unclassified_size_or_no_price`,
`test_builder_picks_best_cell_with_highest_score_above_min_sample`,
`test_builder_returns_no_best_cell_when_all_cells_thin`,
`test_builder_heat_is_zero_for_empty_or_thin_cells`,
`test_builder_heat_scales_1_to_4_for_eligible_cells`,
`test_top_performers_grouped_by_size_class_sorted_by_review_count`,
`test_top_performers_ignore_unclassified_size_class`,
`test_builder_amenity_score_shifts_listing_into_higher_luxury_class`.

(c) `test_recommendation_names_district_size_tier_score_n_adr_and_proxy_note`
komplett ersetzen durch:
```python
def test_recommendation_names_umkreis_size_tier_score_n_adr_and_proxy_note():
    rows = [_row(f"l{i}", "1BR", 100, review_count=80) for i in range(3)]
    matrix = build_segment_matrix(
        rows, config={"min_sample": 3},
        radius_km=2.0, center_label="R. Cap. Leitão 86", crawl_run_id=1,
    )
    rec = matrix.recommendation
    assert "Umkreis" in rec
    assert "2 km" in rec
    assert "R. Cap. Leitão 86" in rec
    assert "1BR" in rec
    assert "Budget" in rec
    assert "80" in rec
    assert "3 Wettbewerber" in rec
    assert "€100" in rec
    assert "Proxy" in rec
    assert "40%" in rec
```

(d) `test_recommendation_falls_back_when_no_cell_meets_min_sample` ersetzen durch:
```python
def test_recommendation_falls_back_when_no_cell_meets_min_sample():
    rows = [_row("1", "1BR", 100, 5)]
    matrix = build_segment_matrix(
        rows, config={"min_sample": 3},
        radius_km=5.0, center_label="R. Cap. Leitão 86", crawl_run_id=1,
    )
    assert matrix.best_cell is None
    assert "Umkreis" in matrix.recommendation
    assert "5 km" in matrix.recommendation
    assert "zu dünn" in matrix.recommendation
```

(e) `_seed`-Helper um Koordinaten erweitern. Ersetze die Funktion durch:
```python
def _seed(db_session, *, size_class, price, reviews, airbnb_id, run,
          lat=38.7391, lng=-9.1048):
    listing = Listing(
        airbnb_id=airbnb_id, city_slug="lisboa", district_slug=None,
        lat=lat, lng=lng, property_type="Apartment",
        bedrooms=1, size_class=size_class, title=f"L{airbnb_id}",
        url=f"https://x/{airbnb_id}",
    )
    db_session.add(listing)
    db_session.flush()
    db_session.add(Snapshot(
        listing_id=listing.id, crawl_run_id=run.id,
        price=Decimal(str(price)), review_count=reviews, rating=4.7,
    ))
```

(f) `_seed_run` um Center erweitern:
```python
def _seed_run(db_session, *, status="completed"):
    cfg = SearchConfig(
        name=f"Cfg-{status}-{id(db_session)}",
        center_lat=38.7391, center_lng=-9.1048, center_label="R. Cap. Leitão 86",
    )
    run = CrawlRun(search_config=cfg, status=status)
    db_session.add(run)
    db_session.flush()
    return cfg, run
```

(g) `test_latest_completed_run_returns_none_when_no_completed_run`: ersetze
`SearchConfig(name="None", district_slugs=["marvila"])` durch
`SearchConfig(name="None", center_lat=38.7391, center_lng=-9.1048)`.

(h) `test_compute_segment_matrix_pulls_only_rows_for_district_and_run` komplett
ersetzen durch einen Umkreis-Test (Distanz-Filter schließt ferne Listings aus):
```python
def test_compute_segment_matrix_filters_by_radius_and_run(db_session):
    cfg, run = _seed_run(db_session)
    # 3 Listings nah am Zentrum (<1 km).
    for i, (p, rev) in enumerate([(80, 10), (90, 12), (100, 8)]):
        _seed(db_session, size_class="1BR", price=p, reviews=rev,
              airbnb_id=f"NEAR{i}", run=run, lat=38.7395, lng=-9.1050)
    # 1 Listing weit weg (~10 km südlich) -> bei radius 2 km ausgeschlossen.
    _seed(db_session, size_class="1BR", price=200, reviews=999,
          airbnb_id="FAR", run=run, lat=38.65, lng=-9.10)
    # Anderer Run -> nicht in diesem Ergebnis.
    other_run = CrawlRun(search_config=cfg, status="completed")
    db_session.add(other_run)
    db_session.flush()
    _seed(db_session, size_class="1BR", price=120, reviews=5,
          airbnb_id="OTHER", run=other_run)

    matrix = compute_segment_matrix(db_session, cfg, 2.0, run)
    assert matrix.listing_count == 3        # nur die nahen, nicht FAR/OTHER
    assert matrix.crawl_run_id == run.id
    assert matrix.radius_km == 2.0
```

(i) `test_compute_segment_matrix_respects_search_config_classification_config`:
`compute_segment_matrix(db_session, cfg, "marvila", run)` → `compute_segment_matrix(db_session, cfg, 2.0, run)` und die `_seed`-Aufrufe ohne `district=`-Argument.

- [ ] **Step 2: Test fails verifizieren**

Run: `uv run pytest tests/test_segment_matrix.py -q`
Expected: FAIL (TypeError district_slug / unexpected radius_km)

- [ ] **Step 3: segment_matrix.py umbauen**

(a) Import ergänzen (oben):
```python
from airbi.geo.distance import haversine_km
```
(b) `SegmentMatrix`: Feld `district_slug: str` entfernen, ersetzen durch:
```python
    radius_km: float | None
    center_label: str | None = None
```
Wichtig: `radius_km` ist ein Pflichtfeld ohne Default — es muss in der
`@dataclass` VOR den Feldern mit Default stehen. Setze die Feld-Reihenfolge auf:
```python
@dataclass
class SegmentMatrix:
    """Vollständiges Insight-Ergebnis für genau einen Umkreis + einen CrawlRun."""

    radius_km: float | None
    crawl_run_id: int | None
    center_label: str | None = None
    size_classes: list[str] = field(default_factory=lambda: list(SIZE_CLASSES))
    luxury_classes: list[str] = field(default_factory=lambda: list(LUXURY_CLASSES))
    cells: dict[tuple[str, str], Cell] = field(default_factory=dict)
    best_cell: tuple[str, str] | None = None
    recommendation: str = ""
    top_performers: list[TopPerformer] = field(default_factory=list)
    listing_count: int = 0
    review_rate: float = DEFAULT_INSIGHT_CONFIG["review_rate"]
    min_sample: int = DEFAULT_INSIGHT_CONFIG["min_sample"]

    def cell(self, size_class: str, luxury_class: str) -> Cell:
        """Template-freundlicher Zugriff (Jinja kann keine Tuple-Subscripts)."""
        return self.cells[(size_class, luxury_class)]
```
(c) `_district_label` entfernen.
(d) `_build_recommendation` ersetzen durch:
```python
def _build_recommendation(matrix: SegmentMatrix) -> str:
    """Formuliert den Empfehlungssatz aus der gefüllten Matrix."""
    label = matrix.center_label or "dem Zielobjekt"
    radius = f"{matrix.radius_km:g}"
    if matrix.best_cell is None:
        return (
            f"Im Umkreis von {radius} km um {label} liefert dieser Crawl noch "
            f"keine Zelle mit mindestens {matrix.min_sample} vergleichbaren "
            f"Objekten — die Datenbasis ist für eine belastbare Empfehlung zu "
            f"dünn."
        )
    size, luxury = matrix.best_cell
    cell = matrix.cell(size, luxury)
    score = cell.score or 0.0
    adr = int(cell.adr) if cell.adr is not None else 0
    rate_pct = int(round(matrix.review_rate * 100))
    return (
        f"Im Umkreis von {radius} km um {label} ist {size}-{luxury} am "
        f"attraktivsten — Ø {score:.0f} Reviews je Listing bei {cell.n} "
        f"Wettbewerber-Listings, Median-ADR €{adr}. Nachfrage ist ein Proxy "
        f"aus Review-Count (~{rate_pct}% der Gäste bewerten), keine gemessene "
        f"Auslastung."
    )
```
(e) `build_segment_matrix`-Signatur und Konstruktion ändern. Signatur:
```python
def build_segment_matrix(
    rows: list[ListingRow],
    *,
    config: dict | None,
    radius_km: float | None,
    center_label: str | None,
    crawl_run_id: int | None,
) -> SegmentMatrix:
```
Im Docstring "für genau einen Bezirk" → "für genau einen Umkreis", und den
Hinweis "(Bezirks-Kohort)" → "(Umkreis-Kohorte)". Die `SegmentMatrix(...)`-
Konstruktion am Ende ändern:
```python
    matrix = SegmentMatrix(
        radius_km=radius_km,
        center_label=center_label,
        crawl_run_id=crawl_run_id,
        cells=cells,
        best_cell=best_cell,
        listing_count=listing_count,
        review_rate=float(cfg["review_rate"]),
        min_sample=min_sample,
    )
```
(f) `compute_segment_matrix` ersetzen durch:
```python
def compute_segment_matrix(
    session: Session,
    search_config: SearchConfig,
    radius_km: float,
    crawl_run: CrawlRun,
) -> SegmentMatrix:
    """Lädt alle Listings+Snapshots des Runs und filtert per Distanz zum
    Zielobjekt auf den gewählten Umkreis, dann ruft den reinen Builder."""
    session.flush()
    stmt = (
        select(Listing, Snapshot)
        .join(Snapshot, Snapshot.listing_id == Listing.id)
        .where(Snapshot.crawl_run_id == crawl_run.id)
        .where(Listing.city_slug == search_config.city_slug)
    )
    center_lat = search_config.center_lat
    center_lng = search_config.center_lng
    rows: list[ListingRow] = []
    if center_lat is not None and center_lng is not None:
        for listing, snap in session.execute(stmt).all():
            if listing.lat is None or listing.lng is None:
                continue
            if haversine_km(center_lat, center_lng, listing.lat, listing.lng) > radius_km:
                continue
            rows.append(
                ListingRow(
                    airbnb_id=listing.airbnb_id,
                    title=listing.title,
                    url=listing.url,
                    size_class=listing.size_class or "unclassified",
                    price=snap.price,
                    review_count=snap.review_count or 0,
                    rating=snap.rating,
                    amenity_score=listing.amenity_score or 0.0,
                )
            )
    return build_segment_matrix(
        rows,
        config=search_config.classification_config or {},
        radius_km=radius_km,
        center_label=search_config.center_label,
        crawl_run_id=crawl_run.id,
    )
```
(g) Den Docstring von `ListingRow` ("bereits einem Bezirk zugeordnet") auf
"aus einem CrawlRun" kürzen — rein kosmetisch, optional.

- [ ] **Step 4: Tests grün**

Run: `uv run pytest tests/test_segment_matrix.py -q`
Expected: PASS (alle test_segment_matrix)

- [ ] **Step 5: Commit**

```bash
git add airbi/insights/segment_matrix.py tests/test_segment_matrix.py
git commit -m "feat(insights): Segment-Matrix nach Umkreis statt Bezirk"
```

---

### Task 5: run_search_crawl auf konzentrische Boxen

**Files:**
- Modify: `airbi/scraper/search_crawl.py` (`run_search_crawl`, Importe, `bounding_box_for` entfernen)
- Test: `tests/test_search_crawl.py`

- [ ] **Step 1: Test anpassen (failing)**

In `tests/test_search_crawl.py`:
(a) Importe oben ändern — `bounding_box_for` und `load_districts` entfernen,
`concentric_boxes` ergänzen:
```python
from airbi.geo.distance import concentric_boxes
from airbi.scraper.models import ListingDetail, ParsedListing
from airbi.scraper.search_crawl import (
    is_entire_home,
    merge_detail,
    persist_results,
)
```
(b) `test_bounding_box_covers_all_district_polygons` komplett entfernen und durch
einen Concentric-Box-Test ersetzen:
```python
def test_concentric_boxes_center_inside_each_box():
    boxes = concentric_boxes(38.7391, -9.1048, [1, 2, 3, 5, 10])
    assert len(boxes) == 5
    for sw_lat, sw_lng, ne_lat, ne_lng in boxes:
        assert sw_lat < 38.7391 < ne_lat
        assert sw_lng < -9.1048 < ne_lng
```

- [ ] **Step 2: Test fails verifizieren**

Run: `uv run pytest tests/test_search_crawl.py -q`
Expected: FAIL (ImportError: cannot import name 'bounding_box_for')

- [ ] **Step 3: search_crawl.py umbauen**

(a) Importblock oben ändern — die District-Importe entfernen, Distanz-Importe
ergänzen:
```python
from airbi.classification.amenity import amenity_score as _amenity_score
from airbi.classification.size import size_class as _size_class
from airbi.geo.distance import concentric_boxes, haversine_km
from airbi.scraper.models import ListingDetail, ParsedListing
```
(Den `TYPE_CHECKING`-Import von `BaseGeometry` ebenfalls entfernen.)

(b) Die gesamte Funktion `bounding_box_for` (inkl. Kommentar-Header `# (a)`)
löschen.

(c) In `run_search_crawl`, im `try`-Block, den District-/BBox-Aufbau ersetzen.
Lösche von `all_districts = load_districts()` bis zur schließenden
`base_search_url = (...)`-Zuweisung (also den District-Filter, `bounding_box_for`
und die Single-URL) und ersetze durch:
```python
        center_lat = search_config.center_lat
        center_lng = search_config.center_lng
        radii = search_config.band_radii_km or [1, 2, 3, 5, 10]
        if center_lat is None or center_lng is None:
            run.status = "failed"
            run.message = "SearchConfig ohne center_lat/center_lng — Umkreis-Crawl nicht möglich."
            run.finished_at = datetime.now(timezone.utc)
            session.commit()
            return run
        max_radius = max(radii)
        boxes = concentric_boxes(center_lat, center_lng, radii)

        def _search_url(box: tuple[float, float, float, float]) -> str:
            sw_lat, sw_lng, ne_lat, ne_lng = box
            return (
                "https://www.airbnb.com/s/Lisboa--Portugal/homes"
                f"?ne_lat={ne_lat}&ne_lng={ne_lng}&sw_lat={sw_lat}&sw_lng={sw_lng}"
                "&search_by_map=true&zoom=14"
            )
```

(d) Den Browser-Block so umbauen, dass er ÜBER ALLE BOXEN iteriert. Ersetze den
gesamten Abschnitt ab `with browser_context(headless=headless) as ctx:` bis
einschließlich der Cursor-Paginierungs-Schleife (also bis vor `# --- Entire-Home-
Filter ...`) durch:
```python
        with browser_context(headless=headless) as ctx:
            page = ctx.new_page()

            for box_idx, box in enumerate(boxes, start=1):
                base_search_url = _search_url(box)

                first_results, page_cursors = _fetch_search_page(
                    page, base_search_url, 1
                )

                if not first_results and not page_cursors:
                    html_check = page.content().lower()
                    if "hcaptcha" in html_check or "access denied" in html_check:
                        logger.warning("Box %d: Block/CAPTCHA — übersprungen.", box_idx)
                        continue

                if not first_results:
                    logger.info("Box %d: keine Ergebnisse — übersprungen.", box_idx)
                    continue

                for pl in parse_search_results(
                    {"data": {"presentation": {"staysSearch": {"results": {"searchResults": first_results}}}}}
                ):
                    parsed_listings[pl.airbnb_id] = pl

                logger.info(
                    "Box %d (von %d): Seite 1 = %d Ergebnisse, %d Cursor",
                    box_idx, len(boxes), len(first_results), len(page_cursors),
                )

                for page_idx, cursor in enumerate(page_cursors[1:_MAX_PAGES], start=2):
                    human_delay(*DEFAULT_PAGE_DELAY)
                    encoded_cursor = urllib.parse.quote(cursor)
                    page_url = base_search_url + f"&cursor={encoded_cursor}"

                    page_results, _ = _fetch_search_page(page, page_url, page_idx)
                    if not page_results:
                        continue
                    for pl in parse_search_results(
                        {"data": {"presentation": {"staysSearch": {"results": {"searchResults": page_results}}}}}
                    ):
                        parsed_listings[pl.airbnb_id] = pl

                human_delay(*DEFAULT_PAGE_DELAY)

            # Gesamtschutz: keine einzige Box lieferte Ergebnisse.
            if not parsed_listings:
                run.status = "failed"
                run.message = "Keine Suchergebnisse über alle Boxen (0 Listings)."
                run.finished_at = datetime.now(timezone.utc)
                session.commit()
                return run
```

(e) Den Vorfilter (District → Distanz) ersetzen. Lösche:
```python
            # --- Entire-Home-Filter + District-Vorfilter ---
            filtered = [
                pl for pl in parsed_listings.values()
                if is_entire_home(pl)
                and assign_district(pl.lat, pl.lng, relevant) != "unassigned"
            ]
            logger.info(
                "Suchergebnisse: %d total (alle Seiten), %d nach Entire-Home- + District-Filter",
                len(parsed_listings),
                len(filtered),
            )
```
und ersetze durch:
```python
            # --- Entire-Home-Filter + Distanz-Vorfilter (max. Radius) ---
            def _in_radius(pl: ParsedListing) -> bool:
                if pl.lat is None or pl.lng is None:
                    return False
                return haversine_km(center_lat, center_lng, pl.lat, pl.lng) <= max_radius

            filtered = [
                pl for pl in parsed_listings.values()
                if is_entire_home(pl) and _in_radius(pl)
            ]
            logger.info(
                "Suchergebnisse: %d total (alle Boxen), %d nach Entire-Home- + Distanz-Filter",
                len(parsed_listings),
                len(filtered),
            )
```

(f) Sicherstellen, dass `parsed_listings: dict[str, ParsedListing] = {}` weiterhin
VOR dem `with browser_context(...)`-Block initialisiert wird (war es schon).

- [ ] **Step 4: Tests grün + Importprüfung**

Run: `uv run pytest tests/test_search_crawl.py -q`
Expected: PASS
Run: `uv run python -c "import airbi.scraper.search_crawl; print('import ok')"`
Expected: `import ok`

- [ ] **Step 5: Commit**

```bash
git add airbi/scraper/search_crawl.py tests/test_search_crawl.py
git commit -m "feat(crawl): konzentrische Boxen + Distanz-Vorfilter statt Bezirk"
```

---

### Task 6: Dashboard — Umkreis-Schalter (Routen + Templates)

**Files:**
- Modify: `airbi/web/routes.py`, `airbi/web/templates/dashboard.html`, `airbi/web/templates/_matrix_region.html`
- Test: `tests/test_web.py`

- [ ] **Step 1: Tests anpassen (failing)**

In `tests/test_web.py`:

(a) `_seed_marvila` umbauen — Center setzen, `district`-Argument raus,
Koordinaten nah am Zentrum:
```python
def _seed_marvila(session):
    cfg = SearchConfig(
        name="Marvila Slice 1",
        center_lat=38.7391, center_lng=-9.1048, center_label="R. Cap. Leitão 86",
    )
    run = CrawlRun(search_config=cfg, status="completed", listings_seen=6)
    session.add(run)
    session.flush()

    def add_listing(airbnb_id, size_class, price, reviews, title):
        listing = Listing(
            airbnb_id=airbnb_id, city_slug="lisboa", district_slug=None,
            lat=38.7395, lng=-9.1050, property_type="Apartment", bedrooms=1,
            size_class=size_class, title=title, url=f"https://x/{airbnb_id}",
        )
        session.add(listing)
        session.flush()
        session.add(Snapshot(
            listing_id=listing.id, crawl_run_id=run.id,
            price=Decimal(str(price)), review_count=reviews, rating=4.7,
        ))

    add_listing("M1", "1BR", 60, 5,  "Marvila Cosy 1BR")
    add_listing("M2", "1BR", 70, 8,  "Marvila Cosy 1BR Nr 2")
    add_listing("M3", "1BR", 250, 90, "Marvila Loft Luxe")
    add_listing("M4", "1BR", 260, 80, "Marvila Loft Riverside")
    add_listing("B1", "1BR", 80, 12, "Beato Studio")
    add_listing("B2", "2BR", 130, 20, "Beato Family Flat")
    session.flush()
    return cfg
```

(b) Ersetze `test_dashboard_renders_matrix_and_panel`:
```python
def test_dashboard_renders_matrix_and_panel(client, db_session):
    cfg = _seed_marvila(db_session)
    response = client.get("/")
    assert response.status_code == 200
    body = response.text
    assert cfg.name in body
    assert "R. Cap. Leitão 86" in body
    assert "Marktübersicht" in body
    assert "vollständig erfasst" in body
    assert "Marvila Loft" in body
    assert "geschätzte Nachfrage" in body
```

(c) Ersetze `test_matrix_partial_returns_single_district` und
`test_matrix_partial_returns_two_matrices_for_both` durch:
```python
def test_matrix_partial_returns_umkreis_matrix(client, db_session):
    cfg = _seed_marvila(db_session)
    response = client.get(f"/matrix?config_id={cfg.id}&radius_km=2")
    assert response.status_code == 200
    body = response.text
    assert "Umkreis" in body and "2 km" in body
    assert "<html" not in body.lower()


def test_matrix_partial_radius_filters_cohort(client, db_session):
    cfg = _seed_marvila(db_session)
    # 1 km Umkreis enthält die nahen Listings (alle bei 38.7395/-9.1050).
    response = client.get(f"/matrix?config_id={cfg.id}&radius_km=1")
    assert response.status_code == 200
    assert "Umkreis" in response.text
```

(d) Ersetze `test_dashboard_filter_buttons_use_htmx`:
```python
def test_dashboard_radius_buttons_use_htmx(client, db_session):
    cfg = _seed_marvila(db_session)
    response = client.get(f"/?config_id={cfg.id}")
    body = response.text
    assert "hx-get=\"/matrix?config_id=" in body
    assert "radius_km=" in body
    assert "hx-target=\"#matrix-region\"" in body
```

(e) Ersetze `test_dashboard_uses_untersuchungsbereich_label`:
```python
def test_dashboard_uses_untersuchungsbereich_label(client, db_session):
    _seed_marvila(db_session)
    response = client.get("/")
    body = response.text
    assert "Untersuchungsbereich" in body
    assert "Lissabon" in body
    assert "R. Cap. Leitão 86" in body
```

(f) Ersetze `test_dashboard_filter_has_vergleich_button` durch einen Umkreis-
Buttons-Test:
```python
def test_dashboard_has_radius_buttons(client, db_session):
    cfg = _seed_marvila(db_session)
    response = client.get(f"/?config_id={cfg.id}")
    body = response.text
    assert "1 km" in body and "2 km" in body and "10 km" in body
```

(g) `test_matrix_uses_klartext_size_labels`: die Assertion `assert "Luxusklasse"
in body` bleibt gültig (steht in der Tabellen-Kopfzeile). Keine Änderung nötig,
sofern der Test sonst nur Größen-Labels prüft — er bleibt unverändert.

(h) `test_matrix_axis_is_luxusklasse` bleibt unverändert (prüft "Luxusklasse" +
"Preis und Ausstattung").

- [ ] **Step 2: Test fails verifizieren**

Run: `uv run pytest tests/test_web.py -q`
Expected: FAIL (Routen kennen `radius_km` noch nicht / Templates zeigen Bezirke)

- [ ] **Step 3: routes.py umbauen**

(a) `_matrices_for` ersetzen durch eine Single-Umkreis-Funktion:
```python
def _matrices_for(
    session: Session,
    search_config: SearchConfig,
    radius_km: float,
    crawl_run: CrawlRun,
) -> list[SegmentMatrix]:
    """Genau eine Matrix für den gewählten Umkreis (als Liste, damit das
    Region-Template unverändert iterieren kann)."""
    return [compute_segment_matrix(session, search_config, radius_km, crawl_run)]
```
(b) `dashboard`-Route: Parameter `district: str = "marvila"` → `radius_km: float
= 2.0`; im Body `district`/`active_district` durch `radius_km`/`active_radius`
ersetzen. Neue Fassung:
```python
@router.get("/", response_class=HTMLResponse)
def dashboard(
    request: Request,
    config_id: int | None = None,
    radius_km: float = 2.0,
    session: Session = Depends(get_session),
):
    search_config = _resolve_search_config(session, config_id)
    if search_config is None:
        return templates.TemplateResponse(
            request, "dashboard.html",
            {"search_config": None, "latest_run": None,
             "matrices": [], "active_radius": radius_km,
             "completed_run": None},
        )
    latest_run = _latest_any_run(session, search_config)
    completed_run = latest_completed_run(session, search_config)
    matrices = (
        _matrices_for(session, search_config, radius_km, completed_run)
        if completed_run is not None else []
    )
    latest_run_date_de = _format_date_de(latest_run.started_at) if latest_run else None
    city_label = "Lissabon" if search_config.city_slug == "lisboa" else search_config.city_slug
    return templates.TemplateResponse(
        request, "dashboard.html",
        {
            "search_config": search_config,
            "latest_run": latest_run,
            "completed_run": completed_run,
            "matrices": matrices,
            "active_radius": radius_km,
            "latest_run_date_de": latest_run_date_de,
            "city_label": city_label,
        },
    )
```
(c) `matrix_partial`-Route analog:
```python
@router.get("/matrix", response_class=HTMLResponse)
def matrix_partial(
    request: Request,
    config_id: int | None = None,
    radius_km: float = 2.0,
    session: Session = Depends(get_session),
):
    """HTMX-Partial: nur die Matrix-Region für den gewählten Umkreis."""
    search_config = _resolve_search_config(session, config_id)
    if search_config is None:
        return templates.TemplateResponse(
            request, "_matrix_region.html",
            {"matrices": [], "completed_run": None},
        )
    completed_run = latest_completed_run(session, search_config)
    matrices = (
        _matrices_for(session, search_config, radius_km, completed_run)
        if completed_run is not None else []
    )
    return templates.TemplateResponse(
        request, "_matrix_region.html",
        {"matrices": matrices, "completed_run": completed_run},
    )
```

- [ ] **Step 4: dashboard.html umbauen**

(a) Den „Untersuchungsbereich"-Block (die `<p class="text-sm text-slate-500">`
mit `district_slugs|map(...)`) ersetzen durch:
```html
      <p class="text-sm text-slate-500">
        {{ city_label }} — Umkreis-Auswertung um
        <span class="font-medium text-slate-700">{{ search_config.center_label or "das Zielobjekt" }}</span>
      </p>
```
(b) Die gesamte `<nav ... aria-label="Bezirksfilter">…</nav>` ersetzen durch eine
Umkreis-Schalterleiste:
```html
    <nav class="mb-6 flex gap-2" aria-label="Umkreis">
      {% for r in search_config.band_radii_km %}
        <button type="button"
                hx-get="/matrix?config_id={{ search_config.id }}&radius_km={{ r }}"
                hx-target="#matrix-region"
                hx-swap="innerHTML"
                class="rounded-md border px-3 py-1.5 text-sm
                       {% if active_radius == r %}
                         border-slate-900 bg-slate-900 text-white
                       {% else %}
                         border-slate-300 bg-white text-slate-700 hover:bg-slate-100
                       {% endif %}">
          {{ r }} km
        </button>
      {% endfor %}
    </nav>
```

- [ ] **Step 5: _matrix_region.html umbauen**

(a) Die Leerzustands-Meldung (zweiter `{% elif not matrices %}`-Block) Text
ersetzen durch:
```html
    Im gewählten Umkreis liegen im aktuellen Datenstand keine Apartments vor.
```
(b) Den Karten-Header ändern:
```html
          <h2 class="text-lg font-semibold">
            Marktübersicht · Umkreis {{ matrix.radius_km|int }} km
          </h2>
```

- [ ] **Step 6: Tests grün**

Run: `uv run pytest tests/test_web.py -q`
Expected: PASS (alle test_web)

- [ ] **Step 7: Commit**

```bash
git add airbi/web/routes.py airbi/web/templates/dashboard.html airbi/web/templates/_matrix_region.html tests/test_web.py
git commit -m "feat(web): Umkreis-Schalter statt Bezirksfilter im Dashboard"
```

---

### Task 7: Integration — Migration, Config-Update, volle Suite

**Files:** keine Code-Änderung; DB-Migration + Daten-Update auf der lokalen DB.

- [ ] **Step 1: Volle Test-Suite grün**

Run: `uv run pytest -q`
Expected: PASS (alle Tests, keine Fehler). Falls Rest-Referenzen auf
`district_slug`/`bounding_box_for` brechen: beheben, bis grün.

- [ ] **Step 2: Migration auf lokale DB anwenden**

Run: `uv run alembic upgrade head`
Expected: Revision `b2c3d4e5f6a7` läuft durch, keine Fehler.

- [ ] **Step 3: Bestehende Config mit Center/Radien füllen**

Run:
```bash
uv run python -c "
from airbi.db.session import SessionLocal
from airbi.db.models import SearchConfig
s = SessionLocal()
cfg = s.query(SearchConfig).filter_by(name='Marvila Slice 1').one()
cfg.center_lat = 38.7391
cfg.center_lng = -9.1048
cfg.center_label = 'R. Cap. Leitão 86'
cfg.band_radii_km = [1, 2, 3, 5, 10]
s.commit()
print('Config aktualisiert:', cfg.center_label, cfg.band_radii_km)
"
```
Expected: `Config aktualisiert: R. Cap. Leitão 86 [1, 2, 3, 5, 10]`

- [ ] **Step 4: Dashboard manuell gegen Bestandsdaten prüfen (Smoke)**

Run:
```bash
uv run python -c "
from airbi.db.session import SessionLocal
from airbi.db.models import SearchConfig
from airbi.insights.segment_matrix import compute_segment_matrix, latest_completed_run
s = SessionLocal()
cfg = s.query(SearchConfig).filter_by(name='Marvila Slice 1').one()
run = latest_completed_run(s, cfg)
for r in [1,2,3,5,10]:
    m = compute_segment_matrix(s, cfg, float(r), run)
    print(f'{r} km: {m.listing_count} Listings, best={m.best_cell}')
"
```
Expected: aufsteigende `listing_count` mit größerem Radius (Bestandsdaten haben
lat/lng); keine Exception.

- [ ] **Step 5: Commit (nur falls in Step 1 Code gefixt wurde)**

```bash
git add -A && git commit -m "test: volle Suite grün nach Umkreis-Umstellung" || echo "nichts zu committen"
```

---

## Nach dem Plan (durch den Controller, nicht als Subagent-Task)

1. **Live-Re-Crawl** (Dev-Rechner, Residential-IP): `uv run airbi crawl --config "Marvila Slice 1"` — füllt die DB über die konzentrischen Boxen mit dichteren Nahbereichs-Daten. Ergebnis prüfen (`listings_seen`, Verteilung über Radien via Step-4-Smoke).
2. **Prod-Rollout** (Pfad aus `docs/DEPLOYMENT.md`): `git pull` + `alembic upgrade head` auf Prod; Config-Update-SQL (Step 3) auf Prod; Daten per `pg_dump --data-only` → scp → restore. Nur AirBI-Artefakte berühren.
3. **DEPLOYMENT.md** ggf. um den Umkreis-Hinweis ergänzen.
4. **Visual-Companion-Server** stoppen, Brainstorm-Artefakte aufräumen.

## Self-Review (Controller)

- Spec-Abdeckung: §3 Felder → Task 2; §4 distance → Task 1; §5 Crawl → Task 3+5;
  §6 Insights → Task 4; §7 Dashboard → Task 6; §8 Migration/Seed → Task 2+7;
  §9 Tests → in jeder Task. ✓
- Typkonsistenz: `radius_km: float`, `center_label: str|None`,
  `SegmentMatrix.radius_km` (Pflichtfeld vor Default-Feldern), `concentric_boxes`
  Rückgabe (sw_lat,sw_lng,ne_lat,ne_lng) konsistent mit `_search_url`-Entpackung. ✓
- Keine Platzhalter; jede Task enthält vollständigen Code. ✓
- Reihenfolge hält das Repo grün: Task 3 ändert persist + Aufrufstelle gemeinsam;
  Task 5 entfernt `bounding_box_for` erst, nachdem es nicht mehr genutzt wird. ✓
