# AirBI Slice 1 — Plan 3: Insight & Dashboard — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Die Segment-Matrix-Insight bauen, in einem schlanken FastAPI/HTMX/Tailwind-Dashboard rendern und damit den Acceptance-Test aus Briefing §12 / Spec §13 für den Marvila-Durchstich erfüllen.

**Architecture:** Drei klar getrennte Schichten. (1) **Pure Insight** — `build_segment_matrix(rows, config)` als reine Funktion, ohne DB/HTTP, vollständig gegen handgebaute `ListingRow`-Fixtures testbar; baut die 4×4-Matrix (Größe × `price_tier`), markiert dünne Zellen, formuliert einen Empfehlungssatz und wählt Top-Performer je Größenklasse. (2) **DB-Anbindung** — `compute_segment_matrix(session, …)` zieht die letzten Snapshots eines `CrawlRun` für einen Bezirk und ruft den Pure Builder. (3) **Web** — FastAPI-App mit Jinja2-Templates, HTMX für den Bezirksfilter, Tailwind v4 als kompiliertes Stylesheet via Standalone-CLI-Binary. Der Bezirksfilter (Marvila / Beato / beide) tauscht nur die Matrix-Region per HTMX; im „beide"-Modus stehen zwei Matrizen nebeneinander, jede in ihrem eigenen Bezirks-Kohort gerechnet.

**Tech Stack:** Python ≥3.11, FastAPI, Uvicorn, Jinja2, HTMX (CDN), Tailwind CSS v4 (Standalone-CLI-Binary), pytest, FastAPI `TestClient` (via `httpx`).

**Bezug:** Umsetzung von `docs/superpowers/specs/2026-05-21-airbi-slice1-marvila-design.md` §9 (Segment-Matrix), §10 (Dashboard) und §13 (Acceptance-Kriterien). Baut auf Plan 1 (`airbi/db/`, `airbi/classification/`, `airbi/geo/`) und Plan 2 (`airbi/scraper/`, `airbi/cli.py`) auf.

---

## Voraussetzungen

- Plan 1 und Plan 2 in `main` gemerged. Lokale `airbi`-DB existiert und ist auf `head` migriert.
- Wenn ein echter `CrawlRun` mit Daten gewünscht ist (für Task 10): `uv run airbi crawl --config "Marvila Slice 1"` läuft auf dem Dev-Rechner durch.
- `uv` auf dem PATH. Worktree/Feature-Branch über `superpowers:using-git-worktrees`.

## Wichtige Hinweise

- **Reine Schicht zuerst.** Tasks 2 + 3 schreiben die komplette Insight als reine Funktion gegen `ListingRow`-Fixtures. DB und Web kommen erst danach — so bleibt die Kernlogik regressionsfest, ohne dass Snapshot- oder Template-Geräusch das Bild verfälscht.
- **`price_tier` immer im Bezirks-Kohort.** Der Pure Builder bekommt nur die Listings **eines** Bezirks; daraus wird der Preis-Kohort gebildet. Die „beide"-Ansicht ruft den Builder zweimal — die `price_tier`-Semantik bleibt damit immer „innerhalb des Bezirks" (Spec §5.5/§8).
- **Tailwind v4 ohne Build-Step-Toolchain.** Standalone-CLI-Binary, keine `tailwind.config.js`, CSS-First-Konfiguration mit `@import "tailwindcss";` und `@source`. Der Tailwind-Scanner liest **Templates**, keine Python-Strings — alle Farbskala-Klassen müssen literal im Jinja2-Template stehen (Schleifen über vorgegebene Listen sind ok, dynamisch zusammengesetzte Klassennamen wie `bg-emerald-{{n}}00` nicht).
- **Test-DB-Trennung.** Die Web-Routen hängen über eine FastAPI-Dependency `get_session` an der DB. Tests überschreiben diese Dependency mit der `db_session`-Fixture (Test-DB, Transaktions-Rollback) — kein Eingriff in `conftest.py`.

## Dateistruktur (in diesem Plan erstellt oder modifiziert)

| Datei | Status | Verantwortung |
|---|---|---|
| `pyproject.toml` | ✏️ T1 | `fastapi`/`uvicorn`/`jinja2`-Deps + `httpx` in dev |
| `airbi/insights/__init__.py` | T1 | Paket-Marker |
| `airbi/insights/segment_matrix.py` | T1/T2/T3/T4 | Dataclasses (T1) + Pure Builder (T2/T3) + DB-Anbindung (T4) |
| `tests/test_segment_matrix.py` | T1/T2/T3/T4 | Tests für Pure Builder + DB-Funktion |
| `airbi/web/__init__.py` | T5 | Paket-Marker |
| `airbi/web/app.py` | T5 | `create_app`, Module-Level `app`, Static-/Templates-Mount, `/health` |
| `airbi/web/routes.py` | T5/T7/T8 | `get_session`-Dep, Router; Dashboard- und Matrix-Routen |
| `airbi/web/templates/base.html` | T5/T6 | Layout, Tailwind-CSS-Link, HTMX-CDN |
| `airbi/web/templates/dashboard.html` | T7 | Haupt-Dashboard-Seite |
| `airbi/web/templates/_matrix_region.html` | T7/T8 | HTMX-Partial: Matrix + Empfehlung + Top-Performer (1 oder 2 Bezirke) |
| `airbi/web/tailwind.src.css` | T6 | Tailwind-Eingangs-CSS |
| `airbi/web/static/app.css` | T6 | kompiliertes Tailwind-Stylesheet (committet) |
| `.gitignore` | ✏️ T6 | `tailwindcss`-Binary ausschließen |
| `airbi/cli.py` | ✏️ T9 | Subcommand `web` |
| `tests/test_web.py` | T5/T7/T8 | TestClient-Smoke + Dashboard- und Filter-Tests |

---

## Task 1: Insights-Paket, Web-Dependencies & Datenkontrakt

**Files:**
- Modify: `pyproject.toml`
- Create: `airbi/insights/__init__.py`
- Create: `airbi/insights/segment_matrix.py`
- Test: `tests/test_segment_matrix.py`

- [ ] **Step 1: `pyproject.toml` um Web- und Dev-Deps ergänzen**

`dependencies = [...]` durch die folgende Liste ersetzen (Reihenfolge bewahren, neue Einträge unten):

```toml
dependencies = [
    "sqlalchemy>=2.0",
    "alembic>=1.13",
    "psycopg[binary]>=3.1",
    "shapely>=2.0",
    "pydantic-settings>=2.0",
    "playwright>=1.40",
    "fastapi>=0.110",
    "uvicorn[standard]>=0.27",
    "jinja2>=3.1",
]
```

Den Kommentar `# Plan 3 ergänzt hier fastapi/uvicorn/jinja2.` entfernen (er ist mit diesem Schritt eingelöst).

`[dependency-groups]` so anpassen:

```toml
[dependency-groups]
dev = [
    "pytest>=8.0",
    "pytest-cov>=5.0",
    "httpx>=0.27",
]
```

- [ ] **Step 2: Lockfile aktualisieren und Imports verifizieren**

Run: `uv sync && uv run python -c "import fastapi, uvicorn, jinja2, httpx; print('ok')"`
Expected: gibt `ok` aus, kein Fehler.

- [ ] **Step 3: Paket anlegen**

Create `airbi/insights/__init__.py` — leer.

- [ ] **Step 4: Datenkontrakt in `airbi/insights/segment_matrix.py` schreiben**

```python
"""Segment-Matrix-Insight (Spec §9).

Drei Schichten:
- Datacontainer: ListingRow (Eingabe), Cell / TopPerformer / SegmentMatrix
  (Ausgabe).
- Reiner Builder: build_segment_matrix(rows, config) — keine DB, kein HTTP.
- DB-Anbindung: compute_segment_matrix(session, ...) zieht die Daten und
  ruft den reinen Builder. Lebt im selben Modul, ist aber sauber getrennt.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

# Reihenfolge bestimmt die Render-Reihenfolge in der Matrix.
SIZE_CLASSES: list[str] = ["Studio", "1BR", "2BR", "3BR+"]
PRICE_TIERS: list[str] = ["Budget", "Mid", "Premium", "Luxury"]

# Defaults für die Insight-spezifischen Knöpfe in SearchConfig.classification_config.
DEFAULT_INSIGHT_CONFIG: dict = {
    "min_sample": 3,        # Zellen mit weniger Listings gelten als "zu dünn".
    "review_rate": 0.40,    # Anteil bewertender Gäste (Briefing §3, ~30-50 %).
    "top_performers_per_segment": 2,
}


@dataclass
class ListingRow:
    """Ein Listing + sein Snapshot aus einem CrawlRun, bereits einem Bezirk
    zugeordnet. Der reine Builder konsumiert nur diese Records."""

    airbnb_id: str
    title: str | None
    url: str | None
    size_class: str            # aus airbi.classification.size.size_class
    price: Decimal | None      # Nacht-Preis aus dem Snapshot
    review_count: int
    rating: float | None


@dataclass
class Cell:
    """Eine Zelle der Matrix (eine Kombination Größe × price_tier)."""

    size_class: str
    price_tier: str
    n: int = 0                         # Wettbewerbsdichte
    review_sum: int = 0                # Nachfrage-Proxy R
    score: float | None = None         # R / N = Ø Reviews je Listing
    adr: Decimal | None = None         # Median-Nacht-Preis der Zelle
    is_thin: bool = True               # N < min_sample
    heat: int = 0                      # 0-4, relativ zum besten nicht-dünnen Score


@dataclass
class TopPerformer:
    airbnb_id: str
    title: str | None
    url: str | None
    size_class: str
    price_tier: str
    review_count: int
    rating: float | None


@dataclass
class SegmentMatrix:
    """Vollständiges Insight-Ergebnis für genau einen Bezirk + einen CrawlRun."""

    district_slug: str
    crawl_run_id: int | None
    size_classes: list[str] = field(default_factory=lambda: list(SIZE_CLASSES))
    price_tiers: list[str] = field(default_factory=lambda: list(PRICE_TIERS))
    cells: dict[tuple[str, str], Cell] = field(default_factory=dict)
    best_cell: tuple[str, str] | None = None
    recommendation: str = ""
    top_performers: list[TopPerformer] = field(default_factory=list)
    listing_count: int = 0
    review_rate: float = DEFAULT_INSIGHT_CONFIG["review_rate"]
    min_sample: int = DEFAULT_INSIGHT_CONFIG["min_sample"]

    def cell(self, size_class: str, price_tier: str) -> Cell:
        """Template-freundlicher Zugriff (Jinja kann keine Tuple-Subscripts)."""
        return self.cells[(size_class, price_tier)]
```

