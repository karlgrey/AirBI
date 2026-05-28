# Slice 2 — Luxusklasse Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Den vollen Detail-Crawl (Amenities) bauen, einen `amenity_score` berechnen, mit dem Preis-Perzentil zur kombinierten `luxury_class` verschneiden und diese zur Spalten-Achse der Segment-Matrix machen — bis ins Live-Dashboard.

**Architecture:** Reine Klassifikatoren (`amenity_score`, `luxury_class`, `price_percentile`) ohne DB/HTTP, gegen Fixtures/Hand-Daten testbar. Detail-Parser erweitert um Amenity-Extraktion. `persist_results` speichert Amenities + `amenity_score` (listing-lokal, stabil). Die Matrix berechnet `luxury_class` zur Abfragezeit (kohortenrelativ über `price_percentile`). Dashboard-Template relabelt die Spalten-Achse.

**Tech Stack:** Python ≥3.11, SQLAlchemy/Alembic, FastAPI/Jinja2, pytest, Playwright (bestehender Crawl), uv.

**Bezug:** Umsetzung von `docs/superpowers/specs/2026-05-28-slice2-luxury-class-design.md`.

---

## Voraussetzungen

- Slice 1 + Cleanup + Dashboard-Klartext + Deployment auf `main`. Lokale `airbi`-DB mit aktuellen Daten.
- `tests/fixtures/scraper/listing_detail.json` enthält Amenity-Daten (verifiziert: `pdpPresentation.amenities.seeAllAmenitiesGroups`, 44 Amenities).
- Worktree/Feature-Branch über `superpowers:using-git-worktrees`. Branch von **lokalem** `main`-HEAD (nicht origin, falls origin hinterherhinkt — fetch+reset wie etabliert).

## Wichtige Hinweise

- **TDD streng.** Reine Funktionen zuerst (Tasks 3+4), dann Verdrahtung.
- **Spalten-Achse wird umbenannt:** `price_tier` → `luxury_class` in der Insight-Schicht (Cell/TopPerformer/SegmentMatrix + Konstante). Die 4 Label-Werte bleiben Budget/Mid/Premium/Luxury — nur Bedeutung + Berechnung ändern sich. Bestehende `test_segment_matrix.py`-Tests werden mit umgestellt.
- **`price_tier` bleibt** als Funktion in `price.py` erhalten (rückwärtskompatibel), nur nicht mehr Matrix-Achse.
- **Amenity-Matching** case-insensitiv via Substring gegen konfigurierbare Listen.

## Dateistruktur

| Datei | Status | Verantwortung |
|---|---|---|
| `airbi/scraper/models.py` | ✏️ T1/T2 | `ListingDetail` + `ParsedListing` um `amenities`/`description` |
| `airbi/scraper/parser.py` | ✏️ T1 | `parse_listing_detail` extrahiert Amenities + Beschreibung |
| `airbi/scraper/search_crawl.py` | ✏️ T2/T6 | `merge_detail` reicht durch; `persist_results` schreibt + scort |
| `airbi/classification/amenity.py` | T3 (neu) | `amenity_score` |
| `airbi/classification/luxury.py` | T4 (neu) | `luxury_class` + `LUXURY_CLASSES` |
| `airbi/classification/price.py` | ✏️ T4 | `price_percentile`-Helfer (DRY mit `price_tier`) |
| `airbi/db/models.py` | ✏️ T5 | `Listing.amenity_score` |
| `alembic/versions/*` | T5 (neu) | Migration `listing.amenity_score` |
| `airbi/insights/segment_matrix.py` | ✏️ T7 | Achse `luxury_class`; `ListingRow.amenity_score` |
| `airbi/web/templates/_matrix_region.html` | ✏️ T8 | „Luxusklasse" + Tooltip |
| `airbi/web/templates/dashboard.html` | ✏️ T8 | Onboarding-Satz |
| `tests/test_scraper_parser.py` | ✏️ T1 | Amenity-Parser-Tests |
| `tests/test_search_crawl.py` | ✏️ T2/T6 | merge/persist-Tests |
| `tests/test_amenity.py` | T3 (neu) | amenity_score-Tests |
| `tests/test_luxury.py` | T4 (neu) | luxury_class + price_percentile-Tests |
| `tests/test_models.py` | ✏️ T5 | amenity_score-Feld |
| `tests/test_segment_matrix.py` | ✏️ T7 | Achsen-Umstellung |
| `tests/test_web.py` | ✏️ T8 | „Luxusklasse"-Assertions |

---

## Task 1: Amenity-Extraktion im Detail-Parser

**Files:**
- Modify: `airbi/scraper/models.py` (`ListingDetail`)
- Modify: `airbi/scraper/parser.py` (`parse_listing_detail`)
- Modify: `tests/test_scraper_parser.py`

- [ ] **Step 1: `ListingDetail` um `amenities`/`description` erweitern**

In `airbi/scraper/models.py`, die `ListingDetail`-Dataclass ergänzen (bestehende Felder behalten):

```python
@dataclass
class ListingDetail:
    """Aus der Airbnb-Detailseite extrahierte Daten (Detail-Crawl)."""

    bedrooms: int | None
    beds: int | None
    bathrooms: float | None
    max_guests: int | None
    amenities: list[str] | None = None
    description: str | None = None
```

- [ ] **Step 2: Failing Tests in `tests/test_scraper_parser.py` ergänzen**

Am Dateiende anhängen:

```python
def test_detail_parser_extracts_available_amenities():
    detail = parse_listing_detail(_detail_payload())
    assert detail.amenities is not None
    # Bekannte verfügbare Amenities aus der Fixture:
    assert any("river view" in a.lower() for a in detail.amenities)
    assert any("air conditioning" in a.lower() for a in detail.amenities)
    # "Not included" (available=False) darf NICHT auftauchen:
    assert not any("smoke alarm" == a.lower() for a in detail.amenities)
    # Plausible Gesamtzahl (Fixture hat 40 verfügbare von 44):
    assert 20 <= len(detail.amenities) <= 44


def test_detail_parser_extracts_description():
    detail = parse_listing_detail(_detail_payload())
    # Beschreibung vorhanden + ohne HTML-Tags
    assert detail.description is None or "<" not in detail.description


def test_detail_parser_amenities_empty_on_unexpected_shape():
    detail = parse_listing_detail({})
    assert detail.amenities == [] or detail.amenities is None
```

