from airbi.classification.size import size_class


def test_size_class_studio_for_zero_bedrooms():
    assert size_class(0) == "Studio"


def test_size_class_one_two_three_plus():
    assert size_class(1) == "1BR"
    assert size_class(2) == "2BR"
    assert size_class(3) == "3BR+"
    assert size_class(5) == "3BR+"


def test_size_class_unclassified_for_missing_bedrooms():
    assert size_class(None) == "unclassified"
