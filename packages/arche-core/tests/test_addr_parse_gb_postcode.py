# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""G-A4: a full GB postcode populates ``postal_code`` and leaves the town alone.

Before: ``parse_address("Flat 2, 10 Baker Street, London NW1 6XE")`` returned
``city='London NW1'`` and ``postal_code=None``. The tail grammar read the
outward code as a capitalised word and dropped the inward code.

The ten GIAS-shaped strings below follow the GIAS establishment address layout
(Street, Locality, Address3, Town, County, Postcode). Streets and towns are
real; the strings are assembled for the test and name no establishment.
"""

from __future__ import annotations

import pytest
from arche.addr import parse_address
from arche.addr.parse import normalise_gb_postcode


def test_the_reported_case():
    a = parse_address("Flat 2, 10 Baker Street, London NW1 6XE")
    assert a is not None
    assert a.components.postal_code == "NW1 6XE"
    assert a.components.city == "London"
    assert a.components.street == "Baker Street"
    assert a.country_inferred == "GB"
    assert a.raw.endswith("NW1 6XE")


# (address, postcode, city)
GIAS_LIKE = [
    ("Hollins Lane, Marple Bridge, Stockport, Cheshire, SK6 5BB", "SK6 5BB", "Stockport"),
    ("St Mary's Road, Huyton, Liverpool, Merseyside, L36 5SR", "L36 5SR", "Liverpool"),
    ("Mill Lane, Wingerworth, Chesterfield, Derbyshire, S42 6NG", "S42 6NG", "Chesterfield"),
    ("Church Road, Crystal Palace, London, SE19 2ET", "SE19 2ET", "London"),
    ("Princess Road, Moss Side, Manchester, M15 5UJ", "M15 5UJ", "Manchester"),
    ("Hall Green Road, West Bromwich, B71 3LB", "B71 3LB", "West Bromwich"),
    # spaceless, as some exports write it
    ("Green Lane, Coventry, CV36EA", "CV3 6EA", "Coventry"),
    # lower case, town and postcode in one comma part
    ("Cranbrook Avenue, Hull hu6 7tt", "HU6 7TT", "Hull"),
    # letter-final outward code, town and postcode in one part
    ("1 Long Lane, London EC1A 1BB", "EC1A 1BB", "London"),
    # the one non-geographic postcode, spaced and spaceless
    ("1 Girobank Road, Bootle, GIR 0AA", "GIR 0AA", "Bootle"),
    ("1 Girobank Road, Bootle GIR0AA", "GIR 0AA", "Bootle"),
]


@pytest.mark.parametrize("text,postcode,city", GIAS_LIKE)
def test_gias_like_addresses(text, postcode, city):
    a = parse_address(text)
    assert a is not None, text
    assert a.components.postal_code == postcode
    assert a.components.city == city
    assert a.country_inferred == "GB"
    # The postcode never leaks into a locality component.
    for part in (a.components.city, a.components.neighborhood,
                 a.components.area, a.components.region):
        assert part is None or postcode.split()[0] not in part.upper().split()


def test_locality_and_county_keep_their_slots():
    a = parse_address("Hollins Lane, Marple Bridge, Stockport, Cheshire, SK6 5BB")
    assert a.components.neighborhood == "Marple Bridge"
    assert a.components.region == "Cheshire"


@pytest.mark.parametrize("raw,expected", [
    ("NW1 6XE", "NW1 6XE"), ("nw16xe", "NW1 6XE"), ("SW1A2AA", "SW1A 2AA"),
    ("ec1a 1bb", "EC1A 1BB"), ("GIR0AA", "GIR 0AA"), ("M1 1AE", "M1 1AE"),
    ("B33 8TH", "B33 8TH"),
    ("NW1", None), ("101001", None), ("8001", None), ("GA-039-2345", None), ("", None),
])
def test_normalise_gb_postcode(raw, expected):
    assert normalise_gb_postcode(raw) == expected


class TestOtherJurisdictionsUnchanged:
    def test_ng(self):
        a = parse_address("7B Allen Avenue, Ikeja, Lagos, Nigeria")
        assert (a.components.city, a.components.neighborhood) == ("Lagos", "Ikeja")
        assert a.components.postal_code is None
        assert a.country_inferred == "NG"

    def test_ng_postal(self):
        a = parse_address("Plot 14, Awolowo Road, Ikoyi, Lagos, 101001")
        assert a.components.postal_code == "101001"
        assert a.country_inferred == "NG"

    def test_za(self):
        a = parse_address("12 Long Street, Cape Town, 8001")
        assert a.components.city == "Cape Town"
        assert a.components.postal_code == "8001"
        assert a.country_inferred == "ZA"

    def test_an_outward_code_alone_is_not_a_postcode(self):
        a = parse_address("10 Baker Street, London NW1")
        assert a.components.postal_code is None
