from pathlib import Path

from airbi.geo.districts import assign_district, load_districts

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "geo"
REAL_DATA_DIR = Path(__file__).parents[1] / "airbi" / "geo" / "data" / "lisboa"

# Zielobjekt aus Briefing §12: R. Cap. Leitão 86, Bezirk Marvila.
MARVILA_TARGET = (38.7390, -9.1044)


def test_load_districts_reads_geojson_by_slug():
    districts = load_districts(FIXTURE_DIR)
    assert "testdistrict" in districts


def test_point_inside_polygon_is_assigned():
    districts = load_districts(FIXTURE_DIR)
    assert assign_district(0.0, 0.0, districts) == "testdistrict"


def test_point_outside_polygon_returns_unassigned():
    districts = load_districts(FIXTURE_DIR)
    assert assign_district(5.0, 5.0, districts) == "unassigned"


def test_real_marvila_polygon_contains_target_object():
    districts = load_districts(REAL_DATA_DIR)
    lat, lng = MARVILA_TARGET
    assert assign_district(lat, lng, districts) == "marvila"
