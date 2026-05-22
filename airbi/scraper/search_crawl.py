"""Crawl-Orchestrator: Bounding-Box, Entire-Home-Filter, Detail-Merge, Persistenz.

Reine/DB-Funktionen (a)-(d) sind vollständig testbar ohne Browser.
`run_search_crawl` (e) enthält die browser-gestützte Lauflogik und wird
erst in Task 10 live getestet."""

from __future__ import annotations

import dataclasses
import logging
import re
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from airbi.classification.size import size_class as _size_class
from airbi.geo.districts import assign_district, load_districts
from airbi.scraper.models import ListingDetail, ParsedListing

if TYPE_CHECKING:
    from shapely.geometry.base import BaseGeometry
    from sqlalchemy.orm import Session

    from airbi.db.models import CrawlRun, SearchConfig

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# (a) bounding_box_for
# ---------------------------------------------------------------------------

def bounding_box_for(
    districts: dict[str, "BaseGeometry"],
    margin: float = 0.003,
) -> tuple[float, float, float, float]:
    """Berechnet eine Bounding-Box, die alle District-Polygone umschließt.

    GeoJSON/Shapely `bounds` liefert (min_lng, min_lat, max_lng, max_lat).
    Rückgabe: (sw_lat, sw_lng, ne_lat, ne_lng) — für die Airbnb-URL.
    """
    min_lngs, min_lats, max_lngs, max_lats = [], [], [], []
    for geom in districts.values():
        min_lng, min_lat, max_lng, max_lat = geom.bounds
        min_lngs.append(min_lng)
        min_lats.append(min_lat)
        max_lngs.append(max_lng)
        max_lats.append(max_lat)

    sw_lat = min(min_lats) - margin
    sw_lng = min(min_lngs) - margin
    ne_lat = max(max_lats) + margin
    ne_lng = max(max_lngs) + margin
    return sw_lat, sw_lng, ne_lat, ne_lng


# ---------------------------------------------------------------------------
# (b) is_entire_home
# ---------------------------------------------------------------------------

def is_entire_home(parsed_listing: ParsedListing) -> bool:
    """True wenn das Listing eine ganze Unterkunft ist (kein Zimmer).

    Heuristik: False wenn `property_type` (case-insensitiv) das Wort "room"
    enthält oder exakt "hostel" ist; sonst True. None → False.
    """
    pt = parsed_listing.property_type
    if pt is None:
        return False
    lower = pt.lower().strip()
    if "room" in lower:
        return False
    if lower == "hostel":
        return False
    return True


# ---------------------------------------------------------------------------
# (c) merge_detail
# ---------------------------------------------------------------------------

def merge_detail(parsed_listing: ParsedListing, detail: ListingDetail) -> ParsedListing:
    """Gibt ein neues ParsedListing zurück, dessen Zimmerfelder aus `detail`
    stammen. Alle anderen Felder bleiben unverändert."""
    return dataclasses.replace(
        parsed_listing,
        bedrooms=detail.bedrooms,
        beds=detail.beds,
        bathrooms=detail.bathrooms,
        max_guests=detail.max_guests,
    )


# ---------------------------------------------------------------------------
# (d) persist_results
# ---------------------------------------------------------------------------

def persist_results(
    session: "Session",
    crawl_run: "CrawlRun",
    parsed_listings: list[ParsedListing],
    districts: dict[str, "BaseGeometry"],
) -> int:
    """Schreibt Listings und Snapshots in die Datenbank (Upsert-Logik).

    Pro ParsedListing:
    - Sucht ein Listing nach (city_slug, airbnb_id); bei Fund → Update, sonst
      neuer Eintrag.
    - Ordnet per `assign_district` einem District zu (oder 'unassigned').
    - Berechnet `size_class` via Schlafzimmerzahl.
    - Erstellt immer einen neuen Snapshot für den aktuellen CrawlRun.

    Ruft session.flush() am Ende auf; committet NICHT (der Aufrufer steuert
    die Transaktion).
    Gibt die Anzahl verarbeiteter Listings zurück.
    """
    from airbi.db.models import Listing, Snapshot  # lokaler Import → kein Zirkelbezug

    city_slug = crawl_run.search_config.city_slug

    for pl in parsed_listings:
        # District-Zuweisung
        if pl.lat is not None and pl.lng is not None:
            district = assign_district(pl.lat, pl.lng, districts)
        else:
            district = "unassigned"

        # Größenklasse
        sc = _size_class(pl.bedrooms)

        # Upsert Listing
        listing = (
            session.query(Listing)
            .filter_by(city_slug=city_slug, airbnb_id=pl.airbnb_id)
            .one_or_none()
        )
        if listing is None:
            listing = Listing(city_slug=city_slug, airbnb_id=pl.airbnb_id)
            session.add(listing)

        # Stammdaten immer aktualisieren
        listing.district_slug = district
        listing.size_class = sc
        listing.title = pl.title
        listing.url = pl.url
        listing.lat = pl.lat
        listing.lng = pl.lng
        listing.property_type = pl.property_type
        listing.bedrooms = pl.bedrooms
        listing.beds = pl.beds
        listing.bathrooms = pl.bathrooms
        listing.max_guests = pl.max_guests
        listing.host_name = pl.host_name
        listing.is_superhost = pl.is_superhost

        session.flush()  # sichert listing.id für die FK-Beziehung

        # Neuer Snapshot
        snap = Snapshot(
            listing_id=listing.id,
            crawl_run_id=crawl_run.id,
            price=pl.price,
            fees=pl.fees,
            review_count=pl.review_count,
            rating=pl.rating,
            search_position=pl.search_position,
        )
        session.add(snap)

    session.flush()
    return len(parsed_listings)


