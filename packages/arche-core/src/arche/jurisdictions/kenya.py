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

"""Kenya Identity Pack — complete jurisdiction profile.

Covers:
- National ID (7-8 digits, IPRS)
- Huduma Namba (NIIMS)
- KRA PIN (Tax, format A + 9 digits + letter)
- NHIF (National Hospital Insurance Fund)
- Phone formats: Safaricom, Airtel, Telkom prefix ranges
- Naming: Kikuyu, Luo, Kalenjin, Luhya conventions
- Data Protection Act 2019 compliance

Usage:
    from arche.jurisdictions.kenya import get_profile, validate_national_id
    profile = get_profile()
    result = validate_national_id("12345678")
"""

from __future__ import annotations  # noqa: I001

import re

from ..models import JurisdictionProfileModel
from .nigeria import ValidationResult


# ═══════════════════════════════════════════════════════════════════════════════
# ID VALIDATORS
# ═══════════════════════════════════════════════════════════════════════════════


def validate_national_id(value: str) -> ValidationResult:
    """Validate a Kenyan National ID number.

    Rules:
    - 7 or 8 digits
    - No letters or special characters
    - Issued by IPRS (Integrated Population Registration System)
    - Also referred to as ID card number
    """
    digits = re.sub(r"[\s\-]+", "", value)
    if not digits.isdigit():
        return ValidationResult(False, "NATIONAL_ID", 0.0, {})

    if len(digits) not in (7, 8):
        return ValidationResult(False, "NATIONAL_ID", 0.0, {})

    # Leading zeros are valid — some old IDs start with 0
    return ValidationResult(True, "NATIONAL_ID", 0.88, {
        "issuer": "IPRS",
        "format": f"{len(digits)}-digit",
    })


def validate_huduma_namba(value: str) -> ValidationResult:
    """Validate a Kenyan Huduma Namba (NIIMS number).

    Rules:
    - Alphanumeric, typically starts with letters followed by digits
    - Part of the National Integrated Identity Management System (NIIMS)
    - Format not yet fully standardized; we validate structural patterns
    """
    cleaned = re.sub(r"[\s\-]+", "", value).upper()

    # Current observed pattern: alphanumeric, 8-12 chars
    if len(cleaned) < 8 or len(cleaned) > 12:
        return ValidationResult(False, "HUDUMA", 0.0, {})

    if not re.match(r"^[A-Z0-9]+$", cleaned):
        return ValidationResult(False, "HUDUMA", 0.0, {})

    return ValidationResult(True, "HUDUMA", 0.55, {
        "issuer": "NIIMS",
        "format": "alphanumeric",
        "note": "Huduma Namba format is evolving; structural validation only",
    })


def validate_kra_pin(value: str) -> ValidationResult:
    """Validate a Kenyan KRA PIN (Tax Identification).

    Rules:
    - Format: A + 9 digits + letter (e.g. A123456789Z)
    - First letter indicates taxpayer type (A = individual, P = partnership,
      C = company, etc.)
    - Issued by Kenya Revenue Authority (KRA)
    """
    cleaned = re.sub(r"[\s\-]+", "", value).upper()

    m = re.match(r"^([A-Z])(\d{9})([A-Z])$", cleaned)
    if not m:
        return ValidationResult(False, "KRA_PIN", 0.0, {})

    prefix = m.group(1)
    _digits = m.group(2)
    suffix = m.group(3)

    entity_types = {
        "A": "individual",
        "P": "partnership",
        "C": "company",
    }

    return ValidationResult(True, "KRA_PIN", 0.90, {
        "issuer": "KRA",
        "format": "letter + 9 digits + letter",
        "prefix": prefix,
        "suffix": suffix,
        "entity_type": entity_types.get(prefix, "other"),
    })


def validate_nhif(value: str) -> ValidationResult:
    """Validate a Kenyan NHIF (National Hospital Insurance Fund) number.

    Rules:
    - Numeric, typically 6-10 digits
    - Issued by NHIF
    """
    digits = re.sub(r"[\s\-]+", "", value)
    if not digits.isdigit():
        return ValidationResult(False, "NHIF", 0.0, {})

    if len(digits) < 6 or len(digits) > 10:
        return ValidationResult(False, "NHIF", 0.0, {})

    return ValidationResult(True, "NHIF", 0.60, {
        "issuer": "NHIF",
        "format": f"{len(digits)}-digit",
    })


# ═══════════════════════════════════════════════════════════════════════════════
# PHONE FORMATS
# ═══════════════════════════════════════════════════════════════════════════════

