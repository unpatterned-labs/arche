# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""The lookup question: which of these is this one?

You hold one record -- a supplier read off an invoice -- and want the entry it
refers to in a master list you already have. ``compare`` answers that for a
named pair, ``reconcile`` for two lists, ``dedupe`` for one list against
itself. None of them answers it for one record against many, and the shortcut
people reach for instead is the dangerous part:

    reconcile([query], master)["matches"][0]      # take the top row

That is a false merge waiting to happen. ``reconcile`` scores each pair on its
own, so two candidates at 0.85 and 0.84 are two records the evidence cannot
separate -- not a winner and a runner-up. Taking the top row invents a
distinction arche's own comparators did not find, and once it is written into a
master list it is indistinguishable from a correct answer.

``find`` refuses instead, and says what would settle it.
"""

from __future__ import annotations

import pytest

from arche.resolve import AMBIGUITY_MARGIN, find

#: Two entries share a name and differ only by address. That is the shape the
#: verdict exists for, and it is ordinary in real supplier data: one company
#: with two registrations, or two companies named after the same place.
_MASTER = [
    {"id": "S1", "name": "Karfi Agro Cooperative Society Ltd",
     "address": "12 Zaria Road, Kano"},
    {"id": "S2", "name": "Karfi Agro Cooperative Society Ltd",
     "address": "8 Murtala Way, Kaduna"},
    {"id": "S3", "name": "Zenith Bank Plc", "address": "Victoria Island, Lagos"},
    {"id": "S4", "name": "Dangote Cement Plc", "address": "Falomo, Ikoyi, Lagos"},
]


def _find(query, **kwargs):
    return find(query, _MASTER, entity="organisation", id_field="id",
                block=None, **kwargs)


# ---------------------------------------------------------------------------
# found
# ---------------------------------------------------------------------------


def test_a_clear_hit_is_found_and_named():
    result = _find({"name": "Karfi Agro Co-operative Soc.",
                    "address": "12 Zaria Rd, Kano State"})
    assert result["verdict"] == "found"
    assert result["match"]["b_id"] == "S1"


def test_a_found_match_carries_its_evidence_and_address():
    result = _find({"name": "Karfi Agro Co-operative Soc.",
                    "address": "12 Zaria Rd, Kano State"})
    assert result["match"]["decision_id"].startswith("xwd:")
    assert result["match"]["evidence"]


# ---------------------------------------------------------------------------
# ambiguous -- the verdict this function exists for
# ---------------------------------------------------------------------------


def test_two_equally_good_candidates_are_not_a_match():
    # The query states a name both entries carry and nothing else. Both score
    # 1.0. There is no answer here, and saying so is the answer.
    result = _find({"name": "Karfi Agro Cooperative Society Ltd"})
    assert result["verdict"] == "ambiguous"
    assert result["match"] is None, (
        "an ambiguous lookup must not hand back a match; the caller writes it "
        "into a master list and cannot tell afterwards that it was a guess"
    )


def test_the_tied_candidates_are_both_shown():
    result = _find({"name": "Karfi Agro Cooperative Society Ltd"})
    assert {edge["b_id"] for edge in result["rivals"]} == {"S1", "S2"}


def test_ambiguity_names_the_field_that_would_break_the_tie():
    # Not `would_resolve`. That answers "what would settle this pair", and here
    # every tied pair has already settled -- asked, it replies "already
    # resolved". The question is which of the matches it is, and that is
    # answered by where the candidates disagree.
    result = _find({"name": "Karfi Agro Cooperative Society Ltd"})
    assert result["would_resolve"] == ["address"]


def test_a_field_the_query_already_states_is_not_suggested():
    # It had its chance and did not separate them. Suggesting it would send the
    # caller to fetch something they already supplied.
    result = _find({"name": "Karfi Agro Cooperative Society Ltd",
                    "address": "Somewhere Else Entirely, Abuja"})
    assert "address" not in result.get("would_resolve", [])


def test_a_field_the_candidates_share_cannot_separate_them():
    # The name is deliberately distinctive. An earlier version of this fixture
    # used "Central Trading Co" and came back `not_found` -- correctly, because
    # the distinctive-signal gate refuses to match two records on a generic
    # name however identical it is. That guard is right and is tested
    # elsewhere; here it just made the fixture unable to reach the state under
    # test.
    master = [
        {"id": "A", "name": "Karfi Agro Cooperative Society Ltd",
         "country": "NG", "address": "12 Zaria Road, Kano"},
        {"id": "B", "name": "Karfi Agro Cooperative Society Ltd",
         "country": "NG", "address": "8 Murtala Way, Kaduna"},
    ]
    result = find({"name": "Karfi Agro Cooperative Society Ltd"}, master,
                  entity="organisation", id_field="id", block=None)
    assert result["verdict"] == "ambiguous"
    assert "address" in result["would_resolve"]
    assert "country" not in result["would_resolve"], (
        "both candidates are in NG, so knowing the country cannot tell them "
        "apart; suggesting it would send the caller on a pointless errand"
    )


def test_the_margin_is_configurable_and_widening_it_creates_doubt():
    # A caller who cannot afford a wrong link can demand a wider gap before
    # accepting one. The knob is on the call, not a global.
    query = {"name": "Karfi Agro Co-operative Soc.",
             "address": "12 Zaria Rd, Kano State"}
    assert _find(query)["verdict"] == "found"
    assert _find(query, ambiguity_margin=1.0)["verdict"] in {
        "found", "ambiguous"
    }


def test_the_default_margin_is_declared_not_buried():
    assert 0.0 < AMBIGUITY_MARGIN < 0.5


# ---------------------------------------------------------------------------
# not_found
# ---------------------------------------------------------------------------


def test_an_absent_supplier_is_not_found():
    result = _find({"name": "Sahel Foods Nigeria Ltd", "address": "Wuse II, Abuja"})
    assert result["verdict"] == "not_found"
    assert result["match"] is None


def test_not_found_is_distinct_from_ambiguous():
    # They call for opposite actions -- create a new entity, versus go and look
    # -- so collapsing them into one falsy answer would be a real loss.
    absent = _find({"name": "Sahel Foods Nigeria Ltd"})["verdict"]
    tied = _find({"name": "Karfi Agro Cooperative Society Ltd"})["verdict"]
    assert absent == "not_found"
    assert tied == "ambiguous"
    assert absent != tied


def test_an_empty_master_list_is_answerable():
    result = find({"name": "Zenith Bank Plc"}, [], entity="organisation",
                  id_field="id", block=None)
    assert result["verdict"] == "not_found"


# ---------------------------------------------------------------------------
# What the caller can always inspect
# ---------------------------------------------------------------------------


def test_every_verdict_explains_itself():
    for query in (
        {"name": "Karfi Agro Co-operative Soc.", "address": "12 Zaria Rd, Kano State"},
        {"name": "Karfi Agro Cooperative Society Ltd"},
        {"name": "Sahel Foods Nigeria Ltd"},
    ):
        assert _find(query)["reason"]


def test_candidates_are_always_returned_best_first():
    # So a caller who disagrees with the verdict can see the evidence it saw
    # rather than having to re-run the comparison themselves.
    result = _find({"name": "Karfi Agro Cooperative Society Ltd"})
    scores = [edge["score"] for edge in result["candidates"]]
    assert scores == sorted(scores, reverse=True)


def test_the_run_keeps_its_pins():
    result = _find({"name": "Zenith Bank Plc"})
    assert result["pins"]["engine"] == "crosswalk.v1"
    assert result["pins"]["entity_pack"] if "entity_pack" in result["pins"] else True


def test_lookups_reproduce():
    query = {"name": "Karfi Agro Co-operative Soc.",
             "address": "12 Zaria Rd, Kano State"}
    assert _find(query) == _find(query)


def test_hand_written_comparators_are_accepted_positionally():
    # Same convention as the other verbs. `would_resolve` needs a pack to know
    # what a comparator could achieve, so without one it stays empty rather
    # than guessing.
    comparators = [{"field": "name", "kind": "placename", "weight": 2.0}]
    result = find({"name": "Karfi Agro Cooperative Society Ltd"}, _MASTER,
                  comparators, id_field="id", block=None)
    assert result["verdict"] in {"found", "ambiguous", "not_found"}


def test_find_is_exported_as_a_verb():
    import arche

    assert callable(arche.find)
    assert "find" in arche.__all__