- [ ] **Step 3: Test laufen lassen, Fehlschlag verifizieren**

Run: `uv run pytest tests/test_scraper_parser.py -k "amenities or description" -v`
Expected: FAIL — `ListingDetail` hat die Felder, aber `parse_listing_detail` füllt sie noch nicht (amenities ist `None`).

- [ ] **Step 4: `parse_listing_detail` um Amenity-/Description-Extraktion erweitern**

In `airbi/scraper/parser.py`, in `parse_listing_detail`, **vor** dem `return ListingDetail(...)` zwei Blöcke ergänzen und den Return erweitern. Zuerst eine Helferfunktion am Modulanfang (nach `_collect_overview_items`) hinzufügen:

```python
def _extract_amenities(payload: dict) -> list[str]:
    """Verfügbare Amenity-Titel aus pdpPresentation.amenities.seeAllAmenitiesGroups.
    Nur Items mit available==True; dedupliziert, Reihenfolge erhalten."""
    # niobeClientData ist eine Liste; defensiv zum pdpPresentation navigieren
    try:
        pdp = payload["niobeClientData"][0][1]["data"]["node"]["pdpPresentation"]
        all_groups = pdp["amenities"]["seeAllAmenitiesGroups"]
    except (KeyError, IndexError, TypeError):
        return []
    if not isinstance(all_groups, list):
        return []
    seen: set[str] = set()
    out: list[str] = []
    for g in all_groups:
        items = (g or {}).get("amenities") or (g or {}).get("items") or []
        for it in items:
            if not isinstance(it, dict):
                continue
            if it.get("available") is False:
                continue
            title = it.get("title")
            if isinstance(title, str) and title and title not in seen:
                seen.add(title)
                out.append(title)
    return out


def _extract_description(payload: dict) -> str | None:
    """Kurzbeschreibung aus pdpPresentation.descriptions, HTML-Tags gestrippt."""
    try:
        descs = payload["niobeClientData"][0][1]["data"]["node"]["pdpPresentation"]["descriptions"]
    except (KeyError, IndexError, TypeError):
        return None
    raw = None
    if isinstance(descs, dict):
        short = descs.get("shortDescriptionHtml")
        long = descs.get("longDescriptionHtml")
        for cand in (short, long):
            if isinstance(cand, dict):
                raw = cand.get("localizedStringWithTranslationPreference") or cand.get("localizedString") or cand.get("content")
                if raw:
                    break
            elif isinstance(cand, str) and cand:
                raw = cand
                break
    if not isinstance(raw, str) or not raw:
        return None
    text = re.sub(r"<[^>]+>", " ", raw)
    text = re.sub(r"\s+", " ", text).strip()
    return text or None
```

Dann in `parse_listing_detail` direkt vor dem finalen `return` die Werte ermitteln:

```python
    amenities = _extract_amenities(payload)
    description = _extract_description(payload)
```

und den Return erweitern:

```python
    return ListingDetail(
        bedrooms=bedrooms,
        beds=beds,
        bathrooms=bathrooms,
        max_guests=max_guests,
        amenities=amenities,
        description=description,
    )
```

- [ ] **Step 5: Tests laufen lassen, Erfolg verifizieren**

Run: `uv run pytest tests/test_scraper_parser.py -v`
Expected: PASS — alle Parser-Tests grün (inkl. der bestehenden Raumzahl-Tests + 3 neue).

- [ ] **Step 6: Commit**

```bash
git add airbi/scraper/models.py airbi/scraper/parser.py tests/test_scraper_parser.py
git commit -m "feat: Detail-Parser extrahiert verfügbare Amenities + Beschreibung"
```

---

## Task 2: `ParsedListing` + `merge_detail` durchreichen

**Files:**
- Modify: `airbi/scraper/models.py` (`ParsedListing`)
- Modify: `airbi/scraper/search_crawl.py` (`merge_detail`)
- Modify: `tests/test_search_crawl.py`

- [ ] **Step 1: `ParsedListing` um `amenities`/`description` erweitern**

In `airbi/scraper/models.py`, die `ParsedListing`-Dataclass um zwei Felder am Ende erweitern (mit Defaults, damit bestehende Tests/Aufrufer ohne diese Felder weiterlaufen):

```python
    search_position: int | None
    amenities: list[str] | None = None
    description: str | None = None
```

(Die vorhandenen Felder bleiben unverändert; `search_position` war das letzte Feld — die zwei neuen kommen danach.)

- [ ] **Step 2: Failing Test in `tests/test_search_crawl.py` ergänzen**

Am Dateiende anhängen:

```python
def test_merge_detail_fills_amenities_and_description():
    pl = _parsed("1", 38.74, -9.10)
    detail = ListingDetail(
        bedrooms=2, beds=3, bathrooms=1.5, max_guests=4,
        amenities=["River view", "Air conditioning"], description="Schöne Wohnung",
    )
    merged = merge_detail(pl, detail)
    assert merged.amenities == ["River view", "Air conditioning"]
    assert merged.description == "Schöne Wohnung"
    # Raumzahlen weiterhin gemergt
    assert merged.bedrooms == 2 and merged.max_guests == 4
```

- [ ] **Step 3: Test laufen lassen, Fehlschlag verifizieren**

Run: `uv run pytest tests/test_search_crawl.py -k merge_detail -v`
Expected: FAIL — `merge_detail` setzt amenities/description noch nicht (bleiben `None`).

- [ ] **Step 4: `merge_detail` erweitern**

In `airbi/scraper/search_crawl.py`, `merge_detail` um die zwei Felder ergänzen:

```python
def merge_detail(parsed_listing: ParsedListing, detail: ListingDetail) -> ParsedListing:
    """Gibt ein neues ParsedListing zurück, dessen Detail-Felder aus `detail`
    stammen. Alle anderen Felder bleiben unverändert."""
    return dataclasses.replace(
        parsed_listing,
        bedrooms=detail.bedrooms,
        beds=detail.beds,
        bathrooms=detail.bathrooms,
        max_guests=detail.max_guests,
        amenities=detail.amenities,
        description=detail.description,
    )
```

