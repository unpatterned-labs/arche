# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Reading an address costs no more than its length: PII detection runs this on any text."""

from __future__ import annotations

import time

import pytest
from arche.addr import parse_addresses, parse_locality
from arche.resolve._matcher import compare_addresses

SHIP = "we ship from 12 Ajala Street, Ibadan to 4 Obodo Road, Lagos and then rest of the week "


def _seconds(fn, *args) -> float:
    best = 9.9
    for _ in range(3):
        t = time.perf_counter()
        fn(*args)
        best = min(best, time.perf_counter() - t)
    return best


@pytest.mark.parametrize("make", [
    lambda n: SHIP * n,                                      # one long line
    lambda n: "12 Ajala Street" + " , " * n * 10 + "x",      # commas
    lambda n: "12 Ajala Street" + " " * n * 10 + "x",        # spaces
    lambda n: "12 Ajala Street, " + "Temanu " * n * 10,      # words
    lambda n: "12 Ajala Street, " + "1234 " * n * 10,        # numbers
])
def test_parse_addresses_is_not_quadratic(make):
    parse_addresses(make(10))                                # load the place list
    small, large = _seconds(parse_addresses, make(40)), _seconds(parse_addresses, make(320))
    # eight times the text: well under the 64 times a quadratic would cost
    assert large < max(0.5, 30 * small)


@pytest.mark.parametrize("text", [
    "Temanu Ajala " * 3200, "Temanu" + " , " * 3200 + "x", "Temanu - " * 3200])
def test_parse_locality_stays_quick(text):
    assert _seconds(parse_locality, text) < 1.0


def test_compare_addresses_stays_quick():
    assert _seconds(compare_addresses, "Temanu " * 3000, "Kanyiri " * 3000) < 2.0
