# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""UK postcode + jurisdiction inference tests.

Per docs/ceo-plans/2026-05-24-places-resolver.md §13 + §16.

CRITICAL: includes the mandatory NG regression test (§13.1 row 17 — IRON RULE).
The UK extension to addr/parse.py must NOT break existing NG/ZA/KE/GH inference.
"""

from __future__ import annotations

import pytest

from arche.addr import infer_jurisdiction, parse_address


# ── UK postcode detection (full + partial) ──────────────────────────────────


def test_infer_uk_full_postcode():
    """A full UK postcode in free text → ('GB', >=0.95)."""
    cc, conf, trigger = infer_jurisdiction("I'm at SE1 7EH right now.")
    assert cc == "GB"
    assert conf >= 0.95
    assert "SE1" in trigger and "7EH" in trigger


def test_infer_uk_full_postcode_in_address():
    """A full postcode anywhere in the text triggers GB inference."""
    cc, conf, _ = infer_jurisdiction(
        "Order ships to Westminster Bridge Rd, London SE1 7EH"
    )
    assert cc == "GB"
    assert conf >= 0.95


def test_infer_uk_partial_postcode():
    """A partial UK postcode ('SW1') → ('GB', ~0.85)."""
    cc, conf, trigger = infer_jurisdiction(
        "My mum lives near St Thomas' Hospital in SW1"
    )
    assert cc == "GB"
    assert 0.80 <= conf <= 0.90
    assert trigger == "SW1"


def test_infer_uk_partial_postcode_alphanumeric_district():
    """Districts like 'EC2A' (letter+digit+letter) should still match the partial pattern."""
    cc, conf, trigger = infer_jurisdiction("Office is in EC2A area")
    assert cc == "GB"
    assert trigger == "EC2A"
    assert conf >= 0.80


def test_infer_uk_two_letter_area():
    """Two-letter area like 'BS8' (Bristol) should match."""
    cc, conf, _ = infer_jurisdiction("My office is in BS8")
    assert cc == "GB"
    assert conf >= 0.80


# ── NG / ZA / KE / GH regression (MANDATORY per IRON RULE §13.1 row 17) ─────


def test_infer_ng_explicit_country_regression():
    """NG inference via explicit country name MUST still work after UK extension."""
    cc, conf, _ = infer_jurisdiction(
        "Customer Adesola Okonkwo, 12B Adetokunbo Crescent, Wuse 2, Abuja, Nigeria"
    )
    assert cc == "NG"
    assert conf >= 0.95


def test_infer_ng_via_parse_address_regression():
    """The existing parse_address() flow MUST still infer NG from city gazetteer."""
    addr = parse_address("7B Allen Avenue, Ikeja, Lagos, Nigeria")
    assert addr is not None
    assert addr.country_inferred == "NG"
    assert addr.country_confidence >= 0.95


def test_infer_za_via_parse_address_regression():
    """ZA inference via city gazetteer (Cape Town) MUST still work."""
    addr = parse_address("12 Long Street, Cape Town, 8001, South Africa")
    assert addr is not None
    assert addr.country_inferred == "ZA"


def test_infer_gh_postcode_specificity_regression():
    """Ghana GhanaPost GPS code 'GA-123-4567' MUST not be misread as UK."""
    cc, conf, trigger = infer_jurisdiction(
        "Residence verified at GPS code GA-123-4567, East Legon"
    )
    assert cc == "GH"
    assert conf >= 0.95
    assert trigger == "GA-123-4567"


# ── No-signal handling ──────────────────────────────────────────────────────


def test_infer_empty_text():
    """Empty text → ('XX', 0.0, '') — never silently default."""
    cc, conf, trigger = infer_jurisdiction("")
    assert cc == "XX"
    assert conf == 0.0
    assert trigger == ""


def test_infer_no_postcode_no_country():
    """Random text with no postcode + no country name → ('XX', 0.0)."""
    cc, conf, _ = infer_jurisdiction("just some random text about nothing important")
    assert cc == "XX"
    assert conf == 0.0


# ── Word boundary on country names (defensive) ──────────────────────────────


def test_country_name_word_boundary():
    """'Mali' must match the country but NOT inside 'malingerer'."""
    # In a normal sentence with the country name, match
    cc, _, _ = infer_jurisdiction("Visiting Bamako, Mali next week")
    assert cc == "ML"

    # Substring inside another word must NOT match
    cc, _, _ = infer_jurisdiction("That patient is a malingerer per the chart")
    assert cc == "XX"
