# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""On one road, a house number that does not agree is not agreement."""

from __future__ import annotations

import pytest
from arche.resolve import reconcile
from arche.resolve._matcher import compare_addresses, compare_house_numbers

SAME = 0.70  # callers read a score at or above this as the same address


@pytest.mark.parametrize("a,b", [
    ("124 Ashgrove Road, Leeds LS2 7HZ", "128 Ashgrove Road, Leeds LS2 7HZ"),
    ("124 Ashgrove Road, Leeds", "Ashgrove Road, Leeds"),
    ("124-128 Ashgrove Road, Leeds LS2 7HZ", "126 Ashgrove Road, Leeds LS2 7HZ"),
    ("82A Ashgrove Road, Leeds LS2 7HZ", "82 Ashgrove Road, Leeds LS2 7HZ"),
    ("12 Ajala Street, Ibadan", "14 Ajala Street, Ibadan"),
])
def test_a_number_that_does_not_agree_is_never_the_same_address(a, b):
    assert compare_addresses(a, b) < SAME
    assert compare_addresses(b, a) == compare_addresses(a, b)


@pytest.mark.parametrize("a,b", [
    ("124 Ashgrove Road, Leeds LS2 7HZ", "124 Ashgrove Rd, Leeds, LS2 7HZ"),
    ("12 Ajala Street, Ibadan", "No. 12 Ajala St, Ibadan"),
    ("48 - 52 Ashgrove Road, Leeds", "48-52 Ashgrove Road, Leeds"),
    ("48\u201352 Ashgrove Road, Leeds", "48-52 Ashgrove Road, Leeds"),
    ("48 TO 52 Ashgrove Road, Leeds", "48-52 Ashgrove Road, Leeds"),
    ("C O Temanu LLP 1 Ashgrove Road, Leeds", "1 Ashgrove Road, Leeds"),
    ("48-52 5th Floor Ashgrove Road, Leeds", "48-52 Ashgrove Road, Leeds"),
    ("48 to 52 Ashgrove Road, Leeds", "48-52 Ashgrove Road, Leeds"),
    ("Unit 82A Ashgrove Road, Leeds", "82A Ashgrove Road, Leeds"),
])
def test_one_address_written_two_ways_still_agrees(a, b):
    assert compare_addresses(a, b) >= 0.9


@pytest.mark.parametrize("a,b,expected", [
    ("124 Ashgrove Road", "124 Ashgrove Rd", 1.0),
    ("Ashgrove Road", "124 Ashgrove Road", 0.5),
    ("124-128 Ashgrove Road", "124 Ashgrove Road", 0.25),
    ("82A Ashgrove Road", "82 Ashgrove Road", 0.25),
    ("124 Ashgrove Road", "128 Ashgrove Road", 0.0),
    ("124 Ashgrove Road", "124 Pondwell Lane", None),
    ("Ashgrove Road", "Ashgrove Road", None),
])
def test_house_numbers_on_their_own(a, b, expected):
    assert compare_house_numbers(a, b) == expected
    assert compare_house_numbers(b, a) == expected


def _decision(a, b, refutes_below):
    pack = [{"field": "address", "kind": "tokenset", "weight": 1.0},
            {"field": "address", "kind": "address", "weight": 1.0}]
    if refutes_below:
        pack.append({"field": "address", "kind": "house_number", "weight": 0.0,
                     "refutes_below": refutes_below})
    out = reconcile([{"id": "a", "address": a}], [{"id": "b", "address": b}], pack,
                    block=None, id_field="id")
    return out["matches"][0]["decision"] if out["matches"] else None


def test_the_comparator_holds_what_an_average_outvotes():
    assert _decision("Ashgrove Road", "128 Ashgrove Road", None) == "match"
    assert _decision("Ashgrove Road", "128 Ashgrove Road", 0.6) == "review"


def test_the_threshold_says_what_is_held():
    pair = ("124-128 Ashgrove Road", "124 Ashgrove Road")
    assert _decision(*pair, 0.2) == "match"
    assert _decision(*pair, 0.4) == "review"
    assert _decision("128 Ashgrove Road", "128 Ashgrove Road", 0.6) == "match"


@pytest.mark.parametrize("a,b", [
    ("Room 3, Ashgrove House, 12 Obodo Road", "Room 4, Ashgrove House, 12 Obodo Road"),
    ("Unit 5, 12 Ajala Street, Leeds LS2 7HZ", "Unit 6, 12 Ajala Street, Leeds LS2 7HZ"),
    ("Unit 2A, Pondwell Estate", "Unit 2B, Pondwell Estate"),
    ("Block C Flat 4, Ajala Estate", "Block D Flat 4, Ajala Estate"),
    ("Shop 14, Kanyiri Plaza, Temanu", "Shop 15, Kanyiri Plaza, Temanu"),
    ("Suite RA01, 195 Ajala Street", "Suite RA02, 195 Ajala Street"),
])
def test_two_units_of_one_building_are_two_addresses(a, b):
    assert compare_addresses(a, b) < SAME
    assert compare_addresses(b, a) == compare_addresses(a, b)


@pytest.mark.parametrize("a,b", [
    ("Unit 5, 12 Ajala Street, Leeds", "12 Ajala Street, Unit 5, Leeds"),
    ("Shop 14 Kanyiri Plaza", "Kanyiri Plaza, Shop No. 14"),
    ("Flat 04, 12 Ajala Street", "Flat 4, 12 Ajala Street"),
    ("Unit E04, Ashgrove Business Centre", "Unit E4, Ashgrove Business Centre"),
    ("Flat 3, 12 Ajala Street", "12 Ajala Street"),          # one side silent says nothing
    ("3rd Floor, Ashgrove House", "5th Floor, Ashgrove House"),  # floors of one building
    ("the office at Ashgrove House", "Ashgrove House"),
])
def test_a_unit_written_another_way_or_not_at_all_is_not_a_difference(a, b):
    assert compare_addresses(a, b) >= SAME
