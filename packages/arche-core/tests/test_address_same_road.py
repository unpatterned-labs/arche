# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""An address with no commas can read the line before the street into the street name."""

from __future__ import annotations

import pytest
from arche.resolve._matcher import compare_addresses


def test_the_line_before_the_street_does_not_make_it_another_road():
    assert compare_addresses("8 kanyiri ajala crescent", "8 ajala crescent") >= 0.95


@pytest.mark.parametrize(("a", "b"), [
    ("8 old ajala road", "8 ajala road"),            # a qualifier names another road
    ("8 kanyiri ajala crescent", "9 ajala crescent"),  # another house number
])
def test_different_roads_or_numbers_stay_apart(a, b):
    assert compare_addresses(a, b) < 0.9
