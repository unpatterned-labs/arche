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

"""Ghana Identity Pack — complete jurisdiction profile.

Covers:
- Ghana Card (GHA-NNNNNNNNN-N format, NIA)
- TIN (Taxpayer Identification Number, GRA)
- NHIS (National Health Insurance Scheme)
- Voter ID (Electoral Commission of Ghana)
- Phone formats: MTN, Vodafone, AirtelTigo prefix ranges
- Naming: Akan (day-names), Ewe, Ga conventions
- Data Protection Act 2012 (Act 843) compliance

Usage:
    from arche.jurisdictions.ghana import get_profile, validate_ghana_card
    profile = get_profile()
    result = validate_ghana_card("GHA-123456789-0")
"""

from __future__ import annotations  # noqa: I001

import re

from ..models import JurisdictionProfileModel
from .nigeria import ValidationResult


# ═══════════════════════════════════════════════════════════════════════════════
# ID VALIDATORS
# ═══════════════════════════════════════════════════════════════════════════════


def validate_ghana_card(value: str) -> ValidationResult:
    """Validate a Ghana Card number.

    Format: GHA-NNNNNNNNN-N (3-letter prefix, 9 digits, 1 check digit).
    The prefix is always 'GHA', followed by a hyphen, nine digits,
    another hyphen, and a single check digit.
    Issued by the National Identification Authority (NIA).
    """
    cleaned = re.sub(r"\s+", "", value).upper()

    # Accept with or without hyphens
    m = re.match(r"^GHA-?(\d{9})-?(\d)$", cleaned)
    if not m:
        return ValidationResult(False, "GHANA_CARD", 0.0, {})

    digits = m.group(1)
    check = m.group(2)

    return ValidationResult(True, "GHANA_CARD", 0.92, {
        "issuer": "NIA",
        "format": "GHA-NNNNNNNNN-N",
        "sequence": digits,
        "check_digit": check,
    })


def validate_tin(value: str) -> ValidationResult:
    """Validate a Ghana Taxpayer Identification Number (TIN).

    Rules:
    - Alphanumeric, typically formatted as P00NNNNNNNNN or C00NNNNNNNNN
    - P prefix = individual, C prefix = corporate, G prefix = government
    - Issued by Ghana Revenue Authority (GRA)
    - Older formats may be purely numeric (9-11 digits)
    """
    cleaned = re.sub(r"[\s\-]+", "", value).upper()

    # New GRA format: letter + digits (11-13 chars)
    if re.match(r"^[PCG]\d{10,12}$", cleaned):
        return ValidationResult(True, "TIN", 0.85, {
            "issuer": "GRA",
            "format": "letter-prefix + digits",
            "entity_type": {"P": "individual", "C": "corporate", "G": "government"}.get(
                cleaned[0], "unknown"
            ),
        })

    # Legacy numeric format
    if re.match(r"^\d{9,11}$", cleaned):
        return ValidationResult(True, "TIN", 0.65, {
            "issuer": "GRA",
            "format": "legacy numeric",
        })

    return ValidationResult(False, "TIN", 0.0, {})


def validate_nhis(value: str) -> ValidationResult:
    """Validate a Ghana NHIS (National Health Insurance Scheme) number.

    Rules:
    - Alphanumeric, typically 8-15 characters
    - Issued by the National Health Insurance Authority (NHIA)
    """
    cleaned = re.sub(r"[\s\-]+", "", value)
    if len(cleaned) < 8 or len(cleaned) > 15:
        return ValidationResult(False, "NHIS", 0.0, {})

    # Must be alphanumeric
    if not re.match(r"^[A-Za-z0-9]+$", cleaned):
        return ValidationResult(False, "NHIS", 0.0, {})

    return ValidationResult(True, "NHIS", 0.60, {
        "issuer": "NHIA",
    })


def validate_voter_id(value: str) -> ValidationResult:
    """Validate a Ghana Voter ID number.

    Rules:
    - Alphanumeric, typically 10-15 characters
    - Issued by the Electoral Commission (EC) of Ghana
    - Older format is purely numeric; newer biometric format is alphanumeric
    """
    cleaned = re.sub(r"[\s\-]+", "", value).upper()
    if len(cleaned) < 10 or len(cleaned) > 15:
        return ValidationResult(False, "VOTER_ID", 0.0, {})

    if not re.match(r"^[A-Z0-9]+$", cleaned):
        return ValidationResult(False, "VOTER_ID", 0.0, {})

    # Must contain at least some digits
    if not re.search(r"\d", cleaned):
        return ValidationResult(False, "VOTER_ID", 0.0, {})

    return ValidationResult(True, "VOTER_ID", 0.60, {
        "issuer": "EC",
        "format": "alphanumeric",
    })


