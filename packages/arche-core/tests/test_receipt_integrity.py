# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""A receipt names the configuration that ran, and only that one.

Four ways a crosswalk ``decision_id`` could name something other than what
produced the decision, each closed here:

* ``extra_pins`` could overwrite a pin the engine set (``engine``,
  ``threshold``), so a receipt could cite a configuration that never ran;
* the gate compared unrounded scores while the receipt recorded rounded ones,
  so a reader could not tell which side of a threshold a score fell on;
* equal-length synonyms resolved in file order while the vocabulary digest was
  taken over the sorted items, so reordering a YAML file could change a
  verdict without changing the pin;
* ``rerank`` and a non-default ``distinctive_kinds`` changed verdicts without
  appearing in the pins.

The environment (Python, Unicode database, library versions) is recorded
beside the pins and deliberately kept out of them; the last class says why.
"""

from __future__ import annotations

import pytest
from arche.resolve import reconcile
from arche.resolve._matcher import _compiled_vocab
from arche.resolve.reconcile import reconcile as reconcile_raw

_ORGS_A = [
    {"id": "a1", "name": "Karfi Agro Cooperative Society Ltd", "city": "Kano"},
    {"id": "a2", "name": "Zenith Bank Plc", "city": "Lagos"},
    {"id": "a3", "name": "Sabon Gari Primary Health Centre", "city": "Kano"},
]
_ORGS_B = [
    {"id": "b1", "name": "Karfi Agro Co-operative Soc.", "city": "Kano"},
    {"id": "b2", "name": "Zenith Bank Limited", "city": "Lagos"},
    {"id": "b3", "name": "Sabon Gari PHC", "city": "Kano"},
]
_COMPARATORS = [
    {"field": "name", "kind": "name", "weight": 2.0},
    {"field": "city", "kind": "name", "weight": 1.0},
]


class TestEnginePinsCannotBeOverwritten:
    @pytest.mark.parametrize("key", ["engine", "threshold", "comparators_sha256"])
    def test_overwriting_an_engine_pin_is_refused(self, key):
        with pytest.raises(ValueError, match="may not overwrite"):
            reconcile_raw(_ORGS_A, _ORGS_B, _COMPARATORS,
                          extra_pins={key: "forged"})

    def test_new_keys_still_add_provenance(self):
        result = reconcile_raw(_ORGS_A, _ORGS_B, _COMPARATORS,
                               extra_pins={"case": "demo.v1"})
        assert result["pins"]["case"] == "demo.v1"

    def test_a_provided_table_may_be_named(self):
        # The engine only knows a table was provided; the caller that built it
        # can say which one. That refinement says more, never less.
        result = reconcile(_ORGS_A, _ORGS_B, entity="organisation", id_field="id")
        assert result["pins"]["tf"] != "provided"


class TestTheGateDecidesOnWhatTheReceiptRecords:
    def test_decision_agrees_with_the_recorded_score_at_every_threshold(self):
        # Sweep thresholds through the recorded scores, including values that
        # sit within half a rounding step of them. Whatever the threshold, a
        # reader holding only the receipt must be able to confirm the verdict.
        base = reconcile_raw(_ORGS_A, _ORGS_B, _COMPARATORS, threshold=0.5,
                             review_margin=0.5)
        scores = sorted({m["score"] for m in base["matches"]})
        assert scores
        for s in scores:
            for t in (s - 0.00004, s, s + 0.00004):
                result = reconcile_raw(_ORGS_A, _ORGS_B, _COMPARATORS,
                                       threshold=t, review_margin=0.5)
                for edge in result["matches"]:
                    if edge["decision"] == "match":
                        assert edge["score"] >= t
                    if edge["score"] < t:
                        assert edge["decision"] == "review"


class TestVocabularyOrderCannotChangeAVerdict:
    def test_equal_length_synonyms_resolve_the_same_in_any_order(self):
        # Two synonyms of equal length mapping to different canonicals: the
        # first in iteration order used to win.
        items = (("abc ltd", "LTD"), ("abc plc", "PLC"), ("ltd", "LTD"))
        forward = _compiled_vocab(items)
        backward = _compiled_vocab(tuple(reversed(items)))
        assert [(c, s) for _, c, s in forward] == [(c, s) for _, c, s in backward]


class TestVerdictSwitchesArePinned:
    def test_rerank_is_pinned_only_when_on(self):
        off = reconcile_raw(_ORGS_A, _ORGS_B, _COMPARATORS)
        assert "rerank" not in off["pins"]
        from arche.resolve._tokenfreq import TokenFrequencyTable

        tf = TokenFrequencyTable.from_corpus(
            r["name"] for r in [*_ORGS_A, *_ORGS_B])
        on = reconcile_raw(_ORGS_A, _ORGS_B, _COMPARATORS, tf=tf, rerank=True)
        assert on["pins"]["rerank"] is True

    def test_non_default_distinctive_kinds_are_pinned(self):
        default = reconcile_raw(_ORGS_A, _ORGS_B, _COMPARATORS)
        assert "distinctive_kinds" not in default["pins"]
        narrowed = reconcile_raw(_ORGS_A, _ORGS_B, _COMPARATORS,
                                 distinctive_kinds=("id",))
        assert narrowed["pins"]["distinctive_kinds"] == ["id"]


class TestDigestsAreFullLength:
    def test_shipped_asset_digests_are_256_bit(self):
        result = reconcile(_ORGS_A, _ORGS_B, entity="organisation", id_field="id")
        assets = result["pins"]["data_assets"]
        assert len(assets["type_tokens:organization"]) == 64
        assert len(assets["legal_form"].split("@")[-1]) == 64


class TestTheEnvironmentIsRecordedNotHashed:
    def test_runtime_is_beside_the_pins_not_in_them(self):
        # Hashing the environment would move every id on every upgrade, and
        # review marks are keyed by decision_id: each release would orphan
        # every human judgement. Recorded, so a verifier can still see it.
        result = reconcile_raw(_ORGS_A, _ORGS_B, _COMPARATORS)
        runtime = result["runtime"]
        for key in ("python", "unicodedata", "arche-core", "jellyfish", "rapidfuzz"):
            assert key in runtime
        assert not set(runtime) & set(result["pins"])
