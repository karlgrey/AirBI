# Investment-Memo Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Das Dashboard wird zu einem Investment-Memo: Urteil → 4 Kapitel → zugeklappter Anhang, basierend auf einem Heimmarkt-Radius plus benannten Vergleichsmärkten (Anker), im Editorial-Stil.

**Architecture:** Neues Modul `airbi/insights/memo.py` komponiert die bestehende `SegmentMatrix`-Mechanik (unverändert als Rechen-Kern) zu einem `Memo`-Datenobjekt: Heimmarkt-Matrix + pro Vergleichsmarkt eine lokal klassifizierte Anker-Matrix + regelbasierte Vertrauens-Stufe + Kapitel als Fragment-Listen (Text/Chip). Templates rendern das Memo; die alten Blöcke (Kernthesen, Hero, Pionier-Strip, Brief, Chancen) entfallen, Matrix/Karte/Top-Apartments wandern in den Anhang. Der Kernthesen-Generator in `segment_matrix.py` wird entfernt; der Jargon-Test-Vertrag wandert auf die Memo-Texte.

**Tech Stack:** Python 3.12, SQLAlchemy 2 + Alembic, FastAPI + Jinja2 + HTMX + Tailwind, pytest.

**Spec:** `docs/superpowers/specs/2026-06-11-investment-memo-redesign-design.md`

**Branch:** `investment-memo`, abgezweigt von `daten-uhr` (dort liegt der Spec). Vor Task 1: `git checkout daten-uhr && git checkout -b investment-memo`.

**Umgebungsfakten:**
- Repo: `/Users/mca/Development/AirBI`. Tests: `uv run pytest` (nutzt DB `airbi_test`, Schema wird von den Tests gebaut). Migration lokal: `uv run alembic upgrade head` (DB `airbi`).
- Aktueller Alembic-Head: `c3d4e5f6a7b8`.
- `airbi/insights/segment_matrix.py` (1004 Zeilen): Rechen-Kern. Wichtige API: `build_segment_matrix(rows, *, config, radius_km, center_label, crawl_run_id) -> SegmentMatrix`, `compute_segment_matrix(session, search_config, radius_km, crawl_run) -> SegmentMatrix`, `latest_completed_run(session, search_config)`, Dataclasses `ListingRow`, `Cell` (Felder u. a. `n`, `score`, `adr`, `is_thin`), `SegmentMatrix` (Felder u. a. `best_cell: tuple[str,str]|None`, `listing_count`, `min_sample`, `review_rate`, `gap_cell: GapCandidate|None`, `top_performers`, `cells`, Methode `.cell(size, lux)`), Konstanten `SIZE_CLASSES`, `LUXURY_CLASSES`, Helfer `_size_klartext(size)`.
- Distanz-Helfer: dasselbe `haversine_km`, das `segment_matrix.py` importiert — Import-Zeile dort nachschlagen (`grep haversine airbi/insights/segment_matrix.py`) und identisch übernehmen.
- Tests bauen Zeilen über das Muster `_row(...)`/`build_segment_matrix(...)` (siehe `tests/test_segment_matrix.py:53-71`); DB-Tests nutzen die Fixture `db_session` aus `tests/conftest.py`.
- Die Jargon-Blacklist steht in `tests/test_segment_matrix.py::test_kernthesen_have_no_internal_jargon` — sie wird in Task 4 wörtlich übernommen (und das Kürzel „Bew./Apt" darf deshalb auch in Chips NICHT vorkommen — ausgeschrieben „Bewertungen je Apartment").

---

### Task 1: Migration + Modell-Felder (`home_radius_km`, `comparison_markets`)

**Files:**
- Create: `alembic/versions/d4e5f6a7b8c9_search_config_memo_felder.py`
- Modify: `airbi/db/models.py` (Klasse `SearchConfig`, nach `band_radii_km`)
- Test: `tests/test_models.py`

- [ ] **Step 1: Failing Test schreiben** — in `tests/test_models.py` ergänzen:

```python
def test_search_config_memo_fields_roundtrip(db_session):
    cfg = SearchConfig(
        name="Memo-Felder-Test",
        home_radius_km=2.0,
        comparison_markets=[
            {"name": "Alfama/Graça", "lat": 38.714, "lng": -9.128, "radius_km": 1.2},
        ],
    )
    db_session.add(cfg)
    db_session.flush()
    db_session.refresh(cfg)
    assert cfg.home_radius_km == 2.0
    assert cfg.comparison_markets[0]["name"] == "Alfama/Graça"


def test_search_config_memo_fields_default_to_none(db_session):
    cfg = SearchConfig(name="Memo-Felder-Default-Test")
    db_session.add(cfg)
    db_session.flush()
    db_session.refresh(cfg)
    assert cfg.home_radius_km is None
    assert cfg.comparison_markets is None
```

(Imports oben in der Datei prüfen — `SearchConfig` wird dort bereits importiert.)

- [ ] **Step 2: Test läuft rot**

Run: `uv run pytest tests/test_models.py -k memo_fields -v`
Expected: FAIL — `TypeError: 'home_radius_km' is an invalid keyword argument`

- [ ] **Step 3: Modell erweitern** — in `airbi/db/models.py`, Klasse `SearchConfig`, direkt nach dem `band_radii_km`-Block:

```python
    # Investment-Memo (Spec 2026-06-11): Heimmarkt + benannte Vergleichsmärkte.
    # home_radius_km None -> Fallback auf min(band_radii_km).
    # comparison_markets: Liste {name, lat, lng, radius_km} oder None.
    home_radius_km: Mapped[float | None] = mapped_column(Float, nullable=True)
    comparison_markets: Mapped[list | None] = mapped_column(JSON, nullable=True)
```

- [ ] **Step 4: Migration anlegen** — `alembic/versions/d4e5f6a7b8c9_search_config_memo_felder.py`:

```python
"""search_config memo felder (home_radius_km, comparison_markets)

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-06-11

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd4e5f6a7b8c9'
down_revision: Union[str, Sequence[str], None] = 'c3d4e5f6a7b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('search_config', sa.Column('home_radius_km', sa.Float(), nullable=True))
    op.add_column('search_config', sa.Column('comparison_markets', sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column('search_config', 'comparison_markets')
    op.drop_column('search_config', 'home_radius_km')
```

- [ ] **Step 5: Tests grün + Migration lokal anwenden**

Run: `uv run pytest tests/test_models.py -v` → alle PASS.
Run: `uv run alembic upgrade head` → `Running upgrade c3d4e5f6a7b8 -> d4e5f6a7b8c9`.

- [ ] **Step 6: Commit**

