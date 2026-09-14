"""OpenStreetMap Overpass lookups: building-footprint existence and adjacency."""

import math
import time

import httpx

from config import logger
from geocoding import ROOFTOP_MATCH_TYPES

# geocode_type values that mean a geocoder already independently confirmed
# this address is a building: Nominatim's own rooftop match types, plus
# OpenCage's equivalent classification from its fallback (stage 4). Used
# only when Overpass itself is unavailable, below.
ROOFTOP_GEOCODE_TYPES = ROOFTOP_MATCH_TYPES | {"opencage:building"}

# Existence checks only care about a building within this distance of the
# address point; adjacency needs to see past that same building out to
# neighbours, hence the wider radius below. Both are fetched from the *same*
# Overpass query (see _overpass_buildings_near's cache) -- the existence
# check just filters the wider result set down to this distance -- so one
# HTTP round trip per address covers both instead of two.
EXISTENCE_CHECK_RADIUS_M = 20
ADJACENCY_SEARCH_RADIUS_M = 30
ADJACENCY_DEFAULT_THRESHOLD_M = 5

# Two independent public Overpass instances. overpass-api.de rate-limits and
# occasionally times out shared cloud IPs (e.g. Render's), which previously
# made a request-failure indistinguishable from a genuine "no building here"
# result and flipped the pipeline path depending on which host happened to
# run it. Falling back to a second mirror keeps the result consistent across
# environments so the verification link a tester opens matches what the
# report said.
OVERPASS_ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]

DEFAULT_RETRY_AFTER_S = 30.0
MAX_RETRY_AFTER_S = 300.0

# Process-lifetime only -- cleared on restart/redeploy, which is fine: it
# exists to stop a burst of addresses in one run from re-querying the same
# spot or re-hammering an endpoint that just rate-limited us, not to persist
# across deploys.
_overpass_cache: dict[tuple[float, float, int], list[dict]] = {}
_endpoint_cooldown_until: dict[str, float] = {}


def _parse_retry_after(value: str | None) -> float:
    if value is None:
        return DEFAULT_RETRY_AFTER_S
    try:
        seconds = float(value)
    except ValueError:
        return DEFAULT_RETRY_AFTER_S
    return max(0.0, min(seconds, MAX_RETRY_AFTER_S))


def _overpass_buildings_near(client: httpx.Client, lat: float, lon: float, radius_m: int) -> list[dict] | None:
    """Returns matched elements, or None if every endpoint was unavailable --
    kept distinct from an empty list (a query that succeeded and found
    nothing) so callers can fall back instead of reporting a false negative."""
    cache_key = (round(lat, 6), round(lon, 6), radius_m)
    cached = _overpass_cache.get(cache_key)
    if cached is not None:
        return cached

    query = f"""
    [out:json][timeout:25];
    (
      way["building"](around:{radius_m},{lat},{lon});
      relation["building"](around:{radius_m},{lat},{lon});
    );
    out geom;
    """
    last_exc = None
    for endpoint in OVERPASS_ENDPOINTS:
        now = time.monotonic()
        cooldown_until = _endpoint_cooldown_until.get(endpoint, 0.0)
        if now < cooldown_until:
            logger.info("Skipping Overpass endpoint %s, in cooldown for %.0fs more", endpoint, cooldown_until - now)
            continue
        try:
            response = client.post(endpoint, data={"data": query})
            if response.status_code == 429:
                retry_after = _parse_retry_after(response.headers.get("Retry-After"))
                _endpoint_cooldown_until[endpoint] = time.monotonic() + retry_after
                logger.warning(
                    "Overpass endpoint %s rate-limited us for (%s, %s); backing off %.0fs",
                    endpoint, lat, lon, retry_after,
                )
                continue
            response.raise_for_status()
            elements = response.json().get("elements", [])
            _overpass_cache[cache_key] = elements
            return elements
        except httpx.HTTPError as exc:
            logger.warning("Overpass query failed for (%s, %s) via %s: %s", lat, lon, endpoint, exc)
            last_exc = exc
    logger.warning("All Overpass endpoints unavailable for (%s, %s): %s", lat, lon, last_exc)
    return None


def _extract_footprint_polygon(element: dict) -> list[list[float]]:
    if element.get("type") == "way":
        return [[node["lat"], node["lon"]] for node in element.get("geometry", []) if node]
    polygon = []
    for member in element.get("members", []):
        if member.get("role") == "outer":
            polygon.extend([[node["lat"], node["lon"]] for node in member.get("geometry", []) if node])
    return polygon


