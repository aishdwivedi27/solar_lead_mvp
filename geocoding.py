"""Worldwide address geocoding via Nominatim's structured search API.

Uses the structured query fields (street/city/state/postalcode/country)
rather than a single free-text `q` string, and does not restrict results to
any one country -- callers pass whichever country the lead supplied.

When Nominatim (OpenStreetMap data) only resolves an address to a road --
because the building itself isn't mapped in OSM -- the OpenCage Geocoding
API is used as a rooftop-level fallback (see `_geocode_opencage`). OpenCage
blends OSM with other open address datasets, so it isn't limited by the
same OSM gaps, and its free trial signup needs no credit card. That
fallback is metered by an on-disk cache (never re-request an address
already looked up) and an on-disk daily counter (never exceed
OPENCAGE_DAILY_REQUEST_LIMIT requests/day), so lead volume can't run up
unexpected OpenCage usage, and a per-call pause respects OpenCage's own
1-request/second limit.
"""

import json
import threading
import time
from datetime import date
from pathlib import Path

import httpx

from config import OPENCAGE_API_KEY, OPENCAGE_DAILY_REQUEST_LIMIT, logger

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
    if cache_key in cache:
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


def geocode_address(
    client: httpx.Client,
    street_address: str,
    city: str = "",
    state_region: str = "",
    postal_code: str = "",
    country: str = "",
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

    if nominatim_result["low_confidence_geocode"]:
        opencage_result = _geocode_opencage(client, street_address, city, state_region, postal_code, country)
        if opencage_result is not None:
            if not opencage_result["low_confidence_geocode"]:
                return opencage_result
            # Nominatim found nothing at all -- a low-confidence OpenCage guess
            # still gives the caller a "did you mean" address to offer, which
            # beats surfacing a bare "couldn't confirm" with no suggestion.
            if nominatim_result["latitude"] is None and opencage_result["latitude"] is not None:
                return opencage_result

    return nominatim_result


def nominatim_rate_limit_pause() -> None:
    time.sleep(NOMINATIM_MIN_DELAY_SECONDS)
