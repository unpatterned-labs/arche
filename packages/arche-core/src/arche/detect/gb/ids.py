# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""United Kingdom identifier detectors: NHS number, NINO, passport, UTR,
DVLA driving licence and Companies House registration number.

Most of these are digit runs of nine or ten, which is also the shape of an
order number, a PO, a bank reference and a phone number. The rule is the one
the US and ZA packs follow: **a bare digit run carries no evidence of being an
identifier; a label before it does.** The exceptions are the forms whose own
structure is evidence:

* **NHS number** (10 digits, modulus 11; NHS Data Dictionary). The check digit
  is ``11 - (sum of digits 1-9 weighted 10..2) mod 11``, with 11 read as 0 and
  10 meaning "never issued". A label ("NHS", "national health") is required for
  the bare run and for any separator, *except* the canonical ``NNN NNN NNNN``
  display form: spaced 3-3-4 is accepted without a label when the check digit
  holds, the first three digits fall in an allocated range (320-499 Northern
  Ireland H&C and England/Wales; 600-799 England/Wales) and no phone word
  ("tel", "call", "mobile", "fax", "ext") precedes it. A random ten-digit run
  passes modulus 11 about one time in eleven, so the checksum alone is not
  enough for a bare run; the spacing, the range and the phone veto together
  are what make the unlabelled form safe. UK phone numbers are 11 digits with
  a leading 0 and never take the 3-3-4 shape.
* **National Insurance number** (HMRC NIM39110): two letters, six digits and a
  suffix A-D, bare or spaced (``AB 12 34 56 C``). The first letter is never
  D, F, I, Q, U or V; the second never D, F, I, O, Q, U or V; the prefixes BG,
  GB, KN, NK, NT, TN and ZZ are not allocated. The shape is distinctive enough
  to stand without a label when written in capitals. ``QQ`` breaks the letter
  rule and is never allocated, but HMRC and most UK forms use it as the
  example prefix, so synthetic and test records carry it: it is accepted
  *only* after a NINO label, and flagged ``example_prefix`` in the metadata.
* **Passport**: nine digits, only after "passport".
* **UTR** (Unique Taxpayer Reference): ten digits (or 5+5 spaced), only after
  "UTR", "unique taxpayer reference" or "self assessment". HMRC publishes no
  check-digit algorithm, so none is applied: the circulating "weights 6..2"
  rule is reverse-engineered, not specified.
* **DVLA driving licence**: 16 characters, ``SSSSS D MM DD Y II N CC``: five
  surname characters (padded with 9), the decade of birth, the month (plus 50
  for women), the day, the year digit, two initials (padded with 9), a digit
  and two check characters. The encoded date is validated. The structure is
  specific enough to stand without a label in capitals; a label also admits
  lowercase and segment spacing.
* **Company registration number** (Companies House, Companies Act 2006
  s.1066): eight digits, or a register prefix (SC, NI, OC, SO, NC, LP, SL,
  NL, FC, SF, NF) and six digits, only after "company number", "registered
  number", "CRN" or "registered in England and Wales". It identifies a
  company on a public register, not a person, and is emitted as ``RC`` so a
  statute pack can retain it.

None of these checks says a number was *issued*; they say it is well-formed.
That is integrity, not authenticity (see ``_checksum``). Only the NHS number
carries a published check digit and is labelled ``checksum_valid``.

Public API::

    from arche.detect.gb.ids import detect_gb_ids, GB_PATTERNS
