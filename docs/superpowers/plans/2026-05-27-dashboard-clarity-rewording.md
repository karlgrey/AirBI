# Dashboard-Klartext-Umbau Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** AirBI-Dashboard von Tech-Sprache (Plan 3) auf Investor-tauglichen Klartext umstellen — Wording + Lese-Reihenfolge — ohne Insight-Logik, Datenmodell oder Crawl-Code anzufassen.

**Architecture:** Reine Template-Schicht-Änderung in `airbi/web/templates/`. Empfehlungstext wird ab jetzt im Template komponiert (statt `_build_recommendation()`-String zu rendern) — saubere Trennung. Mini-Helper für deutsche Datums-Formatierung in `airbi/web/routes.py`.

**Tech Stack:** FastAPI/Jinja2-Templates, Tailwind v4 (Standalone-CLI-Recompile), pytest mit FastAPI `TestClient`.

**Bezug:** Umsetzung von `docs/superpowers/specs/2026-05-27-dashboard-clarity-rewording-design.md`. Baut auf Slice 1 (Plan 1-3 + Parser-Cleanup) auf.

---

## Voraussetzungen

- Slice 1 (Plan 1-3) + Parser-Cleanup auf `main` gemerged. 68/68 Tests grün.
- Lokales PostgreSQL läuft; aktueller CrawlRun (`id=3`) hat 25 Apartments.
- `uv` auf dem PATH. Tailwind-Standalone-Binary `./tailwindcss` im Projekt-Root (von Plan 3 Task 6).
- Worktree/Feature-Branch über `superpowers:using-git-worktrees`.

## Wichtige Hinweise

- **Reine Template-Schicht.** Insight-Logik (`airbi/insights/segment_matrix.py`), DB, Scraper bleiben unangetastet. Wer das ändert, ist außerhalb des Scopes.
- **Empfehlung wandert.** Aktuell rendert das Template `{{ matrix.recommendation }}` (ein String aus `_build_recommendation()`). Ab Task 4 komponiert das Template direkt aus den Zell-Werten. `_build_recommendation()` bleibt als Funktion bestehen (Datenkontrakt unverändert, andere Konsumenten bedient).
- **Tailwind-Recompile am Ende.** Neue Utility-Klassen werden in mehreren Tasks eingeführt — der Recompile-Schritt sammelt sie alle in Task 5.
- **TDD streng.** Jeder Wording-Wechsel: erst Test anpassen/ergänzen (rot), dann Template ändern (grün), dann Commit.

## Dateistruktur

| Datei | Status | Verantwortung |
|---|---|---|
| `airbi/web/routes.py` | ✏️ T1 | Neuer `_format_date_de`-Helper + Date-String an Template übergeben |
| `airbi/web/templates/dashboard.html` | ✏️ T1 | Header-Untertitel, Onboarding-Box, Untersuchungsbereich-Karte, Filter „Vergleich", Footer-Sektion (ersetzt obere Doppelkarte) |
| `airbi/web/templates/_matrix_region.html` | ✏️ T2/T3/T4 | Matrix-Card-Header + Badge + Tabelle (T2), Top-Apartments (T3), Empfehlungs-Block neu + verschoben (T4) |
| `airbi/web/static/app.css` | ✏️ T5 | Tailwind-Recompile (sammelt alle neuen Klassen) |
| `tests/test_web.py` | ✏️ T1-T4 | Pro Task: bestehende Assertions auf alte Strings anpassen + neue Assertions auf neue Strings |

---

## Task 1: dashboard.html — Page Chrome + Footer

**Files:**
- Modify: `airbi/web/routes.py`
- Modify: `airbi/web/templates/dashboard.html`
- Modify: `tests/test_web.py`

Ziel: Alles oberhalb der `<section id="matrix-region">`-Region und der neue Footer darunter werden neu strukturiert. Das `_matrix_region.html`-Include bleibt unverändert.

- [ ] **Step 1: Failing Tests in `tests/test_web.py` ergänzen / anpassen**

Den existierenden Test `test_dashboard_renders_matrix_and_panel` finden und **diese eine Zeile**

```python
    assert "completed" in body
```

ersetzen durch

```python
    assert "vollständig erfasst" in body
```

Am Dateiende anhängen:

```python
def test_dashboard_has_onboarding_box(client, db_session):
    _seed_marvila(db_session)
    response = client.get("/")
    body = response.text
    assert "So liest du dieses Dashboard" in body


def test_dashboard_uses_untersuchungsbereich_label(client, db_session):
    _seed_marvila(db_session)
    response = client.get("/")
    body = response.text
    assert "Untersuchungsbereich" in body
    assert "Lissabon" in body  # city_label aus city_slug = "lisboa"


def test_dashboard_filter_has_vergleich_button(client, db_session):
    cfg = _seed_marvila(db_session)
    response = client.get(f"/?config_id={cfg.id}")
    body = response.text
    assert "Vergleich" in body
    # Bezirks-Buttons (Marvila, Beato) bleiben — strukturell unverändert
    assert "Marvila" in body and "Beato" in body


def test_dashboard_footer_shows_datenstand(client, db_session):
    _seed_marvila(db_session)
    response = client.get("/")
    body = response.text
    assert "Datenstand" in body
    assert "25 Apartments" in body or "6 Apartments" in body  # _seed_marvila legt 6 an


def test_dashboard_empty_state_shows_neuer_text(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "Noch kein Untersuchungsbereich angelegt" in response.text
```

