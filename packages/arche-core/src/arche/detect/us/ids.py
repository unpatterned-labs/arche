# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""United States identifier detectors: SSN, ITIN, EIN and NPI.

All four are nine or ten digits, which is also the shape of an order number,
an invoice number and a bank account. So the rule is the one the ZA tax
reference and the KE Huduma Namba already follow: **a bare digit run carries
no evidence of being an identifier; a label before it does.**

* **SSN** ``NNN-NN-NNNN`` (dashed or spaced) is accepted on its own; the bare
  nine digits only after "SSN" or "social security". Structure per SSA: area
  ``000``, ``666`` and ``900``-``999`` are never issued, nor group ``00`` or
  serial ``0000``; the Woolworth wallet-card number ``078-05-1120`` and the
  advertising number ``219-09-9999`` are rejected by name.
* **ITIN** is SSN-shaped with area ``9xx`` and group ``50``-``65``, ``70``-``88``,
  ``90``-``92`` or ``94``-``99`` (IRS). Same label rule as the SSN.
* **EIN** ``NN-NNNNNNN`` with a prefix the IRS lists as assigned; the bare nine
  digits only after "EIN", "employer identification" or "tax ID".
* **NPI** ten digits starting 1 or 2 whose Luhn check holds over ``80840`` plus
  the number (CMS). Always label-anchored ("NPI", "national provider"): a
  checksum alone passes one random ten-digit run in ten.

None of these check digits or ranges says a number was *issued*; they say it
is well-formed. That is integrity, not authenticity (see ``_checksum``).

Public API::

    from arche.detect.us.ids import detect_us_ids, US_PATTERNS
