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

"""South Africa Identity Pack — complete jurisdiction profile.

Covers:
- SA ID Number (13 digits with Luhn check, embedded DOB/gender/citizenship)
- Tax number (10 digits, SARS)
- Phone formats: Vodacom, MTN, Cell C, Telkom prefix ranges
- Naming: Zulu, Xhosa, Sotho, Tswana, Afrikaans conventions
- POPIA (Protection of Personal Information Act 2013) compliance

Usage:
    from arche.jurisdictions.south_africa import get_profile, validate_sa_id
    profile = get_profile()
    result = validate_sa_id("8001015009087")
"""

from __future__ import annotations  # noqa: I001

import re

from ..models import JurisdictionProfileModel
from .nigeria import ValidationResult


# ═══════════════════════════════════════════════════════════════════════════════
# LUHN CHECK (reused from african/ids.py logic)
# ═══════════════════════════════════════════════════════════════════════════════


def _luhn_check(digits: str) -> bool:
    """Validate a digit string using the Luhn algorithm (mod 10).

    This is the same algorithm used in the african/ids.py module,
    replicated here so the jurisdiction pack is self-contained.
    """
    total = 0
    for i, ch in enumerate(reversed(digits)):
        n = int(ch)
        if i % 2 == 1:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return total % 10 == 0


# ═══════════════════════════════════════════════════════════════════════════════
# ID VALIDATORS
# ═══════════════════════════════════════════════════════════════════════════════


def validate_sa_id(value: str) -> ValidationResult:
    """Validate a South African ID Number.

    Format: YYMMDD SSSS C A Z (13 digits total)
    - YYMMDD: date of birth
    - SSSS: gender (0000-4999 = female, 5000-9999 = male)
    - C: citizenship (0 = SA citizen, 1 = permanent resident)
    - A: was used for race classification, now usually 8 or 9
    - Z: Luhn check digit

    Issued by the Department of Home Affairs (DHA).
    """
    digits = re.sub(r"[\s\-]+", "", value)
    if len(digits) != 13 or not digits.isdigit():
        return ValidationResult(False, "SA_ID", 0.0, {})

    yy = int(digits[0:2])
    mm = int(digits[2:4])
    dd = int(digits[4:6])
    gender_code = int(digits[6:10])
    citizenship = int(digits[10])

    # Basic date validation
    if mm < 1 or mm > 12 or dd < 1 or dd > 31:
        return ValidationResult(False, "SA_ID", 0.0, {"note": "Invalid date of birth"})

    # Citizenship digit must be 0 or 1
    if citizenship not in (0, 1):
        return ValidationResult(False, "SA_ID", 0.0, {"note": "Invalid citizenship digit"})

    # Luhn check
    if not _luhn_check(digits):
        return ValidationResult(False, "SA_ID", 0.0, {"note": "Luhn check failed"})

    # Determine century
    year = 1900 + yy if yy >= 30 else 2000 + yy

    return ValidationResult(True, "SA_ID", 0.95, {
        "issuer": "DHA",
        "format": "13-digit with Luhn",
        "date_of_birth": f"{year:04d}-{mm:02d}-{dd:02d}",
        "gender": "female" if gender_code < 5000 else "male",
        "citizenship": "citizen" if citizenship == 0 else "permanent_resident",
    })


def validate_tax_number(value: str) -> ValidationResult:
    """Validate a South African Tax Number.

    Rules:
    - 10 digits
    - Issued by SARS (South African Revenue Service)
    - First digit typically indicates taxpayer type
    """
    digits = re.sub(r"[\s\-]+", "", value)
    if len(digits) != 10 or not digits.isdigit():
        return ValidationResult(False, "TAX_NUMBER", 0.0, {})

    return ValidationResult(True, "TAX_NUMBER", 0.80, {
        "issuer": "SARS",
        "format": "10-digit",
    })


# ═══════════════════════════════════════════════════════════════════════════════
# PHONE FORMATS
# ═══════════════════════════════════════════════════════════════════════════════

# South African mobile network operators and their prefix allocations (3-digit after 0)
NETWORK_PREFIXES: dict[str, list[str]] = {
    "Vodacom": [
        "060", "061", "062", "063", "064", "065", "066",
        "071", "072", "073", "082",
    ],
    "MTN": [
        "063", "064", "065", "066", "067",
        "071", "073", "078", "083",
    ],
    "Cell C": [
        "074", "084",
    ],
    "Telkom": [
        "081",
    ],
}

