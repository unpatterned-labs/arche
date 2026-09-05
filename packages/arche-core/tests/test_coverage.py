# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Can this pipeline find the thing its statute told it to protect?

The bug
-------
`EgressGuard` had four fail-closed teeth and all four passed on this::

    EgressGuard(Pipeline(jurisdiction="GB"), key=...).guarded(
        "Björn Svensson lives in Manchester, SW1A 1AA, tel 07700 900123.")

    -> text returned verbatim, fields == [], statute UK-GDPR cited

The teeth check the boundary: is there a policy, is the provider allowed, is
the transfer permitted, did anything raise. None asked whether the pipeline was
*capable* of finding what the statute governs. Outside Africa it often is not,
by design — African ID regexes must not run against foreign identifiers — and
the result of that design decision was indistinguishable from a clean document.

What is asserted here
---------------------
Two things, and the second matters more than the first.

**The report is right.** A statute's categories and a detector set's categories
are both exactly knowable, so the gap between them is exactly knowable.

**The report cannot overstate.** A coverage report that claims protection which
is not there is worse than no report, because it converts a silence into a
false assurance. The `effective_detectors` tests exist because the first
implementation did exactly that: it read the *requested* detector list and
reported Nigerian ID coverage for a British pipeline that had already discarded
that pack.