"""

from __future__ import annotations

import re

from arche.detect._base import NationalID, _status_meta
from arche.detect._checksum import luhn

#: Never-issued numbers that are otherwise well-formed: the 1938 Woolworth
#: wallet-insert number and the SSA's own advertising number.
_INVALID_SSNS = frozenset({"078051120", "219099999"})

#: IRS-assigned EIN prefixes, by campus, from
#: https://www.irs.gov/businesses/small-businesses-self-employed/how-eins-are-assigned-and-valid-ein-prefixes
#: (read 2026-11-20). The union of every campus, internet and SBA list.
_EIN_PREFIXES = frozenset(
    f"{n:02d}" for n in (
        *range(1, 7), *range(10, 17), *range(20, 28), *range(30, 49),
        *range(50, 69), *range(71, 78), *range(80, 89), *range(90, 96), 98, 99,
    )
)

#: ITIN group (middle two digits) ranges the IRS issues.
_ITIN_GROUPS = frozenset(
    (*range(50, 66), *range(70, 89), *range(90, 93), *range(94, 100))
)


def _digits(text: str) -> str:
    return re.sub(r"[\s-]", "", text)


def _validate_us_ssn(text: str) -> tuple[bool, dict]:
    """A US Social Security Number: structural SSA rules, no check digit."""
    d = _digits(text)
    if len(d) != 9 or not d.isdigit():
        return False, {}
    area, group, serial = d[:3], d[3:5], d[5:]
    if area in ("000", "666") or area[0] == "9":
        return False, {}
    if group == "00" or serial == "0000" or d in _INVALID_SSNS:
        return False, {}
    return True, {}


def _validate_us_itin(text: str) -> tuple[bool, dict]:
    """An IRS Individual Taxpayer Identification Number: 9xx-GG-NNNN."""
    d = _digits(text)
    if len(d) != 9 or not d.isdigit() or d[0] != "9":
        return False, {}
    return int(d[3:5]) in _ITIN_GROUPS, {}


def _validate_us_ein(text: str) -> tuple[bool, dict]:
    """An IRS Employer Identification Number: an assigned two-digit prefix + 7 digits."""
    d = _digits(text)
    if len(d) != 9 or not d.isdigit():
        return False, {}
    return d[:2] in _EIN_PREFIXES, {}


def _validate_us_npi(text: str) -> tuple[bool, dict]:
    """A CMS National Provider Identifier: Luhn over ``80840`` + the ten digits."""
    d = _digits(text)
    if len(d) != 10 or not d.isdigit() or d[0] not in "12":
        return False, {}
    return luhn("80840" + d), {}


def _cue(words: str) -> re.Pattern[str]:
    """A label that must end within 25 non-digit characters of the number."""
    return re.compile(rf"\b(?:{words})(?![a-z])[^0-9\n]{{0,25}}$", re.IGNORECASE)


_SSN_WORDS = r"ssn|ss\s?#|soc(?:ial)?\.?\s*sec(?:urity)?(?:\s*(?:number|no|num))?"
_SSN_CUE = _cue(_SSN_WORDS)
_ITIN_CUE = _cue(
    r"itin|individual\s+taxpayer(?:\s+identification)?|taxpayer\s+id(?:entification)?|tin|"
    + _SSN_WORDS
)
_EIN_CUE = _cue(
    r"f?ein|employer\s+id(?:entification)?|federal\s+tax\s+id|tax\s+id(?:entification)?"
)
_NPI_CUE = _cue(r"npi|national\s+provider(?:\s+id(?:entifier)?)?")

# NNN-NN-NNNN with one consistent separator ("-", " " or none). Group 2 is the
# separator, so the caller can tell a formatted number from a bare run.
_SSN_SHAPE = re.compile(r"(?<![\d-])(\d{3}([- ]?)\d{2}\2\d{4})(?![\d-])")

#: ``cue``: the label regex; ``cue_required``: ``"always"``, or ``"bare"``
#: when a formatted number stands on its own and only a bare run needs a label.
US_PATTERNS: dict[str, dict] = {
    "US_NPI": {
        "country": "US",
        "id_type": "NPI",
        "description": "US National Provider Identifier: 10 digits, Luhn over 80840+NPI",
        "pattern": re.compile(r"(?<![\d-])([12]\d{9})(?![\d-])"),
        "validator": _validate_us_npi,
        "checksum": "luhn",
        "cue": _NPI_CUE,
        "cue_required": "always",
        "base_confidence": 0.90,
    },
    "US_SSN": {
        "country": "US",
        "id_type": "SSN",
        "description": "US Social Security Number: NNN-NN-NNNN (SSA structural rules)",
        "pattern": _SSN_SHAPE,
        "validator": _validate_us_ssn,
        "cue": _SSN_CUE,
        "cue_required": "bare",
        "base_confidence": 0.85,
    },
    "US_ITIN": {
        "country": "US",
        "id_type": "ITIN",
        "description": "US ITIN: 9NN-GG-NNNN with an IRS-issued group",
        "pattern": _SSN_SHAPE,
        "validator": _validate_us_itin,
        "cue": _ITIN_CUE,
        "cue_required": "bare",
        "base_confidence": 0.85,
    },
    "US_EIN": {
        "country": "US",
        "id_type": "EIN",
        "description": "US Employer Identification Number: NN-NNNNNNN, IRS-assigned prefix",
        "pattern": re.compile(r"(?<![\d-])(\d{2}(-?)\d{7})(?![\d-])"),
        "validator": _validate_us_ein,
        "cue": _EIN_CUE,
        "cue_required": "bare",
        "base_confidence": 0.75,
    },
}


def _is_bare(m: re.Match[str]) -> bool:
    return m.re.groups < 2 or not m.group(2)


def detect_us_ids(text: str) -> list[NationalID]:
    """Detect US identifiers: NPI, SSN, ITIN, EIN."""
    results: list[NationalID] = []
    seen_spans: set[tuple[int, int]] = set()
    # The checksummed, always-labelled NPI first; then the SSN before the
    # ITIN (disjoint by area) and the EIN, which only a label separates from
    # a bare SSN.
    for key in ("US_NPI", "US_SSN", "US_ITIN", "US_EIN"):
        spec = US_PATTERNS[key]
        for m in spec["pattern"].finditer(text):
            span = (m.start(1), m.end(1))
            if any(_overlaps(span, s) for s in seen_spans):
                continue
            cued = bool(spec["cue"].search(text, max(0, span[0] - 60), span[0]))
            needs = spec["cue_required"]
            if not cued and (needs == "always" or (needs == "bare" and _is_bare(m))):
                continue
            is_valid, meta = spec["validator"](m.group(1))
            if not is_valid:
                continue
            confidence = min(spec["base_confidence"] + (0.05 if cued else 0.0), 1.0)
            results.append(NationalID(
                text=m.group(1),
                country="US",
                id_type=spec["id_type"],
                confidence=round(confidence, 4),
                start=span[0],
                end=span[1],
                metadata=_status_meta(spec, {**meta, "labelled": cued}),
            ))
            seen_spans.add(span)
    results.sort(key=lambda x: -x.confidence)
    return results


def _overlaps(a: tuple[int, int], b: tuple[int, int]) -> bool:
    return a[0] < b[1] and b[0] < a[1]


__all__ = [
    "US_PATTERNS", "_validate_us_ein", "_validate_us_itin", "_validate_us_npi",
    "_validate_us_ssn", "detect_us_ids",
]
