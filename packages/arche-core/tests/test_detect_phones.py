# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Tests for arche.detect.phones — multi-country phone detection.

Locks the v0.2 contract for the ``core`` detector package (PRD FR-DETECT-9):
- international + local-format African numbers detected, with E.164 metadata
- bare non-phone identifiers (dates, amounts, dashed account numbers, a
  labelled NIN) are NOT misclassified as phones
- Detection.category is PII-3-PHONE
- the Pipeline routes ``core`` here, so phones now flow through statute policy
  (tokenize) and carry the jurisdiction's regulatory citation
"""

from __future__ import annotations

from arche import Pipeline
from arche.detect.phones import detect_phones
from arche.workflow._primitive import Detection

# ----------------------------------------------------------------------
# detect_phones — unit
# ----------------------------------------------------------------------


def test_detects_international_nigerian_number() -> None:
    detections = detect_phones("Contact: +234 803 555 7890.")
    assert len(detections) == 1
    d = detections[0]
    assert isinstance(d, Detection)
    assert d.text == "+234 803 555 7890"
    assert d.category == "PII-3-PHONE"
    assert d.detector == "rule:phone_libphonenumber"
    assert d.confidence == 0.9
    assert d.metadata["international"] == "+2348035557890"
    assert d.metadata["country"] == "NG"


def test_detects_local_number_against_default_country() -> None:
    """A local 0-prefixed number is interpreted via default_country."""
    detections = detect_phones("Call 0803 555 7890", default_country="NG")
    assert len(detections) == 1
    assert detections[0].metadata["country"] == "NG"
    assert detections[0].metadata["international"] == "+2348035557890"


def test_detects_multiple_countries_sorted_by_offset() -> None:
    detections = detect_phones(
        "NG +234 803 555 7890 and KE +254 712 345678", default_country="NG"
    )
    assert [d.metadata["country"] for d in detections] == ["NG", "KE"]
    # sorted by character offset
    assert detections[0].start < detections[1].start


def test_offsets_extract_the_matched_number() -> None:
    text = "Reach me on +234 803 555 7890 anytime."
    d = detect_phones(text)[0]
    assert text[d.start:d.end] == d.text


def test_skips_non_phone_identifiers() -> None:
    """Dates, amounts, dashed account numbers, and a labelled NIN have no
    valid dialling prefix, so they are not detected as phones."""
    for non_phone in (
        "Bill Date: 2026-03-15",
        "Amount Due: NGN 45,750.00",
        "Account No: 0145-2367-8901",
        "NIN 12345678901 and BVN 22156789012",
    ):
        assert detect_phones(non_phone) == [], non_phone


def test_returns_empty_when_no_phone() -> None:
    assert detect_phones("No contact details in this sentence.") == []


# ----------------------------------------------------------------------
# Pipeline integration — phones now flow through statute policy
# ----------------------------------------------------------------------


def test_pipeline_ng_detects_and_tokenizes_phone() -> None:
    """Pipeline(jurisdiction='NG') detects the phone via the ``core`` package,
    classifies it under NDPA-2023, and tokenizes it in the redacted output."""
    result = Pipeline(jurisdiction="NG").process("Contact: +234 803 555 7890.")

    phones = [d for d in result.detections if d.category == "PII-3-PHONE"]
    assert len(phones) == 1
    assert phones[0].sensitivity_tier.value == "moderate"
    assert phones[0].regulatory_citation == "NDPA-2023 s.30"

    outcome = next(o for o in result.policy_outcomes if o.category == "PII-3-PHONE")
    assert outcome.action == "tokenize"

    # The raw number is gone; a phone token takes its place.
    assert "803 555 7890" not in result.redacted_text
    assert "PHONE_" in result.redacted_text


def test_pipeline_za_phone_uses_popia_citation() -> None:
    """The same detector runs under any jurisdiction; the citation comes from
    the loaded statute (POPIA for ZA)."""
    result = Pipeline(jurisdiction="ZA").process("Reach me on +27 82 123 4567.")

    phones = [d for d in result.detections if d.category == "PII-3-PHONE"]
    assert len(phones) == 1
    assert phones[0].metadata["country"] == "ZA"
    assert phones[0].regulatory_citation == "POPIA s.11"
