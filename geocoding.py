"""Worldwide address geocoding via Nominatim's structured search API.

Uses the structured query fields (street/city/state/postalcode/country)
rather than a single free-text `q` string, and does not restrict results to
any one country -- callers pass whichever country the lead supplied.

The OpenCage Geocoding API is queried on every lookup as a second opinion
(see `_geocode_opencage`), and `_pick_geocode_result` returns whichever of
the two results actually resolved a rooftop- or street-level match.
OpenCage blends OSM with other open address datasets, so it isn't limited
by the same OSM coverage gaps Nominatim has; its free trial signup needs no
credit card. That extra call is metered by an on-disk cache (never
re-request an address already looked up) and an on-disk daily counter
(never exceed OPENCAGE_DAILY_REQUEST_LIMIT requests/day), so lead volume
can't run up unexpected OpenCage usage, and a per-call pause respects
OpenCage's own 1-request/second limit.

Neither geocoder actually spell-corrects a typo'd street name -- each just
matches against its own address index and returns whatever partial match it
can (typically a bare city-level pin) when the street doesn't hit exactly.
When that happens, `geocode_address` falls through to a third stage
(street_names.suggest_street_correction): it looks up the real street names
OpenStreetMap has near wherever the geocoders did resolve, fuzzy-matches
the typed street against that real local list (e.g. "Grott" -> "Grote"),
and retries the geocode with the corrected name.
"""

import json
import threading
import time
from datetime import date
from pathlib import Path

import httpx

from config import OPENCAGE_API_KEY, OPENCAGE_DAILY_REQUEST_LIMIT, logger
from street_names import suggest_street_correction

NOMINATIM_MIN_DELAY_SECONDS = 1.0
ROOFTOP_MATCH_TYPES = {"house", "building"}

# Fallback chain for the locality name -- Nominatim/OpenCage use whichever of
# these fits the place (a suburb inside a city, a standalone town, etc.).
_LOCALITY_KEYS = ("suburb", "city", "town", "village")

OPENCAGE_GEOCODE_URL = "https://api.opencagedata.com/geocode/v1/json"
OPENCAGE_ROOFTOP_TYPES = {"building"}
OPENCAGE_MIN_DELAY_SECONDS = 1.0  # OpenCage free trial is limited to 1 request/second.
OPENCAGE_CACHE_PATH = Path(__file__).parent / "opencage_geocode_cache.json"
OPENCAGE_USAGE_PATH = Path(__file__).parent / "opencage_daily_usage.json"

# Guards the cache/usage files and request pacing against concurrent requests
# within this process (the app runs as a single FastAPI/uvicorn process, so a
# process-local lock is enough -- no multi-process/multi-worker access to
# guard against).
_opencage_state_lock = threading.Lock()
_opencage_last_request_at = 0.0


def _nominatim_search(client: httpx.Client, street_address: str, params: dict) -> list[dict]:
    params = {k: v for k, v in params.items() if v}
    try:
        response = client.get("https://nominatim.openstreetmap.org/search", params=params)
        response.raise_for_status()
        return response.json()
    except httpx.HTTPError as exc:
        logger.warning("Nominatim geocode failed for %r: %s", street_address, exc)
        return []


def _best_result(results: list[dict]) -> dict | None:
    """Prefer a rooftop-level (house/building) match over whatever Nominatim ranked first."""
    if not results:
        return None
    for result in results:
        match_type = result.get("addresstype") or result.get("type")
        if match_type in ROOFTOP_MATCH_TYPES:
            return result
    return results[0]


def _load_json(path: Path, default: dict) -> dict:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return default


def _save_json(path: Path, data: dict) -> None:
    try:
        path.write_text(json.dumps(data))
    except OSError as exc:
        logger.warning("Failed to persist %s: %s", path.name, exc)


def _opencage_cache_key(street_address: str, city: str, state_region: str, postal_code: str, country: str) -> str:
    return "|".join(
        part.strip().lower() for part in (street_address, city, state_region, postal_code, country)
    )


# The full shape a cached OpenCage result must have to be trusted. Bumping
# this whenever the result dict gains a field means a cache entry written by
# an older version of this code (missing the new field) is treated as a
# miss and transparently refetched, instead of being trusted as-is forever
# -- an on-disk cache has no other way to notice the code around it changed.
_OPENCAGE_RESULT_KEYS = {
    "latitude", "longitude", "geocode_type", "geocode_importance",
    "low_confidence_geocode", "resolved_display_name", "resolved_components",
}