```bash
git add airbi/db/models.py alembic/versions/d4e5f6a7b8c9_search_config_memo_felder.py tests/test_models.py
git commit -m "feat(memo): SearchConfig-Felder home_radius_km + comparison_markets"
```

---

### Task 2: `memo.py` — Datenobjekte + Vertrauens-Stufe

**Files:**
- Create: `airbi/insights/memo.py`
- Create: `tests/test_memo.py`

- [ ] **Step 1: Failing Tests** — `tests/test_memo.py` anlegen:

```python
from airbi.insights.memo import (
    CONFIDENCE_BELASTBAR,
    CONFIDENCE_DUENN,
    CONFIDENCE_SOLIDE,
    AnchorStats,
    Fragment,
    Memo,
    MemoChapter,
    compute_confidence,
)


def test_confidence_belastbar_needs_velocity_fresh_data_and_sample():
    assert compute_confidence(
        data_age_days=3, n=5, min_sample=3, velocity_available=True
    ) == CONFIDENCE_BELASTBAR


def test_confidence_solide_without_velocity():
    assert compute_confidence(
        data_age_days=3, n=5, min_sample=3, velocity_available=False
    ) == CONFIDENCE_SOLIDE


def test_confidence_solide_boundary_age_14_and_n_equals_min_sample():
    assert compute_confidence(
        data_age_days=14, n=3, min_sample=3, velocity_available=False
    ) == CONFIDENCE_SOLIDE


def test_confidence_duenn_when_stale_or_thin_or_age_unknown():
    assert compute_confidence(
        data_age_days=15, n=5, min_sample=3, velocity_available=False
    ) == CONFIDENCE_DUENN
    assert compute_confidence(
        data_age_days=3, n=2, min_sample=3, velocity_available=False
    ) == CONFIDENCE_DUENN
    assert compute_confidence(
        data_age_days=None, n=5, min_sample=3, velocity_available=False
    ) == CONFIDENCE_DUENN


def test_confidence_velocity_with_stale_data_is_not_belastbar():
    assert compute_confidence(
        data_age_days=8, n=5, min_sample=3, velocity_available=True
    ) == CONFIDENCE_SOLIDE


def test_chapter_plain_text_joins_fragments():
    ch = MemoChapter(number="02", title="Wo die Nachfrage hinläuft", fragments=[
        Fragment(kind="text", text="Premium sammelt"),
        Fragment(kind="chip", text="37 Bewertungen je Apartment"),
    ])
    assert "Premium sammelt 37 Bewertungen je Apartment" == ch.plain_text
```

- [ ] **Step 2: Rot** — Run: `uv run pytest tests/test_memo.py -v` → FAIL (ModuleNotFoundError).

- [ ] **Step 3: Implementierung** — `airbi/insights/memo.py` anlegen:

```python
"""Investment-Memo: komponiert Heimmarkt-Matrix + Vergleichsmarkt-Anker zu
einem erzählenden Memo (Urteil, Kapitel, Vertrauens-Stufe).

Spec: docs/superpowers/specs/2026-06-11-investment-memo-redesign-design.md.
`segment_matrix.py` bleibt der Rechen-Kern; dieses Modul erzeugt daraus
die Erzähl-Schicht."""

from __future__ import annotations

from dataclasses import dataclass, field

from airbi.insights.segment_matrix import SegmentMatrix

# Teil-3-Hook (Velocity-Modul): solange False, formuliert Kapitel 2 im
# Bestand ("hat gesammelt"); mit True wechselt es auf Buchungs-Trend.
VELOCITY_AVAILABLE = False

CONFIDENCE_BELASTBAR = "belastbar"
CONFIDENCE_SOLIDE = "solide Indizien"
CONFIDENCE_DUENN = "dünne Datenlage"

_CONFIDENCE_DOTS = {
    CONFIDENCE_BELASTBAR: 3,
    CONFIDENCE_SOLIDE: 2,
    CONFIDENCE_DUENN: 1,
}


def compute_confidence(
    *, data_age_days: int | None, n: int, min_sample: int, velocity_available: bool
) -> str:
    """Regelbasierte Vertrauens-Stufe (Spec §4)."""
    if data_age_days is None or n < min_sample:
        return CONFIDENCE_DUENN
    if velocity_available and data_age_days < 7:
        return CONFIDENCE_BELASTBAR
    if data_age_days <= 14:
        return CONFIDENCE_SOLIDE
    return CONFIDENCE_DUENN


@dataclass
class Fragment:
    """Ein Stück Kapitel-Inhalt: Fließtext oder Kennzahlen-Chip."""

    kind: str  # "text" | "chip" | "chip_muted"
    text: str


@dataclass
class AnchorStats:
    """Statistik eines benannten Vergleichsmarkts, lokal klassifiziert."""

    name: str
    radius_km: float
    listing_count: int
    segment_n: int = 0
    segment_score: float | None = None
    segment_adr: float | None = None


@dataclass
class MemoChapter:
    number: str  # "01" .. "04"
    title: str
    fragments: list[Fragment] = field(default_factory=list)

    @property
    def plain_text(self) -> str:
        """Kapitel als reiner Text — Grundlage des Jargon-Tests."""
        return " ".join(f.text for f in self.fragments)


@dataclass
class Memo:
    crawl_run_id: int | None
    home_radius_km: float
    center_label: str | None
    verdict_size_label: str | None      # "2 Schlafzimmer" — None = Memo schweigt
    verdict_luxury_class: str | None
    verdict_subline: str
    confidence: str
    confidence_dots: int                # 1..3, fürs ●●○-Rendering
    chapters: list[MemoChapter] = field(default_factory=list)
    home_matrix: SegmentMatrix | None = None
    anchors: list[AnchorStats] = field(default_factory=list)
    data_age_days: int | None = None
```

- [ ] **Step 4: Grün** — Run: `uv run pytest tests/test_memo.py -v` → alle PASS.

- [ ] **Step 5: Commit**

```bash
git add airbi/insights/memo.py tests/test_memo.py
git commit -m "feat(memo): Datenobjekte + regelbasierte Vertrauens-Stufe"
```

---

### Task 3: Anker-Statistik (Vergleichsmärkte, lokal klassifiziert)

**Files:**
- Modify: `airbi/insights/memo.py`
- Test: `tests/test_memo.py`

- [ ] **Step 1: Failing Test** — in `tests/test_memo.py` ergänzen (DB-Test mit `db_session`-Fixture; Muster für Listing/Snapshot/CrawlRun siehe bestehende `compute_segment_matrix`-Tests am Ende von `tests/test_segment_matrix.py` — dort nachschlagen, wie `Listing`/`Snapshot`/`CrawlRun`/`SearchConfig` minimal angelegt werden, und exakt diesem Muster folgen):

