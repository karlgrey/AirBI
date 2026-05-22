import json
from pathlib import Path

from shapely.geometry import Point, shape
from shapely.geometry.base import BaseGeometry

_DEFAULT_DATA_DIR = Path(__file__).parent / "data" / "lisboa"


def _extract_geometry(geojson: dict) -> BaseGeometry:
    """Wandelt ein GeoJSON-Objekt (Geometry, Feature oder FeatureCollection)
    in eine einzelne shapely-Geometrie um."""
    kind = geojson.get("type")
    if kind == "FeatureCollection":
        geoms = [shape(f["geometry"]) for f in geojson["features"]]
        if not geoms:
            raise ValueError("FeatureCollection enthält keine Features")
        merged = geoms[0]
        for geom in geoms[1:]:
            merged = merged.union(geom)
        return merged
    if kind == "Feature":
        return shape(geojson["geometry"])
    return shape(geojson)


def load_districts(data_dir: Path | None = None) -> dict[str, BaseGeometry]:
    """Lädt alle *.geojson-Dateien aus dem Verzeichnis. Dateiname (ohne
    Endung) = district_slug."""
    directory = data_dir or _DEFAULT_DATA_DIR
    districts: dict[str, BaseGeometry] = {}
    for path in sorted(directory.glob("*.geojson")):
        with path.open(encoding="utf-8") as fh:
            districts[path.stem] = _extract_geometry(json.load(fh))
    return districts


def assign_district(
    lat: float, lng: float, districts: dict[str, BaseGeometry]
) -> str | None:
    """Ordnet einen Punkt per Punkt-in-Polygon einem district_slug zu.
    Liegt der Punkt in keinem Polygon, wird None zurückgegeben."""
    point = Point(lng, lat)  # GeoJSON-Reihenfolge ist (lng, lat)
    for slug, geometry in districts.items():
        if geometry.contains(point):
            return slug
    return None
