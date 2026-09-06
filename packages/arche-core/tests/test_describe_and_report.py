# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""``describe``, and the surface it closes over.

``describe`` is the affordance that makes the tightened vocabulary usable by
something that cannot read prose. Four named questions can be chosen between;
the eight overlapping spellings that preceded them could not.
"""

from __future__ import annotations

import json

import arche

# ---------------------------------------------------------------------------
# describe
# ---------------------------------------------------------------------------


def test_describe_names_every_verb():
    verbs = arche.describe()["verbs"]
    assert set(verbs) == {"compare", "reconcile", "dedupe", "find"}


def test_every_verb_states_its_question_and_its_return():
    for name, spec in arche.describe()["verbs"].items():
        assert spec["question"].endswith("?"), f"{name} does not state a question"
        assert spec["takes"] and spec["returns"]


def test_the_described_verbs_are_the_callable_ones():
    # A catalogue that drifts from the library is worse than none: a caller
    # follows it into an AttributeError and stops trusting the rest.
    for name in arche.describe()["verbs"]:
        assert callable(getattr(arche, name)), f"{name} is described but absent"


def test_every_shipped_pack_is_listed():
    from arche.resolve import ENTITY_PACKS

    assert set(arche.describe()["entities"]) == set(ENTITY_PACKS)


def test_one_pack_can_be_asked_for_alone():
    described = arche.describe("organisation")
    assert described["entities"] == ["organisation"]
    assert "name" in described["packs"]["organisation"]["field_names"]


def test_the_three_outcomes_are_spelled_out():
    # Especially `review`. A caller who reads it as "weak match" will merge on
    # it, which is the single most expensive misreading of this library.
    outcomes = arche.describe()["outcomes"]
    assert set(outcomes) == {"match", "review", "different"}
    assert "human" in outcomes["review"]


def test_the_incomparable_scores_are_disclosed():
    # Two engines, two scales. A caller comparing 0.8 from one against 0.8 from
    # the other is comparing different units, and nothing in the numbers says so.
    assert "not comparable" in arche.describe()["note"]


def test_describe_is_json_serialisable():
    # It exists to be handed to something that speaks JSON. A value that will
    # not serialise makes it useless for the one caller it was built for.
    assert json.loads(json.dumps(arche.describe()))


def test_every_comparator_kind_is_explained():
    from arche.resolve import COMPARATOR_NOTES

    assert arche.describe()["comparators"] == dict(COMPARATOR_NOTES)
