# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""extract_places — spatial role labeling behaviour + the gold-set grade."""

from __future__ import annotations

import pytest
from arche.addr.roles import (
    _CONFIDENCE,
    PlaceMention,
    extract_places,
    grade_places,
    load_gold,
    load_role_pack,
)


def _one(text: str, role: str) -> PlaceMention:
    got = [m for m in extract_places(text) if m.role == role]
    assert got, f"no {role} mention in {text!r}: {extract_places(text)}"
    return got[0]


class TestTicketFrames:
    """The frames the ticket names, verbatim."""

    def test_from_x_to_y(self):
        mentions = extract_places(
            "Can you come pick up this package from 123 Maple Street, London "
            "and send it to 3 Sherborne Place, Birmingham?"
        )
        assert [(m.role, m.text) for m in mentions] == [
            ("origin", "123 Maple Street, London"),
            ("destination", "3 Sherborne Place, Birmingham"),
        ]
        assert mentions[0].cue == "from"
        assert mentions[0].confidence == 0.95

    def test_pick_up_at(self):
        m = _one("Pick up at 6 Camden Passage, London, then wait.", "origin")
        assert m.cue_rule == "pickup_origin"

    def test_deliver_to(self):
        m = _one("Deliver to 25 Zik Avenue, Enugu before noon.", "destination")
        assert m.cue_rule == "deliver_destination"

    def test_between_route_two_roles(self):
        mentions = extract_places("The van runs between Manchester and Leeds.")
        assert [(m.role, m.text) for m in mentions] == [
            ("origin", "Manchester"), ("destination", "Leeds"),
        ]
        assert mentions[1].cue == "and"  # the join cue is the evidence for B

    def test_between_plain_two_locations(self):
        mentions = extract_places("Our office is between Old Street and Moorgate.")
        assert [m.role for m in mentions] == ["location", "location"]

    def test_single_at(self):
        m = _one("I am at SE1 7EH right now.", "location")
        assert m.text == "SE1 7EH"


class TestAbstention:
    """Unknown is a first-class answer, never a guess."""

    def test_conflicting_cues_abstain(self):
        mentions = extract_places(
            "The consignment was picked up at and delivered to "
            "7B Allen Avenue, Ikeja."
        )
        assert [m.role for m in mentions] == ["unknown"]
        assert any(e.startswith("cue_conflict:") for e in mentions[0].evidence)
        assert mentions[0].confidence == 0.25
        assert mentions[0].cue is not None  # the conflict is still inspectable

    def test_no_cue_abstains(self):
        mentions = extract_places(
            "Regarding 17 Fleet Lane, London, we have questions."
        )
        assert [m.role for m in mentions] == ["unknown"]
        assert "cue:absent" in mentions[0].evidence

    def test_negated_cue_abstains(self):
        mentions = extract_places(
            "Don't deliver to 31 Ribadu Road, Kano anymore."
        )
        assert [m.role for m in mentions] == ["unknown"]
        assert "cue:negated" in mentions[0].evidence
        assert mentions[0].cue_phrase == "deliver to"  # named, not hidden


class TestCueMechanics:
    def test_priority_directional_beats_locative(self):
        # "deliver to the depot at X" — "deliver to" (50) governs, "at" (40)
        # loses; no conflict is declared across different priorities.
        m = _one("Deliver to 44 Holloway Road, London.", "destination")
        assert m.cue_rule == "deliver_destination"

    def test_window_blocked_by_sentence_boundary(self):
        mentions = extract_places("Pick up from here. 5 Mill Lane, Oxford.")
        roles = {m.role for m in mentions}
        assert "origin" not in roles  # the full stop severs the cue

    def test_nearest_cue_wins(self):
        # "from A ... to B": each cue binds its own span, no crosstalk.
        mentions = extract_places("From Nairobi to Kampala.")
        assert [(m.role, m.text) for m in mentions] == [
            ("origin", "Nairobi"), ("destination", "Kampala"),
        ]

    def test_intrinsic_anchor_is_location(self):
        m = _one(
            "The workshop is behind the central mosque, Ungwan Rimi, Kaduna.",
            "location",
        )
        assert m.cue_phrase == "behind"
        assert m.cue_span is not None
        assert m.cue_span[0] >= m.span[0]  # the cue lives INSIDE the span

    def test_external_cue_beats_intrinsic(self):
        m = _one(
            "Pick up from behind the Total filling station, Madina Junction.",
            "origin",
        )
        # The composite cue is preferred over bare "from" — more specific
        # evidence — and the intrinsic "behind" (priority 10) loses.
        assert m.cue_phrase == "pick up from"


class TestSpanDetection:
    def test_person_title_vetoes_licensed_span(self):
        mentions = extract_places("Collect the documents from Alhaji Musa now.")
        assert mentions == []

    def test_bare_street_suffix_needs_locative_context(self):
        # "meet Grace Street" is a person; "on Grace Street" would be a place.
        assert extract_places("Come meet Grace Street for lunch.") == []

    def test_calendar_word_never_licensed(self):
        mentions = extract_places("We arrive at Tuesday's venue.")
        assert all(m.text != "Tuesday" for m in mentions)

    def test_postcode_straddle_extends_span(self):
        m = _one("Deliver the crate to 44 Holloway Road, London N7 8JG.",
                 "destination")
        assert m.text.endswith("N7 8JG")

    def test_vitamin_b2_not_a_postcode(self):
        assert extract_places("take vitamin B2 daily and rest") == []

    def test_spans_sorted_and_disjoint(self):
        mentions = extract_places(
            "Route the driver from 4 Ogunu Road, Warri through Benin City "
            "to 10 Airport Road, Abuja."
        )
        assert [m.role for m in mentions] == ["origin", "via", "destination"]
        for a, b in zip(mentions, mentions[1:], strict=False):
            assert a.span[1] <= b.span[0]

    def test_empty_and_junk_inputs(self):
        assert extract_places("") == []
        assert extract_places("   \n  ") == []
        assert extract_places("!!! ??? ...") == []

    def test_large_input_terminates(self):
        text = ("The meeting notes were long. " * 300
                + "Deliver to 25 Zik Avenue, Enugu.")
        assert any(m.role == "destination" for m in extract_places(text))


