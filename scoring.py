"""Composite scoring (stage 9-10). Deterministic and rule-based: gate on shading, then rank
by irradiance. Thresholds are first-pass placeholders, tunable once real outcomes validate them."""

from dataclasses import dataclass

HEAVY_SHADE_HOURS_THRESHOLD = 1000   # annual estimated_shaded_hours at/above this -> LOW regardless of irradiance
HIGH_IRRADIANCE_THRESHOLD = 4.5      # PVGIS H(i)_d, kWh/m2/day, optimally-angled
MEDIUM_IRRADIANCE_THRESHOLD = 3.8


@dataclass(frozen=True)
class ScoreResult:
    pipeline_path: str
    tier: str | None                      # HIGH/MEDIUM/LOW for EXISTING_ROOF, None for NEW_BUILD
    estimated_shaded_hours: float | None
    regional_irradiance: float | None
    optimal_tilt_degrees: float | None    # populated only for NEW_BUILD
    optimal_azimuth_degrees: float | None  # populated only for NEW_BUILD


def score_address(record: dict) -> ScoreResult:
    # Confirms ambiguous_existence / low_confidence_geocode (Prompts 2-3) are present before
    # trusting the rest of the record.
    if "ambiguous_existence" not in record or "low_confidence_geocode" not in record:
        raise ValueError(
            "record is missing ambiguous_existence and/or low_confidence_geocode -- "
            "these must be set by geocoding (Prompt 2) and the building-existence check "
            "(Prompt 3) before scoring."
        )

    if record["pipeline_path"] == "NEW_BUILD":
        return ScoreResult(
            pipeline_path="NEW_BUILD",
            tier=None,
            estimated_shaded_hours=None,
            regional_irradiance=record.get("regional_irradiance"),
            optimal_tilt_degrees=record.get("optimal_tilt_degrees"),
            optimal_azimuth_degrees=record.get("optimal_azimuth_degrees"),
        )

    shaded_hours = record.get("estimated_shaded_hours")
    irradiance = record.get("regional_irradiance")

    if shaded_hours is not None and shaded_hours >= HEAVY_SHADE_HOURS_THRESHOLD:
        tier = "LOW"
    elif irradiance is None:
        tier = "LOW"
    elif irradiance >= HIGH_IRRADIANCE_THRESHOLD:
        tier = "HIGH"
    elif irradiance >= MEDIUM_IRRADIANCE_THRESHOLD:
        tier = "MEDIUM"
    else:
        tier = "LOW"

    return ScoreResult(
        pipeline_path="EXISTING_ROOF",
        tier=tier,
        estimated_shaded_hours=shaded_hours,
        regional_irradiance=irradiance,
        optimal_tilt_degrees=None,
        optimal_azimuth_degrees=None,
    )
