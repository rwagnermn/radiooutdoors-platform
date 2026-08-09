import hashlib
import json
from urllib.parse import urlencode
from urllib.request import urlopen

from django.conf import settings
from django.core.cache import cache

from .pota_parks import normalize_pota_reference

US_STATES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas",
    "CA": "California", "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware",
    "FL": "Florida", "GA": "Georgia", "HI": "Hawaii", "ID": "Idaho",
    "IL": "Illinois", "IN": "Indiana", "IA": "Iowa", "KS": "Kansas",
    "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine", "MD": "Maryland",
    "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota", "MS": "Mississippi",
    "MO": "Missouri", "MT": "Montana", "NE": "Nebraska", "NV": "Nevada",
    "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York",
    "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma",
    "OR": "Oregon", "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina",
    "SD": "South Dakota", "TN": "Tennessee", "TX": "Texas", "UT": "Utah",
    "VT": "Vermont", "VA": "Virginia", "WA": "Washington", "WV": "West Virginia",
    "WI": "Wisconsin", "WY": "Wyoming", "DC": "District of Columbia",
}

def entity_region(entity):
    parts = (entity or "").upper().split("-", 1)
    if len(parts) != 2:
        return {"region_code": parts[-1], "region_name": parts[-1], "country_code": "", "country_name": ""}
    country, region = parts
    return {"region_code": region, "region_name": US_STATES.get(region, region), "country_code": country, "country_name": "United States" if country == "US" else country}

def _component_short(result, component_type):
    for component in result.get("address_components", []):
        if component_type in component.get("types", []):
            return str(component.get("short_name") or "").upper()
    return ""

def geocode_pota_park(reference, park_name, entity):
    region = entity_region(entity)
    query = ", ".join(value for value in (park_name, region["region_name"], region["country_name"]) if value)
    identity = f"{park_name.strip().casefold()}|{entity.strip().upper()}".encode("utf-8")
    cache_key = "pota-park-geocode:" + normalize_pota_reference(reference) + ":" + hashlib.sha256(identity).hexdigest()[:20]
    cached = cache.get(cache_key)
    if cached is not None:
        return cached
    api_key = getattr(settings, "GOOGLE_MAPS_API_KEY", "")
    if not api_key:
        return {"status": "unavailable", "query": query, "candidates": []}
    url = "https://maps.googleapis.com/maps/api/geocode/json?" + urlencode({"address": query, "key": api_key})
    try:
        with urlopen(url, timeout=8) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception:
        result = {"status": "unavailable", "query": query, "candidates": []}
        cache.set(cache_key, result, 900)
        return result
    candidates = []
    wrong_region = False
    for item in payload.get("results", []):
        location = item.get("geometry", {}).get("location", {})
        if "lat" not in location or "lng" not in location:
            continue
        item_region = _component_short(item, "administrative_area_level_1")
        item_country = _component_short(item, "country")
        if region["region_code"] and item_region != region["region_code"]:
            wrong_region = True
            continue
        if region["country_code"] and item_country != region["country_code"]:
            wrong_region = True
            continue
        candidates.append({"label": str(item.get("formatted_address") or park_name), "latitude": str(location["lat"]), "longitude": str(location["lng"])})
    if len(candidates) == 1:
        status = "found"
    elif len(candidates) > 1:
        status = "ambiguous"
    elif wrong_region:
        status = "wrong_region"
    else:
        status = "not_found"
    result = {"status": status, "query": query, "candidates": candidates[:5]}
    cache.set(cache_key, result, 604800 if status == "found" else 3600)
    return result
