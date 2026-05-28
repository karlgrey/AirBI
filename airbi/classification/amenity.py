"""amenity_score (Spec §7): listing-lokaler Ausstattungs-Score in 0..1.

Reine Funktion — kein Netzwerk, keine DB. Gewichte und Amenity-Listen sind
über `config` (SearchConfig.classification_config) justierbar; sinnvolle
Defaults sind hier verankert."""

from __future__ import annotations

DEFAULT_AMENITY_CONFIG: dict = {
    "weights": {
        "view": 0.25,
        "premium": 0.30,
        "richness": 0.15,
        "comfort": 0.10,
        "superhost": 0.10,
        "rating": 0.10,
    },
    "view_premium": [
        "river view", "sea view", "ocean view", "waterfront",
        "lake view", "beach view",
    ],
    "view_secondary": [
        "city skyline view", "city view", "skyline view",
        "garden view", "courtyard view", "mountain view", "harbor view",
    ],
    "premium_amenities": [
        "pool", "hot tub", "air conditioning", "free parking",
        "free street parking", "paid parking", "elevator", "dishwasher",
        "smart lock", "self check-in", "gym", "ev charger",
        "private patio or balcony", "outdoor furniture", "bbq grill",
        # Bewusst KEIN "dryer": würde als Substring das allgegenwärtige
        # "Hair dryer" matchen und den Premium-Count verfälschen.
    ],
    "premium_target": 6,
    "richness_target": 40,
}


def _merge(config: dict | None) -> dict:
    cfg = {**DEFAULT_AMENITY_CONFIG, **(config or {})}
    cfg["weights"] = {**DEFAULT_AMENITY_CONFIG["weights"], **((config or {}).get("weights") or {})}
    return cfg


def _clamp(x: float) -> float:
    return 0.0 if x < 0 else (1.0 if x > 1 else x)


def amenity_score(
    amenities: list[str] | None,
    *,
    beds: int | None,
    bedrooms: int | None,
    max_guests: int | None,
    is_superhost: bool,
    rating: float | None,
    config: dict | None = None,
) -> float:
    """Gewichteter Ausstattungs-Score in 0..1. Fehlende Eingaben → die
    jeweilige Komponente trägt 0 bei (kein Crash)."""
    cfg = _merge(config)
    w = cfg["weights"]
    names = [a.lower() for a in (amenities or []) if isinstance(a, str)]

    if any(any(p in a for a in names) for p in cfg["view_premium"]):
        view = 1.0
    elif any(any(p in a for a in names) for p in cfg["view_secondary"]):
        view = 0.6
    else:
        view = 0.0

    present = sum(1 for p in cfg["premium_amenities"] if any(p in a for a in names))
    premium = _clamp(present / cfg["premium_target"]) if cfg["premium_target"] else 0.0

    richness = _clamp(len(names) / cfg["richness_target"]) if cfg["richness_target"] else 0.0

    space = beds if beds is not None else bedrooms
    if space is not None and max_guests:
        comfort = _clamp(space / max_guests)
    else:
        comfort = 0.0

    superhost = 1.0 if is_superhost else 0.0

    rating_score = _clamp((rating - 4.0) / 1.0) if rating is not None else 0.0

    score = (
        w["view"] * view
        + w["premium"] * premium
        + w["richness"] * richness
        + w["comfort"] * comfort
        + w["superhost"] * superhost
        + w["rating"] * rating_score
    )
    return round(_clamp(score), 4)
