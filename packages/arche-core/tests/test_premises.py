# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""The premises comparator: does an address name the same door?

Guards the bug it was built for -- two suppliers of one name at different
addresses merged, because ``address`` carries weight 1.0 against name's 4.0 and
a similarity over the whole string cannot see a changed digit anyway.
"""

from __future__ import annotations

import pytest

from arche.resolve import COMPARATOR_NOTES, ENTITY_PACKS, crosswalk
from arche.resolve._premises import compare_premises, premises_designator

# ---------------------------------------------------------------------------
# Extraction
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "address,expected",
    [
        # Explicit designators. `Unit`/`Plot`/`Stall` are what industrial and
        # market addressing actually uses, and are exactly what a street-address
        # parser drops.
        ("Unit 4, Trafford Park Industrial Estate, Manchester", "4"),
        ("Plot 88, Ikeja Industrial Scheme, Lagos", "88"),
        ("Suite 300B, Adeola Odeku Street, Victoria Island", "300b"),
        ("Flat 2, Marina Court, Lagos Island", "2"),
        ("Block 7, Kano Free Trade Zone", "7"),
        ("Shop 15, Balogun Market, Lagos", "15"),
        ("Stall 42, Kurmi Market, Kano", "42"),
        ("No. 12 Zaria Road, Kano", "12"),
        ("#5 Awolowo Road, Ikoyi", "5"),
        # Leading street number, the anglophone convention.
        ("12 Zaria Road, Kano", "12"),
        ("221B Baker Street, London", "221b"),
        # Trailing number, the German/Dutch convention. Only the first
        # comma-delimited segment is searched.
        ("An der Gehespitz 50, 63263 Neu-Isenburg", "50"),
        ("Keizersgracht 174, 1016 DW Amsterdam", "174"),
    ],
)
def test_designator_is_recovered(address, expected):
    assert premises_designator(address) == expected


@pytest.mark.parametrize(
    "address",
    [
        # No number at all. `None` is the honest answer and must not become a
        # designator, because a fabricated one would refute a true pair.
        "Trafford Park Industrial Estate, Manchester",
        "Ikeja Industrial Scheme, Lagos",
        "Victoria Island, Lagos",
        "",
        None,
        # A postcode is not a premises. Five and six digits are beyond the
        # trailing pattern's 1-4, and the lookbehind blocks a partial bite.
        "Ikeja 100001",
        "Neu-Isenburg 63263",
    ],
)
def test_silence_is_not_a_designator(address):
    assert premises_designator(address) is None


def test_designator_is_case_folded():
    assert premises_designator("221B Baker Street") == premises_designator(
        "221b baker street"
    )


def test_first_designator_wins():
    # `Unit 4, 12 Zaria Road` states the door first. Both records in a pair are
    # read the same way, so the rule only has to be consistent.
    assert premises_designator("Unit 4, 12 Zaria Road, Kano") == "4"


def test_long_input_is_bounded():
    # A pasted document in an address field must not become a scan of it.
    assert premises_designator("x" * 5000 + " Unit 9") is None


# ---------------------------------------------------------------------------
# Comparison contract
# ---------------------------------------------------------------------------


def test_same_door_agrees():
    assert compare_premises("12 Zaria Road, Kano", "12 Zaria Rd, Kano State") == 1.0


def test_different_door_refutes():
    assert compare_premises("Unit 4, Trafford Park", "Unit 9, Trafford Park") == 0.0


def test_different_convention_same_door():
    # `No. 12 Zaria Road` and `12 Zaria Road` are one address written two ways.
    assert compare_premises("No. 12 Zaria Road", "12 Zaria Road") == 1.0


@pytest.mark.parametrize(
    "left,right",
    [
        ("12 Zaria Road, Kano", "Zaria Road, Kano"),
        ("Trafford Park Estate", "Unit 9, Trafford Park Estate"),
        ("Victoria Island, Lagos", "Ikeja, Lagos"),
        ("", "12 Zaria Road"),
    ],
)
def test_silence_never_refutes(left, right):
    # THE contract every refuting comparator here follows: an absent field is
    # missing evidence, never a disagreement. A comparator returning 0.0 for a
    # silent address would refute most true pairs in any real supplier list.
    assert compare_premises(left, right) is None


def test_agreement_is_weak_by_construction():
    # Weight 0.0 in the pack: every street has a number 12, so agreeing on one
    # must not raise the score. Only the disagreement carries information.
    spec = next(s for s in ENTITY_PACKS["organisation"] if s.get("kind") == "premises")
    assert spec["weight"] == 0.0
    assert spec["refutes_below"] == 0.5


def test_comparator_is_documented():
    # `test_describe_pack.py` guards this globally; named here so a failure
    # points at the comparator that lost its note rather than at the guard.
    assert "premises" in COMPARATOR_NOTES


# ---------------------------------------------------------------------------
# The bug, end to end
# ---------------------------------------------------------------------------


_LEFT = [
    {
        "id": "a",
        "name": "Karfi Agro Cooperative Society Ltd",
        "address": "12 Zaria Road, Kano",
    }
]


def _decide(record):
    matches = crosswalk(_LEFT, [record], entity="organisation", id_field="id")["matches"]
    return matches[0]["decision"] if matches else None


def test_same_supplier_still_matches():
    assert (
        _decide(
            {
                "id": "b",
                "name": "Karfi Agro Co-operative Soc.",
                "address": "12 Zaria Rd, Kano State",
                "registration_id": "RC-889112",
            }
        )
        == "match"
    )


def test_same_name_different_door_is_held():
    # The reported bug. Before the comparator existed this was `match`.
    assert (
        _decide(
            {
                "id": "c",
                "name": "Karfi Agro Cooperative Society Ltd",
                "address": "8 Murtala Way, Kaduna",
            }
        )
        == "review"
    )


def test_same_street_different_number_is_held():
    # The hard case: the addresses agree on almost every token, so the
    # similarity score cannot separate them and only the digit can.
    assert (
        _decide(
            {
                "id": "d",
                "name": "Karfi Agro Cooperative Society Ltd",
                "address": "48 Zaria Road, Kano",
            }
        )
        == "review"
    )


def test_missing_address_still_matches():
    assert _decide({"id": "e", "name": "Karfi Agro Cooperative Society Ltd"}) == "match"


def test_address_without_a_number_still_matches():
    assert (
        _decide(
            {
                "id": "f",
                "name": "Karfi Agro Cooperative Society Ltd",
                "address": "Trafford Park Estate, Kano",
            }
        )
        == "match"
    )


def test_refutation_demotes_and_never_rejects():
    # The justification for refuting on a field a company may legitimately
    # differ on: the worst outcome is a human glance, never a dropped pair. A
    # registered office and an operational site reach a reviewer, not the bin.
    matches = crosswalk(
        _LEFT,
        [
            {
                "id": "g",
                "name": "Karfi Agro Cooperative Society Ltd",
                "address": "8 Murtala Way, Kaduna",
            }
        ],
        entity="organisation",
        id_field="id",
    )["matches"]
    assert [m["decision"] for m in matches] == ["review"]
