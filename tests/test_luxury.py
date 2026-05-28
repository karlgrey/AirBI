from airbi.classification.luxury import LUXURY_CLASSES, luxury_class
from airbi.classification.price import price_percentile


COHORT = [50, 60, 70, 80, 90, 100, 110, 120, 130, 200]


def test_price_percentile_rank():
    assert price_percentile(55, COHORT) == 0.1
    assert price_percentile(200, COHORT) == 0.9
    assert price_percentile(None, COHORT) is None
    assert price_percentile(100, [100]) is None


def test_luxury_classes_constant():
    assert LUXURY_CLASSES == ["Budget", "Mid", "Premium", "Luxury"]


def test_luxury_class_pure_price_when_amenity_zero():
    assert luxury_class(0.1, 0.0) == "Budget"
    assert luxury_class(0.9, 0.0) == "Mid"
    assert luxury_class(1.0, 1.0) == "Luxury"


def test_luxury_class_amenity_lifts_class():
    low_amenity = luxury_class(0.5, 0.0)
    high_amenity = luxury_class(0.5, 1.0)
    assert LUXURY_CLASSES.index(high_amenity) > LUXURY_CLASSES.index(low_amenity)


def test_luxury_class_emerging_weighting():
    cfg = {"luxury_weights": {"price": 0.35, "amenity": 0.65}}
    assert luxury_class(0.2, 0.9, cfg) == "Premium"


def test_luxury_class_unclassified_without_percentile():
    assert luxury_class(None, 0.5) == "unclassified"
