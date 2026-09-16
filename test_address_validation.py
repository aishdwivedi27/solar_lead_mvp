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
    entry = {"street_address": "53 Kng William Road", "city": "Unly"}
    geocode_result = _geocode_result(
        {"house_number": "53", "road": "King William Rd", "locality": "Unley", "state": "", "postal_code": ""},
        "53 King William Rd, Unley, South Australia, Australia",
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


def test_all_caps_locality_is_shown_in_proper_case():
    entry = {"street_address": "279 Grote St", "city": "Adelaide"}
    geocode_result = _geocode_result(
        {"house_number": "279", "road": "Grote Street", "locality": "ADELAIDE", "state": "SOUTH AUSTRALIA", "postal_code": ""},
        "279 Grote Street, ADELAIDE, SOUTH AUSTRALIA, Australia",
    )

    result = compare_address(entry, geocode_result)

    assert result["needs_confirmation"] is False
    assert result["suggested"]["city"] == "Adelaide"
    assert result["suggested"]["state_region"] == "South Australia"
    assert result["resolved_display_name"] == "279 Grote Street, Adelaide, South Australia, Australia"


def test_state_abbreviation_kept_upper_while_street_type_still_title_cased():
    entry = {"street_address": "279 Grott St", "city": "Adelaide"}
    geocode_result = _geocode_result(
        {"house_number": "279", "road": "Grote Street", "locality": "Adelaide", "state": "", "postal_code": "5000"},
        "279 Grote ST, Adelaide SA 5000, Australia",
    )

    result = compare_address(entry, geocode_result)

    assert result["resolved_display_name"] == "279 Grote St, Adelaide SA 5000, Australia"


def test_street_typo_flagged_even_when_resolved_road_is_all_caps():
    entry = {"street_address": "279 Grott street", "city": "Adelaide"}
    geocode_result = _geocode_result(
        {"house_number": "279", "road": "GROTE STREET", "locality": "ADELAIDE", "state": "", "postal_code": ""},
        "279 GROTE STREET, ADELAIDE, South Australia, Australia",
    )

    result = compare_address(entry, geocode_result)

    assert result["needs_confirmation"] is True
    assert result["suggested"]["street_address"] == "279 Grote Street"
    assert result["suggested"]["city"] == "Adelaide"
