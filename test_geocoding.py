import json

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
    """Stands in for httpx.Client: returns queued responses in order, one per
    .get()/.post() call (Nominatim and OpenCage use .get(), the Overpass
    street-name lookup uses .post(), but both draw from the same queue since
    tests care about call order, not which method made each call)."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def get(self, url, params=None):
        self.calls.append(params)
        return _FakeResponse(self._responses.pop(0))

    def post(self, url, data=None):
        self.calls.append(data)
        return _FakeResponse(self._responses.pop(0))


def _house_result(lat="1.0", lon="2.0"):
    return {
        "lat": lat,
        "lon": lon,
        "addresstype": "house",
        "importance": 0.9,
        "display_name": "53 King William Road, Unley, South Australia, Australia",
        "address": {"house_number": "53", "road": "King William Road", "suburb": "Unley"},
    }


def _road_result(lat="1.0", lon="2.0"):
    return {
        "lat": lat,
        "lon": lon,
        "addresstype": "road",
        "type": "residential",
        "importance": 0.5,
        "display_name": "King William Road, Unley, South Australia, Australia",
        "address": {"road": "King William Road", "suburb": "Unley"},
    }


def test_rooftop_result_used_as_is_no_retry():
    client = _FakeClient([[_house_result()]])

    result = geocode_address(client, "53 King William Road", postal_code="5061")

    assert result == {
        "latitude": 1.0,
        "longitude": 2.0,
        "geocode_type": "house",
        "geocode_importance": 0.9,
        "low_confidence_geocode": False,
        "resolved_display_name": "53 King William Road, Unley, South Australia, Australia",
        "resolved_components": {
            "house_number": "53",
            "road": "King William Road",
            "locality": "Unley",
            "state": "",
            "postal_code": "",
        },
    }
    assert len(client.calls) == 1


def test_rooftop_match_preferred_over_higher_ranked_road_result_no_retry():
    client = _FakeClient([[_road_result(), _house_result(lat="3.0", lon="4.0")]])

    result = geocode_address(client, "53 King William Road", postal_code="5061")

    assert result["geocode_type"] == "house"
    assert result["latitude"] == 3.0
    assert result["low_confidence_geocode"] is False
    assert len(client.calls) == 1


def test_retries_without_postalcode_and_uses_rooftop_result():
    client = _FakeClient([
        [_road_result()],
        [_house_result(lat="5.0", lon="6.0")],
    ])

    result = geocode_address(client, "53 King William Road", postal_code="5061")

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

    result = geocode_address(client, "53 King William Road", postal_code="5061")

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
        "resolved_display_name": None,
        "resolved_components": {},
    }


def test_no_retry_when_no_postal_code_supplied():
    client = _FakeClient([[_road_result()]])

    result = geocode_address(client, "King William Road")

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

    result = geocode_address(client, "53 King William Road", postal_code="5061")

    assert result["geocode_type"] == "opencage:building"
    assert result["latitude"] == 7.0
    assert result["low_confidence_geocode"] is False
    assert len(client.calls) == 3


def test_opencage_result_is_cached_and_not_requested_twice(monkeypatch, tmp_path):
    _configure_opencage(monkeypatch, tmp_path)
    first_client = _FakeClient([[_road_result()], [_road_result()], _opencage_building_response()])
    geocode_address(first_client, "53 King William Road", postal_code="5061")

    second_client = _FakeClient([[_road_result()], [_road_result()]])
    result = geocode_address(second_client, "53 King William Road", postal_code="5061")

    assert result["geocode_type"] == "opencage:building"
    assert len(second_client.calls) == 2  # served from cache -- no OpenCage request made


def test_opencage_fallback_skipped_once_daily_limit_reached(monkeypatch, tmp_path):
    _configure_opencage(monkeypatch, tmp_path, daily_limit=0)
    client = _FakeClient([[_road_result()], [_road_result()]])

    result = geocode_address(client, "53 King William Road", postal_code="5061")

    assert result["geocode_type"] == "road"
    assert result["low_confidence_geocode"] is True
    assert len(client.calls) == 2  # no OpenCage request -- daily cap already spent


def _opencage_road_response(lat=7.0, lon=8.0):
    return {"results": [{"components": {"_type": "road"}, "geometry": {"lat": lat, "lng": lon}, "confidence": 5}]}


def _overpass_streets_response(names):
    return {"elements": [{"tags": {"name": name}} for name in names]}


def test_opencage_low_confidence_guess_used_when_nominatim_finds_nothing(monkeypatch, tmp_path):
    """Even a non-rooftop OpenCage guess beats surfacing a bare "couldn't
    confirm" with no suggestion at all, since it still gives the caller
    something to offer the user as a "did you mean" address."""
    _configure_opencage(monkeypatch, tmp_path)
    client = _FakeClient([
        [], [], _opencage_road_response(),
        _overpass_streets_response([]),  # street-name fallback finds no real street to suggest
    ])

    result = geocode_address(client, "Nonexistent Street", postal_code="0000")

    assert result["geocode_type"] == "opencage:road"
    assert result["latitude"] == 7.0
    assert result["low_confidence_geocode"] is True


def _city_result(lat="1.0", lon="2.0"):
    """A Nominatim match that found *something* (a city-level pin with
    coordinates) but couldn't resolve the street itself -- e.g. because the
    street was typo'd and didn't match the OSM road-name index."""
    return {
        "lat": lat,
        "lon": lon,
        "addresstype": "city",
        "importance": 0.5,
        "display_name": "Adelaide, South Australia, Australia",
        "address": {"suburb": "Adelaide"},
    }


def _opencage_road_match_response(lat=7.0, lon=8.0, road="Grote Street"):
    return {
        "results": [
            {
                "components": {"_type": "road", "road": road, "city": "Adelaide"},
                "geometry": {"lat": lat, "lng": lon},
                "confidence": 5,
            }
        ]
    }


def test_opencage_road_match_preferred_over_nominatim_city_level_pin(monkeypatch, tmp_path):
    """Nominatim found a city-level pin (has coordinates) but no street match;
    OpenCage's second-opinion lookup did resolve a street. OpenCage's result
    should win even though it's still "low confidence" by the rooftop-only
    definition, since a resolved street beats a bare city pin."""
    _configure_opencage(monkeypatch, tmp_path)
    client = _FakeClient([[_city_result()], _opencage_road_match_response()])

    result = geocode_address(client, "279 Grott Street", city="Adelaide")

    assert result["geocode_type"] == "opencage:road"
    assert result["resolved_components"]["road"] == "Grote Street"
    assert result["low_confidence_geocode"] is True


def test_opencage_ignored_when_neither_result_has_a_road_match(monkeypatch, tmp_path):
    """Both results are low-confidence and neither resolved a street --
    Nominatim's result is kept rather than switching to OpenCage for no
    actual gain."""
    _configure_opencage(monkeypatch, tmp_path)
    client = _FakeClient([
        [_city_result()], _opencage_road_response(),
        _overpass_streets_response([]),  # street-name fallback finds no real street to suggest
    ])

    result = geocode_address(client, "279 Grott Street", city="Adelaide")

    assert result["geocode_type"] == "city"


def test_street_typo_corrected_via_overpass_when_neither_geocoder_resolves_it(monkeypatch, tmp_path):
    """Neither Nominatim nor OpenCage can fuzzy-correct "Grott" -> "Grote" on
    their own -- both only resolve a city-level pin. The Overpass-based
    fallback looks up the real street names OSM has near that pin, finds
    "Grote Street" is a close match for the typed "Grott Street", and a
    retried geocode with the corrected name resolves a rooftop match."""
    _configure_opencage(monkeypatch, tmp_path)
    client = _FakeClient([
        [_city_result()],                                       # nominatim: city-level pin only
        _opencage_road_response(),                               # opencage: also no road match
        _overpass_streets_response(["Grote Street", "Sturt Street"]),  # real streets near that pin
        [_house_result(lat="9.0", lon="10.0")],                  # retried nominatim w/ corrected street
        _opencage_road_response(),                                # retried opencage (unused -- nominatim wins)
    ])

    result = geocode_address(client, "279 Grott Street", city="Adelaide")

    assert result["geocode_type"] == "house"
    assert result["latitude"] == 9.0
    assert result["low_confidence_geocode"] is False


def test_opencage_stale_cache_entry_missing_newer_fields_is_refetched(monkeypatch, tmp_path):
    """A cache entry written by an older version of this code (before
    resolved_display_name/resolved_components existed) must not be trusted
    forever just because its key matches -- it's refetched and the full,
    current-shape result is what callers see."""
    _configure_opencage(monkeypatch, tmp_path)
    cache_key = geocoding._opencage_cache_key("53 King William Road", "", "", "5061", "")
    (tmp_path / "cache.json").write_text(json.dumps({
        cache_key: {
            "latitude": 7.0,
            "longitude": 8.0,
            "geocode_type": "opencage:building",
            "geocode_importance": 9,
            "low_confidence_geocode": False,
            # resolved_display_name / resolved_components missing -- stale schema
        }
    }))
    fresh_response = {
        "results": [{
            "components": {"_type": "building", "house_number": "53", "road": "King William Road"},
            "geometry": {"lat": 7.0, "lng": 8.0},
            "confidence": 9,
            "formatted": "53 King William Road, Unley, South Australia, Australia",
        }]
    }
    client = _FakeClient([[_road_result()], [_road_result()], fresh_response])

    result = geocode_address(client, "53 King William Road", postal_code="5061")

    assert result["geocode_type"] == "opencage:building"
    assert result["resolved_display_name"] == "53 King William Road, Unley, South Australia, Australia"
    assert len(client.calls) == 3  # refetched rather than trusting the incomplete cached entry


def test_no_opencage_fallback_when_api_key_unset(monkeypatch, tmp_path):
    monkeypatch.setattr(geocoding, "OPENCAGE_API_KEY", "")
    monkeypatch.setattr(geocoding, "OPENCAGE_CACHE_PATH", tmp_path / "cache.json")
    monkeypatch.setattr(geocoding, "OPENCAGE_USAGE_PATH", tmp_path / "usage.json")
    client = _FakeClient([[_road_result()], [_road_result()]])

    result = geocode_address(client, "53 King William Road", postal_code="5061")

    assert result["geocode_type"] == "road"
    assert len(client.calls) == 2