- [ ] **Step 5: Tests laufen lassen, Erfolg verifizieren**

Run: `uv run pytest tests/test_search_crawl.py -v`
Expected: PASS — alle Crawl-Tests grün.

- [ ] **Step 6: Commit**

```bash
git add airbi/scraper/models.py airbi/scraper/search_crawl.py tests/test_search_crawl.py
git commit -m "feat: amenities/description durch ParsedListing + merge_detail durchreichen"
```

---

## Task 3: `amenity_score`-Klassifikator

**Files:**
- Create: `airbi/classification/amenity.py`
- Test: `tests/test_amenity.py`

- [ ] **Step 1: Failing Tests in `tests/test_amenity.py` schreiben**

```python
from airbi.classification.amenity import amenity_score


def _score(amenities, **kw):
    base = dict(beds=2, bedrooms=1, max_guests=2, is_superhost=False, rating=4.5)
    base.update(kw)
    return amenity_score(amenities, **base)


def test_amenity_score_zero_for_empty_minimal_listing():
    s = amenity_score([], beds=None, bedrooms=None, max_guests=None,
                      is_superhost=False, rating=None)
    assert s == 0.0


def test_amenity_score_in_unit_range():
    s = _score(["River view", "Air conditioning", "Free street parking"],
               is_superhost=True, rating=5.0)
    assert 0.0 <= s <= 1.0


def test_amenity_score_view_component_rewards_premium_view():
    high = _score(["River view"])
    low = _score(["City skyline view"])
    none = _score([])
    assert high > low > none


def test_amenity_score_premium_amenities_raise_score():
    few = _score(["Wifi"])
    many = _score(["Pool", "Hot tub", "Air conditioning", "Elevator",
                   "Dishwasher", "Smart lock", "Free parking"])
    assert many > few


def test_amenity_score_superhost_and_rating_contribute():
    base = _score(["Wifi"], is_superhost=False, rating=4.0)
    better = _score(["Wifi"], is_superhost=True, rating=5.0)
    assert better > base


def test_amenity_score_weights_configurable():
    amenities = ["River view"]
    default = _score(amenities)
    # View-Gewicht auf 0 → der River-view-Beitrag verschwindet
    cfg = {"weights": {"view": 0.0, "premium": 0.30, "richness": 0.15,
                       "comfort": 0.10, "superhost": 0.10, "rating": 0.10}}
    zeroed = _score(amenities, config=cfg)
    assert zeroed < default
```

- [ ] **Step 2: Test laufen lassen, Fehlschlag verifizieren**

Run: `uv run pytest tests/test_amenity.py -v`
Expected: FAIL — `ModuleNotFoundError` für `airbi.classification.amenity`.

- [ ] **Step 3: `airbi/classification/amenity.py` schreiben**

```python
"""amenity_score (Spec §7): listing-lokaler Ausstattungs-Score in 0..1.

Reine Funktion — kein Netzwerk, keine DB. Gewichte und Amenity-Listen sind
über `config` (SearchConfig.classification_config) justierbar; sinnvolle
Defaults sind hier verankert."""

from __future__ import annotations

DEFAULT_AMENITY_CONFIG: dict = {
    "weights": {
        "view": 0.25,
        "premium": 0.30,
        "richness": 0.15,
        "comfort": 0.10,
        "superhost": 0.10,
        "rating": 0.10,
    },
    "view_premium": [
        "river view", "sea view", "ocean view", "waterfront",
        "lake view", "beach view",
    ],
    "view_secondary": [
        "city skyline view", "city view", "skyline view",
        "garden view", "courtyard view", "mountain view", "harbor view",
    ],
    "premium_amenities": [
        "pool", "hot tub", "air conditioning", "free parking",
        "free street parking", "paid parking", "elevator", "dishwasher",
        "smart lock", "self check-in", "gym", "ev charger",
        "private patio or balcony", "outdoor furniture", "bbq grill", "dryer",
    ],
    "premium_target": 6,
    "richness_target": 40,
}


def _merge(config: dict | None) -> dict:
    cfg = {**DEFAULT_AMENITY_CONFIG, **(config or {})}
    # weights getrennt mergen, damit Teilangaben die Defaults nicht löschen
    cfg["weights"] = {**DEFAULT_AMENITY_CONFIG["weights"], **((config or {}).get("weights") or {})}
    return cfg


def _clamp(x: float) -> float:
    return 0.0 if x < 0 else (1.0 if x > 1 else x)


def amenity_score(
    amenities: list[str] | None,
    *,
    beds: int | None,
    bedrooms: int | None,
    max_guests: int | None,
    is_superhost: bool,
    rating: float | None,
    config: dict | None = None,
) -> float:
    """Gewichteter Ausstattungs-Score in 0..1. Fehlende Eingaben → die
    jeweilige Komponente trägt 0 bei (kein Crash)."""
    cfg = _merge(config)
    w = cfg["weights"]
    names = [a.lower() for a in (amenities or []) if isinstance(a, str)]

    # View
    if any(any(p in a for a in names) for p in cfg["view_premium"]):
        view = 1.0
    elif any(any(p in a for a in names) for p in cfg["view_secondary"]):
        view = 0.6
    else:
        view = 0.0

    # Premium-Ausstattung
    present = sum(1 for p in cfg["premium_amenities"] if any(p in a for a in names))
    premium = _clamp(present / cfg["premium_target"]) if cfg["premium_target"] else 0.0

    # Reichtum
    richness = _clamp(len(names) / cfg["richness_target"]) if cfg["richness_target"] else 0.0

    # Komfort pro Gast
    space = beds if beds is not None else bedrooms
    if space is not None and max_guests:
        comfort = _clamp(space / max_guests)
    else:
        comfort = 0.0

    # Superhost
    superhost = 1.0 if is_superhost else 0.0

    # Rating-Niveau
    rating_score = _clamp((rating - 4.0) / 1.0) if rating is not None else 0.0

    score = (
        w["view"] * view
        + w["premium"] * premium
        + w["richness"] * richness
        + w["comfort"] * comfort
        + w["superhost"] * superhost
        + w["rating"] * rating_score
    )
    return round(_clamp(score), 4)
```