**Den alten Empty-State-Test entfernen**, der noch auf „Noch keine SearchConfig" prüft. Diese Zeile

```python
def test_dashboard_empty_state_when_no_search_config(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "Noch keine SearchConfig" in response.text
```

komplett aus der Datei entfernen — `test_dashboard_empty_state_shows_neuer_text` ersetzt sie.

- [ ] **Step 2: Tests laufen lassen, Fehlschlag verifizieren**

Run: `uv run pytest tests/test_web.py -v`
Expected: FAIL — die 5 neuen Tests und die geänderte Assertion in `test_dashboard_renders_matrix_and_panel` scheitern. Die anderen Tests (Health, Static, Matrix-Partials) bleiben grün.

- [ ] **Step 3: `_format_date_de`-Helper in `airbi/web/routes.py` ergänzen**

In `airbi/web/routes.py` Importe um `datetime` erweitern (falls noch nicht vorhanden):

```python
from datetime import datetime
```

(Falls dieser Import schon implizit vorhanden ist, nicht doppeln.)

Vor `router = APIRouter()` (z.B. nach dem `templates`-Init) einfügen:

```python
_GERMAN_MONTHS = (
    "Januar", "Februar", "März", "April", "Mai", "Juni",
    "Juli", "August", "September", "Oktober", "November", "Dezember",
)


def _format_date_de(dt: datetime | None) -> str | None:
    """Datum im deutschen Stil: '27. Mai 2026' (kein führendes Null im Tag)."""
    if dt is None:
        return None
    return f"{dt.day}. {_GERMAN_MONTHS[dt.month - 1]} {dt.year}"
```

- [ ] **Step 4: Dashboard-Route um `latest_run_date_de` + `city_label` erweitern**

In `airbi/web/routes.py` die `dashboard`-Funktion finden. Im erfolgreichen (nicht-empty) Pfad (vor dem `return templates.TemplateResponse(...)`) ergänzen:

```python
    latest_run_date_de = _format_date_de(latest_run.started_at) if latest_run else None
    city_label = "Lissabon" if search_config.city_slug == "lisboa" else search_config.city_slug
```

Im `templates.TemplateResponse(...)`-Aufruf das Context-Dict um die zwei Keys erweitern:

```python
    return templates.TemplateResponse(
        request, "dashboard.html",
        {
            "search_config": search_config,
            "latest_run": latest_run,
            "completed_run": completed_run,
            "matrices": matrices,
            "active_district": district,
            "latest_run_date_de": latest_run_date_de,
            "city_label": city_label,
        },
    )
```

Den Empty-State-Branch (wenn `search_config is None`) NICHT ändern — keine zusätzlichen Keys nötig, weil dort der Empty-State-Block läuft.

- [ ] **Step 5: `dashboard.html` komplett ersetzen**

Den vollständigen Inhalt von `airbi/web/templates/dashboard.html` durch folgendes ersetzen:

```html
{% extends "base.html" %}
{% block title %}AirBI — Marktübersicht{% endblock %}
{% block content %}
  <header class="mb-6">
    <h1 class="text-3xl font-semibold tracking-tight">AirBI Dashboard</h1>
    <p class="mt-1 text-sm text-slate-500">
      Marktübersicht — welches Apartment-Segment lohnt sich am ehesten?
    </p>
  </header>

  {% if search_config is none %}
    <section class="rounded-lg border border-amber-300 bg-amber-50 p-6 text-amber-900">
      <h2 class="text-lg font-semibold">Noch kein Untersuchungsbereich angelegt</h2>
      <p class="mt-2 text-sm">
        Lege einen Untersuchungsbereich an und starte einen Crawl, dann erscheint
        die Marktübersicht hier.
      </p>
    </section>
  {% else %}

    <section class="mb-6 rounded-md border-l-4 border-blue-400 bg-blue-50 p-4 text-sm text-slate-700">
      <h2 class="mb-1 font-semibold text-slate-900">So liest du dieses Dashboard</h2>
      <p>
        Wir vergleichen alle Apartments im Untersuchungsbereich nach Größe und
        Preisklasse. Die <em>Marktübersicht</em>-Tabelle zeigt pro Feld:
        durchschnittliche Bewertungen (Indikator für Nachfrage), Anzahl
        Wettbewerber und Mittel-Preis. Die <em>Empfehlung</em> unten fasst
        zusammen, welches Feld am attraktivsten erscheint.
      </p>
    </section>

    <section class="mb-6 rounded-lg border border-slate-200 bg-white p-4">
      <h2 class="text-xs font-medium uppercase tracking-wide text-slate-500">
        Untersuchungsbereich
      </h2>
      <p class="mt-1 text-lg font-semibold text-slate-900">{{ search_config.name }}</p>
      <p class="text-sm text-slate-500">
        {{ city_label }} — {{ search_config.district_slugs|map("title")|join(", ") }}
      </p>
    </section>

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
        Vergleich
      </button>
    </nav>

    <section id="matrix-region">
      {% include "_matrix_region.html" %}
    </section>

    <footer class="mt-10 flex justify-between border-t border-slate-200 pt-3 text-xs text-slate-500">
      <div>
        {% if latest_run %}
          Datenstand · {{ latest_run_date_de }} · {{ latest_run.listings_seen }} Apartments
        {% else %}
          Noch kein Crawl gelaufen.
        {% endif %}
      </div>
      <div>
        {% if latest_run %}
          {% if latest_run.status == 'completed' %}
            vollständig erfasst
          {% else %}
            Status: {{ latest_run.status }}
          {% endif %}
        {% endif %}
      </div>
    </footer>

  {% endif %}
{% endblock %}
```