```python
from decimal import Decimal

from airbi.db.models import CrawlRun, Listing, SearchConfig, Snapshot
from airbi.insights.memo import compute_anchor_stats


def _mk_listing(session, airbnb_id, lat, lng, size_class="1BR", bedrooms=1):
    listing = Listing(
        airbnb_id=airbnb_id, url=f"https://x/{airbnb_id}", title=f"L{airbnb_id}",
        city_slug="lisboa", lat=lat, lng=lng,
        size_class=size_class, bedrooms=bedrooms,
    )
    session.add(listing)
    session.flush()
    return listing


def test_compute_anchor_stats_counts_only_listings_near_anchor(db_session):
    cfg = SearchConfig(name="Anker-Test", city_slug="lisboa",
                       center_lat=38.7390, center_lng=-9.1044)
    db_session.add(cfg)
    db_session.flush()
    run = CrawlRun(search_config_id=cfg.id, status="completed")
    db_session.add(run)
    db_session.flush()

    # Zwei Listings am Anker (Alfama, ~38.714/-9.128), eins weit weg.
    near1 = _mk_listing(db_session, "a1", 38.714, -9.128)
    near2 = _mk_listing(db_session, "a2", 38.715, -9.127)
    far = _mk_listing(db_session, "f1", 38.768, -9.094)
    for listing, price in ((near1, "100"), (near2, "200"), (far, "150")):
        db_session.add(Snapshot(listing_id=listing.id, crawl_run_id=run.id,
                                price=Decimal(price), review_count=10))
    db_session.flush()

    market = {"name": "Alfama/Graça", "lat": 38.714, "lng": -9.128, "radius_km": 1.2}
    stats = compute_anchor_stats(db_session, cfg, run, market, segment=None)
    assert stats.name == "Alfama/Graça"
    assert stats.listing_count == 2          # far liegt außerhalb des Anker-Radius


def test_compute_anchor_stats_segment_uses_local_cohort(db_session):
    """Klassifikation relativ zum ANKER-Markt, nicht zum Heimmarkt: Das
    teuerste Anker-Listing landet in der lokalen Top-Preisklasse."""
    cfg = SearchConfig(name="Anker-Kohorte-Test", city_slug="lisboa",
                       center_lat=38.7390, center_lng=-9.1044)
    db_session.add(cfg)
    db_session.flush()
    run = CrawlRun(search_config_id=cfg.id, status="completed")
    db_session.add(run)
    db_session.flush()

    prices = ["80", "90", "100", "110", "300"]   # 300 = lokales Top-Quartil
    for i, price in enumerate(prices):
        listing = _mk_listing(db_session, f"k{i}", 38.714 + i * 0.0004, -9.128)
        db_session.add(Snapshot(listing_id=listing.id, crawl_run_id=run.id,
                                price=Decimal(price), review_count=20))
    db_session.flush()

    market = {"name": "Alfama/Graça", "lat": 38.714, "lng": -9.128, "radius_km": 1.2}
    stats = compute_anchor_stats(db_session, cfg, run, market, segment=("1BR", "Luxury"))
    assert stats.segment_n >= 1               # das 300er-Listing ist lokal Luxury
```

- [ ] **Step 2: Rot** — Run: `uv run pytest tests/test_memo.py -k anchor -v` → FAIL (ImportError `compute_anchor_stats`).

- [ ] **Step 3: Implementierung** — in `airbi/insights/memo.py` ergänzen (Imports oben erweitern; `haversine_km` exakt so importieren wie in `segment_matrix.py`):

```python
from sqlalchemy import select
from sqlalchemy.orm import Session

from airbi.db.models import CrawlRun, Listing, SearchConfig, Snapshot
from airbi.insights.segment_matrix import (
    ListingRow,
    SegmentMatrix,
    build_segment_matrix,
)
# + haversine_km — Import-Zeile aus segment_matrix.py übernehmen


def _load_rows_for_center(
    session: Session,
    search_config: SearchConfig,
    crawl_run: CrawlRun,
    center_lat: float,
    center_lng: float,
    radius_km: float,
) -> list[ListingRow]:
    """Listings+Snapshots des Runs im Umkreis eines beliebigen Zentrums —
    gleiche Zeilen-Abbildung wie compute_segment_matrix, aber mit freiem
    Mittelpunkt (für Vergleichsmärkte)."""
    session.flush()
    stmt = (
        select(Listing, Snapshot)
        .join(Snapshot, Snapshot.listing_id == Listing.id)
        .where(Snapshot.crawl_run_id == crawl_run.id)
        .where(Listing.city_slug == search_config.city_slug)
    )
    rows: list[ListingRow] = []
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
                amenities=listing.amenities or [],
                bedrooms=listing.bedrooms,
                beds=listing.beds,
                max_guests=listing.max_guests,
                is_superhost=bool(listing.is_superhost),
            )
        )
    return rows


def compute_anchor_stats(
    session: Session,
    search_config: SearchConfig,
    crawl_run: CrawlRun,
    market: dict,
    segment: tuple[str, str] | None,
) -> AnchorStats:
    """Statistik eines Vergleichsmarkts. Klassifikation in der EIGENEN
    Kohorte des Anker-Markts (Spec §2.2); `segment` ist die Heimmarkt-
    Empfehlung (size, lux), deren Pendant im Anker gesucht wird."""
    rows = _load_rows_for_center(
        session, search_config, crawl_run,
        market["lat"], market["lng"], market["radius_km"],
    )
    matrix = build_segment_matrix(
        rows,
        config=search_config.classification_config or {},
        radius_km=market["radius_km"],
        center_label=market["name"],
        crawl_run_id=crawl_run.id,
    )
    stats = AnchorStats(
        name=market["name"],
        radius_km=float(market["radius_km"]),
        listing_count=matrix.listing_count,
    )
    if segment is not None:
        cell = matrix.cell(*segment)
        stats.segment_n = cell.n
        stats.segment_score = cell.score
        stats.segment_adr = float(cell.adr) if cell.adr is not None else None
    return stats
```

- [ ] **Step 4: Grün** — Run: `uv run pytest tests/test_memo.py -v` → alle PASS. Falls das Listing-Modell andere Pflichtfelder hat (NOT-NULL-Fehler), das Anlage-Muster aus `tests/test_segment_matrix.py` übernehmen und die Test-Helper anpassen — nicht das Modul.

- [ ] **Step 5: Commit**

```bash
git add airbi/insights/memo.py tests/test_memo.py
git commit -m "feat(memo): Anker-Statistik mit lokaler Kohorten-Klassifikation"
```

---