- [ ] **Step 4: Tests laufen lassen, Erfolg verifizieren**

Run: `uv run pytest tests/test_amenity.py -v`
Expected: PASS — alle 6 Tests grün.

- [ ] **Step 5: Commit**

```bash
git add airbi/classification/amenity.py tests/test_amenity.py
git commit -m "feat: amenity_score-Klassifikator (gewichtet, konfigurierbar)"
```

---

## Task 4: `price_percentile` + `luxury_class`-Klassifikator

**Files:**
- Modify: `airbi/classification/price.py` (`price_percentile` extrahieren)
- Create: `airbi/classification/luxury.py`
- Test: `tests/test_luxury.py`

- [ ] **Step 1: Failing Tests in `tests/test_luxury.py` schreiben**

```python
from airbi.classification.luxury import LUXURY_CLASSES, luxury_class
from airbi.classification.price import price_percentile


COHORT = [50, 60, 70, 80, 90, 100, 110, 120, 130, 200]


def test_price_percentile_rank():
    # 0 Werte < 55 ... eigentlich 1 (50) -> rank 0.1
    assert price_percentile(55, COHORT) == 0.1
    assert price_percentile(200, COHORT) == 0.9
    assert price_percentile(None, COHORT) is None
    assert price_percentile(100, [100]) is None  # Kohorte < 2


def test_luxury_classes_constant():
    assert LUXURY_CLASSES == ["Budget", "Mid", "Premium", "Luxury"]


def test_luxury_class_pure_price_when_amenity_zero():
    # ausgewogene Default-Gewichte 0.5/0.5; amenity=0 -> index = 0.5*pct
    assert luxury_class(0.1, 0.0) == "Budget"     # 0.05
    assert luxury_class(0.9, 0.0) == "Mid"        # 0.45
    assert luxury_class(1.0, 1.0) == "Luxury"     # 1.0


def test_luxury_class_amenity_lifts_class():
    # gleiches Preis-Perzentil, aber hoher amenity_score -> höhere Klasse
    low_amenity = luxury_class(0.5, 0.0)
    high_amenity = luxury_class(0.5, 1.0)
    assert LUXURY_CLASSES.index(high_amenity) > LUXURY_CLASSES.index(low_amenity)


def test_luxury_class_emerging_weighting():
    # amenity-lastige Gewichtung (Marvila/Beato): Ausstattung dominiert
    cfg = {"luxury_weights": {"price": 0.35, "amenity": 0.65}}
    # niedriger Preis (0.2), hohe Ausstattung (0.9) -> index = 0.35*0.2+0.65*0.9 = 0.655 -> Premium
    assert luxury_class(0.2, 0.9, cfg) == "Premium"


def test_luxury_class_unclassified_without_percentile():
    assert luxury_class(None, 0.5) == "unclassified"
```

- [ ] **Step 2: Test laufen lassen, Fehlschlag verifizieren**

Run: `uv run pytest tests/test_luxury.py -v`
Expected: FAIL — `ImportError` für `price_percentile` bzw. `airbi.classification.luxury`.

- [ ] **Step 3: `price_percentile` in `airbi/classification/price.py` ergänzen + `price_tier` darauf umstellen**

Am Anfang von `price.py` (vor `price_tier`) einfügen:

```python
def price_percentile(
    price: float | Decimal | None,
    cohort_prices: list[float | Decimal | None],
) -> float | None:
    """Perzentil-Rang eines Preises in der Kohorte: Anteil der Kohorten-Preise,
    die strikt kleiner sind. Ohne Preis oder bei Kohorte < 2 Werten: None."""
    clean = [float(p) for p in cohort_prices if p is not None]
    if price is None or len(clean) < 2:
        return None
    value = float(price)
    return sum(1 for p in clean if p < value) / len(clean)
```

In `price_tier` die inline-Rang-Berechnung durch den Helfer ersetzen — den Block

```python
    clean = [float(p) for p in cohort_prices if p is not None]
    if price is None or len(clean) < 2:
        return "unclassified"

    value = float(price)
    rank = sum(1 for p in clean if p < value) / len(clean)
```

ersetzen durch:

```python
    rank = price_percentile(price, cohort_prices)
    if rank is None:
        return "unclassified"
```

(Die `tiers`-Zeile davor und die `for name, low, high in tiers`-Schleife danach bleiben unverändert.)

- [ ] **Step 4: `airbi/classification/luxury.py` schreiben**

```python
"""luxury_class (Spec §8): kombinierte Luxusklasse aus Preis-Perzentil und
amenity_score über einen gewichteten Index. Reine Funktion.

luxury_index = w_preis · price_percentile + w_amenity · amenity_score
Klassifizierung über Schwellen → Budget / Mid / Premium / Luxury.
Gewichte/Schwellen über config justierbar (Emerging-Bezirke: amenity-lastig)."""

from __future__ import annotations

LUXURY_CLASSES = ["Budget", "Mid", "Premium", "Luxury"]

DEFAULT_LUXURY_CONFIG: dict = {
    "luxury_weights": {"price": 0.5, "amenity": 0.5},
    "luxury_thresholds": [0.25, 0.5, 0.75],
}


def luxury_class(
    price_percentile: float | None,
    amenity_score: float | None,
    config: dict | None = None,
) -> str:
    """Kombinierte Luxusklasse. ``price_percentile`` None (kein Preis/zu kleine
    Kohorte) → 'unclassified'. ``amenity_score`` None → als 0 behandelt."""
    if price_percentile is None:
        return "unclassified"
    cfg = config or {}
    weights = {**DEFAULT_LUXURY_CONFIG["luxury_weights"], **(cfg.get("luxury_weights") or {})}
    thresholds = cfg.get("luxury_thresholds") or DEFAULT_LUXURY_CONFIG["luxury_thresholds"]

    a = amenity_score if amenity_score is not None else 0.0
    index = weights["price"] * price_percentile + weights["amenity"] * a

    t0, t1, t2 = thresholds[0], thresholds[1], thresholds[2]
    if index < t0:
        return LUXURY_CLASSES[0]
    if index < t1:
        return LUXURY_CLASSES[1]
    if index < t2:
        return LUXURY_CLASSES[2]
    return LUXURY_CLASSES[3]
```