# ═══════════════════════════════════════════════════════════════════════════════
# PHONE FORMATS
# ═══════════════════════════════════════════════════════════════════════════════

# Ghana mobile network operators and their prefix allocations (3-digit after 0)
NETWORK_PREFIXES: dict[str, list[str]] = {
    "MTN": ["024", "054", "055", "059"],
    "Vodafone": ["020", "050"],
    "AirtelTigo": ["026", "027", "056", "057"],
}

# Flat lookup: prefix -> operator
_PREFIX_TO_OPERATOR: dict[str, str] = {}
for _op, _prefixes in NETWORK_PREFIXES.items():
    for _p in _prefixes:
        _PREFIX_TO_OPERATOR[_p] = _op


def identify_network(phone: str) -> str | None:
    """Identify the Ghanaian mobile network operator from a phone number.

    Parameters
    ----------
    phone:
        Phone number in local (024...) or international (+233 24...) format.

    Returns
    -------
    str or None
        Operator name (MTN, Vodafone, AirtelTigo) or None if unrecognized.
    """
    cleaned = re.sub(r"[\s\-\(\)\+]+", "", phone)

    # Convert international to local
    if cleaned.startswith("233") and len(cleaned) >= 12:
        cleaned = "0" + cleaned[3:]

    prefix = cleaned[:3]
    return _PREFIX_TO_OPERATOR.get(prefix)


def normalize_phone(phone: str) -> str | None:
    """Normalize a Ghanaian phone number to E.164 format (+233XXXXXXXXX).

    Ghana mobile numbers are 10 digits local (0XX XXX XXXX) or
    12 digits international (233 XX XXX XXXX).

    Returns None if the number doesn't look like a valid Ghanaian mobile number.
    """
    cleaned = re.sub(r"[\s\-\(\)\.]+", "", phone)

    # Already international with +
    if cleaned.startswith("+233"):
        digits = cleaned[1:]  # remove +
    elif cleaned.startswith("233") and len(cleaned) >= 12:
        digits = cleaned
    elif cleaned.startswith("0") and len(cleaned) == 10:
        digits = "233" + cleaned[1:]
    else:
        return None

    if len(digits) != 12 or not digits.isdigit():
        return None

    # Verify it's a known prefix
    local_prefix = "0" + digits[3:5]
    if local_prefix[:3] not in _PREFIX_TO_OPERATOR:
        return None

    return "+" + digits


# ═══════════════════════════════════════════════════════════════════════════════
# NAMING CONVENTIONS
# ═══════════════════════════════════════════════════════════════════════════════

NAMING_CONVENTIONS = [
    {
        "tradition": "Akan",
        "region": "Ashanti, Eastern, Central, Western, Bono",
        "conventions": [
            "Day-names: every child receives a name based on the day of birth",
            "Male day-names: Kwadwo (Mon), Kwabena (Tue), Kwaku (Wed), "
            "Yaw (Thu), Kofi (Fri), Kwame (Sat), Kwasi (Sun)",
            "Female day-names: Adwoa (Mon), Abenaa (Tue), Akua (Wed), "
            "Yaa (Thu), Afua (Fri), Ama (Sat), Akosua (Sun)",
            "Family name (abusua din) + day-name + given name",
            "Christian/English first name common in formal contexts",
            "Diminutives: Kofi -> Kojo, Kwame -> Kwamina (Fante variant)",
        ],
        "day_names_male": {
            "Monday": "Kwadwo",
            "Tuesday": "Kwabena",
            "Wednesday": "Kwaku",
            "Thursday": "Yaw",
            "Friday": "Kofi",
            "Saturday": "Kwame",
            "Sunday": "Kwasi",
        },
        "day_names_female": {
            "Monday": "Adwoa",
            "Tuesday": "Abenaa",
            "Wednesday": "Akua",
            "Thursday": "Yaa",
            "Friday": "Afua",
            "Saturday": "Ama",
            "Sunday": "Akosua",
        },
        "common_surnames": [
            "Asante", "Mensah", "Boateng", "Owusu", "Agyemang",
            "Osei", "Appiah", "Amoah", "Adomako", "Frimpong",
        ],
    },
    {
        "tradition": "Ewe",
        "region": "Volta, Oti",
        "conventions": [
            "Birth-order names common (first-born, second-born)",
            "Circumstantial names: reflect events at birth",
            "Clan/family surname + given name + day-name",
            "Cross-border: same naming system in Togo and Benin",
        ],
        "common_surnames": [
            "Agbeko", "Amegashie", "Ametepee", "Togbe", "Dotse",
            "Kpodo", "Tsikata", "Rawlings", "Amedume", "Nyaku",
        ],
    },
    {
        "tradition": "Ga",
        "region": "Greater Accra",
        "conventions": [
            "Day-names similar to Akan but distinct variants",
            "Male: Kojo (Mon), Komla (Tue), Kwaku (Wed), Yao (Thu), "
            "Kofi (Fri), Kwame (Sat), Kwashi (Sun)",
            "Female: Adjoa (Mon), Abla (Tue), Korkor (Wed), Yaaba (Thu), "
            "Afua (Fri), Ama (Sat), Akweley (Sun)",
            "Quarter/neighborhood-based family names in Accra",
        ],
        "common_surnames": [
            "Nartey", "Lamptey", "Aryeetey", "Ankrah", "Vanderpuye",
            "Ocansey", "Quaye", "Nii", "Kotey", "Ayi",
        ],
    },
]


