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

"""Nigeria Identity Pack — the first complete jurisdiction profile.

Covers:
- NIN (National Identification Number) — 11 digits, NIMC
- BVN (Bank Verification Number) — 11 digits starting with 22, NIBSS
- PVC (Permanent Voter Card) — alphanumeric, INEC
- TIN (Tax Identification Number) — 10 digits, FIRS
- NHIS (National Health Insurance) — varies, NHIS
- NHF (National Housing Fund) — varies, FMBN
- Phone formats: MTN, Glo, Airtel, 9mobile prefix ranges
- Naming: Yoruba, Igbo, Hausa conventions (patronymics, day-names, praise-names)
- NDPA compliance: Nigeria Data Protection Act 2023

Usage:
    from arche.jurisdictions.nigeria import get_profile, validate_nin, validate_bvn
    profile = get_profile()
    result = validate_nin("12345678901")
"""

from __future__ import annotations  # noqa: I001

import re
from dataclasses import dataclass

from ..models import JurisdictionProfileModel


# ═══════════════════════════════════════════════════════════════════════════════
# ID VALIDATORS
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class ValidationResult:
    """Result of an ID validation check."""
    is_valid: bool
    id_type: str
    confidence: float
    metadata: dict


def validate_nin(value: str) -> ValidationResult:
    """Validate a Nigerian National Identification Number (NIN).

    Rules:
    - Exactly 11 digits
    - No checksum algorithm publicly documented, but structural validation applies
    - Issued by NIMC (National Identity Management Commission)
    """
    digits = re.sub(r"[\s\-]+", "", value)
    if len(digits) != 11 or not digits.isdigit():
        return ValidationResult(False, "NIN", 0.0, {})

    # BVN starts with 22 — if it does, it's likely a BVN not NIN
    if digits.startswith("22"):
        return ValidationResult(False, "NIN", 0.0, {"note": "Looks like BVN (starts with 22)"})

    return ValidationResult(True, "NIN", 0.90, {
        "issuer": "NIMC",
        "format": "11-digit",
    })


def validate_bvn(value: str) -> ValidationResult:
    """Validate a Nigerian Bank Verification Number (BVN).

    Rules:
    - Exactly 11 digits
    - Starts with "22"
    - Issued by NIBSS (Nigeria Inter-Bank Settlement System)
    """
    digits = re.sub(r"[\s\-]+", "", value)
    if len(digits) != 11 or not digits.isdigit():
        return ValidationResult(False, "BVN", 0.0, {})
    if not digits.startswith("22"):
        return ValidationResult(False, "BVN", 0.0, {"note": "BVN must start with 22"})

    return ValidationResult(True, "BVN", 0.95, {
        "issuer": "NIBSS",
        "format": "11-digit, prefix 22",
    })


def validate_tin(value: str) -> ValidationResult:
    """Validate a Nigerian Tax Identification Number (TIN).

    Rules:
    - 10 digits (individual) or 10 digits with hyphen pattern (corporate)
    - First digit indicates tax office
    - Issued by FIRS (Federal Inland Revenue Service)
    """
    digits = re.sub(r"[\s\-]+", "", value)
    if len(digits) != 10 or not digits.isdigit():
        return ValidationResult(False, "TIN", 0.0, {})

    return ValidationResult(True, "TIN", 0.80, {
        "issuer": "FIRS",
        "format": "10-digit",
    })


def validate_pvc(value: str) -> ValidationResult:
    """Validate a Nigerian Permanent Voter Card (PVC) number.

    Rules:
    - Alphanumeric, typically 19 characters
    - Issued by INEC (Independent National Electoral Commission)
    - Format varies by state/LGA
    """
    cleaned = re.sub(r"[\s\-]+", "", value).upper()
    if len(cleaned) < 15 or len(cleaned) > 25:
        return ValidationResult(False, "PVC", 0.0, {})

    # Must contain both letters and digits
    if not re.search(r"[A-Z]", cleaned) or not re.search(r"\d", cleaned):
        return ValidationResult(False, "PVC", 0.0, {})

    return ValidationResult(True, "PVC", 0.65, {
        "issuer": "INEC",
        "format": "alphanumeric",
    })