# Kenyan mobile network operators and their prefix allocations (4-digit after 0)
NETWORK_PREFIXES: dict[str, list[str]] = {
    "Safaricom": [
        "0701", "0702", "0703", "0704", "0705", "0706", "0707", "0708", "0709",
        "0710", "0711", "0712", "0713", "0714", "0715", "0716", "0717", "0718",
        "0719", "0720", "0721", "0722", "0723", "0724", "0725", "0726", "0727",
        "0728", "0729",
        "0740", "0741", "0742", "0743", "0744", "0745", "0746", "0747", "0748", "0749",
        "0757", "0758", "0759",
        "0768", "0769",
        "0790", "0791", "0792", "0793", "0794", "0795", "0796", "0797", "0798", "0799",
        "0110", "0111", "0112", "0113", "0114", "0115",
    ],
    "Airtel": [
        "0730", "0731", "0732", "0733", "0734", "0735", "0736", "0737", "0738", "0739",
        "0750", "0751", "0752", "0753", "0754", "0755", "0756",
        "0780", "0781", "0782", "0783", "0784", "0785", "0786", "0787", "0788", "0789",
        "0100", "0101", "0102", "0103", "0104", "0105", "0106", "0107", "0108",
    ],
    "Telkom": [
        "0770", "0771", "0772", "0773", "0774", "0775", "0776", "0777", "0778", "0779",
    ],
}

# Flat lookup: prefix -> operator
_PREFIX_TO_OPERATOR: dict[str, str] = {}
for _op, _prefixes in NETWORK_PREFIXES.items():
    for _p in _prefixes:
        _PREFIX_TO_OPERATOR[_p] = _op


def identify_network(phone: str) -> str | None:
    """Identify the Kenyan mobile network operator from a phone number.

    Parameters
    ----------
    phone:
        Phone number in local (07XX...) or international (+254 7XX...) format.

    Returns
    -------
    str or None
        Operator name (Safaricom, Airtel, Telkom) or None if unrecognized.
    """
    cleaned = re.sub(r"[\s\-\(\)\+]+", "", phone)

    # Convert international to local
    if cleaned.startswith("254") and len(cleaned) >= 12:
        cleaned = "0" + cleaned[3:]

    prefix = cleaned[:4]
    return _PREFIX_TO_OPERATOR.get(prefix)


def normalize_phone(phone: str) -> str | None:
    """Normalize a Kenyan phone number to E.164 format (+254XXXXXXXXX).

    Kenya mobile numbers are 10 digits local (07XX XXX XXX) or
    12 digits international (254 7XX XXX XXX).

    Returns None if the number doesn't look like a valid Kenyan mobile number.
    """
    cleaned = re.sub(r"[\s\-\(\)\.]+", "", phone)

    # Already international with +
    if cleaned.startswith("+254"):
        digits = cleaned[1:]  # remove +
    elif cleaned.startswith("254") and len(cleaned) >= 12:
        digits = cleaned
    elif cleaned.startswith("0") and len(cleaned) == 10:
        digits = "254" + cleaned[1:]
    else:
        return None

    if len(digits) != 12 or not digits.isdigit():
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
        "tradition": "Kikuyu",
        "region": "Central Kenya",
        "conventions": [
            "Patronymic: child named after paternal grandparent (alternating generations)",
            "First-born son: named after paternal grandfather",
            "First-born daughter: named after paternal grandmother",
            "Second-born: named after maternal grandparents",
            "Christian first name + Kikuyu name + father's name as surname",
            "Common prefixes: Wa- (daughter of), Wa- also used as 'of'",
        ],
        "common_surnames": [
            "Kamau", "Njoroge", "Maina", "Wanjiku", "Kariuki",
            "Mwangi", "Ngugi", "Kimani", "Kibaki", "Kenyatta",
        ],
    },
    {
        "tradition": "Luo",
        "region": "Nyanza (Lake Victoria)",
        "conventions": [
            "Patronymic: father's first name becomes child's surname",
            "Birth-order names: common (e.g. Ochieng=born during sunshine)",
            "Circumstantial names: reflect events at birth",
            "Clan names used but less common in formal records",
            "Name order: [Given name] [Father's name] [Grandfather's name]",
        ],
        "common_surnames": [
            "Ochieng", "Otieno", "Odhiambo", "Akinyi", "Owino",
            "Odinga", "Oduya", "Onyango", "Awuor", "Nyong'o",
        ],
    },
    {
        "tradition": "Kalenjin",
        "region": "Rift Valley",
        "conventions": [
            "Patronymic: 'arap' (son of) + father's name",
            "Birth circumstance names (e.g. Kipruto=born during rain)",
            "Kip- prefix for males, Chep-/Jep- prefix for females",
            "Age-set names can supplement individual names",
            "Christian name adoption common",
        ],
        "common_prefixes": ["Kip", "Chep", "Jep", "Kib"],
        "common_surnames": [
            "Kipchoge", "Kosgei", "Ruto", "Cheruiyot", "Kipruto",
            "Sang", "Bett", "Kiplagat", "Kibet", "Chepkoech",
        ],
    },
    {
        "tradition": "Luhya",
        "region": "Western Kenya",
        "conventions": [
            "Patronymic: father's name as surname",
            "Clan/sub-tribe identification through names",
            "Birth-order and circumstantial naming",
            "Multiple sub-dialects (Bukusu, Maragoli, Luyia) have naming variants",
            "Christian name + traditional name + father's name",
        ],
        "common_surnames": [
            "Wafula", "Wekesa", "Simiyu", "Nafula", "Nekesa",
            "Masinde", "Barasa", "Wamalwa", "Mudavadi", "Oparanya",
        ],
    },
]


