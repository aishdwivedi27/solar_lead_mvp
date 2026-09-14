"""ETH Global Canopy Height tile lookups and shaded-hours estimation."""

import calendar
import math
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import rasterio
from pysolar.solar import get_altitude

from config import logger

# Tile access confirmed against the real ETH Global Canopy Height tile browser
# (langnico.github.io/globalcanopyheight): tiles are named by their SW corner,
# 3x3 degrees each, e.g. ETH_GlobalCanopyHeight_10m_2020_S39E144_Map.tif covers
# lat -39..-36, lon 144..147. Confirmed by reading a real tile's GeoTIFF header.
CANOPY_TILE_DOWNLOAD_URL = "https://libdrive.ethz.ch/index.php/s/cO8or7iOe5dT2Rt/download"
CANOPY_TILE_CACHE_DIR = Path(__file__).parent / "canopy_tile_cache"
CANOPY_NODATA_VALUE = 255

# Canopy height is sampled only at the record's own coordinate, with no known
# distance/direction to an actual tree, so it's treated as an obstruction a
# nominal 10m away -- the canopy dataset's own pixel resolution.
SHADOW_OBSTRUCTION_DISTANCE_M = 10
SHADED_HOURS_TIME_STEP_MINUTES = 30


def _canopy_tile_filename(lat: float, lon: float) -> str:
    south = math.floor(lat / 3) * 3
    west = math.floor(lon / 3) * 3
    lat_label = f"{'N' if south >= 0 else 'S'}{abs(south):02d}"
    lon_label = f"{'E' if west >= 0 else 'W'}{abs(west):03d}"
    return f"ETH_GlobalCanopyHeight_10m_2020_{lat_label}{lon_label}_Map.tif"


def get_canopy_height(client: httpx.Client, lat: float, lon: float) -> dict:
    unavailable = {"canopy_height_m": None, "canopy_height_unavailable": True}

    filename = _canopy_tile_filename(lat, lon)
    local_path = CANOPY_TILE_CACHE_DIR / filename

    if not local_path.exists():
        CANOPY_TILE_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        partial_path = local_path.with_suffix(".tif.part")
        try:
            with client.stream(
                "GET",
                CANOPY_TILE_DOWNLOAD_URL,
                params={"path": "/3deg_cogs", "files": filename},
                timeout=300.0,
            ) as response:
                response.raise_for_status()
                with open(partial_path, "wb") as f:
                    for chunk in response.iter_bytes():
                        f.write(chunk)
            os.replace(partial_path, local_path)
        except (httpx.HTTPError, OSError) as exc:
            logger.warning("Canopy height tile download failed for %r: %s", filename, exc)
            partial_path.unlink(missing_ok=True)
            return unavailable

    try:
        with rasterio.open(local_path) as dataset:
            value = next(dataset.sample([(lon, lat)]))[0]
    except (rasterio.errors.RasterioError, OSError) as exc:
        logger.warning("Canopy height read failed for (%s, %s): %s", lat, lon, exc)
        return unavailable

    if value == CANOPY_NODATA_VALUE:
        return unavailable
    return {"canopy_height_m": float(value), "canopy_height_unavailable": False}


def estimate_shaded_hours(lat: float, lon: float, canopy_height_m: float) -> float:
    if canopy_height_m <= 0:
        return 0.0

    year = datetime.now(timezone.utc).year
    total_shaded_hours = 0.0
    step = timedelta(minutes=SHADED_HOURS_TIME_STEP_MINUTES)

    for month in range(1, 13):
        days_in_month = calendar.monthrange(year, month)[1]
        t = datetime(year, month, 15, 0, 0, tzinfo=timezone.utc)
        end = t + timedelta(days=1)
        shaded_slots = 0
        while t < end:
            elevation = get_altitude(lat, lon, t)
            if elevation > 0:
                shadow_length = canopy_height_m / math.tan(math.radians(elevation))
                if shadow_length > SHADOW_OBSTRUCTION_DISTANCE_M:
                    shaded_slots += 1
            t += step
        shaded_hours_that_day = shaded_slots * SHADED_HOURS_TIME_STEP_MINUTES / 60
        total_shaded_hours += shaded_hours_that_day * days_in_month

    return total_shaded_hours
