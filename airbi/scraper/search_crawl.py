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
from airbi.geo.distance import concentric_boxes, haversine_km
from airbi.scraper.models import ListingDetail, ParsedListing

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from airbi.db.models import CrawlRun, SearchConfig

logger = logging.getLogger(__name__)

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
) -> int:
    """Schreibt Listings und Snapshots in die Datenbank (Upsert-Logik).

    Pro ParsedListing:
    - Sucht ein Listing nach (city_slug, airbnb_id); bei Fund → Update, sonst
      neuer Eintrag.
    - Berechnet `size_class` via Schlafzimmerzahl.
    - Erstellt einen Snapshot für den aktuellen CrawlRun — **dedupliziert**:
      existiert bereits ein Snapshot für ``(listing, run)``, wird kein
      neuer angelegt. Macht ``run_search_crawl`` resilient (per-Box-Commit
      + Resume können dasselbe Listing mehrfach durchreichen ohne Duplikate).

    Ruft session.flush() am Ende auf; committet NICHT (der Aufrufer steuert
    die Transaktion).
    Gibt die Anzahl verarbeiteter Listings zurück.
    """
    from sqlalchemy import select as _select  # lokaler Import vermeidet shadow

    from airbi.db.models import Listing, Snapshot  # lokaler Import → kein Zirkelbezug

    city_slug = crawl_run.search_config.city_slug
    cls_config = crawl_run.search_config.classification_config or {}

    # Bulk-Set bereits gesnapshotteter listing_ids für diesen Run, damit der
    # Dedup-Check im Loop O(1) statt O(N) DB-Queries kostet.
    snapped_listing_ids: set[int] = set(
        session.execute(
            _select(Snapshot.listing_id).where(Snapshot.crawl_run_id == crawl_run.id)
        ).scalars().all()
    )

    for pl in parsed_listings:
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
        listing.district_slug = None
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

        # Snapshot nur anlegen, wenn für dieses (listing, run) noch keiner
        # existiert — sonst gibt's bei Re-Persist (Resume / Box-Überlapp)
        # Duplikate.
        if listing.id not in snapped_listing_ids:
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
            snapped_listing_ids.add(listing.id)

    session.flush()
    return len(parsed_listings)


# ---------------------------------------------------------------------------
# (e) run_search_crawl  — browser-gestützte Lauflogik (nicht in Unit-Tests)
# ---------------------------------------------------------------------------

_MAX_PAGES = 20  # Schutz gegen Endlosschleifen


_REFRESH_BATCH_SIZE = 50  # Browser nach so vielen Listings frisch starten (Hang-Schutz)


