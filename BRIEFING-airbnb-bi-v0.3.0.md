# BRIEFING — Airbnb BI-Tool (v0.3.0)

> **Status:** Produktspezifikation / Grundkonzept
> **Zielgruppe dieses Dokuments:** Claude Code
> **Auftraggeber:** Michael Alber (Remote Republic Labs)
> **Deployment-Ziel:** eigener Ubuntu-Server (Single-Host)
>
> **Changelog ggü. v0.2.0:** Konkreter erster Use Case fixiert (Objekt in **Marvila**, R. Cap. Leitão 86). Bezirksliste um **Marvila + Beato** (Emerging-/Kreativquartier, „Lisbon Beer District") erweitert. Acceptance-Test in Abschnitt 12 ausformuliert. Hinweis zur Klassifikations-Gewichtung in Emerging-Bezirken ergänzt.
> **Changelog v0.1.0 → v0.2.0:** AirDNA komplett aus MVP entfernt (→ Phase 2). Saisonalität entfernt. Calendar-Crawl bleibt draußen. Kern-Insight = **Segment-Matrix (Größe × Luxusklasse)**. Nachfrage über **Review-Proxies**. **Kombinierte Luxusklassifikation** (Preis-Tier + Amenity-Score) → Detail-Crawl MVP-relevant.

Dieses Briefing beschreibt das **Was** und **Warum** sowie die getroffenen Architektur-Entscheidungen. Das **Wie** auf Implementierungsebene (konkrete Libraries, Schema-Details, Modul-Interfaces, Test-Setup) darf Claude Code eigenständig schärfen und technisch aufladen — solange die hier festgelegten Leitplanken eingehalten werden.

---

## 1. Ziel & Kontext

Wir bauen ein **Business-Intelligence-Tool für Airbnb-Marktanalyse**. Es soll uns helfen, Investitionsentscheidungen für neue Kurzzeitvermietungs-Objekte datenbasiert zu treffen.

Konkreter erster Anwendungsfall: **Wir wollen ein neues Airbnb in Lissabon aufbauen.** Die zentrale Frage im ersten Schritt ist nicht „was wirft es ab", sondern eine **Richtungsentscheidung über das Produkt selbst**:

> **Welche Luxusklasse und welche Apartment-Größe sollten wir anstreben?**

Das Tool wird zweifach genutzt:
1. **Akquise-Analyse** — eine konkrete Location/Property gegen ihren Markt benchmarken.
2. **Markterkundung** — bei reiner Stadtangabe (ohne Bezirk) eine **Bezirksanalyse** liefern, die zeigt, wo welche Segmente attraktiv sind.

Das MVP fokussiert auf **Lissabon**, das Datenmodell wird aber **multi-city-tauglich** entworfen (spätere Städte ohne Schema-Migration).

**Wichtige Erwartungshaltung an die Aussagekraft:** Das MVP arbeitet rein auf Scraper-Daten (Angebotsseite) plus einem **Nachfrage-Proxy** aus Bewertungen. Es liefert damit **richtungssichere, nicht bilanzsichere** Aussagen — also verlässlich „Premium-2BR ist relativ unterversorgt und stark nachgefragt", nicht „macht X €/Monat". Genau das ist für die Produkt-Vorentscheidung das Richtige. Die harte Cashflow-Rechnung erfolgt später an der konkreten Location (und ggf. mit Phase-2-Datenquellen).

---

## 2. Leitfragen (Investment-Fragen)

In Prioritätsreihenfolge für das MVP:

1. **Welche Kombination aus Größe × Luxusklasse ist im Zielmarkt am attraktivsten** — hohe Nachfrage, überschaubare Wettbewerbsdichte, gesundes Preisniveau? *(Kern-Insight, siehe Segment-Matrix.)*
2. Welche **Segmente sind unterversorgt** (hohe Nachfrage bei geringer Konkurrenz)?
3. Wer sind die **Top-Performer** je Segment und was haben sie gemeinsam?
4. *(Phase 2)* Realisierte Performance (Occupancy/RevPAR), Saisonalität, vertiefte Amenity-Korrelationen.

---

## 3. Datenstrategie (MVP: Scraper-only)

Im MVP gibt es **eine** Quelle: den **eigenen Airbnb-Scraper**. Keine AirDNA-Anbindung, kein Calendar-Crawl.

Damit haben wir die **Angebotsseite** vollständig (existierende Objekte, geforderte Preise, Wettbewerbsdichte, Property-Merkmale, Amenities, Ratings, Review-Counts) und schätzen die **Nachfrageseite** über Proxies:

- **Review-Count (absolut):** sofort verfügbarer Beliebtheits-Proxy über die Lebenszeit eines Listings (mehr Reviews ≈ mehr realisierte Buchungen, kumuliert).
- **Review-Velocity (Delta):** Veränderung der Review-Anzahl zwischen unseren Snapshots → Buchungs-Rate-Signal. Baut sich über mehrere Wochen Snapshot-Historie auf und ist dann das aussagekräftigere Nachfrage-Maß.

**Methodische Annahme** (als konfigurierbarer Parameter anlegen): nur ein Bruchteil der Gäste hinterlässt eine Bewertung (grobe Spanne ~30–50 %). Die daraus abgeleitete Nachfrage ist ein **Proxy**, keine gemessene Occupancy — überall im UI entsprechend kennzeichnen.

> **Bewusst nicht im MVP:** AirDNA (CSV oder API), Calendar-Crawling, eigene Occupancy-Berechnung, historische/rückwirkende Saisonalität. Begründung siehe Abschnitt 11/13.

---

## 4. Datenmodell (konzeptionell)

Drei Haupt-Entities (AirDNA-Record aus v0.1.0 entfällt). Spalten/Typen/Indizes sind Sache von Claude Code — hier nur Struktur und bewusst reservierte Felder.

- **Listing** — relativ statische Stammdaten: Airbnb-ID, URL, Titel, Beschreibung, zugeordneter Bezirk, Lat/Lng, Property-Type, Zimmer/Betten/Bäder, max. Gäste, Amenities, Host-Infos, Superhost-Flag.
  → **Reserviert für Phase 2 (jetzt schon anlegen):** `license_number`, `al_status`.
  → **Abgeleitete Klassifikations-Felder:** `size_class`, `price_tier`, `amenity_score`, `luxury_class` (siehe Abschnitt 5b). Werden berechnet, nicht gescrapt.
- **Snapshot** — Zeitreihe pro Listing: Erfassungszeitpunkt, Preis, Gebühren, **Bewertungsanzahl** (Basis für Review-Velocity), Rating, Position im Suchergebnis. Die Velocity-Logik arbeitet auf den Deltas dieser Zeitreihe.
- **SearchConfig** — siehe Abschnitt 5. Zentrales Konfigurationsobjekt.

**Multi-City:** Alles hängt an einem `city`-Bezug (`city_slug`). Im MVP existiert nur Lissabon.

**Persistenz:** PostgreSQL (vanilla, kein PostGIS).

---

## 5. SearchConfig — das zentrale Konzept

Eine **SearchConfig** ist ein benannter, gespeicherter Suchkontext:

- Stadt (Pflicht)
- Bezirk(e) (0..n — leer = ganze Stadt → triggert Bezirksvergleich)
- Property-Filter (Zimmer-Range, Property-Type, Preis-Range, …)
- Crawl-Schedule (z. B. wöchentlich)
- aktive Insight-Module
- **Klassifikations-Konfiguration** (siehe 5b)

Jede SearchConfig hat **eigene Scraper-Runs und eigene Snapshot-Historie**. Parallele Szenarien sind ausdrücklich erwünscht (z. B. „Lisboa City Survey" stadtweit für den Bezirksvergleich neben einer engeren Akquise-Suche). Cross-Search-Vergleiche als optionaler Bonus-View.

### 5b. Luxusklassifikation (kombinierter Ansatz)

„Luxusklasse" ist **kein Feld, das Airbnb liefert** — wir berechnen sie. Im MVP **kombiniert** aus zwei Achsen:

1. **Preis-Tier (Grobachse):** Perzentile des geforderten ADR **innerhalb des jeweiligen Bezirks** → z. B. Budget / Mid / Premium / Luxury. Läuft allein auf Card-Daten, sofort verfügbar.
2. **Amenity-Score (Verfeinerung):** gewichteter Score aus ausstattungs- und qualitätsbezogenen Merkmalen (z. B. Pool, Dachterrasse/Aussicht, Design-/Ausstattungsmerkmale, Fläche bzw. Komfort pro Gast, Superhost, Rating-Niveau). Braucht **Detail-Crawl-Daten**.

Die finale `luxury_class` entsteht aus der Verschneidung beider Achsen. **Alle Schwellen, Tier-Grenzen und Score-Gewichte sind konfigurierbar** (Teil der SearchConfig), damit Michael selbst justieren kann, was für das jeweilige Projekt „Luxury" bedeutet. Sinnvolle Defaults vorgeben, aber nicht hartkodieren.

---

## 6. Scraper — zweistufige Strategie

Oberstes Prinzip: **so menschlich wie möglich, so wenig Requests wie nötig.** Ein geblockter Scraper ist schlimmer als ein langsamer.

- **Stufe A — Search-Crawl** (automatisch, nach Schedule): durchblättert Suchergebnisse, zieht „Card"-Daten (ID, Titel, Preis/Nacht, Rating, **Review-Count**, Zimmer, Lat/Lng, Bild-URL). Unauffällig, deckt Wettbewerbsdichte, Preis-Tier und den Review-Proxy ab.
- **Stufe B — Detail-Crawl** (MVP-relevant geworden): liefert die volle Ausstattungsliste, die der **Amenity-Score** zwingend braucht. Statt flächendeckend ein **repräsentatives Sample pro Segment** (Preis-Tier × Größe) crawlen — genug pro Zelle für einen robusten Score, plus die jeweiligen Top-Performer. So bleibt das Request-Volumen kontrollierbar und das Detection-Risiko gering. Sample-Größe pro Segment als konfigurierbarer Parameter.

**Calendar-Crawling bleibt explizit ausgeschlossen** (stärkster Schutz bei Airbnb; ohne realisierte Occupancy-Pflicht im MVP nicht nötig).

**Anti-Detection-Leitplanken** (Detailausgestaltung durch Claude Code):
- Browser-Automation mit Stealth-Ansatz, keine reinen HTTP-Requests.
- **Residential Proxies** — Datacenter-IPs sind unbrauchbar.
- Randomisiertes, menschliches Pacing inkl. längerer Pausen; kein gleichmäßiges Polling.
- Session-Persistenz über Runs.
- Rate-Limit pro IP/Subnet; defensives Retry/Backoff.
- **Monitoring/Alerting** bei Blocks oder einbrechender Datenqualität.

---

## 7. Geo-System (MVP: kuratierte Tourismus-Bezirke)

Lissabon hat parallele Geo-Systeme (offizielle Freguesias vs. umgangssprachliche Tourismus-Bezirke). Im MVP nutzen wir **ausschließlich kuratierte Tourismus-/Quartiers-Bezirke**. Initiale Liste:

- **Tourist-Kern:** Alfama, Bairro Alto, Chiado, Mouraria, Príncipe Real, Graça, Baixa, Belém, …
- **Emerging/Kreativ:** **Marvila, Beato** (östliches Flussufer, „Lisbon Beer District" — ehemaliges Industrieviertel, jetzt Kreativ-/Ausgehquartier mit Lagerhallen-Umbauten). **Hier liegt das erste Zielobjekt (R. Cap. Leitão 86).**

- Bezirke als **GeoJSON-Polygone** (kuratiert/gepflegt, nicht aus Live-Quelle).
- Listings über **Lat/Lng per Point-in-Polygon** zuordnen (in-Python, z. B. `shapely` — **kein PostGIS**).
- Bei Stadt-only-Query: Aggregation auf Bezirks-Level.

> **Hinweis Emerging-Bezirke:** Marvila/Beato sind noch nicht gesättigt — geringe Wettbewerbsdichte bei wachsender, aber unreifer Nachfrage und abweichendem Gästeprofil. Das ist genau das Szenario, für das die „Nachfrage ÷ Wettbewerbsdichte"-Logik gedacht ist. Für die Luxusklassifikation in solchen Quartieren ist „Luxury" eher **design-/loft-getrieben** als lage-/prestigegetrieben — d. h. der **Amenity-Score sollte ggü. dem reinen Preis-Tier höher gewichtet** werden können (über die konfigurierbaren Gewichte in der SearchConfig abbildbar).

Format bewusst so, dass eine neue Stadt später nur **neue GeoJSONs + Crawl-Config** braucht, keinen Code.

---

## 8. Insight-Modul-System

Insights als **Plugin-/Modul-Ansatz** (Query-Logik + Visualisierung pro Modul, registriert sich am System). Im Dashboard wählt der Nutzer SearchConfig + Filter (Bezirk, Größe, Klasse, Zeitraum) und bekommt die aktiven Module gerendert. Modul-Interface definiert Claude Code.

**MVP-Insights:**

1. **Segment-Matrix (Kern-Insight).** Zeilen = Größe (Studio / 1BR / 2BR / 3BR+), Spalten = Luxusklasse. Pro Zelle: **Nachfrage-Proxy ÷ Wettbewerbsdichte** als Attraktivitäts-Score, mit gefordertem **ADR** danebengestellt. Sweet Spot = hohe Nachfrage, überschaubare Konkurrenz, gesundes Preisniveau. Beantwortet direkt „welche Klasse, welche Größe".
2. **Unterversorgungs-Sicht.** Hebt die Segmente/Bezirke hervor, in denen Nachfrage und Angebot am stärksten auseinanderlaufen (kann als Ranking aus der Matrix abgeleitet werden).
3. **Top-Performer-Profilierung.** Pro Segment die auffälligsten Listings (nach Review-Count/-Velocity und Rating); deren Merkmale aus dem Detail-Crawl, um Muster sichtbar zu machen.

**Phase-2-Insights:** realisierte Occupancy/RevPAR (sobald Datenquelle vorhanden), Saisonalität (über selbst gesammelte Zeitreihe oder externe Quelle), vertiefte Amenity-Korrelations-Analyse.

---

## 9. Dashboard / UI

- **FastAPI + HTMX + Tailwind** — kein Build-Step, läuft direkt auf dem Ubuntu-Server.
- Charts via Plotly o. Ä.
- Kern-Views: SearchConfig-Verwaltung (inkl. Klassifikations-Konfiguration), Bezirks-Übersicht (Stadt-Modus), Segment-Matrix-Ansicht, Top-Performer-Ansicht, Scraper-Status/-Monitoring, Detail-Crawl-Trigger.
- Überall, wo Nachfrage gezeigt wird: klare **Proxy-Kennzeichnung** (kein realisierter Wert).

---

## 10. Deployment

- Single-Host **Ubuntu-Server**.
- Services als systemd-Units (Web, Scheduler/Scraper).
- **APScheduler** für Crawl-Scheduling.
- Postgres lokal, mit Backup-Konzept.
- Sauberes Logging + Alerting (siehe Scraper-Monitoring).

---

## 11. Phase-2-Roadmap (nicht im MVP bauen)

- **Realisierte Performance-Daten** — AirDNA (CSV-Import oder API) oder vergleichbare Quelle, um den Review-Proxy durch echte Occupancy/RevPAR zu ersetzen bzw. zu kalibrieren.
- **Saisonalität** — entweder über mehrere Monate selbst gesammelte Snapshot-Zeitreihe oder über die o. g. externe Quelle.
- **AL-Lizenz-Layer (Portugal):** Abgleich gegen das öffentliche Register von Turismo de Portugal + „Zonas de Contenção" der Câmara Municipal de Lisboa. **Investitionsentscheidend** für Lissabon, bewusst nach hinten geschoben. Schema-Felder sind reserviert.
- **Multi-City-Ausbau** (GeoJSONs + Crawl-Config).
- **Vertiefte Amenity-Korrelationen** und optional Custom-Polygon-Zeichnen im UI.
- *(Optional, mit Risiko-Abwägung)* Calendar-Crawl als zusätzlicher Nachfrage-/Saisonalitäts-Proxy.

---

## 12. Erster Use Case & Acceptance-Test

**Zielobjekt:** R. Cap. Leitão 86, 1950-052 Lisboa — Bezirk **Marvila** (GPS ~38.7390, -9.1044). Emerging-Quartier am östlichen Flussufer.

**Aufgabe des Tools:** Die **Location ist fix**, gesucht ist die **empfohlene Größe × Luxusklasse** für ein neues Listing an dieser Adresse. Das Tool soll die Produktentscheidung stützen, nicht den Cashflow vorhersagen.

**Acceptance-Test-Szenario:**

> Nutzer öffnet das Dashboard → wählt (oder legt an) eine SearchConfig für Lissabon → filtert auf Bezirk **Marvila** (optional inkl. Beato als Vergleich) → und sieht:
> 1. die **Segment-Matrix** (Größe × Luxusklasse) für Marvila, mit dem attraktivsten Feld (höchste Nachfrage ÷ Wettbewerbsdichte bei gesundem ADR) klar markiert;
> 2. die **Wettbewerbsdichte** je Segment (wie viele vergleichbare Objekte existieren bereits);
> 3. die **Top-Performer** in Marvila mit ihren gemeinsamen Merkmalen (Detail-Crawl-Sample);
> 4. eine klare **Empfehlung in Worten**: „Für diese Lage ist Segment X (z. B. Premium-1BR-Loft) am attraktivsten, weil …" — inkl. Proxy-Kennzeichnung der Nachfragewerte.
>
> **Bonus:** Vergleich Marvila ↔ angrenzende Bezirke, um die Emerging-Dynamik einzuordnen (lohnt sich early-mover hier oder ist ein etablierterer Nachbarbezirk sicherer?).

Da Marvila ein Emerging-Bezirk ist (geringe Konkurrenz, unreife Nachfrage), ist dies bewusst ein **anspruchsvoller Test** für die Kernlogik des Tools — wenn die Matrix hier ein plausibles Sweet-Spot-Feld liefert, ist das Konzept tragfähig.

---

## 13. Out of Scope (MVP — bewusst NICHT bauen)

- AirDNA / externe Performance-Daten (jegliche Anbindung).
- Calendar-Scraping / eigene Occupancy-Berechnung.
- Saisonalität / historisch-rückwirkende Zeitreihen.
- PostGIS / dynamische Geo-Quellen.
- AL-Lizenz-Layer.
- Multi-City über Lissabon hinaus.
- Automatisches Pricing / Realtime-Features.

---

*Version 0.3.0 — Grundkonzept mit fixiertem erstem Use Case (Marvila). Technische Vertiefung (Schema-DDL, Modul-Interfaces, Anti-Detection-Implementierung, Scoring-/Velocity-Logik, Test-Strategie) erfolgt durch Claude Code auf Basis dieser Spezifikation.*
