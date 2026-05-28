# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Kenyan identifier detectors - National ID (Stage 1 base).

Per PRD §4.2 FR-DETECT-4. Future expansion (Day 9 / Week 2): KRA PIN,
NHIF, passport with per-identifier validators.

Public API::

    from arche.detect.ke.ids import detect_kenyan_ids, KE_PATTERNS
"""

from __future__ import annotations

import re

from arche.detect._base import NationalID, _always_valid


def _validate_kra_pin(text: str) -> tuple[bool, dict]:
    """Kenyan KRA PIN - tax identification number.

    Format: 11 characters - single letter prefix (typically A or P) + 9
    digits + single letter suffix. Examples: A000123456P, P051234567Z.
    Format-only validation.
    """
    cleaned = text.upper().replace(" ", "")
    match = re.match(r"^([AP])(\d{9})([A-Z])$", cleaned)
    if not match:
        return False, {}
    return True, {"taxpayer_type": "individual" if match.group(1) == "A" else "company"}


def _validate_nhif(text: str) -> tuple[bool, dict]:
    """Kenyan NHIF (National Hospital Insurance Fund) - 8 to 9 digits.

    Format-only validation.
    """
    digits = re.sub(r"\s+", "", text)
    if not digits.isdigit() or len(digits) not in (8, 9):
        return False, {}
    return True, {}


KE_PATTERNS: dict[str, dict] = {
    "KE_ID": {
        "country": "KE",
        "id_type": "NATIONAL_ID",
        "description": "Kenya National ID — 7 or 8 digits",
        "pattern": re.compile(
            r"(?<![0-9])(\d{7,8})(?![0-9])"
        ),
        "validator": _always_valid,
        "base_confidence": 0.40,  # short digit sequences are ambiguous
    },
    "KE_KRA_PIN": {
        "country": "KE",
        "id_type": "KRA_PIN",
        "description": "Kenya KRA PIN — A/P + 9 digits + letter (KRA tax ID)",
        "pattern": re.compile(
            r"(?<![A-Za-z0-9])([AP]\d{9}[A-Z])(?![A-Za-z0-9])",
            re.IGNORECASE,
        ),
        "validator": _validate_kra_pin,
        "base_confidence": 0.92,  # very specific format
    },
    "KE_NHIF": {
        "country": "KE",
        "id_type": "NHIF",
        "description": "Kenya NHIF (National Hospital Insurance Fund) — 8 or 9 digits",
        "pattern": re.compile(
            r"(?<![0-9])(\d{8,9})(?![0-9])"
        ),
        "validator": _validate_nhif,
        "base_confidence": 0.45,  # ambiguous without "NHIF" context
    },
}


def detect_kenyan_ids(text: str) -> list[NationalID]:
    """Detect Kenyan identifiers in text. Covers National ID, KRA PIN, NHIF."""
    results: list[NationalID] = []
    seen_spans: set[tuple[int, int]] = set()
    # Process more-specific patterns first so a KRA PIN isn't double-counted.
    for key in ("KE_KRA_PIN", "KE_NHIF", "KE_ID"):
        spec = KE_PATTERNS[key]
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
                country="KE",
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
