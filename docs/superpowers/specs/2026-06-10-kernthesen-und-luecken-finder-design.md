# Kernthesen + Lücken-Finder — Design

> Status: in Produktion (2026-06-10)
> Stakeholder-Auslöser: „was sind hier die Kernthesen? das Ding ist
> unübersichtlich." plus „die Empfehlung ist eindimensional — was ist mit
> Lücken, die vielleicht gefüllt werden können?"

## 1. Ziel

Zwei Lücken im Dashboard schließen, die ein erster Stakeholder identifiziert
hat:

1. **TL;DR fehlt.** Wer das Dashboard aufmacht, muss durch Hero, Brief,
   Matrix, Chancen, Karte und Top-Apartments scrollen, bevor er einen
   Satz auf die Hand bekommt, mit dem er in einem Investment-Meeting
   sprechen kann. Wir liefern oberhalb des Hero pro Radius **drei bis
   vier ausformulierte Kernthesen** in Klartext.
2. **Empfehlung ist eindimensional.** Wir empfehlen die Best-Cell —
   das ist „join the winners". Daneben gibt es aber Konstellationen,
   in denen die Best-Cell saturiert ist und ein bisher unbesetztes
   Segment direkt daneben starke Nachfrage zeigt. Der **Lücken-Finder**
   meldet diese „weißen Flecken" als Pionier-Alternative.

Beide Features sind **rein abgeleitet** aus bereits berechneten Matrix-
Feldern. Keine neue Datenquelle, kein zusätzlicher Crawl.

## 2. Lücken-Finder (Backend)

### 2.1 `GapCandidate` (neu)

```python
@dataclass
class GapCandidate:
    size_class: str
    luxury_class: str
    n: int                              # eigene Cell-Anzahl (0..min_sample-1)
    adjacency_score: float              # Mittelwert der Nachbar-Scores
    strongest_neighbor_size_class: str
    strongest_neighbor_luxury_class: str
    strongest_neighbor_label: str       # "1 Schlafzimmer · Luxury"
    strongest_neighbor_n: int
    strongest_neighbor_score: float
    rationale: str                      # Begründungs-Text für die UI
```

Liegt auf `SegmentMatrix.gap_cell: GapCandidate | None`.

### 2.2 Algorithmus `_find_gap_cell`

```
threshold := median(score) über alle Cells mit n > 0
für jede Cell (size, lux) mit n < min_sample:
    neighbors := Cells {(size±1, lux), (size, lux±1)} mit n > 0
    wenn neighbors leer: skip
    adj_score := mean(score) über neighbors
    sammeln: (adj_score, size, lux, n, strongest_neighbor)

sortieren nach adj_score desc, ersten Eintrag mit adj_score ≥ threshold zurück
```

Schwellenwert ist absichtlich der Median, nicht ein fester Wert: in
einer schwachen Lage qualifiziert sich eine Lücke weniger schnell als in
einer starken — der Schwellenwert skaliert mit dem Markt.

### 2.3 Was als „Cell-Nachbar" zählt

Adjazenz in der Matrix `SIZE_CLASSES × LUXURY_CLASSES`:

```
                Budget   Mid    Premium Luxury
       Studio    ·       ·       ·       ·
       1BR       ·       ·       ·       ·
       2BR       ·       ·       ·       ·
       3BR+      ·       ·       ·       ·
```

Direkte Nachbarn einer Cell sind die ±1 in einer der beiden Achsen,
NICHT die Diagonale. Damit ist die „Distanz" interpretierbar als
„eine Klassen-Stufe größer/kleiner" bzw. „eine Preisklasse höher/
niedriger".

### 2.4 Begründungs-Komposition