### Task 4: Kapitel-Generator `build_memo` + Jargon-Vertrag

**Files:**
- Modify: `airbi/insights/memo.py`
- Test: `tests/test_memo.py`

- [ ] **Step 1: Failing Tests** — in `tests/test_memo.py` ergänzen. Die Blacklist wörtlich aus `tests/test_segment_matrix.py::test_kernthesen_have_no_internal_jargon` übernehmen (dort nachsehen; sie umfasst 11 Begriffe wie „Nachbar-Cell", „Demand-Signal", „Sweet-Spot", „Pricing-Fenster", „Bew./Apt", „TL;DR" …):

```python
from airbi.insights.segment_matrix import build_segment_matrix, ListingRow
from airbi.insights.memo import build_memo


def _row(airbnb_id, size_class, price, review_count):
    return ListingRow(
        airbnb_id=airbnb_id, title=f"L{airbnb_id}", url=f"https://x/{airbnb_id}",
        size_class=size_class, price=Decimal(str(price)),
        review_count=review_count, rating=4.8,
    )


def _home_matrix():
    """Heimmarkt mit klarer Best-Cell. WICHTIG: die drei 1BR-Zeilen haben
    bewusst IDENTISCHE Preise — gleiches Preis-Perzentil heißt gleiche
    Luxusklasse, nur so erreicht die Zelle n=3 (sonst keine Best-Cell)."""
    rows = [
        _row("h1", "1BR", 100, 40), _row("h2", "1BR", 100, 35), _row("h3", "1BR", 100, 45),
        _row("h4", "2BR", 200, 5), _row("h5", "2BR", 210, 8), _row("h6", "2BR", 190, 2),
        _row("h7", "Studio", 60, 1),
    ]
    return build_segment_matrix(
        rows, config={}, radius_km=2.0,
        center_label="R. Cap. Leitão 86", crawl_run_id=1,
    )


def _anchors():
    return [
        AnchorStats(name="Alfama/Graça", radius_km=1.2, listing_count=240,
                    segment_n=30, segment_score=52.0, segment_adr=120.0),
        AnchorStats(name="Parque das Nações", radius_km=1.5, listing_count=150,
                    segment_n=12, segment_score=41.0, segment_adr=110.0),
    ]


def test_build_memo_verdict_names_segment_and_confidence():
    memo = build_memo(_home_matrix(), _anchors(), data_age_days=2)
    assert memo.verdict_size_label == "1 Schlafzimmer"
    assert memo.verdict_luxury_class in ("Budget", "Mid", "Premium", "Luxury")
    assert memo.confidence == CONFIDENCE_SOLIDE
    assert memo.confidence_dots == 2


def test_build_memo_has_four_chapters_with_gap_else_three():
    memo = build_memo(_home_matrix(), _anchors(), data_age_days=2)
    titles = [c.title for c in memo.chapters]
    assert titles[0] == "Der Markt vor Ort"
    assert titles[1] == "Wo die Nachfrage hinläuft"
    assert titles[-1] == "Was dagegen spricht"
    # Kapitel "Die Alternative" nur, wenn der Lücken-Finder fündig wurde:
    if _home_matrix().gap_cell:
        assert "Die Alternative" in titles


def test_build_memo_chapter1_anchors_density():
    memo = build_memo(_home_matrix(), _anchors(), data_age_days=2)
    ch1 = memo.chapters[0].plain_text
    assert "7" in ch1                  # Heimmarkt-Dichte (listing_count)
    assert "Alfama/Graça" in ch1       # Anker benannt
    assert "240" in ch1                # Anker-Dichte


def test_build_memo_chapter2_has_value_chip_with_median_factor_and_anchor_chips():
    memo = build_memo(_home_matrix(), _anchors(), data_age_days=2)
    ch2 = memo.chapters[1]
    chips = [f for f in ch2.fragments if f.kind == "chip"]
    muted = [f for f in ch2.fragments if f.kind == "chip_muted"]
    assert any("Bewertungen je Apartment" in c.text for c in chips)
    assert any("×" in c.text for c in chips)            # Median-Faktor
    assert any("Alfama/Graça" in m.text for m in muted)  # Anker-Chip
    assert any("52" in m.text for m in muted)


def test_build_memo_chapter2_stock_wording_without_velocity():
    memo = build_memo(_home_matrix(), _anchors(), data_age_days=2)
    ch2 = memo.chapters[1].plain_text
    assert "gesammelt" in ch2          # Bestands-Formulierung (Teil-3-Weiche)


def test_build_memo_risk_chapter_names_age_proxy_and_al():
    memo = build_memo(_home_matrix(), _anchors(), data_age_days=9)
    risk = memo.chapters[-1].plain_text
    assert "9 Tage" in risk
    assert "Indikator" in risk         # Proxy-Annahme
    assert "AL-Lizenz" in risk         # ungeprüft (al_zone_status=None)


def test_build_memo_risk_chapter_skips_al_when_zone_known():
    memo = build_memo(_home_matrix(), _anchors(), data_age_days=2,
                      al_zone_status="ABSORCAO")
    assert "AL-Lizenz" not in memo.chapters[-1].plain_text


def test_build_memo_silent_without_best_cell():
    rows = [_row("x1", "1BR", 100, 5)]   # nur 1 Listing -> alles thin
    matrix = build_segment_matrix(rows, config={}, radius_km=2.0,
                                  center_label="X", crawl_run_id=1)
    memo = build_memo(matrix, [], data_age_days=2)
    assert memo.verdict_size_label is None
    assert memo.chapters == []
    assert "3" in memo.verdict_subline   # nennt die min_sample-Schwelle


def test_build_memo_anchorless_renders_without_anchor_chips():
    memo = build_memo(_home_matrix(), [], data_age_days=2)
    ch2 = memo.chapters[1]
    assert not [f for f in ch2.fragments if f.kind == "chip_muted"]


JARGON_BLACKLIST = [
    # ... wörtlich aus test_kernthesen_have_no_internal_jargon übernehmen ...
]


def test_memo_texts_have_no_internal_jargon():
    memo = build_memo(_home_matrix(), _anchors(), data_age_days=2)
    texts = [memo.verdict_subline] + [c.plain_text for c in memo.chapters]
    for text in texts:
        for term in JARGON_BLACKLIST:
            assert term.lower() not in text.lower(), f"Jargon '{term}' in: {text}"
```

- [ ] **Step 2: Rot** — Run: `uv run pytest tests/test_memo.py -k build_memo -v` → FAIL (ImportError `build_memo`).

- [ ] **Step 3: Implementierung** — in `airbi/insights/memo.py` ergänzen:

```python
from airbi.insights.segment_matrix import _size_klartext


def _fmt_score(score: float) -> str:
    return f"{score:.0f}"


def _median_cell_score(matrix: SegmentMatrix) -> float | None:
    scores = sorted(
        c.score for c in matrix.cells.values() if c.score is not None and c.n > 0
    )
    if not scores:
        return None
    mid = len(scores) // 2
    if len(scores) % 2:
        return scores[mid]
    return (scores[mid - 1] + scores[mid]) / 2


def _density_phrase(home_count: int, anchor: AnchorStats) -> str:
    if anchor.listing_count <= 0:
        return ""
    ratio = home_count / anchor.listing_count
    if ratio < 0.15:
        return "ein Bruchteil dieser Dichte"
    if ratio < 0.45:
        return f"rund ein {'Drittel' if ratio >= 0.28 else 'Viertel'} dieser Dichte"
    if ratio < 0.8:
        return "etwa die Hälfte dieser Dichte"
    return "eine vergleichbare Dichte"


def build_memo(
    home_matrix: SegmentMatrix,
    anchors: list[AnchorStats],
    *,
    data_age_days: int | None,
    al_zone_status: str | None = None,
    velocity_available: bool = VELOCITY_AVAILABLE,
) -> Memo:
    """Erzeugt das Memo aus der fertigen Heimmarkt-Matrix + Anker-Statistik.
    Ohne Best-Cell schweigt das Memo (kein Urteil, keine Kapitel)."""
    radius = home_matrix.radius_km or 0.0
    center = home_matrix.center_label or "das Zielobjekt"

    if home_matrix.best_cell is None:
        return Memo(
            crawl_run_id=home_matrix.crawl_run_id,
            home_radius_km=radius,
            center_label=home_matrix.center_label,
            verdict_size_label=None,
            verdict_luxury_class=None,
            verdict_subline=(
                f"Im Heimmarkt ({radius:g} km um {center}) erreicht noch keine "
                f"Kombination aus Größe und Luxusklasse {home_matrix.min_sample} "
                f"vergleichbare Apartments — das Memo trifft deshalb kein Urteil."
            ),
            confidence=CONFIDENCE_DUENN,
            confidence_dots=_CONFIDENCE_DOTS[CONFIDENCE_DUENN],
            home_matrix=home_matrix,
            anchors=anchors,
            data_age_days=data_age_days,
        )

    size, lux = home_matrix.best_cell
    bcell = home_matrix.cell(size, lux)
    size_label = _size_klartext(size)
    confidence = compute_confidence(
        data_age_days=data_age_days, n=bcell.n,
        min_sample=home_matrix.min_sample,
        velocity_available=velocity_available,
    )

    chapters: list[MemoChapter] = []

    # ---- Kapitel 1: Der Markt vor Ort -------------------------------
    frags = [Fragment("text", (
        f"Im Heimmarkt — {radius:g} km um {center} — stehen "
        f"{home_matrix.listing_count} vergleichbare Apartments im Wettbewerb."
    ))]
    if anchors:
        first = anchors[0]
        frags.append(Fragment("text", "Zum Vergleich:"))
        for a in anchors:
            frags.append(Fragment("chip_muted", f"{a.name} {a.listing_count} Apartments"))
        phrase = _density_phrase(home_matrix.listing_count, first)
        if phrase:
            frags.append(Fragment("text", (
                f"— der Heimmarkt hat {phrase}, typisch für eine junge Lage "
                f"mit Raum für neue Anbieter."
            )))
    chapters.append(MemoChapter("01", "Der Markt vor Ort", frags))

    # ---- Kapitel 2: Wo die Nachfrage hinläuft ------------------------
    verb = (
        "wird aktuell am stärksten gebucht"
        if velocity_available
        else "hat je Apartment die meisten Bewertungen gesammelt"
    )
    frags = [Fragment("text", f"{size_label} im {lux}-Segment {verb}:")]
    median = _median_cell_score(home_matrix)
    chip = f"{_fmt_score(bcell.score)} Bewertungen je Apartment"
    if median and median > 0:
        chip += f" — {bcell.score / median:.1f}× des lokalen Medians"
    frags.append(Fragment("chip", chip))
    scored = [a for a in anchors if a.segment_score is not None]
    if scored:
        frags.append(Fragment("text", "Dieselbe Klasse erreicht in"))
        for a in scored:
            frags.append(Fragment("chip_muted", f"{a.name} {_fmt_score(a.segment_score)}"))
        strongest = max(scored, key=lambda a: a.segment_score)
        pct = int(round(100 * bcell.score / strongest.segment_score))
        frags.append(Fragment("text", (
            f"— der Heimmarkt liegt damit bei {pct} % des stärksten "
            f"Vergleichsmarkts, bei deutlich weniger Wettbewerbern "
            f"({bcell.n} gegenüber {strongest.segment_n})."
        )))
    chapters.append(MemoChapter("02", "Wo die Nachfrage hinläuft", frags))

    # ---- Kapitel 3: Die Alternative (nur mit Lücken-Fund) -------------
    gap = home_matrix.gap_cell
    if gap is not None:
        frags = [
            Fragment("text", (
                f"{_size_klartext(gap.size_class)} · {gap.luxury_class} ist im "
                f"Heimmarkt bislang praktisch unbesetzt."
            )),
            Fragment("text", gap.rationale),
        ]
        chapters.append(MemoChapter(f"{len(chapters) + 1:02d}", "Die Alternative", frags))

    # ---- Kapitel 4: Was dagegen spricht (immer) -----------------------
    rate_pct = int(round(home_matrix.review_rate * 100))
    frags = []
    if data_age_days is not None:
        age_text = f"Der Datenstand ist {data_age_days} Tage alt."
        if data_age_days > 14:
            age_text += " Das ist zu alt für ein belastbares Urteil — ein frischer Datenlauf steht aus."
        frags.append(Fragment("text", age_text))
    frags.append(Fragment("text", (
        f"Alle Nachfrage-Werte sind aus Bewertungen abgeleitet (Annahme: rund "
        f"{rate_pct} % der Gäste bewerten) — ein Indikator, keine gemessene Auslastung."
    )))
    if al_zone_status is None:
        frags.append(Fragment("text", (
            "Die AL-Lizenz-Lage (Zonas de Contenção) ist für diese Adresse noch "
            "ungeprüft — vor einer Investitionsentscheidung zwingend zu klären."
        )))
    if bcell.n < 2 * home_matrix.min_sample:
        frags.append(Fragment("text", (
            f"Die Stichprobe im empfohlenen Segment ist mit {bcell.n} Apartments "
            f"überschaubar — einzelne Ausreißer können das Bild verschieben."
        )))
    if confidence == CONFIDENCE_DUENN:
        frags.append(Fragment("text", (
            "Insgesamt ist die Datenlage dünn; dieses Memo ist als erster "
            "Hinweis zu lesen, nicht als Entscheidungsgrundlage."
        )))
    chapters.append(MemoChapter(f"{len(chapters) + 1:02d}", "Was dagegen spricht", frags))

    return Memo(
        crawl_run_id=home_matrix.crawl_run_id,
        home_radius_km=radius,
        center_label=home_matrix.center_label,
        verdict_size_label=size_label,
        verdict_luxury_class=lux,
        verdict_subline=(
            f"die stärkste Kombination im Heimmarkt — {radius:g} km um {center}"
        ),
        confidence=confidence,
        confidence_dots=_CONFIDENCE_DOTS[confidence],
        chapters=chapters,
        home_matrix=home_matrix,
        anchors=anchors,
        data_age_days=data_age_days,
    )
```

