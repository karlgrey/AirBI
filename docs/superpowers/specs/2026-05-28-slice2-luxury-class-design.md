# AirBI — Slice 2: Luxusklasse vervollständigen — Design / Spec

> **Status:** Design abgestimmt, bereit für Implementierungsplanung
> **Datum:** 2026-05-28
> **Grundlage:** Briefing §2 (Leitfrage 1), §5b (kombinierte Luxusklassifikation), §7 (Emerging-Gewichtung), §8 (Insights)
> **Auftraggeber:** Michael Alber (Remote Republic Labs)
> **Voraussetzung:** Slice 1 (Plan 1-3) + Parser-Cleanup + Dashboard-Klartext + VPS-Deployment auf `main`/live.

---

## 1. Einordnung

Slice 2 schließt die **halbfertige Kern-Insight**: Die Segment-Matrix beantwortet Briefing-Leitfrage 1 („welche Größe × Luxusklasse") heute nur über `price_tier` — die im Briefing §5b geforderte **kombinierte `luxury_class` (Preis × Ausstattung)** fehlt, weil Slice 1 nur einen minimalen Detail-Crawl (Raumzahlen) hatte.

Diese Runde baut den **vollen Detail-Crawl** (Amenities), berechnet einen **`amenity_score`**, verschneidet ihn mit dem Preis-Perzentil zur **`luxury_class`** und macht diese zur Spalten-Achse der Matrix. Vertikaler Durchstich: Crawl → Score → Class → Matrix → Dashboard.

## 2. Ziel

`https://airbi.remoterepublic.com` zeigt die Segment-Matrix mit der Achse **Größe × Luxusklasse** (Preis × Ausstattung), nicht mehr nur Preisklasse. `amenity_score` ist pro Listing gespeichert; `luxury_class` wird kohortenrelativ zur Abfragezeit berechnet. Die Emerging-Gewichtung (Marvila/Beato: Ausstattung höher gewichtet als Preis) ist über die SearchConfig abgebildet.

## 3. Getroffene Entscheidungen (Decision Log)

| Entscheidung | Wahl | Begründung |
|---|---|---|
| Scope | Voller vertikaler Durchstich bis Dashboard | Macht Leitfrage 1 vollständig; liefert auch die Detail-Daten für spätere Top-Performer-Profilierung |
| Verschneidung | **Gewichteter Luxus-Index** (`w_preis·price_perc + w_amenity·amenity_score`) | Konzepttreu zu §5b („Verschneidung beider Achsen"); Emerging-Gewichtung als Regler natürlich abbildbar |
| Emerging-Gewichtung | Marvila/Beato default `w_amenity=0.65` | Briefing §7: Luxus dort design-/loft-getrieben, nicht lage-/preisgetrieben |
| `amenity_score`-Speicherung | Auf `Listing` gespeichert | Listing-lokal/absolut (kohortenunabhängig), stabil |
| `luxury_class`-Berechnung | Zur Abfragezeit | Hängt am kohortenrelativen `price_percentile` (analog `price_tier`, Spec-Slice-1 §5.5) |
| Detail-Crawl | Bestehenden Crawl erweitern, kein neuer Request-Typ | PDP wird ohnehin pro Ganz-Apartment besucht; nur reichere Extraktion |
| Amenity-Quelle | `pdpPresentation.amenities.seeAllAmenitiesGroups`, nur `available=True` | In der vorhandenen Fixture verifiziert (44 Amenities, 13 Gruppen) |
| `price_tier` | Bleibt als Funktion erhalten | Rückwärtskompatibel; nicht mehr Matrix-Spalten-Achse |

## 4. Recon-Befund (Amenity-Daten in der PDP)

Verifiziert gegen `tests/fixtures/scraper/listing_detail.json`:
- Pfad: `niobeClientData[0][1].data.node.pdpPresentation.amenities.seeAllAmenitiesGroups` — Liste von 13 Gruppen.
- Jede Gruppe: `title` + `amenities`-Liste; jedes Item: `{id, available (bool), title, icon, subtitle}`.
- 44 Amenities gesamt; „Not included"-Gruppe listet `available=False`.
- Beobachtete Signal-Amenities: „River view", „City skyline view", „Waterfront", „Private patio or balcony", „Air conditioning", „Free street parking", „Self check-in", „Smart lock" — decken die §5b-Signale ab.
- Beschreibung: `pdpPresentation.descriptions.shortDescriptionHtml` / `longDescriptionHtml` (HTML).

## 5. Architektur & Code-Berührung

```
airbi/
  scraper/
    models.py          ListingDetail += amenities: list[str], description: str | None
                       ParsedListing += amenities: list[str] | None, description: str | None
    parser.py          parse_listing_detail extrahiert verfügbare Amenities + Kurzbeschreibung
    search_crawl.py    merge_detail füllt amenities/description; persist_results schreibt sie +
                       berechnet/speichert amenity_score (Config aus crawl_run.search_config)
  classification/
    amenity.py  (neu)  amenity_score(fields, config) -> float (0..1), rein
    luxury.py   (neu)  luxury_class(price_percentile, amenity_score, config) -> str, rein
    price.py           price_percentile-Helfer extrahieren/teilen (rank-Logik existiert in price_tier)
  insights/
    segment_matrix.py  Spalten-Achse luxury_class statt price_tier
  web/templates/
    _matrix_region.html  "Preisklasse" -> "Luxusklasse", Tooltip "Preis × Ausstattung"
    dashboard.html       Onboarding-Satz minimal anpassen
  db/models.py         Listing += amenity_score: float | None (Alembic-Migration)
alembic/versions/      neue Migration: listing.amenity_score
```

**Unverändert:** Geo, Crawl-Topologie/Browser, Deployment, Heat-/Best-Cell-/Empfehlungs-Logik.

## 6. Amenity-Extraktion (Parser + DB)

- `parse_listing_detail(payload)` zieht zusätzlich aus `seeAllAmenitiesGroups` alle Item-`title` mit `available == True` → flache, deduplizierte Liste. „Not included"/`available=False` verworfen. Bei fehlendem Pfad: leere Liste (defensiv, kein Crash — wie heute).
- Kurzbeschreibung aus `pdpPresentation.descriptions.shortDescriptionHtml` (bzw. `localizedString`/`content`), HTML-Tags gestrippt → `description`. Nicht ermittelbar → `None`.
- `ListingDetail` und `ParsedListing` tragen `amenities` + `description`; `merge_detail` übernimmt sie (wie heute die Raumzahlen).
- `persist_results` schreibt `amenities` (JSON) + `description` (Text) auf `Listing` und berechnet `amenity_score`.

## 7. `amenity_score` (rein, konfigurierbar — Briefing §5b)

`amenity_score ∈ 0..1`, gewichtete Summe normalisierter Teil-Scores. Defaults in `classification_config` (alle justierbar):

| Komponente | Default-Gewicht | Normalisierung |
|---|---|---|
| **View/Lage** | 0.25 | Premium-Aussicht (River/Sea/Waterfront → 1.0; City/Skyline → 0.6; sonst 0). Listen konfigurierbar. |
| **Premium-Ausstattung** | 0.30 | `min(1, anzahl_vorhandener_premium / premium_target)`, `premium_target` default 6. Premium-Liste konfigurierbar (Pool, Hot tub, AC, Balkon/Terrasse, Parking, Aufzug, Spülmaschine, Smart Lock, Gym, EV-Charger, …). |
| **Amenity-Reichtum** | 0.15 | `min(1, anzahl_verfügbarer_amenities / 40)` |
| **Komfort pro Gast** | 0.10 | `min(1, beds / max_guests)` (Fallback `bedrooms` wenn `beds` fehlt; bei fehlenden Werten 0) |
| **Superhost** | 0.10 | 1 wenn Superhost, sonst 0 |
| **Rating-Niveau** | 0.10 | `clamp((rating − 4.0) / 1.0, 0, 1)` |

Defaultgewichte summieren zu 1.0. `amenity_score` ist listing-lokal/absolut → auf `Listing` gespeichert. Fehlende Eingaben degradieren die jeweilige Komponente zu 0 (kein Crash).

## 8. `luxury_class`-Verschneidung (gewichteter Index)

- `price_percentile ∈ 0..1`: Rang des Listing-ADR im Bezirks-Kohort (gleiche Rank-Logik wie `price_tier` heute; zur Abfragezeit).
- `amenity_score ∈ 0..1`: gespeichert (§7).
- `luxury_index = w_preis · price_percentile + w_amenity · amenity_score`, `w_preis + w_amenity = 1`.
- Klassifizierung über Index-Schwellen → Budget/Mid/Premium/Luxury. Default-Schwellen `[0.25, 0.5, 0.75]` (konfigurierbar, analog `DEFAULT_PRICE_TIERS`).
- Gewichte in `classification_config.luxury_weights`. **Code-Default ausgewogen** `{preis: 0.5, amenity: 0.5}`. **Marvila-Slice-1-Config** setzt `{preis: 0.35, amenity: 0.65}` (Emerging, §7).
- `luxury_class` zur Abfragezeit berechnet (Kohortenabhängigkeit über `price_percentile`).
- Listing ohne `amenity_score` (z.B. vor Re-Crawl) → `amenity_score` als 0 behandeln; `luxury_class` weiterhin berechenbar (rein preisgetrieben).

## 9. Matrix- & Dashboard-Auswirkung

- **Segment-Matrix:** Zeilen `size_class`, Spalten **`luxury_class`** (Budget/Mid/Premium/Luxury = Preis × Ausstattung). Zell-Metriken (Bewertungen/Apt, Wettbewerber, Median-ADR) unverändert; ADR bleibt pro Zelle (Briefing-Vorgabe).
- **Dashboard:** Spaltenkopf „Preisklasse" → „Luxusklasse"; Badge/Tooltip ergänzt „Preis × Ausstattung". Onboarding-Satz minimal anpassen. Heat-/Best-Cell-/Empfehlungs-Logik unverändert (arbeiten generisch auf der Spalten-Achse).
- Cell-Tooltip ergänzt, dass die Luxusklasse Preis und Ausstattung kombiniert.

## 10. Daten (Re-Crawl)

- Bestehende 35 Listings haben keine `amenities`/`amenity_score`. Ein Re-Crawl vom Dev-Rechner (`airbi crawl --config "Marvila Slice 1"`) zieht jetzt Amenities und berechnet `amenity_score` beim Upsert.
- Danach lokale DB → Prod per Dump/Restore (Befehl in `docs/DEPLOYMENT.md`).
- Falls der Crawl blockt: kein Daten-Fälschen — die Unit-Tests sichern Parser/Score/Class ab; Daten kommen, sobald ein Lauf durchgeht. `luxury_class` funktioniert auch mit `amenity_score=0` (rein preisgetrieben) für Altbestand.

## 11. Testing

- **Parser:** `parse_listing_detail` gegen Fixture — Amenity-Titel (nur `available=True`, „Not included" raus), gestrippte Beschreibung, Raumzahlen weiterhin korrekt.
- **`amenity_score`:** Unit-Tests je Komponente + Gesamtgewichtung; Config-Override justiert Gewichte/Listen; fehlende Felder → 0 ohne Crash; bekannte Eingabe → bekannter Score.
- **`luxury_class`:** Index-Berechnung, Schwellen, Emerging-Gewichtung (gleiches `price_percentile`, höherer `amenity_score` → höhere Klasse bei amenity-lastigem Gewicht); `amenity_score=0`-Fallback.
- **Segment-Matrix:** bestehende Tests auf `luxury_class`-Achse anpassen; Aggregation/Best-Cell/Empfehlung-Logik bleibt grün.
- **persist_results:** `amenities`/`description`/`amenity_score` werden auf `Listing` geschrieben (db_session-Fixture).
- **Web:** TestClient — „Luxusklasse" statt „Preisklasse" im gerenderten HTML.
- **E2E:** Re-Crawl, Dashboard zeigt Luxusklasse-Achse + befüllte amenity_scores.

## 12. Acceptance-Kriterien

1. `uv run pytest -q` grün, inkl. neuer amenity/luxury/parser-Tests + angepasster Matrix/Web-Tests.
2. Re-Crawl schreibt `amenities`, `description`, `amenity_score` auf die Listings (Stichprobe: das 3503€-Marvila-„Architect Luxury Loft" hat hohen `amenity_score`).
3. Dashboard-Matrix zeigt Achse „Luxusklasse" (Preis × Ausstattung); Tooltip erklärt die Kombination.
4. Emerging-Gewichtung wirkt: ein Marvila-Loft mit Top-Ausstattung bei mittlerem Preis landet höher als rein preislich.
5. Migration `listing.amenity_score` sauber auf lokal + Prod angewandt.
6. Live auf airbi.remoterepublic.com nach Daten-Sync.

## 13. Out of Scope (bewusst NICHT in Slice 2)

- Top-Performer-Profilierung „was haben sie gemeinsam" (eigene Insight, Folge-Runde — nutzt dann die jetzt vorhandenen Amenity-Daten).
- Unterversorgungs-Sicht als eigenes Ranking-View (Leitfrage 2, separate Runde).
- Review-Velocity, AirDNA/Saisonalität, AL-Lizenz-Layer, Multi-City (Phase-2-Roadmap).
- Insight-Plugin-Registry.
- Amenity-Korrelations-Analyse (welche Amenities mit Nachfrage korrelieren — Phase 2).
- APScheduler/Auto-Crawl (vom Nutzer ausgeschlossen).

---

*Slice 2 macht die Kern-Insight des Tools vollständig: „welche Größe × Luxusklasse" — mit Luxus als Verschneidung aus Preis und Ausstattung, in Emerging-Bezirken bewusst ausstattungslastig gewichtet.*
