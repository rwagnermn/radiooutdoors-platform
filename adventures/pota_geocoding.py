import hashlib
import json
import logging
import re
import socket
import ssl
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import urlopen

from django.conf import settings
from django.core.cache import cache

from .pota_parks import normalize_pota_reference

logger = logging.getLogger(__name__)

US_STATES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California", "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware",
    "FL": "Florida", "GA": "Georgia", "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois", "IN": "Indiana", "IA": "Iowa", "KS": "Kansas",
    "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine", "MD": "Maryland", "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota", "MS": "Mississippi",
    "MO": "Missouri", "MT": "Montana", "NE": "Nebraska", "NV": "Nevada", "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York",
    "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma", "OR": "Oregon", "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina",
    "SD": "South Dakota", "TN": "Tennessee", "TX": "Texas", "UT": "Utah", "VT": "Vermont", "VA": "Virginia", "WA": "Washington", "WV": "West Virginia",
    "WI": "Wisconsin", "WY": "Wyoming", "DC": "District of Columbia",
}
GENERIC_SUFFIXES = ("wildlife management area", "national wildlife refuge", "state recreation area", "unique area", "wma")
GENERIC_WORDS = {"area", "state", "national", "wildlife", "management", "recreation", "refuge", "park", "preserve", "wayside", "natural", "feature", "wma", "the", "of"}
REASONABLE_TYPES = {"park", "natural_feature", "tourist_attraction", "campground", "point_of_interest"}
UNRELATED_TYPES = {"street_address", "route", "locality", "postal_code", "residence", "lodging", "store", "restaurant"}

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

def _simple_name(value):
    return " ".join(re.findall(r"[a-z0-9]+", (value or "").casefold()))

def _meaningful_words(value):
    return {word for word in _simple_name(value).split() if word not in GENERIC_WORDS and len(word) > 2}

def _remove_generic_suffix(value):
    simplified = (value or "").strip()
    for suffix in GENERIC_SUFFIXES:
        simplified = re.sub(rf"\s+{re.escape(suffix)}$", "", simplified, flags=re.IGNORECASE).strip()
    return simplified

def _provider_name(item, fallback):
    return str(item.get("name") or item.get("formatted_address") or fallback).split(",", 1)[0].strip()

def _candidate_is_relevant(imported_name, provider_name, item):
    if _simple_name(imported_name) == _simple_name(provider_name):
        return True, "exact"
    imported_words = _meaningful_words(imported_name)
    provider_words = _meaningful_words(provider_name)
    shared = imported_words & provider_words
    strong_name = bool(shared) and (len(shared) >= 2 or shared == imported_words)
    types = set(item.get("types", []))
    reasonable_type = not types or bool(types & REASONABLE_TYPES)
    unrelated = bool(types & UNRELATED_TYPES) and not bool(types & REASONABLE_TYPES)
    return strong_name and reasonable_type and not unrelated, "close"

def _candidate_is_reasonable_place(item):
    """Allow a provider-ranked nearby geographic feature after named lookup fails."""
    types = set(item.get("types", []))
    reasonable_type = bool(types & REASONABLE_TYPES)
    unrelated = bool(types & UNRELATED_TYPES) and not reasonable_type
    return reasonable_type and not unrelated

def _request(query, api_key):
    url = "https://maps.googleapis.com/maps/api/geocode/json?" + urlencode({"address": query, "key": api_key})
    with urlopen(url, timeout=8) as response:
        return json.loads(response.read().decode("utf-8"))

def _provider_failure(status):
    status = (status or "UNKNOWN_ERROR").upper()
    categories = {
        "REQUEST_DENIED": "configuration_denied",
        "OVER_DAILY_LIMIT": "quota_or_billing",
        "OVER_QUERY_LIMIT": "quota_or_billing",
        "INVALID_REQUEST": "invalid_request",
        "UNKNOWN_ERROR": "provider_error",
    }
    safe_messages = {
        "REQUEST_DENIED": "The geocoding provider rejected the server request. Check API restrictions and Geocoding API access.",
        "OVER_DAILY_LIMIT": "The geocoding provider quota or billing limit was reached.",
        "OVER_QUERY_LIMIT": "The geocoding provider quota was reached.",
        "INVALID_REQUEST": "The geocoding provider rejected the location query.",
        "UNKNOWN_ERROR": "The geocoding provider reported a temporary error.",
    }
    return categories.get(status, "provider_error"), safe_messages.get(status, f"Provider response: {status}.")


