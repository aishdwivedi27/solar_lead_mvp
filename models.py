"""Pydantic request models for the JSON API."""

from pydantic import BaseModel, Field

from config import MAX_FORM_ROWS


class AddressEntry(BaseModel):
    street_address: str = Field(min_length=1, max_length=200)
    city: str = Field(default="", max_length=100)
    state_region: str = Field(default="", max_length=100)
    postal_code: str = Field(default="", max_length=20)
    country: str = Field(min_length=1, max_length=100)
    planned_demolition_rebuild: bool = False


class AddressesIn(BaseModel):
    addresses: list[AddressEntry] = Field(min_length=1, max_length=MAX_FORM_ROWS)


class RecordCorrection(BaseModel):
    """Assessor-supplied corrections for one flagged record (stage 14). Every
    field is optional and left-untouched fields keep whatever the automated
    pipeline originally found."""

    confirmed_building_exists: bool | None = None
    confirmed_adjacent_structure: bool | None = None
    confirmed_geocode_accurate: bool | None = None
    corrected_canopy_height_m: float | None = Field(default=None, ge=0)