def refresh_details(
    session: "Session",
    search_config: "SearchConfig",
    *,
    headless: bool = True,
) -> int:
    """Re-Crawl der Detail-Seiten aller Listings des letzten completed Runs.

    Aktualisiert Stammdaten (bedrooms/beds/bathrooms/max_guests/amenities/
    description/size_class/amenity_score) — ohne neue Such-Phase und ohne
    neue Snapshots. Sinnvoll, wenn der Parser gefixt wurde und die existierenden
    Listings mit den korrigierten Feldern angereichert werden sollen.

    **Resumierbar**: Listings mit ``bedrooms IS NOT NULL`` werden übersprungen.
    Per-Listing-Commit, Browser-Neustart alle ``_REFRESH_BATCH_SIZE`` Listings.
    Ein Hang verliert maximal ein Listing.

    Gibt die Anzahl tatsächlich aktualisierter Listings zurück.
    """
    import json

    from sqlalchemy import select

    from airbi.db.models import CrawlRun, Listing, Snapshot
    from airbi.scraper.browser import browser_context
    from airbi.scraper.pacing import DEFAULT_PAGE_DELAY, human_delay
    from airbi.scraper.parser import parse_listing_detail

    # Letzten completed Run dieser Config finden.
    stmt = (
        select(CrawlRun)
        .where(CrawlRun.search_config_id == search_config.id)
        .where(CrawlRun.status == "completed")
        .order_by(CrawlRun.started_at.desc(), CrawlRun.id.desc())
        .limit(1)
    )
    run = session.execute(stmt).scalar_one_or_none()
    if run is None:
        logger.warning("Kein completed Run gefunden für Config '%s'", search_config.name)
        return 0

    # Listings + Snapshots dieses Runs laden (Snapshot.rating fließt in amenity_score).
    rows = session.execute(
        select(Listing, Snapshot)
        .join(Snapshot, Snapshot.listing_id == Listing.id)
        .where(Snapshot.crawl_run_id == run.id)
    ).all()
    total = len(rows)
    # Resume: nur Listings ohne bedrooms anfassen.
    todo = [(l, s) for (l, s) in rows if l.bedrooms is None]
    skipped = total - len(todo)
    cls_config = search_config.classification_config or {}
    logger.info(
        "Detail-Refresh: %d Listings zu refreshen (skip %d bereits-refreshed) aus Run %d",
        len(todo), skipped, run.id,
    )

    updated = 0
    # In Batches; jeder Batch bekommt einen frischen Browser (mildert Long-Session-Hangs).
    for batch_start in range(0, len(todo), _REFRESH_BATCH_SIZE):
        batch = todo[batch_start : batch_start + _REFRESH_BATCH_SIZE]
        logger.info(
            "Browser-Batch %d–%d (von %d)",
            batch_start + 1, batch_start + len(batch), len(todo),
        )
        with browser_context(headless=headless) as ctx:
            page = ctx.new_page()
            for j, (listing, snap) in enumerate(batch, start=1):
                i_global = batch_start + j
                logger.info(
                    "Refresh %d/%d: airbnb_id=%s",
                    i_global, len(todo), listing.airbnb_id,
                )
                detail_url = f"https://www.airbnb.com/rooms/{listing.airbnb_id}"
                try:
                    page.goto(detail_url, timeout=30_000, wait_until="domcontentloaded")
                    page.wait_for_timeout(4_000)
                    blobs = page.eval_on_selector_all(
                        "script[id^='data-deferred-state']",
                        "els => els.map(e => e.textContent)",
                    )
                    if blobs:
                        payload = json.loads(blobs[0])
                        detail = parse_listing_detail(payload)
                        if detail.bedrooms is not None:
                            listing.bedrooms = detail.bedrooms
                        if detail.beds is not None:
                            listing.beds = detail.beds
                        if detail.bathrooms is not None:
                            listing.bathrooms = detail.bathrooms
                        if detail.max_guests is not None:
                            listing.max_guests = detail.max_guests
                        if detail.amenities:
                            listing.amenities = detail.amenities
                        if detail.description:
                            listing.description = detail.description
                        listing.size_class = _size_class(listing.bedrooms)
                        listing.amenity_score = _amenity_score(
                            listing.amenities,
                            beds=listing.beds,
                            bedrooms=listing.bedrooms,
                            max_guests=listing.max_guests,
                            is_superhost=listing.is_superhost,
                            rating=snap.rating,
                            config=cls_config,
                        )
                        session.commit()  # Per-Listing-Commit — Hang verliert max. 1 Listing.
                        updated += 1
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Refresh für %s fehlgeschlagen: %s", listing.airbnb_id, exc)
                    session.rollback()
                human_delay(*DEFAULT_PAGE_DELAY)

    logger.info("Detail-Refresh fertig: %d/%d Listings aktualisiert (skip %d)",
                updated, len(todo), skipped)
    return updated


def extract_results_and_cursors(stays_data: dict | None) -> tuple[list, list]:
    """Liest searchResults + pageCursors None-sicher aus einer StaysSearch-Antwort.

    Airbnb liefert vereinzelt Antworten, in denen Zwischenknoten als JSON-``null``
    stehen (z. B. ``"staysSearch": null``) — verkettete ``.get(key, {})`` schützen
    dagegen nicht, weil das Default nur bei FEHLENDEM Schlüssel greift. Eine solche
    Seite wird als leer behandelt (Aufrufer überspringt sie), statt den Lauf zu
    crashen (Regression: Run 19, 13.07.2026).
    """
    results = (
        ((((stays_data or {}).get("data") or {})
          .get("presentation") or {})
         .get("staysSearch") or {})
        .get("results") or {}
    )
    search_results = results.get("searchResults") or []
    pagination = results.get("paginationInfo") or {}
    page_cursors = pagination.get("pageCursors") or []
    return search_results, page_cursors


