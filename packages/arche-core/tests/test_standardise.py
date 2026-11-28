# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0
"""`standardise`: organisation names written two ways compare as one."""

from __future__ import annotations

import pytest
from arche.resolve import ENTITY_PACKS, reconcile
from arche.resolve._standardise import pin, standardise


@pytest.mark.parametrize("raw, want", [
    ("MARKS AND SPENCER P.L.C.", "MARKS AND SPENCER PLC"),
    ("Marks & Spencer PLC", "Marks and Spencer PLC"),
    ("Premier Quilting Co Ltd", "Premier Quilting company Ltd"),
    ("Smith Bros.", "Smith brothers"),
    ("O.A. Taylor & Sons Ltd.", "O A Taylor and Sons Ltd."),
    ("M & S Poultry", "M & S Poultry"),
], ids=["dotted-plc", "ampersand", "co", "bros", "initials", "initials-ampersand"])
def test_standard_forms(raw, want):
    assert standardise(raw) == want


@pytest.mark.parametrize("raw", [
    "M&M Seafood Ltd",                 # "&" inside a name is the name
    "Karfi Agro Co-operative Soc.",    # a hyphen joins: Co-operative is not Co
    "Co-op Food",
    "P.J.MARTINELLI LIMITED",          # initials run into a word: left alone
], ids=["inner-ampersand", "co-operative", "co-op", "glued-initials"])
def test_left_alone(raw):
    assert standardise(raw) == raw


@pytest.mark.parametrize("a, b", [
    ("MARKS & SPENCER PLC", "MARKS AND SPENCER P.L.C."),
    ("Premier Quilting Co Ltd", "PREMIER QUILTING COMPANY LIMITED"),
    ("Smith & Sons Ltd", "SMITH AND SONS LIMITED"),
], ids=["m-and-s", "co-company", "and-sons"])
def test_one_company_written_two_ways_matches_exactly(a, b):
    m = reconcile([{"id": "a", "name": a}], [{"id": "b", "name": b}],
                  entity="legal_entity", id_field="id")["matches"]
    assert m and m[0]["decision"] == "match" and m[0]["score"] == 1.0


def test_a_legal_form_conflict_still_holds():
    # Standardising must not paper over a real difference.
    m = reconcile([{"id": "a", "name": "Zenith Bank Plc"}],
                  [{"id": "b", "name": "Zenith Bank Limited"}],
                  entity="legal_entity", id_field="id")["matches"]
    assert m and m[0]["decision"] == "review"


def test_on_for_organisation_packs_only_and_pinned():
    for pack in ("organisation", "site", "legal_entity"):
        assert all(s.get("standardise") == "organisation"
                   for s in ENTITY_PACKS[pack] if s.get("field") == "name")
    for pack in ("person", "place"):
        assert not any(s.get("standardise") for s in ENTITY_PACKS[pack])
    pins = reconcile([{"id": "a", "name": "x"}], [{"id": "b", "name": "x"}],
                     entity="organisation", id_field="id")["pins"]["data_assets"]
    assert pins["name_standards:organisation"] == pin("organisation")


def test_an_unknown_domain_is_refused():
    with pytest.raises(ValueError, match="unknown standardise domain"):
        standardise("Acme & Co", "nope")