- [ ] **Step 5: Smoke-Test in `tests/test_segment_matrix.py` schreiben**

```python
from decimal import Decimal

from airbi.insights.segment_matrix import (
    PRICE_TIERS,
    SIZE_CLASSES,
    Cell,
    ListingRow,
    SegmentMatrix,
    TopPerformer,
)


def test_dataclasses_construct_with_minimal_args():
    row = ListingRow(
        airbnb_id="1", title="T", url="u", size_class="1BR",
        price=Decimal("100"), review_count=5, rating=4.7,
    )
    assert row.airbnb_id == "1"

    cell = Cell(size_class="1BR", price_tier="Mid")
    assert cell.n == 0 and cell.is_thin is True and cell.heat == 0

    perf = TopPerformer(
        airbnb_id="1", title="T", url="u", size_class="1BR",
        price_tier="Mid", review_count=5, rating=4.7,
    )
    assert perf.size_class == "1BR"


def test_matrix_axes_have_expected_order():
    assert SIZE_CLASSES == ["Studio", "1BR", "2BR", "3BR+"]
    assert PRICE_TIERS == ["Budget", "Mid", "Premium", "Luxury"]


def test_segment_matrix_cell_lookup_returns_stored_cell():
    matrix = SegmentMatrix(district_slug="marvila", crawl_run_id=1)
    cell = Cell(size_class="1BR", price_tier="Premium", n=3, is_thin=False)
    matrix.cells[("1BR", "Premium")] = cell
    assert matrix.cell("1BR", "Premium") is cell
```

- [ ] **Step 6: Tests laufen lassen, Erfolg verifizieren**

Run: `uv run pytest tests/test_segment_matrix.py -v`
Expected: PASS — alle 3 Smoke-Tests grün.

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml uv.lock airbi/insights/ tests/test_segment_matrix.py
git commit -m "chore: Insights-Paket, Web-Dependencies und Insight-Datenkontrakt"
```

---

## Task 2: Pure Builder — `build_segment_matrix` (Zellen-Aggregation)

**Files:**
- Modify: `airbi/insights/segment_matrix.py`
- Modify: `tests/test_segment_matrix.py`

TDD gegen handgebaute `ListingRow`-Listen. Dieser Task baut **nur** die Zell-Aggregation + `best_cell` + `heat`. Empfehlungstext und Top-Performer kommen in Task 3.

- [ ] **Step 1: Failing Tests in `tests/test_segment_matrix.py` ergänzen**

Importzeile oben erweitern (zusätzlich zum bestehenden Smoke-Import):

```python
from airbi.insights.segment_matrix import build_segment_matrix
```

Am Dateiende anhängen:

```python
def _row(airbnb_id, size_class, price, review_count, rating=4.5):
    return ListingRow(
        airbnb_id=airbnb_id, title=f"L{airbnb_id}", url=f"https://x/{airbnb_id}",
        size_class=size_class,
        price=Decimal(str(price)) if price is not None else None,
        review_count=review_count, rating=rating,
    )


def test_builder_returns_full_4x4_grid_with_district_and_run_id():
    matrix = build_segment_matrix([], config={}, district_slug="marvila", crawl_run_id=42)
    assert matrix.district_slug == "marvila"
    assert matrix.crawl_run_id == 42
    assert len(matrix.cells) == 16
    for size in SIZE_CLASSES:
        for tier in PRICE_TIERS:
            assert (size, tier) in matrix.cells


def test_builder_counts_listings_per_cell_and_sums_reviews():
    # 5er-Cohort [60, 65, 90, 200, 300]: ranks 0.0 / 0.2 / 0.4 / 0.6 / 0.8.
    # 60 und 65 -> Budget (rank < 0.25), Rest verteilt sich.
    rows = [
        _row("1", "1BR", 60, 10),   # Budget (rank 0.0)
        _row("2", "1BR", 65, 20),   # Budget (rank 0.2)
        _row("3", "1BR", 300, 50),  # Premium (rank 0.8)
        _row("4", "1BR", 200, 7),   # Mid (rank 0.6) — Kohorten-Anker
        _row("5", "2BR", 90, 5),    # Mid (rank 0.4)
    ]
    matrix = build_segment_matrix(rows, config={}, district_slug="m", crawl_run_id=1)
    budget_1br = matrix.cell("1BR", "Budget")
    assert budget_1br.n == 2
    assert budget_1br.review_sum == 30
    assert budget_1br.score == 15.0  # 30 / 2


def test_builder_median_adr_per_cell():
    # Cohort [60, 100, 200]: ranks 0.0 / 0.333 / 0.667.
    # 100 und 200 landen beide in Mid -> Median = (100+200)/2 = 150.
    rows = [
        _row("0", "1BR", 60, 5),    # Budget — Kohorten-Anker
        _row("1", "1BR", 100, 5),   # Mid (rank 1/3)
        _row("2", "1BR", 200, 5),   # Mid (rank 2/3)
    ]
    matrix = build_segment_matrix(rows, config={}, district_slug="m", crawl_run_id=1)
    mid_cell = matrix.cell("1BR", "Mid")
    assert mid_cell.n == 2
    assert mid_cell.adr == Decimal("150")


def test_builder_marks_cells_below_min_sample_as_thin():
    # Identischer Preis -> rank 0.0 -> beide in Budget.
    rows = [_row("1", "1BR", 100, 5), _row("2", "1BR", 100, 7)]
    matrix = build_segment_matrix(rows, config={"min_sample": 3},
                                  district_slug="m", crawl_run_id=1)
    populated = next(c for c in matrix.cells.values() if c.n > 0)
    assert populated.n == 2
    assert populated.is_thin is True


def test_builder_skips_rows_with_unclassified_size_or_no_price():
    rows = [
        _row("1", "unclassified", 100, 5),
        _row("2", "1BR", None, 5),
        _row("3", "1BR", 100, 5),
    ]
    matrix = build_segment_matrix(rows, config={"min_sample": 1},
                                  district_slug="m", crawl_run_id=1)
    assert matrix.listing_count == 1
    assert sum(c.n for c in matrix.cells.values()) == 1


def test_builder_picks_best_cell_with_highest_score_above_min_sample():
    # Identischer Preis -> alle in (size, Budget). Höchster Score gewinnt.
    rows = [
        # Studio Budget: 3 Listings, je 20 Reviews -> score = 20.
        _row("a1", "Studio", 100, 20), _row("a2", "Studio", 100, 20), _row("a3", "Studio", 100, 20),
        # 1BR Budget: 3 Listings, je 50 Reviews -> score = 50  (Gewinner).
        _row("b1", "1BR", 100, 50), _row("b2", "1BR", 100, 50), _row("b3", "1BR", 100, 50),
        # 2BR Budget: nur 1 Listing mit 999 Reviews -> dünn, fliegt raus.
        _row("c1", "2BR", 100, 999),
    ]
    matrix = build_segment_matrix(rows, config={"min_sample": 3},
                                  district_slug="m", crawl_run_id=1)
    assert matrix.best_cell == ("1BR", "Budget")


def test_builder_returns_no_best_cell_when_all_cells_thin():
    rows = [_row("1", "1BR", 100, 5)]
    matrix = build_segment_matrix(rows, config={"min_sample": 3},
                                  district_slug="m", crawl_run_id=1)
    assert matrix.best_cell is None


def test_builder_heat_is_zero_for_empty_or_thin_cells():
    rows = [_row("1", "1BR", 100, 5)]
    matrix = build_segment_matrix(rows, config={"min_sample": 3},
                                  district_slug="m", crawl_run_id=1)
    for cell in matrix.cells.values():
        assert cell.heat == 0


