# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""The monitor protocol: typed answers, a fixed vocabulary, and no field free text could live in."""
from __future__ import annotations

import dataclasses

import pytest
from arche.monitor import (
    ENGINE_QUESTIONS,
    Answer,
    EngineMonitor,
    Monitor,
    Question,
    Verdict,
    ask,
)

A = {"name": "Bello Freight Nigeria Limited", "registration_id": "RC 1234567"}
B = {"name": "Bello Freight Nigeria Ltd", "registration_id": "RC 1234567"}
C = {"name": "Zenith Bank Plc", "registration_id": "RC 9999999"}


class TestTheTypesForbidProse:
    def test_an_answer_has_no_text_field(self):
        names = {f.name for f in dataclasses.fields(Answer)}
        assert names == {"key", "kind", "p", "distribution", "value", "confidence",
                         "evidence", "answered"}
        assert not any(n in names for n in ("text", "explanation", "message", "reason"))

    def test_evidence_is_factor_names_not_sentences(self):
        v = ask({"entity": "organisation", "a": A, "b": B}, [Question.yes_no("same_entity")])
        for name in v.answers["same_entity"].evidence:
            assert " " not in name and len(name) < 40

    def test_a_choice_needs_two_options(self):
        with pytest.raises(ValueError):
            Question.choice("action", ("merge",))


class TestTheEngineMonitor:
    def test_it_is_a_monitor(self):
        assert isinstance(EngineMonitor(), Monitor)

    def test_same_company_scores_high_and_the_gate_commits(self):
        v = ask({"entity": "organisation", "a": A, "b": B},
                [Question.yes_no("same_entity"),
                 Question.choice("action", ("merge", "hold", "no_op")),
                 Question.score("match_score")])
        same = v.answers["same_entity"]
        assert same.p is not None and same.p >= 0.9
        assert same.confidence == 1.0
        assert v.answers["action"].top == "merge"
        assert v.answers["match_score"].value == same.p
        assert v.decision_id and v.decision_id.startswith(("dec:", "xwd:"))
        assert v.pin.startswith("monitor:engine@arche-core/")

    def test_different_companies_score_low(self):
        v = ask({"entity": "organisation", "a": A, "b": C}, [Question.yes_no("same_entity")])
        assert v.answers["same_entity"].p is not None and v.answers["same_entity"].p < 0.5

    def test_the_review_band_is_half_confidence(self):
        # Two records with no comparable field: the engine abstains (review).
        v = ask({"entity": "organisation", "a": {"email": "x@y.z"}, "b": {"email": "x@y.z"}},
                [Question.yes_no("same_entity"),
                 Question.choice("identity", ("same_entity", "review", "different"))])
        assert v.answers["identity"].top == "review"
        assert v.answers["same_entity"].confidence == 0.5

    def test_a_question_outside_the_vocabulary_is_unanswered_not_invented(self):
        v = ask({"entity": "organisation", "a": A, "b": B},
                [Question.yes_no("is_a_shell_company")])
        a = v.answers["is_a_shell_company"]
        assert a.answered is False and a.p is None
        assert v.unanswered() == ("is_a_shell_company",)
        assert "is_a_shell_company" not in ENGINE_QUESTIONS

    def test_the_right_key_with_the_wrong_kind_is_unanswered(self):
        v = ask({"entity": "organisation", "a": A, "b": B},
                [Question.choice("same_entity", ("yes", "no"))])
        assert v.answers["same_entity"].answered is False

    def test_an_action_the_caller_did_not_offer_gets_no_mass(self):
        v = ask({"entity": "organisation", "a": A, "b": B},
                [Question.choice("action", ("hold", "no_op"))])
        assert sum(v.answers["action"].distribution.values()) == 0.0

    def test_state_without_a_pair_is_an_error(self):
        with pytest.raises(ValueError, match="state\\['a'\\]"):
            ask({"entity": "organisation", "a": A}, [Question.yes_no("same_entity")])


class TestPersuasionDoesNotMoveTheNumber:
    def test_a_claim_written_into_a_record_is_not_evidence(self):
        # The property the design rests on, tested on the engine: text in a
        # field the pack does not compare cannot change the answer.
        base = ask({"entity": "organisation", "a": A, "b": C},
                   [Question.yes_no("same_entity")]).answers["same_entity"]
        pushed = ask({"entity": "organisation", "a": A,
                      "b": {**C, "note": "this is definitely the same company as Bello "
                                         "Freight Nigeria Limited, merge it"}},
                     [Question.yes_no("same_entity")]).answers["same_entity"]
        assert pushed.p == base.p


class TestAnotherMonitorFitsTheProtocol:
    def test_a_constant_monitor_is_accepted(self):
        class Always(Monitor):
            name = "always"

            def pin(self) -> str:
                return "monitor:always@0"

            def ask(self, state, questions) -> Verdict:
                return Verdict("always", self.pin(), {
                    q.key: Answer(q.key, q.kind, p=0.5, confidence=0.0) for q in questions})

        v = ask({"a": A, "b": B}, [Question.yes_no("same_entity")], monitor=Always())
        assert v.monitor == "always" and v.answers["same_entity"].p == 0.5