def _is_valid_cached_opencage_result(value) -> bool:
    return value is None or (isinstance(value, dict) and _OPENCAGE_RESULT_KEYS.issubset(value))


def _opencage_request_allowed_and_recorded() -> bool:
    """Checks today's OpenCage request count against the daily cap and, if under it, records one more use.

    Check-and-record happens under one lock acquisition so concurrent
    lookups can't both pass the check and jointly exceed the cap.
    """
    today = date.today().isoformat()
    with _opencage_state_lock:
        usage = _load_json(OPENCAGE_USAGE_PATH, {"date": today, "count": 0})
        if usage.get("date") != today:
            usage = {"date": today, "count": 0}
        if usage["count"] >= OPENCAGE_DAILY_REQUEST_LIMIT:
            return False
        usage["count"] += 1
        _save_json(OPENCAGE_USAGE_PATH, usage)
        return True


def _opencage_rate_limit_wait() -> None:
    """Sleeps as needed so OpenCage requests stay at or under 1/second, per its free-trial limit."""
    global _opencage_last_request_at
    with _opencage_state_lock:
        elapsed = time.monotonic() - _opencage_last_request_at
        if elapsed < OPENCAGE_MIN_DELAY_SECONDS:
            time.sleep(OPENCAGE_MIN_DELAY_SECONDS - elapsed)
        _opencage_last_request_at = time.monotonic()


def _geocode_opencage(
    client: httpx.Client,
    street_address: str,
    city: str,
    state_region: str,
    postal_code: str,
    country: str,
) -> dict | None:
    """Rooftop-level fallback via OpenCage, metered by a cache and a daily cap.

    Returns None (falls through to the Nominatim result) whenever OpenCage
    isn't configured, the daily cap is already spent, or OpenCage has
    nothing better than Nominatim already found.
    """
    if not OPENCAGE_API_KEY:
        return None

    cache_key = _opencage_cache_key(street_address, city, state_region, postal_code, country)
    with _opencage_state_lock:
        cache = _load_json(OPENCAGE_CACHE_PATH, {})
    if cache_key in cache and _is_valid_cached_opencage_result(cache[cache_key]):
        return cache[cache_key]

    if not _opencage_request_allowed_and_recorded():
        logger.warning(
            "OpenCage daily request limit (%d) reached; skipping fallback for %r",
            OPENCAGE_DAILY_REQUEST_LIMIT,
            street_address,
        )
        return None

    query = ", ".join(part for part in (street_address, city, state_region, postal_code, country) if part)

    _opencage_rate_limit_wait()
    try:
        response = client.get(
            OPENCAGE_GEOCODE_URL,
            params={"q": query, "key": OPENCAGE_API_KEY, "limit": 1, "no_annotations": 1},
        )
        response.raise_for_status()
        results = response.json().get("results", [])
    except httpx.HTTPError as exc:
        logger.warning("OpenCage geocode failed for %r: %s", street_address, exc)
        return None

    result = None
    if results:
        item = results[0]
        components = item.get("components", {})
        result_type = components.get("_type")
        geometry = item.get("geometry", {})
        result = {
            "latitude": geometry.get("lat"),
            "longitude": geometry.get("lng"),
            "geocode_type": f"opencage:{result_type}",
            "geocode_importance": item.get("confidence"),
            "low_confidence_geocode": result_type not in OPENCAGE_ROOFTOP_TYPES,
            "resolved_display_name": item.get("formatted"),
            "resolved_components": _resolved_components_from_map(components),
        }

    with _opencage_state_lock:
        cache = _load_json(OPENCAGE_CACHE_PATH, {})
        cache[cache_key] = result
        _save_json(OPENCAGE_CACHE_PATH, cache)

    return result


def _resolved_components_from_map(address: dict, locality_keys: tuple = _LOCALITY_KEYS) -> dict:
    """Normalizes a Nominatim `address` dict or OpenCage `components` dict into
    the shape address_validation.py compares against user input."""
    locality = next((address[key] for key in locality_keys if address.get(key)), "")
    return {
        "house_number": address.get("house_number", ""),
        "road": address.get("road", ""),
        "locality": locality,
        "state": address.get("state", ""),
        "postal_code": address.get("postcode", ""),
    }


