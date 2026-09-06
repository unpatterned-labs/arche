# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Detectors that ran for a place they were not built for.

Coverage answers *"is there a detector for this category?"*. It closed the case
where the answer was no and the result looked clean anyway. It left one level
down untouched: a detector can be installed, run, report its category as
covered, and find nothing because it was built for somewhere else.

That is what the original UK example actually hit. Three detectors ran on
``"Jane Smith lives in Manchester, SW1A 1AA, tel 07700 900123."`` and all three
are African-calibrated:

===========  ==================================  ==========================
pack         finds                               misses
===========  ==================================  ==========================
``names``    ``Adaeze Okonkwo``                  ``Björn Svensson``
``locations``  ``Kano State``                    ``Manchester``, ``Munich``
``core``     ``+2348031234567``                  ``+447700900123``, ``+49…``
===========  ==================================  ==========================

Coverage called all three covered, correctly, and the document came back
untouched. Naming the mismatch is what makes that legible.

Two of these were measured rather than assumed, and both were surprises.
``core`` sounds like a general phone parser and is not. ``locations`` sounds
like a gazetteer and is African.

The reported categories stay in ``covered`` and appear again in
``degraded_categories``. Moving them to ``uncovered`` would claim more than is
known: a lexicon built in Lagos still matches a name that happens to be in it.
"""

from __future__ import annotations

import warnings

import pytest
from arche import Pipeline
from arche.coverage import (
    DETECTOR_CALIBRATION,
    calibration_mismatch,
    coverage,
)
from arche.guard import EgressGuard


@pytest.fixture(autouse=True)
def _quiet():
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        yield


class TestTheMeasurementsBehindTheDeclaration:
    """`DETECTOR_CALIBRATION` is a claim about behaviour. These check it.

    A declaration nobody verifies is how the coverage map would have drifted,
    and this one carries more weight because it is what a reader will trust
    when deciding whether a clean result means anything.
    """

    @pytest.mark.parametrize("pack,found,missed", [
        # `Jane Smith` used to be the miss. The shipped 13k lexicon is drawn
        # from people recorded in African countries, and *Jane* and *Smith*
        # are both in it -- names travel. A Scandinavian name is still not.
        ("names", "Adaeze Okonkwo lives here.", "Björn Svensson lives here."),
        ("locations", "Kano State, Nigeria", "Munich, Bavaria"),
        ("core", "+2348031234567", "+4915112345678"),
    ])
    def test_the_african_packs_really_are_african(self, pack, found, missed):
        pipeline = Pipeline(jurisdiction=None, detectors=[pack])
        assert pipeline.process(found).detections, f"{pack} should find {found!r}"
        assert not pipeline.process(missed).detections, (
            f"{pack} found {missed!r}, so it is no longer African-only and "
            "DETECTOR_CALIBRATION is now wrong")

    @pytest.mark.parametrize("text", ["a@example.ng", "x@example.co.uk"])
    def test_a_global_pack_really_is_global(self, text):
        """Email is shape-defined, not place-defined."""
        assert Pipeline(jurisdiction=None, detectors=["emails"]).process(text).detections

    @pytest.mark.parametrize("text", [
        "12 Aminu Kano Crescent, Wuse II, Abuja",
        "221B Baker Street, London NW1 6XE",
    ])
    def test_addr_covers_both_the_regions_it_claims(self, text):
        assert Pipeline(jurisdiction=None, detectors=["addr"]).process(text).detections


class TestTheOriginalCase:

    @pytest.fixture
    def report(self):
        return EgressGuard(Pipeline(jurisdiction="GB"), key="k").guarded(
            "Jane Smith lives in Manchester, SW1A 1AA, tel 07700 900123.").coverage

    def test_the_three_detectors_that_failed_are_named(self, report):
        assert {m["detector"] for m in report["calibration_mismatch"]} == {
            "names", "locations", "core"}

    def test_their_categories_are_marked_degraded(self, report):
        assert report["degraded_categories"] == [
            "PII-1-NAME", "PII-3-PHONE", "PII-4-LOCATION"]

    def test_degraded_categories_stay_covered(self, report):
        """They are not moved to `uncovered`. A detector did run, and a
        mismatched detector is degraded rather than absent."""
        assert set(report["degraded_categories"]) <= set(report["covered"])
        assert not set(report["degraded_categories"]) & set(report["uncovered"])

    def test_the_note_mentions_both_problems(self, report):
        note = report["note"]
        assert "no detector installed" in note
        assert "built for somewhere else" in note

    def test_each_mismatch_says_where_it_was_built_for(self, report):
        names = next(m for m in report["calibration_mismatch"]
                     if m["detector"] == "names")
        assert names["calibrated_for"] == ["AFRICA"]
        assert "African name lexicon" in names["note"]


class TestNoFalseAlarms:

    def test_an_african_jurisdiction_has_no_mismatch(self):
        report = coverage(Pipeline(jurisdiction="NG"))
        assert report["calibration_mismatch"] == []
        assert report["degraded_categories"] == []

    @pytest.mark.parametrize("code", ["KE", "ZA", "GH", "RW", "TZ"])
    def test_nor_do_the_other_african_jurisdictions(self, code):
        """`AFRICA` resolves through `Pipeline._AFRICAN_JURISDICTIONS`, so a
        country with no ID pack of its own still counts as in-region."""
        assert coverage(Pipeline(jurisdiction=code))["calibration_mismatch"] == []

    def test_addr_is_not_flagged_for_gb(self):
        """It claims AFRICA and GB, and both were measured."""
        report = coverage(Pipeline(jurisdiction="GB"))
        assert "addr" not in {m["detector"] for m in report["calibration_mismatch"]}

    def test_an_unknown_detector_is_not_accused(self):
        """This module cannot assess somebody else's detector, so it must not
        claim a mismatch it has no basis for."""
        assert calibration_mismatch(["somebody-elses-detector"], "GB") == []

    def test_no_jurisdiction_means_no_mismatch(self):
        assert calibration_mismatch(["names", "core"], None) == []


class TestTheDeclarationIsComplete:

    def test_every_package_the_pipeline_can_run_has_a_calibration(self):
        """A pack with no entry is silently treated as calibrated, which is the
        safe default and also a way for a new pack to go unreported."""
        from arche.coverage import CROSS_CUTTING_CATEGORIES
        missing = set(CROSS_CUTTING_CATEGORIES) - set(DETECTOR_CALIBRATION)
        assert not missing, f"no calibration declared for {sorted(missing)}"

    def test_a_country_pack_is_scoped_to_its_country(self):
        assert DETECTOR_CALIBRATION["ng"][0] == frozenset({"NG"})

    def test_every_cross_cutting_african_pack_explains_itself(self):
        """A mismatch report with no reason is a status word.

        Only the cross-cutting packs need one. `africa` is an ID pack whose
        scope is a statement of what it detects, not a warning about degraded
        recall somewhere else — the pipeline refuses to run it outside Africa
        at all, so it can never be the subject of a mismatch report.
        """
        from arche.coverage import CROSS_CUTTING_CATEGORIES
        for pack, (regions, note) in DETECTOR_CALIBRATION.items():
            if regions == frozenset({"AFRICA"}) and pack in CROSS_CUTTING_CATEGORIES:
                assert note, f"{pack} claims AFRICA with no explanation"

    def test_the_africa_id_pack_can_never_be_reported_as_mismatched(self):
        """Because the pipeline strips it rather than running it out of region,
        so it is never in the effective list when it would be a mismatch."""
        from arche import Pipeline
        assert Pipeline(jurisdiction="GB", detectors=["africa"]).effective_detectors() == []


def test_calibration_is_the_layer_below_coverage():
    """Stated as a test because the two are easy to conflate.

    For GB: 6 categories have no detector, 3 have a detector built elsewhere,
    and 4 are genuinely covered. Only the first number is `uncovered`.
    """
    report = coverage(Pipeline(jurisdiction="GB"))
    genuinely_covered = set(report["covered"]) - set(report["degraded_categories"])
    assert len(report["uncovered"]) == 6
    assert len(report["degraded_categories"]) == 3
    assert genuinely_covered == {
        "PII-2-DID", "PII-3-EMAIL", "PII-4-ADDRESS", "PII-5-CRYPTO_WALLET"}