# ═══════════════════════════════════════════════════════════════════════════════
# ADDRESS CONVENTIONS
# ═══════════════════════════════════════════════════════════════════════════════

ADDRESS_NORMS = {
    "format": "[P.O. Box NNNNN] / [Building], [Street], [Area], [City] [Postal Code]",
    "counties": [
        "Baringo", "Bomet", "Bungoma", "Busia", "Elgeyo-Marakwet",
        "Embu", "Garissa", "Homa Bay", "Isiolo", "Kajiado",
        "Kakamega", "Kericho", "Kiambu", "Kilifi", "Kirinyaga",
        "Kisii", "Kisumu", "Kitui", "Kwale", "Laikipia",
        "Lamu", "Machakos", "Makueni", "Mandera", "Marsabit",
        "Meru", "Migori", "Mombasa", "Murang'a", "Nairobi",
        "Nakuru", "Nandi", "Narok", "Nyamira", "Nyandarua",
        "Nyeri", "Samburu", "Siaya", "Taita-Taveta", "Tana River",
        "Tharaka-Nithi", "Trans-Nzoia", "Turkana", "Uasin Gishu",
        "Vihiga", "Wajir", "West Pokot",
    ],
    "major_cities": [
        "Nairobi", "Mombasa", "Kisumu", "Nakuru", "Eldoret",
        "Thika", "Malindi", "Kitale", "Garissa", "Nyeri",
        "Machakos", "Meru", "Lamu", "Nanyuki", "Naivasha",
    ],
    "postal_code_format": "5 digits (NNNNN), city/town-based",
}


# ═══════════════════════════════════════════════════════════════════════════════
# DATA PROTECTION ACT 2019 COMPLIANCE
# ═══════════════════════════════════════════════════════════════════════════════

DPA_COMPLIANCE = {
    "law": "Data Protection Act 2019 (No. 24 of 2019)",
    "regulator": "Office of the Data Protection Commissioner (ODPC)",
    "effective_date": "2019-11-25",
    "key_requirements": {
        "consent": "Explicit, informed consent required for processing personal data",
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
            "right_not_to_be_subject_to_automated_decisions",
        ],
        "cross_border_transfer": (
            "Permitted only to countries with adequate data protection, "
            "with appropriate safeguards, or with ODPC authorization"
        ),
        "breach_notification": "72 hours to ODPC, without undue delay to data subjects",
        "dpia_required": "For processing likely to result in high risk to data subjects",
        "registration": "Data controllers and processors must register with ODPC",
    },
    "pii_categories": {
        "high_sensitivity": [
            "national_id", "huduma_namba", "biometric_data", "health_data",
            "genetic_data", "criminal_records",
        ],
        "medium_sensitivity": [
            "KRA_PIN", "NHIF", "phone_number", "email",
            "address", "date_of_birth", "bank_account",
        ],
        "low_sensitivity": [
            "full_name", "gender", "county_of_origin", "occupation",
        ],
    },
    "retention_limits": {
        "default": "Only as long as necessary for the stated purpose",
        "financial_records": "As required by CBK (Central Bank of Kenya) regulations",
        "health_records": "As required by Health Act 2017",
        "tax_records": "As required by KRA (minimum 5 years)",
    },
    "penalties": {
        "individual": "Up to KES 5 million or imprisonment up to 3 years, or both",
        "corporate": "Up to KES 5 million or 1% of annual turnover (whichever is lower)",
        "note": "ODPC can issue enforcement notices, penalty notices, and compliance orders",
    },
}