# ---------------------------------------------------------------------------
# (e) run_search_crawl  — browser-gestützte Lauflogik (nicht in Unit-Tests)
# ---------------------------------------------------------------------------

def run_search_crawl(
    session: "Session",
    search_config: "SearchConfig",
    *,
    headless: bool = True,
) -> "CrawlRun":
    """Führt einen vollständigen Crawl-Lauf durch.

    Erstellt einen CrawlRun, öffnet den Browser, scrapt Suchergebnisse und
    Detail-Seiten, persistiert die Ergebnisse und setzt den Status.
    Committet am Ende (im Gegensatz zu persist_results).

    Wird erst in Task 10 live getestet.
    """
    import json
    import re as _re

    from airbi.db.models import CrawlRun
    from airbi.scraper.browser import browser_context
    from airbi.scraper.pacing import DEFAULT_PAGE_DELAY, human_delay
    from airbi.scraper.parser import parse_listing_detail, parse_search_results

    _DEFERRED_STATE_TAG_ID = "data-deferred-state-0"

    run = CrawlRun(search_config=search_config, status="running")
    session.add(run)
    session.flush()

    try:
        all_districts = load_districts()
        # Nur die in der Config genannten Distrikte für die Bounding-Box
        if search_config.district_slugs:
            relevant = {
                slug: geom
                for slug, geom in all_districts.items()
                if slug in search_config.district_slugs
            }
        else:
            relevant = all_districts
        if not relevant:
            relevant = all_districts

        sw_lat, sw_lng, ne_lat, ne_lng = bounding_box_for(relevant)

        search_url = (
            "https://www.airbnb.com/s/Lisboa--Portugal/homes"
            f"?ne_lat={ne_lat}&ne_lng={ne_lng}&sw_lat={sw_lat}&sw_lng={sw_lng}"
            "&search_by_map=true&zoom=14"
        )

        parsed_listings: dict[str, ParsedListing] = {}

        def _extract_json_from_html(html: str) -> dict | None:
            pattern = rf'<script[^>]+id="{_DEFERRED_STATE_TAG_ID}"[^>]*>(.*?)</script>'
            match = _re.search(pattern, html, _re.DOTALL)
            if not match:
                return None
            try:
                page_data = json.loads(match.group(1))
            except json.JSONDecodeError:
                return None
            niobe = page_data.get("niobeClientData", [])
            for pair in niobe:
                if isinstance(pair, list) and len(pair) == 2:
                    cache_key, response = pair
                    if isinstance(cache_key, str) and cache_key.startswith("StaysSearch:"):
                        return response
            return None

        with browser_context(headless=headless) as ctx:
            page = ctx.new_page()

            # --- Suchergebnisse scrapen ---
            page.goto(search_url, timeout=60_000, wait_until="domcontentloaded")
            page.wait_for_timeout(10_000)

            html = page.content()

            # Block-Erkennung: CAPTCHA / Blocking-Page
            if "captcha" in html.lower() or "blocked" in html.lower():
                run.status = "failed"
                run.message = "CAPTCHA oder Block-Page erkannt."
                run.finished_at = datetime.now(timezone.utc)
                session.commit()
                return run

            stays_data = _extract_json_from_html(html)
            if stays_data is None:
                run.status = "failed"
                run.message = "StaysSearch-JSON nicht im HTML gefunden."
                run.finished_at = datetime.now(timezone.utc)
                session.commit()
                return run

            results = (
                stays_data
                .get("data", {})
                .get("presentation", {})
                .get("staysSearch", {})
                .get("results", {})
                .get("searchResults", [])
            )
            map_results = (
                stays_data
                .get("data", {})
                .get("presentation", {})
                .get("staysSearch", {})
                .get("mapResults", {})
                .get("mapSearchResults", [])
            )
            all_results = results + map_results

            if not all_results:
                run.status = "failed"
                run.message = "Keine Suchergebnisse zurückgegeben (0 Listings)."
                run.finished_at = datetime.now(timezone.utc)
                session.commit()
                return run

            for pl in parse_search_results({"data": stays_data.get("data", {})}):
                parsed_listings[pl.airbnb_id] = pl

            # --- Entire-Home-Filter ---
            filtered = [pl for pl in parsed_listings.values() if is_entire_home(pl)]
            logger.info(
                "Suchergebnisse: %d total, %d nach Entire-Home-Filter",
                len(parsed_listings),
                len(filtered),
            )

            # --- Detail-Crawl ---
            final_listings: list[ParsedListing] = []
            for pl in filtered:
                detail_url = f"https://www.airbnb.com/rooms/{pl.airbnb_id}"
                try:
                    page.goto(detail_url, timeout=60_000, wait_until="networkidle")
                    page.wait_for_timeout(4_000)
                    blobs = page.eval_on_selector_all(
                        "script[id^='data-deferred-state']",
                        "els => els.map(e => e.textContent)",
                    )
                    if blobs:
                        detail_payload = json.loads(blobs[0])
                        detail = parse_listing_detail(detail_payload)
                        pl = merge_detail(pl, detail)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Detail-Crawl für %s fehlgeschlagen: %s", pl.airbnb_id, exc)

                final_listings.append(pl)
                human_delay(*DEFAULT_PAGE_DELAY)

        # --- Persistieren ---
        count = persist_results(session, run, final_listings, all_districts)
        run.status = "completed"
        run.listings_seen = count
        run.finished_at = datetime.now(timezone.utc)

    except Exception as exc:  # noqa: BLE001
        logger.exception("Crawl-Lauf fehlgeschlagen")
        run.status = "failed"
        run.message = str(exc)
        run.finished_at = datetime.now(timezone.utc)

    session.commit()
    return run