Hinweis: Kapitel-Nummern sind fortlaufend (`01`, `02`, dann `03` für Alternative ODER Risiken) — Titel sind das stabile Merkmal, nicht die Nummer. Falls `_size_klartext` nicht importierbar ist (Unterstrich-Konvention), den Import trotzdem nutzen — gleiche Package, bewusste Wiederverwendung.

- [ ] **Step 4: Grün** — Run: `uv run pytest tests/test_memo.py -v` → alle PASS.

- [ ] **Step 5: Commit**

```bash
git add airbi/insights/memo.py tests/test_memo.py
git commit -m "feat(memo): Kapitel-Generator build_memo + Jargon-Vertrag auf Memo-Texte"
```

---

### Task 5: Orchestrierung `compute_memo` + Route

**Files:**
- Modify: `airbi/insights/memo.py`
- Modify: `airbi/web/routes.py`
- Test: `tests/test_memo.py`

- [ ] **Step 1: Failing Test** — in `tests/test_memo.py`:

```python
from airbi.insights.memo import compute_memo


def test_compute_memo_uses_home_radius_and_config_anchors(db_session):
    cfg = SearchConfig(
        name="Memo-E2E-Test", city_slug="lisboa",
        center_lat=38.7390, center_lng=-9.1044,
        band_radii_km=[1, 2, 3], home_radius_km=2.0,
        comparison_markets=[
            {"name": "Alfama/Graça", "lat": 38.714, "lng": -9.128, "radius_km": 1.2},
        ],
    )
    db_session.add(cfg)
    db_session.flush()
    run = CrawlRun(search_config_id=cfg.id, status="completed")
    db_session.add(run)
    db_session.flush()
    # 4 Listings im Heimmarkt (~Zielobjekt), damit eine Best-Cell entsteht:
    for i in range(4):
        listing = _mk_listing(db_session, f"e{i}", 38.7390 + i * 0.0005, -9.1044)
        db_session.add(Snapshot(listing_id=listing.id, crawl_run_id=run.id,
                                price=Decimal("100"), review_count=30))
    db_session.flush()

    memo = compute_memo(db_session, cfg, run)
    assert memo.home_radius_km == 2.0
    assert memo.verdict_size_label is not None
    assert [a.name for a in memo.anchors] == ["Alfama/Graça"]


def test_compute_memo_falls_back_to_smallest_band_radius(db_session):
    cfg = SearchConfig(name="Memo-Fallback-Test", city_slug="lisboa",
                       center_lat=38.7390, center_lng=-9.1044,
                       band_radii_km=[3, 1, 5])
    db_session.add(cfg)
    db_session.flush()
    run = CrawlRun(search_config_id=cfg.id, status="completed")
    db_session.add(run)
    db_session.flush()
    memo = compute_memo(db_session, cfg, run)
    assert memo.home_radius_km == 1.0
    assert memo.anchors == []
```

- [ ] **Step 2: Rot** — Run: `uv run pytest tests/test_memo.py -k compute_memo -v` → FAIL.

- [ ] **Step 3: Implementierung** — in `airbi/insights/memo.py`:

```python
from datetime import datetime

from airbi.insights.segment_matrix import compute_segment_matrix


def _data_age_days(crawl_run: CrawlRun) -> int | None:
    if crawl_run.started_at is None:
        return None
    started = crawl_run.started_at
    now = datetime.now(started.tzinfo) if started.tzinfo else datetime.now()
    return max(0, (now.date() - started.date()).days)


def compute_memo(
    session: Session, search_config: SearchConfig, crawl_run: CrawlRun
) -> Memo:
    """Memo für eine SearchConfig: Heimmarkt-Matrix + Anker + Kapitel."""
    home_radius = search_config.home_radius_km or min(
        search_config.band_radii_km or [2.0]
    )
    home_matrix = compute_segment_matrix(
        session, search_config, float(home_radius), crawl_run
    )
    anchors = [
        compute_anchor_stats(
            session, search_config, crawl_run, market, home_matrix.best_cell
        )
        for market in (search_config.comparison_markets or [])
    ]
    return build_memo(
        home_matrix,
        anchors,
        data_age_days=_data_age_days(crawl_run),
        al_zone_status=search_config.al_zone_status,
    )
```

- [ ] **Step 4: Route erweitern** — in `airbi/web/routes.py`:

Import ergänzen:
```python
from airbi.insights.memo import Memo, compute_memo
```

Im `dashboard`-Handler (`routes.py:94-128`): nach der `matrices`-Berechnung
```python
    memo: Memo | None = (
        compute_memo(session, search_config, completed_run)
        if completed_run is not None else None
    )
```
und `"memo": memo,` in BEIDE TemplateResponse-Kontexte des Handlers aufnehmen (im `search_config is None`-Zweig `"memo": None`).

Der `/matrix`-Partial-Handler bleibt unverändert — er bedient künftig nur noch den Anhang (Umkreis-Umschalter).

- [ ] **Step 5: Grün** — Run: `uv run pytest tests/test_memo.py tests/test_web.py -v`. `test_memo.py` PASS; `test_web.py` darf hier noch NICHT brechen (Template nutzt `memo` noch nicht). Falls `test_web.py` rot ist: Ursache prüfen, nicht überspringen.

- [ ] **Step 6: Commit**

```bash
git add airbi/insights/memo.py airbi/web/routes.py tests/test_memo.py
git commit -m "feat(memo): compute_memo-Orchestrierung + Memo im Dashboard-Kontext"
```

---

### Task 6: Templates — Memo-UI (Editorial) + Anhang

**Files:**
- Create: `airbi/web/templates/_memo.html`
- Modify: `airbi/web/templates/dashboard.html`
- Modify: `airbi/web/templates/_matrix_region.html`
- Test: `tests/test_web.py`

