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


def geocode_address(
    client: httpx.Client,
    street_address: str,
    city: str = "",
    state_region: str = "",
    postal_code: str = "",
    country: str = "",
) -> dict:
    params = {
        "format": "json",
        "addressdetails": 1,
        "limit": 1,
        "street": street_address,
        "city": city,
        "state": state_region,
        "postalcode": postal_code,
        "country": country,
    }
    params = {k: v for k, v in params.items() if v}

    try:
        response = client.get("https://nominatim.openstreetmap.org/search", params=params)
        response.raise_for_status()
        results = response.json()
    except httpx.HTTPError as exc:
        logger.warning("Nominatim geocode failed for %r: %s", street_address, exc)
        results = []

    if not results:
        return {
            "latitude": None,
            "longitude": None,
            "geocode_type": None,
            "geocode_importance": None,
            "low_confidence_geocode": True,
        }

    result = results[0]
    match_type = result.get("addresstype") or result.get("type")
    return {
        "latitude": float(result["lat"]),
        "longitude": float(result["lon"]),
        "geocode_type": match_type,
        "geocode_importance": result.get("importance"),
        "low_confidence_geocode": match_type not in ROOFTOP_MATCH_TYPES,
    }


def nominatim_rate_limit_pause() -> None:
    time.sleep(NOMINATIM_MIN_DELAY_SECONDS)
