"""Address submission pipeline: geocode -> footprint/adjacency -> PVGIS/NDVI/canopy -> score -> narrate."""

import uuid

import httpx

from config import NOMINATIM_USER_AGENT
from geocoding import geocode_address, nominatim_rate_limit_pause
from llm import get_narrative_provider
from narrative import generate_narrative
from ndvi import get_copernicus_token, get_ndvi
from osm import ADJACENCY_DEFAULT_THRESHOLD_M, check_building_footprint, get_nearest_building_distance_m
from canopy import estimate_shaded_hours, get_canopy_height
from pvgis import get_pvgis_data
from scoring import score_address

ADDRESS_RECORDS: dict[str, dict] = {}


def _format_address(entry: dict) -> str:
    parts = [
        entry["street_address"],
        entry.get("city", ""),
        entry.get("state_region", ""),
        entry.get("postal_code", ""),
        entry.get("country", ""),
    ]
    return ", ".join(p for p in parts if p)


# Verification links (stage 11). Plain URL construction from lat/long using Google's documented
# Maps URL scheme (https://developers.google.com/maps/documentation/urls/get-started) -- no API
# key, no scraping. Just a deep link the user's own browser opens.
def generate_verification_links(lat: float, lon: float) -> dict:
    coords = f"{lat},{lon}"
    return {
        "google_maps_link": f"https://www.google.com/maps/search/?api=1&query={coords}",
        "street_view_link": f"https://www.google.com/maps/@?api=1&map_action=pano&viewpoint={coords}",
    }


def needs_verification(record: dict) -> bool:
    return bool(
        record.get("verify_adjacent_structure")
        or record.get("ambiguous_existence")
        or record.get("low_confidence_geocode")
    )


def submit_addresses(entries: list[dict]) -> list[dict]:
    cleaned = [
        {
            "street_address": e["street_address"].strip(),
            "city": e.get("city", "").strip(),
            "state_region": e.get("state_region", "").strip(),
            "postal_code": e.get("postal_code", "").strip(),
            "country": e.get("country", "").strip(),
            "planned_demolition_rebuild": bool(e.get("planned_demolition_rebuild", False)),
        }
        for e in entries
        if e.get("street_address") and e["street_address"].strip()
    ]

    records = []
    for entry in cleaned:
        record = {
            "id": str(uuid.uuid4()),
            "address": _format_address(entry),
            "confidence": "estimated",
            **entry,
        }
        ADDRESS_RECORDS[record["id"]] = record
        records.append(record)

    narrative_provider = get_narrative_provider()

    with httpx.Client(headers={"User-Agent": NOMINATIM_USER_AGENT}, timeout=25.0) as client:
        copernicus_token = get_copernicus_token(client)

        for i, record in enumerate(records):
            record.update(geocode_address(
                client,
                record["street_address"],
                record["city"],
                record["state_region"],
                record["postal_code"],
                record["country"],
            ))
            if i < len(records) - 1:
                nominatim_rate_limit_pause()

            if record["latitude"] is not None and record["longitude"] is not None:
                record.update(check_building_footprint(
                    client, record["latitude"], record["longitude"], record.get("geocode_type")
                ))
            else:
                record.update({
                    "has_building_footprint": None,
                    "building_footprint": None,
                    "building_osm_ref": None,
                    "ambiguous_existence": True,
                })

            if record["latitude"] is not None and record["longitude"] is not None:
                nearest_distance_m = get_nearest_building_distance_m(
                    client,
                    record["latitude"],
                    record["longitude"],
                    record["building_footprint"],
                    record["building_osm_ref"],
                )
            else:
                nearest_distance_m = None
            record["nearest_building_distance_m"] = nearest_distance_m
            record["verify_adjacent_structure"] = (
                nearest_distance_m is not None and nearest_distance_m < ADJACENCY_DEFAULT_THRESHOLD_M
            )

            if (
                record["latitude"] is not None
                and record["longitude"] is not None
                and needs_verification(record)
            ):
                record.update(generate_verification_links(record["latitude"], record["longitude"]))
            else:
                record["google_maps_link"] = None
                record["street_view_link"] = None

            no_footprint = not record["has_building_footprint"]
            if no_footprint or record["planned_demolition_rebuild"]:
                record["pipeline_path"] = "NEW_BUILD"
                if record["latitude"] is not None and record["longitude"] is not None:
                    record.update(get_pvgis_data(client, record["latitude"], record["longitude"]))
                else:
                    record["optimal_tilt_degrees"] = None
                    record["optimal_azimuth_degrees"] = None
                    record["regional_irradiance"] = None
                record["ndvi_value"] = None
                record["ndvi_scene_date"] = None
                record["ndvi_unavailable"] = None
                record["canopy_height_m"] = None
                record["canopy_height_unavailable"] = None
                record["estimated_shaded_hours"] = None
            else:
                record["pipeline_path"] = "EXISTING_ROOF"
                if record["latitude"] is not None and record["longitude"] is not None:
                    record.update(get_pvgis_data(client, record["latitude"], record["longitude"]))
                    record.update(get_ndvi(client, copernicus_token, record["latitude"], record["longitude"]))
                    record.update(get_canopy_height(client, record["latitude"], record["longitude"]))
                    if record["canopy_height_unavailable"]:
                        record["estimated_shaded_hours"] = None
                    else:
                        record["estimated_shaded_hours"] = estimate_shaded_hours(
                            record["latitude"], record["longitude"], record["canopy_height_m"]
                        )
                else:
                    record["regional_irradiance"] = None
                    record.update({"ndvi_value": None, "ndvi_scene_date": None, "ndvi_unavailable": True})
                    record.update({"canopy_height_m": None, "canopy_height_unavailable": True})
                    record["estimated_shaded_hours"] = None
                # The tilt/azimuth recommendation from get_pvgis_data is a
                # new-build design recommendation (stage 5), not meaningful
                # against an existing roof's own (unknown) geometry.
                record["optimal_tilt_degrees"] = None
                record["optimal_azimuth_degrees"] = None

            score_result = score_address(record)
            record["tier"] = score_result.tier
            record["narrative"], record["narrative_unavailable_reason"] = generate_narrative(
                narrative_provider, record, score_result
            )

    return records


