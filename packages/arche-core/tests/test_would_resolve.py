# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""`would_resolve` names the fields that would settle an unresolved pair.

A `review` edge reports that the evidence was insufficient and stops there. A
human reviewer fills the gap from domain knowledge; an agent has none, so it
escalates everything or invents a merge. This turns the refusal into a next
action.

The tests that matter most are in `TestTheAdviceIsTrue`. Guidance that sounds
authoritative and is wrong is worse than no guidance, because an agent will act
on it. The first draft of this module told callers that coordinates more than
10 km apart "refute the pair outright". Measured:

    Karfi Health Post vs itself,  90 m apart -> match
    Karfi Health Post vs itself, 530 km apart -> review

The veto capped the decision. It did not delete the pair and it did not return
`no_match` -- arche declines to assert sameness and never asserts difference.
So those tests take the advice, apply it, and check the decision moves the way
the text promised.
"""

from __future__ import annotations

import pytest
from arche.resolve import ENTITY_PACKS, crosswalk, would_resolve
from arche.resolve._unresolved import (
    CAN_PREVENT_MATCH,
    DECISIVE_FOR,
    HARD_CONSTRAINT,
    INDEPENDENT_SIGNAL,
)

#: Lagos and Abuja: about 530 km, far past the place pack's 10 km veto.
LAGOS = (6.5244, 3.3792)
ABUJA = (9.0765, 7.3986)
#: About 90 m apart, comfortably inside it.
NEXT_DOOR = (6.5250, 3.3800)


def edge_for(a, b, entity):
    edges = crosswalk([a], [b], entity=entity, id_field="id")["matches"]
    assert edges, f"{a} vs {b} was not surfaced under {entity}"
    return edges[0]


def advice(name, entity="place", **extra):
    a = {"id": "a", "name": name, **extra}
    b = {"id": "b", "name": name, **extra}
    return would_resolve(edge_for(a, b, entity), a, b, entity=entity)


class TestItAnswersTheQuestionTheEdgeDoesNot:

    def test_a_generic_place_name_asks_for_coordinates_first(self):
        result = advice("General Hospital")
        assert result["decision"] == "review"
        assert result["would_resolve"][0]["field"] == "lat + lon"
        assert result["would_resolve"][0]["effect"] == HARD_CONSTRAINT

    def test_it_lists_only_fields_that_were_absent(self):
        result = advice("General Hospital")
        offered = {entry["field"] for entry in result["would_resolve"]}
        assert "name" not in offered
        assert offered == {"lat + lon", "admin_path", "address"}

    def test_a_supplied_field_moves_out_of_the_offer(self):
        # A mapping of levels, not a path string. `containment` reads
        # `admin1`/`admin2`/`settlement` off it.
        result = advice("General Hospital",
                        admin_path={"admin1": "Lagos", "admin2": "Ikeja"})
        offered = {entry["field"] for entry in result["would_resolve"]}
        assert "admin_path" not in offered
        assert "admin_path" in result["fields_present"]

    def test_the_reason_names_the_gate_that_held_it(self):
        result = advice("General Hospital")
        assert "0.564" in result["why"]
        assert "0.75" in result["why"]

    def test_a_decided_pair_is_not_given_homework(self):
        result = advice("Karfi Health Post")
        assert result["decision"] == "match"
        assert result["would_resolve"] == []
        assert result["why"] == "already resolved"

    def test_an_unknown_pack_is_refused_by_name(self):
        with pytest.raises(ValueError, match="unknown entity pack"):
            would_resolve({"decision": "review"}, {}, {}, entity="nope")


class TestItSaysWhatWillNotHelp:
    """The half an agent needs most, and the half a scoring API never gives.

    Faced with `review` on two identical names, the obvious move is to fetch a
    longer or cleaner name and retry. That cannot work: rarity is a property of
    the population, so a better rendering of `General Hospital` is still
    `General Hospital`.
    """

    def test_the_agreeing_field_is_named_as_a_dead_end(self):
        result = advice("General Hospital")
        assert [entry["field"] for entry in result["will_not_help"]] == ["name"]
        assert "population" in result["will_not_help"][0]["why"]

    def test_a_conflict_offers_nothing_because_nothing_would_help(self):
        """Distinctive agreement plus a hard contradiction. More evidence does
        not settle it -- the contradiction has to be."""
        a = {"id": "a", "name": "Karfi Health Post", "lat": LAGOS[0], "lon": LAGOS[1]}
        b = {"id": "b", "name": "Karfi Health Post", "lat": ABUJA[0], "lon": ABUJA[1]}
        result = would_resolve(edge_for(a, b, "place"), a, b, entity="place")

        assert result["decision"] == "review"
        assert result["would_resolve"] == []
        assert "contradiction" in result["why"]


class TestPacksDifferBecauseTheirComparatorsDo:

    def test_organisation_offers_its_identifier_as_decisive(self):
        a = {"id": "a", "name": "Central Cooperative Society"}
        b = {"id": "b", "name": "Central Cooperative Society"}
        result = would_resolve(edge_for(a, b, "organisation"), a, b,
                               entity="organisation")
        by_field = {e["field"]: e["effect"] for e in result["would_resolve"]}
        assert by_field.get("registration_id") == DECISIVE_FOR

    def test_organisation_offers_its_refuting_field(self):
        a = {"id": "a", "name": "Central Cooperative Society"}
        b = {"id": "b", "name": "Central Cooperative Society"}
        result = would_resolve(edge_for(a, b, "organisation"), a, b,
                               entity="organisation")
        by_field = {e["field"]: e["effect"] for e in result["would_resolve"]}
        assert by_field.get("entity_class") == CAN_PREVENT_MATCH

    def test_organisation_geo_is_only_a_signal_because_it_has_no_veto(self):
        """The same comparator kind, a different effect, because this pack
        declares no `veto_km`. Read from the spec, never assumed from the kind."""
        a = {"id": "a", "name": "Central Cooperative Society"}
        b = {"id": "b", "name": "Central Cooperative Society"}
        result = would_resolve(edge_for(a, b, "organisation"), a, b,
                               entity="organisation")
        by_field = {e["field"]: e["effect"] for e in result["would_resolve"]}
        assert by_field.get("lat + lon") == INDEPENDENT_SIGNAL

    @pytest.mark.parametrize("entity", sorted(ENTITY_PACKS))
    def test_every_pack_can_be_asked(self, entity):
        """No pack raises, whatever its comparator mix."""
        a = {"id": "a", "name": "General Hospital"}
        b = {"id": "b", "name": "General Hospital"}
        edges = crosswalk([a], [b], entity=entity, id_field="id")["matches"]
        if not edges:
            pytest.skip(f"{entity} does not surface this pair")
        result = would_resolve(edges[0], a, b, entity=entity)
        assert set(result) == {"decision", "why", "fields_present",
                               "would_resolve", "will_not_help"}


class TestTheAdviceIsTrue:
    """Take the advice, apply it, and check the decision moves as promised.

    Without this the module is plausible prose attached to a real API, which is
    the failure mode it exists to prevent.
    """

    def test_supplying_coordinates_close_together_does_not_rescue_a_generic_name(self):
        """`will_not_help` implies this, so it has to hold: geography supports,
        it cannot manufacture distinctiveness."""
        a = {"id": "a", "name": "General Hospital", "lat": LAGOS[0], "lon": LAGOS[1]}
        b = {"id": "b", "name": "General Hospital",
             "lat": NEXT_DOOR[0], "lon": NEXT_DOOR[1]}
        assert edge_for(a, b, "place")["decision"] == "review"

    def test_the_hard_constraint_caps_a_match_at_review(self):
        """What `HARD_CONSTRAINT` promises, on a name distinctive enough to
        match without it."""
        near_a = {"id": "a", "name": "Karfi Health Post",
                  "lat": LAGOS[0], "lon": LAGOS[1]}
        near_b = {"id": "b", "name": "Karfi Health Post",
                  "lat": NEXT_DOOR[0], "lon": NEXT_DOOR[1]}
        far_b = {"id": "b", "name": "Karfi Health Post",
                 "lat": ABUJA[0], "lon": ABUJA[1]}

        assert edge_for(near_a, near_b, "place")["decision"] == "match"
        assert edge_for(near_a, far_b, "place")["decision"] == "review"

    def test_the_constraint_never_asserts_difference(self):
        """The wording says 'caps at review', not 'refutes'. 530 km apart still
        returns an edge, and it is never `no_match`."""
        a = {"id": "a", "name": "Karfi Health Post", "lat": LAGOS[0], "lon": LAGOS[1]}
        b = {"id": "b", "name": "Karfi Health Post", "lat": ABUJA[0], "lon": ABUJA[1]}
        assert edge_for(a, b, "place")["decision"] == "review"

    def test_the_identifier_advice_holds_for_organisations(self):
        """`DECISIVE_FOR` on `registration_id`: supplying an agreeing one lifts
        a generic-name pair that review would otherwise hold."""
        a = {"id": "a", "name": "Central Cooperative Society"}
        b = {"id": "b", "name": "Central Cooperative Society"}
        before = edge_for(a, b, "organisation")["decision"]

        a_id = {**a, "registration_id": "RC-889112"}
        b_id = {**b, "registration_id": "RC-889112"}
        after = edge_for(a_id, b_id, "organisation")["decision"]

        assert before == "review"
        assert after == "match"


class TestItDoesNotTouchTheEdge:
    """`decision_id` is a content hash over the edge dict. An extra key would
    change the identity of every crosswalk edge ever issued while changing no
    verdict, which is why this is a separate call and not a field."""

    def test_the_edge_is_unchanged_by_asking(self):
        a = {"id": "a", "name": "General Hospital"}
        b = {"id": "b", "name": "General Hospital"}
        edge = edge_for(a, b, "place")
        before = dict(edge)
        would_resolve(edge, a, b, entity="place")
        assert edge == before

    def test_guidance_is_not_in_the_edge(self):
        a = {"id": "a", "name": "General Hospital"}
        b = {"id": "b", "name": "General Hospital"}
        assert set(edge_for(a, b, "place")) == {
            "a_id", "b_id", "score", "decision", "evidence", "distinctive_max",
            "decision_id"}


class TestMissingValues:

    def test_a_zero_coordinate_counts_as_supplied(self):
        """`lat=0.0` is the equator. Falsiness would drop it and then advise
        fetching a field the caller already sent."""
        a = {"id": "a", "name": "General Hospital", "lat": 0.0, "lon": 0.0}
        b = {"id": "b", "name": "General Hospital", "lat": 0.0, "lon": 0.0}
        result = would_resolve(edge_for(a, b, "place"), a, b, entity="place")
        assert "lat + lon" in result["fields_present"]

    def test_a_blank_string_counts_as_absent(self):
        a = {"id": "a", "name": "General Hospital", "address": "   "}
        b = {"id": "b", "name": "General Hospital", "address": ""}
        result = would_resolve(edge_for(a, b, "place"), a, b, entity="place")
        assert "address" in {e["field"] for e in result["would_resolve"]}

    def test_one_sided_data_is_still_missing(self):
        """A comparator needs both sides. One coordinate pair is not a pair."""
        a = {"id": "a", "name": "General Hospital", "lat": LAGOS[0], "lon": LAGOS[1]}
        b = {"id": "b", "name": "General Hospital"}
        result = would_resolve(edge_for(a, b, "place"), a, b, entity="place")
        assert "lat + lon" in {e["field"] for e in result["would_resolve"]}