Für die UI-Formulierung („nächstgrößere Wohnungs-Kategorie im selben
Luxury-Segment") wird die Richtung zwischen Gap und stärkstem Nachbar
aus den rohen Klassen-Indizes abgeleitet. Der Generator unterscheidet
drei Fälle:
- Nachbar ist kleinere Größe im gleichen Luxury-Segment
- Nachbar ist größere Größe im gleichen Luxury-Segment
- Nachbar ist andere Luxusklasse in derselben Größe

## 3. Kernthesen-Generator (Backend)

### 3.1 `Kernthese` (neu)

```python
@dataclass
class Kernthese:
    label: str          # "These 1", "These 2", …
    headline: str       # fettes Lead-Statement
    detail: str         # ergänzender Beleg/Erklärung
```

Liegt auf `SegmentMatrix.kernthesen: list[Kernthese]`.

### 3.2 Generator-Regel `_build_kernthesen`

Ohne `best_cell` (Datenbasis zu dünn) liefert der Generator eine leere
Liste — das Tool spricht nicht, wenn es nichts zu sagen hat.

| Position | Titel im Code | Datenquelle | Pflicht? |
|----------|---------------|-------------|----------|
| These 1 | Stärkste Position | `best_cell.n`, `score`, `radius_km` | ja (sobald Best-Cell existiert) |
| These 2 | Preisniveau | `best_cell.adr`, `profile.price_min/max` | nur wenn `adr` da |
| These 3 | Erfolgs-Profil | `top_performer_profile.median_bedrooms/beds/max_guests`, `common_amenities` | nur wenn Profil mit Bedrooms |
| These 4 | Mögliche Marktlücke | `gap_cell` | nur wenn Lücken-Finder fündig |

Labels werden über `_kernthese_label(i)` als `These N` formatiert, nicht
als `T1` o.ä.

### 3.3 Sprach-Regeln

- **Kein Tool-Jargon.** Verboten in Headlines wie Details: `Nachbar-Cell`,
  `Demand-Signal`, `Sweet-Spot`, `Best-Cell`, `Bew./Apt`, `First-Mover`,
  `Pricing-Window`, `Pricing-Fenster`, `TL;DR`. Verbot ist als Test in
  `tests/test_segment_matrix.py::test_kernthesen_have_no_internal_jargon`
  einzementiert.
- **Längere Fließtexte statt Telegrammstil.** Headline + Detail
  zusammen 2–4 Sätze; Stakeholder soll am Stück lesen können.
- **Belege explizit machen.** Jede Aussage nennt die Zahl, auf der sie
  basiert (Anzahl Wettbewerber, Bewertungs-Schnitt, Preis-Spannweite).

### 3.4 Amenity-Stop-Liste

`_GENERIC_AMENITY_TOKENS` schließt Items aus, die in fast jedem Listing
vorkommen und damit keine Differenzierungsaussage erlauben (Bed linens,
Carbon monoxide alarm, Smoke alarm, Essentials, Hangers, Iron, Hot
water, Heating, …). Nur Amenities mit Share ≥ 50 % UND außerhalb der
Stop-Liste qualifizieren sich für These 3.

### 3.5 Amenity-Übersetzungs-Map

`_AMENITY_DE` mappt ~45 häufige englischsprachige Airbnb-Amenities auf
deutschen Klartext (Workspace → Arbeitsplatz, Dining table → Esstisch,
River view → Flussblick, Air conditioning → Klimaanlage, Hot tub →
Whirlpool, …). `_translate_amenity(name)` liefert den deutschen Namen
oder den Originalnamen, falls unbekannt. Das Map ist ohne Code-Änderung
erweiterbar.

## 4. UI (Frontend)

### 4.1 Layout-Regel pro Radius-Region

In dieser Reihenfolge:

1. **Kernthesen-Karte** (`<section>`, weiß, gerundet) — TL;DR oben.
2. **Hero** (dunkler Gradient mit Best-Cell-Empfehlung) — wenn
   gleichzeitig eine Lücke existiert: Eyebrow wird zu „A · Mainstream-
   Empfehlung", die Hero-Karte rundet alle vier Ecken (statt nur oben)
   und bekommt `mb-2`.
3. **Pionier-Strip** (amber, kleiner als Hero) — nur wenn Lücke existiert.
   Eyebrow „B · Pionier-Alternative".
4. **Investment-Brief** (`<details>`, ausklappbar) — wenn Lücke existiert:
   eigene rounded-Karte statt am Hero kleben.
5. Matrix, Chancen, Karte, Top-Apartments (unverändert).

Die Karten 2–4 bilden zusammen das Empfehlungs-Trio; die Kernthesen-Karte
oben ist die Stakeholder-Hülle drumherum.

### 4.2 Kernthesen-Karte (Marginalia-Stil)

```html
<section class="rounded-2xl border bg-white px-6 py-5 mb-3 shadow-sm">
  <div class="text-[10px] uppercase tracking-[0.12em] text-slate-500 mb-4">
    Kernthesen — Umkreis 2 km
  </div>
  <ol class="space-y-4">
    <li class="border-l-2 border-slate-200 pl-4">
      <div class="text-[10px] uppercase tracking-[0.12em] text-slate-500 mb-1">These 1</div>
      <p class="text-[13px] leading-relaxed">
        <span class="font-semibold text-slate-900">{Headline}</span>
        <span class="text-slate-700">{Detail}</span>
      </p>
    </li>
    …
  </ol>
</section>
```

Vertikale Linkslinie als visueller Marker pro These — kein Chip, weil
„These 1" als Label zu lang dafür ist und Kontrast-Chips dem TL;DR-
Charakter nicht helfen.

## 5. Test-Vertrag

Im Kern-Testset sind festgenagelt:

- `test_gap_cell_detects_white_spot_with_strong_neighbor` — Algorithmus
  findet die Studio-Luxury-Lücke, Adjazenz-Score = 200, stärkster Nachbar
  korrekt verlinkt.
- `test_gap_cell_none_when_no_listings` — leere Eingabe → kein Crash.
- `test_kernthesen_generated_from_best_cell_and_profile` — Labels in
  Reihenfolge „These 1/2/3", Inhalte enthalten Pflicht-Tokens.
- `test_kernthesen_t3_skips_generic_amenities` — Bed linens/Carbon
  monoxide alarm/Smoke alarm dürfen nicht im Output stehen.
- `test_kernthesen_t3_translates_english_amenity_names` — Dedicated
  workspace → Arbeitsplatz, Dining table → Esstisch.
- `test_kernthesen_t2_uses_german_preisrahmen_not_pricing_window` —
  „Pricing" nirgends, „Preisrahmen" im Detail.
- `test_kernthesen_have_no_internal_jargon` — schwarze Liste mit 11
  Tool-Begriffen; jede Verletzung in Headline oder Detail einer These
  schlägt sofort an.
- `test_kernthesen_include_gap_when_pioneer_alternative_exists` — wenn
  `gap_cell` da, taucht eine These „Marktlücke" auf.
- `test_kernthesen_empty_when_no_best_cell` — ohne Datenbasis: leere
  Liste, nicht „keine Aussage" auf der Karte.

Wenn jemand künftig Texte ändert, müssen mehrere dieser Tests bewusst
angefasst werden — der Stakeholder-Vertrag bricht nicht still.

## 6. Bewusst nicht gebaut

- **Über-Radien-Robustheit.** Die ursprüngliche „T2" aus dem Kernthesen-
  Brainstorming (Empfehlung gilt stabil über 1–3 km) lebt nicht in der
  einzelnen `SegmentMatrix`. Müsste in `dashboard.py` über alle
  Radien zentral berechnet werden — Aufwand mittel, lohnt sich erst,
  wenn ein Stakeholder explizit nach Stabilität fragt.
- **Lift-basiertes Amenity-Ranking.** Aktuell pickt These 3 die häufigsten
  differenzierenden Amenities. „Lift" (Häufigkeit im Best-Segment vs.
  Markt insgesamt) wäre präziser, der Effekt aber inkrementell.
- **Top-Vertreter-These.** Hatte das Brainstorming als T4 angedacht
  („‚Urban Oasis' führt die Top-Liste an"). Liefert nur Erwähnung des
  einen Listings; bringt weniger Substanz als die Marktlücke. Weggelassen.
- **Cross-Radius-Vergleich der Marktlücken.** Wenn dieselbe Lücke in
  zwei Radien auftaucht, ist das ein stärkeres Signal. Aktuell rechnen
  wir pro Radius isoliert.

## 7. Open Loops

- **Stakeholder-Review.** Ist jetzt bei vier Thesen + Pionier-Strip die
  Antwort auf „was sind die Kernthesen" lesbar genug? Antwort kommt aus
  der ersten Vorstellung — falls nicht, würden wir vermutlich auf
  weniger Thesen (3 statt 4) oder weitere Verkürzung gehen.
- **AL-Lizenz-Block-Sicht.** Im AL-Slice-Spec
  (2026-06-04-al-license-check-design.md) pausiert. Wenn das Feature
  wiederkommt, sollte es nicht als eigene Strip oben aufschlagen,
  sondern als Beleg/Filter IN den Thesen erscheinen.