- [ ] **Step 5: Tests laufen lassen, Erfolg verifizieren**

Run: `uv run pytest tests/test_luxury.py tests/test_classification.py -v`
Expected: PASS — neue luxury/percentile-Tests grün UND die bestehenden `price_tier`-Tests in `test_classification.py` weiterhin grün (Refactor bricht sie nicht).

- [ ] **Step 6: Commit**

```bash
git add airbi/classification/price.py airbi/classification/luxury.py tests/test_luxury.py
git commit -m "feat: price_percentile + luxury_class (gewichteter Index)"
```

---

## Task 5: DB-Migration `listing.amenity_score`

**Files:**
- Modify: `airbi/db/models.py` (`Listing`)
- Create: `alembic/versions/<hash>_listing_amenity_score.py` (autogenerate)
- Modify: `tests/test_models.py`

- [ ] **Step 1: Failing Test in `tests/test_models.py` ergänzen**

Am Dateiende anhängen:

```python
def test_listing_stores_amenity_score_and_amenities(db_session):
    from airbi.db.models import Listing
    listing = Listing(
        airbnb_id="AS1", city_slug="lisboa", lat=38.74, lng=-9.10,
        amenity_score=0.73, amenities=["River view", "Pool"],
        description="Tolle Aussicht",
    )
    db_session.add(listing)
    db_session.flush()
    got = db_session.query(Listing).filter_by(airbnb_id="AS1").one()
    assert got.amenity_score == 0.73
    assert got.amenities == ["River view", "Pool"]
    assert got.description == "Tolle Aussicht"
```

- [ ] **Step 2: Test laufen lassen, Fehlschlag verifizieren**

Run: `uv run pytest tests/test_models.py -k amenity_score -v`
Expected: FAIL — `Listing` hat kein `amenity_score`-Attribut (TypeError beim Konstruktor).

- [ ] **Step 3: `Listing.amenity_score` in `airbi/db/models.py` ergänzen**

In der `Listing`-Klasse, bei den abgeleiteten/reservierten Feldern (nach `size_class`), ergänzen:

```python
    amenity_score: Mapped[float | None] = mapped_column(Float, nullable=True)
```

(`Float` ist bereits importiert. `amenities`/`description` existieren schon als reservierte Felder.)

- [ ] **Step 4: Alembic-Migration autogenerieren + anwenden**

```bash
uv run alembic revision --autogenerate -m "listing amenity_score"
```
Die erzeugte Datei in `alembic/versions/` öffnen und prüfen: enthält `op.add_column('listing', sa.Column('amenity_score', sa.Float(), nullable=True))` (und keine ungewollten Drops). Dann:
```bash
uv run alembic upgrade head
```
Expected: Migration läuft sauber; Spalte `listing.amenity_score` existiert.

- [ ] **Step 5: Tests laufen lassen, Erfolg verifizieren**

Run: `uv run pytest tests/test_models.py -v`
Expected: PASS — alle Modell-Tests grün.

- [ ] **Step 6: Commit**

```bash
git add airbi/db/models.py alembic/versions/ tests/test_models.py
git commit -m "feat: Listing.amenity_score + Migration"
```

---

## Task 6: `persist_results` schreibt Amenities + amenity_score

**Files:**
- Modify: `airbi/scraper/search_crawl.py` (`persist_results`)
- Modify: `tests/test_search_crawl.py`

- [ ] **Step 1: Failing Test in `tests/test_search_crawl.py` ergänzen**

Am Dateiende anhängen:

```python
def test_persist_results_writes_amenities_and_amenity_score(db_session):
    cfg = SearchConfig(name="Lux", district_slugs=["marvila"])
    run = CrawlRun(search_config=cfg, status="running")
    db_session.add(run)
    db_session.flush()
    districts = load_districts()

    pl = merge_detail(
        _parsed("LX1", 38.7390, -9.1044),
        ListingDetail(bedrooms=2, beds=2, bathrooms=1.0, max_guests=2,
                      amenities=["River view", "Air conditioning", "Pool"],
                      description="Loft mit Blick"),
    )
    persist_results(db_session, run, [pl], districts)

    listing = db_session.query(Listing).filter_by(airbnb_id="LX1").one()
    assert listing.amenities == ["River view", "Air conditioning", "Pool"]
    assert listing.description == "Loft mit Blick"
    assert listing.amenity_score is not None and 0.0 <= listing.amenity_score <= 1.0
    # River view + Pool + AC + Superhost(false)/rating 4.5 → spürbar > 0
    assert listing.amenity_score > 0.2
```

- [ ] **Step 2: Test laufen lassen, Fehlschlag verifizieren**

Run: `uv run pytest tests/test_search_crawl.py -k amenity -v`
Expected: FAIL — `persist_results` schreibt amenities/amenity_score noch nicht.

- [ ] **Step 3: `persist_results` erweitern**

In `airbi/scraper/search_crawl.py`, oben bei den Imports den amenity_score-Import ergänzen (zu den bestehenden Klassifikations-Imports):

```python
from airbi.classification.amenity import amenity_score as _amenity_score
```

In `persist_results`, die `classification_config` aus der SearchConfig holen (einmal vor der Schleife):

```python
    city_slug = crawl_run.search_config.city_slug
    cls_config = crawl_run.search_config.classification_config or {}
```

In der Schleife, nach `listing.is_superhost = pl.is_superhost`, ergänzen:

```python
        listing.amenities = pl.amenities
        listing.description = pl.description
        listing.amenity_score = _amenity_score(
            pl.amenities,
            beds=pl.beds,
            bedrooms=pl.bedrooms,
            max_guests=pl.max_guests,
            is_superhost=pl.is_superhost,
            rating=pl.rating,
            config=cls_config,
        )
```

- [ ] **Step 4: Tests laufen lassen, Erfolg verifizieren**

Run: `uv run pytest tests/test_search_crawl.py -v`
Expected: PASS — alle Crawl-Tests grün.

- [ ] **Step 5: Commit**

```bash
git add airbi/scraper/search_crawl.py tests/test_search_crawl.py
git commit -m "feat: persist_results speichert Amenities + amenity_score"
```

---

