# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Two convenience verbs, and the surface they close over.

``describe`` is the affordance that makes the tightened vocabulary usable by
something that cannot read prose. Four named questions can be chosen between;
the eight overlapping spellings that preceded them could not.

``report`` collapses eleven formatters that were never eleven jobs -- they are
a small matrix (result vs evidence) x (csv, html, table, ...) that Python has
no overloading to express, so the input type ended up encoded in the name.
"""

from __future__ import annotations

import json

import pytest

import arche
from arche.workflow.pipeline import resolve as _resolve

_TEXT = "Adebayo Oluwaseun lives at 12 Zaria Road, Kano. Call 08012345678."


@pytest.fixture(scope="module")
def result():
    return _resolve(_TEXT)


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


# ---------------------------------------------------------------------------
# report
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "fmt", ["table", "summary", "csv", "dot", "html", "graph"]
)
def test_every_result_format_produces_output(result, fmt):
    assert arche.report(result, format=fmt)


def test_table_is_the_default():
    from arche.workflow._format import format_table

    result = _resolve(_TEXT)
    assert arche.report(result) == format_table(result)


def test_report_agrees_with_the_formatter_it_replaces(result):
    from arche.workflow import _format

    assert arche.report(result, format="csv") == _format.to_csv(result)
    assert arche.report(result, format="summary") == _format.format_summary(result)


def test_an_impossible_combination_says_what_is_possible(result):
    # A list of evidence spans has no entity graph to draw, and a result has no
    # tagged-text form. Rather than quietly returning something else, the
    # refusal names the formats that do exist for what was handed in.
    with pytest.raises(ValueError) as excinfo:
        arche.report(result, format="tagged")
    message = str(excinfo.value)
    assert "not available" in message
    for available in ("csv", "table", "summary"):
        assert available in message


def test_an_unknown_format_is_refused(result):
    with pytest.raises(ValueError, match="not available"):
        arche.report(result, format="parquet")


def test_an_unsupported_type_is_refused_before_the_formatter():
    # An earlier version accepted anything carrying `detections`, which let a
    # Pipeline `Result` through to fail inside the formatter with an
    # AttributeError about a field the caller never mentioned. Failing at the
    # door names the actual problem.
    with pytest.raises(TypeError, match="does not know how to describe"):
        arche.report(42)


def test_the_pipeline_result_confusion_is_named(result):
    from arche import Pipeline

    pipeline_result = Pipeline(jurisdiction="NG").process(_TEXT)
    with pytest.raises(TypeError, match="detections"):
        arche.report(pipeline_result)


def test_keyword_arguments_reach_the_formatter(result):
    plain = arche.report(result, format="table")
    with_source = arche.report(result, format="table", show_source=True)
    assert plain != with_source


def test_the_eleven_formatters_still_work():
    # `report` is one name over them, not a replacement of them. Anyone who
    # already imported one keeps working.
    for name in ("to_csv", "to_html", "to_dot", "to_graph_html", "format_table",
                 "format_summary", "print_table", "evidence_to_csv",
                 "evidence_to_html", "format_evidence_table",
                 "format_tagged_text"):
        assert callable(getattr(arche, name)), f"{name} disappeared"


def test_report_is_callable_whichever_way_it_resolved():
    # Same collision `arche.extract` had: `arche.report` is a module and a
    # verb, and importing any name out of the submodule rebinds the package
    # attribute to the module. The callable-module shim makes both work.
    import arche.report  # noqa: F401  -- the rebinding import

    assert callable(arche.report)
    from arche.report import crosswalk_report  # noqa: F401

    assert callable(arche.report)
