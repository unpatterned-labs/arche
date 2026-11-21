# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Record identifiers: MRN, health-plan id, VIN, device id, URL."""

from __future__ import annotations

import pytest
from arche.detect.records import detect_record_ids, person_signal, vin_check_digit_valid


def _found(text: str) -> list[tuple[str, str]]:
    return [(d.category, d.text) for d in detect_record_ids(text)]


def test_hipaa_identifiers_from_the_audit_repro() -> None:
    text = ("MRN 00482913, health plan ID XKG882716431, VIN 1HGCM82633A004352, "
            "pacemaker serial PM-SN 88123-XZ, https://portal.example.com/patients/hope-washington")
    assert _found(text) == [
        ("PII-2-MRN", "00482913"),
        ("PII-2-HEALTH_PLAN_ID", "XKG882716431"),
        ("PII-8-VEHICLE_ID", "1HGCM82633A004352"),
        ("PII-8-DEVICE_ID", "PM-SN 88123-XZ"),
        ("PII-8-URL", "https://portal.example.com/patients/hope-washington"),
    ]
    url = detect_record_ids(text)[-1]
    assert url.metadata["has_name_or_id_path"] is True
    assert url.metadata["patient_path"] is True


@pytest.mark.parametrize(("text", "expected"), [
    ("Hospital no LUTH/2026/04417.", [("PII-2-MRN", "LUTH/2026/04417")]),
    ("Medical record number: A-778812", [("PII-2-MRN", "A-778812")]),
    ("Patient ID 99812301", [("PII-2-MRN", "99812301")]),
    ("Medical aid no DIS1234567.", [("PII-2-HEALTH_PLAN_ID", "DIS1234567")]),
    ("Member ID: W123456789", [("PII-2-HEALTH_PLAN_ID", "W123456789")]),
    ("IMEI 490154203237518", [("PII-8-DEVICE_ID", "490154203237518")]),
    ("S/N: AB-12345", [("PII-8-DEVICE_ID", "AB-12345")]),
    ("mac 00:1A:2B:3C:4D:5E", [("PII-8-DEVICE_ID", "00:1A:2B:3C:4D:5E")]),
])
def test_labelled_record_numbers(text: str, expected: list[tuple[str, str]]) -> None:
    assert _found(text) == expected


@pytest.mark.parametrize("text", [
    "MRN pending; patient no longer attends.",
    "The serial killer was caught. Serial 2 of 5.",
    "Group 00 and serial 0000 are invalid.",
    "IMEI 490154203237519",                 # Luhn fails
    "Meeting at 10:30:00 in room 4.",
    "order 1HGCM82633A004353",             # VIN check digit fails, no VIN label
    "Contact example.com for details.",     # bare domain without a path
    "Email j.botha@firm.example.co.za today.",
])
def test_not_record_ids(text: str) -> None:
    assert _found(text) == []


def test_vin_check_digit() -> None:
    assert vin_check_digit_valid("1HGCM82633A004352")
    assert not vin_check_digit_valid("1HGCM82633A004353")
    assert not vin_check_digit_valid("1HGCM82633A00435")       # 16 chars
    assert not vin_check_digit_valid("1HGCM82633AO04352")      # O is not in the alphabet


def test_labelled_vin_without_check_digit_is_accepted_and_flagged() -> None:
    [d] = detect_record_ids("VIN: WVWZZZ1JZXW000001")
    assert d.category == "PII-8-VEHICLE_ID"
    assert d.metadata["check_digit_valid"] is False
    assert d.metadata["labelled"] is True


@pytest.mark.parametrize(("url", "person"), [
    ("https://www.linkedin.com/in/grace-oyelaran-55a1b2", True),
    ("github.com/seun-adebayo", True),
    ("https://firm.example.co.za/staff/johannes-botha", True),
    ("https://example.org/report?patient_id=4471", True),
    ("https://www.gov.uk/tax", False),
    ("https://github.com/features", False),
])
def test_url_person_signal(url: str, person: bool) -> None:
    [d] = detect_record_ids(f"See {url}.")
    # A URL that names or identifies no one is its own category, so each
    # statute pack states its choice (HIPAA removes it; GDPR keeps it).
    assert d.category == ("PII-8-URL" if person else "PII-8-URL_OTHER")
    assert d.text == url
    assert d.metadata["has_name_or_id_path"] is person
    assert (person_signal(url) is not None) is person
