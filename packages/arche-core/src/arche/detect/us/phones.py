# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""North American Numbering Plan phone detection (libphonenumber-backed).

Accepted shapes, each with an optional ``+1`` / ``1-`` prefix::

    (212) 555-0147    212-555-0147    212.555.0147    212 555 0147    +1 2125550147

The separator between the three groups must be consistent, so ``2026-11-20``
and ``12.5.2026`` cannot match, and a bare ten-digit run is a phone only with
``+1`` in front of it: an NPI, an order number and an account number are all
ten digits. The area code and the exchange may not start with 0 or 1 (NANP
rule), and libphonenumber must call the number valid, which also rejects
unassigned area codes and ``N11`` service codes. A number straight after
"order", "invoice", "ref", "PO", "confirmation" or "tracking" is left alone.

``555-01xx`` fictional numbers are *not* excluded: arche treats the 555
numbers in its own examples as phones throughout, and masking a fictional
number costs nothing.
"""

from __future__ import annotations

import re
from typing import Any

from arche.detect._africa.phones import normalize_e164, validate_phone

_NANP = re.compile(
    r"(?<![\w+$])"
    r"((?:\+1[\s.-]?|\b1[\s.-])?"
    r"(?:\([2-9]\d{2}\)\s?[2-9]\d{2}[\s.-]\d{4}"
    r"|[2-9]\d{2}([\s.-])[2-9]\d{2}\2\d{4}))"
    r"(?![\w-])"
    r"|(?<![\w+$])(\+1\s?[2-9]\d{2}[2-9]\d{6})(?![\w-])"
)

_NOT_A_PHONE = re.compile(
    r"(?i)\b(?:order|invoice|inv|ref(?:erence)?|po|confirmation|tracking|case|claim)"
    r"(?:\s*(?:no|number|num|#))?\.?\s*[:#-]?\s*$"
)


def normalize_us_phone(number: str) -> str | None:
    """Normalize a NANP phone number to E.164."""
    return normalize_e164(number, default_country="US")


def validate_us_phone(number: str) -> dict[str, Any]:
    """Validate and structure a NANP phone number."""
    return validate_phone(number, default_country="US")


def detect_us_phones(text: str) -> list[dict]:
    """NANP phone numbers in ``text`` as dicts (``raw``, ``start``, ``end``,
    ``country``, ``international``), the shape :func:`arche.detect.phones`
    merges."""
    import phonenumbers

    hits = []
    for m in _NANP.finditer(text):
        group = 1 if m.group(1) else 3
        raw, start, end = m.group(group), m.start(group), m.end(group)
        if _NOT_A_PHONE.search(text, max(0, start - 40), start):
            continue
        try:
            parsed = phonenumbers.parse(raw, "US")
        except phonenumbers.NumberParseException:
            continue
        if parsed.country_code != 1 or not phonenumbers.is_valid_number(parsed):
            continue
        hits.append({
            "raw": raw, "start": start, "end": end,
            "country": phonenumbers.region_code_for_number(parsed) or "US",
            "international": phonenumbers.format_number(
                parsed, phonenumbers.PhoneNumberFormat.E164),
        })
    return hits


__all__ = ["detect_us_phones", "normalize_us_phone", "validate_us_phone"]
