from airbi.classification.amenity import amenity_score


def _score(amenities, **kw):
    base = dict(beds=2, bedrooms=1, max_guests=2, is_superhost=False, rating=4.5)
    base.update(kw)
    return amenity_score(amenities, **base)


def test_amenity_score_zero_for_empty_minimal_listing():
    s = amenity_score([], beds=None, bedrooms=None, max_guests=None,
                      is_superhost=False, rating=None)
    assert s == 0.0


def test_amenity_score_in_unit_range():
    s = _score(["River view", "Air conditioning", "Free street parking"],
               is_superhost=True, rating=5.0)
    assert 0.0 <= s <= 1.0


def test_amenity_score_view_component_rewards_premium_view():
    high = _score(["River view"])
    low = _score(["City skyline view"])
    none = _score([])
    assert high > low > none


def test_amenity_score_premium_amenities_raise_score():
    few = _score(["Wifi"])
    many = _score(["Pool", "Hot tub", "Air conditioning", "Elevator",
                   "Dishwasher", "Smart lock", "Free parking"])
    assert many > few


def test_amenity_score_superhost_and_rating_contribute():
    base = _score(["Wifi"], is_superhost=False, rating=4.0)
    better = _score(["Wifi"], is_superhost=True, rating=5.0)
    assert better > base


def test_amenity_score_weights_configurable():
    amenities = ["River view"]
    default = _score(amenities)
    cfg = {"weights": {"view": 0.0, "premium": 0.30, "richness": 0.15,
                       "comfort": 0.10, "superhost": 0.10, "rating": 0.10}}
    zeroed = _score(amenities, config=cfg)
    assert zeroed < default
