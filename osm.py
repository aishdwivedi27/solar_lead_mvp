"""OpenStreetMap Overpass lookups: building-footprint existence and adjacency."""

import math

import httpx

from config import logger

# Adjacency search radius must be wider than the existence-check radius below
# -- it needs to see past the record's own building to any neighbours -- but
# the threshold below is what actually decides the flag.
ADJACENCY_SEARCH_RADIUS_M = 30
ADJACENCY_DEFAULT_THRESHOLD_M = 5


def _overpass_buildings_near(client: httpx.Client, lat: float, lon: float, radius_m: int) -> list[dict]:
    query = f"""
    [out:json][timeout:25];
    (
      way["building"](around:{radius_m},{lat},{lon});
      relation["building"](around:{radius_m},{lat},{lon});
    );
    out geom;
    """
    try:
        response = client.post(
            "https://overpass-api.de/api/interpreter",
            data={"data": query},
        )
        response.raise_for_status()
        return response.json().get("elements", [])
    except httpx.HTTPError as exc:
        logger.warning("Overpass query failed for (%s, %s): %s", lat, lon, exc)
        return []


def _extract_footprint_polygon(element: dict) -> list[list[float]]:
    if element.get("type") == "way":
        return [[node["lat"], node["lon"]] for node in element.get("geometry", []) if node]
    polygon = []
    for member in element.get("members", []):
        if member.get("role") == "outer":
            polygon.extend([[node["lat"], node["lon"]] for node in member.get("geometry", []) if node])
    return polygon


def check_building_footprint(client: httpx.Client, lat: float, lon: float, radius_m: int = 20) -> dict:
    elements = _overpass_buildings_near(client, lat, lon, radius_m)

    if not elements:
        return {
            "has_building_footprint": False,
            "building_footprint": None,
            "building_osm_ref": None,
            "ambiguous_existence": True,
        }

    element = elements[0]
    return {
        "has_building_footprint": True,
        "building_footprint": _extract_footprint_polygon(element),
        "building_osm_ref": f"{element.get('type')}/{element.get('id')}",
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
