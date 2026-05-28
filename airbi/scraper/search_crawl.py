"""Crawl-Orchestrator: Bounding-Box, Entire-Home-Filter, Detail-Merge, Persistenz.

Reine/DB-Funktionen (a)-(d) sind vollständig testbar ohne Browser.
`run_search_crawl` (e) enthält die browser-gestützte Lauflogik und wird
erst in Task 10 live getestet."""

from __future__ import annotations

import dataclasses
import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from airbi.classification.amenity import amenity_score as _amenity_score
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

# Title-Signale, die auf eine Privatzimmer-Vermietung hindeuten — zusätzlich
# zur property_type-Prüfung. Plan-2-Befund: Airbnb klassifiziert manche
# Privatzimmer in Guesthouses / B&Bs unter property_type='Guesthouse' o.ä.;
# der Listing-Name verrät den Privatzimmer-Charakter trotzdem.
_PRIVATE_ROOM_TITLE_NEEDLES: tuple[str, ...] = (
    "private room",
    "shared room",
)


def is_entire_home(parsed_listing: ParsedListing) -> bool:
    """True wenn das Listing eine ganze Unterkunft ist (kein Zimmer).

    Heuristik in zwei Stufen:
    1. False wenn ``property_type`` (case-insensitiv) das Wort "room" enthält
       oder exakt "hostel" ist.
    2. Zusätzlich False wenn der ``title`` (Listing-Name) ein Privatzimmer-
       Signal enthält (z.B. 'Private Room with AC ...' bei einem
       Guesthouse-Listing).

    ``property_type=None`` → False.
    """
    pt = parsed_listing.property_type
    if pt is None:
        return False
    lower_pt = pt.lower().strip()
    if "room" in lower_pt or lower_pt == "hostel":
        return False
    title = (parsed_listing.title or "").lower()
    if any(needle in title for needle in _PRIVATE_ROOM_TITLE_NEEDLES):
        return False
    return True


# ---------------------------------------------------------------------------
# (c) merge_detail
# ---------------------------------------------------------------------------

