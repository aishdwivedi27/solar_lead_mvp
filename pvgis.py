"""PVGIS PVcalc lookups: new-build tilt/azimuth recommendation and regional irradiance."""

import httpx

from config import logger


def get_pvgis_data(client: httpx.Client, lat: float, lon: float) -> dict:
    """One PVGIS PVcalc call (optimalangles=1) serves two stages: the new-build
    tilt/azimuth recommendation (stage 5), and H(i)_d -- average daily sum of
    global irradiation on the optimally-inclined plane, kWh/m2/day, numerically
    equivalent to average daily peak-sun-hours -- used as regional_irradiance on
    every record regardless of path (stage 7)."""
    try:
        response = client.get(
            "https://re.jrc.ec.europa.eu/api/v5_2/PVcalc",
            params={
                "lat": lat,
                "lon": lon,
                "peakpower": 1,
                "loss": 14,
                "optimalangles": 1,
                "outputformat": "json",
            },
        )
        response.raise_for_status()
        data = response.json()
        fixed_inputs = data["inputs"]["mounting_system"]["fixed"]
        fixed_outputs = data["outputs"]["totals"]["fixed"]
        return {
            "optimal_tilt_degrees": fixed_inputs["slope"]["value"],
            "optimal_azimuth_degrees": fixed_inputs["azimuth"]["value"],
            "regional_irradiance": fixed_outputs["H(i)_d"],
        }
    except (httpx.HTTPError, KeyError) as exc:
        logger.warning("PVGIS lookup failed for (%s, %s): %s", lat, lon, exc)
        return {
            "optimal_tilt_degrees": None,
            "optimal_azimuth_degrees": None,
            "regional_irradiance": None,
        }