def test_builder_heat_scales_1_to_4_for_eligible_cells():
    # Drei nicht-dünne Budget-Zellen mit aufsteigenden Scores: 1, 5, 20.
    # (Alle Preise gleich -> rank 0.0 -> Budget.)
    rows = []
    rows += [_row(f"s{i}", "Studio", 100, 1) for i in range(3)]    # score = 1
    rows += [_row(f"o{i}", "1BR", 100, 5) for i in range(3)]       # score = 5
    rows += [_row(f"t{i}", "2BR", 100, 20) for i in range(3)]      # score = 20 (Top)
    matrix = build_segment_matrix(rows, config={"min_sample": 3},
                                  district_slug="m", crawl_run_id=1)
    assert matrix.cell("2BR", "Budget").heat == 4
    assert 1 <= matrix.cell("Studio", "Budget").heat <= 4
    assert 1 <= matrix.cell("1BR", "Budget").heat <= 4
    assert matrix.cell("Studio", "Budget").heat < matrix.cell("2BR", "Budget").heat
```

- [ ] **Step 2: Tests laufen lassen, Fehlschlag verifizieren**

Run: `uv run pytest tests/test_segment_matrix.py -v`
Expected: FAIL — `ImportError` für `build_segment_matrix`.

- [ ] **Step 3: `build_segment_matrix` in `airbi/insights/segment_matrix.py` ergänzen**

Importe am Dateianfang erweitern:

```python
from statistics import median

from airbi.classification.price import price_tier as _price_tier
```

Am Dateiende anhängen:

```python
def _merge_config(config: dict | None) -> dict:
    return {**DEFAULT_INSIGHT_CONFIG, **(config or {})}


def _empty_grid() -> dict[tuple[str, str], Cell]:
    return {
        (size, tier): Cell(size_class=size, price_tier=tier)
        for size in SIZE_CLASSES
        for tier in PRICE_TIERS
    }


def build_segment_matrix(
    rows: list[ListingRow],
    *,
    config: dict | None,
    district_slug: str,
    crawl_run_id: int | None,
) -> SegmentMatrix:
    """Reine Aggregation der Segment-Matrix für genau einen Bezirk.

    - Verteilt jeden ListingRow auf eine (size_class, price_tier)-Zelle.
    - `price_tier` wird aus dem Preis-Kohort *dieser* rows berechnet (Spec
      §5.5/§8: immer innerhalb des Bezirks).
    - Zellen unter cfg['min_sample'] gelten als 'dünn' und scheiden aus der
      Best-Cell-Wahl aus.
    - `heat` 0-4 skaliert relativ zum besten nicht-dünnen Score.
    """
    cfg = _merge_config(config)
    cells = _empty_grid()
    cohort = [r.price for r in rows if r.price is not None]

    # Listings auf Zellen verteilen.
    cell_rows: dict[tuple[str, str], list[ListingRow]] = {}
    listing_count = 0
    for r in rows:
        if r.size_class not in SIZE_CLASSES:
            continue
        if r.price is None:
            continue
        tier = _price_tier(r.price, cohort, cfg)
        if tier not in PRICE_TIERS:
            continue
        cell_rows.setdefault((r.size_class, tier), []).append(r)
        listing_count += 1

    # Pro Zelle: N, R, Score, ADR, is_thin.
    min_sample = int(cfg["min_sample"])
    for key, group in cell_rows.items():
        cell = cells[key]
        cell.n = len(group)
        cell.review_sum = sum(r.review_count for r in group)
        cell.score = cell.review_sum / cell.n if cell.n else None
        prices = [r.price for r in group if r.price is not None]
        cell.adr = (
            Decimal(median(prices)).quantize(Decimal("1")) if prices else None
        )
        cell.is_thin = cell.n < min_sample

    # Best-Cell: höchster Score unter den nicht-dünnen Zellen.
    eligible = [
        (key, cell) for key, cell in cells.items()
        if not cell.is_thin and cell.score is not None
    ]
    best_cell = max(eligible, key=lambda kv: kv[1].score, default=(None, None))[0]

    # Heat 0-4 relativ zum besten nicht-dünnen Score.
    max_score = max((c.score for _, c in eligible), default=None)
    for cell in cells.values():
        if cell.is_thin or cell.score is None or not max_score:
            cell.heat = 0
        else:
            cell.heat = max(1, min(4, round(cell.score / max_score * 4)))

    return SegmentMatrix(
        district_slug=district_slug,
        crawl_run_id=crawl_run_id,
        cells=cells,
        best_cell=best_cell,
        listing_count=listing_count,
        review_rate=float(cfg["review_rate"]),
        min_sample=min_sample,
    )
```

Hinweis zum `median`-Aufruf: `statistics.median` liefert für eine `Decimal`-Liste ungerader Länge einen `Decimal`, für gerade Länge ein arithmetisches Mittel — wir umhüllen das Ergebnis defensiv mit `Decimal(...)` (akzeptiert beides) und runden auf ganze Euro.

- [ ] **Step 4: Tests laufen lassen, Erfolg verifizieren**

Run: `uv run pytest tests/test_segment_matrix.py -v`
Expected: PASS — alle Tests aus Task 1 + die 9 neuen Builder-Tests grün.

- [ ] **Step 5: Commit**

```bash
git add airbi/insights/segment_matrix.py tests/test_segment_matrix.py
git commit -m "feat: Pure Segment-Matrix-Builder (Aggregation, Best-Cell, Heat)"
```

---

## Task 3: Empfehlungstext & Top-Performer

**Files:**
- Modify: `airbi/insights/segment_matrix.py`
- Modify: `tests/test_segment_matrix.py`

Erweitert `build_segment_matrix` um die `recommendation` und `top_performers` (Spec §9). Die Heuristik bleibt bewusst einfach und über `DEFAULT_INSIGHT_CONFIG` justierbar.

- [ ] **Step 1: Failing Tests in `tests/test_segment_matrix.py` ergänzen**

Am Dateiende anhängen:

```python
def test_recommendation_names_district_size_tier_score_n_adr_and_proxy_note():
    # 3 identische 1BR-Listings -> Cohort = [100,100,100] -> rank(100) = 0.0
    # -> alle landen mit DEFAULT_PRICE_TIERS in der (1BR, Budget)-Zelle.
    # N=3 = min_sample -> nicht dünn -> Best-Cell = (1BR, Budget).
    rows = [_row(f"l{i}", "1BR", 100, review_count=80) for i in range(3)]
    matrix = build_segment_matrix(rows, config={"min_sample": 3},
                                  district_slug="marvila", crawl_run_id=1)
    rec = matrix.recommendation
    assert "Marvila" in rec
    assert "1BR" in rec
    assert "Budget" in rec           # Gewinner aus der Konstruktion
    assert "80" in rec               # Ø Reviews je Listing
    assert "3 Wettbewerber" in rec   # N = 3 Wettbewerber-Listings
    assert "€100" in rec             # Median-ADR
    assert "Proxy" in rec
    assert "40%" in rec              # review_rate * 100


def test_recommendation_falls_back_when_no_cell_meets_min_sample():
    rows = [_row("1", "1BR", 100, 5)]  # nur 1 Listing -> alle Zellen dünn
    matrix = build_segment_matrix(rows, config={"min_sample": 3},
                                  district_slug="beato", crawl_run_id=1)
    assert matrix.best_cell is None
    assert "Beato" in matrix.recommendation
    assert "zu dünn" in matrix.recommendation


def test_top_performers_grouped_by_size_class_sorted_by_review_count():
    rows = [
        _row("a", "1BR", 100, 5,  rating=4.5),
        _row("b", "1BR", 100, 90, rating=4.9),  # Top 1
        _row("c", "1BR", 100, 50, rating=4.7),  # Top 2
        _row("d", "2BR", 100, 30, rating=4.6),  # einziger 2BR
    ]
    matrix = build_segment_matrix(rows, config={"top_performers_per_segment": 2,
                                                "min_sample": 1},
                                  district_slug="m", crawl_run_id=1)
    perfs = matrix.top_performers
    # Reihenfolge: nach SIZE_CLASSES, innerhalb nach review_count desc.
    one_br = [p for p in perfs if p.size_class == "1BR"]
    assert [p.airbnb_id for p in one_br] == ["b", "c"]
    two_br = [p for p in perfs if p.size_class == "2BR"]
    assert [p.airbnb_id for p in two_br] == ["d"]
    # Reihenfolge gesamt: 1BR-Block kommt vor 2BR-Block.
    assert [p.size_class for p in perfs] == ["1BR", "1BR", "2BR"]


def test_top_performers_ignore_unclassified_size_class():
    rows = [
        _row("a", "unclassified", 100, 999),
        _row("b", "1BR", 100, 5),
    ]
    matrix = build_segment_matrix(rows, config={"min_sample": 1,
                                                "top_performers_per_segment": 2},
                                  district_slug="m", crawl_run_id=1)
    assert all(p.size_class in SIZE_CLASSES for p in matrix.top_performers)
    assert any(p.airbnb_id == "b" for p in matrix.top_performers)
    assert all(p.airbnb_id != "a" for p in matrix.top_performers)
```

- [ ] **Step 2: Tests laufen lassen, Fehlschlag verifizieren**

Run: `uv run pytest tests/test_segment_matrix.py -v`
Expected: FAIL — `recommendation` ist leer und `top_performers` ist `[]`.

- [ ] **Step 3: `build_segment_matrix` um Empfehlung und Top-Performer erweitern**

Vor `build_segment_matrix` (oder am Dateiende — Modulebene reicht) zwei reine Helfer ergänzen:

```python
def _district_label(slug: str) -> str:
    """Hübscher Anzeigename für einen Bezirks-Slug ('marvila' -> 'Marvila')."""
    return slug.replace("-", " ").replace("_", " ").title()