## Task 7: Segment-Matrix auf `luxury_class`-Achse umstellen

**Files:**
- Modify: `airbi/insights/segment_matrix.py`
- Modify: `tests/test_segment_matrix.py`

Umbenennung der Spalten-Achse von `price_tier` zu `luxury_class` in der Insight-Schicht + Verschneidungslogik. Die 4 Labelwerte (Budget/Mid/Premium/Luxury) bleiben.

- [ ] **Step 1: Failing Tests in `tests/test_segment_matrix.py` anpassen/ergänzen**

Die Modul-Konstante in den Tests umstellen: Wo `PRICE_TIERS` importiert/verwendet wird, auf `LUXURY_CLASSES` umstellen. Konkret den Import oben

```python
from airbi.insights.segment_matrix import (
    PRICE_TIERS,
    SIZE_CLASSES,
    ...
)
```

ändern zu (statt `PRICE_TIERS` jetzt `LUXURY_CLASSES`; restliche Importe behalten):

```python
from airbi.insights.segment_matrix import (
    LUXURY_CLASSES,
    SIZE_CLASSES,
    ...
)
```

Den Test `test_matrix_axes_have_expected_order` umstellen:

```python
def test_matrix_axes_have_expected_order():
    assert SIZE_CLASSES == ["Studio", "1BR", "2BR", "3BR+"]
    assert LUXURY_CLASSES == ["Budget", "Mid", "Premium", "Luxury"]
```

Der `_row`-Helfer und alle Tests, die `Cell(... price_tier=...)`, `matrix.price_tiers`, `pl.price_tier`, `perf.price_tier` verwenden, auf `luxury_class` umstellen. Wo `ListingRow` gebaut wird, das neue Feld `amenity_score` ergänzen. Den `_row`-Helfer erweitern:

```python
def _row(airbnb_id, size_class, price, review_count, rating=4.5, amenity_score=0.0):
    return ListingRow(
        airbnb_id=airbnb_id, title=f"L{airbnb_id}", url=f"https://x/{airbnb_id}",
        size_class=size_class,
        price=Decimal(str(price)) if price is not None else None,
        review_count=review_count, rating=rating, amenity_score=amenity_score,
    )
```

Einen neuen Test ergänzen, der die Amenity-Wirkung auf die Achse prüft:

```python
def test_builder_amenity_score_shifts_listing_into_higher_luxury_class():
    # 4 gleich-große, gleich-teure 1BR; eines mit hohem amenity_score.
    # Bei amenity-lastiger Gewichtung muss es in eine höhere Luxusklasse fallen.
    cfg = {"min_sample": 1,
           "luxury_weights": {"price": 0.35, "amenity": 0.65}}
    rows = [
        _row("a", "1BR", 100, 10, amenity_score=0.0),
        _row("b", "1BR", 100, 10, amenity_score=0.0),
        _row("c", "1BR", 100, 10, amenity_score=0.0),
        _row("d", "1BR", 100, 10, amenity_score=0.95),
    ]
    matrix = build_segment_matrix(rows, config=cfg, district_slug="m", crawl_run_id=1)
    # Listing d landet in einer höheren Luxusklasse als a/b/c (gleicher Preis).
    classes_with_d = [lux for (sz, lux), cell in matrix.cells.items()
                      if cell.n > 0 and sz == "1BR"]
    assert "Premium" in classes_with_d or "Luxury" in classes_with_d
```

Bestehende Aggregations-/Best-Cell-/Empfehlungs-Tests: die hartcodierten `price`-Werte erzeugen jetzt `luxury_class` statt `price_tier`. Da `amenity_score` der Test-Rows default `0.0` ist und die Default-Gewichte 0.5/0.5 sind, gilt `luxury_index = 0.5 · price_percentile`. Das verschiebt die Schwellen: Wo Tests vorher auf „Budget"/„Mid" geprüft haben (price_tier = Perzentil direkt), muss jetzt mit `index = 0.5·percentile` gerechnet werden. **Jeden betroffenen Assert auf die erwartete Luxusklasse anpassen** (Index = 0.5·rank bei amenity=0; Schwellen 0.25/0.5/0.75): rank 0.0–0.5 → index 0.0–0.25 → „Budget"; rank 0.5–1.0 → index 0.25–0.5 → „Mid". D.h. bei amenity=0 fallen alle Listings in Budget/Mid. Tests, die spezifische Premium/Luxury-Zellen brauchen, geben den Test-Rows ein `amenity_score` > 0 mit, um die Zielklasse zu erreichen.

- [ ] **Step 2: Test laufen lassen, Fehlschlag verifizieren**

Run: `uv run pytest tests/test_segment_matrix.py -v`
Expected: FAIL — `ImportError`/`AttributeError` (LUXURY_CLASSES, ListingRow.amenity_score, Cell.luxury_class existieren noch nicht).

- [ ] **Step 3: `segment_matrix.py` umstellen**

(a) Importe + Konstanten oben. `PRICE_TIERS` durch `LUXURY_CLASSES` ersetzen (aus luxury.py importieren), `price_percentile` + `luxury_class` importieren:

```python
from airbi.classification.price import price_percentile as _price_percentile
from airbi.classification.luxury import LUXURY_CLASSES, luxury_class as _luxury_class
```

Die bisherige lokale Konstante `PRICE_TIERS = [...]` entfernen; stattdessen `LUXURY_CLASSES` (importiert) verwenden. Den bisherigen `_price_tier`-Import entfernen, falls er nur hier genutzt wurde.

(b) `ListingRow` um `amenity_score` erweitern:

```python
@dataclass
class ListingRow:
    airbnb_id: str
    title: str | None
    url: str | None
    size_class: str
    price: Decimal | None
    review_count: int
    rating: float | None
    amenity_score: float = 0.0
```

(c) `Cell.price_tier` → `Cell.luxury_class`, `TopPerformer.price_tier` → `TopPerformer.luxury_class`, `SegmentMatrix.price_tiers` → `SegmentMatrix.luxury_classes` (default_factory `lambda: list(LUXURY_CLASSES)`). Die `cell(self, size_class, price_tier)`-Methode umbenennen zu `cell(self, size_class, luxury_class)` (Parametername), Verhalten gleich.