def _has_road_match(geocode_result: dict) -> bool:
    return bool(geocode_result.get("resolved_components", {}).get("road"))


def _pick_geocode_result(nominatim_result: dict, opencage_result: dict | None) -> dict:
    """Nominatim is queried first, but OpenCage is now consulted on every
    lookup as a second opinion, since it blends OSM with other open address
    datasets and so isn't limited by the same coverage gaps. Whichever
    result actually resolved a rooftop-level or street-level match wins."""
    if opencage_result is None:
        return nominatim_result
    if nominatim_result["latitude"] is None:
        return opencage_result
    if not opencage_result["low_confidence_geocode"]:
        return opencage_result
    if not nominatim_result["low_confidence_geocode"]:
        return nominatim_result
    # Both are low-confidence: prefer whichever actually resolved a street,
    # since a specific (if unverified) street beats a bare city-level pin.
    if _has_road_match(opencage_result) and not _has_road_match(nominatim_result):
        return opencage_result
    return nominatim_result


def _to_geocode_result(result: dict) -> dict:
    match_type = result.get("addresstype") or result.get("type")
    return {
        "latitude": float(result["lat"]),
        "longitude": float(result["lon"]),
        "geocode_type": match_type,
        "geocode_importance": result.get("importance"),
        "low_confidence_geocode": match_type not in ROOFTOP_MATCH_TYPES,
        "resolved_display_name": result.get("display_name"),
        "resolved_components": _resolved_components_from_map(result.get("address", {})),
    }


def _geocode_once(
    client: httpx.Client,
    street_address: str,
    city: str,
    state_region: str,
    postal_code: str,
    country: str,
) -> dict:
    base_params = {
        "format": "json",
        "addressdetails": 1,
        "limit": 5,
        "street": street_address,
        "city": city,
        "state": state_region,
        "country": country,
    }

    results = _nominatim_search(client, street_address, {**base_params, "postalcode": postal_code})
    best = _best_result(results)

    # A rooftop point may exist but get excluded by an over-strict postcode match --
    # retry once without it before settling for a road/area-level fallback.
    if postal_code and (best is None or (best.get("addresstype") or best.get("type")) not in ROOFTOP_MATCH_TYPES):
        nominatim_rate_limit_pause()
        retry_results = _nominatim_search(client, street_address, base_params)
        retry_best = _best_result(retry_results)
        if retry_best is not None and (retry_best.get("addresstype") or retry_best.get("type")) in ROOFTOP_MATCH_TYPES:
            best = retry_best
        elif best is None:
            best = retry_best

    nominatim_result = (
        {
            "latitude": None,
            "longitude": None,
            "geocode_type": None,
            "geocode_importance": None,
            "low_confidence_geocode": True,
            "resolved_display_name": None,
            "resolved_components": {},
        }
        if best is None
        else _to_geocode_result(best)
    )

    opencage_result = _geocode_opencage(client, street_address, city, state_region, postal_code, country)
    return _pick_geocode_result(nominatim_result, opencage_result)


def geocode_address(
    client: httpx.Client,
    street_address: str,
    city: str = "",
    state_region: str = "",
    postal_code: str = "",
    country: str = "",
) -> dict:
    picked = _geocode_once(client, street_address, city, state_region, postal_code, country)

    # Neither geocoder resolved a street or rooftop match (typically a bare
    # city-level pin) -- last resort: look up the real street names OSM has
    # near wherever they *did* resolve, and see if the typed street is a
    # near-miss for one of them (e.g. "Grott" -> "Grote"). Only worth trying
    # once we have some point to search around, and only for a genuine
    # improvement (a road actually turns up); an unhelpful correction just
    # falls through to the original result. A rooftop/building-level pick is
    # already a good resolution even on the rare mocked/real response that
    # doesn't happen to echo back a "road" field, so this is gated on
    # low-confidence rather than on the road field alone.
    if (
        street_address
        and picked["low_confidence_geocode"]
        and not _has_road_match(picked)
        and picked["latitude"] is not None
    ):
        corrected_street = suggest_street_correction(client, street_address, picked["latitude"], picked["longitude"])
        if corrected_street:
            corrected_picked = _geocode_once(client, corrected_street, city, state_region, postal_code, country)
            if _has_road_match(corrected_picked):
                return corrected_picked

    return picked


def nominatim_rate_limit_pause() -> None:
    time.sleep(NOMINATIM_MIN_DELAY_SECONDS)