- [ ] **Step 6: Tests laufen lassen, Erfolg verifizieren**

Run: `uv run pytest tests/test_web.py -v`
Expected: PASS — die 5 neuen Tests grün, `test_dashboard_renders_matrix_and_panel` grün (mit der geänderten Assertion). Bestehende Tests für `/matrix`-Partials und Health/Static bleiben grün.

- [ ] **Step 7: Volle Suite**

Run: `uv run pytest -q`
Expected: 68 Tests grün (4 neue + 1 ersetzter Empty-State = +5 neue Assertions; aber die Test-Anzahl steigt nur um die Differenz aus „neu" minus „entfernt" — netto +4 Tests, also 72).

Hinweis: Die genaue Test-Zählung hängt davon ab, wie pytest die Datei sammelt. Wichtig ist: alle Tests grün, keine Regression.

- [ ] **Step 8: Commit**

```bash
git add airbi/web/routes.py airbi/web/templates/dashboard.html tests/test_web.py
git commit -m "feat: Dashboard Page-Chrome in Klartext (Onboarding, Untersuchungsbereich, Footer)"
```

---

## Task 2: _matrix_region.html — Matrix-Card-Header + Tabelle + Tooltips

**Files:**
- Modify: `airbi/web/templates/_matrix_region.html`
- Modify: `tests/test_web.py`

Ziel: Matrix-Card-Header, Badge, Tabellen-Achsen-Labels, Zeilen-Beschriftungen (Klartext-Schlafzimmer), Zellen-Inhalte mit neuen Begriffen, Tooltips. Top-Apartments und Empfehlungs-Block werden in Task 3 / 4 angefasst.

- [ ] **Step 1: Failing Tests in `tests/test_web.py` anpassen / ergänzen**

Im existierenden `test_dashboard_renders_matrix_and_panel`:

Ersetze

```python
    assert "Segment-Matrix" in body
```

durch

```python
    assert "Marktübersicht" in body
```

Ersetze

```python
    assert "Proxy" in body
```

durch

```python
    assert "geschätzte Nachfrage" in body
```

Im existierenden `test_matrix_partial_returns_single_district`:

Ersetze

```python
    assert "Segment-Matrix — Marvila" in body
    assert "Segment-Matrix — Beato" not in body
```

durch

```python
    assert "Marktübersicht Marvila" in body
    assert "Marktübersicht Beato" not in body
```

Im existierenden `test_matrix_partial_returns_two_matrices_for_both`:

Ersetze

```python
    assert "Segment-Matrix — Marvila" in body
    assert "Segment-Matrix — Beato" in body
```

durch

```python
    assert "Marktübersicht Marvila" in body
    assert "Marktübersicht Beato" in body
```

Am Dateiende anhängen:

```python
def test_matrix_uses_klartext_size_labels(client, db_session):
    _seed_marvila(db_session)
    response = client.get("/")
    body = response.text
    # Klartext-Größen-Beschriftungen in Matrix-Zeilen
    assert "1 Schlafzimmer" in body
    assert "2 Schlafzimmer" in body
    assert "3+ Schlafzimmer" in body
    # Studio bleibt "Studio"
    assert "Studio" in body
    # Tabellen-Ecke
    assert "Apartment-Größe" in body
    assert "Preisklasse" in body


def test_matrix_cell_uses_klartext_metrics(client, db_session):
    _seed_marvila(db_session)
    response = client.get("/")
    body = response.text
    # Belegte Zelle: "X Bew./Apt" und "Y Wettb. · €Z/N."
    assert "Bew./Apt" in body
    assert "Wettb." in body
    assert "/N." in body  # Tarif-Suffix


def test_matrix_thin_marker_in_klartext(client, db_session):
    _seed_marvila(db_session)
    response = client.get("/")
    body = response.text
    # Dünn-Marker neuer Text
    assert "Stichprobe klein" in body
    # Alter Marker NICHT mehr vorhanden
    assert ">dünn<" not in body  # spezifisch das Marker-Tag, nicht das Wort generell


def test_matrix_empty_cell_uses_em_dash(client, db_session):
    _seed_marvila(db_session)
    response = client.get("/")
    body = response.text
    # Em-Strich für leere Zellen (statt "leer")
    assert "—" in body
    # Alter Text NICHT mehr vorhanden
    assert ">leer<" not in body
```

- [ ] **Step 2: Tests laufen lassen, Fehlschlag verifizieren**

Run: `uv run pytest tests/test_web.py -v`
Expected: FAIL — die 4 neuen Tests + die angepassten Assertions in den bestehenden Tests scheitern.

- [ ] **Step 3: Matrix-Card-Header + Tabellen-Achsen in `_matrix_region.html` umschreiben**

In `airbi/web/templates/_matrix_region.html` den `<header>`-Block der `<article>` ersetzen:

Alter Block:

```html
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
```

Neuer Block:

```html
        <header class="mb-4 flex items-baseline justify-between">
          <h2 class="text-lg font-semibold">
            Marktübersicht {{ matrix.district_slug.title() }}
          </h2>
          <span class="rounded bg-slate-100 px-2 py-0.5 text-xs uppercase
                       tracking-wide text-slate-500"
                title="Wir können Buchungen nicht direkt zählen. Mehr Bewertungen ≈ mehr Buchungen über die Lebenszeit (Annahme: ~{{ (matrix.review_rate * 100)|round|int }}% der Gäste bewerten).">
            geschätzte Nachfrage ⓘ
          </span>
        </header>
```

- [ ] **Step 4: Den existierenden `<p>`-Absatz mit `{{ matrix.recommendation }}` entfernen**

Den Block

```html
        <p class="mb-4 text-sm leading-relaxed text-slate-700">
          {{ matrix.recommendation }}
        </p>
```

aus dem Template entfernen. Diese Recommendation rendert Task 4 neu am unteren Ende der Card.

- [ ] **Step 5: Tabellen-Header und Zeilen-Beschriftung umschreiben**

Den Tabellen-`<thead>`-Block

```html
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
```

ersetzen durch

```html
            <thead>
              <tr>
                <th class="w-32 text-left text-xs font-medium uppercase
                           tracking-wide text-slate-500">Apartment-Größe ↓ / Preisklasse →</th>
                {% for tier in matrix.price_tiers %}
                  <th class="px-2 py-1 text-left text-xs font-medium uppercase
                             tracking-wide text-slate-500">{{ tier }}</th>
                {% endfor %}
              </tr>
            </thead>
```

In der `<tbody>`-Schleife — den existierenden Zeilen-Header `<th>{{ size }}</th>` durch eine Klartext-Variante ersetzen. Den Block

```html
              {% for size in matrix.size_classes %}
                <tr>
                  <th class="px-2 py-1 text-left text-xs font-medium
                             text-slate-500">{{ size }}</th>
```

ersetzen durch

```html
              {% for size in matrix.size_classes %}
                <tr>
                  <th class="px-2 py-1 text-left text-xs font-medium
                             text-slate-500">
                    {% if size == "Studio" %}Studio
                    {% elif size == "1BR" %}1 Schlafzimmer
                    {% elif size == "2BR" %}2 Schlafzimmer
                    {% elif size == "3BR+" %}3+ Schlafzimmer
                    {% else %}{{ size }}{% endif %}
                  </th>
```

- [ ] **Step 6: Zellen-Inhalt umschreiben (Klartext + Tooltips + Marker)**

Den Zellen-`<td>`-Block

```html
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
```

ersetzen durch

```html
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
                               {% endif %}"
                        title="{{ size }} · {{ tier }} — Durchschnittliche Bewertungen je Apartment, Anzahl Wettbewerber und Mittel-Preis pro Nacht. Empfehlung wird per Bewertungen ÷ Wettbewerber bestimmt.">
                      {% if cell.n == 0 %}
                        <span class="text-xs">—</span>
                      {% else %}
                        <div class="text-xs">
                          {% if cell.is_thin %}
                            <span class="rounded bg-white/60 px-1
                                         text-[10px] uppercase text-slate-500">Stichprobe klein</span>
                          {% endif %}
                          <span class="font-semibold">
                            {{ cell.score|round(0)|int }} Bew./Apt
                          </span>
                        </div>
                        <div class="text-[11px] opacity-80">
                          {{ cell.n }} Wettb. ·
                          €{% if cell.adr %}{{ cell.adr|int }}{% else %}–{% endif %}/N.
                        </div>
                      {% endif %}
                    </td>
                  {% endfor %}
```

