# Velocity-Modul (Teilprojekt 3) — Nachtrag

> Status: umgesetzt (2026-07-30)
> Teilprojekt 3 von 3 (1: Daten-Uhr ✓ · 2: Memo-Redesign ✓ · 3: Velocity-Modul ✓)
> Auslöser: SmartTasks #151, Freigabe Micha 30.07. — die Snapshot-Zeitreihe
> ist seit 13.07. datenreif (571 Listings ≥21 Tage Spanne, Wiki-Referenz).
> Kein eigenständiges Spec/Plan-Dokument existierte vorher — der Hook
> (`VELOCITY_AVAILABLE`) und die Formulierungs-Weiche wurden bereits im
> Memo-Redesign (`2026-06-11-investment-memo-redesign-design.md`, §8)
> vorbereitet. Dieser Nachtrag dokumentiert die tatsächliche Berechnung.

## 1. Was gebaut wurde

**Neues Modul `airbi/insights/velocity.py`** — drei Schichten wie
`segment_matrix.py`:

- **Reiner Kern:** `compute_weekly_velocity(snapshots, min_span_days=21)` —
  Reviews/Woche aus erstem und letztem Snapshot eines Listings
  (`(last_count - first_count) / span_days * 7`). None ohne mindestens 2
  Snapshots oder Spanne < `MIN_SPAN_DAYS` (21 Tage — die Wiki-dokumentierte
  Reife-Schwelle). Negative Deltas (Parser-Rauschen) werden auf 0.0
  geklippt, nie negative Nachfrage.
- **DB-Anbindung:** `compute_velocities(session, listing_ids)` lädt die
  **gesamte** Snapshot-Historie je Listing (alle CrawlRuns, nicht nur den
  aktuellen) und berechnet je Listing-ID.
- **Verdrahtung:** `attach_velocities(session, rows)` setzt
  `ListingRow.weekly_velocity` in-place für Rows mit `listing_id`.

**`segment_matrix.py`:**

- `ListingRow` um `listing_id: int | None` (DB-PK, nur für Velocity-Lookup)
  und `weekly_velocity: float | None` erweitert.
- `Cell` um `velocity: float | None` (Ø über alle Rows der Zelle mit
  Signal) und `velocity_n: int` (wie viele Rows ein Signal liefern).
- `SegmentMatrix.velocity_available: bool` — True, wenn die Best-Cell
  `velocity_n >= min_sample` hat. Ersetzt die bisher hart auf `False`
  verdrahtete Konstante `VELOCITY_AVAILABLE` in `memo.py` für echte Runs.
- `compute_segment_matrix` ruft `attach_velocities` nach dem Laden der
  Rows auf (vor `build_segment_matrix`).

**`memo.py`:**

- `AnchorStats` um `segment_velocity` / `segment_velocity_n` erweitert;
  `compute_anchor_stats` befüllt sie aus der Anker-Matrix.
- `_load_rows_for_center` (Anker-Loader) ruft ebenfalls `attach_velocities`
  auf, damit Anker-Vergleiche dieselbe Velocity-Basis haben wie der
  Heimmarkt.
- Kapitel 2 (`build_memo`): `use_velocity = velocity_available and
  bcell.velocity is not None` — nur wenn die Best-Cell selbst ein Signal
  hat, schaltet der Chip **und** der Anker-Vergleich auf Velocity-Zahlen
  um ("X,X Bewertungen/Woche je Apartment" statt "X Bewertungen je
  Apartment"). Fällt defensiv auf den Bestandswert zurück, wenn der Flag
  True ist, aber die konkrete Best-Cell (noch) kein Signal hat.
- `compute_memo` übergibt jetzt `velocity_available=home_matrix.
  velocity_available` statt der Konstante — der Hook ist real.

**Kein Schema-/Migrations-Bedarf:** alle neuen Felder leben in den
Insight-Dataclasses (`ListingRow`, `Cell`, `SegmentMatrix`, `AnchorStats`),
nicht im ORM. Kein `alembic`-Eintrag nötig.

**Kein Template-Bedarf:** `_memo.html` rendert Kapitel generisch über
`Fragment(kind, text)` — die Velocity-Formulierung kommt automatisch mit,
ohne Template-Änderung.

## 2. Beleg gegen echte Daten

`scripts/example_velocity_report.py` (Beleg-Skript, nicht Teil der
Test-Suite) rendert Segment-Matrix + Memo gegen die lokale Postgres-DB
(Stand 30.07.2026: 1.614 Listings, 9.260 Snapshots, 22 Runs seit
22.05.2026). Ergebnis für „Marvila Slice 1": `velocity_available=True`,
Vertrauens-Stufe **belastbar** (erstmals erreichbar), Kapitel 2 nennt
reale Wochenraten (z. B. 0,8 Bewertungen/Woche in 3BR+/Mid vs. 0,7 in
Alfama/Graça).

## 3. Bewusst nicht gebaut

- **Code-Aufräumen `underserved`-Pfad** (Next-Step #4 im Briefing/Wiki):
  `matrix.underserved` wird in `segment_matrix.py` weiterhin berechnet,
  ist aber seit dem Memo-Redesign in keinem Template mehr verlinkt
  (verifiziert: `grep -r underserved airbi/web/templates` → leer). Bleibt
  toter, aber gut getesteter Code — Entfernung ist eine eigene,
  risikobehaftete Aufräum-Aufgabe (viele Tests in `test_segment_matrix.py`
  hängen daran) und war nicht Teil dieses Auftrags.
- **Konfigurierbarkeit von `MIN_SPAN_DAYS`:** aktuell Modul-Konstante
  (21 Tage), nicht Teil von `SearchConfig.classification_config`. Für
  Lissabon/Marvila ausreichend; bei Multi-City ggf. nachziehen.
- **Deploy auf den VPS:** siehe `docs/DEPLOYMENT.md`, Standard-Update-Pfad
  reicht (kein Migrations-Schritt nötig, s.o.).

## 4. Test-Vertrag

- `tests/test_velocity.py` — reiner Kern (Grenzfälle: <2 Snapshots, Spanne
  zu kurz, negative Deltas, unsortierte Eingabe) + DB-Anbindung
  (`compute_velocities`, `attach_velocities`).
- `tests/test_segment_matrix.py` — Zell-Aggregation (Ø über Rows mit
  Signal, `velocity_available`-Ableitung aus der Best-Cell) + ein
  DB-Integrationstest über zwei CrawlRuns hinweg.
- `tests/test_memo.py` — Anker-Velocity (`compute_anchor_stats`), Kapitel-
  2-Weiche (Trend-Wortlaut + Velocity-Chip + Anker-Vergleich, inkl.
  defensiver Rückfall auf Bestand, wenn die Best-Cell kein Signal hat).
