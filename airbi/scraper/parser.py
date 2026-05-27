"""Parser für Airbnb-Such-Ergebnisse (eingebettetes server-side JSON).

Wandelt den StaysSearch-Payload (aus ``data-deferred-state-0``) in eine
Liste von :class:`~airbi.scraper.models.ParsedListing`-Objekten um.

Einziger öffentlicher Einstiegspunkt: :func:`parse_search_results`.

Das Modul ist rein funktional: kein Netzwerk, kein Browser, keine DB.
"""
from __future__ import annotations

import base64
import re
from decimal import Decimal, InvalidOperation
from typing import Any

from airbi.scraper.models import ListingDetail, ParsedListing


def _dig(obj: Any, *keys: str) -> Any:
    """Sicherer Zugriff auf verschachtelte Dicts; gibt ``None`` zurück,
    wenn ein Schlüssel fehlt oder der Wert kein Dict ist."""
    for key in keys:
        if not isinstance(obj, dict):
            return None
        obj = obj.get(key)
    return obj


def _decode_listing_id(raw_id: str | None) -> str | None:
    """Dekodiert die base64-kodierte Listing-ID und gibt den numerischen
    Teil zurück (z. B. ``"25532057"`` aus ``"DemandStayListing:25532057"``)."""
    if not raw_id:
        return None
    try:
        decoded = base64.b64decode(raw_id).decode("utf-8", errors="replace")
        # Format: "DemandStayListing:25532057"
        if ":" in decoded:
            return decoded.split(":", 1)[1]
        return decoded
    except Exception:
        return None


def _parse_price(price_str: str | None) -> Decimal | None:
    """Extrahiert einen Decimal-Preis aus einem formatierten String.
    Erkennt das Dezimaltrennzeichen als ein '.' oder ',', das von genau
    zwei Ziffern am Ende gefolgt wird; alle anderen '.'/',' sind
    Tausendertrennzeichen."""
    if not price_str:
        return None
    digits = re.sub(r"[^\d.,]", "", price_str)
    if not digits:
        return None
    m = re.search(r"[.,](\d{2})$", digits)
    if m:
        decimals = m.group(1)
        integer = re.sub(r"[.,]", "", digits[: m.start()])
        normalized = f"{integer or '0'}.{decimals}"
    else:
        normalized = re.sub(r"[.,]", "", digits)
    try:
        return Decimal(normalized) if normalized else None
    except InvalidOperation:
        return None


def _parse_rating(avg_rating_localized: str | None) -> tuple[float | None, int]:
    """Parst ``avgRatingLocalized`` (z. B. ``"4.86 (245)"`` oder ``"New"``)
    und gibt ``(rating, review_count)`` zurück."""
    if not avg_rating_localized:
        return None, 0
    # Bewertung in Klammern: "4.86 (245)"
    m = re.match(r"^(\d+(?:\.\d+)?)\s+\((\d+)\)", avg_rating_localized)
    if m:
        return float(m.group(1)), int(m.group(2))
    # Nur Bewertung ohne Review-Anzahl: "4.86"
    m2 = re.match(r"^(\d+(?:\.\d+)?)$", avg_rating_localized.strip())
    if m2:
        return float(m2.group(1)), 0
    # "New" oder andere Werte ohne numerische Bewertung
    return None, 0


def _is_superhost(badges: list[Any]) -> bool:
    """Gibt ``True`` zurück, wenn eines der Badges den Typ ``SUPERHOST`` hat."""
    for badge in badges:
        if not isinstance(badge, dict):
            continue
        logging_ctx = badge.get("loggingContext")
        if isinstance(logging_ctx, dict) and logging_ctx.get("badgeType") == "SUPERHOST":
            return True
    return False


def _parse_property_type(title: str | None) -> str | None:
    """Extrahiert den Property-Typ aus dem Titel (alles vor `` in ``)."""
    if not title:
        return None
    if " in " in title:
        return title.split(" in ", 1)[0]
    return title


# Geordnete Liste der Preis-Pfade unter einem searchResult-Eintrag.
# Erste Variante mit nicht-None-Treffer gewinnt. Liste basiert auf
# Discovery-Befund (siehe scripts/record_stays_search.py Kopfkommentar).
PRICE_PATHS: tuple[tuple[str, ...], ...] = (
    ("structuredDisplayPrice", "primaryLine", "price"),
    ("structuredDisplayPrice", "primaryLine", "discountedPrice"),
)


def _parse_result(r: dict, position: int) -> ParsedListing | None:
    """Verarbeitet einen einzelnen searchResults-Eintrag zu einem ParsedListing.
    Gibt ``None`` zurück, wenn die minimalen Pflichtfelder fehlen."""
    dsl = r.get("demandStayListing")
    if not isinstance(dsl, dict):
        return None

    airbnb_id = _decode_listing_id(dsl.get("id"))
    if not airbnb_id:
        return None

    title_field = _dig(dsl, "description", "name", "localizedStringWithTranslationPreference")
    url = f"https://www.airbnb.com/rooms/{airbnb_id}"

    coord = _dig(dsl, "location", "coordinate")
    lat = coord.get("latitude") if isinstance(coord, dict) else None
    lng = coord.get("longitude") if isinstance(coord, dict) else None

    page_title = r.get("title")
    property_type = _parse_property_type(page_title)

    price = None
    for path in PRICE_PATHS:
        price_str = _dig(r, *path)
        if price_str:
            price = _parse_price(price_str)
            if price is not None:
                break

    rating, review_count = _parse_rating(r.get("avgRatingLocalized"))

    is_superhost = _is_superhost(r.get("badges") or [])

    return ParsedListing(
        airbnb_id=airbnb_id,
        title=title_field,
        url=url,
        lat=lat,
        lng=lng,
        property_type=property_type,
        bedrooms=None,
        beds=None,
        bathrooms=None,
        max_guests=None,
        host_name=None,
        is_superhost=is_superhost,
        price=price,
        fees=None,
        review_count=review_count,
        rating=rating,
        search_position=position,
    )


