# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Dates, dates of birth and stated ages (HIPAA Safe Harbor identifier C).

Before this detector the rules-only path returned ``DOB 03/14/1961 ... admitted
10/02/2026 ... aged 93 ... discharged Oct 9, 2026`` unchanged under HIPAA. All
values here are invented.
"""

from __future__ import annotations

import datetime as dt

import pytest
from arche.detect.dates import detect_ages, detect_calendar_dates, detect_dates

TODAY = dt.date(2026, 11, 20)


def _one(text: str, jurisdiction: str | None = None):
    found = detect_calendar_dates(text, jurisdiction, today=TODAY)
    assert len(found) == 1, (text, found)
    return found[0]


# ── the audit repro ─────────────────────────────────────────────────────────

def test_audit_repro_us() -> None:
    text = "DOB 03/14/1961 … admitted 10/02/2026 … aged 93 … discharged Oct 9, 2026"
    got = [(d.category, d.text) for d in detect_dates(text, "US")]
    assert got == [
        ("PII-1-DOB", "03/14/1961"),
        ("PII-1-DATE", "10/02/2026"),
        ("PII-1-AGE", "93"),
        ("PII-1-DATE", "Oct 9, 2026"),
    ]
    admitted = detect_dates(text, "US")[1]
    assert admitted.metadata["event"] == "admission"
    assert (admitted.metadata["month"], admitted.metadata["day"]) == (10, 2)


def test_span_excludes_cue() -> None:
    d = _one("Patient DOB: 14/03/1958.", "GB")
    assert d.text == "14/03/1958"
    assert d.detector == "rule:dob"


# ── formats ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    ("text", "jur", "ymd", "fmt", "order"),
    [
        ("seen 2026-10-02 in clinic", None, (2026, 10, 2), "YYYY-MM-DD", "YMD"),
        ("seen 2026/10/02 in clinic", None, (2026, 10, 2), "YYYY/MM/DD", "YMD"),
        ("seen 10/02/2026 in clinic", "US", (2026, 10, 2), "MM/DD/YYYY", "MDY"),
        ("seen 10/02/2026 in clinic", "GB", (2026, 2, 10), "DD/MM/YYYY", "DMY"),
        ("seen 10/02/2026 in clinic", None, (2026, 2, 10), "DD/MM/YYYY", "DMY"),
        ("seen 14.03.1961 in clinic", "DE", (1961, 3, 14), "DD.MM.YYYY", "DMY"),
        ("seen 14.03.1961 in clinic", "US", (1961, 3, 14), "DD.MM.YYYY", "DMY"),
        ("seen 14-03-1961 in clinic", "ZA", (1961, 3, 14), "DD-MM-YYYY", "DMY"),
        ("seen 12 March 2026 in clinic", None, (2026, 3, 12), "D Month YYYY", "DMY"),
        ("seen 9th October 2026.", None, (2026, 10, 9), "D Month YYYY", "DMY"),
        ("seen 14-Mar-1961 here", None, (1961, 3, 14), "D Month YYYY", "DMY"),
        ("seen Mar 14, 1961 here", None, (1961, 3, 14), "Month D, YYYY", "MDY"),
        ("seen Oct 9, 2026 here", "US", (2026, 10, 9), "Month D, YYYY", "MDY"),
        ("seen September 3rd 2026", None, (2026, 9, 3), "Month D, YYYY", "MDY"),
    ],
)
def test_formats(text: str, jur: str | None, ymd: tuple[int, int, int], fmt: str,
                 order: str) -> None:
    m = _one(text, jur).metadata
    assert (m["year"], m["month"], m["day"]) == ymd
    assert (m["format"], m["order"]) == (fmt, order)


def test_us_order_falls_back_when_month_first_is_not_a_day() -> None:
    m = _one("DOB 14/03/1961", "US").metadata
    assert (m["order"], m["month"], m["day"], m["order_fallback"]) == ("DMY", 3, 14, True)


def test_ambiguous_flagged_and_year_kept() -> None:
    m = _one("seen 03/04/2026", "US").metadata
    assert m["ambiguous"] is True and m["year"] == 2026
    assert _one("seen 03/03/2026", "US").metadata["ambiguous"] is False


def test_iso_timestamp_is_a_date() -> None:
    assert _one("event at 2026-10-02T10:30:00Z").text == "2026-10-02"


@pytest.mark.parametrize("text", ["DOB 14/03/58", "admitted 03/09/26", "born 14 Mar 61"])
def test_two_digit_year_with_cue(text: str) -> None:
    d = _one(text, "GB")
    assert d.metadata["two_digit_year"] is True
    assert d.metadata["year"] in (1958, 2026, 1961)


def test_two_digit_year_never_in_future() -> None:
    assert _one("DOB 01/01/30", "GB").metadata["year"] == 1930
    assert _one("DOB 01/01/26", "GB").metadata["year"] == 2026


# ── DOB vs other dates ──────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "text",
    ["DOB 14/03/1961", "D.O.B. 14/03/1961", "d.o.b: 14/03/1961", "date of birth 14/03/1961",
     "Date of Birth: 14 March 1961", "born on 14 March 1961", "birthday Mar 14, 1961",
     "Birth date 1961-03-14", "born 14.03.1961"],
)
def test_dob_cues(text: str) -> None:
    d = _one(text, "GB")
    assert d.category == "PII-1-DOB"
    assert d.metadata["year"] == 1961 and d.metadata["kind"] == "dob"


def test_dob_cue_does_not_reach_the_next_date() -> None:
    found = detect_calendar_dates("DOB 03/14/1961, admitted 10/02/2026", "US", today=TODAY)
    assert [d.category for d in found] == ["PII-1-DOB", "PII-1-DATE"]


def test_dob_cue_outside_window_is_a_plain_date() -> None:
    text = "DOB recorded at intake, last reviewed 10/02/2026"
    assert _one(text, "US").category == "PII-1-DATE"


def test_dob_over_89_flag() -> None:
    assert _one("born 12 March 1931").metadata["over_89"] is True
    assert _one("born 12 March 1961").metadata["over_89"] is False


@pytest.mark.parametrize(
    ("text", "event"),
    [("admitted 03/09/2026", "admission"), ("discharged Oct 9, 2026", "discharge"),
     ("date of death 2026-10-09", "death"), ("died 9 October 2026", "death"),
     ("seen on 02/10/2026", "service")],
)
def test_events(text: str, event: str) -> None:
    d = _one(text, "GB")
    assert d.category == "PII-1-DATE" and d.metadata["event"] == event


def test_document_date_is_not_a_persons_date() -> None:
    for text in ["Invoice date 01/11/2026", "Invoice #100245 dated 11/01/2026.",
                 "Date 01/11/2026  Bill to", "Date: 2026-11-01", "Due 01/12/2026",
                 "Issued 3 March 2026"]:
        assert detect_calendar_dates(text, "US", today=TODAY) == [], text


def test_document_cue_does_not_hide_a_birth_cue() -> None:
    assert _one("Date of birth 14/03/1961", "GB").category == "PII-1-DOB"


# ── negatives ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "text",
    [
        "upgraded to v1.2.3 and Python 3.12",
        "meet at 10:30 or 10:30:15",
        "paid 12.50 and 1,234.56",
        "scored 3/4 and 7/10; half is 1/2",
        "call 555-0100-22 or 07700 900461 or (617) 846-0148",
        "invoice INV-2026-00417, ref TRF-20261101-0042, order 20261101234",
        "ISBN 978-3-16-148410-0",
        "in 2026 the clinic moved; founded 1961",
        "see pp. 12-14 and pages 1961-1965",
        "ZIP 02139 or 90210-1234",
        "IP 10.02.20.26",
        "on 03/09/26 without a cue",
        "not a day: 2026-02-30, 31/04/2026, 13/13/2026",
        "We hope to see you May 5.",
        "version 2026.10.02",
        "ratio 12/31/2026/1",
    ],
)
def test_negatives(text: str) -> None:
    assert detect_dates(text, "US") == [], text


# ── ages ────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "text",
    ["aged 93", "a 93-year-old man", "93 year old", "93 years old", "93 years of age",
     "93 yrs", "age: 93", "Age 93", "93 y/o", "93yo", "93 y.o. male", "93-yr-old"],
)
def test_ages_over_89(text: str) -> None:
    (a,) = detect_ages(text)
    assert a.text == "93" and a.category == "PII-1-AGE"
    assert a.metadata == {"kind": "age", "age": 93, "over_89": True, "format": a.metadata["format"]}


def test_age_under_90_detected_not_flagged() -> None:
    (a,) = detect_ages("82yo pt")
    assert a.metadata["age"] == 82 and a.metadata["over_89"] is False
    (b,) = detect_ages("aged 89")
    assert b.metadata["over_89"] is False
    (c,) = detect_ages("aged 90")
    assert c.metadata["over_89"] is True


@pytest.mark.parametrize(
    "text",
    ["worked there for 12 yrs", "over 20 yrs experience", "page 93", "stage 3 cancer",
     "usage: 93", "93 patients", "in 93 years' time", "age 1.5mg", "aged 300"],
)
def test_age_negatives(text: str) -> None:
    assert detect_ages(text) == [], text


def test_age_inside_date_is_dropped() -> None:
    assert [d.category for d in detect_dates("DOB 14 Mar 1961", "GB")] == ["PII-1-DOB"]


# ── the policy can generalise any format from metadata ─────────────────────

def test_metadata_year_for_every_format() -> None:
    text = ("DOB 03/14/1961; admitted 2026-10-02; seen 12 March 2026; "
            "discharged Oct 9, 2026; died 09.10.2026")
    years = [d.metadata["year"] for d in detect_dates(text, "US")]
    assert years == [1961, 2026, 2026, 2026, 2026]
