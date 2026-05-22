from airbi.classification.size import size_class
from airbi.classification.price import price_tier


def test_size_class_studio_for_zero_bedrooms():
    assert size_class(0) == "Studio"


def test_size_class_one_two_three_plus():
    assert size_class(1) == "1BR"
    assert size_class(2) == "2BR"
    assert size_class(3) == "3BR+"
    assert size_class(5) == "3BR+"


def test_size_class_unclassified_for_missing_bedrooms():
    assert size_class(None) == "unclassified"


COHORT = [50, 60, 70, 80, 90, 100, 110, 120, 130, 200]


def test_price_tier_budget_for_low_price():
    # Perzentil-Rang von 55 in COHORT = 1/10 = 0.10 -> Budget
    assert price_tier(55, COHORT) == "Budget"


def test_price_tier_mid_for_median_price():
    # Rang von 100 = 5/10 = 0.50 -> Mid
    assert price_tier(100, COHORT) == "Mid"


def test_price_tier_luxury_for_top_price():
    # Rang von 200 = 9/10 = 0.90 -> Luxury
    assert price_tier(200, COHORT) == "Luxury"


def test_price_tier_unclassified_for_missing_price():
    assert price_tier(None, COHORT) == "unclassified"


def test_price_tier_unclassified_for_tiny_cohort():
    assert price_tier(100, [100]) == "unclassified"


def test_price_tier_respects_custom_tiers_from_config():
    config = {"price_tiers": [["Low", 0.0, 0.5], ["High", 0.5, 1.0]]}
    assert price_tier(55, COHORT, config) == "Low"
    assert price_tier(200, COHORT, config) == "High"
