# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Addresses with no street in common are compared by their place words."""

from __future__ import annotations

import pytest
from arche.resolve._matcher import _place_word_overlap, compare_addresses


def test_generic_words_are_not_evidence():
    assert _place_word_overlap(
        "Kanyiri Road, near the Market", "Obodo Road, near the Market") == 0.0


def test_a_misspelt_place_word_counts_once():
    assert _place_word_overlap("Kanyiri Stage", "Kanyirri Stage") == 1.0
    assert _place_word_overlap("Kanyiri", "Kanyirri Kanyyiri") < 1.0


def test_a_number_must_be_equal():
    assert _place_word_overlap("Area 3 Temanu", "Area 4 Temanu") < 1.0


def test_no_place_words_is_not_a_score():
    assert _place_word_overlap("the road", "Kanyiri") is None


def test_unrelated_landmarks_score_low():
    a, b = "Temanu Stage, Opposite Ajala Superstore", "Obodo Junction, Behind Kanyiri Mosque"
    assert compare_addresses(a, b) < 0.4


def test_one_place_with_two_landmarks_scores_above_two_places():
    one = compare_addresses("Temanu Stage, Opposite Ajala Superstore",
                            "Temanu Stage, opposite Obodo Superstore")
    two = compare_addresses("Temanu Stage, Opposite Ajala Superstore",
                            "Kanyiri Stage, opposite Obodo Superstore")
    assert one > two


def test_word_order_does_not_matter():
    assert compare_addresses("Temanu Kanyiri", "Kanyiri Temanu") == 1.0


def test_identical_text_is_one():
    assert compare_addresses("the road", "the road") == 1.0


@pytest.mark.parametrize("a,b", [
    ("Ashgrove House", "Ashgrove House, Pondwell Business Technology Park"),
    ("Ground Floor, Ashgrove House", "3rd Floor, Ashgrove House"),
    ("C/O Temanu Ltd, Kanyiri Plaza", "Kanyiri Plaza"),
])
def test_one_named_building_is_one_address(a, b):
    assert compare_addresses(a, b) >= 0.7
    assert compare_addresses(a, b) == compare_addresses(b, a)


@pytest.mark.parametrize("a,b", [
    ("Ashgrove House, 12 Obodo Road", "Ashgrove House, 90 Pondwell Lane"),
    ("60 Ashgrove Business Centre", "Office 67 Ashgrove Business Centre"),
    ("Ashgrove Business Centre", "Pondwell Business Centre"),
    ("Obodo Road, Temanu", "Kanyiri House, Temanu"),
])
def test_two_buildings_are_not(a, b):
    assert compare_addresses(a, b) < 0.7


def test_a_long_text_is_read_in_linear_time():
    import time

    start = time.perf_counter()
    for text in ("ajala " * 50_000 + "house", "1 " * 50_000 + "floor", "1-" * 50_000):
        compare_addresses(text, "Ashgrove House, 12 Obodo Road")
    assert time.perf_counter() - start < 2.0
