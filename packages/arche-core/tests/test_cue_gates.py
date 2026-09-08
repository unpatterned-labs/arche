# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""The cue-gate audit: patterns that read a document reference as personal data.

Each test here is one row of the detection benchmark's false-positive table
(`data/scripts/benchmark_pii.py`), fixed at the pattern it named, with the
count it carried. The positive test beside each negative one is the guard
against the fix removing the detector along with the false positive.
"""

from __future__ import annotations

import pytest
from arche.detect.model import _plausible, merge, propose_pii
from arche.detect.phones import detect_phones
from arche.workflow._primitive import Pipeline

# ---------------------------------------------------------------------------
# a bare eight-digit run is not a phone number (35 of 240 texts)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("text", [
    "receipt INV-97880932.", "Invoice PO 82141621 dated 2 March", "Deliver ORD-55062048 to",
])
def test_an_order_number_is_not_a_phone_somewhere_in_africa(text):
    assert detect_phones(text, default_country="NG") == []


@pytest.mark.parametrize("text, country", [
    ("Call 0722 123456", "KE"), ("Call 0803 555 7890", "NG"), ("Call 082 123 4567", "ZA"),
    ("Call +233 24 123 4567", "GH"), ("Ring 0712 345 678 today", "NG"),   # a KE number, NG default
])
def test_a_number_written_as_a_phone_is_still_found(text, country):
    found = detect_phones(text, default_country=country)
    assert len(found) == 1, (text, found)


# ---------------------------------------------------------------------------
# a bare seven- or eight-digit run is not a Kenyan id (25 of 240 texts)
# ---------------------------------------------------------------------------


def _ke(text):
    return [(d.category, d.text) for d in Pipeline(jurisdiction="KE").process(text).detections]


@pytest.mark.parametrize("text", [
    "Deliver ORD-40320191 to the clinic", "receipt INV-5613575.", "Invoice PO 36674714 dated",
])
def test_an_order_number_is_not_a_kenyan_id_or_nhif_number(text):
    assert not [c for c, _ in _ke(text) if c in ("PII-2-NATIONAL_ID", "PII-2-NHIF")]


@pytest.mark.parametrize("text, category, value", [
    ("ID No. 12345678", "PII-2-NATIONAL_ID", "12345678"),
    ("national ID 1234567 on file", "PII-2-NATIONAL_ID", "1234567"),
    ("her ID: 23456789", "PII-2-NATIONAL_ID", "23456789"),
    ("NHIF 123456789 only", "PII-2-NHIF", "123456789"),
    ("NHIF membership no. 87654321", "PII-2-NHIF", "87654321"),
])
def test_a_cued_kenyan_id_is_still_found(text, category, value):
    assert (category, value) in _ke(text)


def test_paid_is_not_an_id_cue():
    assert not [c for c, _ in _ke("paid 12345678 on Monday") if c == "PII-2-NATIONAL_ID"]


# ---------------------------------------------------------------------------
# INV-3702838222 is an invoice, not a licence from a state called INV (8)
# ---------------------------------------------------------------------------


def _ng(text):
    return [(d.category, d.text) for d in Pipeline(jurisdiction="NG").process(text).detections]


@pytest.mark.parametrize("text", ["INV-3702838222", "ORD-2731979678", "REF-12345678901"])
def test_a_document_reference_is_not_a_driving_licence(text):
    assert not [c for c, _ in _ng(text) if c == "PII-2-DRIVERS_LICENCE"]


def test_a_state_coded_licence_is_still_found():
    assert ("PII-2-DRIVERS_LICENCE", "LSD-1234567890") in _ng("Licence LSD-1234567890.")


# ---------------------------------------------------------------------------
# the model's proposals: a shape that cannot be what it is labelled
# ---------------------------------------------------------------------------


def test_an_all_digit_passport_proposal_is_dropped_and_a_real_one_kept():
    assert not _plausible("passport_number", "9876543210")
    assert _plausible("passport_number", "A12345678")


def test_a_short_bare_run_is_not_a_phone_proposal():
    assert not _plausible("phone_number", "55062048")
    assert _plausible("phone_number", "0722 123456")
    assert _plausible("phone_number", "+44 20 7946 0958")
    assert _plausible("phone_number", "722 123 4567")          # nine digits, no zero


def test_propose_pii_applies_the_shape_checks(monkeypatch):
    class Fake:
        def extract_entities(self, text, labels, **kw):
            return {"entities": {
                "passport_number": [{"text": "9876543210", "confidence": 0.9, "start": 0, "end": 10}],
                "phone_number": [{"text": "55062048", "confidence": 0.9, "start": 11, "end": 19},
                                 {"text": "0803 555 7890", "confidence": 0.9, "start": 20, "end": 33}],
            }}
    monkeypatch.setattr("arche._models.get_gliner2", lambda *a, **k: Fake())
    detections, _ = propose_pii("9876543210 55062048 0803 555 7890", backend="gliner2-pii")
    assert [(d.category, d.text) for d in detections] == [("PII-3-PHONE", "0803 555 7890")]
    assert merge([], detections) == detections