def _collect_overview_items(payload: dict) -> list[dict]:
    """Durchsucht alle Sections in sbuiData nach overviewItems-Listen und
    gibt eine flache Liste aller gefundenen Items zurück."""
    items: list[dict] = []
    try:
        sc_sections = (
            payload["niobeClientData"][0][1]["data"]
            ["presentation"]["stayProductDetailPage"]["sections"]
            ["sbuiData"]["sectionConfiguration"]["root"]["sections"]
        )
    except (KeyError, IndexError, TypeError):
        return items
    if not isinstance(sc_sections, list):
        return items
    for section in sc_sections:
        section_data = _dig(section, "sectionData")
        if not isinstance(section_data, dict):
            continue
        overview = section_data.get("overviewItems")
        if isinstance(overview, list):
            items.extend(overview)
    return items


def parse_listing_detail(payload: dict) -> ListingDetail:
    """Extrahiert Raumzahlen aus dem Airbnb-Detailseiten-Payload.

    Primäre Quelle: ``overviewItems`` aller Sections in
    ``sbuiData.sectionConfiguration.root.sections``. Die title-Strings
    ("2 guests", "1 bedroom", "1 bed", "1 bath") werden per Regex ausgelesen.
    Fallback für ``max_guests``: ``sharingConfig.personCapacity``.

    Bei unbekanntem / leerem Payload werden alle Felder als ``None``
    zurückgegeben — kein Exception-Raise.

    Args:
        payload: Das rohe Payload-Dict aus dem ``data-deferred-state-0``-Tag
                 der Airbnb-Detailseite.

    Returns:
        :class:`~airbi.scraper.models.ListingDetail` mit den extrahierten
        Werten (nicht gefundene Felder sind ``None``).
    """
    bedrooms: int | None = None
    beds: int | None = None
    bathrooms: float | None = None
    max_guests: int | None = None

    try:
        items = _collect_overview_items(payload)
        for item in items:
            if not isinstance(item, dict):
                continue
            title = item.get("title", "")
            if not isinstance(title, str):
                continue

            # max_guests: "2 guests"
            if max_guests is None:
                m = re.match(r"^(\d+)\s+guest", title, re.IGNORECASE)
                if m:
                    max_guests = int(m.group(1))
                    continue

            # bedrooms: "1 bedroom" / "Studio" → 0
            if bedrooms is None:
                if re.match(r"^studio$", title, re.IGNORECASE):
                    bedrooms = 0
                    continue
                m = re.match(r"^(\d+)\s+bedroom", title, re.IGNORECASE)
                if m:
                    bedrooms = int(m.group(1))
                    continue

            # beds: "1 bed" / "2 beds" (but NOT "1 bedroom")
            if beds is None:
                m = re.match(r"^(\d+)\s+beds?\b", title, re.IGNORECASE)
                if m:
                    beds = int(m.group(1))
                    continue

            # bathrooms: "1 bath" / "1.5 baths" / "1 private bath"
            if bathrooms is None:
                m = re.match(r"^(\d+(?:\.\d+)?)\s+(?:\w+\s+)*bath", title, re.IGNORECASE)
                if m:
                    bathrooms = float(m.group(1))
                    continue

        # Fallback for max_guests via sharingConfig.personCapacity
        if max_guests is None:
            try:
                capacity = (
                    payload["niobeClientData"][0][1]["data"]
                    ["presentation"]["stayProductDetailPage"]["sections"]
                    ["metadata"]["sharingConfig"]["personCapacity"]
                )
                if isinstance(capacity, int):
                    max_guests = capacity
            except (KeyError, IndexError, TypeError):
                pass

    except Exception:
        pass

    return ListingDetail(
        bedrooms=bedrooms,
        beds=beds,
        bathrooms=bathrooms,
        max_guests=max_guests,
    )


def parse_search_results(payload: dict) -> list[ParsedListing]:
    """Wandelt den StaysSearch-Payload in eine Liste von ParsedListing um.

    Falls der Payload nicht die erwartete Struktur hat (z. B. leeres Dict oder
    geändertes Airbnb-Schema), wird eine leere Liste zurückgegeben — kein
    Exception-Raise.

    Args:
        payload: Das rohe Payload-Dict aus dem ``data-deferred-state-0``-Tag,
                 wie es von ``record_stays_search.py`` aufgezeichnet wird.

    Returns:
        Liste von :class:`~airbi.scraper.models.ParsedListing`, 1-basiert
        indiziert über ``search_position``.
    """
    search_results = _dig(
        payload,
        "data", "presentation", "staysSearch", "results", "searchResults",
    )
    if not isinstance(search_results, list) or not search_results:
        return []

    listings: list[ParsedListing] = []
    for position, r in enumerate(search_results, start=1):
        if not isinstance(r, dict):
            continue
        pl = _parse_result(r, position)
        if pl is not None:
            listings.append(pl)

    return listings