def fetch_with_retry(
    fetch,
    *,
    retries: int = 2,
    on_retry=None,
) -> tuple[list, list]:
    """Ruft ``fetch()`` auf und wiederholt bei leerem Ergebnis bis zu ``retries``-mal.

    Ein transienter Fehlschlag (Timeout, Netz-Hickser) auf Seite 1 einer Box hat
    bisher die GANZE Box gekostet (02./06.07.2026: bis zu 3 von 5 Boxen verloren).
    ``on_retry(attempt)`` wird vor jedem Wiederholungsversuch gerufen — Ort für
    Logging und Delay des Aufrufers.
    """
    results: list = []
    cursors: list = []
    for attempt in range(retries + 1):
        results, cursors = fetch()
        if results or cursors:
            return results, cursors
        if attempt < retries and on_retry is not None:
            on_retry(attempt + 1)
    return results, cursors


def run_search_crawl(
    session: "Session",
    search_config: "SearchConfig",
    *,
    headless: bool = True,
) -> "CrawlRun":
    """Führt einen vollständigen Crawl-Lauf durch — **resilient**:

    - **Auto-Resume**: existiert für die SearchConfig ein laufender (status=
      ``running``) CrawlRun, wird der fortgesetzt statt neu angelegt.
    - **Per-Box-Commit**: nach jeder Box wird persistiert + committet.
      Ein Abbruch verliert maximal die laufende Box, nicht den ganzen Lauf.
    - **Snapshot-Dedup**: Listings, die in mehreren Boxen vorkommen oder
      durch Resume erneut auftauchen, bekommen keinen Doppel-Snapshot.
    - **Detail-Phase delegiert an :func:`refresh_details`** — bereits
      resilient (per-Listing-Commit, Browser-Restart alle 50, Skip von
      bereits-gedetailcrawlten Listings via ``bedrooms IS NOT NULL``).
    """
    import json
    import re as _re
    import urllib.parse

    from sqlalchemy import func as _sql_func
    from sqlalchemy import select as _sql_select

    from airbi.db.models import CrawlRun, Snapshot
    from airbi.scraper.browser import browser_context
    from airbi.scraper.pacing import DEFAULT_PAGE_DELAY, human_delay
    from airbi.scraper.parser import parse_search_results

    _DEFERRED_STATE_TAG_ID = "data-deferred-state-0"

    # Auto-Resume: laufenden Run dieser Config aufgreifen, sonst neuen anlegen.
    existing_run = session.execute(
        _sql_select(CrawlRun)
        .where(CrawlRun.search_config_id == search_config.id)
        .where(CrawlRun.status == "running")
        .order_by(CrawlRun.id.desc()).limit(1)
    ).scalar_one_or_none()
    if existing_run is not None:
        run = existing_run
        logger.info(
            "Resume: setze laufenden CrawlRun %d für Config '%s' fort.",
            run.id, search_config.name,
        )
    else:
        run = CrawlRun(search_config=search_config, status="running")
        session.add(run)
        session.commit()  # commit sofort, damit Resume den Run sieht
        logger.info("Neuer CrawlRun %d für Config '%s' gestartet.",
                    run.id, search_config.name)

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

        search_results, page_cursors = extract_results_and_cursors(stays_data)
        if not search_results and not page_cursors:
            logger.warning("Seite %d: StaysSearch-Antwort ohne Ergebnisse (null-Knoten?).", page_num)
        return search_results, page_cursors

    try:
        center_lat = search_config.center_lat
        center_lng = search_config.center_lng
        radii = search_config.band_radii_km or [1, 2, 3, 5, 10]
        if center_lat is None or center_lng is None:
            run.status = "failed"
            run.message = "SearchConfig ohne center_lat/center_lng — Umkreis-Crawl nicht möglich."
            run.finished_at = datetime.now(timezone.utc)
            session.commit()
            return run
        max_radius = max(radii)
        boxes = concentric_boxes(center_lat, center_lng, radii)

        def _search_url(box: tuple[float, float, float, float]) -> str:
            sw_lat, sw_lng, ne_lat, ne_lng = box
            return (
                "https://www.airbnb.com/s/Lisboa--Portugal/homes"
                f"?ne_lat={ne_lat}&ne_lng={ne_lng}&sw_lat={sw_lat}&sw_lng={sw_lng}"
                "&search_by_map=true&zoom=14"
            )

        def _in_radius(pl: ParsedListing) -> bool:
            if pl.lat is None or pl.lng is None:
                return False
            return haversine_km(center_lat, center_lng, pl.lat, pl.lng) <= max_radius

        # ============================================================
        # SEARCH-PHASE: pro Box paginieren, filtern, persistieren, commit.
        # ============================================================
        with browser_context(headless=headless) as ctx:
            page = ctx.new_page()

            for box_idx, box in enumerate(boxes, start=1):
                base_search_url = _search_url(box)
                parsed_in_box: dict[str, ParsedListing] = {}

                def _on_page1_retry(attempt: int, _box=box_idx) -> None:
                    logger.info(
                        "Box %d: Seite 1 leer/fehlgeschlagen — Retry %d.",
                        _box, attempt,
                    )
                    human_delay(*DEFAULT_PAGE_DELAY)

                first_results, page_cursors = fetch_with_retry(
                    lambda: _fetch_search_page(page, base_search_url, 1),
                    retries=2,
                    on_retry=_on_page1_retry,
                )

                if not first_results and not page_cursors:
                    html_check = page.content().lower()
                    if "hcaptcha" in html_check or "access denied" in html_check:
                        logger.warning("Box %d: Block/CAPTCHA — übersprungen.", box_idx)
                        continue

                if not first_results:
                    logger.info("Box %d: keine Ergebnisse — übersprungen.", box_idx)
                    continue

                for pl in parse_search_results(
                    {"data": {"presentation": {"staysSearch": {"results": {"searchResults": first_results}}}}}
                ):
                    parsed_in_box[pl.airbnb_id] = pl

                logger.info(
                    "Box %d (von %d): Seite 1 = %d Ergebnisse, %d Cursor",
                    box_idx, len(boxes), len(first_results), len(page_cursors),
                )

                for page_idx, cursor in enumerate(page_cursors[1:_MAX_PAGES], start=2):
                    human_delay(*DEFAULT_PAGE_DELAY)
                    encoded_cursor = urllib.parse.quote(cursor)
                    page_url = base_search_url + f"&cursor={encoded_cursor}"

                    page_results, _ = _fetch_search_page(page, page_url, page_idx)
                    if not page_results:
                        continue
                    for pl in parse_search_results(
                        {"data": {"presentation": {"staysSearch": {"results": {"searchResults": page_results}}}}}
                    ):
                        parsed_in_box[pl.airbnb_id] = pl

                # Filter pro Box: Entire-Home + Distanz (max. Radius).
                filtered = [
                    pl for pl in parsed_in_box.values()
                    if is_entire_home(pl) and _in_radius(pl)
                ]
                # Persist + commit pro Box. Re-Persist im Resume oder
                # Box-Überlapp ist dank Snapshot-Dedup ungefährlich.
                persist_results(session, run, filtered)
                session.commit()
                logger.info(
                    "Box %d: %d/%d nach Filter, persistiert + committet.",
                    box_idx, len(filtered), len(parsed_in_box),
                )

                human_delay(*DEFAULT_PAGE_DELAY)

        # Authoritative Snapshot-Anzahl für diesen Run.
        snap_count = session.execute(
            _sql_select(_sql_func.count()).select_from(Snapshot)
            .where(Snapshot.crawl_run_id == run.id)
        ).scalar_one()

        if snap_count == 0:
            run.status = "failed"
            run.message = "Keine Suchergebnisse über alle Boxen (0 Listings)."
            run.finished_at = datetime.now(timezone.utc)
            session.commit()
            return run

        run.listings_seen = snap_count
        session.commit()
        logger.info(
            "Search-Phase fertig: %d Listings im Run. Starte resilienten Detail-Refresh.",
            snap_count,
        )

        # ============================================================
        # DETAIL-PHASE: an refresh_details delegieren (per-Listing-Commit,
        # Resume via bedrooms IS NOT NULL, Browser-Restart alle 50).
        # ============================================================
        refresh_details(session, search_config, headless=headless)

        run.status = "completed"
        run.finished_at = datetime.now(timezone.utc)

    except Exception as exc:  # noqa: BLE001
        logger.exception("Crawl-Lauf fehlgeschlagen")
        run.status = "failed"
        run.message = str(exc)
        run.finished_at = datetime.now(timezone.utc)

    session.commit()
    return run