class TestConfidenceTable:
    @pytest.mark.parametrize("cell,value", sorted(_CONFIDENCE.items()))
    def test_cells_are_the_documented_labels(self, cell, value):
        expected = {
            (2, 2): 0.95, (2, 1): 0.80, (2, 0): 0.60,
            (1, 2): 0.70, (1, 1): 0.55, (1, 0): 0.40,
            (0, 2): 0.25, (0, 1): 0.25, (0, 0): 0.25,
        }
        assert value == expected[cell]

    def test_unknown_is_always_floor(self):
        for m in extract_places(
            "Regarding 17 Fleet Lane, London, we have questions."
        ):
            assert m.confidence == 0.25


class TestOutputContract:
    def test_cue_span_invariant_over_gold_set(self):
        # source[cue_span] == cue, for every mention over all 54 sentences.
        for sent in load_gold():
            for m in extract_places(sent.text):
                if m.cue is not None:
                    assert sent.text[m.cue_span[0]:m.cue_span[1]] == m.cue
                assert sent.text[m.span[0]:m.span[1]] == m.text

    def test_masked_dict_carries_no_values(self):
        m = _one("Deliver to 25 Zik Avenue, Enugu.", "destination")
        d = m.to_dict(reveal=False)
        assert "text" not in d and "components" not in d
        assert "25 Zik Avenue" not in str(d)
        assert d["cue"] in load_role_pack().vocabulary()
        assert d["components_present"]  # names only

    def test_unicode_spans(self):
        mentions = extract_places("Tunasafiri kwenda Dodoma kesho.")
        assert [(m.role, m.text) for m in mentions] == [("destination", "Dodoma")]


class TestGoldSetGrade:
    """The shipped extractor graded against the shipped gold set.

    Floors were calibrated on first green (2026-08-05: span_f1 0.9922,
    origin 0.9714 / destination 0.9778 / location 1.0 / via 1.0,
    cue_accuracy 1.0) and only ever ratchet UP.
    """

    @pytest.fixture(scope="class")
    def grade(self):
        gold = load_gold()
        preds = {s.id: extract_places(s.text) for s in gold}
        return grade_places(gold, preds, pack=load_role_pack().pin)

    def test_gold_set_composition(self):
        gold = load_gold()
        assert len(gold) >= 50
        assert sum(1 for s in gold if not s.places) >= 4          # negatives
        assert sum(1 for s in gold for p in s.places
                   if p.role == "unknown") >= 6                    # adversarial

    def test_span_f1_floor(self, grade):
        assert grade.span_f1 >= 0.95

    def test_per_role_f1_floors(self, grade):
        for role in ("origin", "destination", "location", "via"):
            assert grade.per_role[role]["f1"] >= 0.90, (role, grade.per_role)

    def test_cue_accuracy_floor(self, grade):
        assert grade.cue_accuracy >= 0.95

    def test_over_guess_bounded(self, grade):
        # Exactly one known over-guess is tolerated: the attributive trap
        # (amb-004, "the invoice from our Lagos office") — the documented
        # blind spot of cue-based labeling. Any INCREASE is a regression in
        # the match-don't-guess property and must fail.
        assert grade.abstentions["over_guess"] <= 1

    def test_no_missed_abstentions(self, grade):
        assert grade.abstentions["missed_by_abstention"] == 0

    def test_grader_accepts_plain_dicts(self):
        # A non-Python extractor's JSON grades against the same set.
        gold = [s for s in load_gold() if s.id == "gb-001"]
        preds = {"gb-001": [
            {"start": gold[0].places[0].span[0],
             "end": gold[0].places[0].span[1],
             "role": "origin",
             "cue_start": gold[0].places[0].cue_span[0],
             "cue_end": gold[0].places[0].cue_span[1]},
        ]}
        g = grade_places(gold, preds)
        assert g.per_role["origin"]["tp"] == 1
        assert g.per_role["destination"]["fn"] == 1

    def test_refusal_scoring_rules(self):
        # unknown-on-committed = missed_by_abstention (never an fp);
        # committed-on-unknown = over_guess AND an fp.
        gold = [s for s in load_gold() if s.id in ("gb-001", "amb-003")]
        by_id = {s.id: s for s in gold}
        preds = {
            "gb-001": [{"start": by_id["gb-001"].places[0].span[0],
                        "end": by_id["gb-001"].places[0].span[1],
                        "role": "unknown"}],
            "amb-003": [{"start": by_id["amb-003"].places[0].span[0],
                         "end": by_id["amb-003"].places[0].span[1],
                         "role": "destination"}],
        }
        g = grade_places(gold, preds)
        assert g.abstentions["missed_by_abstention"] == 1
        assert g.abstentions["over_guess"] == 1
        assert g.per_role["destination"]["fp"] == 1
