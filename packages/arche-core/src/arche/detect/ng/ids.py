# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Nigerian identifier detectors - NIN, BVN, PVC (Stage 1 base).

Per PRD §4.2 FR-DETECT-1..3. Future expansion (Day 9 / Week 2): TIN, RC,
driver's licence + check-digit validators per the NIMC / NIBSS specs.

Public API::

    from arche.detect.ng.ids import detect_nigerian_ids, NG_PATTERNS

    ids = detect_nigerian_ids("My NIN is 12345678901 and BVN is 22156789012")
    # -> list[NationalID]

Private validators:

    _validate_bvn   — 11 digits, prefix "22" (NIBSS-issued)
    _validate_nin   — 11 digits, NIMC-issued (currently format-only;
                       check-digit algorithm is not publicly documented)
"""

from __future__ import annotations

import re

from arche.detect._base import NationalID, _always_valid


def _validate_bvn(text: str) -> tuple[bool, dict]:
    """Nigerian BVN - 11 digits, first two are 22 (NIBSS-issued prefix)."""
    digits = re.sub(r"\s+", "", text)
    if len(digits) != 11 or not digits.isdigit():
        return False, {}
    if not digits.startswith("22"):
        return False, {}
    return True, {}


def _validate_nin(text: str) -> tuple[bool, dict]:
    """Nigerian NIN - 11 digits, NIMC-issued.

    Currently format-only validation: 11 digits, all numeric. The NIMC
    check-digit algorithm is not publicly documented at the time of v0.2.
    If/when NIMC publishes the spec, swap in the proper check here.
    """
    digits = re.sub(r"\s+", "", text)
    if len(digits) != 11 or not digits.isdigit():
        return False, {}
    return True, {}


def _validate_ng_tin(text: str) -> tuple[bool, dict]:
    """Nigerian TIN - FIRS-issued tax identification number.

    Format: 10 digits, optionally followed by "-0001" branch suffix.
    Validation is format-only (FIRS does not publish a check-digit spec).
    """
    cleaned = re.sub(r"[\s-]", "", text)
    if not cleaned.isdigit() or len(cleaned) not in (10, 14):
        return False, {}
    return True, {}


def _validate_ng_rc(text: str) -> tuple[bool, dict]:
    """Nigerian Company Registration Number - CAC-issued.

    Format: "RC" or "BN" prefix + 5 to 8 digits. RC = limited liability,
    BN = business name. Validation is format-only.
    """
    cleaned = text.upper().replace(" ", "")
    match = re.match(r"^(RC|BN)(\d{5,8})$", cleaned)
    if not match:
        return False, {}
    return True, {"entity_type": "limited_liability" if match.group(1) == "RC" else "business_name"}


def _validate_ng_drivers_licence(text: str) -> tuple[bool, dict]:
    """Nigerian Driver's Licence - FRSC-issued.

    Format: 3-letter state code + dash + 10-12 digits (e.g., "AAA-12345678901").
    Format-only validation. The dash separator is now mandatory in the regex
    to avoid false positives from common 3-letter context words (BVN, NIN, TIN).
    """
    cleaned = text.upper().replace(" ", "")
    if not re.match(r"^[A-Z]{3}-\d{10,12}$", cleaned):
        return False, {}
    return True, {"state_code": cleaned[:3]}


NG_PATTERNS: dict[str, dict] = {
    "NG_NIN": {
        "country": "NG",
        "id_type": "NIN",
        "description": "Nigeria National Identification Number — 11 digits, NIMC-issued",
        "pattern": re.compile(
            r"(?<![0-9])(\d{11})(?![0-9])"
        ),
        "validator": _validate_nin,
        "base_confidence": 0.55,  # 11 digits alone are ambiguous
    },
    "NG_BVN": {
        "country": "NG",
        "id_type": "BVN",
        "description": "Nigeria Bank Verification Number — 11 digits starting with 22, NIBSS-issued",
        "pattern": re.compile(
            r"(?<![0-9])(22\d{9})(?![0-9])"
        ),
        "validator": _validate_bvn,
        "base_confidence": 0.80,
    },
    "NG_PVC": {
        "country": "NG",
        "id_type": "PVC",
        "description": "Nigeria Permanent Voter Card — 19-char alphanumeric (INEC)",
        "pattern": re.compile(
            r"(?<![A-Za-z0-9])"
            r"(\d{2}\s?[A-Z0-9]{2}\s?[A-Z0-9]{2}\s?[A-Z0-9]{2}\s?\d{4}\s?\d{3}\s?\d{4})"
            r"(?![A-Za-z0-9])",
            re.IGNORECASE,
        ),
        "validator": _always_valid,
        "base_confidence": 0.60,
    },
    "NG_TIN": {
        "country": "NG",
        "id_type": "TIN",
        "description": "Nigeria Tax Identification Number — 10 digits (FIRS), optional -0001 branch suffix",
        "pattern": re.compile(
            r"(?<![0-9])(\d{10}(?:-\d{4})?)(?![0-9])"
        ),
        "validator": _validate_ng_tin,
        "base_confidence": 0.50,  # 10-digit sequences are ambiguous without context
    },
    "NG_RC": {
        "country": "NG",
        "id_type": "RC",
        "description": "Nigeria Company Registration Number — RC/BN + 5-8 digits (CAC)",
        "pattern": re.compile(
            r"(?<![A-Za-z0-9])((?:RC|BN)\s?\d{5,8})(?![A-Za-z0-9])",
            re.IGNORECASE,
        ),
        "validator": _validate_ng_rc,
        "base_confidence": 0.90,  # "RC" prefix is highly specific
    },
    "NG_DRIVERS": {
        "country": "NG",
        "id_type": "DRIVERS_LICENCE",
        "description": "Nigeria Driver's Licence — 3-letter state code + dash + 10-12 digits (FRSC)",
        # Mandatory dash separator avoids false positives from any
        # 3-letter context word ("BVN 22100987654", "NIN 12345678901", etc.).
        "pattern": re.compile(
            r"(?<![A-Za-z0-9])([A-Z]{3}-\d{10,12})(?![A-Za-z0-9])"
        ),
        "validator": _validate_ng_drivers_licence,
        "base_confidence": 0.85,  # dash + 3-letter prefix is fairly specific
    },
}


def detect_nigerian_ids(text: str) -> list[NationalID]:
    """Detect Nigerian identifiers (NIN, BVN, PVC) in text.

    Scans only NG patterns - faster than the multi-country
    ``detect_african_ids`` orchestrator when you already know you're
    processing Nigerian data.

    For multi-country detection, use ``arche.detect._africa.ids.detect_african_ids``.
    """
    results: list[NationalID] = []
    seen_spans: set[tuple[int, int]] = set()

    # Process the more-specific patterns first so a BVN isn't double-counted
    # as a NIN, and the alphanumeric RC/DL/PVC patterns are tried before the
    # bare-digit NIN/BVN/TIN patterns.
    for key in ("NG_RC", "NG_DRIVERS", "NG_PVC", "NG_BVN", "NG_TIN", "NG_NIN"):
        spec = NG_PATTERNS[key]
        for m in spec["pattern"].finditer(text):
            span = (m.start(1), m.end(1))
            if any(_overlaps(span, s) for s in seen_spans):
                continue
            matched_text = m.group(1)
            is_valid, meta = spec["validator"](matched_text)
            if not is_valid and spec["validator"] is not _always_valid:
                continue
            confidence = spec["base_confidence"]
            if is_valid and spec["validator"] is not _always_valid:
                confidence = min(confidence + 0.05, 1.0)
            results.append(NationalID(
                text=matched_text,
                country="NG",
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