- [ ] **Step 1: `_memo.html` anlegen** (Editorial-Stil, Spec §5 — Urteil, Kapitel mit Chips, Anhang-Rahmen):

```html
{% if memo is none %}
  <div class="rounded-lg border border-slate-200 bg-white p-6 text-slate-500">
    Noch keine Daten. Das Memo erscheint, sobald der erste Datenstand vorliegt.
  </div>
{% elif memo.verdict_size_label is none %}
  <section class="rounded-2xl border border-slate-200 bg-white px-8 py-8">
    <div class="text-[10px] uppercase tracking-[0.14em] text-slate-400 mb-2">Urteil</div>
    <h2 class="text-2xl font-semibold text-slate-900">Datenbasis zu dünn</h2>
    <p class="mt-2 text-sm text-slate-600">{{ memo.verdict_subline }}</p>
  </section>
{% else %}
  <article class="rounded-2xl border border-slate-200 bg-white px-8 py-8 sm:px-10 sm:py-9">

    {# ---------- Urteil ---------- #}
    <header class="border-b border-slate-100 pb-6 mb-7">
      <div class="text-[10px] uppercase tracking-[0.14em] text-slate-400 mb-2">
        Investment-Memo · {{ memo.center_label or "Zielobjekt" }}
      </div>
      <h2 class="text-3xl sm:text-[32px] font-bold tracking-tight text-slate-900 leading-tight">
        {{ memo.verdict_size_label }} · {{ memo.verdict_luxury_class }}.
      </h2>
      <p class="mt-1.5 text-sm text-slate-500">{{ memo.verdict_subline }}</p>
      <p class="mt-3 text-[13px] text-slate-600">
        Vertrauen:
        <span class="font-semibold text-amber-700">
          {% for i in range(memo.confidence_dots) %}●{% endfor %}{% for i in range(3 - memo.confidence_dots) %}○{% endfor %}
          {{ memo.confidence }}</span>{% if memo.confidence != "belastbar" %} — Verlaufsdaten bauen sich auf{% endif %}
      </p>
    </header>

    {# ---------- Kapitel ---------- #}
    <div class="space-y-7">
      {% for ch in memo.chapters %}
        <section>
          <div class="text-[11px] font-bold uppercase tracking-[0.1em] text-slate-400 mb-2">
            {{ ch.number }} — {{ ch.title }}
          </div>
          <p class="text-sm leading-[1.7] text-slate-800">
            {% for f in ch.fragments %}
              {%- if f.kind == "chip" -%}
                <span class="inline-block bg-emerald-50 text-emerald-700 font-semibold px-2 py-0.5 rounded-full text-[13px] align-baseline">{{ f.text }}</span>
              {%- elif f.kind == "chip_muted" -%}
                <span class="inline-block bg-slate-100 text-slate-700 px-2 py-0.5 rounded-full text-[13px] align-baseline">{{ f.text }}</span>
              {%- else -%}
                {{ f.text }}
              {%- endif %}
            {% endfor %}
          </p>
        </section>
      {% endfor %}
    </div>
  </article>
{% endif %}
```

- [ ] **Step 2: `_matrix_region.html` auf Anhang reduzieren**

Entfernen (Zeilen-Bereiche im aktuellen Stand): Kernthesen-Sektion (Z. 26–43), Hero (Z. 45–89), Pionier-Strip (Z. 91–113), Investment-Brief (Z. 115–166), Chancen-Segmente (Z. 229–332). Ebenso die zugehörigen `{% set %}`-Variablen am Kopf, die nur diese Blöcke brauchten (`show_gap`; `has_best`/`bsize`/`blux`/`bcell` bleiben — die Marktübersicht-Tabelle markiert die Empfehlung weiter mit Ring, und Top-Apartments nutzt sie im Untertitel).

Behalten: Marktübersicht-`<details>` (Heatmap-Tabelle), Marktkarte, Top-Apartments — unverändert.

- [ ] **Step 3: `dashboard.html` umbauen**

1. Nach dem Header (`</header>`, Z. 33) das Memo einfügen:
```html
    <section class="mb-6">
      {% include "_memo.html" %}
    </section>
```
2. Den Umkreis-Schalter-Block (Z. 35–63) und das zugehörige `<script>` (Z. 64–81) in ein `<details>` „Anhang" verschieben, das auch die Matrix-Region umschließt:
```html
    <details class="group">
      <summary class="cursor-pointer list-none flex items-center justify-between rounded-lg border border-slate-200 bg-white px-5 py-3 text-sm font-medium text-slate-700 hover:bg-slate-50">
        <span>Anhang — Marktübersicht, Karte und Apartments im Detail</span>
        <span class="text-base group-open:rotate-180 transition-transform">▾</span>
      </summary>
      <div class="mt-4">
        {# Umkreis-Schalter (hierher verschoben, Beschriftung angepasst): #}
        ...bisheriger Schalter-Block, Text "wechselt die gesamte Auswertung unten"
           ersetzt durch "wechselt die Detail-Ansichten unten — das Memo oben
           basiert immer auf dem Heimmarkt"...
        <section id="matrix-region">
          {% include "_matrix_region.html" %}
        </section>
      </div>
    </details>
```
Das `<script>` für die Button-Optik bleibt funktional unverändert (nur mit verschieben).

- [ ] **Step 4: `test_web.py` anpassen**

Run: `uv run pytest tests/test_web.py -v` und jede rote Assertion nach dieser Tabelle umstellen (Tests lesen, gezielt anpassen — keine Tests löschen, deren Gegenstand weiterlebt):

| Alte Erwartung (Beispiele) | Neu |
|---|---|
| Hero-Text „Empfehlung" / „attraktivste Kombination" | Urteils-Header: `"Investment-Memo"` und `" · "`-Segment-Zeile |
| „Kernthesen" | `"01 — Der Markt vor Ort"` (Kapitel-Header) |
| „Investment-Brief" / Methodik-Text | Risiko-Kapitel: `"Was dagegen spricht"` und `"Indikator"` |
| „Andere Chancen-Segmente" | entfällt ersatzlos — Assertion streichen, Test ggf. auf Anhang-Inhalt („Marktübersicht") umwidmen |
| „Datenbasis zu dünn"-Hero | bleibt: `"Datenbasis zu dünn"` jetzt aus `_memo.html` |

