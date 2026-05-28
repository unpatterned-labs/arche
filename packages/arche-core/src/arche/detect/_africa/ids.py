# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Multi-country African ID orchestrator and shared helpers.

The launch four jurisdictions (NG, KE, ZA, GH) live in their own per-country
modules per PRD §6.1:

    arche.detect.ng.ids   - Nigerian NIN, BVN, PVC (+ TIN, RC, driver's licence in Day 9)
    arche.detect.ke.ids   - Kenyan National ID (+ KRA PIN, NHIF, passport in Day 9)
    arche.detect.za.ids   - South African ID with Luhn + structural decode
    arche.detect.gh.ids   - Ghana Card (+ SSNIT, TIN in Day 9)

This module (``arche.detect._africa.ids``) hosts:

1. The ``NationalID`` dataclass (shared across countries)
2. Shared validator helpers (``_luhn_check``, ``_always_valid``)
3. Validators for the 11 non-launch African countries currently supported
   (RW, TZ, UG, ET, CI, SN, CM, EG, MA, AO, MZ)
4. The ``ID_PATTERNS`` registry composed from all per-country pattern dicts
5. The ``detect_african_ids`` multi-country orchestrator with priority-
   ordered pattern matching, contextual keyword boosting, and span
   deduplication

The shim at ``arche.african.ids`` re-exports from here so v0.1 imports
continue to work through the v0.2.x series.
"""

from __future__ import annotations

import re

# Shared dataclass + helpers live in detect._base to avoid a circular
# import with the per-country modules (which need NationalID before
# this module finishes loading).
from arche.detect._base import NationalID, _always_valid, _luhn_check  # noqa: F401


# ---------------------------------------------------------------------------
# Non-launch country validators
# ---------------------------------------------------------------------------

def _validate_egypt_id(text: str) -> tuple[bool, dict]:
    """Validate an Egyptian National ID (14 digits).

    Format: C YYMMDD SS GGGG K
    - C: century (2 = 1900s, 3 = 2000s)
    - YYMMDD: date of birth
    - SS: governorate code (01-35)
    - GGGG: sequence
    - K: check digit
    """
    digits = re.sub(r"\s+", "", text)
    if len(digits) != 14 or not digits.isdigit():
        return False, {}

    century_code = int(digits[0])
    yy, mm, dd = int(digits[1:3]), int(digits[3:5]), int(digits[5:7])
    governorate = int(digits[7:9])

    if century_code not in (2, 3):
        return False, {}
    if mm < 1 or mm > 12 or dd < 1 or dd > 31:
        return False, {}
    if governorate < 1 or governorate > 35:
        return False, {}

    century = 1900 if century_code == 2 else 2000
    year = century + yy

    return True, {
        "date_of_birth": f"{year:04d}-{mm:02d}-{dd:02d}",
        "governorate_code": f"{governorate:02d}",
    }


def _validate_rwanda_nid(text: str) -> tuple[bool, dict]:
    """Validate a Rwandan NID (16 digits starting with 1).

    Format: 1 YYYY MMDD SSSSSSS P CC
    Approximate — Rwanda NID encodes birth year and sequence.
    """
    digits = re.sub(r"\s+", "", text)
    if len(digits) != 16 or not digits.isdigit():
        return False, {}
    if digits[0] != "1":
        return False, {}

    yyyy = int(digits[1:5])
    if yyyy < 1900 or yyyy > 2030:
        return False, {}

    return True, {"birth_year": yyyy}


# ---------------------------------------------------------------------------
# Per-country pattern composition
# ---------------------------------------------------------------------------
# Import per-country pattern dicts AFTER NationalID + helpers are defined, so
# the per-country modules can safely `from arche.detect._africa.ids import
# NationalID, _luhn_check, _always_valid` at their module load time.

from arche.detect.ng.ids import NG_PATTERNS, _validate_bvn, _validate_nin  # noqa: E402,F401
from arche.detect.ke.ids import KE_PATTERNS  # noqa: E402
from arche.detect.za.ids import ZA_PATTERNS, _validate_sa_id  # noqa: E402,F401
from arche.detect.gh.ids import GH_PATTERNS, _validate_ghana_card  # noqa: E402,F401


# ---------------------------------------------------------------------------
# Non-launch African country patterns (11 countries)
# ---------------------------------------------------------------------------

OTHER_PATTERNS: dict[str, dict] = {
    "RW_NID": {
        "country": "RW",
        "id_type": "NID",
        "description": "Rwanda National ID — 16 digits starting with 1",
        "pattern": re.compile(
            r"(?<![0-9])(1\d{15})(?![0-9])"
        ),
        "validator": _validate_rwanda_nid,
        "base_confidence": 0.85,
    },
    "TZ_NIDA": {
        "country": "TZ",
        "id_type": "NIDA",
        "description": "Tanzania National ID (NIDA) — 20 digits",
        "pattern": re.compile(
            r"(?<![0-9])(\d{20})(?![0-9])"
        ),
        "validator": _always_valid,
        "base_confidence": 0.85,
    },
    "UG_NIN": {
        "country": "UG",
        "id_type": "NIN",
        "description": "Uganda National ID — CM/CF + alphanumeric (14 characters total)",
        "pattern": re.compile(
            r"(?<![A-Za-z0-9])(C[MF][A-Z0-9]{12})(?![A-Za-z0-9])"
        ),
        "validator": _always_valid,
        "base_confidence": 0.85,
    },
    "ET_KEBELE": {
        "country": "ET",
        "id_type": "KEBELE_ID",
        "description": "Ethiopia Kebele ID — varies by region, loose alphanumeric pattern",
        "pattern": re.compile(
            r"(?<![A-Za-z0-9])(ET[-/]?[A-Z]{2,4}[-/]?\d{4,10})(?![A-Za-z0-9])",
            re.IGNORECASE,
        ),
        "validator": _always_valid,
        "base_confidence": 0.50,
    },
    "CI_CNI": {
        "country": "CI",
        "id_type": "CNI",
        "description": "Cote d'Ivoire Carte Nationale d'Identite — C + digits",
        "pattern": re.compile(
            r"(?<![A-Za-z0-9])(C\d{9,14})(?![A-Za-z0-9])"
        ),
        "validator": _always_valid,
        "base_confidence": 0.70,
    },
    "SN_CNI": {
        "country": "SN",
        "id_type": "CNI",
        "description": "Senegal Carte Nationale d'Identite — 13 digits",
        "pattern": re.compile(
            r"(?<![0-9])([12]\d{12})(?![0-9])"
        ),
        "validator": _always_valid,
        "base_confidence": 0.65,
    },
    "CM_CNI": {
        "country": "CM",
        "id_type": "CNI",
        "description": "Cameroon Carte Nationale d'Identite — 9 digits",
        "pattern": re.compile(
            r"(?<![0-9])(\d{9})(?![0-9])"
        ),
        "validator": _always_valid,
        "base_confidence": 0.40,
    },
    "EG_NID": {
        "country": "EG",
        "id_type": "NATIONAL_ID",
        "description": "Egypt National ID — 14 digits with embedded DOB",
        "pattern": re.compile(
            r"(?<![0-9])([23]\d{13})(?![0-9])"
        ),
        "validator": _validate_egypt_id,
        "base_confidence": 0.88,
    },
    "MA_CNIE": {
        "country": "MA",
        "id_type": "CNIE",
        "description": "Morocco CNIE — 2 letters + 6 digits",
        "pattern": re.compile(
            r"(?<![A-Za-z0-9])([A-Z]{1,2}\d{5,7})(?![A-Za-z0-9])"
        ),
        "validator": _always_valid,
        "base_confidence": 0.60,
    },
    "AO_BI": {
        "country": "AO",
        "id_type": "BI",
        "description": "Angola Bilhete de Identidade — 9 digits + 2 letters",
        "pattern": re.compile(
            r"(?<![A-Za-z0-9])(\d{9}[A-Z]{2}\d)(?![A-Za-z0-9])"
        ),
        "validator": _always_valid,
        "base_confidence": 0.70,
    },
    "MZ_BI": {
        "country": "MZ",
        "id_type": "BI",
        "description": "Mozambique Bilhete de Identidade — 12 digits + letter",
        "pattern": re.compile(
            r"(?<![A-Za-z0-9])(\d{12}[A-Z])(?![A-Za-z0-9])"
        ),
        "validator": _always_valid,
        "base_confidence": 0.70,
    },
}


# Composed registry: launch four + 11 others = 17 country pattern entries.
ID_PATTERNS: dict[str, dict] = {
    **NG_PATTERNS,
    **KE_PATTERNS,
    **ZA_PATTERNS,
    **GH_PATTERNS,
    **OTHER_PATTERNS,
}


# ---------------------------------------------------------------------------
# Contextual keyword boosters
# ---------------------------------------------------------------------------

_CONTEXT_KEYWORDS: dict[str, list[str]] = {
    "NG": ["nin", "bvn", "national id", "bank verification", "voter card",
            "inec", "nimc", "nigeria"],
    "GH": ["ghana card", "national id", "nia", "ghana"],
    "KE": ["kenyan id", "national id", "huduma", "kenya"],
    "ZA": ["south african id", "id number", "sa id", "south africa"],
    "RW": ["rwanda", "nid", "national id"],
    "TZ": ["nida", "tanzania", "national id"],
    "UG": ["nira", "uganda", "national id"],
    "ET": ["kebele", "ethiopia", "fayda"],
    "CI": ["cni", "cote d'ivoire", "ivory coast", "carte nationale"],
    "SN": ["cni", "senegal", "carte nationale"],
    "CM": ["cni", "cameroon", "cameroun", "carte nationale"],
    "EG": ["egypt", "national id", "egyptian id"],
    "MA": ["cnie", "morocco", "moroccan", "carte nationale"],
    "AO": ["angola", "bilhete de identidade", "bi"],
    "MZ": ["mozambique", "bilhete de identidade", "bi"],
}

_CONTEXT_WINDOW = 80  # characters before/after match to scan for keywords


def _context_boost(text: str, start: int, end: int, country: str) -> float:
    """Return a confidence boost (0.0-0.15) if contextual keywords are nearby."""
    window_start = max(0, start - _CONTEXT_WINDOW)
    window_end = min(len(text), end + _CONTEXT_WINDOW)
    context = text[window_start:window_end].lower()

    keywords = _CONTEXT_KEYWORDS.get(country, [])
    for kw in keywords:
        if kw in context:
            return 0.15
    return 0.0


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def detect_african_ids(text: str) -> list[NationalID]:
    """Scan free text for African national ID patterns across all 15+ supported countries.

    Applies regex matching, structural validation (check digits where
    available), and contextual keyword boosting.

    For single-country detection, prefer the per-country helpers:

        from arche.detect.ng.ids import detect_nigerian_ids
        from arche.detect.za.ids import detect_south_african_ids

    Parameters
    ----------
    text:
        Input text to scan.

    Returns
    -------
    list[NationalID]
        All detected IDs, sorted by descending confidence.

    Examples
    --------
    >>> ids = detect_african_ids("His SA ID is 8001015009087 and NIN is 12345678901")
    >>> ids[0].country
    'ZA'
    >>> ids[0].metadata.get("gender")
    'male'
    """
    results: list[NationalID] = []
    seen_spans: set[tuple[int, int]] = set()

    # Process patterns in specificity order (more-specific / rarer first).
    # Order matters: a 13-digit SA ID would otherwise be partially matched by
    # the 10-digit ZA_TAX_REF pattern, etc. The span-deduplication logic
    # below skips any match overlapping a higher-priority span.
    priority_order = [
        # Highly specific alphanumeric formats first
        "GH_CARD", "GH_TIN", "GH_SSNIT",
        "KE_KRA_PIN",
        "NG_RC", "NG_DRIVERS", "NG_PVC",
        "ZA_PASSPORT",
        "UG_NIN", "ET_KEBELE", "AO_BI", "MZ_BI", "CI_CNI", "MA_CNIE",
        # Long-digit patterns (less ambiguous than short digits)
        "TZ_NIDA", "RW_NID", "EG_NID",
        "ZA_ID",  # 13 digits + Luhn — comes before shorter digit patterns
        "SN_CNI",
        # Constrained digit patterns (require specific prefix or length)
        "NG_BVN",  # 11 digits, must start with 22
        "ZA_TAX_REF",  # 10 digits, first digit in {0,1,2,3,9}
        "KE_NHIF",  # 8-9 digits
        # Bare-digit patterns (most ambiguous, last)
        "NG_TIN", "NG_NIN", "CM_CNI", "KE_ID",
    ]

    for key in priority_order:
        spec = ID_PATTERNS[key]
        for m in spec["pattern"].finditer(text):
            span = (m.start(1), m.end(1))

            # Skip if this span overlaps a higher-priority match.
            if any(_overlaps(span, s) for s in seen_spans):
                continue

            matched_text = m.group(1)
            is_valid, meta = spec["validator"](matched_text)

            if not is_valid and spec["validator"] is not _always_valid:
                continue

            confidence = spec["base_confidence"]
            if is_valid and spec["validator"] is not _always_valid:
                confidence = min(confidence + 0.05, 1.0)

            confidence += _context_boost(text, span[0], span[1], spec["country"])
            confidence = min(confidence, 1.0)

            results.append(NationalID(
                text=matched_text,
                country=spec["country"],
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
    """Return True if two (start, end) spans overlap."""
    return a[0] < b[1] and b[0] < a[1]