- [ ] **Step 7: Tests laufen lassen, Erfolg verifizieren**

Run: `uv run pytest tests/test_web.py -v`
Expected: PASS — alle Tests grün, inklusive der 4 neuen + der angepassten Assertions.

- [ ] **Step 8: Volle Suite**

Run: `uv run pytest -q`
Expected: alle Tests grün.

- [ ] **Step 9: Commit**

```bash
git add airbi/web/templates/_matrix_region.html tests/test_web.py
git commit -m "feat: Marktübersicht-Tabelle in Klartext (Größen, Metriken, Tooltips)"
```

---

## Task 3: _matrix_region.html — Top-Apartments-Sektion

**Files:**
- Modify: `airbi/web/templates/_matrix_region.html`
- Modify: `tests/test_web.py`

Ziel: „Top-Performer" wird zu „Top-Apartments" mit Sortier-Untertitel; Tier-Tag verwendet Kompaktform „1 SZ · Budget".

- [ ] **Step 1: Failing Tests in `tests/test_web.py` ergänzen**

Am Dateiende anhängen:

```python
def test_top_apartments_section_renamed(client, db_session):
    _seed_marvila(db_session)
    response = client.get("/")
    body = response.text
    assert "Top-Apartments" in body
    # Alter Begriff weg
    assert "Top-Performer" not in body


def test_top_apartments_has_sort_explanation(client, db_session):
    _seed_marvila(db_session)
    response = client.get("/")
    body = response.text
    assert "Sortiert nach Bewertungen" in body
    assert "Buchungs-Indikator" in body


def test_top_apartments_use_compact_size_tags(client, db_session):
    _seed_marvila(db_session)
    response = client.get("/")
    body = response.text
    # Kompakt-Form für Top-Apartments-Tag: "1 SZ · Budget", nicht "1BR · Budget"
    assert "1 SZ" in body or "2 SZ" in body  # je nach Fixture mind. eine Variante
    # Alter Slug-Stil bei Top-Apartments-Einträgen weg
    # (Achtung: "1BR" könnte noch in anderen Strings auftauchen, daher den
    # konkreten Tag-Pattern via `· Budget`-Kontext prüfen)
    assert "1BR · Budget" not in body
    assert "2BR · Mid" not in body
```

- [ ] **Step 2: Tests laufen lassen, Fehlschlag verifizieren**

Run: `uv run pytest tests/test_web.py -v`
Expected: FAIL — die 3 neuen Tests scheitern.

- [ ] **Step 3: Top-Apartments-Sektion in `_matrix_region.html` umschreiben**

Den Top-Performer-`<section>`-Block

```html
        <section class="mt-6">
          <h3 class="text-sm font-medium uppercase tracking-wide text-slate-500">
            Top-Performer
          </h3>
          {% if matrix.top_performers %}
            <ul class="mt-2 divide-y divide-slate-100">
              {% for perf in matrix.top_performers %}
                <li class="flex items-baseline justify-between py-2 text-sm">
                  <div>
                    {% if perf.url %}
                      <a href="{{ perf.url }}" class="font-medium text-slate-900 hover:underline"
                         target="_blank" rel="noreferrer">{{ perf.title or perf.airbnb_id }}</a>
                    {% else %}
                      <span class="font-medium text-slate-900">{{ perf.title or perf.airbnb_id }}</span>
                    {% endif %}
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
```

ersetzen durch

```html
        <section class="mt-6">
          <h3 class="text-sm font-medium uppercase tracking-wide text-slate-500">
            Top-Apartments
          </h3>
          <p class="mt-1 text-xs italic text-slate-400">
            Sortiert nach Bewertungen — dem stärksten verfügbaren Buchungs-Indikator
          </p>
          {% if matrix.top_performers %}
            <ul class="mt-2 divide-y divide-slate-100">
              {% for perf in matrix.top_performers %}
                <li class="flex items-baseline justify-between py-2 text-sm">
                  <div>
                    {% if perf.url %}
                      <a href="{{ perf.url }}" class="font-medium text-slate-900 hover:underline"
                         target="_blank" rel="noreferrer">{{ perf.title or perf.airbnb_id }}</a>
                    {% else %}
                      <span class="font-medium text-slate-900">{{ perf.title or perf.airbnb_id }}</span>
                    {% endif %}
                    <span class="ml-2 rounded bg-slate-100 px-1.5 py-0.5
                                 text-[11px] text-slate-600">
                      {% if perf.size_class == "Studio" %}Studio
                      {% elif perf.size_class == "1BR" %}1 SZ
                      {% elif perf.size_class == "2BR" %}2 SZ
                      {% elif perf.size_class == "3BR+" %}3+ SZ
                      {% else %}{{ perf.size_class }}{% endif %}
                      · {{ perf.price_tier }}
                    </span>
                  </div>
                  <div class="text-xs text-slate-500">
                    {{ perf.review_count }} Bewertungen
                    {% if perf.rating %} · ★ {{ "%.2f"|format(perf.rating) }}{% endif %}
                  </div>
                </li>
              {% endfor %}
            </ul>
          {% else %}
            <p class="mt-2 text-sm text-slate-500">
              Keine Top-Apartments mit klassifizierter Größe in diesem Bezirk.
            </p>
          {% endif %}
        </section>
```

