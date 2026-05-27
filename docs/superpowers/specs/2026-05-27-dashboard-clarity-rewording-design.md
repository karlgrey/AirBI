# AirBI — Dashboard-Klartext-Umbau — Design / Spec

> **Status:** Design abgestimmt (Ansatz B), bereit für Implementierungsplanung
> **Datum:** 2026-05-27
> **Grundlage:** Spec-Backlog §14 „UX/Hygiene", Plan-3-Dashboard
> **Auftraggeber:** Michael Alber (Remote Republic Labs)
> **Vorausgesetzt:** Slice 1 (Plan 1-3) + Parser-Cleanup auf `main`. Lokaler CrawlRun mit 25 Apartments liegt in der DB.

---

## 1. Einordnung

Diese Runde ist **kein** neuer Slice (kein vertikaler Durchstich), sondern ein **UX-Umbau** an der Dashboard-Schicht: Wording in Klartext + Lese-Reihenfolge umstellen. Das Backend (Insight-Berechnung, DB, Crawler) ist davon unberührt. Ziel: Dashboard von „braucht Tech-Hintergrund" zu „Investor-Briefing-tauglich".

**Auslöser:** Beim Begutachten der Slice-1-Dashboard-Ausgabe zeigte sich, dass die Begriffswelt durchgängig zu Tech-/Entwickler-sprachlich ist (`SearchConfig`, `crawl`, `N=`, `ADR`, `Ø`, `dünn`, `Segment-Matrix`, `Tier`) und die Lese-Reihenfolge (Empfehlung **über** der Matrix, bei aktuell „zu dünn"-Status frustrierend) den Investor-Wert verdeckt.

Drei Ansätze wurden im Brainstorming verglichen: A (Sprache-only), B (Sprache + Lese-Reihenfolge), C (Insight-First Umbau). **Ansatz B wurde gewählt** — beste Verständnis-pro-Aufwand-Ratio.

## 2. Ziel

- Alle technischen Begriffe im UI durch Klartext-Äquivalente ersetzen.
- Lese-Reihenfolge umstellen: Empfehlung erscheint **unter** Matrix + Top-Apartments, nicht darüber.
- Onboarding-Box („So liest du dieses Dashboard") immer sichtbar unter dem Header.
- Status-Panel als unscheinbare Footer-Zeile.
- Bei „zu dünn"-Status: konstruktive Hebel-Anleitung ohne Tech-Befehle.
- Keine Änderung an Insight-Funktionen, Datenmodell, DB, CLI, Scraper.

## 3. Getroffene Entscheidungen (Decision Log)

| Entscheidung | Wahl | Begründung |
|---|---|---|
| Ansatz | B (Sprache + Lese-Reihenfolge) | A behebt nur Jargon, lässt Layout-Probleme; C ist zu groß für diese Runde |
| Wording-Liste | Im Brainstorming festgelegt (siehe §5) | Investor-Vokabular statt Tech-Slugs |
| Empfehlungs-Position | Unter Matrix + Top-Apartments | Bei „zu dünn" verliert man Vertrauen nicht direkt; bei Erfolg ist die Schlussfolgerung am unteren Ende der Lese-Reihenfolge |
| Onboarding-Box | Dauerhaft sichtbar, nicht klappbar | Niedrigste UI-Komplexität; ein 4-Zeilen-Blob, kein versteckter Knopf |
| „Zu dünn"-Hinweis | Pragmatische Mitte: Beschreibend + 1-2 Hebel ohne CLI-Befehle | Aktiver als rein passiv, freundlicher als CLI-im-UI |
| Status-Panel | Einzeilige Footer-Zeile | Hygiene-Information, nicht Insight |
| Recommendation-Funktion | Wird im UI nicht mehr direkt gerendert; Template komponiert aus Zell-Daten | Saubere Schichten-Trennung; bestehender String-Output bleibt für Rückwärts-Kompatibilität |
| Heat-Farben, Best-Cell-Ring | Unverändert (grün-Skala, amber-Ring) | Funktionieren, sind nicht das Problem |
| Untersuchungsbereich-Karte | Eine prominent zentrierte Zeile ersetzt die zwei nebeneinander-Karten | Kontext-Info zusammenführen statt verteilen |

## 4. Architektur & Code-Berührung

Die Änderung lebt vollständig in der Web-Schicht (`airbi/web/`). Insight-Berechnungs-Code in `airbi/insights/segment_matrix.py` wird NICHT angefasst.

```
airbi/
  web/
    templates/
      base.html              ← Header-Untertitel, Footer-Slot
      dashboard.html         ← Komplette Wording-Sanierung, Onboarding-Box,
                                Untersuchungsbereich-Karte, Filter-Beschriftung,
                                Status-Panel → Footer
      _matrix_region.html    ← Komplette Wording-Sanierung, Empfehlung wandert
                                unter die Top-Performer-Liste, neue Zellen-Tooltips,
                                Top-Performer mit Sortier-Untertitel,
                                "zu dünn"-Hinweis mit Hebel-Zeile
    static/app.css           ← Tailwind-Recompile mit ggf. neuen Klassen
tests/
  test_web.py                ← Assertions auf neue Strings, alte Strings entfernen
```

**Was bleibt unverändert:**
- `airbi/insights/segment_matrix.py` — Datacontract und Berechnungs-Funktionen.
- `airbi/db/`, `airbi/scraper/`, `airbi/classification/`, `airbi/geo/`, `airbi/cli.py`.
- HTMX-Filter-Mechanik (URL-Pfade, `hx-get`, `hx-target`, `hx-swap`).
- Heat-Farben (`bg-emerald-100/200/300/500`), Best-Cell-Ring (`ring-amber-500`).
- Datenmodell, DB-Schema, alle Backend-Tests.

**Optionaler Helper:**
`airbi/web/routes.py` könnte eine kleine `_size_class_label()`-Funktion bekommen, die `"Studio"`/`"1BR"`/`"2BR"`/`"3BR+"` zu `"Studio"`/`"1 Schlafzimmer"`/`"2 Schlafzimmer"`/`"3+ Schlafzimmer"` mappt — oder das Template macht das per Jinja-Filter inline. Plan-Entscheidung: **inline im Template via `{% if %}{% elif %}`-Ladder**, weil das nur an einer Stelle (Matrix-Zeilen-Beschriftung + Top-Performer-Tag) genutzt wird und kein Wiederverwendungs-Druck besteht.

## 5. Wording-Mapping (verbindlich)

| Heute (UI-Text) | Neu (UI-Text) | Wo |
|---|---|---|
| `AirBI Dashboard` | unverändert | Header |
| `Segment-Matrix: Welche Größe × Luxusklasse ist im Zielmarkt am attraktivsten?` | `Marktübersicht — welches Apartment-Segment lohnt sich am ehesten?` | Header-Untertitel |
| — (neu) | Onboarding-Box: „So liest du dieses Dashboard / Wir vergleichen alle Apartments im Untersuchungsbereich nach Größe und Preisklasse. Die Marktübersicht-Tabelle zeigt pro Feld: durchschnittliche Bewertungen (Indikator für Nachfrage), Anzahl Wettbewerber und Mittel-Preis. Die Empfehlung unten fasst zusammen, welches Feld am attraktivsten erscheint." | Unter dem Header, blauer Linker-Rand |
| `SearchConfig` / Karten-Überschrift | `Untersuchungsbereich` | Karten-Überschrift (klein) |
| `Marvila Slice 1` | unverändert (Name der SearchConfig) | Karten-Hauptzeile |
| `lisboa · marvila, beato` | `Lissabon — Marvila, Beato` | Untertext der Karte |
| `Letzter Crawl` / `completed` / `2026-05-27 11:02 · 25 Listings` (eigene Karte oben) | `Datenstand · 27. Mai 2026 · 25 Apartments · vollständig erfasst` (Footer-Zeile, klein) | Footer (oben raus) |
| Filter `Marvila` `Beato` `Beide` | `Marvila` `Beato` `Vergleich` | Filter-Buttons |
| `Segment-Matrix — {District}` | `Marktübersicht {District}` | Matrix-Card-Überschrift |
| Badge `Nachfrage: Proxy` | Badge `geschätzte Nachfrage ⓘ` mit Tooltip-Text „Wir können Buchungen nicht direkt zählen. Mehr Bewertungen ≈ mehr Buchungen über die Lebenszeit (Annahme: ~40% der Gäste bewerten)." | Matrix-Card-Header rechts |
| Tabellen-Ecke `Größe ↓ / Tier →` | `Apartment-Größe ↓ / Preisklasse →` | Tabellen-Ecke |
| Zeilen `Studio` `1BR` `2BR` `3BR+` | `Studio` `1 Schlafzimmer` `2 Schlafzimmer` `3+ Schlafzimmer` | Zeilen-Beschriftung |
| Spalten `Budget` `Mid` `Premium` `Luxury` | unverändert | Spaltenköpfe |
| Leere Zelle `leer` | `—` (Em-Strich) | Leere Zelle |
| Belegte Zelle `Ø 43 Reviews` `N = 1 · ADR €642` | `43 Bew./Apt` `1 Wettb. · €642/N.` | Belegte Zelle |
| Dünn-Marker `dünn` | `Stichprobe klein` | Über Bewertungs-Zeile in dünner Zelle |
| Zell-Tooltip (neu) | Hover-Text mit Beispiel-Wortlaut: „Studio · Mid — Durchschnittliche Bewertungen je Apartment, Anzahl Wettbewerber und Mittel-Preis pro Nacht. Best-Cell wird per Reviews ÷ Wettbewerber bestimmt." | `title=`-Attribut je Zelle |
| `Top-Performer` (Überschrift) | `Top-Apartments` | Performer-Sektion-Überschrift |
| — (neu Untertitel) | `Sortiert nach Bewertungen — dem stärksten verfügbaren Buchungs-Indikator` | Direkt unter „Top-Apartments" |
| `1BR · Budget` (Slug-Tag) | `1 SZ · Budget` (kompakt für Liste) | Performer-Eintrag |
| Empfehlung-Block mit Sieger: `Für Marvila ist {size}-{tier} am attraktivsten — Ø {score:.0f} Reviews je Listing bei {N} Wettbewerber-Listings, Median-ADR €{adr}.` | Block: „Empfehlung — am attraktivsten" als Überschrift + Detail: „**{Size} · {Tier}.** Im Schnitt {Score} Bewertungen pro Apartment bei {N} Wettbewerbern, Mittel-Preis €{ADR}/Nacht. *Nachfragewerte sind ein Indikator (~{rate}% der Gäste bewerten), keine gemessene Auslastung.*" | Unter Top-Apartments |
| Empfehlung-Block „zu dünn": `Für {district} liefert dieser Crawl noch keine Zelle mit mindestens {min_sample} vergleichbaren Objekten — die Datenbasis ist für eine belastbare Empfehlung zu dünn.` | Block: „Empfehlung — noch nicht möglich" als Überschrift + Detail: „Die Datenbasis ist noch zu klein für eine belastbare Empfehlung. Wir brauchen mindestens {min_sample} vergleichbare Apartments pro Feld." + neue Hebel-Zeile: „**Hebel:** Größerer Untersuchungsbereich, oder weitere Crawl-Läufe über Zeit — jeder bringt neue Apartments." | Unter Top-Apartments |
| Empty-State `Noch keine SearchConfig` | `Noch kein Untersuchungsbereich angelegt` (mit Hinweis unverändert in Aussage) | Card oben |

**Größen-Kompaktform** (für Top-Apartments-Liste): `Studio` / `1 SZ` / `2 SZ` / `3+ SZ`. Volle Form (`1 Schlafzimmer` etc.) für Matrix-Zeilen-Beschriftung, weil dort Platz ist.

## 6. Layout

Die neue Seiten-Struktur (von oben nach unten):

1. **Header**: Titel + neuer Untertitel.
2. **Onboarding-Box** (blauer Linker-Rand, 4 Zeilen, immer sichtbar).
3. **Untersuchungsbereich-Karte** (eine Zeile, prominent, mittlere Größe — ersetzt die Plan-3-Doppelkarte).
4. **Bezirksfilter** (Buttons: Marvila · Beato · Vergleich — unverändert in HTMX-Verhalten).
5. **Matrix-Region** (`#matrix-region`, HTMX-Swap-Target — unverändert in Mechanik):
   - **Marktübersicht-Card** je gewählter Bezirk (1 Card im Single-View, 2 Cards nebeneinander im Vergleich-View):
     1. Card-Header mit Bezirks-Name + Badge „geschätzte Nachfrage".
     2. Matrix-Tabelle (4×4 mit neuen Beschriftungen + Zell-Tooltips, Heat-Farben + Best-Cell-Ring unverändert).
     3. **Top-Apartments-Liste** mit Sortier-Untertitel.
     4. **Empfehlungs-Block** (gelb bei Sieger / grau-Slate bei „zu dünn") — am unteren Ende der Card.
6. **Footer** (klein, dezent): „Datenstand · {Datum-deutsch} · {N} Apartments · {Status}".

Vergleich zu Plan-3:
- Onboarding-Box ist neu.
- Plan-3 hatte SearchConfig-Karte + Letzter-Crawl-Karte oben nebeneinander (jeweils gleicher Größe). NEU: nur Untersuchungsbereich-Karte oben, Datenstand wandert in den Footer.
- Empfehlung war oberhalb der Matrix-Tabelle. NEU: unten unter den Top-Apartments.
- Filter-Button-Text „Beide" wird „Vergleich".

## 7. Recommendation-Funktion: Wer formuliert den Text?

Heute liefert `airbi/insights/segment_matrix.py::_build_recommendation()` den Empfehlungssatz als String, der direkt im Template gerendert wird. Mit dem neuen, mehrteiligen Empfehlungs-Block (Headline + Detail-Paragraph + ggf. Hebel-Zeile) wäre die alte Funktion entweder zu erweitern (zweiteiliges Output-Tuple) oder das Template übernimmt die Komposition aus den Cell-Werten.

**Entscheidung:** Das Template übernimmt die Komposition. Begründung:
- Reine Schichten-Trennung: Insight produziert Daten, Template formt Worte.
- `_build_recommendation()` bleibt rückwärts-kompatibel im Datenkontrakt (`SegmentMatrix.recommendation` ist weiterhin ein String mit dem alten Format), wird aber im neuen Dashboard-Template nicht mehr direkt gerendert.
- Andere Konsumenten (z.B. spätere CLI-Reports, API-Antworten) können den fertigen String weiterhin nutzen.

Konsequenz: `_matrix_region.html` rendert den Empfehlungs-Block aus diesen vier Daten:
- `matrix.best_cell` (Tuple oder None)
- `matrix.cell(size, tier)` für die Werte (n, score, adr)
- `matrix.min_sample`, `matrix.review_rate` (für „zu dünn"-Hinweis bzw. Proxy-Hinweis)
- `matrix.district_slug` (für District-Label — bzw. eigentlich nicht im neuen Text drin, weil die Card schon mit „Marktübersicht {District}" überschrieben ist)

Damit kein `_build_recommendation()`-Aufruf mehr im UI nötig ist — der bleibt aber als Funktion erhalten.

## 8. Test-Strategie

Die UI-Tests in `tests/test_web.py` müssen angepasst werden. Die Bestands-Assertions auf alte Strings werden ersetzt durch Assertions auf die neuen.

**Anzupassende Tests:**
- `test_dashboard_renders_matrix_and_panel` — alte Assertions auf „Segment-Matrix", „completed", „Proxy" → neue Assertions auf „Marktübersicht", „Datenstand", „geschätzte Nachfrage". `cfg.name in body` bleibt, weil der Name unverändert ist. „Marvila Loft" bleibt (Top-Apartment).
- `test_dashboard_empty_state_when_no_search_config` — Text-Assertion auf „Noch keine SearchConfig" → „Noch kein Untersuchungsbereich".
- `test_matrix_partial_returns_single_district` — „Segment-Matrix — Marvila" → „Marktübersicht Marvila".
- `test_matrix_partial_returns_two_matrices_for_both` — beide District-Strings entsprechend.
- `test_dashboard_filter_buttons_use_htmx` — `hx-get` und `hx-target` bleiben strukturell identisch; ggf. zusätzlich Button-Text-Assertion für „Vergleich".

**Neue Tests:**
- `test_dashboard_has_onboarding_box` — Body enthält „So liest du dieses Dashboard".
- `test_dashboard_has_footer_with_data_status` — Body enthält „Datenstand" und die Listing-Anzahl.
- `test_top_apartments_have_sort_explanation` — Body enthält „Sortiert nach Bewertungen".
- `test_thin_recommendation_has_lever_hint` — Wenn alle Zellen dünn: Body enthält „noch nicht möglich" und „Hebel".

**Nicht angetastet:**
- `test_health_returns_ok`, `test_static_app_css_is_served` — strukturell, sind unabhängig vom Wording.
- Alle Tests in `tests/test_segment_matrix.py` — Insight-Berechnungs-Tests; bleiben unverändert.

## 9. Definition of Done

- [ ] Alle Strings aus §5 sind im UI sichtbar (Marvila, Beato, Vergleich).
- [ ] Empfehlungs-Block steht unter den Top-Apartments, nicht darüber.
- [ ] Onboarding-Box ist immer sichtbar unter dem Header.
- [ ] Status-Panel ist eine einzeilige Footer-Zeile, klein.
- [ ] Bei „zu dünn"-Status: Hinweis enthält „Hebel:" + 1-2 konkrete Vorschläge (kein CLI-Befehl).
- [ ] Zell-Tooltips (`title=`-Attribut) sind vorhanden je belegter Zelle.
- [ ] Tailwind nachkompiliert; alle neuen Klassen in `static/app.css` enthalten.
- [ ] `uv run pytest -q` — alle Tests grün; angepasste UI-Tests verifizieren die neuen Strings.
- [ ] Manuelle Sichtkontrolle gegen das Mockup (`.superpowers/brainstorm/.../layout-mockup.html`).
- [ ] Spec, Plan und Implementation committet, gemerged.

## 10. Out of Scope (bewusst NICHT in dieser Runde)

- Insight-Logik-Änderungen (Best-Cell-Auswahl, Score-Formel, min_sample-Default).
- Backend-Felder (`amenity_score`, `luxury_class`, Review-Velocity) — Slice 2.
- HTMX-Active-State-Sync nach Button-Klick (bekannte Slice-1-Limitierung — separat).
- Mehrsprachigkeit (heute nur DE; EN/PT würde I18N-Setup brauchen).
- Detail-Listing-Ansicht im Dashboard (immer noch out-of-scope; Spec §10/§14).
- Methoden-Aufklappbox aus Ansatz C (Hero-Empfehlung etc.) — falls B nicht reicht.

---

*Diese Runde macht das Dashboard für die Investor-Brille lesbar, ohne die Methodik zu verändern. Wenn der Wechsel überzeugend ist, bleibt der C-Ansatz (Insight-First) als Vertiefung verfügbar.*