"""

from __future__ import annotations

import calendar
import re
from collections.abc import Callable

from arche.detect._base import NationalID, _status_meta

#: First letters HMRC never allocates; second letters likewise (NIM39110).
_NINO_BAD_FIRST = frozenset("DFIQUV")
_NINO_BAD_SECOND = frozenset("DFIOQUV")
_NINO_BAD_PREFIXES = frozenset({"BG", "GB", "KN", "NK", "NT", "TN", "ZZ"})
#: The prefix HMRC uses in its own examples. Never allocated.
_NINO_EXAMPLE_PREFIX = "QQ"

#: Companies House register prefixes followed by six digits.
_CRN_PREFIXES = ("SC", "NI", "OC", "SO", "NC", "LP", "SL", "NL", "FC", "SF", "NF")


def _compact(text: str) -> str:
    return re.sub(r"[\s-]", "", text).upper()


def nhs_check_digit(nine: str) -> int | None:
    """The NHS-number modulus-11 check digit for nine digits, or ``None``
    when the remainder gives 10 (such a number is never issued)."""
    total = sum(int(ch) * w for ch, w in zip(nine, range(10, 1, -1), strict=True))
    check = 11 - total % 11
    if check == 11:
        return 0
    return None if check == 10 else check


def _validate_gb_nhs(text: str) -> tuple[bool, dict]:
    """An NHS (England, Wales, IoM) or H&C (Northern Ireland) number: mod 11."""
    d = _compact(text)
    if len(d) != 10 or not d.isdigit():
        return False, {}
    return nhs_check_digit(d[:9]) == int(d[9]), {}


def _validate_gb_nino(text: str) -> tuple[bool, dict]:
    """A National Insurance number: HMRC prefix rules and an A-D suffix."""
    v = _compact(text)
    if not re.fullmatch(r"[A-Z]{2}\d{6}[A-D]", v):
        return False, {}
    prefix = v[:2]
    if prefix == _NINO_EXAMPLE_PREFIX:
        return True, {"example_prefix": True}
    if prefix[0] in _NINO_BAD_FIRST or prefix[1] in _NINO_BAD_SECOND:
        return False, {}
    return prefix not in _NINO_BAD_PREFIXES, {}


def _validate_gb_passport(text: str) -> tuple[bool, dict]:
    """A UK passport number: nine digits (HM Passport Office)."""
    d = _compact(text)
    return len(d) == 9 and d.isdigit(), {}


def _validate_gb_utr(text: str) -> tuple[bool, dict]:
    """A Unique Taxpayer Reference: ten digits; no published check digit."""
    d = _compact(text)
    return len(d) == 10 and d.isdigit(), {}


def _validate_gb_driving_licence(text: str) -> tuple[bool, dict]:
    """A DVLA licence number: surname block, encoded date of birth, initials."""
    v = _compact(text)
    m = re.fullmatch(r"([A-Z9]{5})(\d)(\d{2})(\d{2})(\d)([A-Z9]{2})(\d)([A-Z0-9]{2})", v)
    if not m:
        return False, {}
    surname, decade, month, day, year, initials = m.group(1, 2, 3, 4, 5, 6)
    # Surname: letters, then 9-padding only at the end; at least one letter.
    if not re.fullmatch(r"[A-Z]+9*", surname) or not re.fullmatch(r"[A-Z][A-Z9]", initials):
        return False, {}
    mm = int(month)
    if mm > 50:  # women: month + 50
        mm -= 50
    if not 1 <= mm <= 12:
        return False, {}
    yy = int(decade + year)
    # The century is not encoded; 00 is a leap year in 2000, not in 1900.
    leap = yy % 4 == 0
    days = 29 if (mm == 2 and leap) else calendar.monthrange(2001, mm)[1]
    return 1 <= int(day) <= days, {}


def _validate_gb_crn(text: str) -> tuple[bool, dict]:
    """A Companies House registration number: 8 digits or prefix + 6 digits."""
    v = _compact(text)
    if len(v) != 8:
        return False, {}
    return v.isdigit() or (v[:2] in _CRN_PREFIXES and v[2:].isdigit()), {}


def _cue(words: str, *, gap: int = 25) -> re.Pattern[str]:
    """A label that must end within ``gap`` non-digit characters of the value."""
    return re.compile(rf"\b(?:{words})(?![a-z])[^0-9\n]{{0,{gap}}}$", re.IGNORECASE)


_NHS_CUE = _cue(r"nhs|national\s+health(?:\s+service)?")
_NINO_CUE = _cue(
    r"nino|national\s+insurance|nat\.?\s*ins\.?|n\.?i\.?\s*(?:no|num|number|#)"
)
_PASSPORT_CUE = _cue(r"passport")
_UTR_CUE = _cue(
    r"s?a?\s*utr|unique\s+tax\s*payer(?:\s+ref(?:erence)?)?|self[\s-]+assessment"
)
_DL_CUE = _cue(r"driving\s+licen[cs]e|driver'?s?\s+licen[cs]e|dvla|licen[cs]e\s+(?:no|number)|dl")
_CRN_CUE = _cue(
    r"company\s+(?:reg(?:istration|istered)?\.?\s+)?(?:no|num|number)|"
    r"registered\s+(?:company\s+)?(?:no|num|number)|crn|companies\s+house|"
    r"registered\s+in\s+(?:england|wales|scotland|northern\s+ireland)"
)
#: A phone word just before a spaced ten-digit run: it is a number to call.
_PHONE_CUE = _cue(
    r"tel|telephone|phone|call|mob|mobile|cell|fax|ext|sms|whatsapp|contact", gap=15
)


def _nhs_stands_alone(m: re.Match[str], text: str) -> bool:
    """Unlabelled NHS number: ``NNN NNN NNNN``, allocated range, no phone word."""
    if m.group(2) != " ":
        return False
    head = int(m.group(1)[:3])
    if not (320 <= head <= 499 or 600 <= head <= 799):
        return False
    start = m.start(1)
    if text[max(0, start - 3):start].rstrip().endswith("+"):
        return False
    return not _PHONE_CUE.search(text, max(0, start - 40), start)


def _nino_stands_alone(m: re.Match[str], text: str) -> bool:
    """Unlabelled NINO: capitals, and never the example prefix."""
    value = m.group(1)
    return value.isupper() and not value.startswith(_NINO_EXAMPLE_PREFIX)


def _dl_stands_alone(m: re.Match[str], text: str) -> bool:
    """Unlabelled licence number: capitals, unbroken."""
    value = m.group(1)
    return value.isupper() and " " not in value


_Alone = Callable[[re.Match[str], str], bool]

#: ``cue``: the label regex; ``alone``: ``None`` when the label is always
#: required, else a predicate saying whether this unlabelled match stands on
#: its own. ``id_type`` becomes the category ``PII-2-{id_type}``.
GB_PATTERNS: dict[str, dict] = {
    "GB_NHS": {
        "country": "GB",
        "id_type": "NHS",
        "description": "UK NHS / H&C number: 10 digits, modulus 11",
        "pattern": re.compile(r"(?<![\d-])(?<!\d[ -])(\d{3}([ -]?)\d{3}\2\d{4})(?![\d-])(?! \d)"),
        "validator": _validate_gb_nhs,
        "checksum": "mod11",
        "cue": _NHS_CUE,
        "alone": _nhs_stands_alone,
        "base_confidence": 0.85,
    },
    "GB_NINO": {
        "country": "GB",
        "id_type": "NIN",
        "description": "UK National Insurance number: AA 99 99 99 A (HMRC prefix rules)",
        "pattern": re.compile(
            r"(?<![A-Za-z0-9])([A-Z]{2} ?\d{2} ?\d{2} ?\d{2} ?[A-D])(?![A-Za-z0-9])",
            re.IGNORECASE,
        ),
        "validator": _validate_gb_nino,
        "cue": _NINO_CUE,
        "alone": _nino_stands_alone,
        "base_confidence": 0.85,
    },
    "GB_DRIVING_LICENCE": {
        "country": "GB",
        "id_type": "DRIVERS_LICENCE",
        "description": "DVLA driving licence number: 16 characters with an encoded birth date",
        "pattern": re.compile(
            r"(?<![A-Za-z0-9])([A-Z9]{5} ?\d{6} ?[A-Z9]{2}\d[A-Z0-9]{2})(?![A-Za-z0-9])",
            re.IGNORECASE,
        ),
        "validator": _validate_gb_driving_licence,
        "cue": _DL_CUE,
        "alone": _dl_stands_alone,
        "base_confidence": 0.85,
    },
    "GB_UTR": {
        "country": "GB",
        "id_type": "TIN",
        "description": "HMRC Unique Taxpayer Reference: 10 digits after a UTR label",
        "pattern": re.compile(r"(?<![\d-])(\d{5} ?\d{5})(?![\d-])(?! \d)"),
        "validator": _validate_gb_utr,
        "cue": _UTR_CUE,
        "alone": None,
        "base_confidence": 0.85,
    },
    "GB_PASSPORT": {
        "country": "GB",
        "id_type": "PASSPORT",
        "description": "UK passport number: 9 digits after 'passport'",
        "pattern": re.compile(r"(?<![\d-])(\d{9})(?![\d-])"),
        "validator": _validate_gb_passport,
        "cue": _PASSPORT_CUE,
        "alone": None,
        "base_confidence": 0.85,
    },
    "GB_CRN": {
        "country": "GB",
        "id_type": "RC",
        "description": "Companies House registration number after a company-number label",
        "pattern": re.compile(
            rf"(?<![A-Za-z0-9])((?:{'|'.join(_CRN_PREFIXES)})\d{{6}}|\d{{8}})(?![A-Za-z0-9])"
        ),
        "validator": _validate_gb_crn,
        "cue": _CRN_CUE,
        "alone": None,
        "base_confidence": 0.85,
    },
}

#: Checksummed and structured first, then the label-only digit runs.
_ORDER = ("GB_NHS", "GB_NINO", "GB_DRIVING_LICENCE", "GB_UTR", "GB_PASSPORT", "GB_CRN")


def detect_gb_ids(text: str) -> list[NationalID]:
    """Detect UK identifiers: NHS, NINO, driving licence, UTR, passport, CRN."""
    results: list[NationalID] = []
    seen_spans: set[tuple[int, int]] = set()
    for key in _ORDER:
        spec = GB_PATTERNS[key]
        for m in spec["pattern"].finditer(text):
            span = (m.start(1), m.end(1))
            if any(_overlaps(span, s) for s in seen_spans):
                continue
            cued = bool(spec["cue"].search(text, max(0, span[0] - 60), span[0]))
            alone: _Alone | None = spec["alone"]
            if not cued and (alone is None or not alone(m, text)):
                continue
            is_valid, meta = spec["validator"](m.group(1))
            if not is_valid:
                continue
            confidence = spec["base_confidence"] + (0.1 if cued else 0.0)
            if meta.get("example_prefix"):
                confidence -= 0.25
            results.append(NationalID(
                text=m.group(1),
                country="GB",
                id_type=spec["id_type"],
                confidence=round(min(confidence, 1.0), 4),
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
    "GB_PATTERNS", "_validate_gb_crn", "_validate_gb_driving_licence", "_validate_gb_nhs",
    "_validate_gb_nino", "_validate_gb_passport", "_validate_gb_utr", "detect_gb_ids",
    "nhs_check_digit",
]
