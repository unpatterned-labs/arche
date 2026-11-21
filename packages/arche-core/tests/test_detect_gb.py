# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""United Kingdom identifier detection: NHS, NINO, passport, UTR, DVLA, CRN.

Every value here is invented. NHS numbers are built to pass modulus 11; the
NINOs use allocatable prefixes with made-up digits, plus HMRC's own ``QQ``
example prefix; the licence numbers are built from the DVLA layout.
"""

from __future__ import annotations

import pytest
from arche import Pipeline
from arche.detect.gb.ids import (
    GB_PATTERNS,
    _validate_gb_crn,
    _validate_gb_driving_licence,
    _validate_gb_nhs,
    _validate_gb_nino,
    detect_gb_ids,
    nhs_check_digit,
)


def _ids(text: str) -> list[tuple[str, str]]:
    return sorted((d.id_type, d.text) for d in detect_gb_ids(text))


# ── validators ───────────────────────────────────────────────────────────────


class TestValidators:
    @pytest.mark.parametrize("value", ["4010232137", "485 777 3457", "612-398-7453", "4500000003"])
    def test_nhs_mod11_holds(self, value):
        assert _validate_gb_nhs(value)[0]

    @pytest.mark.parametrize("value", [
        "4010232138",  # wrong check digit
        "1234567890",  # remainder gives 10: never issued
        "401023213",  # nine digits
    ])
    def test_nhs_rejected(self, value):
        assert not _validate_gb_nhs(value)[0]

    def test_check_digit_eleven_reads_as_zero_and_ten_is_none(self):
        assert nhs_check_digit("123456789") is None
        assert nhs_check_digit("401023213") == 7

    @pytest.mark.parametrize("value", ["AB123456C", "NP 65 43 21 B", "JG103759A", "ce123456d"])
    def test_nino_allocatable(self, value):
        assert _validate_gb_nino(value)[0]

    @pytest.mark.parametrize("value", [
        "DA123456A", "FA123456A", "IA123456A", "UA123456A", "VA123456A",  # bad first
        "AD123456A", "AF123456A", "AI123456A", "AO123456A", "AU123456A", "AV123456A",
        "BG123456A", "GB123456A", "KN123456A", "NK123456A", "NT123456A", "TN123456A",
        "ZZ123456A",  # unallocated prefixes
        "AB123456E",  # suffix beyond D
        "AB12345C",  # five digits
    ])
    def test_nino_rejected(self, value):
        assert not _validate_gb_nino(value)[0]

    def test_qq_is_well_formed_but_flagged_as_the_example_prefix(self):
        assert _validate_gb_nino("QQ123456C") == (True, {"example_prefix": True})

    @pytest.mark.parametrize(("value", "ok"), [
        ("WHITC657228E99AB", True),  # woman, July 22
        ("MORGA753116SM9IJ", True),  # woman, March 11
        ("MORGA703116SM9IJ", True),  # man, March 11
        ("LEE99002290J99AB", True),  # 9-padded surname, Feb 29 in a leap '00
        ("LEE99002291J99AB", False),  # Feb 29 in '01
        ("SMITH613328AB9CD", False),  # month 13
        ("SMITH663328AB9CD", False),  # month 63
        ("SMITH601008AB9CD", False),  # day 00
        ("SMITH604318AB9CD", False),  # April 31
        ("SM9TH601018AB9CD", False),  # 9 inside the surname
        ("99999601018AB9CD", False),  # no surname letter
        ("SMITH601018A99CD", True),  # one initial
        ("SMITH6010189A9CD", False),  # initials start with 9
    ])
    def test_driving_licence_structure_and_date(self, value, ok):
        assert _validate_gb_driving_licence(value)[0] is ok

    @pytest.mark.parametrize(("value", "ok"), [
        ("09876543", True), ("SC123456", True), ("NI123456", True), ("OC301234", True),
        ("XX123456", False), ("1234567", False), ("SC1234567", False),
    ])
    def test_company_number(self, value, ok):
        assert _validate_gb_crn(value)[0] is ok


# ── detection ────────────────────────────────────────────────────────────────


class TestNHS:
    @pytest.mark.parametrize(("text", "value"), [
        ("NHS no 485 777 3457", "485 777 3457"), ("nhs 4010232137", "4010232137"),
        ("NHS number: 485-777-3457", "485-777-3457"),
        ("National Health Service no. 4010232137", "4010232137"),
    ])
    def test_labelled_in_any_layout(self, text, value):
        assert _ids(text) == [("NHS", value)]

    def test_spaced_three_three_four_stands_alone(self):
        (d,) = detect_gb_ids("Discharge: Pieter, 612 398 7453, admitted")
        assert (d.id_type, d.text, d.metadata["labelled"]) == ("NHS", "612 398 7453", False)
        assert d.metadata["validator_status"] == "checksum_valid"

    @pytest.mark.parametrize("text", [
        "Ref 4010232137",  # bare ten digits: an order number as often as anything
        "Ref 485-777-3457",  # dashed 3-3-4 is a North American phone layout
        "Ref 500 000 0005",  # valid mod 11, unallocated range
        "Ref 100 000 0001",
        "tel 612 398 7453", "call me on 612 398 7453", "+1 612 398 7453",
        "NHS no 401 023 2138",  # labelled, wrong check digit
        "NHS no 123 456 7890",  # check digit 10
        "Call ext 612 398.",
    ])
    def test_rejected(self, text):
        assert _ids(text) == []

    def test_not_a_slice_of_a_longer_grouped_number(self):
        assert _ids("ref 01632 960 000 000") == []
        assert _ids("acct 9 612 398 7453") == []


class TestNINO:
    @pytest.mark.parametrize(("text", "value"), [
        ("NI number NP654321B", "NP654321B"),
        ("NINO: AB 12 34 56 C", "AB 12 34 56 C"),
        ("national insurance no ab123456c", "ab123456c"),
        ("on file AB123456C", "AB123456C"),  # capitals stand alone
    ])
    def test_detected(self, text, value):
        assert _ids(text) == [("NIN", value)]

    def test_lowercase_needs_the_label(self):
        assert _ids("code ab123456c") == []

    def test_example_prefix_only_with_a_label(self):
        assert _ids("QQ 12 34 56 C") == []
        (d,) = detect_gb_ids("NINO QQ 12 34 56 C")
        assert d.metadata["example_prefix"] is True and d.confidence < 0.85

    @pytest.mark.parametrize("text", ["NINO GB123456A", "NINO DA123456A", "NINO AB123456E"])
    def test_invalid_prefix_or_suffix_rejected_even_labelled(self, text):
        assert _ids(text) == []


class TestLabelOnly:
    def test_passport(self):
        assert _ids("passport 533380006") == [("PASSPORT", "533380006")]
        assert _ids("Passport No.: 533380006") == [("PASSPORT", "533380006")]
        assert _ids("order 533380006") == []

    @pytest.mark.parametrize("text", [
        "UTR 1234567890", "SA UTR: 12345 67890", "Unique Taxpayer Reference 1234567890",
        "self assessment ref 1234567890",
    ])
    def test_utr(self, text):
        assert [t for t, _ in _ids(text)] == ["TIN"]

    def test_utr_needs_its_label(self):
        assert _ids("PO 4482190312") == []

    @pytest.mark.parametrize("text", [
        "Company no 09876543", "company number SC123456", "CRN: OC301234",
        "Registered in England and Wales No. 09876543", "registered number 09876543",
    ])
    def test_company_number(self, text):
        assert [t for t, _ in _ids(text)] == ["RC"]

    def test_company_number_needs_its_label(self):
        assert _ids("Invoice 09876543") == []


class TestDrivingLicence:
    def test_capitals_stand_alone(self):
        assert _ids("WHITC657228E99AB") == [("DRIVERS_LICENCE", "WHITC657228E99AB")]

    def test_label_admits_lowercase_and_spacing(self):
        assert _ids("driving licence whitc 657228 E99AB") == [
            ("DRIVERS_LICENCE", "whitc 657228 E99AB")]
        assert _ids("whitc657228e99ab") == []

    def test_bad_date_rejected_even_labelled(self):
        assert _ids("driving licence SMITH613328AB9CD") == []


@pytest.mark.parametrize("text", [
    "INVOICE INV-2026-00417 order 4471-2290 account 41239876",
    "Call 07700 900461 or 020 7946 0321 or 0800 123 4567 or +44 113 496 0000",
    "sort code 20-45-77", "Date 01/11/2026, 2026-11-20",
    "Bristol BS1 5DS, Cardiff CF10 3AT, LS6 2QT",
    "ISBN 0-306-40615-2, ISBN 978-0-306-40615-7",
    "VAT GB 123 4567 89", "SKU A12345678", "ref 4482190312", "Ward 7B-12",
])
def test_negatives(text):
    assert _ids(text) == []


def test_kyc_note_finds_every_identifier():
    text = ("Patient, NHS no 485 777 3457, NINO AB 12 34 56 C, passport 533380006, "
            "UTR 1234567890, DL WHITC657228E99AB, Company no 09876543")
    assert _ids(text) == [
        ("DRIVERS_LICENCE", "WHITC657228E99AB"), ("NHS", "485 777 3457"),
        ("NIN", "AB 12 34 56 C"), ("PASSPORT", "533380006"), ("RC", "09876543"),
        ("TIN", "1234567890"),
    ]


def test_categories_as_the_pipeline_builds_them():
    text = ("NHS no 485 777 3457, NINO AB 12 34 56 C, passport 533380006, "
            "UTR 1234567890, DL WHITC657228E99AB, Company no 09876543")
    cats = {Pipeline._to_detection(d).category for d in detect_gb_ids(text)}
    declared = {f"PII-2-{spec['id_type']}" for spec in GB_PATTERNS.values()}
    assert cats == declared == {
        "PII-2-NHS", "PII-2-NIN", "PII-2-PASSPORT", "PII-2-TIN",
        "PII-2-DRIVERS_LICENCE", "PII-2-RC"}