- [ ] **Step 4: Tests laufen lassen, Erfolg verifizieren**

Run: `uv run pytest tests/test_web.py -v`
Expected: PASS — die 3 neuen Tests grün.

- [ ] **Step 5: Volle Suite**

Run: `uv run pytest -q`
Expected: alle Tests grün.

- [ ] **Step 6: Commit**

```bash
git add airbi/web/templates/_matrix_region.html tests/test_web.py
git commit -m "feat: Top-Apartments mit Klartext-Beschriftung + Sortier-Erklärung"
```

---

## Task 4: _matrix_region.html — Empfehlungs-Block neu + verschoben

**Files:**
- Modify: `airbi/web/templates/_matrix_region.html`
- Modify: `tests/test_web.py`

Ziel: Der Empfehlungs-Block, der in Task 2 oben aus dem Template entfernt wurde, kommt **unter** die Top-Apartments-Sektion und wird komplett im Template komponiert (statt `matrix.recommendation` zu rendern). Zwei Varianten: Sieger (gelb) und „zu dünn" (grau-Slate mit Hebel-Zeile).

- [ ] **Step 1: Failing Tests in `tests/test_web.py` ergänzen**

Am Dateiende anhängen:

```python
def test_recommendation_block_appears_below_top_apartments(client, db_session):
    _seed_marvila(db_session)
    response = client.get("/")
    body = response.text
    # Die Sektion ist unterhalb von Top-Apartments — Position via String-Reihenfolge
    top_idx = body.find("Top-Apartments")
    rec_idx = body.find("Empfehlung")
    assert top_idx > -1 and rec_idx > -1
    assert top_idx < rec_idx


def test_thin_recommendation_shows_lever_hint(client, db_session):
    _seed_marvila(db_session)  # Marvila Fixtures: 6 Apartments, alle Zellen dünn
    response = client.get("/")
    body = response.text
    # "Zu dünn"-Variante: Headline + Hebel-Zeile
    assert "Empfehlung — noch nicht möglich" in body
    assert "Datenbasis ist noch zu klein" in body
    assert "Hebel:" in body
    assert "Untersuchungsbereich" in body  # ist auch in der Card-Überschrift, aber zusätzlich im Hebel-Text


def test_winner_recommendation_includes_proxy_disclaimer(client, db_session):
    """Wenn eine Best-Cell existiert: Empfehlungs-Block enthält den Hinweis,
    dass die Nachfragewerte ein Indikator sind. Mit dem Seed reichen die
    Marvila-Daten nicht für eine Best-Cell. Wir nehmen daher eine zweite
    SearchConfig mit min_sample=1 und prüfen den Sieger-Block.
    """
    from decimal import Decimal
    from airbi.db.models import CrawlRun, Listing, SearchConfig, Snapshot

    cfg = SearchConfig(
        name="Test-Config-min1",
        district_slugs=["marvila"],
        classification_config={"min_sample": 1},
    )
    run = CrawlRun(search_config=cfg, status="completed", listings_seen=2)
    db_session.add(run)
    db_session.flush()
    for i, (price, reviews) in enumerate([(100, 50), (110, 60)]):
        listing = Listing(
            airbnb_id=f"W{i}", city_slug="lisboa", district_slug="marvila",
            lat=38.74, lng=-9.10, property_type="Apartment", bedrooms=1,
            size_class="1BR", title=f"Winner {i}", url=f"https://x/W{i}",
        )
        db_session.add(listing)
        db_session.flush()
        db_session.add(Snapshot(
            listing_id=listing.id, crawl_run_id=run.id,
            price=Decimal(str(price)), review_count=reviews, rating=4.7,
        ))
    db_session.flush()

    response = client.get(f"/?config_id={cfg.id}&district=marvila")
    body = response.text
    assert "Empfehlung — am attraktivsten" in body
    # Proxy-Disclaimer mit Prozentzahl
    assert "Nachfragewerte sind ein Indikator" in body
    assert "% der Gäste bewerten" in body
```

- [ ] **Step 2: Tests laufen lassen, Fehlschlag verifizieren**

Run: `uv run pytest tests/test_web.py -v`
Expected: FAIL — die 3 neuen Tests scheitern (Empfehlungs-Block existiert noch nicht in seiner neuen Form).

- [ ] **Step 3: Empfehlungs-Block am Ende der `<article>`-Card einfügen**

