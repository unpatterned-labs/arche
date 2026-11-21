# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Dates, dates of birth and stated ages: HIPAA Safe Harbor identifier (C).

45 CFR 164.514(b)(2)(i)(C) removes "all elements of dates (except year) for
dates directly related to an individual, including birth date, admission date,
discharge date, date of death; and all ages over 89 and all elements of dates
(including year) indicative of such age". Until this detector the rules-only
path (``backend="basic"``) returned every one of them in the clear.

Categories:

* ``PII-1-DOB``: a date with a birth cue ("DOB", "date of birth", "born",
  "d.o.b.", "birthday") just before it. ``metadata["over_89"]`` is set when the
  person would now be over 89, since then the year must go too.
* ``PII-1-DATE``: any other calendar date, with ``metadata["event"]`` naming
  the cue when there is one (admission, discharge, death, service).
* ``PII-1-AGE``: a stated age, the number alone; ``metadata["over_89"]``.

Every date carries ``year``, ``month``, ``day``, ``format`` and ``order``
(``"MDY"``, ``"DMY"`` or ``"YMD"``) in its metadata, so a policy can
generalise any format to its year, not only ISO. Numeric dates are read month
first for ``jurisdiction="US"`` and day first elsewhere; when the preferred
reading is not a real day the other is used (``order_fallback``), and when
both are real ``ambiguous`` is set. The year is the same either way.

Not dates: a bare year (``in 2026``), versions (``1.2.3``), times, amounts,
scores and fractions (``3/4``), two-digit years without a cue (``03/09/26``),
and a document's own date (``Invoice date 01/11/2026``, ``dated``).
"""

from __future__ import annotations

from arche.detect.dates._ages import detect_ages
from arche.detect.dates._dates import MDY_JURISDICTIONS, detect_calendar_dates
from arche.workflow._primitive import Detection

__all__ = ["MDY_JURISDICTIONS", "detect_ages", "detect_calendar_dates", "detect_dates"]


def detect_dates(text: str, jurisdiction: str | None = None) -> list[Detection]:
    """Dates (``PII-1-DOB``, ``PII-1-DATE``) and stated ages (``PII-1-AGE``) in
    ``text``, sorted by offset. An age inside a date's span is dropped."""
    dates = detect_calendar_dates(text, jurisdiction)
    ages = [a for a in detect_ages(text)
            if not any(d.start < a.end and a.start < d.end for d in dates)]
    return sorted([*dates, *ages], key=lambda d: (d.start, d.end))