# ═══════════════════════════════════════════════════════════════════════════════
# ADDRESS CONVENTIONS
# ═══════════════════════════════════════════════════════════════════════════════

ADDRESS_NORMS = {
    "format": "[House Number], [Street Name], [Area/Estate], [City], [Region]",
    "regions": [
        "Ahafo", "Ashanti", "Bono", "Bono East", "Central",
        "Eastern", "Greater Accra", "North East", "Northern",
        "Oti", "Savannah", "Upper East", "Upper West",
        "Volta", "Western", "Western North",
    ],
    "major_cities": [
        "Accra", "Kumasi", "Tamale", "Takoradi", "Cape Coast",
        "Sunyani", "Koforidua", "Ho", "Bolgatanga", "Wa",
        "Tema", "Obuasi", "Teshie", "Nungua", "Madina",
    ],
    "postal_code_format": "Ghana uses digital address system (GhanaPostGPS): XX-NNNN-NNNN",
    "notes": "GhanaPostGPS is the official digital addressing system since 2017",
}


# ═══════════════════════════════════════════════════════════════════════════════
# DATA PROTECTION ACT 2012 (ACT 843) COMPLIANCE
# ═══════════════════════════════════════════════════════════════════════════════

DPA_COMPLIANCE = {
    "law": "Data Protection Act 2012 (Act 843)",
    "regulator": "Data Protection Commission (DPC)",
    "effective_date": "2012-10-16",
    "key_requirements": {
        "consent": "Explicit consent required for processing personal data",
        "lawful_basis": [
            "consent",
            "contract",
            "legal_obligation",
            "vital_interests",
            "public_interest",
            "legitimate_interests",
        ],
        "data_subject_rights": [
            "right_of_access",
            "right_to_rectification",
            "right_to_erasure",
            "right_to_object",
            "right_to_prevent_direct_marketing",
        ],
        "cross_border_transfer": (
            "Transfer restricted unless receiving country has adequate data protection "
            "or data subject has consented"
        ),
        "breach_notification": "Notify DPC without undue delay",
        "registration": "All data controllers and processors must register with the DPC",
    },
    "pii_categories": {
        "high_sensitivity": [
            "ghana_card", "biometric_data", "health_data",
            "genetic_data", "criminal_records",
        ],
        "medium_sensitivity": [
            "TIN", "NHIS", "voter_id", "phone_number", "email",
            "address", "date_of_birth", "bank_account",
        ],
        "low_sensitivity": [
            "full_name", "gender", "region_of_origin", "occupation",
        ],
    },
    "retention_limits": {
        "default": "Only as long as necessary for the stated purpose",
        "financial_records": "As required by Bank of Ghana regulations",
        "health_records": "As required by National Health Insurance Act",
    },
    "penalties": {
        "non_registration": "Up to GHS 36,000 fine and/or up to 3 years imprisonment",
        "unauthorized_disclosure": "Up to GHS 18,000 fine and/or up to 2 years imprisonment",
        "note": "DPC can also issue enforcement notices and compliance orders",
    },
}


# ═══════════════════════════════════════════════════════════════════════════════
# RESOLUTION DEFAULTS
# ═══════════════════════════════════════════════════════════════════════════════

