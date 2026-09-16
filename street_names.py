"""Overpass-backed street-name spell-correction, used as a last resort when
neither Nominatim nor OpenCage can resolve a typo'd street.

Both geocoders match against their own address index and simply return
whatever partial match they can when a street name doesn't hit exactly
(e.g. a bare city-level pin) -- neither one does real spell-correction, so a
one-letter typo like "Grott" for "Grote" can silently fall all the way back
to a city-level result with no street at all. This module instead pulls the
real street names OpenStreetMap has near wherever the geocoders *did* manage
to resolve (even just a city-level point), and fuzzy-matches the typed
street against that real, local list -- which is a much safer bet than
guessing a correction out of thin air, since every candidate is a street
that actually exists in that area.
"""

import re
from difflib import get_close_matches

import httpx

from address_validation import normalize_street_text
from config import logger

OVERPASS_ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]

STREET_LOOKUP_RADIUS_M = 1500
MATCH_CUTOFF = 0.75

_LEADING_HOUSE_NUMBER_RE = re.compile(r"^(\S*\d\S*)\s+(.+)$")


def _split_house_number(street_address: str) -> tuple[str, str]:
    """Splits "279 Grott Street" into ("279", "Grott Street"); a street with
    no leading house-number token (e.g. "Grott Street") is returned as
    ("", "Grott Street")."""
    match = _LEADING_HOUSE_NUMBER_RE.match(street_address.strip())
    if match:
        return match.group(1), match.group(2)
    return "", street_address.strip()


def _named_streets_near(client: httpx.Client, lat: float, lon: float, radius_m: int) -> set[str]:
    query = f"""
    [out:json][timeout:15];
    way["highway"]["name"](around:{radius_m},{lat},{lon});
    out tags;
    """
    for endpoint in OVERPASS_ENDPOINTS:
        try:
            response = client.post(endpoint, data={"data": query})
            response.raise_for_status()
            elements = response.json().get("elements", [])
            return {el["tags"]["name"] for el in elements if el.get("tags", {}).get("name")}
        except httpx.HTTPError as exc:
            logger.warning("Overpass street lookup failed near (%s, %s) via %s: %s", lat, lon, endpoint, exc)
    return set()


def suggest_street_correction(client: httpx.Client, street_address: str, lat: float, lon: float) -> str | None:
    """Returns a corrected full street address (house number + a real nearby
    street name), or None if no real street near (lat, lon) is a close
    enough match to be worth retrying the geocode with."""
    house_number, road = _split_house_number(street_address)
    if not road:
        return None

    candidates = _named_streets_near(client, lat, lon, STREET_LOOKUP_RADIUS_M)
    if not candidates:
        return None

    normalized_to_original: dict[str, str] = {}
    for name in candidates:
        normalized_to_original.setdefault(normalize_street_text(name), name)

    matches = get_close_matches(
        normalize_street_text(road), normalized_to_original.keys(), n=1, cutoff=MATCH_CUTOFF
    )
    if not matches:
        return None

    corrected_road = normalized_to_original[matches[0]]
    return f"{house_number} {corrected_road}".strip() if house_number else corrected_road