def validate_nhis(value: str) -> ValidationResult:
    """Validate a Nigerian NHIS number (National Health Insurance Scheme)."""
    digits = re.sub(r"[\s\-]+", "", value)
    if len(digits) < 8 or len(digits) > 15 or not digits.isdigit():
        return ValidationResult(False, "NHIS", 0.0, {})

    return ValidationResult(True, "NHIS", 0.60, {
        "issuer": "NHIS",
    })


def validate_nhf(value: str) -> ValidationResult:
    """Validate a Nigerian NHF number (National Housing Fund)."""
    digits = re.sub(r"[\s\-]+", "", value)
    if len(digits) < 8 or len(digits) > 15 or not digits.isdigit():
        return ValidationResult(False, "NHF", 0.0, {})

    return ValidationResult(True, "NHF", 0.55, {
        "issuer": "FMBN",
    })


# ═══════════════════════════════════════════════════════════════════════════════
# PHONE FORMATS
# ═══════════════════════════════════════════════════════════════════════════════

# Nigerian mobile network operators and their prefix allocations
NETWORK_PREFIXES: dict[str, list[str]] = {
    "MTN": [
        "0703", "0706", "0803", "0806", "0810", "0813", "0814",
        "0816", "0903", "0906", "0913", "0916",
    ],
    "Glo": [
        "0705", "0805", "0807", "0811", "0815", "0905", "0915",
    ],
    "Airtel": [
        "0701", "0708", "0802", "0808", "0812", "0901", "0902",
        "0904", "0907", "0912",
    ],
    "9mobile": [
        "0809", "0817", "0818", "0819", "0908", "0909",
    ],
}

# Flat lookup: prefix -> operator
_PREFIX_TO_OPERATOR: dict[str, str] = {}
for _op, _prefixes in NETWORK_PREFIXES.items():
    for _p in _prefixes:
        _PREFIX_TO_OPERATOR[_p] = _op


def identify_network(phone: str) -> str | None:
    """Identify the Nigerian mobile network operator from a phone number.

    Parameters
    ----------
    phone:
        Phone number in local (0803...) or international (+234803...) format.

    Returns
    -------
    str or None
        Operator name (MTN, Glo, Airtel, 9mobile) or None if unrecognized.
    """
    cleaned = re.sub(r"[\s\-\(\)\+]+", "", phone)

    # Convert international to local
    if cleaned.startswith("234") and len(cleaned) >= 13:
        cleaned = "0" + cleaned[3:]

    prefix = cleaned[:4]
    return _PREFIX_TO_OPERATOR.get(prefix)


def normalize_phone(phone: str) -> str | None:
    """Normalize a Nigerian phone number to E.164 format (+234XXXXXXXXXX).

    Returns None if the number doesn't look like a valid Nigerian mobile number.
    """
    cleaned = re.sub(r"[\s\-\(\)\.]+", "", phone)

    # Already international with +
    if cleaned.startswith("+234"):
        digits = cleaned[1:]  # remove +
    elif cleaned.startswith("234") and len(cleaned) >= 13:
        digits = cleaned
    elif cleaned.startswith("0") and len(cleaned) == 11:
        digits = "234" + cleaned[1:]
    else:
        return None

    if len(digits) != 13 or not digits.isdigit():
        return None

    # Verify it's a known prefix
    local_prefix = "0" + digits[3:6]
    if local_prefix[:4] not in _PREFIX_TO_OPERATOR:
        return None

    return "+" + digits


# ═══════════════════════════════════════════════════════════════════════════════
# NAMING CONVENTIONS
# ═══════════════════════════════════════════════════════════════════════════════