Neuen Test ergänzen:
```python
def test_dashboard_renders_memo_with_anchor_chips(client_with_data):
    """Voraussetzung: die bestehende Daten-Fixture um comparison_markets
    auf der SearchConfig erweitern (Alfama/Graça wie in test_memo.py)."""
    resp = client_with_data.get("/")
    assert resp.status_code == 200
    assert "Investment-Memo" in resp.text
    assert "Wo die Nachfrage hinläuft" in resp.text
```
(`client_with_data`: an die tatsächliche Fixture-Benennung in `test_web.py` anpassen — die Datei hat bereits einen Client mit befüllter DB; deren Muster folgen.)

- [ ] **Step 5: Volle Suite grün** — Run: `uv run pytest` → alle PASS (test_segment_matrix bleibt unberührt grün, da der Generator erst in Task 7 fällt).

- [ ] **Step 6: Commit**

```bash
git add airbi/web/templates/ tests/test_web.py
git commit -m "feat(memo): Editorial-Memo-UI ersetzt Block-Stapel; Matrix/Karte/Apartments in Anhang"
```

---

### Task 7: Kernthesen-Generator entfernen

**Files:**
- Modify: `airbi/insights/segment_matrix.py`
- Modify: `tests/test_segment_matrix.py`

- [ ] **Step 1: Nutzung verifizieren**

```bash
grep -rn "kernthesen\|Kernthese\|_translate_amenity\|_AMENITY_DE\|_is_distinctive_amenity\|_GENERIC_AMENITY_TOKENS" airbi/ --include="*.py" --include="*.html"
```
Expected: Treffer nur noch in `airbi/insights/segment_matrix.py` (Definitionen + interner Aufruf). Falls ein Template oder Modul außerhalb noch zugreift: STOPP, als BLOCKED melden (Task 6 war dann unvollständig).

- [ ] **Step 2: Entfernen** — in `airbi/insights/segment_matrix.py`:
- Dataclass `Kernthese`, Feld `SegmentMatrix.kernthesen`, Funktionen `_build_kernthesen`, `_kernthese_label`, `_translate_amenity`, `_is_distinctive_amenity` sowie die Konstanten `_AMENITY_DE` und `_GENERIC_AMENITY_TOKENS` löschen — sofern Step 1 bestätigt, dass nur der Kernthesen-Pfad sie nutzt (sonst nur den Kernthesen-Pfad entfernen und Helfer behalten).
- Den Aufruf von `_build_kernthesen` in `build_segment_matrix` entfernen.

- [ ] **Step 3: Tests bereinigen** — in `tests/test_segment_matrix.py`: alle `test_kernthesen_*`-Tests und den `Kernthese`-Import löschen. Der Jargon-Vertrag lebt seit Task 4 in `tests/test_memo.py::test_memo_texts_have_no_internal_jargon` weiter.

- [ ] **Step 4: Volle Suite grün** — Run: `uv run pytest` → alle PASS.

- [ ] **Step 5: Commit**

```bash
git add airbi/insights/segment_matrix.py tests/test_segment_matrix.py
git commit -m "refactor(memo): Kernthesen-Generator entfernt — Memo-Kapitel übernehmen"
```

---

### Task 8: Marvila-Config befüllen + Betriebs-Doku

**Files:**
- Modify: `docs/DEPLOYMENT.md`

- [ ] **Step 1: Lokale Config setzen**

```bash
PGPASSWORD=airbi /opt/homebrew/opt/postgresql@16/bin/psql -U airbi -d airbi -c "
UPDATE search_config SET
  home_radius_km = 2.0,
  comparison_markets = '[
    {\"name\": \"Alfama/Graça\", \"lat\": 38.714, \"lng\": -9.128, \"radius_km\": 1.2},
    {\"name\": \"Parque das Nações\", \"lat\": 38.768, \"lng\": -9.094, \"radius_km\": 1.5}
  ]'::json
WHERE name = 'Marvila Slice 1';"
```
Expected: `UPDATE 1`.

- [ ] **Step 2: DEPLOYMENT.md ergänzen** — im Abschnitt „## Daten aktualisieren", nach dem bestehenden „Einmalig nach Migration `b2c3d4e5f6a7`"-Block, neuen Block einfügen:

```markdown
**Einmalig nach Migration `d4e5f6a7b8c9`** — Memo-Felder der Config setzen
(auf dem Server identisch ausführen; bis dahin rendert das Memo mit dem
kleinsten Band-Radius und ohne Vergleichsanker):
```sql
UPDATE search_config SET
  home_radius_km = 2.0,
  comparison_markets = '[
    {"name": "Alfama/Graça", "lat": 38.714, "lng": -9.128, "radius_km": 1.2},
    {"name": "Parque das Nações", "lat": 38.768, "lng": -9.094, "radius_km": 1.5}
  ]'::json
WHERE name = 'Marvila Slice 1';
```
```

(Hinweis: Der Daten-Uhr-Sync repliziert `search_config` mit — nach dem ersten Sync nach diesem UPDATE ist die Prod-Config automatisch aktuell; das Server-UPDATE ist nur nötig, wenn das Deployment VOR dem nächsten Sync passiert.)

- [ ] **Step 3: Commit**

```bash
git add docs/DEPLOYMENT.md
git commit -m "docs(memo): Config-UPDATE für Memo-Felder dokumentiert + lokal gesetzt"
```

---

### Task 9: End-zu-End-Verifikation gegen echte Daten

**Files:** keine Änderungen — Verifikationstask.

- [ ] **Step 1: Volle Test-Suite** — Run: `uv run pytest` → alle PASS.

- [ ] **Step 2: Dashboard gegen die echte DB rendern**

```bash
uv run airbi web --host 127.0.0.1 --port 8765 &
sleep 3
curl -s "http://127.0.0.1:8765/" -o /tmp/memo-smoke.html
kill %1
grep -c "Investment-Memo" /tmp/memo-smoke.html
grep -o "Alfama/Graça [0-9]* Apartments" /tmp/memo-smoke.html | head -2
grep -o "0[0-9] — [A-Za-zÄÖÜäöüß ]*" /tmp/memo-smoke.html | head -6
```
Expected: mindestens 1× „Investment-Memo"; ein Alfama-Dichte-Chip mit plausibler Zahl (dreistellig); Kapitel-Header „01 — Der Markt vor Ort", „02 — Wo die Nachfrage hinläuft", „Was dagegen spricht".

- [ ] **Step 3: Plausibilität der Anker-Werte sichten** (Spec §9 Open Loop): die gegrepten Zahlen kurz bewerten — Alfama/Graça muss deutlich dichter sein als der Heimmarkt; wenn nicht (z. B. 0 Apartments), Anker-Koordinaten/Radius gegen die Karte prüfen und als Concern berichten, nicht stillschweigend akzeptieren.

- [ ] **Step 4: Kein Commit** — Ergebnis an den Controller berichten (Zahlen + Auffälligkeiten).
