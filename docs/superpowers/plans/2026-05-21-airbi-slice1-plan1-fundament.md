# AirBI Slice 1 — Plan 1: Fundament & Klassifikation — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Das Datenfundament für AirBI bauen — Postgres-Schema, Geo-Bezirkszuordnung und Klassifikationslogik (`size_class`, `price_tier`) — alles vollständig unit-getestet, ohne Browser oder Netzwerk.

**Architecture:** Eine Python-Anwendung (`airbi`-Paket). PostgreSQL über SQLAlchemy 2.0 ORM, Migrationen über Alembic. Geo-Bezirke als GeoJSON-Polygone, Punkt-in-Polygon über `shapely` (kein PostGIS). Klassifikation als reine Funktionen: `size_class` hängt nur an der Zimmerzahl, `price_tier` an ADR-Perzentilen innerhalb einer Bezirks-Kohorte und wird zur Abfragezeit berechnet.

**Tech Stack:** Python ≥3.11, `uv` (Paket-/Env-Manager), SQLAlchemy 2.0, Alembic, psycopg 3, shapely 2, pydantic-settings, pytest.

**Bezug:** Umsetzung von `docs/superpowers/specs/2026-05-21-airbi-slice1-marvila-design.md`, Abschnitte §4 (Architektur), §5 (Datenmodell), §6 (Geo), §8 (Klassifikation).

---

## Voraussetzungen (vor Task 1 herstellen)

- Python ≥3.11 installiert.
- `uv` installiert (`curl -LsSf https://astral.sh/uv/install.sh | sh`).
- Lokales PostgreSQL läuft. Datenbanken + Rolle anlegen (Defaults aus `config.py`):

```bash
createuser airbi --createdb 2>/dev/null || true
psql -d postgres -c "ALTER ROLE airbi WITH PASSWORD 'airbi';"
createdb -O airbi airbi
createdb -O airbi airbi_test
```

- **Vor Beginn der Umsetzung:** einen Feature-Branch bzw. Worktree anlegen (über die `superpowers:using-git-worktrees`-Skill). Nicht direkt auf `main` arbeiten.

---

## Dateistruktur (in diesem Plan erstellt)

| Datei | Verantwortung |
|---|---|
| `pyproject.toml` | Projekt-Metadaten, Dependencies, pytest-Konfiguration |
| `airbi/__init__.py` | Paket-Marker |
| `airbi/config.py` | App-Konfiguration (DB-URLs) via pydantic-settings |
| `airbi/db/__init__.py` | Paket-Marker |
| `airbi/db/session.py` | SQLAlchemy `Base`, Engine-/Session-Factory |
| `airbi/db/models.py` | ORM-Modelle: `SearchConfig`, `CrawlRun`, `Listing`, `Snapshot` |
| `alembic/` + `alembic.ini` | Migrations-Setup + initiale Migration |
| `airbi/geo/__init__.py` | Paket-Marker |
| `airbi/geo/districts.py` | GeoJSON laden, Punkt-in-Polygon-Zuordnung |
| `airbi/geo/data/lisboa/marvila.geojson` | Bezirkspolygon Marvila |
| `airbi/geo/data/lisboa/beato.geojson` | Bezirkspolygon Beato |
| `airbi/classification/__init__.py` | Paket-Marker |
| `airbi/classification/size.py` | `size_class`-Logik |
| `airbi/classification/price.py` | `price_tier`-Logik |
| `tests/conftest.py` | pytest-Fixtures (Test-DB, Transaktions-Rollback) |
| `tests/test_models.py` | Tests für ORM-Modelle |
| `tests/test_geo.py` | Tests für Geo-Zuordnung |
| `tests/test_classification.py` | Tests für `size_class` und `price_tier` |
| `tests/fixtures/geo/testdistrict.geojson` | synthetisches Polygon für deterministische Geo-Tests |

---

## Task 1: Projekt-Scaffolding & Konfiguration

**Files:**
- Create: `pyproject.toml`
- Create: `airbi/__init__.py`, `airbi/db/__init__.py`, `airbi/geo/__init__.py`, `airbi/classification/__init__.py`
- Create: `airbi/config.py`

