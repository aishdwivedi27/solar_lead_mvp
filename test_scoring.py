import pytest

from scoring import HEAVY_SHADE_HOURS_THRESHOLD, ScoreResult, score_address


def _existing_roof_record(**overrides) -> dict:
    record = {
        "pipeline_path": "EXISTING_ROOF",
        "ambiguous_existence": False,
        "low_confidence_geocode": False,
        "estimated_shaded_hours": 50.0,
        "regional_irradiance": 5.5,
    }
    record.update(overrides)
    return record


def _new_build_record(**overrides) -> dict:
    record = {
        "pipeline_path": "NEW_BUILD",
        "ambiguous_existence": True,
        "low_confidence_geocode": False,
        "regional_irradiance": 5.0,
        "optimal_tilt_degrees": 32.0,
        "optimal_azimuth_degrees": 0.0,
    }
    record.update(overrides)
    return record


def test_high_tier_for_low_shading_and_high_irradiance():
    result = score_address(_existing_roof_record())

    assert result.tier == "HIGH"
    assert result.pipeline_path == "EXISTING_ROOF"
    assert result.estimated_shaded_hours == 50.0
    assert result.regional_irradiance == 5.5


def test_low_tier_when_heavy_shading_overrides_high_irradiance():
    record = _existing_roof_record(
        estimated_shaded_hours=HEAVY_SHADE_HOURS_THRESHOLD + 500,
        regional_irradiance=5.5,  # would otherwise be a clear HIGH
    )

    result = score_address(record)

    assert result.tier == "LOW"


def test_new_build_returns_pvgis_recommendation_instead_of_tier():
    record = _new_build_record()

    result = score_address(record)

    assert result.pipeline_path == "NEW_BUILD"
    assert result.tier is None
    assert result.estimated_shaded_hours is None
    assert result.optimal_tilt_degrees == 32.0
    assert result.optimal_azimuth_degrees == 0.0


def test_missing_confidence_flags_raises():
    record = _existing_roof_record()
    del record["ambiguous_existence"]

    with pytest.raises(ValueError):
        score_address(record)
