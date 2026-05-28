# Copyright 2026 unpatterned.org
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""African phone number parsing, detection, and E.164 normalisation.

Covers 30+ African countries with real mobile prefixes, local digit lengths,
and common writing styles encountered in African data (spaces, hyphens,
dots, parenthesised area codes, etc.).

Key capabilities:
- Detect phone numbers in free text with country attribution
- Normalise to E.164 international format (``+234XXXXXXXXXX``)
- Handle "0-prefix" local dialling conventions
- Recognise common African formatting: ``0803 555 7890``, ``080-3555-7890``,
  ``+234 803 555 7890``, ``234-803-555-7890``
"""

from __future__ import annotations

import re
from typing import Any

# ---------------------------------------------------------------------------
# Country phone specs
# ---------------------------------------------------------------------------
# Each entry describes one country's mobile numbering plan.
#
# Fields:
#   country_code  — ITU dialling code (without +)
#   country       — ISO 3166-1 alpha-2
#   country_name  — human-readable
#   local_length  — total digits in local number including leading 0 (where applicable)
#   intl_length   — total digits AFTER the country code
#   mobile_prefixes — list of prefix strings in *local* format (with leading 0)
#                     OR in subscriber format (without leading 0)
#   prefix_style  — "local" (prefixes include leading 0) or "subscriber"

PHONE_PATTERNS: dict[str, dict] = {
    "NG": {
        "country_code": "234",
        "country": "NG",
        "country_name": "Nigeria",
        "local_length": 11,
        "intl_length": 10,
        "mobile_prefixes": [
            "0703", "0704", "0705", "0706", "0707", "0708",
            "0802", "0803", "0804", "0805", "0806", "0807", "0808", "0809",
            "0810", "0811", "0812", "0813", "0814", "0815", "0816", "0817",
            "0818", "0819",
            "0901", "0902", "0903", "0904", "0905", "0906", "0907", "0908",
            "0909",
            "0912", "0913", "0915", "0916",
        ],
        "prefix_style": "local",
    },
    "KE": {
        "country_code": "254",
        "country": "KE",
        "country_name": "Kenya",
        "local_length": 10,
        "intl_length": 9,
        "mobile_prefixes": [
            "070", "071", "072", "074", "075", "076", "077", "078", "079",
            "010", "011",
        ],
        "prefix_style": "local",
    },
    "ZA": {
        "country_code": "27",
        "country": "ZA",
        "country_name": "South Africa",
        "local_length": 10,
        "intl_length": 9,
        "mobile_prefixes": [
            "060", "061", "062", "063", "064", "065", "066",
            "067", "068", "069",
            "071", "072", "073", "074", "076", "078", "079",
            "081", "082", "083", "084",
        ],
        "prefix_style": "local",
    },
    "GH": {
        "country_code": "233",
        "country": "GH",
        "country_name": "Ghana",
        "local_length": 10,
        "intl_length": 9,
        "mobile_prefixes": [
            "020", "023", "024", "025", "026", "027", "028",
            "050", "054", "055", "059",
        ],
        "prefix_style": "local",
    },
    "TZ": {
        "country_code": "255",
        "country": "TZ",
        "country_name": "Tanzania",
        "local_length": 10,
        "intl_length": 9,
        "mobile_prefixes": [
            "061", "062", "065", "067", "068", "069",
            "071", "074", "075", "076", "077", "078",
        ],
        "prefix_style": "local",
    },
    "UG": {
        "country_code": "256",
        "country": "UG",
        "country_name": "Uganda",
        "local_length": 10,
        "intl_length": 9,
        "mobile_prefixes": [
            "070", "071", "074", "075", "077", "078",
        ],
        "prefix_style": "local",
    },
    "RW": {
        "country_code": "250",
        "country": "RW",
        "country_name": "Rwanda",
        "local_length": 10,
        "intl_length": 9,
        "mobile_prefixes": [
            "072", "073", "078",
        ],
        "prefix_style": "local",
    },
    "ET": {
        "country_code": "251",
        "country": "ET",
        "country_name": "Ethiopia",
        "local_length": 10,
        "intl_length": 9,
        "mobile_prefixes": [
            "091", "092", "093", "094", "095", "096", "097",
            "070", "071",
        ],
        "prefix_style": "local",
    },
    "CI": {
        "country_code": "225",
        "country": "CI",
        "country_name": "Cote d'Ivoire",
        "local_length": 10,
        "intl_length": 10,
        "mobile_prefixes": [
            "01", "05", "07",
        ],
        "prefix_style": "subscriber",
    },
    "SN": {
        "country_code": "221",
        "country": "SN",
        "country_name": "Senegal",
        "local_length": 9,
        "intl_length": 9,
        "mobile_prefixes": [
            "70", "76", "77", "78",
        ],
        "prefix_style": "subscriber",
    },
    "EG": {
        "country_code": "20",
        "country": "EG",
        "country_name": "Egypt",
        "local_length": 11,
        "intl_length": 10,
        "mobile_prefixes": [
            "010", "011", "012", "015",
        ],
        "prefix_style": "local",
    },
    "MA": {
        "country_code": "212",
        "country": "MA",
        "country_name": "Morocco",
        "local_length": 10,
        "intl_length": 9,
        "mobile_prefixes": [
            "06", "07",
        ],
        "prefix_style": "local",
    },
    "CM": {
        "country_code": "237",
        "country": "CM",
        "country_name": "Cameroon",
        "local_length": 9,
        "intl_length": 9,
        "mobile_prefixes": [
            "6",
        ],
        "prefix_style": "subscriber",
    },
    "CD": {
        "country_code": "243",
        "country": "CD",
        "country_name": "DR Congo",
        "local_length": 10,
        "intl_length": 9,
        "mobile_prefixes": [
            "081", "082", "083", "084", "085", "089",
            "097", "099",
        ],
        "prefix_style": "local",
    },
    "AO": {
        "country_code": "244",
        "country": "AO",
        "country_name": "Angola",
        "local_length": 9,
        "intl_length": 9,
        "mobile_prefixes": [
            "91", "92", "93", "94", "95", "96", "99",
        ],
        "prefix_style": "subscriber",
    },
    "MZ": {
        "country_code": "258",
        "country": "MZ",
        "country_name": "Mozambique",
        "local_length": 9,
        "intl_length": 9,
        "mobile_prefixes": [
            "82", "83", "84", "85", "86", "87",
        ],
        "prefix_style": "subscriber",
    },
    "ZW": {
        "country_code": "263",
        "country": "ZW",
        "country_name": "Zimbabwe",
        "local_length": 10,
        "intl_length": 9,
        "mobile_prefixes": [
            "071", "073", "077", "078",
        ],
        "prefix_style": "local",
    },
    "ZM": {
        "country_code": "260",
        "country": "ZM",
        "country_name": "Zambia",
        "local_length": 10,
        "intl_length": 9,
        "mobile_prefixes": [
            "095", "096", "097",
        ],
        "prefix_style": "local",
    },
    "BW": {
        "country_code": "267",
        "country": "BW",
        "country_name": "Botswana",
        "local_length": 8,
        "intl_length": 8,
        "mobile_prefixes": [
            "71", "72", "73", "74", "75", "76", "77",
        ],
        "prefix_style": "subscriber",
    },
    "NA": {
        "country_code": "264",
        "country": "NA",
        "country_name": "Namibia",
        "local_length": 10,
        "intl_length": 9,
        "mobile_prefixes": [
            "081", "085",
        ],
        "prefix_style": "local",
    },
    "SD": {
        "country_code": "249",
        "country": "SD",
        "country_name": "Sudan",
        "local_length": 10,
        "intl_length": 9,
        "mobile_prefixes": [
            "091", "092", "096", "099",
        ],
        "prefix_style": "local",
    },
    "ML": {
        "country_code": "223",
        "country": "ML",
        "country_name": "Mali",
        "local_length": 8,
        "intl_length": 8,
        "mobile_prefixes": [
            "6", "7",
        ],
        "prefix_style": "subscriber",
    },
    "BF": {
        "country_code": "226",
        "country": "BF",
        "country_name": "Burkina Faso",
        "local_length": 8,
        "intl_length": 8,
        "mobile_prefixes": [
            "5", "6", "7",
        ],
        "prefix_style": "subscriber",
    },
    "NE": {
        "country_code": "227",
        "country": "NE",
        "country_name": "Niger",
        "local_length": 8,
        "intl_length": 8,
        "mobile_prefixes": [
            "8", "9",
        ],
        "prefix_style": "subscriber",
    },
    "GN": {
        "country_code": "224",
        "country": "GN",
        "country_name": "Guinea",
        "local_length": 9,
        "intl_length": 9,
        "mobile_prefixes": [
            "62", "63", "64", "65", "66", "67", "68", "69",
        ],
        "prefix_style": "subscriber",
    },
    "BJ": {
        "country_code": "229",
        "country": "BJ",
        "country_name": "Benin",
        "local_length": 8,
        "intl_length": 8,
        "mobile_prefixes": [
            "40", "41", "42", "43", "44", "46",
            "51", "52", "53", "54", "55", "56",
            "61", "62", "63", "64", "65", "66", "67", "68", "69",
            "90", "91", "94", "95", "96", "97",
        ],
        "prefix_style": "subscriber",
    },
    "TG": {
        "country_code": "228",
        "country": "TG",
        "country_name": "Togo",
        "local_length": 8,
        "intl_length": 8,
        "mobile_prefixes": [
            "90", "91", "92", "93", "96", "97", "98", "99",
            "70", "71", "79",
        ],
        "prefix_style": "subscriber",
    },
    "SL": {
        "country_code": "232",
        "country": "SL",
        "country_name": "Sierra Leone",
        "local_length": 8,
        "intl_length": 8,
        "mobile_prefixes": [
            "25", "30", "33", "34", "40", "44", "50", "55",
            "76", "77", "78", "79", "88",
        ],
        "prefix_style": "subscriber",
    },
    "LR": {
        "country_code": "231",
        "country": "LR",
        "country_name": "Liberia",
        "local_length": 8,
        "intl_length": 7,
        "mobile_prefixes": [
            "55", "77", "88",
        ],
        "prefix_style": "subscriber",
    },
    "MG": {
        "country_code": "261",
        "country": "MG",
        "country_name": "Madagascar",
        "local_length": 10,
        "intl_length": 9,
        "mobile_prefixes": [
            "032", "033", "034", "038",
        ],
        "prefix_style": "local",
    },
    "SO": {
        "country_code": "252",
        "country": "SO",
        "country_name": "Somalia",
        "local_length": 8,
        "intl_length": 8,
        "mobile_prefixes": [
            "61", "62", "63", "65", "66", "68", "69",
            "90",
        ],
        "prefix_style": "subscriber",
    },
}


# Build a lookup from country code digits → list of country keys
_CODE_TO_COUNTRIES: dict[str, list[str]] = {}
for _iso, _spec in PHONE_PATTERNS.items():
    _CODE_TO_COUNTRIES.setdefault(_spec["country_code"], []).append(_iso)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

# Regex to find phone-like sequences in text.
# Matches: optional +, digits with optional separators (space, -, ., (, ))
_PHONE_RE = re.compile(
    r"(?<![0-9A-Za-z])"
    r"(\+?\d[\d\s\-\.\(\)]{5,18}\d)"
    r"(?![0-9A-Za-z])"
)


def _strip_to_digits(text: str) -> str:
    """Remove all non-digit characters except a leading +."""
    if text.startswith("+"):
        return "+" + re.sub(r"\D", "", text[1:])
    return re.sub(r"\D", "", text)


def _try_match_international(digits: str) -> dict | None:
    """Try to match a digit string in international format (+CC or CC prefix)."""
    pure = digits.lstrip("+")

    # Try country codes of length 1, 2, 3
    for cc_len in (1, 2, 3):
        cc = pure[:cc_len]
        if cc not in _CODE_TO_COUNTRIES:
            continue
        subscriber = pure[cc_len:]
        for iso in _CODE_TO_COUNTRIES[cc]:
            spec = PHONE_PATTERNS[iso]
            if len(subscriber) != spec["intl_length"]:
                continue
            if _matches_prefix(subscriber, spec):
                return {
                    "country": spec["country"],
                    "country_code": spec["country_code"],
                    "country_name": spec["country_name"],
                    "subscriber": subscriber,
                    "international": f"+{cc}{subscriber}",
                    "local": _to_local(subscriber, spec),
                }
    return None


def _matches_prefix(subscriber: str, spec: dict) -> bool:
    """Check if subscriber digits match any known mobile prefix for this country."""
    prefixes = spec["mobile_prefixes"]
    style = spec["prefix_style"]

    if style == "local":
        # Prefixes include leading 0; subscriber does NOT have leading 0.
        # Strip the 0 from each prefix before comparing.
        for p in prefixes:
            stripped = p.lstrip("0")
            if subscriber.startswith(stripped):
                return True
    else:
        # Subscriber-style prefixes — compare directly.
        for p in prefixes:
            if subscriber.startswith(p):
                return True
    return False


def _to_local(subscriber: str, spec: dict) -> str:
    """Convert subscriber digits to local dialling format."""
    style = spec["prefix_style"]
    if style == "local":
        return "0" + subscriber
    # Countries without a trunk prefix dial subscriber directly
    return subscriber


def _try_match_local(digits: str, default_country: str) -> dict | None:
    """Try to match a digit string as a local number in the default country."""
    if default_country not in PHONE_PATTERNS:
        return None
    spec = PHONE_PATTERNS[default_country]

    if len(digits) != spec["local_length"]:
        return None

    # Check if starts with known prefix
    for p in spec["mobile_prefixes"]:
        if spec["prefix_style"] == "local":
            if digits.startswith(p):
                subscriber = digits[1:]  # strip the leading 0
                return {
                    "country": spec["country"],
                    "country_code": spec["country_code"],
                    "country_name": spec["country_name"],
                    "subscriber": subscriber,
                    "international": f"+{spec['country_code']}{subscriber}",
                    "local": digits,
                }
        else:
            if digits.startswith(p):
                subscriber = digits
                return {
                    "country": spec["country"],
                    "country_code": spec["country_code"],
                    "country_name": spec["country_name"],
                    "subscriber": subscriber,
                    "international": f"+{spec['country_code']}{subscriber}",
                    "local": digits,
                }
    return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def parse_african_phone(
    text: str,
    *,
    default_country: str = "NG",
) -> list[dict]:
    """Find and parse phone numbers in free text.

    Scans for phone-number-like sequences and attempts to match them against
    known African country mobile prefixes.

    Parameters
    ----------
    text:
        Input text to scan.
    default_country:
        ISO alpha-2 code used when a number is in local format (starts with 0)
        and could belong to the default country.

    Returns
    -------
    list[dict]
        Each dict contains:
        - ``country`` — ISO alpha-2 code
        - ``country_code`` — ITU dialling code
        - ``country_name`` — human-readable
        - ``international`` — E.164 format (``+CCXXXXXXXXX``)
        - ``local`` — local dialling format
        - ``raw`` — the original matched text
        - ``start`` / ``end`` — character offsets in *text*

    Examples
    --------
    >>> results = parse_african_phone("Call me on 0803 555 7890 or +254 712 345678")
    >>> results[0]["international"]
    '+2348035557890'
    >>> results[1]["country"]
    'KE'
    """
    results: list[dict] = []
    seen_numbers: set[str] = set()

    for m in _PHONE_RE.finditer(text):
        raw = m.group(1)
        cleaned = _strip_to_digits(raw)
        pure_digits = cleaned.lstrip("+")

        if len(pure_digits) < 7 or len(pure_digits) > 15:
            continue

        parsed = None

        # First try international format (starts with + or country code)
        if cleaned.startswith("+") or len(pure_digits) > 10:
            parsed = _try_match_international(pure_digits)

        # Then try local format against default country
        if parsed is None:
            parsed = _try_match_local(pure_digits, default_country)

        # Last resort: try all countries
        if parsed is None:
            for iso in PHONE_PATTERNS:
                parsed = _try_match_local(pure_digits, iso)
                if parsed:
                    break

        if parsed and parsed["international"] not in seen_numbers:
            seen_numbers.add(parsed["international"])
            results.append({
                **parsed,
                "raw": raw,
                "start": m.start(1),
                "end": m.end(1),
            })

    return results


def normalize_phone(
    number: str,
    default_country: str = "NG",
) -> str:
    """Normalise a phone number to E.164 international format.

    Parameters
    ----------
    number:
        A phone number string in any common format.
    default_country:
        Assumed country when the number is in local format.

    Returns
    -------
    str
        E.164 format (e.g. ``"+2348035557890"``), or the original string
        stripped to digits if no African pattern matched.

    Examples
    --------
    >>> normalize_phone("0803 555 7890")
    '+2348035557890'
    >>> normalize_phone("+27 82 555 1234")
    '+27825551234'
    >>> normalize_phone("0712345678", default_country="KE")
    '+254712345678'
    """
    cleaned = _strip_to_digits(number)
    pure_digits = cleaned.lstrip("+")

    # Try international
    if cleaned.startswith("+") or len(pure_digits) > 10:
        result = _try_match_international(pure_digits)
        if result:
            return result["international"]

    # Try local
    result = _try_match_local(pure_digits, default_country)
    if result:
        return result["international"]

    # Fallback — return stripped digits with + if it was present
    return cleaned


# ---------------------------------------------------------------------------
# phonenumbers (libphonenumber) integration — PRD FR-DETECT-9
# ---------------------------------------------------------------------------
# The custom regex-based parsing above is fast and works offline, but
# libphonenumber has the canonical numbering plans for every country in the
# world. We use it for E.164 normalization and validation as a second
# opinion / fallback. ``phonenumbers`` is in arche-core's base dependencies
# (~5MB pure-Python).


def normalize_e164(number: str, default_country: str = "NG") -> str | None:
    """Normalize a phone number to E.164 using libphonenumber.

    Returns ``None`` if the number cannot be parsed at all. Distinguish
    from ``normalize_phone`` which always returns a string (best-effort).

    Parameters
    ----------
    number:
        Phone number in any common format.
    default_country:
        ISO 3166-1 alpha-2 used when ``number`` lacks an international prefix.

    Returns
    -------
    str or None
        E.164 string like ``"+2348035557890"``, or ``None`` if unparseable.

    Examples
    --------
    >>> normalize_e164("0803 555 7890", "NG")
    '+2348035557890'
    >>> normalize_e164("+27 82 555 1234")
    '+27825551234'
    >>> normalize_e164("not a phone")
    None
    """
    import phonenumbers

    try:
        parsed = phonenumbers.parse(number, default_country)
    except phonenumbers.NumberParseException:
        return None
    if not phonenumbers.is_possible_number(parsed):
        return None
    return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)


def validate_phone(number: str, default_country: str = "NG") -> dict[str, Any]:
    """Validate a phone number using libphonenumber's full numbering-plan data.

    Returns a structured validation record with country / region / line-type
    inference. Useful for downstream policy decisions (e.g. mask only mobile
    numbers, leave landlines for business directories).

    Returns
    -------
    dict
        Always includes ``valid: bool``. When valid, also includes:
            country     - ISO 3166-1 alpha-2 region code
            e164        - E.164 formatted string
            national    - National format string
            line_type   - "mobile" | "fixed_line" | "voip" | "toll_free" | other
            country_calling_code - int (e.g. 234)

    Examples
    --------
    >>> validate_phone("0803 555 7890", "NG")
    {'valid': True, 'country': 'NG', 'e164': '+2348035557890', ...}
    """
    import phonenumbers
    from phonenumbers import carrier as _carrier, geocoder as _geocoder

    try:
        parsed = phonenumbers.parse(number, default_country)
    except phonenumbers.NumberParseException:
        return {"valid": False, "reason": "parse_failed"}

    if not phonenumbers.is_valid_number(parsed):
        return {"valid": False, "reason": "invalid_numbering_plan"}

    line_type_map = {
        phonenumbers.PhoneNumberType.MOBILE: "mobile",
        phonenumbers.PhoneNumberType.FIXED_LINE: "fixed_line",
        phonenumbers.PhoneNumberType.FIXED_LINE_OR_MOBILE: "fixed_or_mobile",
        phonenumbers.PhoneNumberType.VOIP: "voip",
        phonenumbers.PhoneNumberType.TOLL_FREE: "toll_free",
        phonenumbers.PhoneNumberType.PREMIUM_RATE: "premium_rate",
        phonenumbers.PhoneNumberType.SHARED_COST: "shared_cost",
        phonenumbers.PhoneNumberType.PAGER: "pager",
        phonenumbers.PhoneNumberType.UAN: "uan",
        phonenumbers.PhoneNumberType.PERSONAL_NUMBER: "personal_number",
    }
    line_type = line_type_map.get(phonenumbers.number_type(parsed), "unknown")

    return {
        "valid": True,
        "country": phonenumbers.region_code_for_number(parsed),
        "e164": phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164),
        "national": phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.NATIONAL),
        "international": phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.INTERNATIONAL),
        "country_calling_code": parsed.country_code,
        "line_type": line_type,
        "carrier_hint": _carrier.name_for_number(parsed, "en") or None,
        "region_hint": _geocoder.description_for_number(parsed, "en") or None,
    }
