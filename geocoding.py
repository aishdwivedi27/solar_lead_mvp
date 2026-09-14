"""Worldwide address geocoding via Nominatim's structured search API.

Uses the structured query fields (street/city/state/postalcode/country)
rather than a single free-text `q` string, and does not restrict results to
any one country -- callers pass whichever country the lead supplied.
"""

import time

import httpx

from config import logger

NOMINATIM_MIN_DELAY_SECONDS = 1.0
ROOFTOP_MATCH_TYPES = {"house", "building"}


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


def _to_geocode_result(result: dict) -> dict:
    match_type = result.get("addresstype") or result.get("type")
    return {
        "latitude": float(result["lat"]),
        "longitude": float(result["lon"]),
        "geocode_type": match_type,
        "geocode_importance": result.get("importance"),
        "low_confidence_geocode": match_type not in ROOFTOP_MATCH_TYPES,
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

    if best is None:
        return {
            "latitude": None,
            "longitude": None,
            "geocode_type": None,
            "geocode_importance": None,
            "low_confidence_geocode": True,
        }

    return _to_geocode_result(best)


def nominatim_rate_limit_pause() -> None:
    time.sleep(NOMINATIM_MIN_DELAY_SECONDS)