# Manual override and recompute (stage 14). An assessor who has verified a
# flagged address on-site (or via the Google Maps/Street View links) corrects
# the specific input that was flagged, and this reruns only stages 10-13
# (scoring, verification links, narrative) against the corrected data --
# it never re-calls geocoding/Overpass/PVGIS/NDVI/canopy, since those already
# ran and the whole point is the assessor's on-site knowledge overriding them.
def recompute_record(record_id: str, corrections: dict) -> dict:
    record = ADDRESS_RECORDS[record_id]

    if corrections.get("confirmed_geocode_accurate"):
        record["low_confidence_geocode"] = False

    if corrections.get("confirmed_adjacent_structure") is not None:
        record["verify_adjacent_structure"] = bool(corrections["confirmed_adjacent_structure"])

    if corrections.get("confirmed_building_exists") is not None:
        record["has_building_footprint"] = bool(corrections["confirmed_building_exists"])
        record["ambiguous_existence"] = False

    if corrections.get("corrected_canopy_height_m") is not None:
        canopy_height_m = float(corrections["corrected_canopy_height_m"])
        record["canopy_height_m"] = canopy_height_m
        record["canopy_height_unavailable"] = False
        if record["latitude"] is not None and record["longitude"] is not None:
            record["estimated_shaded_hours"] = estimate_shaded_hours(
                record["latitude"], record["longitude"], canopy_height_m
            )

    no_footprint = not record["has_building_footprint"]
    new_path = "NEW_BUILD" if (no_footprint or record["planned_demolition_rebuild"]) else "EXISTING_ROOF"
    if new_path != record["pipeline_path"]:
        record["pipeline_path"] = new_path
        if new_path == "NEW_BUILD":
            if record["latitude"] is not None and record["longitude"] is not None:
                with httpx.Client(headers={"User-Agent": NOMINATIM_USER_AGENT}, timeout=25.0) as client:
                    record.update(get_pvgis_data(client, record["latitude"], record["longitude"]))
            record["estimated_shaded_hours"] = None
        else:
            record["optimal_tilt_degrees"] = None
            record["optimal_azimuth_degrees"] = None

    if record["latitude"] is not None and record["longitude"] is not None and needs_verification(record):
        record.update(generate_verification_links(record["latitude"], record["longitude"]))
    else:
        record["google_maps_link"] = None
        record["street_view_link"] = None

    score_result = score_address(record)
    record["tier"] = score_result.tier
    narrative_provider = get_narrative_provider()
    record["narrative"], record["narrative_unavailable_reason"] = generate_narrative(
        narrative_provider, record, score_result
    )
    record["confidence"] = "verified"

    return record