# Flat lookup: prefix -> operator
# Note: Some prefixes are shared between Vodacom and MTN due to number portability
# and NPA allocation overlaps. We assign to the historically primary operator.
_PREFIX_TO_OPERATOR: dict[str, str] = {}
# Load in order: Vodacom first, then MTN (MTN overwrites shared prefixes),
# then Cell C and Telkom
for _op in ["Vodacom", "MTN", "Cell C", "Telkom"]:
    for _p in NETWORK_PREFIXES[_op]:
        _PREFIX_TO_OPERATOR[_p] = _op


def identify_network(phone: str) -> str | None:
    """Identify the South African mobile network operator from a phone number.

    Parameters
    ----------
    phone:
        Phone number in local (0XX...) or international (+27 XX...) format.

    Returns
    -------
    str or None
        Operator name (Vodacom, MTN, Cell C, Telkom) or None if unrecognized.

    Note
    ----
    Due to number portability, a number's *current* operator may differ from
    what the prefix suggests. This function returns the *original* allocation.
    Some prefixes (060-066, 071, 073) are shared between Vodacom and MTN.
    """
    cleaned = re.sub(r"[\s\-\(\)\+]+", "", phone)

    # Convert international to local
    if cleaned.startswith("27") and len(cleaned) >= 11:
        cleaned = "0" + cleaned[2:]

    prefix = cleaned[:3]
    return _PREFIX_TO_OPERATOR.get(prefix)


def normalize_phone(phone: str) -> str | None:
    """Normalize a South African phone number to E.164 format (+27XXXXXXXXX).

    SA mobile numbers are 10 digits local (0XX XXX XXXX) or
    11 digits international (27 XX XXX XXXX).

    Returns None if the number doesn't look like a valid SA mobile number.
    """
    cleaned = re.sub(r"[\s\-\(\)\.]+", "", phone)

    # Already international with +
    if cleaned.startswith("+27"):
        digits = cleaned[1:]  # remove +
    elif cleaned.startswith("27") and len(cleaned) >= 11:
        digits = cleaned
    elif cleaned.startswith("0") and len(cleaned) == 10:
        digits = "27" + cleaned[1:]
    else:
        return None

    if len(digits) != 11 or not digits.isdigit():
        return None

    # Verify it's a known prefix
    local_prefix = "0" + digits[2:4]
    if local_prefix[:3] not in _PREFIX_TO_OPERATOR:
        return None

    return "+" + digits


# ═══════════════════════════════════════════════════════════════════════════════
# NAMING CONVENTIONS
# ═══════════════════════════════════════════════════════════════════════════════

NAMING_CONVENTIONS = [
    {
        "tradition": "Zulu",
        "region": "KwaZulu-Natal",
        "conventions": [
            "Patronymic: clan name (isibongo) is primary surname",
            "Praise-names (izithakazelo) used in formal address",
            "Given name often reflects circumstances of birth",
            "Prefix meanings: Nku-/Nkosi- (chief), Si-/Sbu- (blessing/gift)",
            "Name order: [Given name] [Surname/Clan name]",
            "Multiple names common: English name + Zulu name + clan name",
        ],
        "common_prefixes": ["Nku", "Nkosi", "Si", "Sbu", "Mzu", "Tha"],
        "common_surnames": [
            "Zulu", "Dlamini", "Nkosi", "Mkhize", "Ndlovu",
            "Buthelezi", "Zwane", "Cele", "Ngcobo", "Khumalo",
        ],
    },
    {
        "tradition": "Xhosa",
        "region": "Eastern Cape, Western Cape",
        "conventions": [
            "Clan name (isiduko) is the primary surname",
            "Praise-names (iziduko) used in formal contexts",
            "Birth-order and circumstantial names common",
            "Prefix meanings: No- (mother of), Ma- (feminine prefix)",
            "Circumcision name given to males at initiation",
            "Name order: [Given name] [Clan name]",
        ],
        "common_prefixes": ["No", "Ma", "Noma", "Tha", "Lun"],
        "common_surnames": [
            "Mandela", "Sigcau", "Hani", "Mbeki", "Madikizela",
            "Tambo", "Sisulu", "Xaba", "Mda", "Jola",
        ],
    },
    {
        "tradition": "Sotho",
        "region": "Free State, Gauteng",
        "conventions": [
            "Patronymic: father's name or clan name as surname",
            "Praise-names (seboko) important in formal address",
            "Birth-order names common (e.g. Thabiso = joy)",
            "Totem-based clan names (e.g. Tau = lion, Phiri = hyena)",
            "Christian/English name + Sotho name + surname",
        ],
        "common_prefixes": ["Mo", "Ma", "Le", "Tse"],
        "common_surnames": [
            "Mokoena", "Molefe", "Nkosi", "Motsepe", "Letsie",
            "Moshoeshoe", "Ramaphosa", "Sello", "Maseko", "Tau",
        ],
    },
    {
        "tradition": "Tswana",
        "region": "North West, Gauteng, Northern Cape",
        "conventions": [
            "Patronymic: father's or grandfather's name as surname",
            "Totem-based naming (e.g. Phiri, Tau, Kwena)",
            "Birth circumstance names reflect events at birth",
            "Setswana prefix meanings: Mo- (person), Ba- (people)",
            "Traditional names often paired with English names",
        ],
        "common_prefixes": ["Mo", "Ba", "Ke", "Tse"],
        "common_surnames": [
            "Modise", "Mogale", "Phiri", "Moloi", "Motlanthe",
            "Pilane", "Montshiwa", "Sebego", "Kgositsile", "Moroka",
        ],
    },
    {
        "tradition": "Afrikaans",
        "region": "Western Cape, Northern Cape, Free State",
        "conventions": [
            "Dutch-origin naming: patronymic surnames (van der, du, de)",
            "Compound surnames common (e.g. Van der Merwe, Du Plessis)",
            "Diminutives common (e.g. -tjie, -kie suffixes for given names)",
            "Family names often include farm or place of origin",
            "Name order: [Voornaam] [Van] [Surname]",
        ],
        "common_prefixes": ["Van", "Du", "De", "Le"],
        "common_surnames": [
            "Van der Merwe", "Botha", "Du Plessis", "Joubert", "Pretorius",
            "Van Niekerk", "Kruger", "Venter", "Steyn", "Nel",
        ],
    },
]