RESOLUTION_DEFAULTS = {
    "name_comparison": "jaro_winkler",
    "name_threshold": 0.85,
    "use_cultural_naming": True,
    "cultural_naming_traditions": ["akan", "ewe", "ga"],
    "phone_comparison": "exact_after_normalization",
    "phone_normalization": "+233 E.164",
    "id_comparison": {
        "GHANA_CARD": "exact",
        "TIN": "exact",
    },
    "address_comparison": "token_sort_ratio",
    "address_threshold": 0.75,
    "blocking_keys": [
        "first_char_first_name",
        "first_char_last_name",
        "phone_last_4",
        "region",
    ],
}


# ═══════════════════════════════════════════════════════════════════════════════
# CONTEXT KEYWORDS
# ═══════════════════════════════════════════════════════════════════════════════

CONTEXT_KEYWORDS = {
    "GHANA_CARD": [
        "ghana card", "nia", "national identification",
        "ghana id", "national id", "gha-",
    ],
    "TIN": [
        "tin", "tax identification", "gra", "tax id",
        "taxpayer", "tax number", "ghana revenue",
    ],
    "NHIS": [
        "nhis", "health insurance", "nhia",
        "national health insurance",
    ],
    "VOTER_ID": [
        "voter", "voter id", "electoral commission",
        "voter card", "biometric voter", "ec card",
    ],
}


# ═══════════════════════════════════════════════════════════════════════════════
# JURISDICTION PROFILE
# ═══════════════════════════════════════════════════════════════════════════════


def get_profile() -> JurisdictionProfileModel:
    """Return the complete Ghana jurisdiction profile."""
    return JurisdictionProfileModel(
        country_code="GH",
        country_name="Ghana",
        id_patterns=[
            {
                "id_type": "GHANA_CARD",
                "description": "Ghana Card (National ID)",
                "issuer": "NIA",
                "format": "GHA-NNNNNNNNN-N",
                "validator": "validate_ghana_card",
                "sensitivity": "high",
            },
            {
                "id_type": "TIN",
                "description": "Taxpayer Identification Number",
                "issuer": "GRA",
                "format": "P/C/G + 10-12 digits",
                "validator": "validate_tin",
                "sensitivity": "medium",
            },
            {
                "id_type": "NHIS",
                "description": "National Health Insurance Scheme",
                "issuer": "NHIA",
                "format": "alphanumeric 8-15 chars",
                "validator": "validate_nhis",
                "sensitivity": "medium",
            },
            {
                "id_type": "VOTER_ID",
                "description": "Voter ID Card",
                "issuer": "EC",
                "format": "alphanumeric 10-15 chars",
                "validator": "validate_voter_id",
                "sensitivity": "medium",
            },
        ],
        phone_formats=[
            {
                "operator": operator,
                "prefixes": prefixes,
                "format": "0XX XXX XXXX (local) / +233 XX XXX XXXX (international)",
                "local_length": 10,
                "intl_length": 12,
            }
            for operator, prefixes in NETWORK_PREFIXES.items()
        ],
        naming_conventions=NAMING_CONVENTIONS,
        address_norms=ADDRESS_NORMS,
        compliance_metadata=DPA_COMPLIANCE,
        version="0.1.0",
    )


def detect_ids(text: str) -> list[ValidationResult]:
    """Detect and validate Ghanaian ID types in free text.

    Scans for Ghana Card patterns and uses context keywords
    to boost confidence for other ID types.
    """
    results: list[ValidationResult] = []

    # Ghana Card pattern: GHA-NNNNNNNNN-N
    for m in re.finditer(r"GHA-?\d{9}-?\d", text, re.IGNORECASE):
        val = m.group(0)
        card_result = validate_ghana_card(val)
        if card_result.is_valid:
            context = text[max(0, m.start() - 80):min(len(text), m.end() + 80)].lower()
            if any(kw in context for kw in CONTEXT_KEYWORDS["GHANA_CARD"]):
                card_result.confidence = min(card_result.confidence + 0.05, 1.0)
            results.append(card_result)

    # TIN detection via context keywords (letter prefix + digits)
    for m in re.finditer(r"(?<![A-Za-z])([PCG]\d{10,12})(?![0-9])", text, re.IGNORECASE):
        val = m.group(1)
        context = text[max(0, m.start() - 80):min(len(text), m.end() + 80)].lower()
        if any(kw in context for kw in CONTEXT_KEYWORDS["TIN"]):
            tin_result = validate_tin(val)
            if tin_result.is_valid:
                tin_result.confidence = min(tin_result.confidence + 0.10, 1.0)
                results.append(tin_result)

    return results
