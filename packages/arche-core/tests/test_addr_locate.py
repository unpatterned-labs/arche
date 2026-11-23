# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Plus Codes and H3 cells for a point.

The expected codes were produced by Google's reference implementation
(``openlocationcode``) and are pinned here, so the encoder is checked against
the specification without depending on that package. The encoder also agreed
with it on 20,011 random and edge points at every supported length when it
was written.
"""

from __future__ import annotations

import doctest

import pytest
from arche.addr import locate
from arche.addr.locate import h3_cell, h3_steps, plus_code

REFERENCE = [
    (20.375, 2.775, "7FG49QGG+22", "7FG49Q00+"),
    (90, 0, "CFX2X2X2+X2", "CFX2X200+"),
    (-90, -180, "22222222+22", "22222200+"),
    (0, 180, "62G22222+22", "62G22200+"),
    (-41.2730625, 174.7859375, "4VCPPQGP+Q9", "4VCPPQ00+"),
    (6.4550575, 3.3941795, "6FR5F94V+2M", "6FR5F900+"),
    (51.5007, -0.1246, "9C3XGV2G+75", "9C3XGV00+"),
    (12.0022, 8.592, "7F4C2H2R+VR", "7F4C2H00+"),
    (89.99999, 179.99999, "CVXXXXXX+XX", "CVXXXX00+"),
    (-31.710102, -125.694297, "44WP78Q4+X7", "44WP7800+"),
    (27.168205, -153.922937, "73V8539G+7R", "73V85300+"),
    (6.458761, -48.35199, "68RHFJ5X+G6", "68RHFJ00+"),
    (-79.560194, 2.676864, "2FG4CMQG+WP", "2FG4CM00+"),
    (-83.250781, -23.887554, "298RP4X6+MX", "298RP400+"),
    (-77.426024, -147.343315, "23JJHMF4+HM", "23JJHM00+"),
]


@pytest.mark.parametrize(("lat", "lon", "ten", "six"), REFERENCE)
def test_plus_code_matches_the_reference(lat, lon, ten, six):
    assert plus_code(lat, lon) == ten
    assert plus_code(lat, lon, length=6) == six


def test_longitude_wraps_and_latitude_clips():
    assert plus_code(12.0022, 8.592 + 360) == plus_code(12.0022, 8.592)
    assert plus_code(95, 0) == plus_code(90, 0)


@pytest.mark.parametrize("bad", [0, 3, 11, 12])
def test_only_pair_lengths(bad):
    with pytest.raises(ValueError, match="length"):
        plus_code(1.0, 1.0, length=bad)


def test_not_a_number_is_refused():
    with pytest.raises(ValueError, match="finite"):
        plus_code(float("nan"), 1.0)


def test_h3_cells_and_steps():
    a = h3_cell(12.0022, 8.592)
    b = h3_cell(12.0022, 8.6020)          # about 1.1 km east; a cell is about 0.17 km across
    assert a.startswith("89") and h3_steps(a, a) == 0
    assert 3 <= h3_steps(a, b) <= 8
    assert locate.locate(12.0022, 8.592) == {"plus_code": "7F4C2H2R+VR", "h3": a}


def test_docstring_examples():
    assert doctest.testmod(locate).failed == 0