def _build_recommendation(matrix: SegmentMatrix) -> str:
    """Formuliert den Empfehlungssatz aus der gefüllten Matrix."""
    label = _district_label(matrix.district_slug)
    if matrix.best_cell is None:
        return (
            f"Für {label} liefert dieser Crawl noch keine Zelle mit mindestens "
            f"{matrix.min_sample} vergleichbaren Objekten — die Datenbasis ist "
            f"für eine belastbare Empfehlung zu dünn."
        )
    size, tier = matrix.best_cell
    cell = matrix.cell(size, tier)
    score = cell.score or 0.0
    adr = int(cell.adr) if cell.adr is not None else 0
    rate_pct = int(round(matrix.review_rate * 100))
    return (
        f"Für {label} ist {size}-{tier} am attraktivsten — Ø {score:.0f} "
        f"Reviews je Listing bei {cell.n} Wettbewerber-Listings, "
        f"Median-ADR €{adr}. Nachfrage ist ein Proxy aus Review-Count "
        f"(~{rate_pct}% der Gäste bewerten), keine gemessene Auslastung."
    )


def _pick_top_performers(
    rows_by_cell: dict[tuple[str, str], list[ListingRow]],
    per_segment: int,
) -> list[TopPerformer]:
    """Top-N je Größenklasse, sortiert nach review_count desc, dann rating desc."""
    by_size: dict[str, list[tuple[ListingRow, str]]] = {s: [] for s in SIZE_CLASSES}
    for (size, tier), group in rows_by_cell.items():
        for r in group:
            by_size[size].append((r, tier))

    result: list[TopPerformer] = []
    for size in SIZE_CLASSES:
        candidates = by_size[size]
        candidates.sort(
            key=lambda rt: (-rt[0].review_count, -(rt[0].rating or 0.0), rt[0].airbnb_id)
        )
        for r, tier in candidates[:per_segment]:
            result.append(
                TopPerformer(
                    airbnb_id=r.airbnb_id,
                    title=r.title,
                    url=r.url,
                    size_class=size,
                    price_tier=tier,
                    review_count=r.review_count,
                    rating=r.rating,
                )
            )
    return result
```

In `build_segment_matrix` **kurz vor dem `return`** den Empfehlungssatz und die Top-Performer-Liste setzen:

```python
    matrix = SegmentMatrix(
        district_slug=district_slug,
        crawl_run_id=crawl_run_id,
        cells=cells,
        best_cell=best_cell,
        listing_count=listing_count,
        review_rate=float(cfg["review_rate"]),
        min_sample=min_sample,
    )
    matrix.recommendation = _build_recommendation(matrix)
    matrix.top_performers = _pick_top_performers(
        cell_rows, int(cfg["top_performers_per_segment"])
    )
    return matrix
```

(Den bestehenden `return SegmentMatrix(...)`-Block aus Task 2 dadurch ersetzen.)

- [ ] **Step 4: Tests laufen lassen, Erfolg verifizieren**

Run: `uv run pytest tests/test_segment_matrix.py -v`
Expected: PASS — alle bisherigen + die 4 neuen Tests grün.

- [ ] **Step 5: Commit**

```bash
git add airbi/insights/segment_matrix.py tests/test_segment_matrix.py
git commit -m "feat: Segment-Matrix Empfehlungstext und Top-Performer"
```

---

## Task 4: DB-Anbindung — `compute_segment_matrix` & `latest_completed_run`

**Files:**
- Modify: `airbi/insights/segment_matrix.py`
- Modify: `tests/test_segment_matrix.py`

Die DB-Funktion zieht die `ListingRow`s für einen Bezirk + einen `CrawlRun` und delegiert an den reinen Builder.

- [ ] **Step 1: Failing Tests in `tests/test_segment_matrix.py` ergänzen**

Importzeile oben um die DB-Modelle und die neuen Funktionen erweitern:

```python
from airbi.db.models import CrawlRun, Listing, SearchConfig, Snapshot
from airbi.insights.segment_matrix import (
    compute_segment_matrix,
    latest_completed_run,
)
```

Am Dateiende anhängen:

```python
def _seed(db_session, *, district, size_class, price, reviews, airbnb_id, run):
    listing = Listing(
        airbnb_id=airbnb_id, city_slug="lisboa", district_slug=district,
        lat=38.74, lng=-9.10, property_type="Apartment",
        bedrooms=1, size_class=size_class, title=f"L{airbnb_id}",
        url=f"https://x/{airbnb_id}",
    )
    db_session.add(listing)
    db_session.flush()
    db_session.add(Snapshot(
        listing_id=listing.id, crawl_run_id=run.id,
        price=Decimal(str(price)), review_count=reviews, rating=4.7,
    ))


def _seed_run(db_session, *, status="completed"):
    cfg = SearchConfig(name=f"Cfg-{status}-{id(db_session)}",
                       district_slugs=["marvila", "beato"])
    run = CrawlRun(search_config=cfg, status=status)
    db_session.add(run)
    db_session.flush()
    return cfg, run


def test_latest_completed_run_returns_most_recent_completed(db_session):
    cfg, completed_old = _seed_run(db_session, status="completed")
    completed_new = CrawlRun(search_config=cfg, status="completed")
    failed = CrawlRun(search_config=cfg, status="failed")
    db_session.add_all([completed_new, failed])
    db_session.flush()
    latest = latest_completed_run(db_session, cfg)
    assert latest.id == completed_new.id


def test_latest_completed_run_returns_none_when_no_completed_run(db_session):
    cfg = SearchConfig(name="None", district_slugs=["marvila"])
    db_session.add(CrawlRun(search_config=cfg, status="failed"))
    db_session.flush()
    assert latest_completed_run(db_session, cfg) is None


def test_compute_segment_matrix_pulls_only_rows_for_district_and_run(db_session):
    cfg, run = _seed_run(db_session)
    # marvila: 3 1BR-Listings.
    for i, (p, rev) in enumerate([(80, 10), (90, 12), (100, 8)]):
        _seed(db_session, district="marvila", size_class="1BR",
              price=p, reviews=rev, airbnb_id=f"M{i}", run=run)
    # beato: 2 2BR-Listings (sollen NICHT auftauchen).
    for i, (p, rev) in enumerate([(150, 50), (160, 60)]):
        _seed(db_session, district="beato", size_class="2BR",
              price=p, reviews=rev, airbnb_id=f"B{i}", run=run)
    # Anderer Run: gehört nicht in dieses Ergebnis.
    other_run = CrawlRun(search_config=cfg, status="completed")
    db_session.add(other_run)
    db_session.flush()
    _seed(db_session, district="marvila", size_class="1BR",
          price=200, reviews=999, airbnb_id="OTHER", run=other_run)

    matrix = compute_segment_matrix(db_session, cfg, "marvila", run)
    assert matrix.listing_count == 3
    assert matrix.crawl_run_id == run.id
    assert matrix.district_slug == "marvila"


def test_compute_segment_matrix_respects_search_config_classification_config(db_session):
    cfg, run = _seed_run(db_session)
    cfg.classification_config = {"min_sample": 2}
    db_session.flush()
    # Zwei Listings mit demselben Preis -> selbe Zelle -> N = 2.
    for i, (p, rev) in enumerate([(100, 10), (100, 20)]):
        _seed(db_session, district="marvila", size_class="1BR",
              price=p, reviews=rev, airbnb_id=f"M{i}", run=run)
    matrix = compute_segment_matrix(db_session, cfg, "marvila", run)
    # min_sample=2 -> die Zelle mit 2 Listings ist gerade nicht mehr dünn
    # (mit dem Default 3 wäre sie es).
    populated = next(c for c in matrix.cells.values() if c.n > 0)
    assert populated.n == 2
    assert populated.is_thin is False
```

- [ ] **Step 2: Tests laufen lassen, Fehlschlag verifizieren**

Run: `uv run pytest tests/test_segment_matrix.py -v`
Expected: FAIL — `ImportError` für `compute_segment_matrix` und `latest_completed_run`.

- [ ] **Step 3: Funktionen in `airbi/insights/segment_matrix.py` ergänzen**

Importe am Dateianfang erweitern:

```python
from sqlalchemy import select
from sqlalchemy.orm import Session

from airbi.db.models import CrawlRun, Listing, SearchConfig, Snapshot
```

Am Dateiende anhängen:

```python
def latest_completed_run(
    session: Session, search_config: SearchConfig
) -> CrawlRun | None:
    """Letzter erfolgreich abgeschlossener CrawlRun einer SearchConfig (oder None)."""
    stmt = (
        select(CrawlRun)
        .where(CrawlRun.search_config_id == search_config.id)
        .where(CrawlRun.status == "completed")
        .order_by(CrawlRun.started_at.desc(), CrawlRun.id.desc())
        .limit(1)
    )
    return session.execute(stmt).scalar_one_or_none()