What this does NOT claim
------------------------
Coverage is capability, not recall. `PII-1-NAME` reads as covered for `GB`
because a name detector ran, and that detector is calibrated on West African
names and will still miss "Björn Svensson". Category coverage is a floor on
honesty, not a completeness guarantee, and `test_coverage_is_not_recall` pins
that distinction so nobody later reads more into it.
"""

from __future__ import annotations

import warnings

import pytest
from arche import Pipeline
from arche.coverage import (
    CROSS_CUTTING_CATEGORIES,
    coverage,
    detectable_categories,
)
from arche.guard import EgressGuard, GuardDenied


class TestTheReportedBug:
    """British text, a British statute, and nothing removed."""

    TEXT = "Björn Svensson lives in Manchester, SW1A 1AA, tel 07700 900123."

    @pytest.fixture
    def projection(self):
        return EgressGuard(Pipeline(jurisdiction="GB"), key="secret").guarded(self.TEXT)

    def test_the_text_still_comes_back_unchanged(self, projection):
        """The premise. Fixing this was never about detecting more."""
        assert projection.redacted_text == self.TEXT
        assert projection.fields == []

    def test_but_it_no_longer_looks_like_a_clean_document(self, projection):
        assert projection.complete is False
        assert projection.coverage["verdict"] == "partial"

    def test_and_it_names_what_it_cannot_find(self, projection):
        """UK-GDPR governs a National Insurance number. Nothing installed
        can find one, and that is now on the record rather than implied."""
        assert "PII-2-NIN" in projection.coverage["uncovered"]

    def test_the_note_is_actionable_rather_than_a_status_word(self, projection):
        note = projection.coverage["note"]
        assert "no detector installed" in note
        assert "does not mean those are absent" in note

    def test_a_caller_reading_only_metadata_still_sees_it(self, projection):
        """The MCP handlers serialise `metadata` and drop the rest."""
        assert projection.metadata["coverage"] == "partial"
        assert "PII-2-NIN" in projection.metadata["uncovered_categories"]


class TestItCannotOverstate:
    """The failure mode that would make this worse than nothing.

    `detector_packages` is what was *asked for*. African ID packs are stripped
    at run time for a non-African jurisdiction, so the two lists differ, and
    reading the wrong one claims coverage that does not exist.
    """

    def test_requested_and_effective_differ(self):
        pipeline = Pipeline(jurisdiction="GB", detectors=["ng"])
        assert pipeline.detector_packages == ["ng"]
        assert pipeline.effective_detectors() == []

    def test_coverage_reads_the_effective_list(self):
        report = coverage(Pipeline(jurisdiction="GB", detectors=["ng"]))
        assert report["verdict"] == "none"
        assert "PII-2-NIN" not in report["detectable_categories"]

    def test_an_african_jurisdiction_keeps_its_pack(self):
        pipeline = Pipeline(jurisdiction="NG", detectors=["ng"])
        assert pipeline.effective_detectors() == ["ng"]

    def test_asking_does_not_emit_the_warning_that_running_does(self):
        """A coverage report must not warn about something the caller did not
        do. `_run_detectors` warns; `effective_detectors()` alone does not."""
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            coverage(Pipeline(jurisdiction="GB", detectors=["ng"]))


class TestTheFifthTooth:
    """Deny when the guard cannot do its job at all.

    Not when coverage is partial. Partial is the normal answer, including under
    NDPA-2023, and denying it would deny everything. Only when *nothing* the
    statute governs is detectable, where a clean result means nothing was
    looked for.
    """

    def test_zero_coverage_is_denied(self):
        guard = EgressGuard(Pipeline(jurisdiction="GB", detectors=["ng"]), key="k")
        with pytest.raises(GuardDenied, match="nothing was looked for"):
            guard.guarded("Björn Svensson")

    def test_the_denial_cites_the_statute(self):
        guard = EgressGuard(Pipeline(jurisdiction="GB", detectors=["ng"]), key="k")
        try:
            guard.guarded("Björn Svensson")
        except GuardDenied as exc:
            assert exc.citation == "UK-GDPR"

    def test_partial_coverage_is_not_denied(self):
        """The deliberate limit. Denying partial would deny Nigeria."""
        projection = EgressGuard(Pipeline(jurisdiction="NG"), key="k").guarded(
            "Adaeze Okonkwo, NIN 12345678901")
        assert projection.coverage["verdict"] == "partial"
        assert "[NIN:" in projection.redacted_text


class TestNigeriaIsPartialToo:
    """The honest half. This is not a report about foreigners.

    NDPA-2023 governs health, religion, biometric and device categories that
    arche ships no detector for. A report that said "full" for Nigeria and
    "partial" for Britain would be flattering rather than true.
    """

    @pytest.fixture
    def report(self):
        return coverage(Pipeline(jurisdiction="NG"))

    def test_nigeria_does_not_claim_full_coverage(self, report):
        assert report["verdict"] == "partial"

    @pytest.mark.parametrize("category", [
        "PII-6-HEALTH", "PII-6-RELIGION", "PII-6-BIOMETRIC", "PII-8-PASSWORD",
    ])
    def test_the_sensitive_categories_are_named_as_uncovered(self, report, category):
        assert category in report["uncovered"]

    def test_the_national_ids_are_covered(self, report):
        assert {"PII-2-NIN", "PII-2-BVN"} <= set(report["covered"])


class TestTheDeclaredMapMatchesReality:
    """`CROSS_CUTTING_CATEGORIES` is hand-written and could drift.

    The country packs cannot: their categories are read out of their own
    pattern tables. The cross-cutting ones are declared, so they get a probe.
    A package that emits a category the map does not claim would silently
    understate coverage, which is the safe direction, but it is still wrong.
    """

    PROBE = (
        "Adaeze Okonkwo, tel 08031234567, email a@b.ng, "
        "at 12 Aminu Kano Crescent, Wuse II, Abuja. IP 192.168.1.1. did:key:z6Mk."
    )

    @pytest.mark.parametrize("package", sorted(CROSS_CUTTING_CATEGORIES))
    def test_a_package_emits_nothing_it_does_not_declare(self, package):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            pipeline = Pipeline(jurisdiction=None, detectors=[package])
            emitted = {d.category for d in pipeline.process(self.PROBE).detections}
        assert emitted <= CROSS_CUTTING_CATEGORIES[package], (
            f"{package} emitted {sorted(emitted - CROSS_CUTTING_CATEGORIES[package])} "
            "which CROSS_CUTTING_CATEGORIES does not declare")

    def test_country_categories_come_from_the_pattern_tables(self):
        """Derived, not declared, so adding an identifier cannot desync them."""
        from arche.detect.ng.ids import NG_PATTERNS
        expected = {f"PII-2-{spec['id_type']}" for spec in NG_PATTERNS.values()}
        assert detectable_categories(["ng"]) == expected

    def test_the_africa_pack_is_the_union_of_the_countries(self):
        union = set()
        for country in ("ng", "ke", "za", "gh"):
            union |= detectable_categories([country])
        assert detectable_categories(["africa"]) == union

    def test_an_unknown_package_contributes_nothing_rather_than_raising(self):
        assert detectable_categories(["somebody-elses-detector"]) == set()


def test_coverage_is_not_recall():
    """The distinction the docstring makes, pinned so it cannot be forgotten.

    `PII-1-NAME` is reported covered for GB because a name detector ran. It
    still missed "Björn Svensson": the shipped lexicon is drawn from people
    recorded in African countries, and a Scandinavian name is not in it
    (*Jane Smith*, the original example, now is -- names travel). Coverage says
    a detector was there to miss it, which is strictly less than saying nothing
    was missed.
    """
    projection = EgressGuard(Pipeline(jurisdiction="GB"), key="k").guarded(
        "Björn Svensson lives in Manchester.")
    assert "PII-1-NAME" in projection.coverage["covered"]
    assert projection.fields == []
    assert "Björn Svensson" in projection.redacted_text


def test_no_statute_reports_no_statute_rather_than_full():
    """An empty governed set makes `uncovered` empty, which would compute as
    "full" if the case were not handled. Nothing governed is not full coverage.
    """
    report = coverage(Pipeline())
    assert report["verdict"] == "no-statute"