# ═══════════════════════════════════════════════════════════════════════════════
# ADDRESS CONVENTIONS
# ═══════════════════════════════════════════════════════════════════════════════

ADDRESS_NORMS = {
    "format": "[Unit/Complex], [Street Number] [Street Name], [Suburb], [City], [Province] [Postal Code]",
    "provinces": [
        "Eastern Cape", "Free State", "Gauteng", "KwaZulu-Natal",
        "Limpopo", "Mpumalanga", "Northern Cape", "North West",
        "Western Cape",
    ],
    "major_cities": [
        "Johannesburg", "Cape Town", "Durban", "Pretoria", "Port Elizabeth",
        "Bloemfontein", "East London", "Pietermaritzburg", "Polokwane",
        "Nelspruit", "Kimberley", "Rustenburg", "Soweto", "Sandton",
        "Centurion",
    ],
    "postal_code_format": "4 digits (NNNN), area-based",
}


# ═══════════════════════════════════════════════════════════════════════════════
# POPIA COMPLIANCE (Protection of Personal Information Act 2013)
# ═══════════════════════════════════════════════════════════════════════════════

POPIA_COMPLIANCE = {
    "law": "Protection of Personal Information Act 2013 (POPIA, Act 4 of 2013)",
    "regulator": "Information Regulator South Africa",
    "effective_date": "2013-11-26",
    "enforcement_date": "2021-07-01",
    "key_requirements": {
        "consent": "Explicit, voluntary, specific consent required for processing",
        "lawful_basis": [
            "consent",
            "contract",
            "legal_obligation",
            "legitimate_interests",
            "public_law_duty",
            "protection_of_legitimate_interests_of_data_subject",
        ],
        "data_subject_rights": [
            "right_of_access",
            "right_to_rectification",
            "right_to_erasure",
            "right_to_restrict_processing",
            "right_to_object",
            "right_to_object_to_direct_marketing",
            "right_not_to_be_subject_to_automated_decisions",
            "right_to_complain_to_regulator",
        ],
        "cross_border_transfer": (
            "Permitted only to recipients subject to laws providing "
            "adequate protection, binding corporate rules, or consent"
        ),
        "breach_notification": (
            "Notify Information Regulator and data subjects as soon as "
            "reasonably possible after discovery"
        ),
        "impact_assessment": "Required for processing of special personal information",
        "information_officer": "Every responsible party must appoint an Information Officer",
    },
    "pii_categories": {
        "high_sensitivity": [
            "SA_ID", "biometric_data", "health_data",
            "genetic_data", "criminal_records", "children_data",
            "religious_belief", "political_opinion", "trade_union_membership",
            "sexual_orientation",
        ],
        "medium_sensitivity": [
            "tax_number", "phone_number", "email",
            "address", "date_of_birth", "bank_account",
            "employment_data",
        ],
        "low_sensitivity": [
            "full_name", "gender", "province", "occupation",
        ],
    },
    "retention_limits": {
        "default": "Only as long as necessary for the purpose, or as required by law",
        "financial_records": "5 years (SARS requirement)",
        "employment_records": "As required by Basic Conditions of Employment Act",
        "health_records": "As required by National Health Act",
    },
    "penalties": {
        "administrative_fine": "Up to ZAR 10 million",
        "imprisonment": "Up to 10 years for certain offences (e.g. obstruction)",
        "civil_damages": "Data subjects may claim damages for breach",
        "note": "Information Regulator can issue enforcement notices, infringement notices",
    },
}


