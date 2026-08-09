from django.conf import settings


def normalize_pota_reference(value):
    return "".join((value or "").upper().split())


def lookup_pota_park(reference):
    """Return configured public park metadata without credentials or scraping."""
    normalized = normalize_pota_reference(reference)
    data = getattr(settings, "POTA_PARK_REFERENCE_DATA", {}) or {}
    result = data.get(normalized)
    if not isinstance(result, dict):
        return None
    latitude = result.get("latitude")
    longitude = result.get("longitude")
    if latitude is None or longitude is None:
        return None
    return {
        "reference": normalized,
        "name": str(result.get("name") or "").strip(),
        "entity": str(result.get("entity") or "").strip().upper(),
        "latitude": str(latitude),
        "longitude": str(longitude),
        "coordinate_quality": "Approximate park location",
    }
