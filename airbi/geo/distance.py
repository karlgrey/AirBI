"""Distanz- und Bounding-Box-Helfer für die Umkreis-Suche.

Reine Funktionen ohne Browser/DB. Airbnb akzeptiert nur rechteckige
Karten-Viewports; ``concentric_boxes`` liefert pro Band-Radius eine
quadratische Box um das Zielobjekt.
"""

from __future__ import annotations

from math import asin, cos, radians, sin, sqrt

_EARTH_RADIUS_KM = 6371.0088
_KM_PER_DEG_LAT = 110.574
_KM_PER_DEG_LNG_EQ = 111.320


def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Großkreis-Distanz zwischen zwei Punkten in Kilometern."""
    phi1, phi2 = radians(lat1), radians(lat2)
    d_phi = radians(lat2 - lat1)
    d_lambda = radians(lng2 - lng1)
    a = sin(d_phi / 2) ** 2 + cos(phi1) * cos(phi2) * sin(d_lambda / 2) ** 2
    return 2 * _EARTH_RADIUS_KM * asin(sqrt(a))


def bbox_around(
    center_lat: float, center_lng: float, radius_km: float
) -> tuple[float, float, float, float]:
    """Quadratische Bounding-Box um einen Kreis mit ``radius_km``.

    Rückgabe (sw_lat, sw_lng, ne_lat, ne_lng) — dieselbe Reihenfolge, die die
    Airbnb-Such-URL erwartet.
    """
    d_lat = radius_km / _KM_PER_DEG_LAT
    d_lng = radius_km / (_KM_PER_DEG_LNG_EQ * cos(radians(center_lat)))
    return (
        center_lat - d_lat,
        center_lng - d_lng,
        center_lat + d_lat,
        center_lng + d_lng,
    )


def concentric_boxes(
    center_lat: float, center_lng: float, radii_km: list[float]
) -> list[tuple[float, float, float, float]]:
    """Eine Bounding-Box je Radius, alle um dasselbe Zentrum."""
    return [bbox_around(center_lat, center_lng, r) for r in radii_km]