# ═══════════════════════════════════════════════════════════════════════════════
# RESOLUTION DEFAULTS
# ═══════════════════════════════════════════════════════════════════════════════

RESOLUTION_DEFAULTS = {
    "name_comparison": "jaro_winkler",
    "name_threshold": 0.85,
    "use_cultural_naming": True,
    "cultural_naming_traditions": ["zulu", "xhosa", "sotho", "tswana", "afrikaans"],
    "phone_comparison": "exact_after_normalization",
    "phone_normalization": "+27 E.164",
    "id_comparison": {
        "SA_ID": "exact",
        "TAX_NUMBER": "exact",
    },
    "address_comparison": "token_sort_ratio",
    "address_threshold": 0.75,
    "blocking_keys": [
        "first_char_first_name",
        "first_char_last_name",
        "phone_last_4",
        "province",
    ],
}


# ═══════════════════════════════════════════════════════════════════════════════
# CONTEXT KEYWORDS
# ═══════════════════════════════════════════════════════════════════════════════

CONTEXT_KEYWORDS = {
    "SA_ID": [
        "id number", "identity number", "sa id", "south african id",
        "id no", "identity document", "id book", "smart card",
        "home affairs", "dha",
    ],
    "TAX_NUMBER": [
        "tax number", "tax no", "sars", "tax reference",
        "south african revenue", "income tax",
    ],
}


# ═══════════════════════════════════════════════════════════════════════════════
# JURISDICTION PROFILE
# ═══════════════════════════════════════════════════════════════════════════════


def get_profile() -> JurisdictionProfileModel:
    """Return the complete South Africa jurisdiction profile."""
    return JurisdictionProfileModel(
        country_code="ZA",
        country_name="South Africa",
        id_patterns=[
            {
                "id_type": "SA_ID",
                "description": "South African ID Number",
                "issuer": "DHA",
                "format": "13 digits (YYMMDD SSSS C A Z) with Luhn check",
                "validator": "validate_sa_id",
                "sensitivity": "high",
            },
            {
                "id_type": "TAX_NUMBER",
                "description": "SARS Tax Number",
                "issuer": "SARS",
                "format": "10 digits",
                "validator": "validate_tax_number",
                "sensitivity": "medium",
            },
        ],
        phone_formats=[
            {
                "operator": operator,
                "prefixes": prefixes,
                "format": "0XX XXX XXXX (local) / +27 XX XXX XXXX (international)",
                "local_length": 10,
                "intl_length": 11,
            }
            for operator, prefixes in NETWORK_PREFIXES.items()
        ],
        naming_conventions=NAMING_CONVENTIONS,
        address_norms=ADDRESS_NORMS,
        compliance_metadata=POPIA_COMPLIANCE,
        version="0.1.0",
    )


def detect_ids(text: str) -> list[ValidationResult]:
    """Detect and validate South African ID types in free text.

    Scans for 13-digit SA ID numbers with Luhn validation,
    and 10-digit tax numbers with context keyword boosting.
    """
    results: list[ValidationResult] = []

    # SA ID pattern: 13 digits
    for m in re.finditer(r"(?<![0-9])(\d{13})(?![0-9])", text):
        val = m.group(1)
        id_result = validate_sa_id(val)
        if id_result.is_valid:
            context = text[max(0, m.start() - 80):min(len(text), m.end() + 80)].lower()
            if any(kw in context for kw in CONTEXT_KEYWORDS["SA_ID"]):
                id_result.confidence = min(id_result.confidence + 0.05, 1.0)
            results.append(id_result)

    # Tax number: 10 digits with context
    for m in re.finditer(r"(?<![0-9])(\d{10})(?![0-9])", text):
        val = m.group(1)
        context = text[max(0, m.start() - 80):min(len(text), m.end() + 80)].lower()
        if any(kw in context for kw in CONTEXT_KEYWORDS["TAX_NUMBER"]):
            tax_result = validate_tax_number(val)
            if tax_result.is_valid:
                tax_result.confidence = min(tax_result.confidence + 0.10, 1.0)
                results.append(tax_result)

    return results