NAMING_CONVENTIONS = [
    {
        "tradition": "Yoruba",
        "region": "South-West",
        "conventions": [
            "Patronymic: children take father's first name as surname",
            "Oriki (praise-name): e.g. Adewale = 'crown has come home'",
            "Day-names less common but exist (e.g. Abiku names)",
            "Christian/Muslim first name + Yoruba surname common",
            "Name order: [Western name] [Yoruba name] [Surname]",
        ],
        "common_prefixes": ["Ade", "Ola", "Ayo", "Oba", "Omo"],
        "common_surnames": [
            "Okafor", "Adeyemi", "Ogundimu", "Afolabi", "Oluwaseun",
            "Bakare", "Balogun", "Fashola", "Osinbajo", "Tinubu",
        ],
    },
    {
        "tradition": "Igbo",
        "region": "South-East",
        "conventions": [
            "Patronymic: father's name as surname",
            "Theophoric names: Chi- prefix (God) e.g. Chinedu, Chinwe, Chisom",
            "Nna-/Nne- prefix (father/mother) e.g. Nneka, Nnamdi",
            "Day-names: Eke, Oye, Afo, Nkwo (market days)",
            "Name order: [Western name] [Igbo name] [Surname]",
        ],
        "common_prefixes": ["Chi", "Nna", "Nne", "Obi", "Ugo"],
        "common_surnames": [
            "Okafor", "Nwosu", "Eze", "Onyeka", "Igwe",
            "Nwachukwu", "Okonkwo", "Uzoma", "Chukwuma", "Amadi",
        ],
    },
    {
        "tradition": "Hausa",
        "region": "North",
        "conventions": [
            "Patronymic: 'ibn/bin' (son of) or 'bint' (daughter of)",
            "Islamic naming: Arabic-origin names predominate",
            "Praise-names (laqabi): describe qualities",
            "Place-based surnames common (e.g. Kano, Sokoto)",
            "Name order: [First name] [Father's name] [Grandfather's name]",
        ],
        "common_prefixes": ["Abdul", "Muhammad", "Ibrahim"],
        "common_surnames": [
            "Abdullahi", "Bello", "Suleiman", "Abubakar", "Danladi",
            "Yusuf", "Shehu", "Musa", "Aliyu", "Garba",
        ],
    },
    {
        "tradition": "Fulani",
        "region": "North / Pan-West Africa",
        "conventions": [
            "Patronymic: father's name follows given name",
            "Clan names: Ba-, Bal-, Barry, Diallo, Sow, Bah",
            "Cross-border: same families in NG, CM, SN, GN, ML",
            "Islamic naming tradition",
        ],
        "common_prefixes": [],
        "common_surnames": [
            "Bello", "Diallo", "Sow", "Bah", "Barry",
            "Jallow", "Balde", "Camara",
        ],
    },
]


# ═══════════════════════════════════════════════════════════════════════════════
# ADDRESS CONVENTIONS
# ═══════════════════════════════════════════════════════════════════════════════

ADDRESS_NORMS = {
    "format": "[House Number], [Street Name], [Area/Estate], [City], [State]",
    "states": [
        "Abia", "Adamawa", "Akwa Ibom", "Anambra", "Bauchi", "Bayelsa",
        "Benue", "Borno", "Cross River", "Delta", "Ebonyi", "Edo",
        "Ekiti", "Enugu", "FCT", "Gombe", "Imo", "Jigawa", "Kaduna",
        "Kano", "Katsina", "Kebbi", "Kogi", "Kwara", "Lagos",
        "Nasarawa", "Niger", "Ogun", "Ondo", "Osun", "Oyo",
        "Plateau", "Rivers", "Sokoto", "Taraba", "Yobe", "Zamfara",
    ],
    "major_cities": [
        "Lagos", "Abuja", "Kano", "Ibadan", "Port Harcourt",
        "Benin City", "Kaduna", "Enugu", "Aba", "Maiduguri",
        "Ilorin", "Jos", "Owerri", "Abeokuta", "Warri",
        "Calabar", "Uyo", "Asaba", "Awka", "Lokoja",
    ],
    "postal_code_format": "6 digits (NNNNNN), state-based allocation",
}


