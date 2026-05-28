"""luxury_class (Spec §8): kombinierte Luxusklasse aus Preis-Perzentil und
amenity_score über einen gewichteten Index. Reine Funktion.

luxury_index = w_preis · price_percentile + w_amenity · amenity_score
Klassifizierung über Schwellen → Budget / Mid / Premium / Luxury.
Gewichte/Schwellen über config justierbar (Emerging-Bezirke: amenity-lastig)."""

from __future__ import annotations

LUXURY_CLASSES = ["Budget", "Mid", "Premium", "Luxury"]

DEFAULT_LUXURY_CONFIG: dict = {
    "luxury_weights": {"price": 0.5, "amenity": 0.5},
    "luxury_thresholds": [0.25, 0.5, 0.75],
}


def luxury_class(
    price_percentile: float | None,
    amenity_score: float | None,
    config: dict | None = None,
) -> str:
    """Kombinierte Luxusklasse. ``price_percentile`` None (kein Preis/zu kleine
    Kohorte) → 'unclassified'. ``amenity_score`` None → als 0 behandelt."""
    if price_percentile is None:
        return "unclassified"
    cfg = config or {}
    weights = {**DEFAULT_LUXURY_CONFIG["luxury_weights"], **(cfg.get("luxury_weights") or {})}
    thresholds = cfg.get("luxury_thresholds") or DEFAULT_LUXURY_CONFIG["luxury_thresholds"]

    a = amenity_score if amenity_score is not None else 0.0
    index = weights["price"] * price_percentile + weights["amenity"] * a

    t0, t1, t2 = thresholds[0], thresholds[1], thresholds[2]
    if index < t0:
        return LUXURY_CLASSES[0]
    if index < t1:
        return LUXURY_CLASSES[1]
    if index < t2:
        return LUXURY_CLASSES[2]
    return LUXURY_CLASSES[3]
