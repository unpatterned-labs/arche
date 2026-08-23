# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""The Documents tab runs two detectors and must not conflate them.

Reported from a real run: two invoices uploaded to arche studio came back with
a wall of rows reading `uncovered - no rule covered this - no statute`, which
reads as arche having no coverage at all.

It was not a coverage gap. Two detectors run in that tab:

* `Pipeline.process` runs the **jurisdiction-aware** set and emits `PII-*`
  categories the statute has rules about.
* `detect` runs the **general** entity recogniser and emits `PERSON`,
  `ORGANIZATION`, `MONEY`, `URL`.

Different vocabularies over different spans. The tab listed `detect`'s output
and looked each span up in the *pipeline's* policy outcomes. Measured on the
reported German invoice: **28 detected entities, 4 policy outcomes, 2 spans in
common.** The other 26 were labelled as though a statute had been consulted and
had nothing to say. It had never seen them. Widening to an overlap join does not
help -- overlap and exact both give 2.

A plumbing mismatch rendered as a legal finding is the worst available way to be
wrong, so the two origins are now distinct and each row says which detector
produced it.

The second defect was next to it: the tab hardcoded

    jurisdiction = payload.get("jurisdiction") or "NG"

so a German invoice was read under the Nigerian NDPA. `statute_for("DE")`
returns GDPR and reports it available; the tab simply never asked.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_STUDIO = Path(__file__).resolve().parents[3] / "tools" / "arche-studio"

pytestmark = pytest.mark.skipif(
    not (_STUDIO / "serve.py").exists(),
    reason="arche-studio is not present in this checkout",
)

#: German signals strong enough to infer: a Handelsregister number is tier A.
GERMAN = ("Condor Flugdienst GmbH, An der Gehespitz 50, 63263 Neu-Isenburg. "
          "Register Court Amtsgericht Offenbach HRB 83385. Passenger "
          "MRS ANDREA KROPP, contact andr3akropp@example.de, "
          "phone +49 6171 698890.")

#: No inferable jurisdiction: a US address and an m/d/y date are tier C at best.
AMERICAN = ("Invoice from 1100 Rocky Drive, West Lawn PA, 19609 USA. "
            "Dated 04/26/24. Bill to MRS ANDREA KROPP, 227 N 5TH AVE, "
            "RIDGEFIELD WA 98642. Total USD 60.00.")


