# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""The place list, and the parser's use of it to split places with no comma between.

Real town names are GeoNames facts; the streets are invented.
"""

from __future__ import annotations

import pytest
from arche.addr import parse_address, parse_locality, places


@pytest.fixture(autouse=True)
def _clean_registry():
    places.clear_registered_places()
    yield
    places.clear_registered_places()


def test_lookup_ranks_a_city_above_a_village():
    assert places.town_rank("Ibadan") >= 5
    assert places.focus_rank("Ibadan") >= 5      # Nigeria is covered in full
    assert places.town_rank("Manchester") >= 5
    assert places.focus_rank("Manchester") == 0  # the UK is not
    assert places.lookup("Kanyiri Ashgrove Temanu") is None


def test_lookup_folds_case_and_punctuation():
    assert places.lookup("PORT-HARCOURT") == places.lookup("port harcourt")


def test_regions_are_known():
    assert places.lookup("Kiambu").region
    assert places.lookup("Oyo State").region


def test_register_places_adds_and_never_lowers():
    assert places.lookup("Temanu") is None
    assert places.register_places([["Temanu", "NG", "town", 4]]) == 1
    assert places.focus_rank("Temanu") == 4
    places.register_places([["Ibadan", "NG", "town", 2]])
    assert places.focus_rank("Ibadan") >= 5
    places.clear_registered_places()
    assert places.lookup("Temanu") is None


@pytest.mark.parametrize(("text", "neighborhood", "city"), [
    ("22 Ajala Road Ibadan", None, "Ibadan"),                     # no comma before the town
    ("6 Ajala Street, Kanyiri Ibadan", "Kanyiri", "Ibadan"),       # an area, then the town
    ("6 Ajala Street, Off Obodo Road Ibadan", None, "Ibadan"),     # the town after a landmark
    ("8 Ajala Close, Benin City", None, "Benin City"),             # a two-word town stays whole
])
def test_town_with_no_comma(text, neighborhood, city):
    c = parse_address(text).components
    assert (c.neighborhood, c.city) == (neighborhood, city)


def test_larger_to_smaller_without_a_street():
    c = parse_locality("Kumasi Kanyiri")
    assert (c.city, c.neighborhood) == ("Kumasi", "Kanyiri")


def test_no_split_outside_the_full_coverage_countries():
    # "Side" is a town in Turkey; "Moss Side" is one place in Manchester.
    c = parse_address("Ajala Road, Moss Side, Manchester, M15 5UJ").components
    assert c.neighborhood == "Moss Side"


def test_no_split_of_a_place_noun_or_a_postcode():
    assert parse_address("6 Ajala Street, Kanyiri Estate, Ibadan").components.neighborhood \
        == "Kanyiri Estate"
    assert parse_address("1 Ajala Road, Bootle, GIR 0AA").components.postal_code == "GIR 0AA"
