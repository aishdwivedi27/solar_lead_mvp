"""Copernicus Sentinel-2 auth and NDVI lookups."""

import math
from datetime import datetime, timedelta, timezone

import httpx

from config import COPERNICUS_CLIENT_ID, COPERNICUS_CLIENT_SECRET, logger

COPERNICUS_TOKEN_URL = "https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token"
COPERNICUS_STATS_URL = "https://sh.dataspace.copernicus.eu/api/v1/statistics"
NDVI_BUFFER_RADIUS_M = 15
NDVI_SEARCH_WINDOW_DAYS = 60
NDVI_MAX_CLOUD_COVERAGE = 20

# Statistical API names output bands by position (B0, B1), not by input band
# name, so the order here (Red, then NIR) is what makes B0 == Red, B1 == NIR
# below. Verified against a live request/response before relying on this.
NDVI_EVALSCRIPT = """
//VERSION=3
function setup() {
  return {
    input: [{ bands: ["B04", "B08", "dataMask"] }],
    output: [
      { id: "default", bands: 2, sampleType: "FLOAT32" },
      { id: "dataMask", bands: 1 }
    ]
  };
}
function evaluatePixel(sample) {
  return {
    default: [sample.B04, sample.B08],
    dataMask: [sample.dataMask]
  };
}
"""


def get_copernicus_token(client: httpx.Client) -> str | None:
    if not COPERNICUS_CLIENT_ID or not COPERNICUS_CLIENT_SECRET:
        return None
    try:
        response = client.post(
            COPERNICUS_TOKEN_URL,
            data={
                "grant_type": "client_credentials",
                "client_id": COPERNICUS_CLIENT_ID,
                "client_secret": COPERNICUS_CLIENT_SECRET,
            },
        )
        response.raise_for_status()
        return response.json()["access_token"]
    except (httpx.HTTPError, KeyError) as exc:
        logger.warning("Copernicus auth failed: %s", exc)
        return None


def _bbox_from_point(lat: float, lon: float, radius_m: int) -> list[float]:
    dlat = radius_m / 111_320
    dlon = radius_m / (111_320 * math.cos(math.radians(lat)))
    return [lon - dlon, lat - dlat, lon + dlon, lat + dlat]


def get_ndvi(client: httpx.Client, token: str | None, lat: float, lon: float) -> dict:
    unavailable = {"ndvi_value": None, "ndvi_scene_date": None, "ndvi_unavailable": True}
    if not token:
        return unavailable

    now = datetime.now(timezone.utc)
    time_range = {
        "from": (now - timedelta(days=NDVI_SEARCH_WINDOW_DAYS)).strftime("%Y-%m-%dT00:00:00Z"),
        "to": now.strftime("%Y-%m-%dT23:59:59Z"),
    }
    payload = {
        "input": {
            "bounds": {
                "bbox": _bbox_from_point(lat, lon, NDVI_BUFFER_RADIUS_M),
                "properties": {"crs": "http://www.opengis.net/def/crs/EPSG/0/4326"},
            },
            "data": [
                {
                    "type": "sentinel-2-l2a",
                    "dataFilter": {
                        "timeRange": time_range,
                        "maxCloudCoverage": NDVI_MAX_CLOUD_COVERAGE,
                    },
                }
            ],
        },
        "aggregation": {
            "timeRange": time_range,
            "aggregationInterval": {"of": "P1D"},
            "evalscript": NDVI_EVALSCRIPT,
            "resx": 10,
            "resy": 10,
        },
    }
    try:
        response = client.post(
            COPERNICUS_STATS_URL,
            headers={"Authorization": f"Bearer {token}"},
            json=payload,
        )
        response.raise_for_status()
        entries = response.json()["data"]
    except (httpx.HTTPError, KeyError) as exc:
        logger.warning("Copernicus NDVI lookup failed for (%s, %s): %s", lat, lon, exc)
        return unavailable

    for entry in reversed(entries):
        try:
            bands = entry["outputs"]["default"]["bands"]
            red_stats = bands["B0"]["stats"]
            nir_stats = bands["B1"]["stats"]
        except KeyError:
            continue
        if red_stats["sampleCount"] == 0 or red_stats["noDataCount"] > 0 or nir_stats["noDataCount"] > 0:
            continue
        red, nir = red_stats["mean"], nir_stats["mean"]
        if red + nir == 0:
            continue
        return {
            "ndvi_value": (nir - red) / (nir + red),
            "ndvi_scene_date": entry["interval"]["from"][:10],
            "ndvi_unavailable": False,
        }

    return unavailable
