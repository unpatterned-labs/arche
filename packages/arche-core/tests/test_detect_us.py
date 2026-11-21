# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""United States detection: SSN, ITIN, EIN, NPI, NANP phones and ZIP codes.

Every value here is invented. Positive SSNs use well-formed but obviously
made-up numbers; negatives use the never-issued ranges (``000``, ``666``,
``9xx``). The NPIs are the CMS check-digit example ``1234567893`` and numbers
built to pass the same Luhn rule.
"""

from __future__ import annotations

import warnings

import pytest
from arche import Pipeline, deidentify
from arche.coverage import detectable_categories
from arche.detect.us.ids import (
    _validate_us_ein,
    _validate_us_itin,
    _validate_us_npi,
    _validate_us_ssn,
    detect_us_ids,
)
from arche.detect.us.phones import detect_us_phones
from arche.detect.us.zip import detect_us_zips, restricted_zip3, safe_harbor_zip3


def _ids(text: str) -> list[tuple[str, str]]:
    return sorted((d.id_type, d.text) for d in detect_us_ids(text))


# ── validators ───────────────────────────────────────────────────────────────


class TestValidators:
    @pytest.mark.parametrize("value", ["123-45-6789", "123 45 6789", "234567890", "665-12-3456"])
    def test_ssn_well_formed(self, value):
        assert _validate_us_ssn(value)[0]

    @pytest.mark.parametrize("value", [
        "000-12-3456",  # area 000
        "666-12-3456",  # area 666
        "900-12-3456", "999-99-9999",  # area 9xx (ITIN / never issued)
        "123-00-4567",  # group 00
        "123-45-0000",  # serial 0000
        "078-05-1120",  # Woolworth wallet card
        "219-09-9999",  # SSA advertising number
        "12345678",  # eight digits
    ])
    def test_ssn_rejected(self, value):
        assert not _validate_us_ssn(value)[0]

    @pytest.mark.parametrize(("value", "ok"), [
        ("912-50-1234", True), ("912-65-1234", True), ("912-70-1234", True),
        ("912-88-1234", True), ("912-90-1234", True), ("912-92-1234", True),
        ("912-94-1234", True), ("912-99-1234", True),
        ("912-49-1234", False), ("912-66-1234", False), ("912-69-1234", False),
        ("912-89-1234", False), ("912-93-1234", False), ("812-70-1234", False),
    ])
    def test_itin_groups(self, value, ok):
        assert _validate_us_itin(value)[0] is ok

    @pytest.mark.parametrize(("value", "ok"), [
        ("12-3456789", True), ("01-2345678", True), ("99-1234567", True),
        ("31-1234567", True),  # SBA
        ("00-1234567", False), ("07-1234567", False), ("19-1234567", False),
        ("28-1234567", False), ("49-1234567", False), ("69-1234567", False),
        ("70-1234567", False), ("79-1234567", False), ("89-1234567", False),
        ("96-1234567", False), ("97-1234567", False),
    ])
    def test_ein_prefixes(self, value, ok):
        assert _validate_us_ein(value)[0] is ok

    @pytest.mark.parametrize(("value", "ok"), [
        ("1234567893", True),  # CMS's own check-digit example
        ("1987654328", True), ("2123456784", True),
        ("1234567890", False),  # wrong check digit
        ("3234567893", False),  # must start 1 or 2
        ("123456789", False),
    ])
    def test_npi_luhn(self, value, ok):
        assert _validate_us_npi(value)[0] is ok


# ── detection ────────────────────────────────────────────────────────────────


class TestSSN:
    def test_dashed_and_spaced_stand_alone(self):
        assert _ids("on file: 123-45-6789") == [("SSN", "123-45-6789")]
        assert _ids("on file: 123 45 6789") == [("SSN", "123 45 6789")]

    @pytest.mark.parametrize("text", [
        "SSN 234567890", "ssn: 234567890", "Social Security Number: 234567890",
        "social security no. 234567890", "SS# 234567890",
    ])
    def test_bare_nine_digits_need_the_label(self, text):
        assert _ids(text) == [("SSN", "234567890")]

    @pytest.mark.parametrize("text", [
        "Invoice 234567890", "order number 234567890", "234567890", "Ref: 234567890",
    ])
    def test_a_bare_digit_run_is_not_an_ssn(self, text):
        assert _ids(text) == []

    def test_invalid_ranges_are_not_detected_even_labelled(self):
        assert _ids("SSN 900-12-3456, SSN 666-12-3456, SSN 078-05-1120") == []

    def test_mixed_separators_are_not_an_ssn(self):
        assert _ids("123-45 6789") == []

    def test_label_is_not_in_the_span(self):
        (d,) = detect_us_ids("SSN: 123-45-6789")
        assert d.text == "123-45-6789" and d.metadata["labelled"] is True

    def test_label_inside_a_word_is_not_a_label(self):
        assert _ids("Martin 234567890") == []


class TestOthers:
    def test_itin_formatted_and_labelled(self):
        assert _ids("912-70-1234") == [("ITIN", "912-70-1234")]
        assert _ids("ITIN 912701234") == [("ITIN", "912701234")]
        assert _ids("912701234") == []

    def test_ein_formatted_and_labelled(self):
        assert _ids("12-3456789") == [("EIN", "12-3456789")]
        assert _ids("EIN: 123456789") == [("EIN", "123456789")]
        assert _ids("Employer Identification Number 123456789") == [("EIN", "123456789")]
        assert _ids("07-1234567") == []  # unassigned prefix

    def test_npi_needs_its_label(self):
        assert _ids("NPI 1234567893") == [("NPI", "1234567893")]
        assert _ids("National Provider Identifier: 1234567893") == [("NPI", "1234567893")]
        assert _ids("Order 1234567893") == []
        assert _ids("NPI 1234567890") == []  # bad check digit

    def test_npi_is_checksum_valid_the_others_format_valid(self):
        status = {d.id_type: d.metadata["validator_status"]
                  for d in detect_us_ids("NPI 1234567893, SSN 123-45-6789, EIN 12-3456789")}
        assert status == {"NPI": "checksum_valid", "SSN": "format_valid",
                          "EIN": "format_valid"}

    @pytest.mark.parametrize("text", [
        "Invoice 2026-11-20 total $1,234.56", "Order #4471-2290-118", "Qty 12, $123.45",
        "Visit 11/20/2026", "PO 123456789",
    ])
    def test_negatives(self, text):
        assert _ids(text) == []


class TestPhones:
    @pytest.mark.parametrize("text", [
        "(212) 555-0147", "212-555-0147", "212.555.0147", "212 555 0147",
        "+1 212 555 0147", "+12125550147", "1-212-555-0147", "+1 (212) 555-0147",
    ])
    def test_nanp_shapes(self, text):
        assert [h["international"] for h in detect_us_phones(text)] == ["+12125550147"]

    @pytest.mark.parametrize("text", [
        "2125550147",  # bare ten digits: an NPI or order number as often as a phone
        "2026-11-20", "12.05.2026", "11/20/2026",
        "212-555.0147",  # mixed separators
        "112-555-0147", "212-155-0147",  # area / exchange start with 1
        "012-555-0147",
        "911-555-0147",  # N11 is not an area code
        "Order 212-555-0147", "Invoice #: 646.555.0199", "$212.555.0147",
    ])
    def test_not_phones(self, text):
        assert detect_us_phones(text) == []

    def test_fictional_555_numbers_are_still_masked(self):
        # arche treats 555 numbers as phones throughout; masking one costs nothing.
        assert detect_us_phones("call 212-555-0199")

    def test_pipeline_routes_us_phones_through_core(self):
        result = Pipeline(jurisdiction="US").process("Call (212) 555-0147 today.")
        phones = [d for d in result.detections if d.category == "PII-3-PHONE"]
        assert [d.metadata["international"] for d in phones] == ["+12125550147"]


class TestZip:
    def test_after_a_state_or_the_word_zip(self):
        found = [d.text for d in detect_us_zips(
            "Springfield, IL 62701-1234. Austin, Texas 78701. ZIP: 05901.")]
        assert found == ["62701-1234", "78701", "05901"]

    @pytest.mark.parametrize("text", ["Total 12345.", "in 46204 or 97201", "Room 62701"])
    def test_a_bare_five_digit_run_is_not_a_zip(self, text):
        assert detect_us_zips(text) == []

    def test_the_bundled_table_is_the_hhs_list(self):
        assert restricted_zip3() == frozenset({
            "036", "059", "063", "102", "203", "556", "692", "790", "821", "823",
            "830", "831", "878", "879", "884", "890", "893"})

    @pytest.mark.parametrize(("zip_code", "expected"), [
        ("62701", "627"), ("62701-1234", "627"), ("82414", "824"),
        ("82301", "000"), ("05901", "000"), ("89301-0001", "000"), ("12", "000"),
    ])
    def test_safe_harbor_zip3(self, zip_code, expected):
        assert safe_harbor_zip3(zip_code) == expected

    def test_hipaa_generalizes_a_zip_to_its_zip3(self):
        out = deidentify("Springfield, IL 62701 and Rawlins, WY 82301.", "US",
                         backend="basic", statute="HIPAA-SAFE-HARBOR")
        assert "62701" not in out.text and "82301" not in out.text
        zips = [o.applied_value for o in out.outcomes if o.category == "PII-4-ZIP"]
        assert zips == ["627", "000"]


# ── routing and coverage ─────────────────────────────────────────────────────


def test_us_jurisdiction_runs_the_us_pack():
    assert "us" in Pipeline(jurisdiction="US").effective_detectors()
    assert "us" not in Pipeline(jurisdiction="GB").effective_detectors()
    assert "us" not in Pipeline().effective_detectors()


def test_the_us_pack_emits_only_what_coverage_declares():
    probe = ("SSN 123-45-6789, ITIN 912-70-1234, EIN 12-3456789, NPI 1234567893, "
             "Springfield, IL 62701")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        emitted = {d.category for d in
                   Pipeline(jurisdiction="US", detectors=["us"]).process(probe).detections}
    assert emitted == detectable_categories(["us"]) == {
        "PII-2-SSN", "PII-2-ITIN", "PII-2-EIN", "PII-2-NPI", "PII-4-ZIP"}


def test_ssn_is_a_foundational_identifier():
    det = next(d for d in Pipeline(jurisdiction="US").process("SSN 123-45-6789").detections
               if d.category == "PII-2-SSN")
    assert det.identity_class == "foundational"


# ── end to end ───────────────────────────────────────────────────────────────

NOTE = """\
Clinic visit note (invented test record)
Patient: Jane Smith    SSN: 123-45-6789    ITIN 912-70-1234
Phone (212) 555-0147, alt 646.555.0199, fax +1 312 555 0188
Email jane.smith@example.com
Address: 100 Main Street, Springfield, IL 62701
Referring provider NPI 1234567893, practice EIN 12-3456789
Invoice 2026-4471 for $1,234.56 paid.
"""

IDENTIFIERS = [
    "Jane Smith", "123-45-6789", "912-70-1234", "(212) 555-0147", "646.555.0199",
    "+1 312 555 0188", "jane.smith@example.com", "100 Main Street", "62701",
    "1234567893", "12-3456789",
]


@pytest.mark.parametrize("statute", [None, "HIPAA-SAFE-HARBOR"])
def test_clinical_note_leaves_no_identifier_in_clear(statute):
    out = deidentify(NOTE, "US", backend="basic", statute=statute)
    leaked = [v for v in IDENTIFIERS if v in out.text]
    assert leaked == [], f"left in clear: {leaked}"
    # What is not an identifier survives.
    assert "$1,234.56" in out.text and "Invoice 2026-4471" in out.text


def test_without_a_statute_the_us_falls_back_to_the_baseline_floor():
    out = deidentify(NOTE, "US", backend="basic")
    assert out.statute == "BASELINE"


def test_dates_are_reduced_to_the_year():
    # Was a strict xfail until the `dates` package landed (20 Nov 2026).
    out = deidentify("Admitted 2026-03-14, DOB 03/14/1931, aged 93.", "US",
                     backend="basic", statute="HIPAA-SAFE-HARBOR")
    assert out.text == "Admitted 2026, DOB [DOB 90+], aged 90+."
