DEFAULT_SIZE_CONFIG = {"three_plus_min_bedrooms": 3}


def size_class(bedrooms: int | None, config: dict | None = None) -> str:
    """Leitet die Größenklasse aus der Schlafzimmerzahl ab.

    Studio (0) / 1BR / 2BR / 3BR+ . Ohne verwertbare Angabe: 'unclassified'.
    Die Untergrenze für '3BR+' ist über config['three_plus_min_bedrooms']
    justierbar (Spec §8)."""
    cfg = {**DEFAULT_SIZE_CONFIG, **(config or {})}
    if bedrooms is None:
        return "unclassified"
    if bedrooms <= 0:
        return "Studio"
    if bedrooms == 1:
        return "1BR"
    if bedrooms == 2:
        return "2BR"
    if bedrooms >= cfg["three_plus_min_bedrooms"]:
        return "3BR+"
    return "unclassified"
