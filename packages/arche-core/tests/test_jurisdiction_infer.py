# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Tests for jurisdiction inference.

The bug: `Pipeline(jurisdiction=...)` made the caller type a country code, and
typing the wrong one ran the Nigerian detector set over a British bank statement
and reported 36 tax identification numbers — every one a Bolt ride reference or
a Viator transaction ID, because a Nigerian TIN is ten digits and so are they.

The trap in fixing it: Britain had no statute pack, so "detecting the right
country" would have taken the error count from 36 to zero *by switching
redaction off*. Every test here that checks the false-positive count also checks
that the document is still redacted.
"""

from __future__ import annotations

import warnings

import pytest

from arche.jurisdictions.infer import (
    RULESET_VERSION,
    JurisdictionInference,
    infer_jurisdiction,
)

_UK_STATEMENT = (
    "Monzo Bank Limited, Broadwalk House, 5 Appold Street, London EC2A 2AG. "
    "Registered in England and Wales. Sort code 04-00-04. Balance £1,204.50."
)
_DE_INVOICE = (
    "Condor Flugdienst GmbH, Handelsregister HRB 12345. Gesamtbetrag €419,00."
)


class TestItFindsWhatIsThere:
    def test_a_uk_document(self):
        got = infer_jurisdiction(_UK_STATEMENT)
        assert got.country == "GB"
        assert not got.abstained
        assert got.confidence > 0.6

    def test_a_german_document(self):
        got = infer_jurisdiction(_DE_INVOICE)
        assert got.country == "DE"

    def test_the_reason_names_the_deciding_signal(self):
        """A reviewer must be able to check the conclusion, not just read it."""
        got = infer_jurisdiction(_UK_STATEMENT)
        assert "postcode" in got.reason or "registrar" in got.reason

    def test_evidence_is_returned_for_inspection(self):
        got = infer_jurisdiction(_UK_STATEMENT)
        assert got.evidence
        assert {e.country for e in got.evidence} >= {"GB"}
        assert all(e.tier in ("A", "B", "C") for e in got.evidence)


class TestAbstentionIsAResult:
    def test_empty_input_abstains(self):
        got = infer_jurisdiction("")
        assert got.abstained and got.country is None
        assert "no jurisdiction signals" in got.reason

    def test_thin_evidence_abstains(self):
        """One currency symbol does not name a country."""
        got = infer_jurisdiction("Total: $49.99")
        assert got.abstained
        assert "weak or corroborating" in got.reason

    def test_conflicting_evidence_abstains(self):
        """A German company billing in dollars is genuinely ambiguous."""
        got = infer_jurisdiction(
            "Widget GmbH invoice. Total $500.00. Betrag €450,00. Ltd partner."
        )
        assert got.abstained

    def test_an_abstention_is_falsy(self):
        assert not infer_jurisdiction("")
        assert infer_jurisdiction(_UK_STATEMENT)


class TestTierCCanNeverDecide:
    """The rule that keeps a printer's clock from choosing a legal regime.

    A UK user printing a US invoice produces a UK timestamp. If a timezone or a
    date format could name a country on its own, that clock would decide which
    detectors run and which statute applies.
    """

    def test_a_timezone_alone_does_not_name_a_country(self):
        class Meta:
            tz_offset_minutes = 0

        got = infer_jurisdiction("Invoice 12345. Thank you.", metadata=Meta())
        assert got.abstained
        assert got.country is None

    def test_a_date_format_alone_does_not_name_a_country(self):
        got = infer_jurisdiction("Issued 03/04/2026 and due 17/04/2026.")
        assert got.abstained

    def test_tier_c_can_corroborate_something_already_earned(self):
        class Meta:
            tz_offset_minutes = 0

        got = infer_jurisdiction(_UK_STATEMENT, metadata=Meta())
        assert got.country == "GB"
        assert any(e.signal == "timezone.pdf" for e in got.evidence)

    def test_one_tier_a_signal_is_enough(self):
        got = infer_jurisdiction("Registered in England and Wales.")
        assert got.country == "GB"

    def test_two_independent_tier_b_signals_are_enough(self):
        got = infer_jurisdiction("Acme Ltd. Total £42.00.")
        assert got.country == "GB"


class TestCountsAreCapped:
    def test_one_chatty_signal_cannot_swamp_the_document(self):
        """The Monzo statement has 166 dd/mm dates. They must not decide.

        What matters is how many distinct *kinds* of evidence agree, not how
        often one of them repeats.
        """
        many_dates = " ".join("01/02/2026" for _ in range(200))
        got = infer_jurisdiction(many_dates + " Widget Inc. Total $50.00.")
        gb = sum(e.weight for e in got.evidence if e.country == "GB")
        assert gb <= 0.5, "capped date evidence must stay small"


class TestCandidateFiltering:
    def test_candidates_restrict_the_answer(self):
        got = infer_jurisdiction(_UK_STATEMENT, candidates=["NG", "ZA"])
        assert got.country is None


class TestSerialisation:
    def test_to_dict_is_json_safe_and_masks_samples(self):
        import json

        got = infer_jurisdiction(_UK_STATEMENT)
        as_dict = got.to_dict()
        json.dumps(as_dict)
        assert all(e["sample"] == "" for e in as_dict["evidence"])
        assert any(e["sample"] for e in got.to_dict(reveal=True)["evidence"])

    def test_the_ruleset_version_travels(self):
        assert infer_jurisdiction(_UK_STATEMENT).ruleset_version == RULESET_VERSION

    def test_explain_reads_as_prose(self):
        text = infer_jurisdiction(_UK_STATEMENT).explain()
        assert "GB" in text and "evidence:" in text
        assert "abstained" in infer_jurisdiction("").explain()


class TestTheOriginalBug:
    """36 phantom tax numbers, and whether the fix is real or just flattering."""

    _TEXT = (
        "Monzo Bank Limited, London EC2A 2AG. Registered in England and Wales. "
        "BOLT.EU/O/2601272201 London GBR. VIATOR *IT-1747722393 London GBR. "
        "Contact jane.smith@monzo.com. Balance £1,204.50."
    )

    def test_the_wrong_jurisdiction_produces_phantom_identifiers(self):
        from arche import Pipeline

        result = Pipeline(jurisdiction="NG").process(self._TEXT)
        assert sum(1 for d in result.detections if d.category.endswith("TIN")) > 0

    def test_inference_finds_the_right_one(self):
        assert infer_jurisdiction(self._TEXT).country == "GB"

    def test_the_fix_removes_the_false_positives_AND_still_redacts(self):
        """The guard that stops this being a regression dressed as a fix.

        Before the UK pack existed, `jurisdiction="GB"` reported zero false
        positives and redacted nothing. A false-positive count is only an
        improvement if protection survives it.
        """
        from arche import Pipeline

        country = infer_jurisdiction(self._TEXT).country
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            result = Pipeline(jurisdiction=country, on_uncovered="baseline").process(
                self._TEXT
            )
        assert sum(1 for d in result.detections if d.category.endswith("TIN")) == 0
        assert result.redacted_text != self._TEXT, "0 false positives must not mean 0 protection"
        assert "jane.smith@monzo.com" not in result.redacted_text


class TestItIsAProposerNotADecider:
    def test_an_explicit_jurisdiction_always_wins(self):
        from arche.doc._documents import DocumentReport, _resolve_jurisdiction

        report = DocumentReport()
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            chosen, inferred = _resolve_jurisdiction(
                "NG", _UK_STATEMENT, None, "doc.pdf", report,
            )
        assert chosen == "NG"
        assert inferred is False

    def test_a_disagreement_is_recorded_not_swallowed(self):
        """'You said NG, the evidence says GB' — one warning, not 36 mysteries."""
        from arche.doc._documents import DocumentReport, _resolve_jurisdiction

        report = DocumentReport()
        with pytest.warns(UserWarning, match="evidence indicates 'GB'"):
            _resolve_jurisdiction("NG", _UK_STATEMENT, None, "doc.pdf", report)
        assert report.jurisdiction_conflicts["doc.pdf"] == ("NG", "GB")

    def test_agreement_is_silent(self):
        from arche.doc._documents import DocumentReport, _resolve_jurisdiction

        report = DocumentReport()
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            _resolve_jurisdiction("GB", _UK_STATEMENT, None, "doc.pdf", report)
        assert not report.jurisdiction_conflicts

    def test_auto_uses_the_inference_and_says_it_inferred(self):
        from arche.doc._documents import DocumentReport, _resolve_jurisdiction

        report = DocumentReport()
        chosen, inferred = _resolve_jurisdiction(
            "auto", _UK_STATEMENT, None, "doc.pdf", report,
        )
        assert (chosen, inferred) == ("GB", True)
        assert report.jurisdictions["doc.pdf"]["country"] == "GB"

    def test_auto_on_an_ambiguous_document_selects_no_statute(self):
        from arche.doc._documents import DocumentReport, _resolve_jurisdiction

        report = DocumentReport()
        chosen, inferred = _resolve_jurisdiction(
            "auto", "Total: $49.99", None, "doc.pdf", report,
        )
        assert chosen is None and inferred is False
        assert report.jurisdictions["doc.pdf"]["abstained"] is True
