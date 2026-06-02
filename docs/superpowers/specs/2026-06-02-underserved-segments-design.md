# Unterversorgungs-Sicht — Design

> Status: freigegeben (2026-06-02)
> Briefing-Bezug: §8.2 ("kann als Ranking aus der Matrix abgeleitet werden")

## 1. Ziel

Zweites MVP-Insight aus dem Brief liefern: nach der einen Empfehlung im Hero
zeigen, **welche anderen Größe-×-Klasse-Kombinationen besonders unterversorgt
sind** — also wo das Verhältnis Nachfrage ÷ Wettbewerb (= `cell.score`,
Bew./Apt) hoch ist, ohne dass es die Best-Cell wurde.

## 2. Backend

### 2.1 `UnderservedSegment` (neu)

```python
@dataclass
class UnderservedSegment:
    size_class: str
    luxury_class: str
    n: int
    adr: Decimal | None
    score: float
    is_thin: bool
```

### 2.2 `_rank_underserved_segments(cells, best_cell, max_count)`

Sortiert alle Zellen mit `score != None` absteigend nach `score`,
exkludiert die Best-Cell (die im Hero steht), gibt Top-`max_count` zurück.
Thin-Zellen sind eingeschlossen — ihre `is_thin`-Markierung wird in der UI
übersetzt in ein „Stichprobe klein"-Label.

### 2.3 `SegmentMatrix.underserved: list[UnderservedSegment]`

Default leere Liste. Wird in `build_segment_matrix` nach Best-Cell-Wahl
gefüllt.

### 2.4 Konfiguration

Erweitert `DEFAULT_INSIGHT_CONFIG`:
- `underserved_max: 3`

## 3. Frontend

Neue Section in `_matrix_region.html`, eingeklemmt **zwischen Investment-Brief
und Marktübersicht**.

- Header: „Andere Chancen-Segmente"
- Untertitel: „Rangiert nach Bew./Apt — die Empfehlung im Hero wird
  übersprungen."
- Grid mit Mini-Cards, je Eintrag:
  - Größe (Klartext) · Luxusklasse
  - `cell.n` Wettbewerber · €`cell.adr` · `cell.score|round` Bew./Apt
  - Bei `is_thin`: kleines „Stichprobe klein"-Tag, leichte Abdunklung
- Bei `not matrix.underserved`: Section weggelassen.

## 4. Tests

- `_rank_underserved_segments` Sortierung + Exklusion + max_count + thin-flag.
- `SegmentMatrix.underserved` auf Builder-Ebene befüllt; Best-Cell nicht drin.
- Template rendert die Section bei vorhandenen Einträgen, lässt sie sonst weg.
- Spekulativ-Marker erscheint für thin-Zellen.

## 5. YAGNI

- Keine eigene Route.
- Keine Sortier-/Filter-UI.
- Kein „Warum unterversorgt"-Tooltip.
- Keine eigene Empfehlungs-Sprache pro Segment (nur Kennzahlen).
