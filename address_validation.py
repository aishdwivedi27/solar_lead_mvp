"""Compares a user-typed address against what the geocoder actually resolved,
so an address confirmation step can catch typos (e.g. "Osuvillam Beach" typed
for "O'Sullivan Beach", or "Morphet Vale" for "Morphett Vale") before the slow
pipeline (Overpass/PVGIS/NDVI/canopy) runs on a misspelled address. Pure
comparison logic -- the geocoding lookup itself already happened in
geocoding.py.

A fuzzy-similarity comparison (e.g. difflib ratio) turns out not to work
here: a single-letter typo inside a short proper noun ("Grote" vs "Grott",
"Berrin" vs "Berin") still scores as 80-90% similar, which is indistinguishable
from a harmless formatting difference. Instead, each field is normalized
(case/punctuation-insensitive) and street-type words are expanded to a
canonical form (so "St" == "Street", "Rd" == "Road") and then compared for
exact equality -- any real spelling difference in the proper-noun part fails
that comparison and is surfaced to the user, while an abbreviation the user
typed correctly is not.
"""

import re

# Canonical form for common street-type abbreviations, so "43 Tingira Dr" and
# "43 Tingira Drive" compare equal instead of falsely flagging every address
# where the user (or Nominatim) used the short form.
_STREET_TYPE_EXPANSIONS = {
    "st": "street", "rd": "road", "ave": "avenue", "av": "avenue", "dr": "drive",
    "ln": "lane", "ct": "court", "cres": "crescent", "cr": "crescent", "pl": "place",
    "tce": "terrace", "hwy": "highway", "pde": "parade", "blvd": "boulevard",
    "cl": "close", "grn": "green", "gr": "grove", "sq": "square", "cct": "circuit",
    "esp": "esplanade", "cir": "circle", "way": "way",
}

_PUNCTUATION_RE = re.compile(r"[^\w\s]")
_WHITESPACE_RE = re.compile(r"\s+")


def normalize_street_text(text: str) -> str:
    """Case/punctuation-insensitive form with street-type words expanded to a
    canonical spelling (so "St" == "Street", "Rd" == "Road"). Shared with
    street_names.py, which normalizes the same way before fuzzy-matching a
    typed street against real nearby OSM street names."""
    text = _PUNCTUATION_RE.sub(" ", text.strip().lower())
    words = [_STREET_TYPE_EXPANSIONS.get(word, word) for word in text.split()]
    return _WHITESPACE_RE.sub(" ", " ".join(words)).strip()


def _matches(entered: str, resolved: str) -> bool:
    entered, resolved = normalize_street_text(entered), normalize_street_text(resolved)
    if not entered or not resolved:
        return True  # nothing typed/resolved for this field -- not a conflict
    return entered == resolved


def _smart_title_case(text: str) -> str:
    """Fixes ALL-CAPS words from raw geocoder data (e.g. Australian OSM/G-NAF
    locality names, which are commonly stored upper-case) into proper title
    case, without touching text that's already mixed-case -- so correctly
    cased provider text, and names like "O'Sullivan" or "McLaren", pass
    through untouched."""

    def fix_word(word: str) -> str:
        letters = [c for c in word if c.isalpha()]
        if len(letters) < 2 or not all(c.isupper() for c in letters):
            return word
        chars = []
        capitalize_next = True
        for ch in word:
            if ch.isalpha():
                chars.append(ch.upper() if capitalize_next else ch.lower())
                capitalize_next = False
            else:
                chars.append(ch)
                capitalize_next = ch in ("'", "-")
        return "".join(chars)

    return " ".join(fix_word(word) for word in text.split(" "))


def compare_address(entry: dict, geocode_result: dict) -> dict:
    """Returns whether `entry` (as typed) needs the user's confirmation
    against `geocode_result` (from geocoding.geocode_address), plus a
    suggested corrected set of fields drawn from the resolved address."""
    components = geocode_result.get("resolved_components") or {}
    resolved_display_name = geocode_result.get("resolved_display_name")
    if resolved_display_name:
        resolved_display_name = _smart_title_case(resolved_display_name)
    low_confidence = bool(geocode_result.get("low_confidence_geocode"))

    resolved_street = " ".join(
        part for part in (components.get("house_number", ""), components.get("road", "")) if part
    )
    if resolved_street:
        resolved_street = _smart_title_case(resolved_street)
    resolved_locality = components.get("locality", "")
    if resolved_locality:
        resolved_locality = _smart_title_case(resolved_locality)
    resolved_postal_code = components.get("postal_code", "")
    resolved_state = components.get("state", "")
    if resolved_state:
        resolved_state = _smart_title_case(resolved_state)

    if geocode_result.get("latitude") is None or geocode_result.get("longitude") is None:
        needs_confirmation = True
    else:
        needs_confirmation = (
            low_confidence
            or not _matches(entry.get("street_address", ""), resolved_street)
            or not _matches(entry.get("city", ""), resolved_locality)
            or not _matches(entry.get("postal_code", ""), resolved_postal_code)
        )

    return {
        "needs_confirmation": needs_confirmation,
        "low_confidence_geocode": low_confidence,
        "resolved_display_name": resolved_display_name,
        "suggested": {
            "street_address": resolved_street or entry.get("street_address", ""),
            "city": resolved_locality or entry.get("city", ""),
            "state_region": resolved_state or entry.get("state_region", ""),
            "postal_code": resolved_postal_code or entry.get("postal_code", ""),
        },
    }