# ═══════════════════════════════════════════════════════════════════════════════
# NDPA COMPLIANCE (Nigeria Data Protection Act 2023)
# ═══════════════════════════════════════════════════════════════════════════════

NDPA_COMPLIANCE = {
    "law": "Nigeria Data Protection Act 2023 (NDPA)",
    "regulator": "Nigeria Data Protection Commission (NDPC)",
    "effective_date": "2023-06-14",
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
            "right_to_restrict_processing",
            "right_to_data_portability",
            "right_to_object",
        ],
        "cross_border_transfer": (
            "Permitted only to countries with adequate protection "
            "or with appropriate safeguards (NDPC adequacy assessment)"
        ),
        "breach_notification": "72 hours to NDPC, without undue delay to data subjects",
        "dpia_required": "For high-risk processing (large-scale identity data, biometrics)",
    },
    "pii_categories": {
        "high_sensitivity": [
            "NIN", "BVN", "biometric_data", "health_data",
            "genetic_data", "criminal_records",
        ],
        "medium_sensitivity": [
            "TIN", "PVC", "phone_number", "email", "address",
            "date_of_birth", "bank_account",
        ],
        "low_sensitivity": [
            "full_name", "gender", "state_of_origin", "occupation",
        ],
    },
    "retention_limits": {
        "default": "Only as long as necessary for the purpose",
        "financial_records": "6 years (CBN requirement)",
        "kyc_records": "5 years after relationship ends (CBN/NDPC)",
        "health_records": "As required by National Health Act",
    },
    "penalties": {
        "minor_violation": "Up to NGN 10 million or 2% of annual gross revenue",
        "major_violation": "Up to NGN 10 million or 2% of annual gross revenue",
        "note": "NDPC can also issue enforcement notices, compliance orders",
    },
}


# ═══════════════════════════════════════════════════════════════════════════════
# RESOLUTION DEFAULTS — optimized Splink settings for Nigerian data
# ═══════════════════════════════════════════════════════════════════════════════

RESOLUTION_DEFAULTS = {
    "name_comparison": "jaro_winkler",
    "name_threshold": 0.85,
    "use_cultural_naming": True,
    "cultural_naming_traditions": ["yoruba", "igbo", "hausa", "fulani", "pan_islamic"],
    "phone_comparison": "exact_after_normalization",
    "phone_normalization": "+234 E.164",
    "id_comparison": {
        "NIN": "exact",
        "BVN": "exact",
        "TIN": "exact",
    },
    "address_comparison": "token_sort_ratio",
    "address_threshold": 0.75,
    "blocking_keys": [
        "first_char_first_name",
        "first_char_last_name",
        "phone_last_4",
        "state_of_origin",
    ],
}


# ═══════════════════════════════════════════════════════════════════════════════
# CONTEXT KEYWORDS — boost ID detection confidence when these appear nearby
# ═══════════════════════════════════════════════════════════════════════════════

CONTEXT_KEYWORDS = {
    "NIN": [
        "nin", "national identification number", "nimc",
        "national identity", "identity number", "id number",
    ],
    "BVN": [
        "bvn", "bank verification number", "nibss",
        "bank verification", "bvn number",
    ],
    "TIN": [
        "tin", "tax identification", "firs", "tax id",
        "taxpayer", "tax number",
    ],
    "PVC": [
        "pvc", "voter card", "voter's card", "inec",
        "permanent voter", "voter number",
    ],
}


# ═══════════════════════════════════════════════════════════════════════════════
# JURISDICTION PROFILE
# ═══════════════════════════════════════════════════════════════════════════════