- [ ] **Step 1: `pyproject.toml` anlegen**

```toml
[project]
name = "airbi"
version = "0.1.0"
description = "Airbnb BI-Tool — Slice 1 (Marvila)"
requires-python = ">=3.11"
dependencies = [
    "sqlalchemy>=2.0",
    "alembic>=1.13",
    "psycopg[binary]>=3.1",
    "shapely>=2.0",
    "pydantic-settings>=2.0",
]
# Plan 2 ergänzt hier playwright; Plan 3 ergänzt fastapi/uvicorn/jinja2.

[dependency-groups]
dev = [
    "pytest>=8.0",
    "pytest-cov>=5.0",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["airbi"]

[tool.pytest.ini_options]
testpaths = ["tests"]
```

- [ ] **Step 2: Paketverzeichnisse mit leeren `__init__.py` anlegen**

Create `airbi/__init__.py`, `airbi/db/__init__.py`, `airbi/geo/__init__.py`, `airbi/classification/__init__.py` — jeweils leer.

- [ ] **Step 3: `airbi/config.py` schreiben**

```python
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """App-Konfiguration. Werte überschreibbar per .env oder Umgebungsvariablen."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://airbi:airbi@localhost:5432/airbi"
    test_database_url: str = "postgresql+psycopg://airbi:airbi@localhost:5432/airbi_test"


settings = Settings()
```

- [ ] **Step 4: Dependencies installieren und Import verifizieren**

Run: `uv sync && uv run python -c "import airbi.config; print(airbi.config.settings.database_url)"`
Expected: gibt `postgresql+psycopg://airbi:airbi@localhost:5432/airbi` aus, kein Fehler.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml uv.lock airbi/
git commit -m "chore: Projekt-Scaffolding und Konfiguration"
```

---

## Task 2: Datenbank-Anbindung & Base

**Files:**
- Create: `airbi/db/session.py`

- [ ] **Step 1: `airbi/db/session.py` schreiben**

```python
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from airbi.config import settings


class Base(DeclarativeBase):
    """Gemeinsame Declarative-Base für alle ORM-Modelle."""


def make_engine(url: str | None = None) -> Engine:
    """Erzeugt eine SQLAlchemy-Engine. Ohne Argument: produktive DB."""
    return create_engine(url or settings.database_url, future=True)


def make_session_factory(bind) -> sessionmaker:
    """Erzeugt eine Session-Factory, gebunden an Engine oder Connection."""
    return sessionmaker(bind=bind, autoflush=False, expire_on_commit=False)


engine = make_engine()
SessionLocal = make_session_factory(engine)
```

- [ ] **Step 2: Import verifizieren**

Run: `uv run python -c "from airbi.db.session import Base, make_engine; make_engine(); print('ok')"`
Expected: gibt `ok` aus, kein Fehler.

- [ ] **Step 3: Commit**

```bash
git add airbi/db/session.py
git commit -m "feat: SQLAlchemy Base und Engine-/Session-Factory"
```

---

## Task 3: ORM-Modelle & Test-Fixtures

**Files:**
- Create: `airbi/db/models.py`
- Create: `tests/conftest.py`
- Test: `tests/test_models.py`

- [ ] **Step 1: Test-Fixtures in `tests/conftest.py` schreiben**

```python
import pytest

from airbi.config import settings
from airbi.db import models  # noqa: F401  -- Modelle registrieren bei Base.metadata
from airbi.db.session import Base, make_engine, make_session_factory


@pytest.fixture(scope="session")
def engine():
    """Engine gegen die Test-DB; Schema einmal pro Testlauf neu aufbauen."""
    eng = make_engine(settings.test_database_url)
    Base.metadata.drop_all(eng)
    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()


@pytest.fixture
def db_session(engine):
    """Session mit Transaktions-Rollback nach jedem Test — keine Testdaten bleiben."""
    connection = engine.connect()
    transaction = connection.begin()
    session = make_session_factory(connection)()
    yield session
    session.close()
    transaction.rollback()
    connection.close()
```

- [ ] **Step 2: Failing Test in `tests/test_models.py` schreiben**

```python
from datetime import datetime
from decimal import Decimal

from airbi.db.models import CrawlRun, Listing, SearchConfig, Snapshot


