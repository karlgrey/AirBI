from decimal import Decimal

# (Name, untere Perzentil-Grenze inkl., obere Perzentil-Grenze exkl.)
DEFAULT_PRICE_TIERS = [
    ["Budget", 0.0, 0.25],
    ["Mid", 0.25, 0.75],
    ["Premium", 0.75, 0.90],
    ["Luxury", 0.90, 1.0],
]


def price_tier(
    price: float | Decimal | None,
    cohort_prices: list[float | Decimal | None],
    config: dict | None = None,
) -> str:
    """Ordnet einen Preis einer Preisstufe zu — über seinen Perzentil-Rang
    innerhalb der Kohorte (Spec §8).

    Der Rang ist der Anteil der Kohorten-Preise, die strikt kleiner als
    'price' sind. Tier-Grenzen über config['price_tiers'] justierbar.
    Ohne Preis oder bei Kohorte < 2 Werten: 'unclassified'."""
    tiers = (config or {}).get("price_tiers") or DEFAULT_PRICE_TIERS
    clean = [float(p) for p in cohort_prices if p is not None]
    if price is None or len(clean) < 2:
        return "unclassified"

    value = float(price)
    rank = sum(1 for p in clean if p < value) / len(clean)
    for name, low, high in tiers:
        if low <= rank < high:
            return name
    return tiers[-1][0]  # rank == 1.0 -> oberste Stufe
