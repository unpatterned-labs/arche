# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""South African identifier detectors - SA ID with Luhn check + DOB/gender/citizenship decode.

Per PRD §4.2 FR-DETECT-5. The SA ID Number is a 13-digit identifier with
structural decoding (date of birth, gender, citizenship) and a Luhn check.
Future expansion (Week 2): tax reference, passport.

Public API::

    from arche.detect.za.ids import detect_south_african_ids, ZA_PATTERNS
"""

from __future__ import annotations

import re

from arche.detect._base import NationalID, _luhn_check


def _validate_sa_id(text: str) -> tuple[bool, dict]:
    """Validate a South African ID Number (13 digits).

    Format: YYMMDD SSSS C A Z
    - YYMMDD: date of birth
    - SSSS:   gender (0000-4999 female, 5000-9999 male)
    - C:      citizenship (0 = SA citizen, 1 = permanent resident)
    - A:      historically race; now usually 8 or 9
    - Z:      Luhn check digit
    """
    digits = re.sub(r"\s+", "", text)
    if len(digits) != 13 or not digits.isdigit():
        return False, {}

    yy, mm, dd = int(digits[0:2]), int(digits[2:4]), int(digits[4:6])
    gender_code = int(digits[6:10])
    citizenship = int(digits[10])

    if mm < 1 or mm > 12 or dd < 1 or dd > 31:
        return False, {}

    if not _luhn_check(digits):
        return False, {}

    # SA IDs issued since ~2000 use 00-xx for the century.
    year = 1900 + yy if yy >= 30 else 2000 + yy

    return True, {
        "date_of_birth": f"{year:04d}-{mm:02d}-{dd:02d}",
        "gender": "female" if gender_code < 5000 else "male",
        "citizenship": "citizen" if citizenship == 0 else "permanent_resident",
    }


def _validate_za_tax_ref(text: str) -> tuple[bool, dict]:
    """South African Tax Reference Number - SARS-issued.

    Format: 10 digits, first digit typically 0, 1, 2, 3, or 9. Format-only
    validation; SARS does not publish a check-digit algorithm.
    """
    digits = re.sub(r"\s+", "", text)
    if not digits.isdigit() or len(digits) != 10:
        return False, {}
    if digits[0] not in "01239":
        return False, {}
    return True, {}


def _validate_za_passport(text: str) -> tuple[bool, dict]:
    """South African Passport - 1 letter + 8 digits.

    Issued by DHA. Format-only validation.
    """
    cleaned = text.upper().replace(" ", "")
    if not re.match(r"^[A-Z]\d{8}$", cleaned):
        return False, {}
    return True, {}


ZA_PATTERNS: dict[str, dict] = {
    "ZA_ID": {
        "country": "ZA",
        "id_type": "NATIONAL_ID",
        "description": "South Africa ID Number — 13 digits (YYMMDD SSSS C A Z) with Luhn check",
        "pattern": re.compile(
            r"(?<![0-9])(\d{13})(?![0-9])"
        ),
        "validator": _validate_sa_id,
        "base_confidence": 0.90,
    },
    "ZA_TAX_REF": {
        "country": "ZA",
        "id_type": "TAX_REFERENCE",
        "description": "South Africa Tax Reference Number — 10 digits (SARS)",
        "pattern": re.compile(
            r"(?<![0-9])([01239]\d{9})(?![0-9])"
        ),
        "validator": _validate_za_tax_ref,
        "base_confidence": 0.50,  # 10-digit sequences ambiguous without context
    },
    "ZA_PASSPORT": {
        "country": "ZA",
        "id_type": "PASSPORT",
        "description": "South Africa Passport — 1 letter + 8 digits (DHA)",
        "pattern": re.compile(
            r"(?<![A-Za-z0-9])([A-Z]\d{8})(?![A-Za-z0-9])"
        ),
        "validator": _validate_za_passport,
        "base_confidence": 0.75,
    },
}


def detect_south_african_ids(text: str) -> list[NationalID]:
    """Detect South African identifiers: SA ID, tax reference, passport."""
    results: list[NationalID] = []
    seen_spans: set[tuple[int, int]] = set()
    # SA ID (13 digits) is the most specific, so process it first.
    for key in ("ZA_ID", "ZA_PASSPORT", "ZA_TAX_REF"):
        spec = ZA_PATTERNS[key]
        for m in spec["pattern"].finditer(text):
            span = (m.start(1), m.end(1))
            if any(_overlaps(span, s) for s in seen_spans):
                continue
            matched_text = m.group(1)
            is_valid, meta = spec["validator"](matched_text)
            if not is_valid:
                continue
            confidence = min(spec["base_confidence"] + 0.05, 1.0)
            results.append(NationalID(
                text=matched_text,
                country="ZA",
                id_type=spec["id_type"],
                confidence=round(confidence, 4),
                start=span[0],
                end=span[1],
                metadata=meta,
            ))
            seen_spans.add(span)
    results.sort(key=lambda x: -x.confidence)
    return results


def _overlaps(a: tuple[int, int], b: tuple[int, int]) -> bool:
    return a[0] < b[1] and b[0] < a[1]
