# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""US ZIP codes, and the HIPAA Safe Harbor three-digit-ZIP rule.

A five-digit run is a ZIP only with evidence: straight after a USPS state code
or state name (``Springfield, IL 62701``, ``Austin, Texas 78701``) or after the
word "ZIP" (``ZIP: 62701``). A bare ``62701`` is an amount, a part number or a
count as often as a ZIP. Emits ``PII-4-ZIP``; ZIP+4 is one span.

Safe Harbor (45 CFR §164.514(b)(2)(i)(B)) lets a de-identified record keep the
first three digits of a ZIP only where the area those three digits cover holds
more than 20,000 people; otherwise they become ``000``. :func:`safe_harbor_zip3`
applies that rule from the bundled table ``arche/_data/hipaa_restricted_zip3.csv``
(the HHS-published list, source and date in the file's header), and the policy
engine's ``generalize`` action calls it for ``PII-4-ZIP``.
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

from arche.workflow._primitive import Detection

_STATE_CODES = (
    "AL|AK|AZ|AR|CA|CO|CT|DE|DC|FL|GA|HI|ID|IL|IN|IA|KS|KY|LA|ME|MD|MA|MI|MN|MS|MO|MT|"
    "NE|NV|NH|NJ|NM|NY|NC|ND|OH|OK|OR|PA|RI|SC|SD|TN|TX|UT|VT|VA|WA|WV|WI|WY|"
    "PR|VI|GU|AS|MP"
)
_STATE_NAMES = (
    "Alabama|Alaska|Arizona|Arkansas|California|Colorado|Connecticut|Delaware|Florida|"
    "Georgia|Hawaii|Idaho|Illinois|Indiana|Iowa|Kansas|Kentucky|Louisiana|Maine|Maryland|"
    "Massachusetts|Michigan|Minnesota|Mississippi|Missouri|Montana|Nebraska|Nevada|"
    "New Hampshire|New Jersey|New Mexico|New York|North Carolina|North Dakota|Ohio|"
    "Oklahoma|Oregon|Pennsylvania|Rhode Island|South Carolina|South Dakota|Tennessee|"
    "Texas|Utah|Vermont|Virginia|Washington|West Virginia|Wisconsin|Wyoming|"
    "District of Columbia|Puerto Rico"
)

# State codes are matched case-sensitively, so "in 46204" and "or 97201" in
# running prose are not Indiana and Oregon.
_ZIP = re.compile(
    rf"(?:\b(?:{_STATE_CODES})\.?|\b(?i:{_STATE_NAMES})),?\s+"
    r"(\d{5}(?:-\d{4})?)(?![\d-])"
    r"|(?i:\bzip(?:\s*code)?)\s*(?:no\.?|#)?\s*:?\s*(\d{5}(?:-\d{4})?)(?![\d-])"
)

_TABLE = Path(__file__).resolve().parents[2] / "_data" / "hipaa_restricted_zip3.csv"


@lru_cache(maxsize=1)
def restricted_zip3() -> frozenset[str]:
    """The three-digit ZIPs whose area holds 20,000 or fewer people (bundled table)."""
    rows = _TABLE.read_text(encoding="utf-8").splitlines()
    return frozenset(
        r.strip() for r in rows
        if r.strip() and not r.startswith("#") and r.strip() != "zip3"
    )


def safe_harbor_zip3(zip_code: str) -> str:
    """The Safe Harbor rendering of a ZIP: its first three digits, or ``000``.

    ``62701`` -> ``627``; ``82301-1234`` -> ``000`` (ZIP3 823 is restricted).
    """
    zip3 = re.sub(r"\D", "", zip_code)[:3]
    if len(zip3) != 3 or zip3 in restricted_zip3():
        return "000"
    return zip3


def detect_us_zips(text: str) -> list[Detection]:
    """ZIP codes after a state or the word "ZIP", as ``PII-4-ZIP`` detections."""
    out = []
    for m in _ZIP.finditer(text):
        group = 1 if m.group(1) else 2
        start, end = m.start(group), m.end(group)
        out.append(Detection(
            id=f"det:zip:{start}:{end}",
            category="PII-4-ZIP",
            text=m.group(group),
            start=start,
            end=end,
            confidence=0.9,
            detector="rule:us_zip",
            identity_class="inferred",
            metadata={"country": "US", "safe_harbor": safe_harbor_zip3(m.group(group))},
        ))
    return out


__all__ = ["detect_us_zips", "restricted_zip3", "safe_harbor_zip3"]