(d) `_empty_grid()` über `LUXURY_CLASSES` iterieren statt `PRICE_TIERS`.

(e) In `build_segment_matrix` die Zuordnung umstellen: statt `tier = _price_tier(r.price, cohort, cfg)` jetzt:

```python
    cohort = [r.price for r in rows if r.price is not None]
    ...
    for r in rows:
        if r.size_class not in SIZE_CLASSES:
            continue
        if r.price is None:
            continue
        pct = _price_percentile(r.price, cohort)
        if pct is None:
            continue
        lux = _luxury_class(pct, r.amenity_score, cfg)
        if lux not in LUXURY_CLASSES:
            continue
        cell_rows.setdefault((r.size_class, lux), []).append(r)
        listing_count += 1
```

(f) Überall, wo `PRICE_TIERS` / `price_tiers` / `.price_tier` im Builder, in `_pick_top_performers`, im Empfehlungstext (`_build_recommendation`) und in `SegmentMatrix.cell(...)`-Aufrufen vorkommt, auf die luxury-Benennung umstellen. `_build_recommendation` verwendet die Spalten-Bezeichnung im Satz — den `tier`-Begriff dort zu `luxury_class` umbenennen (der gerenderte Text bleibt „{size}-{class}", z.B. „1BR-Premium").

(g) `compute_segment_matrix` (DB-Funktion): beim Bauen der `ListingRow` das Feld `amenity_score=listing.amenity_score or 0.0` ergänzen:

```python
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
```

- [ ] **Step 4: Tests laufen lassen, Erfolg verifizieren**

Run: `uv run pytest tests/test_segment_matrix.py -v`
Expected: PASS — alle Matrix-Tests grün (umgestellt + neuer Amenity-Shift-Test).

- [ ] **Step 5: Volle Suite (Web-Tests brechen erwartbar — kommen in Task 8)**

Run: `uv run pytest -q`
Expected: `test_web.py` kann jetzt fehlschlagen, wo es `matrix.price_tiers` o.ä. via Template erwartet — das ist Task 8. Alle übrigen grün. Falls `test_web.py` durch den Template-Bezug auf `matrix.price_tiers` einen 500er wirft: in Task 8 behoben. (Wenn du strikt grün bleiben willst, Task 7 + 8 als ein Commit-Paar behandeln.)

- [ ] **Step 6: Commit**

```bash
git add airbi/insights/segment_matrix.py tests/test_segment_matrix.py
git commit -m "refactor: Segment-Matrix-Achse price_tier -> luxury_class (Preis x Ausstattung)"
```

---

## Task 8: Dashboard-Template auf „Luxusklasse"

**Files:**
- Modify: `airbi/web/templates/_matrix_region.html`
- Modify: `airbi/web/templates/dashboard.html`
- Modify: `tests/test_web.py`

- [ ] **Step 1: Template-Bezüge `price_tiers`/`price_tier` → `luxury_classes`/`luxury_class` umstellen**

In `airbi/web/templates/_matrix_region.html`:
- Schleife `{% for tier in matrix.price_tiers %}` → `{% for tier in matrix.luxury_classes %}` (Schleifenvariable `tier` darf als lokaler Name bleiben).
- Tabellen-Ecke `Apartment-Größe ↓ / Preisklasse →` → `Apartment-Größe ↓ / Luxusklasse →`.
- `matrix.cell(size, tier)` bleibt aufrufbar (Methode nimmt jetzt `luxury_class`-Parametername, Positionsargumente unverändert).
- Top-Performer-Tag `{{ perf.price_tier }}` → `{{ perf.luxury_class }}`.
- Best-Cell-Markierung `{% if matrix.best_cell == (size, tier) %}` bleibt (Tuple-Vergleich, Werte sind jetzt luxury_class).
- Cell-`title`-Tooltip ergänzen: „… Luxusklasse kombiniert Preis und Ausstattung."
- Badge-Tooltip (geschätzte Nachfrage) unverändert.

In `airbi/web/templates/dashboard.html`:
- Onboarding-Box-Satz: „… nach Größe und Preisklasse." → „… nach Größe und Luxusklasse (Preis kombiniert mit Ausstattung)."

- [ ] **Step 2: Web-Tests anpassen**

In `tests/test_web.py`:
- `test_matrix_uses_klartext_size_labels`: Assertion `assert "Preisklasse" in body` → `assert "Luxusklasse" in body`. (Falls „Preisklasse" sonst nicht mehr vorkommt: zusätzlich `assert "Preisklasse" not in body` ist NICHT nötig — „Preis" kommt im Tooltip weiter vor.)
- Ein neuer Test:

```python
def test_matrix_axis_is_luxusklasse(client, db_session):
    _seed_marvila(db_session)
    response = client.get("/")
    body = response.text
    assert "Luxusklasse" in body
    assert "Preis und Ausstattung" in body  # Tooltip/Erklärung
```

Der `_seed_marvila`-Helfer in `test_web.py` legt Listings ohne `amenity_score` an → `luxury_class` ist rein preisgetrieben (amenity_score=0 → index=0.5·percentile). Bestehende Assertions auf konkrete Listing-Titel/Top-Apartments bleiben gültig (unabhängig von der Achse).

- [ ] **Step 3: Test laufen lassen, Fehlschlag verifizieren**

Run: `uv run pytest tests/test_web.py -v`
Expected: FAIL zuerst (vor Template-Edit) bzw. nach Edit grün. Reihenfolge: Tests anpassen → Template anpassen → grün.

- [ ] **Step 4: Tests laufen lassen, Erfolg verifizieren**

Run: `uv run pytest -q`
Expected: PASS — alle Tests grün (Insight + Web wieder konsistent).

- [ ] **Step 5: Tailwind nachkompilieren (nur falls neue Klassen — hier vmtl. keine)**

Run: `./tailwindcss -i airbi/web/tailwind.src.css -o airbi/web/static/app.css --minify`
(Falls die Binary im Worktree fehlt: wie in der Deploy-Runde von `tailwindlabs/tailwindcss/releases/latest` für macOS-arm64 laden.) Wenn `git diff` an `app.css` nichts zeigt, nicht committen.

- [ ] **Step 6: Commit**

