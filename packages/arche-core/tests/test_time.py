# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""`arche.time.extract_times`. Every sentence is invented; the anchor is a Wednesday."""

from __future__ import annotations

import time

import pytest
from arche.time import extract_times

A = "2026-11-25T10:00"


def one(text, **kw):
    got = extract_times(text, anchor=kw.pop("anchor", A), **kw)
    assert len(got) == 1, [m.text for m in got]
    return got[0]


@pytest.mark.parametrize("text,start,typ", [
    ("deliver tomorrow", "2026-11-26", "date"),
    ("pick it up today", "2026-11-25", "date"),
    ("it came yesterday", "2026-11-24", "date"),
    ("na next tomorrow we go", "2026-11-27", "date"),
    ("two weeks from today", "2026-12-09", "date"),
    ("in 3 days", "2026-11-28", "date"),
    ("10 days ago", "2026-11-15", "date"),
    ("a week on Monday", "2026-12-07", "date"),
    ("last week Tuesday", "2026-11-17", "date"),
    ("Jumatatu ijayo", "2026-11-30", "date"),
    ("siku tatu zilizopita", "2026-11-22", "date"),
    ("by 25th Dec", "2026-12-25", "date"),
    ("2026-04-01 at 16:30", "2026-04-01T16:30", "datetime"),
    ("deliver tomorrow at 4pm", "2026-11-26T16:00", "datetime"),
    ("this evening around 7", "2026-11-25T19:00", "time"),
])
def test_resolves_against_the_anchor(text, start, typ):
    m = one(text)
    assert (m.start, m.type) == (start, typ)


@pytest.mark.parametrize("text,start", [
    ("kesho saa mbili asubuhi", "2026-11-26T08:00"),   # Swahili hours run from sunrise
    ("saa nne usiku", "2026-11-25T22:00"),
    ("saa sita mchana", "2026-11-25T12:00"),
    ("saa moja jioni", "2026-11-25T19:00"),
])
def test_swahili_time(text, start):
    assert one(text).start == start


def test_by_is_a_deadline():
    m = one("Deliver tomorrow by 4pm to Temanu")
    assert (m.start, m.mod) == ("2026-11-26T16:00", "ON_OR_BEFORE")


def test_a_chained_date_counts_from_the_one_before_it():
    got = extract_times("Admitted on 12 March 2026, discharged 2 days later", anchor=A)
    assert [m.start for m in got] == ["2026-03-12", "2026-03-14"]
    assert got[1].relative_to == "previous"


def test_or_from_the_one_after_it():
    got = extract_times("the day before the wedding on 12 May", anchor=A)
    assert [m.start for m in got] == ["2027-05-11", "2027-05-12"]


@pytest.mark.parametrize("text,start,end", [
    ("Monday to Friday 8-5", "2026-11-30", "2026-12-05"),
    ("between 2 and 4pm", "2026-11-25T14:00", "2026-11-25T16:00"),
    ("from the 3rd to the 10th", "2026-12-03", "2026-12-11"),
])
def test_ranges(text, start, end):
    m = extract_times(text, anchor=A)[0]
    assert (m.type, m.start, m.end) == ("range", start, end)


def test_working_hours_run_into_the_afternoon():
    hours = extract_times("Monday to Friday 8-5", anchor=A)[1]
    assert (hours.start, hours.end) == ("2026-11-25T08:00", "2026-11-25T17:00")


@pytest.mark.parametrize("text", ["we leave at 6", "pay on 3/12", "next Friday", "half past two"])
def test_ambiguity_is_said(text):
    m = one(text)
    assert m.ambiguous and len(m.alternatives) == 2


def test_a_reading_is_not_invented_without_an_anchor():
    m = extract_times("tomorrow at 4pm")[0]
    assert m.start is None and m.offset == {"days": 1}


@pytest.mark.parametrize("text,value,typ", [
    ("every Tuesday", "XXXX-WXX-2", "set"), ("for 3 days", "P3D", "duration"),
    ("this weekend", "2026-W48-WE", "date"), ("Q3", "2026-Q3", "date"),
])
def test_values(text, value, typ):
    m = one(text)
    assert (m.value, m.type) == (value, typ)


@pytest.mark.parametrize("text", [
    "Room 4 is on the 2nd floor", "a 4 by 4 truck", "May will call you", "meet at 6 Ajala Street",
    "it is a two-way street", "since day one", "for good",
])
def test_look_alikes_are_not_times(text):
    assert extract_times(text, anchor=A) == []


def test_yoruba_and_hausa_need_tone_marks_or_a_language():
    assert one("mu pade ni ọ̀la").start == "2026-11-26"
    assert extract_times("Ola will come", anchor=A) == []
    assert one("gobe da safe", language="ha").start == "2026-11-26"


@pytest.mark.parametrize("text", ["tomorrow " * 4000, "4 " * 8000, "every " * 5000, "3/" * 6000])
def test_long_text_is_quick(text):
    t = time.perf_counter()
    extract_times(text, anchor=A)
    assert time.perf_counter() - t < 3.0
