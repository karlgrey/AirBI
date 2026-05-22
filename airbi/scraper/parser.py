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

from airbi.scraper.models import ParsedListing


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
    """Extrahiert die erste Zahl (mit optionalem Dezimaltrenner) aus einem
    formatierten Preisstring wie ``"€ 817"`` oder ``"$ 1,234.56"``."""
    if not price_str:
        return None
    # Entferne alle Nicht-Ziffern außer Punkt und Komma, dann normalisiere
    match = re.search(r"[\d]+(?:[.,]\d+)*", price_str.replace(" ", ""))
    if not match:
        return None
    # Normalisiere: deutsches Format "1.234,56" → "1234.56", oder "1,234.56" → "1234.56"
    raw = match.group(0)
    # Wenn Komma als Dezimaltrenner (kein Punkt nach Komma), ersetze Komma durch Punkt
    if "," in raw and "." not in raw:
        raw = raw.replace(",", ".")
    else:
        # Tausendertrennzeichen entfernen
        raw = raw.replace(",", "")
    try:
        return Decimal(raw)
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

    price_str = _dig(r, "structuredDisplayPrice", "primaryLine", "price")
    price = _parse_price(price_str)

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