def merge_detail(parsed_listing: ParsedListing, detail: ListingDetail) -> ParsedListing:
    """Gibt ein neues ParsedListing zurück, dessen Detail-Felder aus `detail`
    stammen. Alle anderen Felder bleiben unverändert."""
    return dataclasses.replace(
        parsed_listing,
        bedrooms=detail.bedrooms,
        beds=detail.beds,
        bathrooms=detail.bathrooms,
        max_guests=detail.max_guests,
        amenities=detail.amenities,
        description=detail.description,
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
    cls_config = crawl_run.search_config.classification_config or {}

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
        listing.amenities = pl.amenities
        listing.description = pl.description
        listing.amenity_score = _amenity_score(
            pl.amenities,
            beds=pl.beds,
            bedrooms=pl.bedrooms,
            max_guests=pl.max_guests,
            is_superhost=pl.is_superhost,
            rating=pl.rating,
            config=cls_config,
        )

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

_MAX_PAGES = 20  # Schutz gegen Endlosschleifen


def run_search_crawl(
    session: "Session",
    search_config: "SearchConfig",
    *,
    headless: bool = True,
) -> "CrawlRun":
    """Führt einen vollständigen Crawl-Lauf durch.

    Erstellt einen CrawlRun, öffnet den Browser, scrapt alle Suchergebnis-
    Seiten (paginiert via Cursor) und Detail-Seiten, persistiert die
    Ergebnisse und setzt den Status.
    Committet am Ende (im Gegensatz zu persist_results).

    Wird erst in Task 10 live getestet.
    """
    import json
    import re as _re
    import urllib.parse

    from airbi.db.models import CrawlRun
    from airbi.scraper.browser import browser_context
    from airbi.scraper.pacing import DEFAULT_PAGE_DELAY, human_delay
    from airbi.scraper.parser import parse_listing_detail, parse_search_results

    _DEFERRED_STATE_TAG_ID = "data-deferred-state-0"

    run = CrawlRun(search_config=search_config, status="running")
    session.add(run)
    session.flush()

    # ------------------------------------------------------------------
    # Hilfsfunktion: eine Such-Seite laden und deren searchResults lesen.
    # Gibt (search_results_list, page_cursors_list) zurück oder (None, [])
    # bei Fehlern oder Block-Erkennung.
    # ------------------------------------------------------------------
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

    def _fetch_search_page(
        pw_page: object,
        url: str,
        page_num: int,
    ) -> tuple[list, list[str]]:
        """Navigiert zu `url`, extrahiert searchResults und pageCursors.

        Gibt ([], []) bei Block-Erkennung oder fehlendem JSON zurück.
        """
        try:
            pw_page.goto(url, timeout=60_000, wait_until="domcontentloaded")
            pw_page.wait_for_timeout(10_000)
            html = pw_page.content()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Seite %d: Navigation fehlgeschlagen: %s", page_num, exc)
            return [], []

        lower_html = html.lower()
        if "hcaptcha" in lower_html or "access denied" in lower_html:
            logger.warning("Seite %d: Block/CAPTCHA erkannt.", page_num)
            return [], []

        stays_data = _extract_json_from_html(html)
        if stays_data is None:
            logger.warning("Seite %d: StaysSearch-JSON nicht gefunden.", page_num)
            return [], []

        search_results = (
            stays_data
            .get("data", {})
            .get("presentation", {})
            .get("staysSearch", {})
            .get("results", {})
            .get("searchResults", [])
        )
        page_cursors = (
            stays_data
            .get("data", {})
            .get("presentation", {})
            .get("staysSearch", {})
            .get("results", {})
            .get("paginationInfo", {})
            .get("pageCursors", [])
        )
        return search_results, page_cursors

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

        base_search_url = (
            "https://www.airbnb.com/s/Lisboa--Portugal/homes"
            f"?ne_lat={ne_lat}&ne_lng={ne_lng}&sw_lat={sw_lat}&sw_lng={sw_lng}"
            "&search_by_map=true&zoom=14"
        )

        parsed_listings: dict[str, ParsedListing] = {}

        with browser_context(headless=headless) as ctx:
            page = ctx.new_page()

            # ----------------------------------------------------------
            # Seite 1 laden (kein Cursor)
            # ----------------------------------------------------------
            first_results, page_cursors = _fetch_search_page(page, base_search_url, 1)

            # Block auf Seite 1 → abbrechen
            if not first_results and not page_cursors:
                # Prüfe nochmal ob es ein echtes Block war
                html_check = page.content().lower()
                if "hcaptcha" in html_check or "access denied" in html_check:
                    run.status = "failed"
                    run.message = "CAPTCHA oder Block-Page erkannt."
                    run.finished_at = datetime.now(timezone.utc)
                    session.commit()
                    return run

            # 0-Treffer-Guard: prüft searchResults (was der Parser liest)
            if not first_results:
                run.status = "failed"
                run.message = "Keine Suchergebnisse zurückgegeben (0 Listings)."
                run.finished_at = datetime.now(timezone.utc)
                session.commit()
                return run

            # Seite 1 einlesen
            for pl in parse_search_results(
                {"data": {"presentation": {"staysSearch": {"results": {"searchResults": first_results}}}}}
            ):
                parsed_listings[pl.airbnb_id] = pl

            logger.info("Seite 1: %d Ergebnisse, %d Cursor verfügbar", len(first_results), len(page_cursors))

            # ----------------------------------------------------------
            # Seiten 2…N (Cursor-Paginierung)
            # Cursor[0] = Seite 1 (offset 0), ab Cursor[1] = Seite 2
            # URL-Parameter: &cursor=<base64-token>
            # ----------------------------------------------------------
            for page_idx, cursor in enumerate(page_cursors[1:_MAX_PAGES], start=2):
                human_delay(*DEFAULT_PAGE_DELAY)
                encoded_cursor = urllib.parse.quote(cursor)
                page_url = base_search_url + f"&cursor={encoded_cursor}"

                page_results, _ = _fetch_search_page(page, page_url, page_idx)
                if not page_results:
                    logger.info("Seite %d lieferte keine Ergebnisse, übersprungen.", page_idx)
                    continue

                new_count = 0
                for pl in parse_search_results(
                    {"data": {"presentation": {"staysSearch": {"results": {"searchResults": page_results}}}}}
                ):
                    if pl.airbnb_id not in parsed_listings:
                        parsed_listings[pl.airbnb_id] = pl
                        new_count += 1
                    else:
                        parsed_listings[pl.airbnb_id] = pl  # neueste Daten behalten

                logger.info(
                    "Seite %d: %d Ergebnisse (%d neu gesamt=%d)",
                    page_idx, len(page_results), new_count, len(parsed_listings),
                )

            # --- Entire-Home-Filter + District-Vorfilter ---
            filtered = [
                pl for pl in parsed_listings.values()
                if is_entire_home(pl)
                and assign_district(pl.lat, pl.lng, relevant) != "unassigned"
            ]
            logger.info(
                "Suchergebnisse: %d total (alle Seiten), %d nach Entire-Home- + District-Filter",
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
