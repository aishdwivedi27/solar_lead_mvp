import pytest

import geocoding
from geocoding import geocode_address


@pytest.fixture(autouse=True)
def _disable_opencage_fallback_by_default(monkeypatch):
    """Tests must not depend on whether the developer's local .env has a real OPENCAGE_API_KEY.

    Tests that want to exercise the fallback opt back in via _configure_opencage.
    """
    monkeypatch.setattr(geocoding, "OPENCAGE_API_KEY", "")


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


class _FakeClient:
    """Stands in for httpx.Client: returns queued responses in order, one per .get() call."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def get(self, url, params=None):
        self.calls.append(params)
        return _FakeResponse(self._responses.pop(0))


def _house_result(lat="1.0", lon="2.0"):
    return {"lat": lat, "lon": lon, "addresstype": "house", "importance": 0.9}


def _road_result(lat="1.0", lon="2.0"):
    return {"lat": lat, "lon": lon, "addresstype": "road", "type": "residential", "importance": 0.5}


def test_rooftop_result_used_as_is_no_retry():
    client = _FakeClient([[_house_result()]])

    result = geocode_address(client, "4 Berrin Road", postal_code="5162")

    assert result == {
        "latitude": 1.0,
        "longitude": 2.0,
        "geocode_type": "house",
        "geocode_importance": 0.9,
        "low_confidence_geocode": False,
    }
    assert len(client.calls) == 1


def test_rooftop_match_preferred_over_higher_ranked_road_result_no_retry():
    client = _FakeClient([[_road_result(), _house_result(lat="3.0", lon="4.0")]])

    result = geocode_address(client, "4 Berrin Road", postal_code="5162")

    assert result["geocode_type"] == "house"
    assert result["latitude"] == 3.0
    assert result["low_confidence_geocode"] is False
    assert len(client.calls) == 1


def test_retries_without_postalcode_and_uses_rooftop_result():
    client = _FakeClient([
        [_road_result()],
        [_house_result(lat="5.0", lon="6.0")],
    ])

    result = geocode_address(client, "4 Berrin Road", postal_code="5162")

    assert result["geocode_type"] == "house"
    assert result["latitude"] == 5.0
    assert result["low_confidence_geocode"] is False
    assert len(client.calls) == 2
    assert "postalcode" not in client.calls[1]


def test_falls_back_to_road_result_when_retry_also_non_rooftop():
    client = _FakeClient([
        [_road_result()],
        [_road_result()],
    ])

    result = geocode_address(client, "4 Berrin Road", postal_code="5162")

    assert result["geocode_type"] == "road"
    assert result["low_confidence_geocode"] is True
    assert len(client.calls) == 2


def test_no_results_returns_none_coordinates():
    client = _FakeClient([[], []])

    result = geocode_address(client, "Nonexistent Street", postal_code="0000")

    assert result == {
        "latitude": None,
        "longitude": None,
        "geocode_type": None,
        "geocode_importance": None,
        "low_confidence_geocode": True,
    }


def test_no_retry_when_no_postal_code_supplied():
    client = _FakeClient([[_road_result()]])

    result = geocode_address(client, "Berrin Road")

    assert result["geocode_type"] == "road"
    assert len(client.calls) == 1


def _opencage_building_response(lat=7.0, lon=8.0):
    return {"results": [{"components": {"_type": "building"}, "geometry": {"lat": lat, "lng": lon}, "confidence": 9}]}


def _configure_opencage(monkeypatch, tmp_path, daily_limit=10):
    monkeypatch.setattr(geocoding, "OPENCAGE_API_KEY", "test-key")
    monkeypatch.setattr(geocoding, "OPENCAGE_CACHE_PATH", tmp_path / "cache.json")
    monkeypatch.setattr(geocoding, "OPENCAGE_USAGE_PATH", tmp_path / "usage.json")
    monkeypatch.setattr(geocoding, "OPENCAGE_DAILY_REQUEST_LIMIT", daily_limit)
    monkeypatch.setattr(geocoding, "OPENCAGE_MIN_DELAY_SECONDS", 0)  # don't slow tests down


def test_opencage_fallback_used_when_nominatim_only_finds_road(monkeypatch, tmp_path):
    _configure_opencage(monkeypatch, tmp_path)
    client = _FakeClient([[_road_result()], [_road_result()], _opencage_building_response()])

    result = geocode_address(client, "4 Berrin Road", postal_code="5162")

    assert result["geocode_type"] == "opencage:building"
    assert result["latitude"] == 7.0
    assert result["low_confidence_geocode"] is False
    assert len(client.calls) == 3


def test_opencage_result_is_cached_and_not_requested_twice(monkeypatch, tmp_path):
    _configure_opencage(monkeypatch, tmp_path)
    first_client = _FakeClient([[_road_result()], [_road_result()], _opencage_building_response()])
    geocode_address(first_client, "4 Berrin Road", postal_code="5162")

    second_client = _FakeClient([[_road_result()], [_road_result()]])
    result = geocode_address(second_client, "4 Berrin Road", postal_code="5162")

    assert result["geocode_type"] == "opencage:building"
    assert len(second_client.calls) == 2  # served from cache -- no OpenCage request made


def test_opencage_fallback_skipped_once_daily_limit_reached(monkeypatch, tmp_path):
    _configure_opencage(monkeypatch, tmp_path, daily_limit=0)
    client = _FakeClient([[_road_result()], [_road_result()]])

    result = geocode_address(client, "4 Berrin Road", postal_code="5162")

    assert result["geocode_type"] == "road"
    assert result["low_confidence_geocode"] is True
    assert len(client.calls) == 2  # no OpenCage request -- daily cap already spent


def test_no_opencage_fallback_when_api_key_unset(monkeypatch, tmp_path):
    monkeypatch.setattr(geocoding, "OPENCAGE_API_KEY", "")
    monkeypatch.setattr(geocoding, "OPENCAGE_CACHE_PATH", tmp_path / "cache.json")
    monkeypatch.setattr(geocoding, "OPENCAGE_USAGE_PATH", tmp_path / "usage.json")
    client = _FakeClient([[_road_result()], [_road_result()]])

    result = geocode_address(client, "4 Berrin Road", postal_code="5162")

    assert result["geocode_type"] == "road"
    assert len(client.calls) == 2
