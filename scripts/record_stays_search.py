"""Öffnet die Airbnb-Suche für die Marvila+Beato-Bounding-Box, extrahiert die
eingebetteten StaysSearch-Daten aus der Seite und speichert die erste Seite als
Fixture.

Aufruf: uv run python scripts/record_stays_search.py

WICHTIG: Airbnb bettet die Suchergebnisse als serverseitig gerendertes JSON in
das Script-Tag <script id="data-deferred-state-0" type="application/json"> ein.
Es gibt KEINEN separaten POST-Request namens "StaysSearch" — die Daten kommen
direkt mit dem HTML-Dokument.

=== Ergebnisstruktur & Feld-Mapping (Spec für Task 5 — Parser) ===

Zugriffspfad zum Ergebnis-Array:
  fixture["data"]["presentation"]["staysSearch"]["results"]["searchResults"]
  (Liste von Dicts; Typ-Name: "StaySearchResult")

Felder eines einzelnen searchResults-Eintrags:

  Listing-ID (int):
    base64.b64decode(r["demandStayListing"]["id"]).decode()  →  "DemandStayListing:25532057"
    → Den Teil nach dem Doppelpunkt nehmen: int(decoded.split(":")[1])

  Titel der Seite / Property-Type + Viertel (str):
    r["title"]
    Beispiele: "Apartment in Santa Engrácia", "Boat in Lisbon", "Room in Graça"

  Listing-Name (str):
    r["demandStayListing"]["description"]["name"]
      ["localizedStringWithTranslationPreference"]

  Koordinaten (float, float):
    lat = r["demandStayListing"]["location"]["coordinate"]["latitude"]
    lng = r["demandStayListing"]["location"]["coordinate"]["longitude"]

  Property-Type / Room-Type (str):
    Aus r["title"] extrahieren: alles vor " in " ergibt den Typ.
    Beispiele: "Apartment", "Room", "Boat", "Guesthouse"

  Preis (str, formatiert mit Währungssymbol):
    r["structuredDisplayPrice"]["primaryLine"]["price"]
    Qualifier: r["structuredDisplayPrice"]["primaryLine"]["qualifier"]
    Beispiel: "€ 817", qualifier="total" → Totalpreis für Aufenthalt

  Preis pro Nacht (aus explanationData ablesen, falls vorhanden):
    r["structuredDisplayPrice"]["explanationData"]["priceDetails"][0]["items"][0]["description"]
    Format: "5 nights x € 159.40" → Preis pro Nacht parsen

  Bewertung + Anzahl Reviews (str):
    r["avgRatingLocalized"]  →  "4.86 (245)"  (Rating + Anzahl Reviews in Klammern)
    r["avgRatingA11yLabel"]  →  "4.86 out of 5 average rating,  245 reviews"

  Superhost (bool):
    any(b["loggingContext"]["badgeType"] == "SUPERHOST"
        for b in r.get("badges", []) if b.get("loggingContext"))

  Gastgeber-Typ (str, optional):
    Aus r["structuredContent"]["primaryLine"] Einträge mit type=="HOSTINFO"
    Beispiel body: "Business host", "Superhost"

  Bedrooms / Beds / Baths / Max Guests:
    NICHT in den Suchergebnissen verfügbar.
    Diese Felder sind nur über die Listing-Detail-API abrufbar (Task späterer
    Slice) und müssen in ParsedListing als Optional[int] bleiben.

  Kartenergebnisse (zusätzliche Listings, nicht in der Listenansicht):
    fixture["data"]["presentation"]["staysSearch"]["mapResults"]["mapSearchResults"]
    (gleiche Feldstruktur wie searchResults, aber separater Array)

Daten-Container im Fixture:
  fixture["variables"]  →  Suchanfrage-Parameter (rawParams, treatmentFlags, …)
  fixture["data"]["presentation"]["staysSearch"]["results"]["paginationInfo"]  →  Paginierung
"""
import json
import re
from pathlib import Path

from airbi.scraper.browser import browser_context

# Bounding-Box über Marvila + Beato (aus den GeoJSON-Bounds, mit Rand).
SW_LAT, SW_LNG = 38.721, -9.133
NE_LAT, NE_LNG = 38.766, -9.090

SEARCH_URL = (
    "https://www.airbnb.com/s/Lisboa--Portugal/homes"
    f"?ne_lat={NE_LAT}&ne_lng={NE_LNG}&sw_lat={SW_LAT}&sw_lng={SW_LNG}"
    "&search_by_map=true&zoom=14"
)

OUT = Path("tests/fixtures/scraper/stays_search_page1.json")

# Anpassungshinweis: Airbnb bettet alle Daten in dieses Script-Tag ein.
# Falls der Tag-Name sich ändert, hier anpassen.
_DEFERRED_STATE_TAG_ID = "data-deferred-state-0"


def _extract_stays_search(html: str) -> dict:
    """Extrahiert den StaysSearch-Datenblock aus dem eingebetteten JSON."""
    pattern = rf'<script[^>]+id="{_DEFERRED_STATE_TAG_ID}"[^>]*>(.*?)</script>'
    match = re.search(pattern, html, re.DOTALL)
    if not match:
        raise ValueError(
            f"Script-Tag '{_DEFERRED_STATE_TAG_ID}' nicht im HTML gefunden.\n"
            "Airbnb hat möglicherweise die Struktur geändert — Tag-ID prüfen."
        )
    raw = match.group(1)
    page_data = json.loads(raw)

    # niobeClientData ist eine Liste von [cacheKey, responseData]-Paaren.
    # Das StaysSearch-Paar erkennt man an dem cacheKey, der mit "StaysSearch:" beginnt.
    niobe = page_data.get("niobeClientData", [])
    for pair in niobe:
        if isinstance(pair, list) and len(pair) == 2:
            cache_key, response = pair
            if isinstance(cache_key, str) and cache_key.startswith("StaysSearch:"):
                return response  # {"data": {"presentation": {"staysSearch": {...}}}, "variables": {...}}

    raise ValueError(
        "Kein 'StaysSearch:'-Eintrag in niobeClientData gefunden.\n"
        f"Vorhandene Schlüssel: {[p[0][:60] if isinstance(p, list) and p else str(p)[:60] for p in niobe[:5]]}"
    )


def main() -> None:
    with browser_context(headless=True) as ctx:
        page = ctx.new_page()
        page.goto(SEARCH_URL, timeout=60000, wait_until="domcontentloaded")
        page.wait_for_timeout(10000)
        html = page.content()

    stays_data = _extract_stays_search(html)

    # Sanity-Check: Ergebnis-Array muss vorhanden sein.
    results = (
        stays_data
        .get("data", {})
        .get("presentation", {})
        .get("staysSearch", {})
        .get("results", {})
        .get("searchResults", [])
    )
    if not results:
        raise SystemExit(
            "StaysSearch-Daten gefunden, aber searchResults ist leer.\n"
            "Möglicherweise wurden keine Listings für die Bounding-Box zurückgegeben."
        )

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(stays_data, indent=2, ensure_ascii=False), encoding="utf-8")
    print(
        f"Fixture gespeichert: {OUT} "
        f"({OUT.stat().st_size:,} Bytes, {len(results)} Suchergebnisse)"
    )


if __name__ == "__main__":
    main()