def compute_segment_matrix(
    session: Session,
    search_config: SearchConfig,
    district_slug: str,
    crawl_run: CrawlRun,
) -> SegmentMatrix:
    """Lädt die Listings + Snapshots aus crawl_run für einen Bezirk und ruft
    den reinen Builder."""
    # SessionLocal nutzt autoflush=False — Pending Writes der gleichen
    # Unit-of-Work müssen vor dem SELECT explizit sichtbar gemacht werden,
    # damit Tests/Routen, die direkt vor der Insight schreiben, das Ergebnis
    # auch lesen können.
    session.flush()
    stmt = (
        select(Listing, Snapshot)
        .join(Snapshot, Snapshot.listing_id == Listing.id)
        .where(Snapshot.crawl_run_id == crawl_run.id)
        .where(Listing.city_slug == search_config.city_slug)
        .where(Listing.district_slug == district_slug)
    )
    rows = [
        ListingRow(
            airbnb_id=listing.airbnb_id,
            title=listing.title,
            url=listing.url,
            size_class=listing.size_class or "unclassified",
            price=snap.price,
            review_count=snap.review_count or 0,
            rating=snap.rating,
        )
        for listing, snap in session.execute(stmt).all()
    ]
    return build_segment_matrix(
        rows,
        config=search_config.classification_config or {},
        district_slug=district_slug,
        crawl_run_id=crawl_run.id,
    )
```

- [ ] **Step 4: Tests laufen lassen, Erfolg verifizieren**

Run: `uv run pytest tests/test_segment_matrix.py -v`
Expected: PASS — alle Tests grün (Smoke + Builder + Empfehlung + DB-Anbindung).

- [ ] **Step 5: Commit**

```bash
git add airbi/insights/segment_matrix.py tests/test_segment_matrix.py
git commit -m "feat: DB-Anbindung der Segment-Matrix (compute + latest_completed_run)"
```

---

## Task 5: FastAPI-App-Gerüst

**Files:**
- Create: `airbi/web/__init__.py`
- Create: `airbi/web/app.py`
- Create: `airbi/web/routes.py`
- Create: `airbi/web/templates/base.html`
- Create: `tests/test_web.py`

Das Gerüst — eine erzeugbare App mit Static-Mount, Templates und einer `/health`-Route. Das eigentliche Dashboard kommt in Task 7.

- [ ] **Step 1: `airbi/web/__init__.py` anlegen**

Create `airbi/web/__init__.py` — leer.

- [ ] **Step 2: `airbi/web/routes.py` schreiben**

`templates` lebt bewusst hier (statt in `app.py`): `app.py` importiert `router` aus `routes.py`, also kann `routes.py` nicht im Gegenzug aus `app.py` importieren — das wäre ein Zirkel. Routen, die Templates rendern, greifen direkt auf das modullokale `templates`-Objekt.

```python
"""FastAPI-Router der AirBI-Web-App.

`get_session` ist die einzige DB-Dependency und wird in Tests via
`app.dependency_overrides` durch eine Test-Session ersetzt."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from fastapi import APIRouter, Depends
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from airbi.db.session import SessionLocal

TEMPLATES_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

router = APIRouter()


def get_session() -> Iterator[Session]:
    """DB-Session pro Request. Override in Tests über
    `app.dependency_overrides[get_session]`."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