def geocode_pota_park(reference, park_name, entity, *, force_refresh=False):
    region = entity_region(entity)
    initial_query = ", ".join(value for value in (park_name, region["region_name"], region["country_name"]) if value)
    identity = f"{park_name.strip().casefold()}|{entity.strip().upper()}".encode("utf-8")
    cache_key = "pota-park-geocode:v2:" + normalize_pota_reference(reference) + ":" + hashlib.sha256(identity).hexdigest()[:20]
    cached = None if force_refresh else cache.get(cache_key)
    if cached is not None:
        return cached
    api_key = getattr(settings, "GOOGLE_GEOCODING_API_KEY", "")
    if not api_key:
        return {
            "status": "unavailable",
            "query": initial_query,
            "queries": [initial_query],
            "candidates": [],
            "failure_category": "configuration_missing",
            "failure_reason": "Server-side geocoding is not configured.",
        }

    search_names = [park_name]
    simplified = _remove_generic_suffix(park_name)
    if simplified and _simple_name(simplified) != _simple_name(park_name):
        search_names.append(simplified)
    queries, candidates, nearby_candidates, wrong_region = [], [], [], False
    try:
        for search_name in search_names:
            query = ", ".join(value for value in (search_name, region["region_name"], region["country_name"]) if value)
            queries.append(query)
            payload = _request(query, api_key)
            provider_status = str(payload.get("status") or ("OK" if "results" in payload else "")).upper()
            if provider_status not in {"OK", "ZERO_RESULTS"}:
                category, reason = _provider_failure(provider_status)
                logger.warning("POTA geocoding provider failure: category=%s status=%s", category, provider_status or "UNKNOWN_ERROR")
                result = {"status": "unavailable", "query": initial_query, "queries": queries, "candidates": [], "failure_category": category, "failure_reason": reason}
                cache.set(cache_key, result, 900)
                return result
            for item in payload.get("results", []):
                location = item.get("geometry", {}).get("location", {})
                if "lat" not in location or "lng" not in location:
                    continue
                if region["region_code"] and _component_short(item, "administrative_area_level_1") != region["region_code"]:
                    wrong_region = True
                    continue
                if region["country_code"] and _component_short(item, "country") != region["country_code"]:
                    wrong_region = True
                    continue
                provider_name = _provider_name(item, park_name)
                accepted, match_kind = _candidate_is_relevant(park_name, provider_name, item)
                if accepted:
                    candidates.append({"label": str(item.get("formatted_address") or provider_name), "provider_name": provider_name, "latitude": str(location["lat"]), "longitude": str(location["lng"]), "match_kind": match_kind})
                elif _candidate_is_reasonable_place(item):
                    nearby_candidates.append({"label": str(item.get("formatted_address") or provider_name), "provider_name": provider_name, "latitude": str(location["lat"]), "longitude": str(location["lng"]), "match_kind": "nearby"})
            if candidates:
                break
    except Exception as exc:
        reason = getattr(exc, "reason", None)
        if isinstance(exc, HTTPError):
            category = "http_error"
        elif isinstance(reason, PermissionError):
            category = "network_permission"
        elif isinstance(reason, socket.gaierror):
            category = "dns_failure"
        elif isinstance(reason, ssl.SSLError):
            category = "tls_failure"
        elif isinstance(exc, (TimeoutError, socket.timeout)) or isinstance(reason, (TimeoutError, socket.timeout)):
            category = "timeout"
        elif isinstance(exc, URLError):
            category = "network_failure"
        else:
            category = "transport_error"
        logger.warning("POTA geocoding transport failure: category=%s exception=%s", category, type(exc).__name__)
        result = {"status": "unavailable", "query": initial_query, "queries": queries or [initial_query], "candidates": [], "failure_category": category, "failure_reason": f"Geocoding transport failure ({category})."}
        cache.set(cache_key, result, 900)
        return result

    if not candidates and nearby_candidates:
        # Google orders geocoding results by relevance to the named query. After
        # enforcing state/country and geographic-feature type, retain its first
        # result as an explicitly approximate nearby-place fallback.
        candidates = nearby_candidates[:1]
    status = "found" if len(candidates) == 1 else "ambiguous" if candidates else "wrong_region" if wrong_region else "not_found"
    result = {"status": status, "query": initial_query, "queries": queries, "candidates": candidates[:5], "failure_reason": ""}
    cache.set(cache_key, result, 604800 if status == "found" else 3600)
    return result
