# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Ghanaian identifier detectors - Ghana Card (Stage 1 base).

Per PRD §4.2 FR-DETECT-7. Future expansion (Week 2): SSNIT, TIN.

Public API::

    from arche.detect.gh.ids import detect_ghanaian_ids, GH_PATTERNS
"""

from __future__ import annotations

import re

from arche.detect._base import NationalID


def _validate_ghana_card(text: str) -> tuple[bool, dict]:
    """Ghana Card - format GHA-NNNNNNNNN-N (9 digits + 1 check digit).

    Currently format-only validation. The NIA (National Identification
    Authority) does not publish the check-digit algorithm; this can be
    upgraded if/when the spec becomes available.
    """
    cleaned = text.upper().replace(" ", "")
    match = re.match(r"^GHA-(\d{9})-(\d)$", cleaned)
    if not match:
        return False, {}
    return True, {}


def _validate_ssnit(text: str) -> tuple[bool, dict]:
    """Ghanaian SSNIT - Social Security and National Insurance Trust number.

    Format: 13 characters. First character is a letter (issuance year code),
    followed by 12 alphanumeric characters. Format-only validation.
    """
    cleaned = text.upper().replace(" ", "")
    if not re.match(r"^[A-Z][A-Z0-9]{12}$", cleaned):
        return False, {}
    return True, {}


def _validate_gh_tin(text: str) -> tuple[bool, dict]:
    """Ghanaian TIN - Tax Identification Number issued by GRA.

    Format: 11 digits, first digit typically P, C, or G prefix variant.
    Modern format: P0000000001 (1 letter prefix + 10 digits). Format-only.
    """
    cleaned = text.upper().replace(" ", "")
    if re.match(r"^[PCG]\d{10}$", cleaned):
        return True, {"taxpayer_type": {"P": "individual", "C": "company", "G": "government"}.get(cleaned[0], "unknown")}
    if cleaned.isdigit() and len(cleaned) == 11:
        return True, {}
    return False, {}


GH_PATTERNS: dict[str, dict] = {
    "GH_CARD": {
        "country": "GH",
        "id_type": "GHANA_CARD",
        "description": "Ghana Card — GHA-NNNNNNNNN-N (NIA-issued)",
        "pattern": re.compile(
            r"(?<![A-Za-z0-9])(GHA-\d{9}-\d)(?![A-Za-z0-9])",
            re.IGNORECASE,
        ),
        "validator": _validate_ghana_card,
        "base_confidence": 0.95,
    },
    "GH_SSNIT": {
        "country": "GH",
        "id_type": "SSNIT",
        "description": "Ghana SSNIT — 1 letter + 12 alphanumeric (Social Security)",
        "pattern": re.compile(
            r"(?<![A-Za-z0-9])([A-Z][A-Z0-9]{12})(?![A-Za-z0-9])"
        ),
        "validator": _validate_ssnit,
        "base_confidence": 0.65,
    },
    "GH_TIN": {
        "country": "GH",
        "id_type": "TIN",
        "description": "Ghana Tax Identification Number — P/C/G + 10 digits or 11 digits (GRA)",
        "pattern": re.compile(
            r"(?<![A-Za-z0-9])([PCG]\d{10})(?![A-Za-z0-9])",
            re.IGNORECASE,
        ),
        "validator": _validate_gh_tin,
        "base_confidence": 0.85,  # P/C/G prefix is fairly specific
    },
}


def detect_ghanaian_ids(text: str) -> list[NationalID]:
    """Detect Ghanaian identifiers: Ghana Card, SSNIT, TIN."""
    results: list[NationalID] = []
    seen_spans: set[tuple[int, int]] = set()
    # Process most-specific patterns first.
    for key in ("GH_CARD", "GH_TIN", "GH_SSNIT"):
        spec = GH_PATTERNS[key]
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
                country="GH",
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
