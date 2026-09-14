from geocoding import geocode_address


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
