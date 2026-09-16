from address_validation import compare_address


def _geocode_result(
    resolved_components,
    resolved_display_name,
    low_confidence=False,
    latitude=1.0,
    longitude=2.0,
):
    return {
        "latitude": latitude,
        "longitude": longitude,
        "low_confidence_geocode": low_confidence,
        "resolved_display_name": resolved_display_name,
        "resolved_components": resolved_components,
    }


def test_exact_match_needs_no_confirmation():
    entry = {"street_address": "279 Grote St", "city": "Adelaide"}
    geocode_result = _geocode_result(
        {"house_number": "279", "road": "Grote Street", "locality": "Adelaide", "state": "", "postal_code": ""},
        "279 Grote Street, Adelaide, South Australia, Australia",
    )

    result = compare_address(entry, geocode_result)

    assert result["needs_confirmation"] is False
    assert result["suggested"]["street_address"] == "279 Grote Street"


def test_street_typo_flagged_with_suggestion():
    entry = {"street_address": "279 Grott street", "city": "Adelaide"}
    geocode_result = _geocode_result(
        {"house_number": "279", "road": "Grote Street", "locality": "Adelaide", "state": "", "postal_code": ""},
        "279 Grote Street, Adelaide, South Australia, Australia",
    )

    result = compare_address(entry, geocode_result)

    assert result["needs_confirmation"] is True
    assert result["suggested"]["street_address"] == "279 Grote Street"


def test_suburb_typo_flagged_with_suggestion():
    entry = {"street_address": "43 Tingara Avenue", "city": "Osuvillam beach"}
    geocode_result = _geocode_result(
        {
            "house_number": "43",
            "road": "Tingira Drive",
            "locality": "O'Sullivan Beach",
            "state": "South Australia",
            "postal_code": "5166",
        },
        "43 Tingira Drive, O'Sullivan Beach, South Australia, Australia",
    )

    result = compare_address(entry, geocode_result)

    assert result["needs_confirmation"] is True
    assert result["suggested"]["street_address"] == "43 Tingira Drive"
    assert result["suggested"]["city"] == "O'Sullivan Beach"
    assert result["suggested"]["postal_code"] == "5166"


def test_combined_street_and_suburb_typo_flagged():
    entry = {"street_address": "4 Berin Road", "city": "Morphet vale"}
    geocode_result = _geocode_result(
        {"house_number": "4", "road": "Berrin Rd", "locality": "Morphett Vale", "state": "", "postal_code": ""},
        "4 Berrin Rd, Morphett Vale, South Australia, Australia",
    )

    result = compare_address(entry, geocode_result)

    assert result["needs_confirmation"] is True


def test_no_geocode_match_needs_confirmation():
    entry = {"street_address": "Nonexistent Street", "city": "Nowhere"}
    geocode_result = {
        "latitude": None,
        "longitude": None,
        "low_confidence_geocode": True,
        "resolved_display_name": None,
        "resolved_components": {},
    }

    result = compare_address(entry, geocode_result)

    assert result["needs_confirmation"] is True
    assert result["suggested"]["street_address"] == "Nonexistent Street"


def test_low_confidence_geocode_needs_confirmation_even_if_text_matches():
    entry = {"street_address": "279 Grote Street", "city": "Adelaide"}
    geocode_result = _geocode_result(
        {"house_number": "", "road": "Grote Street", "locality": "Adelaide", "state": "", "postal_code": ""},
        "Grote Street, Adelaide, South Australia, Australia",
        low_confidence=True,
    )

    result = compare_address(entry, geocode_result)

    assert result["needs_confirmation"] is True