def check_building_footprint(
    client: httpx.Client,
    lat: float,
    lon: float,
    geocode_type: str | None = None,
    radius_m: int = EXISTENCE_CHECK_RADIUS_M,
) -> dict:
    # Fetched at the adjacency radius (wider) so this shares its cached
    # Overpass response with get_nearest_building_distance_m below instead of
    # firing a second query for the same point.
    elements = _overpass_buildings_near(client, lat, lon, ADJACENCY_SEARCH_RADIUS_M)

    if elements is None:
        # Overpass itself is unavailable -- fall back to the geocoder's own
        # rooftop-level classification (Nominatim's "house"/"building" match,
        # or OpenCage's equivalent from its stage-4 fallback) rather than
        # reporting a false "no building here". It has no footprint
        # geometry, so adjacency still can't be checked, but it's a real
        # independent confirmation the address is a building.
        if geocode_type in ROOFTOP_GEOCODE_TYPES:
            return {
                "has_building_footprint": True,
                "building_footprint": None,
                "building_osm_ref": None,
                "ambiguous_existence": False,
            }
        return {
            "has_building_footprint": False,
            "building_footprint": None,
            "building_osm_ref": None,
            "ambiguous_existence": True,
        }

    own_element = None
    for element in elements:
        footprint = _extract_footprint_polygon(element)
        if footprint and _min_distance_m([[lat, lon]], footprint) <= radius_m:
            own_element = element
            break

    if own_element is None:
        return {
            "has_building_footprint": False,
            "building_footprint": None,
            "building_osm_ref": None,
            "ambiguous_existence": True,
        }

    return {
        "has_building_footprint": True,
        "building_footprint": _extract_footprint_polygon(own_element),
        "building_osm_ref": f"{own_element.get('type')}/{own_element.get('id')}",
        "ambiguous_existence": False,
    }


def _to_local_xy(point: list[float], ref_lat: float) -> tuple[float, float]:
    lat, lon = point
    x = lon * 111_320 * math.cos(math.radians(ref_lat))
    y = lat * 111_320
    return x, y


def _point_segment_distance_m(point: list[float], seg_start: list[float], seg_end: list[float], ref_lat: float) -> float:
    px, py = _to_local_xy(point, ref_lat)
    ax, ay = _to_local_xy(seg_start, ref_lat)
    bx, by = _to_local_xy(seg_end, ref_lat)
    abx, aby = bx - ax, by - ay
    length_sq = abx * abx + aby * aby
    if length_sq == 0:
        t = 0.0
    else:
        t = max(0.0, min(1.0, ((px - ax) * abx + (py - ay) * aby) / length_sq))
    closest_x, closest_y = ax + t * abx, ay + t * aby
    return math.hypot(px - closest_x, py - closest_y)


def _polygon_edges(points: list[list[float]]) -> list[tuple[list[float], list[float]]]:
    if len(points) < 2:
        return []
    return [(points[i], points[(i + 1) % len(points)]) for i in range(len(points))]


def _min_distance_m(points_a: list[list[float]], points_b: list[list[float]]) -> float:
    ref_lat = points_a[0][0]
    edges_a = _polygon_edges(points_a)
    edges_b = _polygon_edges(points_b)

    distances = []
    for p in points_a:
        for start, end in edges_b:
            distances.append(_point_segment_distance_m(p, start, end, ref_lat))
    for p in points_b:
        for start, end in edges_a:
            distances.append(_point_segment_distance_m(p, start, end, ref_lat))
    if not distances:
        distances.append(_point_segment_distance_m(points_a[0], points_b[0], points_b[0], ref_lat))
    return min(distances)


def get_nearest_building_distance_m(
    client: httpx.Client,
    lat: float,
    lon: float,
    own_footprint: list[list[float]] | None,
    own_osm_ref: str | None,
    radius_m: int = ADJACENCY_SEARCH_RADIUS_M,
) -> float | None:
    elements = _overpass_buildings_near(client, lat, lon, radius_m)
    if elements is None:
        return None
    own_points = own_footprint if own_footprint else [[lat, lon]]

    nearest = None
    for element in elements:
        if f"{element.get('type')}/{element.get('id')}" == own_osm_ref:
            continue
        neighbor_points = _extract_footprint_polygon(element)
        if not neighbor_points:
            continue
        distance = _min_distance_m(own_points, neighbor_points)
        if nearest is None or distance < nearest:
            nearest = distance
    return nearest