In `airbi/web/templates/_matrix_region.html`, **unmittelbar vor dem schließenden `</article>`-Tag** (innerhalb des `{% else %}`-Branches der `{% if not completed_run %}`-Abfrage, am Ende jeder Matrix-`<article>`), folgenden Block einfügen:

```html
        {% if matrix.best_cell %}
          {% set size, tier = matrix.best_cell %}
          {% set cell = matrix.cell(size, tier) %}
          <section class="mt-6 rounded-md border-l-4 border-amber-500 bg-amber-50 p-4">
            <h3 class="mb-1 text-xs font-semibold uppercase tracking-wide text-amber-900">
              Empfehlung — am attraktivsten
            </h3>
            <p class="text-sm text-amber-950">
              <strong>
                {% if size == "Studio" %}Studio
                {% elif size == "1BR" %}1 Schlafzimmer
                {% elif size == "2BR" %}2 Schlafzimmer
                {% elif size == "3BR+" %}3+ Schlafzimmer
                {% else %}{{ size }}{% endif %}
                · {{ tier }}.
              </strong>
              Im Schnitt {{ cell.score|round(0)|int }} Bewertungen pro Apartment bei
              {{ cell.n }} Wettbewerber{% if cell.n != 1 %}n{% endif %},
              Mittel-Preis €{% if cell.adr %}{{ cell.adr|int }}{% else %}–{% endif %}/Nacht.
            </p>
            <p class="mt-2 text-xs italic text-amber-800">
              Nachfragewerte sind ein Indikator (~{{ (matrix.review_rate * 100)|round|int }}% der
              Gäste bewerten), keine gemessene Auslastung.
            </p>
          </section>
        {% else %}
          <section class="mt-6 rounded-md border-l-4 border-slate-400 bg-slate-50 p-4">
            <h3 class="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-700">
              Empfehlung — noch nicht möglich
            </h3>
            <p class="text-sm text-slate-700">
              Die Datenbasis ist noch zu klein für eine belastbare Empfehlung.
              Wir brauchen mindestens {{ matrix.min_sample }} vergleichbare Apartments pro Feld.
            </p>
            <p class="mt-2 rounded bg-slate-100 px-3 py-2 text-xs text-slate-700">
              <strong>Hebel:</strong> Größerer Untersuchungsbereich, oder weitere Crawl-Läufe
              über Zeit — jeder bringt neue Apartments.
            </p>
          </section>
        {% endif %}
```

Hinweis zur Position: Dieser Block muss **innerhalb** der `<article>` stehen, **direkt nach** der schließenden `</section>` der Top-Apartments-Sektion (aus Task 3) und **vor** dem `</article>`-Closing-Tag. Konkret im Template-Aufbau:

```
<article>
  <header>...</header>
  <div class="overflow-x-auto"><table>...</table></div>
  <section class="mt-6"> Top-Apartments... </section>
  ← HIER der neue Empfehlungs-Block ←
</article>
```

- [ ] **Step 4: Tests laufen lassen, Erfolg verifizieren**

Run: `uv run pytest tests/test_web.py -v`
Expected: PASS — alle Tests grün, inklusive der 3 neuen Empfehlungs-Tests.

- [ ] **Step 5: Volle Suite**

Run: `uv run pytest -q`
Expected: alle Tests grün.

- [ ] **Step 6: Commit**

```bash
git add airbi/web/templates/_matrix_region.html tests/test_web.py
git commit -m "feat: Empfehlungs-Block neu formuliert + unter Top-Apartments verschoben"
```

---

## Task 5: Tailwind-Recompile + E2E-Sichtkontrolle

**Files:** keine neuen — Tailwind regeneriert `airbi/web/static/app.css`.

Ziel: Alle neuen Tailwind-Klassen (border-l-4, bg-blue-50, bg-amber-50, border-amber-500 etc.) müssen in der kompilierten `app.css` enthalten sein. Manuelle Sichtkontrolle gegen das Mockup.

- [ ] **Step 1: Tailwind-Größe VOR Recompile notieren**

Run: `wc -c airbi/web/static/app.css`
Expected: gibt die heutige Größe (ca. 13 KB) aus.

- [ ] **Step 2: Tailwind recompilieren**

Run:

```bash
./tailwindcss -i airbi/web/tailwind.src.css -o airbi/web/static/app.css --minify
```

Expected: kein Fehler. `app.css` wird neu erzeugt mit allen neuen Klassen aus den Templates.

- [ ] **Step 3: Größe NACH Recompile prüfen**

Run: `wc -c airbi/web/static/app.css`
Expected: Größe leicht größer als vorher (neue Utility-Klassen hinzugekommen — z.B. `bg-blue-50`, `border-l-4`, `border-blue-400`, `bg-amber-50`, `border-amber-500`, `bg-slate-50`, `border-slate-400`, `italic`).