```bash
git add airbi/web/templates/_matrix_region.html airbi/web/templates/dashboard.html tests/test_web.py airbi/web/static/app.css
git commit -m "feat: Dashboard-Matrix zeigt Luxusklasse (Preis x Ausstattung)"
```

---

## Task 9: E2E — Re-Crawl + Verifikation + Daten-Sync

**Files:** keine neuen — reale Verifikation.

- [ ] **Step 1: Volle Test-Suite**

Run: `uv run pytest -q`
Expected: alle Tests grün.

- [ ] **Step 2: Re-Crawl gegen die echte Suche (lokal)**

Run: `uv run airbi crawl --config "Marvila Slice 1"`
Expected: `Status: completed`, `listings_seen > 0`. Bei Block/CAPTCHA: eskalieren, nicht fälschen.

- [ ] **Step 3: amenity_score + Amenities in der lokalen DB verifizieren**

Run:
```bash
uv run python -c "
from airbi.db.session import SessionLocal
from airbi.db.models import Listing
s = SessionLocal()
total = s.query(Listing).count()
scored = s.query(Listing).filter(Listing.amenity_score.isnot(None)).count()
with_amen = s.query(Listing).filter(Listing.amenities.isnot(None)).count()
print(f'Listings: {total} | mit amenity_score: {scored} | mit amenities: {with_amen}')
top = s.query(Listing).filter(Listing.amenity_score.isnot(None)).order_by(Listing.amenity_score.desc()).first()
if top:
    print(f'Top amenity_score: {top.amenity_score} -> {(top.title or \"\")[:50]}')
s.close()
"
```
Expected: ein plausibler Anteil hat `amenity_score` + `amenities`; das teuerste/luxuriöseste Marvila-Listing hat einen hohen Score.

- [ ] **Step 4: Dashboard lokal prüfen**

Run (Hintergrund): `uv run airbi web --port 8000` → `curl -s "http://127.0.0.1:8000/?district=marvila" | grep -o "Luxusklasse\|Preis und Ausstattung" | sort -u` → Server stoppen (`pkill -f airbi.web.app`).
Expected: „Luxusklasse" + Tooltip-Text erscheinen; Matrix-Zellen verteilen sich jetzt über die kombinierte Achse.

- [ ] **Step 5: Daten-Sync auf Prod (dump/restore, wie in docs/DEPLOYMENT.md)**

⚠ CHECKPOINT (Prod-Schreibzugriff): vor Ausführung bestätigen.
```bash
PGPASSWORD=airbi pg_dump --data-only --no-owner --no-privileges -h localhost -U airbi -d airbi \
  -t search_config -t crawl_run -t listing -t snapshot -f /tmp/airbi-data.sql
scp /tmp/airbi-data.sql deploy@labs.remoterepublic.com:/tmp/
ssh deploy@labs.remoterepublic.com 'cd /opt/airbi && git pull --ff-only && ~/.local/bin/uv sync --no-dev && ~/.local/bin/uv run alembic upgrade head && sudo systemctl restart airbi-web'
```
Dann die Prod-DB leeren+neu einspielen ODER `--data-only` in die migrierte DB (Reihenfolge je nach Strategie — bei Bedarf Listings/Snapshots vorher truncaten, da Re-Crawl dieselben airbnb_ids upsertet). Konkret die DEPLOYMENT.md-Sektion „Daten aktualisieren" befolgen. Migration `listing.amenity_score` läuft via `alembic upgrade head` auf Prod mit.

- [ ] **Step 6: Live-Verifikation**

Run:
```bash
curl -s https://airbi.remoterepublic.com/ | grep -o "Luxusklasse" | head -1
curl -s -o /dev/null -w "https://airbi: %{http_code}\n" https://airbi.remoterepublic.com/
```
Expected: „Luxusklasse" erscheint, HTTP 200.

---

## Definition of Done

- [ ] `uv run pytest -q` — alle Tests grün (neue amenity/luxury/parser-Tests + umgestellte Matrix/Web-Tests).
- [ ] `parse_listing_detail` liefert verfügbare Amenities + Beschreibung; `merge_detail`/`persist_results` reichen sie durch und speichern `amenity_score`.
- [ ] `amenity_score` (0..1, konfigurierbar) auf `Listing` gespeichert; `luxury_class` zur Abfragezeit aus `price_percentile` × `amenity_score` berechnet.
- [ ] Segment-Matrix-Achse ist `luxury_class`; Dashboard zeigt „Luxusklasse" mit Tooltip „Preis und Ausstattung".
- [ ] Migration `listing.amenity_score` lokal + Prod angewandt.
- [ ] Re-Crawl befüllt amenity_score; Daten auf Prod synchronisiert; live auf airbi.remoterepublic.com.
- [ ] Emerging-Gewichtung in der Marvila-Config gesetzt (`luxury_weights {price:0.35, amenity:0.65}`).

## Marvila-Config: Emerging-Gewichtung setzen

Einmalig (lokal + via Re-Crawl/Sync auf Prod), die SearchConfig-`classification_config` um die Emerging-Gewichtung ergänzen:

```bash
uv run python -c "
from airbi.db.session import SessionLocal
from airbi.db.models import SearchConfig
s = SessionLocal()
cfg = s.query(SearchConfig).filter_by(name='Marvila Slice 1').one()
c = dict(cfg.classification_config or {})
c['luxury_weights'] = {'price': 0.35, 'amenity': 0.65}
cfg.classification_config = c
s.commit(); print('Emerging-Gewichtung gesetzt:', cfg.classification_config)
s.close()
"
```
Dies in Task 9 nach dem Re-Crawl (vor dem Dump) ausführen, damit die Gewichtung mit in die Prod-DB wandert. (Die Gewichtung wirkt zur Abfragezeit — sie muss in der Prod-`classification_config` stehen.)

## Bewusst NICHT in Slice 2 (Spec §13)

- Top-Performer-Profilierung „was haben sie gemeinsam", Unterversorgungs-Ranking-View.
- Review-Velocity, AirDNA/Saisonalität, AL-Lizenz-Layer, Multi-City.
- Insight-Plugin-Registry, Amenity-Korrelations-Analyse.
- APScheduler/Auto-Crawl.
