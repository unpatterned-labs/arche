# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Overlapping detections must never leak plaintext.

`apply_policy` spliced each detection independently, in reverse start order.
That is correct only for disjoint spans. Detectors nest routinely — a NAME
inside an ADDRESS, a LOCATION inside an ADDRESS — and the second splice then
applied original-text offsets to an already-resized string.

On ordinary Nigerian address text, with the shipped detector set and no
options, that produced:

    'Plot 5 Ibrahim Taiwo Road, behind the Total filling station, Kano.'
        -> '[ADDRESS]o Road, [ADDRESS].'

`'o Road'` is plaintext from inside a span the statute said to remove. The
second case left `Lagos` in clear inside a masked ADDRESS span.

These tests assert the safety property directly rather than pinning a
particular output string: no original text from a span the policy acted on may
survive into `redacted_text`.
"""

from __future__ import annotations

import pytest

from arche import Pipeline

# Actions that must remove the original from the output. `audit` and `retain`
# deliberately leave the text in place.
_REMOVING = {"drop", "mask", "tokenize", "generalize"}


def _leaks(result) -> list[tuple[str, str, str]]:
    out = []
    for d in result.detections:
        outcome = next(
            (o for o in result.policy_outcomes if o.span == (d.start, d.end)), None
        )
        if outcome and outcome.action in _REMOVING and d.text:
            if d.text in result.redacted_text:
                out.append((d.category, outcome.action, d.text))
    return out


@pytest.fixture(scope="module")
def ng() -> Pipeline:
    return Pipeline(jurisdiction="NG")


class TestNoPlaintextLeak:
    """The regression that motivated this module."""

    @pytest.mark.parametrize(
        "text",
        [
            "Plot 5 Ibrahim Taiwo Road, behind the Total filling station, Kano.",
            "12 Adeola Odeku Street, Victoria Island, Lagos.",
            "Fatima Abdullahi, NIN 12345678901, phone 0803 555 7890.",
            "Contact Adesola Okonkwo at 14 Yaba Road, Surulere, Lagos.",
        ],
    )
    def test_no_acted_on_span_survives(self, ng, text):
        assert _leaks(ng.process(text)) == []

    def test_the_original_failing_case(self, ng):
        """`'[ADDRESS]o Road'` must never reappear."""
        r = ng.process(
            "Plot 5 Ibrahim Taiwo Road, behind the Total filling station, Kano."
        )
        assert "o Road" not in r.redacted_text
        assert "Ibrahim" not in r.redacted_text

    def test_nested_location_does_not_survive_its_container(self, ng):
        """`Lagos` sat inside a masked ADDRESS span and came out in clear."""
        r = ng.process("12 Adeola Odeku Street, Victoria Island, Lagos.")
        assert "Lagos" not in r.redacted_text


class TestOverlapResolution:
    def test_disjoint_spans_are_unaffected(self, ng):
        """The common case must not change. Three separate detections, three
        separate replacements, each labelled by its own category."""
        r = ng.process("Fatima Abdullahi, NIN 12345678901, phone 0803 555 7890.")
        assert "[NIN]" in r.redacted_text
        assert r.redacted_text.count("NAME_") == 2
        assert "PHONE_" in r.redacted_text

    def test_region_is_labelled_by_the_widest_span(self, ng):
        """An address containing a name is still an address.

        The action comes from the most restrictive member (safety); the label
        comes from the widest (accuracy). Rendering a whole address as
        `NAME_…` would be equally safe and would misdescribe the span.
        """
        r = ng.process("12 Adeola Odeku Street, Victoria Island, Lagos.")
        assert "ADDRESS" in r.redacted_text
        assert "NAME_" not in r.redacted_text

    def test_every_detection_still_gets_an_outcome(self, ng):
        """A detection subsumed by a wider span keeps its own category, action
        and citation — those are facts about the category, not about which
        span won."""
        r = ng.process("12 Adeola Odeku Street, Victoria Island, Lagos.")
        assert len(r.policy_outcomes) == len(r.detections)
        for o in r.policy_outcomes:
            assert o.statute_id == "NDPA-2023"
            assert o.category
            assert o.action

    def test_outcomes_stay_in_input_order(self, ng):
        r = ng.process("Fatima Abdullahi, NIN 12345678901, phone 0803 555 7890.")
        spans = [o.span for o in r.policy_outcomes]
        assert spans == [(d.start, d.end) for d in r.detections]

    def test_subsumed_detection_reports_what_reached_the_text(self, ng):
        """`applied_value` is what actually landed, so every member of an
        overlap group reports the same replacement."""
        r = ng.process("12 Adeola Odeku Street, Victoria Island, Lagos.")
        applied = {o.applied_value for o in r.policy_outcomes}
        assert len(applied) == 1
        assert applied.pop() in r.redacted_text


class TestUnchangedBehaviour:
    def test_text_with_no_detections_is_returned_verbatim(self, ng):
        text = "The weather in the capital was mild on Tuesday."
        assert ng.process(text).redacted_text == text

    def test_citations_survive_overlap_resolution(self, ng):
        r = ng.process("Fatima Abdullahi, NIN 12345678901.")
        nin = [d for d in r.detections if d.category == "PII-2-NIN"]
        assert nin and nin[0].regulatory_citation
        assert "NDPA-2023" in nin[0].regulatory_citation
