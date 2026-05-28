import math

from airbi.geo.distance import bbox_around, concentric_boxes, haversine_km


def test_haversine_zero_for_identical_point():
    assert haversine_km(38.7391, -9.1048, 38.7391, -9.1048) == 0.0


def test_haversine_symmetric():
    a = haversine_km(38.74, -9.10, 38.70, -9.20)
    b = haversine_km(38.70, -9.20, 38.74, -9.10)
    assert math.isclose(a, b)


def test_haversine_one_degree_lat_about_111km():
    d = haversine_km(38.0, -9.0, 39.0, -9.0)
    assert 110.0 < d < 112.0


def test_bbox_around_contains_center_and_is_about_2r_high():
    sw_lat, sw_lng, ne_lat, ne_lng = bbox_around(38.7391, -9.1048, 2.0)
    assert sw_lat < 38.7391 < ne_lat
    assert sw_lng < -9.1048 < ne_lng
    # halbe Höhe in km ~ Radius
    assert math.isclose((ne_lat - sw_lat) / 2 * 110.574, 2.0, rel_tol=0.05)


def test_concentric_boxes_one_per_radius_and_nested():
    boxes = concentric_boxes(38.7391, -9.1048, [1, 2, 5])
    assert len(boxes) == 3
    inner, _mid, outer = boxes
    assert outer[0] < inner[0] and outer[1] < inner[1]   # sw weiter außen
    assert outer[2] > inner[2] and outer[3] > inner[3]   # ne weiter außen