@pytest.fixture(scope="module")
def studio():
    sys.path.insert(0, str(_STUDIO))
    try:
        spec = importlib.util.spec_from_file_location(
            "arche_studio_serve_docjoin", _STUDIO / "serve.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        yield module
    finally:
        sys.path.remove(str(_STUDIO))


def run(studio, text, name="doc.txt", **extra):
    return studio._documents({"documents": [{"name": name, "text": text}],
                              "reveal": False, **extra})


class TestTheJurisdictionIsDetectedNotAssumed:

    def test_a_german_document_is_read_under_gdpr(self, studio):
        """The reported bug. This came back as NG, so GDPR never ran."""
        out = run(studio, GERMAN)
        report = out["jurisdiction_report"]
        assert out["jurisdiction"] == "DE"
        assert report["source"] == "inferred"
        assert report["statute"] == "GDPR"
        assert report["statute_available"] is True

    def test_it_says_what_the_inference_rested_on(self, studio):
        """An inferred jurisdiction and a stated one deserve different trust,
        so the evidence travels with the answer."""
        signals = {e["signal"] for e in run(studio, GERMAN)["jurisdiction_report"]["evidence"]}
        assert any("handelsregister" in (s or "") for s in signals), signals

    def test_an_explicit_choice_overrules_inference(self, studio):
        """Somebody picking a jurisdiction is stating a fact about their own
        obligation. Detection must not overrule it."""
        out = run(studio, GERMAN, jurisdiction="NG")
        assert out["jurisdiction"] == "NG"
        assert out["jurisdiction_report"]["source"] == "requested"
        assert out["jurisdiction_report"]["statute"] == "NDPA-2023"

    def test_an_unplaceable_document_says_so_rather_than_guessing(self, studio):
        """A document arche cannot place is a real result. Falling back to a
        default country would attach a statute nobody chose."""
        out = run(studio, AMERICAN)
        assert out["jurisdiction"] is None
        assert "No jurisdiction could be inferred" in out["jurisdiction_report"]["note"]

    def test_it_no_longer_defaults_to_nigeria(self, studio):
        """The literal regression. `or "NG"` made every unplaceable document
        Nigerian, and every finding then read as an NDPA gap."""
        assert run(studio, AMERICAN)["jurisdiction"] != "NG"


class TestTheTwoDetectorsAreNotConflated:

    def test_every_row_says_which_detector_found_it(self, studio):
        entities = run(studio, GERMAN)["documents"][0]["entities"]
        assert entities
        assert all(e["origin"] in {"policy", "detector"} for e in entities)

    def test_a_policy_row_carries_a_real_verdict(self, studio):
        """The pipeline's own detections join their outcomes exactly, because
        they are the same detections. This is the join that always works."""
        entities = run(studio, GERMAN)["documents"][0]["entities"]
        policy = [e for e in entities if e["origin"] == "policy"]
        assert policy
        decided = [e for e in policy if e["action"] not in {"uncovered", "not evaluated"}]
        assert decided, "no policy row carried an action"
        assert any(e["authority"] for e in decided), "a verdict with no citation"

    def test_a_detector_row_does_not_claim_a_statute_was_consulted(self, studio):
        """The regression. These used to read `uncovered - no rule covered
        this`, asserting that a statute had been checked. It had not."""
        entities = run(studio, GERMAN)["documents"][0]["entities"]
        detector = [e for e in entities if e["origin"] == "detector"]
        assert detector
        for entity in detector:
            assert entity["action"] == "not evaluated"
            assert entity["authority"] == ""
            assert "did not see this span" in entity["rationale"] or \
                   "does not read" in entity["rationale"]

    def test_an_unevaluated_name_is_still_hidden(self, studio):
        """Not evaluated is not cleared. The safe default is unchanged and the
        reason is now accurate rather than invented."""
        entities = run(studio, GERMAN)["documents"][0]["entities"]
        people = [e for e in entities if e["type"] == "PERSON"]
        assert people
        assert all(e["masked"] for e in people)
        assert all(e["value"] is None for e in people)

    def test_a_span_found_by_both_is_listed_once(self, studio):
        """`detect` also finds the email the pipeline finds. Two rows for one
        span would let one copy contradict the other."""
        entities = run(studio, GERMAN)["documents"][0]["entities"]
        spans = [tuple(e["span"]) for e in entities]
        assert len(spans) == len(set(spans)), "a span was listed twice"

    def test_the_statute_category_survives_beside_the_display_type(self, studio):
        """`PII-1-NAME` is what a citation refers to; `PERSON` is what a reader
        recognises. The tab needs both."""
        entities = run(studio, GERMAN)["documents"][0]["entities"]
        policy = [e for e in entities if e["origin"] == "policy"]
        assert any(e.get("category", "").startswith("PII-") for e in policy)


class TestCoverageReplacesTheWallOfUncovered:
    """One honest statement about what a detector for this jurisdiction can
    find, instead of many rows each implying a statute had been consulted."""

    def test_the_response_reports_coverage(self, studio):
        coverage = run(studio, GERMAN)["coverage"]
        assert "error" not in coverage
        assert coverage.get("verdict")

    def test_it_names_what_this_jurisdiction_cannot_detect(self, studio):
        """arche ships no German ID pack, so a set of categories is genuinely
        undetectable here. That is the real finding the wall was obscuring."""
        coverage = run(studio, GERMAN)["coverage"]
        assert coverage.get("uncovered")

    def test_coverage_failing_does_not_take_the_tab_down(self, studio, monkeypatch):
        """Findings are worth showing when the self-assessment is unavailable.
        An exception here would lose both."""
        class Boom:
            def __getattr__(self, name):
                raise RuntimeError("no")

        assert "error" in studio._coverage_report(Boom())


class TestTheLinkerStillWorks:
    """The pipeline emits `PII-1-NAME`, which `_LINKABLE` does not key on. A
    detection that arrived under its statute category would silently drop out
    of the cross-document matching this tab exists for."""

    def test_names_still_link_across_two_documents(self, studio):
        out = studio._documents({"documents": [
            {"name": "a.txt", "text": GERMAN},
            {"name": "b.txt", "text": GERMAN.replace("HRB 83385", "HRB 83386")}],
            "reveal": False})
        assert out["links"], "no links across two documents naming one person"

    def test_a_pii_category_maps_to_a_linkable_type(self, studio):
        assert studio._PII_KIND["PII-1-NAME"] == "PERSON"
        assert studio._PII_KIND["PII-4-ADDRESS"] == "LOCATION"

    def test_an_unmapped_category_degrades_to_its_own_tail(self, studio):
        """Better than UNKNOWN: `PII-6-HEALTH` reads as HEALTH, which is wrong
        about nothing."""
        class Detection:
            entity_type = None
            category = "PII-6-HEALTH"

        assert studio._entity_kind(Detection()) == "HEALTH"
