"""Laedt eine Airbnb-Detailseite (/rooms/<id>), extrahiert das eingebettete
JSON aus dem Seiten-HTML und speichert es als Fixture.

Aufruf: uv run python scripts/record_listing_detail.py <listing_id>

Struktur der Fixture (ermittelt am 2026-05-22, listing_id=25532057)
=====================================================================

Das eingebettete JSON sitzt in <script id="data-deferred-state-0">.
Top-Level-Schluessel des Fixture-Dicts: {"niobeClientData": [[key, {data, variables}]]}

Einstiegspunkt:
  root = fixture["niobeClientData"][0][1]["data"]

PRIMARY PATH -- overviewItems (zuverlaessig, String-Parsing):
  root
    ["presentation"]
    ["stayProductDetailPage"]
    ["sections"]
    ["sbuiData"]
    ["sectionConfiguration"]
    ["root"]
    ["sections"]          <- Liste von Sections
    [N]["sectionData"]
    ["overviewItems"]     <- Liste von {"__typename": "PdpSbuiBasicListItem", "title": "..."}

  Beispielwerte (listing 25532057):
    [{"title": "2 guests"}, {"title": "1 bedroom"}, {"title": "1 bed"}, {"title": "1 bath"}]

  Extraktion per Regex auf "title"-Strings:
    max_guests  = int(re.match(r"(\\d+) guest",   title).group(1))
    bedrooms    = int(re.match(r"(\\d+) bedroom", title).group(1))
    beds        = int(re.match(r"(\\d+) bed\\b",   title, re.I).group(1))  # "bed" != "bedroom"
    bathrooms   = int(re.match(r"(\\d+) bath",    title).group(1))

  Hinweis: nicht alle vier Felder muessen in derselben Section stehen;
  iteriere ALLE Sections und sammle Treffer auf.

SECONDARY PATH -- sharingConfig (personCapacity als Integer, kein Parsing):
  root
    ["presentation"]
    ["stayProductDetailPage"]
    ["sections"]
    ["metadata"]
    ["sharingConfig"]
    ["personCapacity"]    <- Integer (z. B. 2)
  Zimmeranzahl steht hier nur als Text im "title"-String:
    "Rental unit in Lisbon * 4.86 * 1 bedroom * 1 bed * 1 private bath"
  (Regex nutzbar, aber overviewItems ist praeziser.)

Empfohlene Extraktions-Strategie fuer Task 7:
  1. Iterate ueber alle Sections in sbuiData.sectionConfiguration.root.sections
     und sammle overviewItems-Treffer (Variante PRIMARY).
  2. Fallback fuer personCapacity: sharingConfig["personCapacity"] (SECONDARY).
  3. Kein Apollo-Cache-Knoten "Listing:<id>" in dieser Fixture-Version vorhanden.
"""
import json
import sys
from pathlib import Path

from airbi.scraper.browser import browser_context

OUT = Path("tests/fixtures/scraper/listing_detail.json")


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit("Aufruf: record_listing_detail.py <listing_id>")
    listing_id = sys.argv[1]
    url = f"https://www.airbnb.com/rooms/{listing_id}"

    with browser_context(headless=True) as ctx:
        page = ctx.new_page()
        page.goto(url, timeout=60000, wait_until="networkidle")
        page.wait_for_timeout(4000)
        blobs = page.eval_on_selector_all(
            "script[id^='data-deferred-state']",
            "els => els.map(e => e.textContent)",
        )

    if not blobs:
        raise SystemExit("Kein eingebettetes JSON gefunden — siehe Task-6-Hinweise.")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(blobs[0], encoding="utf-8")
    print(f"Fixture gespeichert: {OUT} ({OUT.stat().st_size} Bytes)")


if __name__ == "__main__":
    main()