def test_search_config_persists_with_defaults(db_session):
    cfg = SearchConfig(name="Marvila Slice 1", district_slugs=["marvila", "beato"])
    db_session.add(cfg)
    db_session.flush()

    assert cfg.id is not None
    assert cfg.city_slug == "lisboa"
    assert cfg.district_slugs == ["marvila", "beato"]


def test_crawl_run_links_to_search_config(db_session):
    cfg = SearchConfig(name="Marvila Slice 1")
    run = CrawlRun(search_config=cfg, status="running")
    db_session.add(run)
    db_session.flush()

    assert run.id is not None
    assert run.status == "running"
    assert run.listings_seen == 0
    assert run.search_config.name == "Marvila Slice 1"


def test_listing_unique_per_city_and_airbnb_id(db_session):
    from sqlalchemy.exc import IntegrityError

    db_session.add(Listing(airbnb_id="123", city_slug="lisboa", lat=38.74, lng=-9.10))
    db_session.flush()
    db_session.add(Listing(airbnb_id="123", city_slug="lisboa", lat=38.75, lng=-9.11))
    try:
        db_session.flush()
        assert False, "erwartete IntegrityError wegen Unique-Constraint"
    except IntegrityError:
        pass


def test_snapshot_links_listing_and_crawl_run(db_session):
    cfg = SearchConfig(name="Marvila Slice 1")
    run = CrawlRun(search_config=cfg, status="running")
    listing = Listing(airbnb_id="999", city_slug="lisboa", lat=38.74, lng=-9.10)
    snap = Snapshot(
        listing=listing,
        crawl_run=run,
        captured_at=datetime(2026, 5, 21, 12, 0, 0),
        price=Decimal("120.00"),
        review_count=42,
        rating=4.8,
    )
    db_session.add(snap)
    db_session.flush()

    assert snap.id is not None
    assert snap.price == Decimal("120.00")
    assert snap.review_count == 42
    assert snap.listing.airbnb_id == "999"
```

- [ ] **Step 3: Test laufen lassen, Fehlschlag verifizieren**

Run: `uv run pytest tests/test_models.py -v`
Expected: FAIL — `ModuleNotFoundError` bzw. `ImportError` für `airbi.db.models`.

- [ ] **Step 4: `airbi/db/models.py` schreiben**

```python
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    JSON,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from airbi.db.session import Base


class SearchConfig(Base):
    """Benannter, gespeicherter Suchkontext (Spec §5.1)."""

    __tablename__ = "search_config"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), unique=True)
    city_slug: Mapped[str] = mapped_column(String(80), default="lisboa")
    district_slugs: Mapped[list] = mapped_column(JSON, default=list)
    property_filter: Mapped[dict] = mapped_column(JSON, default=dict)
    classification_config: Mapped[dict] = mapped_column(JSON, default=dict)
    crawl_schedule: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    crawl_runs: Mapped[list["CrawlRun"]] = relationship(back_populates="search_config")


class CrawlRun(Base):
    """Ein Scraper-Lauf einer SearchConfig (Spec §5.2)."""

    __tablename__ = "crawl_run"

    id: Mapped[int] = mapped_column(primary_key=True)
    search_config_id: Mapped[int] = mapped_column(ForeignKey("search_config.id"))
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    status: Mapped[str] = mapped_column(String(20), default="running")
    listings_seen: Mapped[int] = mapped_column(Integer, default=0)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)

    search_config: Mapped["SearchConfig"] = relationship(back_populates="crawl_runs")
    snapshots: Mapped[list["Snapshot"]] = relationship(back_populates="crawl_run")


