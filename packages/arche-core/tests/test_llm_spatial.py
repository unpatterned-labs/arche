# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""extract_places_llm — the model proposes, the cue engine verifies.

All offline: the "model" is a stub callable returning canned JSON.
"""

from __future__ import annotations

import json

import pytest
from arche.addr.roles import grade_places, load_gold
from arche.llm.spatial import extract_places_llm

TEXT = ("Pick up the parcel from 7B Allen Avenue, Ikeja, Lagos and "
        "deliver to 12 Adeola Odeku Street, Victoria Island.")


def _stub(payload):
    def fn(messages):
        assert messages[0]["role"] == "system"
        return json.dumps(payload)
    return fn


class TestVerification:
    def test_correct_proposal_is_verified(self):
        ex = extract_places_llm(TEXT, complete_fn=_stub([
            {"text": "7B Allen Avenue, Ikeja, Lagos", "role": "origin",
             "cue": "from"},
            {"text": "12 Adeola Odeku Street, Victoria Island",
             "role": "destination", "cue": "deliver to"},
        ]), model="stub@1")
        assert [m.role for m in ex.mentions] == ["origin", "destination"]
        assert all("cue:model_proposed_verified" in m.evidence
                   for m in ex.mentions)
        assert ex.violations == [] and ex.downgrades == []
        # the verified cue obeys the same invariant as the deterministic path
        for m in ex.mentions:
            assert TEXT[m.cue_span[0]:m.cue_span[1]] == m.cue

    def test_hallucinated_span_is_a_violation_never_a_value(self):
        ex = extract_places_llm(TEXT, complete_fn=_stub([
            {"text": "99 Invented Close, Nowhere", "role": "origin",
             "cue": "from"},
        ]))
        assert ex.mentions == []
        assert len(ex.violations) == 1
        assert "verbatim" in ex.violations[0]

    def test_fabricated_cue_downgrades_to_unknown(self):
        ex = extract_places_llm(TEXT, complete_fn=_stub([
            {"text": "7B Allen Avenue, Ikeja, Lagos", "role": "origin",
             "cue": "dispatched from"},   # not in the source text
        ]))
        assert [m.role for m in ex.mentions] == ["unknown"]
        assert "cue:unverified" in ex.mentions[0].evidence
        assert ex.mentions[0].confidence == 0.25
        assert "not found in source" in ex.downgrades[0]

    def test_role_inconsistent_cue_downgrades(self):
        # "from" exists and is adjacent, but the pack maps it to origin.
        ex = extract_places_llm(TEXT, complete_fn=_stub([
            {"text": "7B Allen Avenue, Ikeja, Lagos", "role": "destination",
             "cue": "from"},
        ]))
        assert [m.role for m in ex.mentions] == ["unknown"]
        assert "not 'destination'" in ex.downgrades[0]

    def test_non_adjacent_cue_downgrades(self):
        # "deliver to" is real but sits before the SECOND span, not the first.
        ex = extract_places_llm(TEXT, complete_fn=_stub([
            {"text": "7B Allen Avenue, Ikeja, Lagos", "role": "destination",
             "cue": "deliver to"},
        ]))
        assert [m.role for m in ex.mentions] == ["unknown"]

    def test_committed_role_without_cue_downgrades(self):
        ex = extract_places_llm(TEXT, complete_fn=_stub([
            {"text": "7B Allen Avenue, Ikeja, Lagos", "role": "origin",
             "cue": None},
        ]))
        assert [m.role for m in ex.mentions] == ["unknown"]
        assert "no cue offered" in ex.downgrades[0]

    def test_model_unknown_is_accepted_as_is(self):
        ex = extract_places_llm(TEXT, complete_fn=_stub([
            {"text": "7B Allen Avenue, Ikeja, Lagos", "role": "unknown",
             "cue": None},
        ]))
        assert [m.role for m in ex.mentions] == ["unknown"]
        assert ex.downgrades == []  # abstaining is never punished

    def test_closed_role_vocabulary(self):
        ex = extract_places_llm(TEXT, complete_fn=_stub([
            {"text": "7B Allen Avenue, Ikeja, Lagos", "role": "pickup",
             "cue": "from"},
        ]))
        assert ex.mentions == []
        assert "closed" in ex.violations[0] or "vocabulary" in ex.violations[0]


class TestContract:
    def test_bad_json_fails_loud(self):
        with pytest.raises(ValueError, match="valid JSON"):
            extract_places_llm(TEXT, complete_fn=lambda m: "sure! here you go")

    def test_exactly_one_seam(self):
        with pytest.raises(ValueError, match="exactly one"):
            extract_places_llm(TEXT)

    def test_pins_are_honest(self):
        ex = extract_places_llm(TEXT, complete_fn=_stub([]), model="m@2026")
        pins = ex.pins()["place_extraction"]
        assert pins["model"] == "m@2026"
        assert pins["reproducible"] is False
        assert pins["pack"].startswith("arche.place_roles@")
        assert len(pins["prompt_sha256"]) == 64

    def test_lazy_export(self):
        import arche.llm as llm

        assert llm.extract_places_llm is extract_places_llm


class TestGradedAgainstGold:
    def test_llm_output_grades_with_the_same_scorer(self):
        # A "perfect model" stub built FROM the gold labels grades cleanly —
        # closing the loop: propose -> verify -> grade, one referee.
        gold = [s for s in load_gold() if s.id in ("gb-001", "ng-001")]
        preds = {}
        for s in gold:
            payload = [
                {"text": p.text, "role": p.role, "cue": p.cue}
                for p in s.places
            ]
            ex = extract_places_llm(s.text, complete_fn=_stub(payload))
            preds[s.id] = ex.mentions
        g = grade_places(gold, preds)
        assert g.abstentions["over_guess"] == 0
        assert g.per_role["origin"]["fn"] == 0
        assert g.per_role["destination"]["fn"] == 0


class TestProviderCallSignature:
    """The `config=` path, which nothing else in the suite exercises.

    Every other test here passes `complete_fn=`, which bypasses the provider
    module entirely. That gap let `spatial.py` call
    `complete(messages, config)` — arguments reversed — through a full release:
    the real provider would take a list where it expected an `LLMConfig` and
    die on the first attribute access, while the suite stayed green.
    """

    def test_provider_receives_config_first(self, monkeypatch):
        from arche.llm import LLMConfig
        from arche.llm import providers

        seen: dict = {}

        def fake_complete(config, messages):
            seen["config"] = config
            seen["messages"] = messages
            return "[]"

        monkeypatch.setattr(providers, "complete", fake_complete)
        cfg = LLMConfig(model="test-model", api_key="k")
        extract_places_llm("send it to 3 Sherborne Place, Birmingham", config=cfg)

        assert seen["config"] is cfg
        assert isinstance(seen["messages"], list)
        assert all("role" in m and "content" in m for m in seen["messages"])

    def test_config_path_pins_the_model_name(self, monkeypatch):
        from arche.llm import LLMConfig
        from arche.llm import providers

        monkeypatch.setattr(providers, "complete", lambda config, messages: "[]")
        cfg = LLMConfig(model="test-model", api_key="k")
        ex = extract_places_llm("deliver to 7B Allen Avenue, Ikeja", config=cfg)
        # The pin names what produced the extraction; a decision made under a
        # model has to say which one.
        assert ex.pins()["place_extraction"]["model"] == "test-model"
        assert ex.pins()["place_extraction"]["reproducible"] is False

    def test_supplying_both_config_and_complete_fn_is_refused(self):
        from arche.llm import LLMConfig

        with pytest.raises(ValueError, match="exactly one"):
            extract_places_llm(
                "deliver to 7B Allen Avenue, Ikeja",
                config=LLMConfig(model="m", api_key="k"),
                complete_fn=lambda messages: "[]",
            )