```

- [ ] **Step 3: `airbi/web/app.py` schreiben**

```python
"""FastAPI-App-Factory + Modul-Level `app` für Uvicorn-Imports.

CLI/Uvicorn nutzen den String "airbi.web.app:app" als Einstiegspunkt; Tests
nutzen `create_app()` direkt, um die DB-Dependency zu überschreiben."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from airbi.web.routes import router

WEB_DIR = Path(__file__).parent
STATIC_DIR = WEB_DIR / "static"


def create_app() -> FastAPI:
    app = FastAPI(title="AirBI Dashboard", version="0.1.0")
    STATIC_DIR.mkdir(parents=True, exist_ok=True)
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
    app.include_router(router)
    return app


app = create_app()
```

- [ ] **Step 4: Minimalen `base.html` schreiben**

Create `airbi/web/templates/base.html`:

```html
<!doctype html>
<html lang="de">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>{% block title %}AirBI Dashboard{% endblock %}</title>
    <link rel="stylesheet" href="/static/app.css" />
    <script src="https://unpkg.com/htmx.org@1.9.12"
            integrity="sha384-ujb1lZYygJmzgSwoxRggbCHcjc0rB2XoQrxeTUQyRjrOnlCoYta87iKBWq3EsdM2"
            crossorigin="anonymous"></script>
  </head>
  <body class="min-h-screen bg-slate-50 text-slate-900">
    <main class="mx-auto max-w-7xl px-6 py-8">
      {% block content %}{% endblock %}
    </main>
  </body>
</html>
```

- [ ] **Step 5: Failing Smoke-Tests in `tests/test_web.py` schreiben**

```python
import pytest
from fastapi.testclient import TestClient

from airbi.web.app import create_app
from airbi.web.routes import get_session


@pytest.fixture
def client(db_session):
    app = create_app()
    app.dependency_overrides[get_session] = lambda: db_session
    return TestClient(app)


def test_health_returns_ok(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_static_app_css_is_served(client):
    response = client.get("/static/app.css")
    # In Task 5 existiert app.css noch nicht; Task 6 erzeugt sie.
    # Akzeptiert: 200 (wenn Datei da) ODER 404 (wenn nicht). Aber der
    # /static-Mount muss reagieren, nicht den Server crashen.
    assert response.status_code in (200, 404)
```

- [ ] **Step 6: Tests laufen lassen, Erfolg verifizieren**

Run: `uv run pytest tests/test_web.py -v`
Expected: PASS — beide Tests grün.

- [ ] **Step 7: Commit**

```bash
git add airbi/web/ tests/test_web.py
git commit -m "feat: FastAPI-App-Gerüst (create_app, /health, base-template)"
```

---

## Task 6: Tailwind-Standalone-CSS

**Files:**
- Create: `airbi/web/tailwind.src.css`
- Create: `airbi/web/static/app.css` (generiert)
- Modify: `.gitignore`

Tailwind v4 kommt als Standalone-CLI-Binary. Keine `tailwind.config.js`, keine Node-Toolchain. Eingangs-CSS verwendet `@import "tailwindcss";` + `@source` und wird zu `airbi/web/static/app.css` kompiliert. Die kompilierte CSS-Datei wird committet; die Binary nicht.

- [ ] **Step 1: Eingangs-CSS schreiben**

Create `airbi/web/tailwind.src.css`:

```css
@import "tailwindcss";

/* Templates dieses Pakets nach Klassenverwendung scannen. */
@source "./templates";
```

- [ ] **Step 2: `.gitignore` ergänzen**

`.gitignore` öffnen und folgenden Block am Dateiende anhängen (falls noch nicht vorhanden):

```
# Tailwind-Standalone-Binary (plattform-spezifisch, nicht committen)
tailwindcss
tailwindcss-*
```

- [ ] **Step 3: Tailwind-Standalone-Binary herunterladen**

Aktuelle v4-Standalone-CLI von `github.com/tailwindlabs/tailwindcss/releases/latest` laden. Plattform = darwin/arm64 (Dev-Rechner laut Environment); für andere Plattformen Asset entsprechend wählen.

Run (aus dem Projekt-Root, **macOS arm64**):

```bash
curl -sLo tailwindcss \
  https://github.com/tailwindlabs/tailwindcss/releases/latest/download/tailwindcss-macos-arm64 \
&& chmod +x tailwindcss
```

Expected: Datei `tailwindcss` im Projekt-Root, ausführbar. (Sie liegt unter dem `.gitignore`-Pattern aus Step 2.)

- [ ] **Step 4: CSS kompilieren**

Run:

```bash
./tailwindcss -i airbi/web/tailwind.src.css -o airbi/web/static/app.css --minify
```

Expected: `airbi/web/static/app.css` wird erzeugt, Größe > 5 KB (enthält die Default-Theme-Tokens + die in `base.html` verwendeten Klassen).

Während der Entwicklung kann `--watch` angehängt werden — beim Anlegen neuer Klassen in Templates erkennt der Scanner sie dann automatisch.

- [ ] **Step 5: Static-CSS via TestClient verifizieren**

Run: `uv run pytest tests/test_web.py::test_static_app_css_is_served -v`
Expected: PASS — `/static/app.css` liefert jetzt `200`. (Der Test akzeptierte schon 200; hier prüfen wir, dass die Datei tatsächlich kommt.)

Zusätzlich manuell:

```bash
uv run python -c "from pathlib import Path; print('app.css:', Path('airbi/web/static/app.css').stat().st_size, 'bytes')"
```

Expected: Größe > 5000.

- [ ] **Step 6: Commit**

```bash
git add airbi/web/tailwind.src.css airbi/web/static/app.css .gitignore
git commit -m "feat: Tailwind v4 Standalone-CSS kompiliert in static/app.css"
```

---

## Task 7: Dashboard-Route & Templates

**Files:**
- Modify: `airbi/web/routes.py`
- Modify: `airbi/web/app.py` (Templates-Export)
- Create: `airbi/web/templates/dashboard.html`
- Create: `airbi/web/templates/_matrix_region.html`
- Modify: `tests/test_web.py`

Eine Seite, ein Default-Bezirk (Marvila). CrawlRun-Status-Panel + Matrix + Empfehlung + Top-Performer. HTMX-Filter folgt in Task 8.

- [ ] **Step 1: Failing Tests in `tests/test_web.py` ergänzen**

Importzeile oben erweitern:

```python
from decimal import Decimal

from airbi.db.models import CrawlRun, Listing, SearchConfig, Snapshot
```

Am Dateiende anhängen:

```python
def _seed_marvila(session):
    cfg = SearchConfig(name="Marvila Slice 1",
                       district_slugs=["marvila", "beato"])
    run = CrawlRun(search_config=cfg, status="completed", listings_seen=6)
    session.add(run)
    session.flush()

    def add_listing(airbnb_id, district, size_class, price, reviews, title):
        listing = Listing(
            airbnb_id=airbnb_id, city_slug="lisboa", district_slug=district,
            lat=38.74, lng=-9.10, property_type="Apartment", bedrooms=1,
            size_class=size_class, title=title, url=f"https://x/{airbnb_id}",
        )
        session.add(listing)
        session.flush()
        session.add(Snapshot(
            listing_id=listing.id, crawl_run_id=run.id,
            price=Decimal(str(price)), review_count=reviews, rating=4.7,
        ))

    # 4 Marvila-1BRs mit unterschiedlichen Preisen, klare Best-Cell.
    add_listing("M1", "marvila", "1BR", 60, 5,  "Marvila Cosy 1BR")
    add_listing("M2", "marvila", "1BR", 70, 8,  "Marvila Cosy 1BR Nr 2")
    add_listing("M3", "marvila", "1BR", 250, 90, "Marvila Loft Luxe")
    add_listing("M4", "marvila", "1BR", 260, 80, "Marvila Loft Riverside")
    # 2 Beato-Listings.
    add_listing("B1", "beato", "1BR", 80, 12, "Beato Studio")
    add_listing("B2", "beato", "2BR", 130, 20, "Beato Family Flat")
    session.flush()  # KEIN commit — Test-Fixture rollt am Ende zurück.
    return cfg


def test_dashboard_renders_matrix_and_panel(client, db_session):
    cfg = _seed_marvila(db_session)
    response = client.get("/")
    assert response.status_code == 200
    body = response.text
    assert cfg.name in body
    assert "Marvila" in body
    assert "Segment-Matrix" in body
    # CrawlRun-Status-Panel.
    assert "completed" in body
    # Mindestens ein Listing-Titel taucht in den Top-Performern auf.
    assert "Marvila Loft" in body
    # Proxy-Kennzeichnung sichtbar.
    assert "Proxy" in body


def test_dashboard_empty_state_when_no_search_config(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "Noch keine SearchConfig" in response.text
```

- [ ] **Step 2: Tests laufen lassen, Fehlschlag verifizieren**

Run: `uv run pytest tests/test_web.py -v`
Expected: FAIL — `/` liefert 404, weil noch keine Dashboard-Route existiert.

- [ ] **Step 3: Dashboard-Route in `airbi/web/routes.py` ergänzen**

In `routes.py` Importe oben erweitern (das modullokale `templates`-Objekt aus Task 5 nutzen wir direkt):

```python
from fastapi import Request
from fastapi.responses import HTMLResponse
from sqlalchemy import select

from airbi.db.models import CrawlRun, SearchConfig
from airbi.insights.segment_matrix import (
    SegmentMatrix,
    compute_segment_matrix,
    latest_completed_run,
)
```

Am Dateiende anhängen:

```python
def _resolve_search_config(
    session: Session, config_id: int | None
) -> SearchConfig | None:
    stmt = select(SearchConfig)
    if config_id is not None:
        stmt = stmt.where(SearchConfig.id == config_id)
    stmt = stmt.order_by(SearchConfig.id.asc()).limit(1)
    return session.execute(stmt).scalar_one_or_none()


def _latest_any_run(
    session: Session, search_config: SearchConfig
) -> CrawlRun | None:
    stmt = (
        select(CrawlRun)
        .where(CrawlRun.search_config_id == search_config.id)
        .order_by(CrawlRun.started_at.desc(), CrawlRun.id.desc())
        .limit(1)
    )
    return session.execute(stmt).scalar_one_or_none()


def _matrices_for(
    session: Session,
    search_config: SearchConfig,
    district_filter: str,
    crawl_run: CrawlRun,
) -> list[SegmentMatrix]:
    districts = (
        search_config.district_slugs
        if district_filter == "both"
        else [district_filter]
    )
    return [
        compute_segment_matrix(session, search_config, d, crawl_run)
        for d in districts
    ]


@router.get("/", response_class=HTMLResponse)
def dashboard(
    request: Request,
    config_id: int | None = None,
    district: str = "marvila",
    session: Session = Depends(get_session),
):
    search_config = _resolve_search_config(session, config_id)
    if search_config is None:
        return templates.TemplateResponse(
            request, "dashboard.html",
            {"search_config": None, "latest_run": None,
             "matrices": [], "active_district": district,
             "completed_run": None},
        )
    latest_run = _latest_any_run(session, search_config)
    completed_run = latest_completed_run(session, search_config)
    matrices = (
        _matrices_for(session, search_config, district, completed_run)
        if completed_run is not None else []
    )
    return templates.TemplateResponse(
        request, "dashboard.html",
        {
            "search_config": search_config,
            "latest_run": latest_run,
            "completed_run": completed_run,
            "matrices": matrices,
            "active_district": district,
        },
    )
```

- [ ] **Step 4: `dashboard.html` schreiben**

Create `airbi/web/templates/dashboard.html`:

```html
{% extends "base.html" %}
{% block title %}AirBI — Segment-Matrix{% endblock %}
{% block content %}
  <header class="mb-8">
    <h1 class="text-3xl font-semibold tracking-tight">AirBI Dashboard</h1>
    <p class="mt-1 text-sm text-slate-500">
      Segment-Matrix: Welche Größe × Luxusklasse ist im Zielmarkt am attraktivsten?
    </p>
  </header>

  {% if search_config is none %}
    <section class="rounded-lg border border-amber-300 bg-amber-50 p-6 text-amber-900">
      <h2 class="text-lg font-semibold">Noch keine SearchConfig</h2>
      <p class="mt-2 text-sm">
        Lege eine SearchConfig an und starte einen Crawl, dann erscheint die
        Segment-Matrix hier.
      </p>
    </section>
  {% else %}
    <section class="mb-6 grid grid-cols-1 gap-4 md:grid-cols-2">
      <div class="rounded-lg border border-slate-200 bg-white p-5">
        <h2 class="text-sm font-medium uppercase tracking-wide text-slate-500">
          SearchConfig
        </h2>
        <p class="mt-2 text-xl font-semibold">{{ search_config.name }}</p>
        <p class="text-sm text-slate-500">
          {{ search_config.city_slug }} ·
          {{ search_config.district_slugs|join(", ") }}
        </p>
      </div>
      <div class="rounded-lg border border-slate-200 bg-white p-5">
        <h2 class="text-sm font-medium uppercase tracking-wide text-slate-500">
          Letzter Crawl
        </h2>
        {% if latest_run %}
          <p class="mt-2 text-xl font-semibold">{{ latest_run.status }}</p>
          <p class="text-sm text-slate-500">
            {{ latest_run.started_at.strftime("%Y-%m-%d %H:%M") }} ·
            {{ latest_run.listings_seen }} Listings
          </p>
          {% if latest_run.message %}
            <p class="mt-2 text-xs text-slate-400">{{ latest_run.message }}</p>
          {% endif %}
        {% else %}
          <p class="mt-2 text-sm text-slate-500">Noch kein Crawl gelaufen.</p>
        {% endif %}
      </div>
    </section>

    <nav class="mb-6 flex gap-2" aria-label="Bezirksfilter">
      {% set districts = search_config.district_slugs %}
      {% for slug in districts %}
        <a href="/?config_id={{ search_config.id }}&district={{ slug }}"
           class="rounded-md border px-3 py-1.5 text-sm
                  {% if active_district == slug %}
                    border-slate-900 bg-slate-900 text-white
                  {% else %}
                    border-slate-300 bg-white text-slate-700 hover:bg-slate-100
                  {% endif %}">
          {{ slug.title() }}
        </a>
      {% endfor %}
      <a href="/?config_id={{ search_config.id }}&district=both"
         class="rounded-md border px-3 py-1.5 text-sm
                {% if active_district == 'both' %}
                  border-slate-900 bg-slate-900 text-white
                {% else %}
                  border-slate-300 bg-white text-slate-700 hover:bg-slate-100
                {% endif %}">Beide</a>
    </nav>

    <section id="matrix-region">
      {% include "_matrix_region.html" %}
    </section>
  {% endif %}
{% endblock %}
```

- [ ] **Step 5: `_matrix_region.html` schreiben**

Create `airbi/web/templates/_matrix_region.html`:

```html
{% if not completed_run %}
  <div class="rounded-lg border border-slate-200 bg-white p-6 text-slate-500">
    Noch kein abgeschlossener Crawl — die Segment-Matrix erscheint nach dem
    ersten erfolgreichen <code>airbi crawl</code>-Lauf.
  </div>
{% elif not matrices %}
  <div class="rounded-lg border border-slate-200 bg-white p-6 text-slate-500">
    Für diesen Bezirk lagen im letzten Crawl keine zugeordneten Listings vor.
  </div>
{% else %}
  <div class="grid gap-6 {% if matrices|length > 1 %}lg:grid-cols-2{% endif %}">
    {% for matrix in matrices %}
      <article class="rounded-lg border border-slate-200 bg-white p-5">
        <header class="mb-4 flex items-baseline justify-between">
          <h2 class="text-lg font-semibold">
            Segment-Matrix — {{ matrix.district_slug.title() }}
          </h2>
          <span class="rounded bg-slate-100 px-2 py-0.5 text-xs uppercase
                       tracking-wide text-slate-500"
                title="Nachfrage basiert auf Review-Count (~{{ (matrix.review_rate * 100)|round|int }}%
                       der Gäste bewerten), keine gemessene Auslastung.">
            Nachfrage: Proxy
          </span>
        </header>

        <p class="mb-4 text-sm leading-relaxed text-slate-700">
          {{ matrix.recommendation }}
        </p>

        <div class="overflow-x-auto">
          <table class="w-full border-separate border-spacing-1 text-sm">
            <thead>
              <tr>
                <th class="w-24 text-left text-xs font-medium uppercase
                           tracking-wide text-slate-500">Größe ↓ / Tier →</th>
                {% for tier in matrix.price_tiers %}
                  <th class="px-2 py-1 text-left text-xs font-medium uppercase
                             tracking-wide text-slate-500">{{ tier }}</th>
                {% endfor %}
              </tr>
            </thead>
            <tbody>
              {% for size in matrix.size_classes %}
                <tr>
                  <th class="px-2 py-1 text-left text-xs font-medium
                             text-slate-500">{{ size }}</th>
                  {% for tier in matrix.price_tiers %}
                    {% set cell = matrix.cell(size, tier) %}
                    <td class="rounded p-2 align-top
                               {% if cell.heat == 4 %}bg-emerald-500 text-white
                               {% elif cell.heat == 3 %}bg-emerald-300
                               {% elif cell.heat == 2 %}bg-emerald-200
                               {% elif cell.heat == 1 %}bg-emerald-100
                               {% else %}bg-slate-100 text-slate-400{% endif %}
                               {% if matrix.best_cell == (size, tier) %}
                                 ring-2 ring-amber-500
                               {% endif %}">
                      {% if cell.n == 0 %}
                        <span class="text-xs">leer</span>
                      {% else %}
                        <div class="text-xs">
                          {% if cell.is_thin %}
                            <span class="rounded bg-white/60 px-1
                                         text-[10px] uppercase text-slate-500">dünn</span>
                          {% endif %}
                          <span class="font-semibold">
                            Ø {{ cell.score|round(0)|int }} Reviews
                          </span>
                        </div>
                        <div class="text-[11px] opacity-80">
                          N = {{ cell.n }} ·
                          ADR €{% if cell.adr %}{{ cell.adr|int }}{% else %}–{% endif %}
                        </div>
                      {% endif %}
                    </td>
                  {% endfor %}
                </tr>
              {% endfor %}
            </tbody>
          </table>
        </div>

        <section class="mt-6">
          <h3 class="text-sm font-medium uppercase tracking-wide text-slate-500">
            Top-Performer
          </h3>
          {% if matrix.top_performers %}
            <ul class="mt-2 divide-y divide-slate-100">
              {% for perf in matrix.top_performers %}
                <li class="flex items-baseline justify-between py-2 text-sm">
                  <div>
                    <a href="{{ perf.url }}" class="font-medium text-slate-900 hover:underline"
                       target="_blank" rel="noreferrer">{{ perf.title or perf.airbnb_id }}</a>
                    <span class="ml-2 rounded bg-slate-100 px-1.5 py-0.5
                                 text-[11px] text-slate-600">
                      {{ perf.size_class }} · {{ perf.price_tier }}
                    </span>
                  </div>
                  <div class="text-xs text-slate-500">
                    {{ perf.review_count }} Reviews
                    {% if perf.rating %} · ★ {{ "%.2f"|format(perf.rating) }}{% endif %}
                  </div>
                </li>
              {% endfor %}
            </ul>
          {% else %}
            <p class="mt-2 text-sm text-slate-500">
              Keine Top-Performer mit klassifizierter Größe in diesem Bezirk.
            </p>
          {% endif %}
        </section>
      </article>
    {% endfor %}
  </div>
{% endif %}
```

Wichtig zum Tailwind-Scanner: alle Farb-/Heat-Klassen (`bg-emerald-100`/`200`/`300`/`500`, `bg-slate-100`, `ring-2`, `ring-amber-500`) stehen literal in diesem Template — der Scanner inkludiert sie damit in `app.css`.

- [ ] **Step 6: Tests laufen lassen, Erfolg verifizieren**

Run: `uv run pytest tests/test_web.py -v`
Expected: PASS — `test_dashboard_renders_matrix_and_panel` und `test_dashboard_empty_state_when_no_search_config` grün.

- [ ] **Step 7: Tailwind nachkompilieren**

Mit den neuen Template-Klassen muss `app.css` aktualisiert werden:

Run: `./tailwindcss -i airbi/web/tailwind.src.css -o airbi/web/static/app.css --minify`
Expected: `app.css` wird größer (jetzt mit allen Heat-, Ring- und Layout-Klassen).

- [ ] **Step 8: Commit**

```bash
git add airbi/web/routes.py airbi/web/templates/dashboard.html \
        airbi/web/templates/_matrix_region.html airbi/web/static/app.css \
        tests/test_web.py
git commit -m "feat: Dashboard-Route, Segment-Matrix-Template und Top-Performer-Anzeige"
```

---

## Task 8: HTMX-Bezirksfilter (Marvila / Beato / beide)

**Files:**
- Modify: `airbi/web/routes.py`
- Modify: `airbi/web/templates/dashboard.html`
- Modify: `tests/test_web.py`

Statt die ganze Seite neu zu laden, tauscht HTMX nur das `#matrix-region`-Fragment. „Beide" rendert beide Bezirke nebeneinander (Spec §13 Bonus).

- [ ] **Step 1: Failing Tests in `tests/test_web.py` ergänzen**

Am Dateiende anhängen:

```python
def test_matrix_partial_returns_single_district(client, db_session):
    cfg = _seed_marvila(db_session)
    response = client.get(f"/matrix?config_id={cfg.id}&district=marvila")
    assert response.status_code == 200
    body = response.text
    assert "Segment-Matrix — Marvila" in body
    assert "Segment-Matrix — Beato" not in body
    # Partial enthält NICHT das Layout-Root (kein <html>-Tag).
    assert "<html" not in body.lower()


def test_matrix_partial_returns_two_matrices_for_both(client, db_session):
    cfg = _seed_marvila(db_session)
    response = client.get(f"/matrix?config_id={cfg.id}&district=both")
    assert response.status_code == 200
    body = response.text
    assert "Segment-Matrix — Marvila" in body
    assert "Segment-Matrix — Beato" in body


def test_dashboard_filter_buttons_use_htmx(client, db_session):
    cfg = _seed_marvila(db_session)
    response = client.get(f"/?config_id={cfg.id}")
    body = response.text
    # Mindestens ein HTMX-Attribut auf den Filter-Buttons.
    assert "hx-get=\"/matrix?config_id=" in body
    assert "hx-target=\"#matrix-region\"" in body
```

- [ ] **Step 2: Tests laufen lassen, Fehlschlag verifizieren**

Run: `uv run pytest tests/test_web.py -v`
Expected: FAIL — `/matrix` liefert 404, und die `hx-get`-Attribute fehlen im Dashboard.

- [ ] **Step 3: `/matrix`-Route in `airbi/web/routes.py` ergänzen**

Am Dateiende anhängen:

```python
@router.get("/matrix", response_class=HTMLResponse)
def matrix_partial(
    request: Request,
    config_id: int | None = None,
    district: str = "marvila",
    session: Session = Depends(get_session),
):
    """HTMX-Partial: nur die Matrix-Region (eine oder zwei Matrizen)."""
    search_config = _resolve_search_config(session, config_id)
    if search_config is None:
        return templates.TemplateResponse(
            request, "_matrix_region.html",
            {"matrices": [], "completed_run": None},
        )
    completed_run = latest_completed_run(session, search_config)
    matrices = (
        _matrices_for(session, search_config, district, completed_run)
        if completed_run is not None else []
    )
    return templates.TemplateResponse(
        request, "_matrix_region.html",
        {"matrices": matrices, "completed_run": completed_run},
    )
```

- [ ] **Step 4: Dashboard-Filter-Buttons auf HTMX umstellen**

In `airbi/web/templates/dashboard.html` den `<nav>`-Block aus Task 7 durch folgenden ersetzen:

```html
    <nav class="mb-6 flex gap-2" aria-label="Bezirksfilter">
      {% set districts = search_config.district_slugs %}
      {% for slug in districts %}
        <button type="button"
                hx-get="/matrix?config_id={{ search_config.id }}&district={{ slug }}"
                hx-target="#matrix-region"
                hx-swap="innerHTML"
                class="rounded-md border px-3 py-1.5 text-sm
                       {% if active_district == slug %}
                         border-slate-900 bg-slate-900 text-white
                       {% else %}
                         border-slate-300 bg-white text-slate-700 hover:bg-slate-100
                       {% endif %}">
          {{ slug.title() }}
        </button>
      {% endfor %}
      <button type="button"
              hx-get="/matrix?config_id={{ search_config.id }}&district=both"
              hx-target="#matrix-region"
              hx-swap="innerHTML"
              class="rounded-md border px-3 py-1.5 text-sm
                     {% if active_district == 'both' %}
                       border-slate-900 bg-slate-900 text-white
                     {% else %}
                       border-slate-300 bg-white text-slate-700 hover:bg-slate-100
                     {% endif %}">
        Beide
      </button>
    </nav>
```

- [ ] **Step 5: Tests laufen lassen, Erfolg verifizieren**

Run: `uv run pytest tests/test_web.py -v`
Expected: PASS — alle Web-Tests grün.

- [ ] **Step 6: Tailwind nachkompilieren (falls in Step 4 neue Klassen dazukamen — hier nicht; trotzdem sicher gehen)**

Run: `./tailwindcss -i airbi/web/tailwind.src.css -o airbi/web/static/app.css --minify`
Expected: `app.css` bleibt funktional gleich; wenn der Inhalt sich nicht ändert, ist nichts zu committen.

- [ ] **Step 7: Commit**

```bash
git add airbi/web/routes.py airbi/web/templates/dashboard.html \
        airbi/web/static/app.css tests/test_web.py
git commit -m "feat: HTMX-Bezirksfilter (Marvila/Beato/beide) tauscht die Matrix-Region"
```

---

## Task 9: CLI — `airbi web`

**Files:**
- Modify: `airbi/cli.py`

`airbi web` startet uvicorn gegen `airbi.web.app:app`. Konsistent mit dem bestehenden `airbi crawl`-Subcommand aus Plan 2.

- [ ] **Step 1: `airbi/cli.py` um den `web`-Subcommand erweitern**

In `airbi/cli.py`:

(a) Neue Handler-Funktion **nach** `_cmd_crawl` einfügen:

```python
def _cmd_web(args: argparse.Namespace) -> int:
    """Startet das FastAPI-Dashboard via uvicorn."""
    import uvicorn

    uvicorn.run(
        "airbi.web.app:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
    )
    return 0
```

(b) In `main`, **nach** dem `crawl_parser`-Block und **vor** dem `args = parser.parse_args(argv)`, den `web`-Subparser ergänzen:

```python
    # --- web ---
    web_parser = subparsers.add_parser(
        "web",
        help="Dashboard-Webserver starten (uvicorn)",
        description="Startet das AirBI-Dashboard auf dem angegebenen Host/Port.",
    )
    web_parser.add_argument("--host", default="127.0.0.1", help="Bind-Host (default 127.0.0.1)")
    web_parser.add_argument("--port", type=int, default=8000, help="Bind-Port (default 8000)")
    web_parser.add_argument("--reload", action="store_true", default=False,
                            help="Auto-Reload bei Code-Änderungen (Entwicklung)")
```

(c) Den Dispatch am Ende von `main` um den neuen Befehl erweitern. Die bestehende Zeile

```python
    if args.command == "crawl":
        exit_code = _cmd_crawl(args)
        sys.exit(exit_code)
```

durch folgenden Block ersetzen:

```python
    if args.command == "crawl":
        sys.exit(_cmd_crawl(args))
    if args.command == "web":
        sys.exit(_cmd_web(args))
```

- [ ] **Step 2: CLI-Hilfe und Web-Hilfe verifizieren**

Run: `uv run airbi --help && uv run airbi web --help`
Expected: `airbi` listet `crawl` **und** `web` als Befehle; `airbi web --help` zeigt `--host`, `--port`, `--reload`.

- [ ] **Step 3: Server-Start kurz verifizieren (manuell, optional)**

Run (in einem zweiten Terminal): `uv run airbi web --host 127.0.0.1 --port 8765` — danach `curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8765/health` ausführen.
Expected: `200`. Server mit `Ctrl-C` beenden.

- [ ] **Step 4: Commit**

```bash
git add airbi/cli.py
git commit -m "feat: CLI-Befehl 'airbi web' startet das Dashboard via uvicorn"
```

---

## Task 10: End-to-End — Acceptance-Test (§13)

**Files:** keine neuen — manuelle Abnahme des Slice-1-Acceptance-Tests gegen echte Crawl-Daten.

- [ ] **Step 1: Sicherstellen, dass ein `CrawlRun` mit Daten existiert**

Wenn aus Plan 2 noch kein erfolgreicher Lauf in der lokalen DB liegt:

```bash
uv run airbi crawl --config "Marvila Slice 1"
```

Erwartet: `status: completed`, `listings_seen > 0`. Falls nicht: das ist das im Briefing benannte Scraper-Risiko — dokumentieren und eskalieren, nicht durch Datenfälschung „grün machen".

DB-Stand kurz prüfen:

```bash
uv run python -c "
from airbi.db.session import SessionLocal
from airbi.db.models import CrawlRun, Listing
s = SessionLocal()
print('completed runs:', s.query(CrawlRun).filter_by(status='completed').count())
print('listings:', s.query(Listing).count())
s.close()
"
```

Expected: `completed runs >= 1`, `listings > 0`.

- [ ] **Step 2: Dashboard starten**

Run: `uv run airbi web --reload`
Expected: uvicorn startet auf `http://127.0.0.1:8000`, Logs zeigen ein erfolgreich gemountetes Static-Verzeichnis.

- [ ] **Step 3: Acceptance-Kriterien §13 durchgehen**

Im Browser `http://127.0.0.1:8000/` öffnen und folgende Kriterien Punkt für Punkt prüfen — diese Liste ist 1:1 aus Spec §13:

1. Im CrawlRun-Status-Panel steht der letzte Lauf mit `status: completed` und einer plausiblen `listings_seen`-Zahl.
2. Für Bezirk **Marvila** erscheint die Segment-Matrix (Größe × `price_tier`); das attraktivste Feld trägt den gelben Ring (`ring-amber-500`) — die Best-Cell-Markierung.
3. Pro Zelle steht die Wettbewerbsdichte `N` sichtbar (z. B. „N = 3").
4. Unter der Matrix liegt eine schlanke Top-Performer-Liste, gruppiert je Größenklasse, mit Reviews und Rating.
5. Über der Matrix steht ein Empfehlungssatz im Stil „Für Marvila ist {Segment} am attraktivsten — Ø {…} Reviews je Listing bei {…} Wettbewerber-Listings, Median-ADR €{…}." — mit Proxy-Kennzeichnung in einem Badge oben rechts in der Matrix-Card.
6. Bezirks-Toggle auf „Beide" tauscht via HTMX die Region; Marvila und Beato erscheinen nebeneinander, jeweils mit eigener Best-Cell.
7. Zellen unter `min_sample` tragen den „dünn"-Marker, sind ausgegraut und sind **nicht** als Best-Cell markiert.

Jeden erfüllten Punkt unten abhaken (in einem PR-Kommentar oder Acceptance-Notiz). Treten Abweichungen auf: nicht still korrigieren — den Befund vor dem Merge eskalieren.

- [ ] **Step 4: Volle Test-Suite**

Run: `uv run pytest -q`
Expected: alle Tests grün (Plan 1 + Plan 2 + Plan 3: `test_models`, `test_geo`, `test_classification`, `test_scraper_pacing`, `test_scraper_parser`, `test_search_crawl`, `test_segment_matrix`, `test_web`).

- [ ] **Step 5: Acceptance-Notiz committen (kein Code)**

Wurden in Task 10 keine Code-Änderungen nötig, gibt es keinen Commit. Sonst werden eventuelle Korrekturen mit eindeutigem Bezug zur §13-Abnahme committet.

---

## Definition of Done (Plan 3)

- [ ] `uv run pytest -q` — alle Tests grün (Plan 1 + Plan 2 + Plan 3, inkl. `test_segment_matrix` und `test_web`).
- [ ] `uv run airbi --help` listet `crawl` und `web`; `uv run airbi web --help` zeigt `--host`/`--port`/`--reload`.
- [ ] `airbi/web/static/app.css` existiert, ist committet und stammt aus `airbi/web/tailwind.src.css`; die Tailwind-Binary ist gitignored.
- [ ] Lokal gegen die DB mit echten Marvila-Daten: `uv run airbi web` startet das Dashboard, die Segment-Matrix für Marvila erscheint mit Best-Cell-Markierung, Empfehlungssatz und Top-Performer; der HTMX-Bezirksfilter (Marvila / Beato / Beide) wechselt die Matrix-Region.
- [ ] §13-Acceptance-Kriterien (1)–(7) sind durchgegangen und dokumentiert.
- [ ] Alle Tasks committet.

## Bewusst NICHT in Plan 3 (Slice-1-Scope)

- Voller Detail-Crawl für `amenity_score`/kombinierte `luxury_class` (Vertiefungsrunde, Spec §14).
- Review-Velocity-Anzeige (braucht mehrwöchige Snapshot-Historie).
- Eigenständige Insight-Plugin-Registry/Discovery (Spec §4).
- Anlegen neuer SearchConfigs aus der UI (Slice 1 nutzt die per CLI/Skript bootstrappte Config, Spec §14).
- Custom-Polygon-Zeichnen, Plotly-Charts, Cross-Search-Vergleiche.
- UI-Crawl-Button, APScheduler, systemd, Backup, volles Monitoring (Vertiefungsrunde #5, Spec §11).

## Bekannte Tailwind-Stolperfallen

- Dynamisch zusammengesetzte Klassennamen (`bg-emerald-{{n}}00`) werden vom v4-Scanner nicht erkannt. Alle Heat-/Ring-/Layout-Klassen stehen daher literal im Template und sind über `@source "./templates";` abgedeckt.
- Neue Klassen in Templates erfordern eine Neukompilierung von `app.css` (`./tailwindcss -i … -o … --minify`). Während der Entwicklung mit `--watch` arbeiten.
- Die Standalone-Binary ist plattform-spezifisch und wird **nicht** committet. Andere Plattformen laden das entsprechende Asset von `tailwindlabs/tailwindcss/releases/latest`.