def get_profile() -> JurisdictionProfileModel:
    """Return the complete Nigeria jurisdiction profile."""
    return JurisdictionProfileModel(
        country_code="NG",
        country_name="Nigeria",
        id_patterns=[
            {
                "id_type": "NIN",
                "description": "National Identification Number",
                "issuer": "NIMC",
                "format": "11 digits",
                "validator": "validate_nin",
                "sensitivity": "high",
            },
            {
                "id_type": "BVN",
                "description": "Bank Verification Number",
                "issuer": "NIBSS",
                "format": "11 digits, prefix 22",
                "validator": "validate_bvn",
                "sensitivity": "high",
            },
            {
                "id_type": "TIN",
                "description": "Tax Identification Number",
                "issuer": "FIRS",
                "format": "10 digits",
                "validator": "validate_tin",
                "sensitivity": "medium",
            },
            {
                "id_type": "PVC",
                "description": "Permanent Voter Card",
                "issuer": "INEC",
                "format": "alphanumeric ~19 chars",
                "validator": "validate_pvc",
                "sensitivity": "medium",
            },
            {
                "id_type": "NHIS",
                "description": "National Health Insurance Scheme",
                "issuer": "NHIS",
                "format": "8-15 digits",
                "validator": "validate_nhis",
                "sensitivity": "medium",
            },
            {
                "id_type": "NHF",
                "description": "National Housing Fund",
                "issuer": "FMBN",
                "format": "8-15 digits",
                "validator": "validate_nhf",
                "sensitivity": "low",
            },
        ],
        phone_formats=[
            {
                "operator": operator,
                "prefixes": prefixes,
                "format": "0XXX XXX XXXX (local) / +234 XXX XXX XXXX (international)",
                "local_length": 11,
                "intl_length": 13,
            }
            for operator, prefixes in NETWORK_PREFIXES.items()
        ],
        naming_conventions=NAMING_CONVENTIONS,
        address_norms=ADDRESS_NORMS,
        compliance_metadata=NDPA_COMPLIANCE,
        version="0.1.0",
    )


def detect_ids(text: str) -> list[ValidationResult]:
    """Detect and validate all Nigerian ID types in free text.

    This is a higher-level function than ``african.ids.detect_african_ids()``
    — it adds TIN detection and uses Nigeria-specific context boosting.
    """
    results: list[ValidationResult] = []

    # NIN pattern: 11 digits with NIN context
    for m in re.finditer(r"(?<![0-9])(\d{11})(?![0-9])", text):
        val = m.group(1)
        # Check BVN first (more specific)
        bvn_result = validate_bvn(val)
        if bvn_result.is_valid:
            # Check for BVN context
            context = text[max(0, m.start() - 80):min(len(text), m.end() + 80)].lower()
            if any(kw in context for kw in CONTEXT_KEYWORDS["BVN"]):
                bvn_result.confidence = min(bvn_result.confidence + 0.05, 1.0)
            results.append(bvn_result)
            continue

        nin_result = validate_nin(val)
        if nin_result.is_valid:
            context = text[max(0, m.start() - 80):min(len(text), m.end() + 80)].lower()
            if any(kw in context for kw in CONTEXT_KEYWORDS["NIN"]):
                nin_result.confidence = min(nin_result.confidence + 0.10, 1.0)
            results.append(nin_result)

    # TIN pattern: 10 digits with TIN context
    for m in re.finditer(r"(?<![0-9])(\d{10})(?![0-9])", text):
        val = m.group(1)
        context = text[max(0, m.start() - 80):min(len(text), m.end() + 80)].lower()
        if any(kw in context for kw in CONTEXT_KEYWORDS["TIN"]):
            tin_result = validate_tin(val)
            if tin_result.is_valid:
                tin_result.confidence = min(tin_result.confidence + 0.10, 1.0)
                results.append(tin_result)

    return results
