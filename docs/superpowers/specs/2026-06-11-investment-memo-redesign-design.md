# Investment-Memo — Redesign des Dashboards

> Status: Design abgenommen (2026-06-11)
> Teilprojekt 2 von 3 (1: Daten-Uhr ✓ · 3: Velocity-Modul, folgt)
> Auslöser: Stakeholder-Feedback zur bisherigen Version — Begründung
> nicht überzeugend, kein Erkenntnisgewinn gegenüber manueller
> Airbnb-Recherche, Seite zu voll, Zahlen-Redundanz ohne roten Faden,
> Zahlen ohne Einordnung, Optik nicht meeting-tauglich.

## 1. Diagnose & Ziel

Das Dashboard ist in acht Slices additiv gewachsen (Kernthesen + Hero +
Pionier-Strip + Brief + Matrix + Chancen + Karte + Top-Apartments — pro
Radius). Dieselben drei Zahlen erscheinen vier- bis fünfmal, nichts ist
verankert („37 Bewertungen — ist das viel?"), und fünf parallele Radien
multiplizieren den Stapel.

Das Redesign ersetzt den Block-Stapel durch **ein durchgehendes
Investment-Memo**: Urteil → Beweisführung → Risiken → Anhang. Jede Zahl
bekommt einen Vergleichsanker, das Memo kennt seine eigene
Belastbarkeit, und die Seite erzählt eine Argumentationskette statt
Widgets zu stapeln.

## 2. Marktmodell (Backend)

### 2.1 Heimmarkt statt Radius-Fächer

Das Urteil basiert auf **genau einem Markt**: dem Heimmarkt-Radius der
SearchConfig (Marvila: **2 km** — fußläufiges Marvila/Beato). Damit gibt
es eine stabile Luxus-Kohorte; das bisherige Problem „dasselbe Apartment
wechselt je nach Radius die Luxusklasse" entfällt aus der
Argumentation.

Die Radius-Bänder (`band_radii_km`) **bleiben als Konfigurations-
Werkzeug** erhalten: städtische Configs nutzen kleine Radien, ländliche
große. Im UI leben sie nur noch im Anhang (Matrix-Explorer), nicht mehr
als parallele Dashboards.

### 2.2 Benannte Vergleichsmärkte

Neu in der SearchConfig: eine Liste von Vergleichsmärkten
(Name, Mittelpunkt, eigener kleiner Radius). Defaults für die
Marvila-Config:

| Name | Zentrum (lat, lng) | Radius | Erzähl-Rolle |
|---|---|---|---|
| Alfama/Graça | 38.714, -9.128 | 1,2 km | Reife-Maßstab: so sieht der etablierte Markt aus |
| Parque das Nações | 38.768, -9.094 | 1,5 km | Zwischen-Anker: so könnte Marvila in 5 Jahren aussehen |

Für jeden Vergleichsmarkt werden dieselben Segment-Statistiken mit der
vorhandenen `SegmentMatrix`-Mechanik gerechnet. **Klassifikation jeweils
in der eigenen lokalen Kohorte** — „Premium in Alfama" heißt Premium
relativ zu Alfama. Verglichen werden Marktpositionen (Bewertungen je
Apartment im gleichen Segment, Dichte), Preis-Anker vergleichen Mediane
direkt.

Datenlage: Der Crawl deckt bis ~6 km ab; beide Anker liegen in dichten
Ringen. **Kein zusätzliches Crawl-Volumen nötig.**

### 2.3 Schema

Zwei neue Felder auf `search_config` (Alembic-Migration):
- `home_radius_km: float | None` — der Heimmarkt-Radius
- `comparison_markets: JSON | None` — Liste `{name, lat, lng, radius_km}`

Beide nullable mit definiertem Fallback: ohne `home_radius_km` nutzt
das Memo den kleinsten Wert aus `band_radii_km` als Heimmarkt; ohne
`comparison_markets` rendert es ohne Anker-Chips (nur lokaler Median
als Bezug). So bricht die Prod-Instanz nicht, bevor das UPDATE für die
Marvila-Config eingespielt ist.

## 3. Memo-Struktur (Frontend)

Eine Seite, ein Dokument, Editorial-Stil (siehe §5). Reihenfolge:

1. **Urteil** — Segment-Empfehlung in einem Satz („2 Schlafzimmer ·
   Premium."), eine Zeile Begründungs-Kern, Vertrauens-Angabe (§4).
2. **Kapitel 1 · Der Markt vor Ort** — Wettbewerbsdichte und
   Marktcharakter, verankert: „87 Apartments — ⅓ der Dichte von
   Alfama/Graça, typisch für eine junge Lage."
3. **Kapitel 2 · Wo die Nachfrage hinläuft** — Nachfrage-Evidenz mit
   Anker-Chips: eigener Wert, lokaler Median, beide Vergleichsmärkte.
   Dieses Kapitel rüstet automatisch auf Velocity um, sobald Teil 3
   liefert (Formulierung wechselt von „hat gesammelt" zu „wird aktuell
   gebucht").
4. **Kapitel 3 · Die Alternative** — Pionier-Option aus dem
   Lücken-Finder (`gap_cell`), nur wenn vorhanden.
5. **Kapitel 4 · Was dagegen spricht** — Risiken ehrlich und konkret:
   Alter des Datenstands, Proxy-Annahme der Nachfrage, AL-Lizenz
   ungeprüft, dünne Stichproben wo zutreffend. Immer vorhanden.
6. **Anhang (zugeklappt, `<details>`)** — Matrix-Explorer (hier lebt
   der Radius-Umschalter weiter), Marktkarte, Top-Apartments, Methodik.

**Ersatzlos entfallen:** Kernthesen-Karte, Hero, Pionier-Strip,
Investment-Brief, Chancen-Karten. Ihre Inhalte gehen in den Kapiteln
auf. Die Kapitel SIND die Kernthesen.

**Ohne Datenbasis schweigt das Memo:** kein Urteil, stattdessen der
bisherige „Datenbasis zu dünn"-Hinweis mit konkreter Angabe, was fehlt.

## 4. Vertrauens-Indikator

Regelbasiert, drei Stufen. `data_age_days` = Tage seit dem letzten
completed CrawlRun; `n` = Stichprobe der empfohlenen Zelle;
`velocity_available` = Hook für Teil 3, bis dahin konstant `False`.

| Stufe | Bedingung | Wirkung |
|---|---|---|
| **belastbar** | velocity_available ∧ data_age < 7 ∧ n ≥ min_sample | normale Formulierungen |
| **solide Indizien** | data_age ≤ 14 ∧ n ≥ min_sample (heutiger Zustand) | Urteil normal, Hinweis „Verlaufsdaten bauen sich auf" |
| **dünne Datenlage** | sonst (n < min_sample ∨ data_age > 14) | Kapitel formulieren hörbar vorsichtiger und benennen, was fehlt |

Die Stufe steht beim Urteil (Punkt-Skala ●●●○ + Klartext-Label) und
steuert Formulierungsvarianten in den Kapiteln.

## 5. Stil: Editorial

Gewählt aus drei Mockup-Richtungen (Print-Memo / Editorial /
Dashboard-Kontinuität): **Editorial.**

- Markantes Urteil in großer Sans-Serif-Typo (text-2xl+, font-weight
  ~750, negatives Letter-Spacing), heller Seitenhintergrund.
- Kapitel-Header als kleine Caps-Labels („02 — Wo die Nachfrage
  hinläuft").
- **Kennzahlen als Inline-Chips** im Fließtext: eigener Wert
  emerald-hinterlegt mit Anker-Zusatz („37 Bew./Apt — 2,1× Median"),
  Vergleichswerte als neutrale slate-Chips („Alfama 52").
- Fließtext 14px, Zeilenhöhe ~1.7, Kapitel klar getrennt durch
  Weißraum, keine Karten-in-Karten-Schachtelung.

## 6. Umsetzung

- **Neues Modul `airbi/insights/memo.py`** — komponiert
  Heimmarkt-Matrix + Anker-Matrizen zu einem `Memo`-Datenobjekt
  (Urteil, Kapitel-Texte, Chips-Daten, Vertrauens-Stufe).
  `segment_matrix.py` (1000+ Zeilen) bleibt unangetastet als
  Rechen-Kern; der Kernthesen-Generator darin wird vom Memo-Generator
  abgelöst und entfällt.
- **Neue Template-Struktur** — `_memo.html` ersetzt den oberen Teil von
  `_matrix_region.html`; Anhang nutzt die vorhandenen Matrix-/Karten-/
  Top-Apartments-Bausteine weiter.
- **Migration** für die zwei SearchConfig-Felder + dokumentiertes
  UPDATE für die Marvila-Config (lokal und Prod).

## 7. Test-Vertrag

- **Jargon-Test wandert auf alle Memo-Texte** — die bestehende
  Blacklist (11 Begriffe) gilt für Urteil und alle Kapitel; erweitern
  statt aufweichen.
- Anker-Berechnung: Vergleichsmarkt-Statistik aus bekannten Fixtures
  (eigene Kohorten-Klassifikation nachgewiesen).
- Vertrauens-Stufen: alle drei Stufen + Grenzfälle (n = min_sample,
  data_age = 7/14).
- „Memo schweigt bei leerer Datenbasis" — kein Urteil ohne best_cell.
- Chips-Daten: eigener Wert + Median-Faktor + beide Anker vorhanden,
  wenn Daten da; Anker fehlt graceful, wenn Vergleichsmarkt leer.

## 8. Bewusst nicht gebaut

- **Velocity-Berechnung** — Teilprojekt 3; hier nur der Hook
  (`velocity_available`) und die Formulierungs-Weiche in Kapitel 2.
- **AL-Lizenz-Prüfung** — Kapitel 4 nennt sie als ungeprüftes Risiko;
  die pausierte AL-Slice-Arbeit (2026-06-04) würde später als Beleg in
  Kapitel 4 andocken, nicht als eigener Strip.
- **Polygon-Bezirke** — Vergleichsmärkte sind Punkt+Radius; kuratierte
  Polygone (Briefing-Idee) nur falls Punkt+Radius erkennbar schlechte
  Kohorten liefert.
- **PDF-Export des Memos** — naheliegend, aber erst auf Nachfrage.

## 9. Open Loops

- Stakeholder-Review des fertigen Memos (gleicher Test wie bei den
  Kernthesen: „Kann ich damit in ein Meeting?").
- Anker-Werte beobachten: Liefern Alfama/Graça- und
  Parque-das-Nações-Kohorten plausible Zahlen aus dem realen
  Datenbestand? (Erste Verifikation gegen den frischen Crawl-Stand der
  Daten-Uhr.)
- Wenn Teil 3 (Velocity) live ist: Vertrauens-Stufe „belastbar"
  erstmals erreichbar — Formulierungs-Weiche in Kapitel 2 dann real
  prüfen.