# ═══════════════════════════════════════════════════════════════════════════════
# RESOLUTION DEFAULTS
# ═══════════════════════════════════════════════════════════════════════════════

RESOLUTION_DEFAULTS = {
    "name_comparison": "jaro_winkler",
    "name_threshold": 0.85,
    "use_cultural_naming": True,
    "cultural_naming_traditions": ["kikuyu", "luo", "kalenjin", "luhya"],
    "phone_comparison": "exact_after_normalization",
    "phone_normalization": "+254 E.164",
    "id_comparison": {
        "NATIONAL_ID": "exact",
        "KRA_PIN": "exact",
    },
    "address_comparison": "token_sort_ratio",
    "address_threshold": 0.75,
    "blocking_keys": [
        "first_char_first_name",
        "first_char_last_name",
        "phone_last_4",
        "county",
    ],
}


# ═══════════════════════════════════════════════════════════════════════════════
# CONTEXT KEYWORDS
# ═══════════════════════════════════════════════════════════════════════════════

CONTEXT_KEYWORDS = {
    "NATIONAL_ID": [
        "national id", "id number", "id card", "identity card",
        "national identity", "iprs", "id no",
    ],
    "HUDUMA": [
        "huduma", "huduma namba", "niims", "huduma number",
    ],
    "KRA_PIN": [
        "kra", "kra pin", "tax pin", "kenya revenue",
        "tax identification", "pin certificate",
    ],
    "NHIF": [
        "nhif", "national hospital insurance", "health insurance fund",
        "nhif number",
    ],
}


# ═══════════════════════════════════════════════════════════════════════════════
# JURISDICTION PROFILE
# ═══════════════════════════════════════════════════════════════════════════════


def get_profile() -> JurisdictionProfileModel:
    """Return the complete Kenya jurisdiction profile."""
    return JurisdictionProfileModel(
        country_code="KE",
        country_name="Kenya",
        id_patterns=[
            {
                "id_type": "NATIONAL_ID",
                "description": "National Identity Card",
                "issuer": "IPRS",
                "format": "7-8 digits",
                "validator": "validate_national_id",
                "sensitivity": "high",
            },
            {
                "id_type": "HUDUMA",
                "description": "Huduma Namba (NIIMS)",
                "issuer": "NIIMS",
                "format": "alphanumeric 8-12 chars",
                "validator": "validate_huduma_namba",
                "sensitivity": "high",
            },
            {
                "id_type": "KRA_PIN",
                "description": "KRA Tax PIN",
                "issuer": "KRA",
                "format": "letter + 9 digits + letter",
                "validator": "validate_kra_pin",
                "sensitivity": "medium",
            },
            {
                "id_type": "NHIF",
                "description": "National Hospital Insurance Fund",
                "issuer": "NHIF",
                "format": "6-10 digits",
                "validator": "validate_nhif",
                "sensitivity": "medium",
            },
        ],
        phone_formats=[
            {
                "operator": operator,
                "prefixes": prefixes,
                "format": "07XX XXX XXX (local) / +254 7XX XXX XXX (international)",
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
    """Detect and validate Kenyan ID types in free text.

    Scans for KRA PIN patterns, National ID numbers with context,
    and other Kenyan identifiers.
    """
    results: list[ValidationResult] = []

    # KRA PIN pattern: letter + 9 digits + letter
    for m in re.finditer(r"(?<![A-Za-z])([A-Za-z]\d{9}[A-Za-z])(?![A-Za-z])", text):
        val = m.group(1)
        kra_result = validate_kra_pin(val)
        if kra_result.is_valid:
            context = text[max(0, m.start() - 80):min(len(text), m.end() + 80)].lower()
            if any(kw in context for kw in CONTEXT_KEYWORDS["KRA_PIN"]):
                kra_result.confidence = min(kra_result.confidence + 0.05, 1.0)
            results.append(kra_result)

    # National ID pattern: 7-8 digits with context
    for m in re.finditer(r"(?<![0-9])(\d{7,8})(?![0-9])", text):
        val = m.group(1)
        context = text[max(0, m.start() - 80):min(len(text), m.end() + 80)].lower()
        if any(kw in context for kw in CONTEXT_KEYWORDS["NATIONAL_ID"]):
            id_result = validate_national_id(val)
            if id_result.is_valid:
                id_result.confidence = min(id_result.confidence + 0.10, 1.0)
                results.append(id_result)

    return results
