# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""UK and US addresses that close with a postcode or a state and ZIP.

Town names and postcode areas are real; the streets are invented.
"""

from __future__ import annotations

import pytest
from arche.addr import parse_address, parse_locality


def _c(text: str):
    a = parse_address(text)
    assert a is not None, text
    return a.components


@pytest.mark.parametrize(("text", "city", "postcode"), [
    ("145 Ajala Road Bristol BS8 2QB", "Bristol", "BS8 2QB"),            # no commas
    ("145 AJALA ROAD BRISTOL BS8 2QB", "BRISTOL", "BS8 2QB"),
    ("33 Ajala Road, Burton on Trent, DE15 0LQ", "Burton on Trent", "DE15 0LQ"),
    ("8 Ajala Street, St. Helens, WA10 1HJ", "St Helens", "WA10 1HJ"),
    ("39 Ajala Road, Old Trafford, Stretford, Manchester, M16 9NH", "Manchester", "M16 9NH"),
    ("5 Ajala Lane, Marple, Stockport, Cheshire, SK6 5BB", "Stockport", "SK6 5BB"),   # a county
    ("68 Ajala Road, Earls Court, SW5 0RD", "Earls Court", "SW5 0RD"),   # a town named like a road
])
def test_gb_postcode_closes_the_address(text, city, postcode):
    c = _c(text)
    assert (c.city, c.postal_code) == (city, postcode)


def test_an_area_before_the_town_without_commas():
    c = _c("198 Ajala Road Mapperley Nottingham NG3 6LH")
    assert (c.neighborhood, c.city) == ("Mapperley", "Nottingham")


@pytest.mark.parametrize(("text", "number", "street", "city", "state", "zip_"), [
    ("8 Ajala Street, Bellport NY 11713", "8", "Ajala Street", "Bellport", "NY", "11713"),
    ("8 ajala street, bellport ny 11713, us", "8", "ajala street", "bellport", "ny", "11713"),
    ("12770 Ajala Parkway, Plainview, NY 11803",
     "12770", "Ajala Parkway", "Plainview", "NY", "11803"),
])
def test_us_state_and_zip(text, number, street, city, state, zip_):
    c = _c(text)
    assert (c.street_number, c.street, c.city, c.region, c.postal_code) == (
        number, street, city, state, zip_)


def test_a_direction_closes_a_street_name():
    assert _c("24 Ajala Road South, Uxbridge, UB10 8HB").street == "Ajala Road South"


def test_a_code_after_the_town_in_a_comma_part():
    c = _c("12 Ajala Lane, Westlands, Nairobi 00100")
    assert (c.city, c.postal_code) == ("Nairobi", "00100")


def test_a_bare_number_without_commas_is_not_a_postcode():
    assert _c("8 ajala street kanyiri obodo 4223 nsw").postal_code is None


def test_locality_with_a_postcode():
    c = parse_locality("Kanyiri, Stoke On Trent, ST6 7ER")
    assert (c.neighborhood, c.city, c.postal_code) == ("Kanyiri", "Stoke On Trent", "ST6 7ER")