class Listing(Base):
    """Relativ statische Stammdaten eines Airbnb-Objekts (Spec §5.3)."""

    __tablename__ = "listing"
    __table_args__ = (
        UniqueConstraint("city_slug", "airbnb_id", name="uq_listing_city_airbnb"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    airbnb_id: Mapped[str] = mapped_column(String(40))
    city_slug: Mapped[str] = mapped_column(String(80), default="lisboa")
    district_slug: Mapped[str | None] = mapped_column(String(80), nullable=True)
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    lat: Mapped[float] = mapped_column(Float)
    lng: Mapped[float] = mapped_column(Float)
    property_type: Mapped[str | None] = mapped_column(String(120), nullable=True)
    bedrooms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    beds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    bathrooms: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_guests: Mapped[int | None] = mapped_column(Integer, nullable=True)
    host_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    is_superhost: Mapped[bool] = mapped_column(Boolean, default=False)
    size_class: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # Reserviert für Phase 2 / Detail-Crawl (Spec §5.3)
    license_number: Mapped[str | None] = mapped_column(String(80), nullable=True)
    al_status: Mapped[str | None] = mapped_column(String(40), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    amenities: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    snapshots: Mapped[list["Snapshot"]] = relationship(back_populates="listing")


class Snapshot(Base):
    """Zeitreihen-Eintrag pro Listing und CrawlRun (Spec §5.4)."""

    __tablename__ = "snapshot"

    id: Mapped[int] = mapped_column(primary_key=True)
    listing_id: Mapped[int] = mapped_column(ForeignKey("listing.id"))
    crawl_run_id: Mapped[int] = mapped_column(ForeignKey("crawl_run.id"))
    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    price: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    fees: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    review_count: Mapped[int] = mapped_column(Integer, default=0)
    rating: Mapped[float | None] = mapped_column(Float, nullable=True)
    search_position: Mapped[int | None] = mapped_column(Integer, nullable=True)

    listing: Mapped["Listing"] = relationship(back_populates="snapshots")
    crawl_run: Mapped["CrawlRun"] = relationship(back_populates="snapshots")
```

- [ ] **Step 5: Tests laufen lassen, Erfolg verifizieren**

Run: `uv run pytest tests/test_models.py -v`
Expected: PASS — alle 4 Tests grün.

- [ ] **Step 6: Commit**

```bash
git add airbi/db/models.py tests/conftest.py tests/test_models.py
git commit -m "feat: ORM-Modelle SearchConfig, CrawlRun, Listing, Snapshot"
```

---

## Task 4: Alembic-Setup & initiale Migration

**Files:**
- Create: `alembic.ini`, `alembic/` (durch `alembic init` erzeugt)
- Modify: `alembic/env.py`
- Create: `alembic/versions/<hash>_initial_schema.py` (durch Autogenerate erzeugt)

- [ ] **Step 1: Alembic initialisieren**

Run: `uv run alembic init alembic`
Expected: legt `alembic.ini` und das `alembic/`-Verzeichnis an.

- [ ] **Step 2: `alembic/env.py` an das Projekt anbinden**

Drei Änderungen in `alembic/env.py`:

(a) Nach den bestehenden Imports am Dateianfang die Projekt-Imports ergänzen:

```python
from airbi.config import settings
from airbi.db import models  # noqa: F401  -- registriert Modelle bei Base.metadata
from airbi.db.session import Base
```

(b) Die bestehende Zeile `config = context.config` belassen und **unmittelbar darunter** einfügen (sie braucht das bereits definierte `config`-Objekt):

```python
config.set_main_option("sqlalchemy.url", settings.database_url)
```

(c) Die bestehende Zeile `target_metadata = None` ersetzen durch:

```python
target_metadata = Base.metadata
```

- [ ] **Step 3: Initiale Migration autogenerieren**

Run: `uv run alembic revision --autogenerate -m "initial schema"`
Expected: erzeugt eine Datei unter `alembic/versions/`. Diese Datei öffnen und prüfen: `op.create_table(` für `search_config`, `crawl_run`, `listing` und `snapshot` ist vorhanden; die Unique-Constraints `search_config.name` und `uq_listing_city_airbnb` sind enthalten.

- [ ] **Step 4: Migration anwenden und Schema verifizieren**

Run: `uv run alembic upgrade head && uv run python -c "import sqlalchemy as sa; e=sa.create_engine('postgresql+psycopg://airbi:airbi@localhost:5432/airbi'); print(sorted(sa.inspect(e).get_table_names()))"`
Expected: gibt `['alembic_version', 'crawl_run', 'listing', 'search_config', 'snapshot']` aus.

- [ ] **Step 5: Commit**

```bash
git add alembic.ini alembic/
git commit -m "feat: Alembic-Setup und initiale Schema-Migration"
```

---

## Task 5: Geo — GeoJSON-Daten & Bezirkszuordnung

**Files:**
- Create: `airbi/geo/data/lisboa/marvila.geojson`
- Create: `airbi/geo/data/lisboa/beato.geojson`
- Create: `airbi/geo/districts.py`
- Create: `tests/fixtures/geo/testdistrict.geojson`
- Test: `tests/test_geo.py`

- [ ] **Step 1: Echte Bezirkspolygone beschaffen**

Reale GeoJSON-Polygone der Freguesias **Marvila** und **Beato** (Lissabon) besorgen und als `airbi/geo/data/lisboa/marvila.geojson` bzw. `beato.geojson` ablegen. Quelle: OpenStreetMap-Export der jeweiligen `boundary=administrative`-Relation (z. B. über die Overpass-API / `polygons.openstreetmap.fr`), alternativ die Carta Administrativa Oficial de Portugal (CAOP). Jede Datei muss valides GeoJSON sein — ein `Feature`, eine `FeatureCollection` oder eine reine `Geometry` vom Typ `Polygon`/`MultiPolygon`, Koordinaten in `[lng, lat]`-Reihenfolge (GeoJSON-Standard). Der Dateiname ohne Endung ist der `district_slug`.

- [ ] **Step 2: Synthetisches Test-Polygon anlegen**

Create `tests/fixtures/geo/testdistrict.geojson` — ein deterministisches Quadrat für Geo-Unit-Tests:

```json
{
  "type": "Feature",
  "properties": {},
  "geometry": {
    "type": "Polygon",
    "coordinates": [[[-1.0, -1.0], [1.0, -1.0], [1.0, 1.0], [-1.0, 1.0], [-1.0, -1.0]]]
  }
}
```

- [ ] **Step 3: Failing Test in `tests/test_geo.py` schreiben**

```python
from pathlib import Path

from airbi.geo.districts import assign_district, load_districts

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "geo"
REAL_DATA_DIR = Path(__file__).parents[1] / "airbi" / "geo" / "data" / "lisboa"

# Zielobjekt aus Briefing §12: R. Cap. Leitão 86, Bezirk Marvila.
MARVILA_TARGET = (38.7390, -9.1044)


def test_load_districts_reads_geojson_by_slug():
    districts = load_districts(FIXTURE_DIR)
    assert "testdistrict" in districts


def test_point_inside_polygon_is_assigned():
    districts = load_districts(FIXTURE_DIR)
    assert assign_district(0.0, 0.0, districts) == "testdistrict"


def test_point_outside_polygon_returns_none():
    districts = load_districts(FIXTURE_DIR)
    assert assign_district(5.0, 5.0, districts) is None


def test_real_marvila_polygon_contains_target_object():
    districts = load_districts(REAL_DATA_DIR)
    lat, lng = MARVILA_TARGET
    assert assign_district(lat, lng, districts) == "marvila"
```

- [ ] **Step 4: Test laufen lassen, Fehlschlag verifizieren**

Run: `uv run pytest tests/test_geo.py -v`
Expected: FAIL — `ModuleNotFoundError` für `airbi.geo.districts`.

- [ ] **Step 5: `airbi/geo/districts.py` schreiben**

```python
import json
from pathlib import Path

from shapely.geometry import Point, shape
from shapely.geometry.base import BaseGeometry

_DEFAULT_DATA_DIR = Path(__file__).parent / "data" / "lisboa"


def _extract_geometry(geojson: dict) -> BaseGeometry:
    """Wandelt ein GeoJSON-Objekt (Geometry, Feature oder FeatureCollection)
    in eine einzelne shapely-Geometrie um."""
    kind = geojson.get("type")
    if kind == "FeatureCollection":
        geoms = [shape(f["geometry"]) for f in geojson["features"]]
        merged = geoms[0]
        for geom in geoms[1:]:
            merged = merged.union(geom)
        return merged
    if kind == "Feature":
        return shape(geojson["geometry"])
    return shape(geojson)


def load_districts(data_dir: Path | None = None) -> dict[str, BaseGeometry]:
    """Lädt alle *.geojson-Dateien aus dem Verzeichnis. Dateiname (ohne
    Endung) = district_slug."""
    directory = data_dir or _DEFAULT_DATA_DIR
    districts: dict[str, BaseGeometry] = {}
    for path in sorted(directory.glob("*.geojson")):
        with path.open(encoding="utf-8") as fh:
            districts[path.stem] = _extract_geometry(json.load(fh))
    return districts


def assign_district(
    lat: float, lng: float, districts: dict[str, BaseGeometry]
) -> str | None:
    """Ordnet einen Punkt per Punkt-in-Polygon einem district_slug zu.
    Liegt der Punkt in keinem Polygon, wird None zurückgegeben."""
    point = Point(lng, lat)  # GeoJSON-Reihenfolge ist (lng, lat)
    for slug, geometry in districts.items():
        if geometry.contains(point):
            return slug
    return None
```

- [ ] **Step 6: Tests laufen lassen, Erfolg verifizieren**

Run: `uv run pytest tests/test_geo.py -v`
Expected: PASS — alle 4 Tests grün. Schlägt `test_real_marvila_polygon_contains_target_object` fehl, ist die `marvila.geojson` aus Step 1 fehlerhaft (falsche Koordinaten-Reihenfolge oder falsches Gebiet) — korrigieren.

- [ ] **Step 7: Commit**

```bash
git add airbi/geo/ tests/fixtures/geo/ tests/test_geo.py
git commit -m "feat: Geo-Bezirkszuordnung (GeoJSON + Punkt-in-Polygon)"
```

---

## Task 6: Klassifikation — `size_class`

**Files:**
- Create: `airbi/classification/size.py`
- Test: `tests/test_classification.py`

- [ ] **Step 1: Failing Test in `tests/test_classification.py` schreiben**

```python
from airbi.classification.size import size_class


def test_size_class_studio_for_zero_bedrooms():
    assert size_class(0) == "Studio"


def test_size_class_one_two_three_plus():
    assert size_class(1) == "1BR"
    assert size_class(2) == "2BR"
    assert size_class(3) == "3BR+"
    assert size_class(5) == "3BR+"


def test_size_class_unclassified_for_missing_bedrooms():
    assert size_class(None) == "unclassified"
```

- [ ] **Step 2: Test laufen lassen, Fehlschlag verifizieren**

Run: `uv run pytest tests/test_classification.py -v`
Expected: FAIL — `ModuleNotFoundError` für `airbi.classification.size`.

- [ ] **Step 3: `airbi/classification/size.py` schreiben**

```python
DEFAULT_SIZE_CONFIG = {"three_plus_min_bedrooms": 3}


def size_class(bedrooms: int | None, config: dict | None = None) -> str:
    """Leitet die Größenklasse aus der Schlafzimmerzahl ab.

    Studio (0) / 1BR / 2BR / 3BR+ . Ohne verwertbare Angabe: 'unclassified'.
    Die Untergrenze für '3BR+' ist über config['three_plus_min_bedrooms']
    justierbar (Spec §8)."""
    cfg = {**DEFAULT_SIZE_CONFIG, **(config or {})}
    if bedrooms is None:
        return "unclassified"
    if bedrooms <= 0:
        return "Studio"
    if bedrooms == 1:
        return "1BR"
    if bedrooms == 2:
        return "2BR"
    if bedrooms >= cfg["three_plus_min_bedrooms"]:
        return "3BR+"
    return "unclassified"
```

- [ ] **Step 4: Tests laufen lassen, Erfolg verifizieren**

Run: `uv run pytest tests/test_classification.py -v`
Expected: PASS — alle 3 `size_class`-Tests grün.

- [ ] **Step 5: Commit**

```bash
git add airbi/classification/size.py tests/test_classification.py
git commit -m "feat: size_class-Klassifikation"
```

---

## Task 7: Klassifikation — `price_tier`

**Files:**
- Create: `airbi/classification/price.py`
- Modify: `tests/test_classification.py`

- [ ] **Step 1: Failing Tests in `tests/test_classification.py` ergänzen**

Folgende Importzeile am Dateianfang ergänzen (zusätzlich zum bestehenden `size`-Import):

```python
from airbi.classification.price import price_tier
```

Am Ende von `tests/test_classification.py` anhängen:

```python
COHORT = [50, 60, 70, 80, 90, 100, 110, 120, 130, 200]


def test_price_tier_budget_for_low_price():
    # Perzentil-Rang von 55 in COHORT = 1/10 = 0.10 -> Budget
    assert price_tier(55, COHORT) == "Budget"


def test_price_tier_mid_for_median_price():
    # Rang von 100 = 5/10 = 0.50 -> Mid
    assert price_tier(100, COHORT) == "Mid"


def test_price_tier_luxury_for_top_price():
    # Rang von 200 = 9/10 = 0.90 -> Luxury
    assert price_tier(200, COHORT) == "Luxury"


def test_price_tier_unclassified_for_missing_price():
    assert price_tier(None, COHORT) == "unclassified"


def test_price_tier_unclassified_for_tiny_cohort():
    assert price_tier(100, [100]) == "unclassified"


def test_price_tier_respects_custom_tiers_from_config():
    config = {"price_tiers": [["Low", 0.0, 0.5], ["High", 0.5, 1.0]]}
    assert price_tier(55, COHORT, config) == "Low"
    assert price_tier(200, COHORT, config) == "High"
```

- [ ] **Step 2: Tests laufen lassen, Fehlschlag verifizieren**

Run: `uv run pytest tests/test_classification.py -v`
Expected: FAIL — `ModuleNotFoundError` für `airbi.classification.price`.

- [ ] **Step 3: `airbi/classification/price.py` schreiben**

```python
from decimal import Decimal

# (Name, untere Perzentil-Grenze inkl., obere Perzentil-Grenze exkl.)
DEFAULT_PRICE_TIERS = [
    ["Budget", 0.0, 0.25],
    ["Mid", 0.25, 0.75],
    ["Premium", 0.75, 0.90],
    ["Luxury", 0.90, 1.0],
]


def price_tier(
    price: float | Decimal | None,
    cohort_prices: list[float | Decimal | None],
    config: dict | None = None,
) -> str:
    """Ordnet einen Preis einer Preisstufe zu — über seinen Perzentil-Rang
    innerhalb der Kohorte (Spec §8).

    Der Rang ist der Anteil der Kohorten-Preise, die strikt kleiner als
    'price' sind. Tier-Grenzen über config['price_tiers'] justierbar.
    Ohne Preis oder bei Kohorte < 2 Werten: 'unclassified'."""
    tiers = (config or {}).get("price_tiers") or DEFAULT_PRICE_TIERS
    clean = [float(p) for p in cohort_prices if p is not None]
    if price is None or len(clean) < 2:
        return "unclassified"

    value = float(price)
    rank = sum(1 for p in clean if p < value) / len(clean)
    for name, low, high in tiers:
        if low <= rank < high:
            return name
    return tiers[-1][0]  # rank == 1.0 -> oberste Stufe
```

- [ ] **Step 4: Tests laufen lassen, Erfolg verifizieren**

Run: `uv run pytest tests/test_classification.py -v`
Expected: PASS — alle Tests grün (3× `size_class`, 6× `price_tier`).

- [ ] **Step 5: Commit**

```bash
git add airbi/classification/price.py tests/test_classification.py
git commit -m "feat: price_tier-Klassifikation (Perzentil-Rang)"
```

---

## Definition of Done (Plan 1)

- [ ] `uv run pytest -v` — alle Tests grün (test_models, test_geo, test_classification).
- [ ] `uv run alembic upgrade head` läuft sauber durch; die DB `airbi` enthält die Tabellen `search_config`, `crawl_run`, `listing`, `snapshot`.
- [ ] `airbi/geo/data/lisboa/marvila.geojson` und `beato.geojson` enthalten echte Polygone; der Marvila-Zielpunkt (38.7390, -9.1044) wird korrekt `marvila` zugeordnet.
- [ ] Alle Tasks committet.

Damit steht das Fundament. **Plan 2 (Scraper Stufe A)** wird nach Abschluss dieses Plans geschrieben — seine Code-Schnittstellen bauen direkt auf den hier definierten Modellen, der `assign_district`-Funktion und den Klassifikationsfunktionen auf.
