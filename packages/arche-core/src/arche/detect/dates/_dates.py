# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Calendar dates in free text, each parsed to (year, month, day).

A candidate becomes a detection only if it parses to a real calendar day. The
span is the date alone; the cue before it ("DOB", "admitted") is never part
of it, so ``DOB 03/14/1961`` generalises to ``DOB 1961``.
"""

from __future__ import annotations

import calendar
import datetime as _dt
import re
from typing import Any

from arche.workflow._primitive import Detection

#: Jurisdictions that write numeric dates month first.
MDY_JURISDICTIONS = frozenset({"US"})

_MONTHS: dict[str, int] = {}
for _i, _name in enumerate(calendar.month_name):
    if _i:
        _MONTHS[_name.lower()] = _i
        _MONTHS[_name[:3].lower()] = _i
_MONTHS["sept"] = 9
_MON = r"(?:" + "|".join(sorted(_MONTHS, key=len, reverse=True)) + r")\.?"

# Edges. Before: not a word character, slash, dot or dash (`v1.14/03/1961`,
# `INV-2026-10-02`). After: not a word character, slash or dash, and not a dot
# or colon followed by a digit (`10.02.2026.1`); an ISO `T` time suffix is fine.
_B = r"(?<![\w/.-])"
_A = r"(?:(?=T\d)|(?![\w/-]|[.:]\d))"
_ORD = r"(?:st|nd|rd|th)?"

_ISO = re.compile(_B + r"(\d{4})-(\d{2})-(\d{2})" + _A)
_YMD_SLASH = re.compile(_B + r"(\d{4})/(\d{1,2})/(\d{1,2})" + _A)
#: Numeric day/month/year with one separator used twice.
_NUM = re.compile(_B + r"(\d{1,2})([/.-])(\d{1,2})\2(\d{4}|\d{2})" + _A)
#: 12 March 2026, 9th October 2026, 14-Mar-1961, 14 Mar 61.
_DMY_TEXT = re.compile(
    r"(?i)(?<![\w.-])(\d{1,2})" + _ORD + r"(?:\s+of)?[\s-]+(" + _MON + r")[\s,-]+"
    r"(\d{4}|\d{2})(?![\w/-]|[.:]\d)"
)
#: Mar 14, 1961; Oct 9, 2026; March 14th 1961.
_MDY_TEXT = re.compile(
    r"(?i)(?<![\w.-])(" + _MON + r")\s+(\d{1,2})" + _ORD + r",?\s+(\d{4})(?![\w/-]|[.:]\d)"
)

#: Cue words, nearest one before a date decides what the date is. ``born`` and
#: friends make it a birth date; the rest name an event in a person's care.
_CUE = re.compile(
    r"(?i)\b(?:(?P<birth>d\.?o\.?b\b\.?|date\s+of\s+birth|birth\s*date|birthday|born(?:\s+on)?"
    r"|b\.(?=\s*\d))"
    r"|(?P<death>d\.?o\.?d\b\.?|date\s+of\s+death|died(?:\s+on)?|deceased|death)"
    r"|(?P<admission>admitted|admission(?:\s+date)?|date\s+of\s+admission|adm\b\.?)"
    r"|(?P<discharge>discharged|discharge(?:\s+date)?|date\s+of\s+discharge|d/c)"
    r"|(?P<service>seen|visit(?:ed)?|appointment|appt\b\.?|surgery|procedure|operation"
    r"|presented|consult(?:ation)?|delivered|treated|results?|test(?:ed)?|scan|onset"
    r"|injury|incident|encounter|date\s+of\s+service|dos\b))"
)
#: A document's own date (an invoice date, a letter's date): not about a person.
#: A bare ``Date`` label counts, unless a person event cue follows it.
_DOC_CUE = re.compile(
    r"(?i)\b(?:invoice|order|issued?|due|dated|statement|printed|effective|expir(?:y|es|ed)"
    r"|valid\s+(?:until|from|to)|published|updated|revised|released|version|copyright"
    r"|(?<!of\s)date)\b\s*(?:date\b)?\s*[:#-]?\s*$"
)
_WINDOW = 25


def _year2(yy: int, ref: int) -> int:
    """A two-digit year, never in the future: ``61`` is 1961, ``26`` is 2026."""
    full = 2000 + yy
    return full if full <= ref else 1900 + yy


def _valid(y: int, m: int, d: int) -> bool:
    if not (1 <= m <= 12 and 1800 <= y <= 2199):
        return False
    return 1 <= d <= calendar.monthrange(y, m)[1]


def _context(text: str, start: int, floor: int) -> tuple[str | None, bool]:
    """``(event, document)`` from the text just before ``start``.

    The window stops at ``floor`` (the end of the previous date) and at a
    semicolon or newline, so ``DOB 03/14/1961, admitted 10/02/2026`` does not
    make the second date a birth date.
    """
    lo = max(floor, start - _WINDOW)
    window = text[lo:start]
    cut = max(window.rfind(";"), window.rfind("\n"))
    if cut >= 0:
        window = window[cut + 1:]
    event = None
    for m in _CUE.finditer(window):
        event = m.lastgroup
    return event, bool(_DOC_CUE.search(window))


def _age_at(y: int, m: int, d: int, today: _dt.date) -> int:
    return today.year - y - ((today.month, today.day) < (m, d))


def detect_calendar_dates(
    text: str,
    jurisdiction: str | None = None,
    *,
    today: _dt.date | None = None,
) -> list[Detection]:
    """Dates in ``text`` that parse to a real day, as ``PII-1-DOB`` or ``PII-1-DATE``.

    Two-digit years and document dates are left alone unless a cue says
    otherwise: ``03/09/26`` alone is skipped, ``admitted 03/09/26`` is a date;
    ``Invoice date 01/11/2026`` is the document's date, not the person's.
    """
    today = today or _dt.date.today()
    mdy_first = (jurisdiction or "").upper() in MDY_JURISDICTIONS
    found: list[tuple[int, int, int, int, int, str, str, dict[str, Any]]] = []

    def add(m: re.Match[str], y: int, mo: int, d: int, fmt: str, order: str,
            two_digit: bool, extra: dict[str, Any] | None = None) -> None:
        found.append((m.start(), m.end(), y, mo, d, fmt, order,
                      {"two_digit_year": two_digit, **(extra or {})}))

    for m in _ISO.finditer(text):
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if _valid(y, mo, d):
            add(m, y, mo, d, "YYYY-MM-DD", "YMD", False)
    for m in _YMD_SLASH.finditer(text):
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if _valid(y, mo, d):
            add(m, y, mo, d, "YYYY/MM/DD", "YMD", False)
    for m in _NUM.finditer(text):
        a, sep, b, yraw = int(m.group(1)), m.group(2), int(m.group(3)), m.group(4)
        two = len(yraw) == 2
        y = _year2(int(yraw), today.year) if two else int(yraw)
        mdy_ok, dmy_ok = _valid(y, a, b), _valid(y, b, a)
        # Dotted dates are day first everywhere, the US included.
        prefer_mdy = mdy_first and sep != "."
        if prefer_mdy and mdy_ok:
            order, mo, d, fallback = "MDY", a, b, False
        elif dmy_ok:
            order, mo, d, fallback = "DMY", b, a, prefer_mdy
        elif mdy_ok:
            order, mo, d, fallback = "MDY", a, b, True
        else:
            continue
        fmt = ("MM" if order == "MDY" else "DD") + sep + ("DD" if order == "MDY" else "MM")
        fmt += sep + ("YY" if two else "YYYY")
        add(m, y, mo, d, fmt, order, two, {
            "ambiguous": mdy_ok and dmy_ok and a != b,
            "order_fallback": fallback,
        })
    for m in _DMY_TEXT.finditer(text):
        d, mo, yraw = int(m.group(1)), _MONTHS[m.group(2).rstrip(".").lower()], m.group(3)
        two = len(yraw) == 2
        y = _year2(int(yraw), today.year) if two else int(yraw)
        if _valid(y, mo, d):
            add(m, y, mo, d, "D Month YYYY" if not two else "D Month YY", "DMY", two)
    for m in _MDY_TEXT.finditer(text):
        mo, d, y = _MONTHS[m.group(1).rstrip(".").lower()], int(m.group(2)), int(m.group(3))
        if _valid(y, mo, d):
            add(m, y, mo, d, "Month D, YYYY", "MDY", False)

    # One detection per region: the earliest, then longest, candidate wins.
    found.sort(key=lambda f: (f[0], -f[1]))
    out: list[Detection] = []
    last_end = 0
    for start, end, y, mo, d, fmt, order, extra in found:
        if start < last_end:
            continue
        event, document = _context(text, start, last_end)
        if extra["two_digit_year"] and event is None:
            continue
        if document and event is None:
            continue
        last_end = end
        birth = event == "birth"
        meta: dict[str, Any] = {
            "kind": "dob" if birth else "date",
            "year": y, "month": mo, "day": d, "format": fmt, "order": order,
            "event": event, **extra,
        }
        if birth:
            age = _age_at(y, mo, d, today)
            meta["age"] = age
            # 45 CFR 164.514(b)(2)(i)(C): for a person over 89 even the year
            # of birth must go (aggregated to "90 or older").
            meta["over_89"] = age > 89
        conf = 0.95 if birth else 0.9
        if extra.get("ambiguous") or extra["two_digit_year"]:
            conf -= 0.1
        kind = meta["kind"]
        out.append(Detection(
            id=f"det:{kind}:{start}:{end}",
            category="PII-1-DOB" if birth else "PII-1-DATE",
            text=text[start:end],
            start=start,
            end=end,
            confidence=round(conf, 2),
            detector=f"rule:{kind}",
            identity_class="inferred",
            metadata=meta,
        ))
    return out