Auch verifizieren, dass die neuen Klassen tatsächlich drin sind:

```bash
grep -o 'border-l-4\|bg-blue-50\|bg-amber-50\|border-amber-500\|border-slate-400\|italic' airbi/web/static/app.css | sort -u
```

Expected: jede gesuchte Klasse erscheint mindestens einmal in der Ausgabe.

- [ ] **Step 4: Volle Test-Suite**

Run: `uv run pytest -q`
Expected: alle Tests grün.

- [ ] **Step 5: Manuelle E2E-Sichtkontrolle**

Start Server:

```bash
uv run airbi web --host 127.0.0.1 --port 8000
```

Im Browser http://127.0.0.1:8000/ öffnen und gegen folgende Checkliste prüfen:

1. **Header**: „Marktübersicht — welches Apartment-Segment lohnt sich am ehesten?" sichtbar.
2. **Onboarding-Box** (blauer Linker-Rand): „So liest du dieses Dashboard" mit dem 4-Zeilen-Erklärtext sichtbar.
3. **Untersuchungsbereich-Karte**: einzeilige Card, kleines Label oben, fett der Name, darunter „Lissabon — Marvila, Beato".
4. **Filter-Buttons**: „Marvila · Beato · Vergleich" (nicht „Beide").
5. **Marktübersicht-Card**: Überschrift „Marktübersicht Marvila", Badge oben rechts „geschätzte Nachfrage ⓘ" mit Tooltip-Text (Hover).
6. **Tabelle**: Ecke „Apartment-Größe ↓ / Preisklasse →"; Zeilen „Studio / 1 Schlafzimmer / 2 Schlafzimmer / 3+ Schlafzimmer"; Zellen mit „X Bew./Apt", „Y Wettb. · €Z/N.", „Stichprobe klein"-Marker für dünne Zellen, „—" für leere; Cell-Hover zeigt Tooltip.
7. **Top-Apartments** (untere Sektion): Überschrift „Top-Apartments", Untertitel „Sortiert nach Bewertungen — dem stärksten verfügbaren Buchungs-Indikator"; Einträge mit Kompakt-Tag „1 SZ · Budget"; Reviews + Stern-Rating.
8. **Empfehlungs-Block ganz unten**: bei aktueller Datenlage grau-Slate „Empfehlung — noch nicht möglich" mit Hebel-Zeile. Bei genug Daten: gelb „Empfehlung — am attraktivsten" mit Detail + Proxy-Disclaimer.
9. **Footer**: kleine Zeile „Datenstand · 27. Mai 2026 · 25 Apartments" links, „vollständig erfasst" rechts.
10. **HTMX-Filter**: Klick auf „Beato"/„Vergleich" wechselt die Matrix-Region (`#matrix-region`).

Server beenden:

```bash
pkill -f "airbi.web.app"
```

- [ ] **Step 6: Commit (falls `app.css` sich geändert hat)**

```bash
git add airbi/web/static/app.css
git diff --cached --stat
git commit -m "chore: Tailwind-Recompile für Dashboard-Klartext-Umbau"
```

Wenn `git diff --cached --stat` 0 Zeilen anzeigt (Tailwind-Output identisch), dann ist kein Commit nötig — alle nötigen Klassen waren bereits vorhanden.

---

## Definition of Done

- [ ] `uv run pytest -q` — alle Tests grün, inklusive der neuen Dashboard- und Matrix-Tests.
- [ ] Tailwind-Recompile durchgeführt; `app.css` enthält die neuen Utility-Klassen.
- [ ] Manuelle E2E-Sichtkontrolle gegen die 10-Punkte-Checkliste aus Task 5 Step 5 erfolgreich.
- [ ] Wording aus Spec §5 ist im UI sichtbar: Marktübersicht, Untersuchungsbereich, geschätzte Nachfrage, X Bew./Apt, Y Wettb., Stichprobe klein, Top-Apartments, Empfehlung — am attraktivsten / noch nicht möglich, Hebel:, Datenstand, Lissabon.
- [ ] Empfehlungs-Block steht **unter** den Top-Apartments, nicht darüber.
- [ ] `_build_recommendation()` in `airbi/insights/segment_matrix.py` ist nicht angefasst — das Template komponiert die Empfehlung jetzt selbst.
- [ ] Alle Tasks committet.

## Bewusst NICHT in diesem Plan (Spec §10)

- Insight-Logik (Best-Cell, Score-Formel, min_sample-Default) — unverändert.
- Backend (DB, Scraper, CLI) — unverändert.
- HTMX-Active-State-Sync — bekannte Slice-1-Limitierung, separate Hygiene-Runde.
- Mehrsprachigkeit — heute nur DE.
- Detail-Listing-Ansicht im Dashboard — bleibt out-of-scope.
- Insight-First-Hero-Layout (Ansatz C) — bleibt verfügbar, falls Ansatz B nicht reicht.
