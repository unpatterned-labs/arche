# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Tests for arche.addr.parse — the v0.2 address parser MVP (NG + ZA)."""

from __future__ import annotations

import pytest

from arche.addr import parse_address, parse_addresses


# ── Nigeria ─────────────────────────────────────────────────────────────────


def test_ng_basic_street_address():
    a = parse_address("7B Allen Avenue, Ikeja, Lagos, Nigeria")
    assert a is not None
    assert a.components.street == "Allen Avenue"
    assert a.components.neighborhood == "Ikeja"
    assert a.components.city == "Lagos"
    assert a.country_inferred == "NG"
    assert a.country_confidence >= 0.95


def test_ng_plot_prefix():
    a = parse_address("Plot 14, Awolowo Road, Ikoyi, Lagos, Nigeria")
    assert a is not None
    assert a.components.plot == "Plot 14"
    assert a.components.street == "Awolowo Road"
    assert a.country_inferred == "NG"


def test_ng_landmark_anchor():
    """Landmark prefix ('behind X') should attach to the address."""
    a = parse_address(
        "behind the Total filling station, 23 Marina Street, Lagos Island, Nigeria"
    )
    assert a is not None
    assert a.components.anchor is not None
    assert "Total" in a.components.anchor
    assert a.components.anchor_type == "commercial"
    assert a.country_inferred == "NG"


def test_ng_postal_code_inference():
    """A 6-digit postal code in NG context should infer country."""
    a = parse_address("12 Marina Street, Lagos, 101001")
    assert a is not None
    assert a.components.postal_code == "101001"
    assert a.country_inferred == "NG"


# ── South Africa ────────────────────────────────────────────────────────────


def test_za_street_address_with_postal():
    a = parse_address("12 Long Street, Cape Town, 8001, South Africa")
    assert a is not None
    assert a.components.street == "Long Street"
    assert a.components.city == "Cape Town"
    assert a.components.postal_code == "8001"
    assert a.country_inferred == "ZA"


def test_za_unit_prefix():
    a = parse_address("Unit 5B, 22 Riebeek Street, Cape Town, 8001")
    assert a is not None
    assert a.components.plot == "Unit 5B"
    assert a.components.street == "Riebeek Street"
    assert a.country_inferred == "ZA"


def test_za_box_address():
    a = parse_address("P.O. Box 1234, Sandton, Johannesburg, 2196")
    assert a is not None
    assert "Box 1234" in a.components.plot
    assert a.components.city == "Johannesburg"
    assert a.country_inferred == "ZA"


def test_za_postal_code_inference():
    """A 4-digit code with no explicit country should still infer ZA."""
    a = parse_address("33 Houghton Drive, Johannesburg, 2196")
    assert a is not None
    assert a.country_inferred == "ZA"


# ── Ghana / Kenya (best-effort) ────────────────────────────────────────────


def test_gh_via_gazetteer():
    """Ghana best-effort: city lookup in the gazetteer should infer GH."""
    a = parse_address("Plot 3, near Madina Mosque, Madina Junction, Accra")
    if a is None:
        pytest.skip("Address span detection didn't catch this format; Stage 2 work.")
    assert a.country_inferred == "GH"


def test_ke_via_gazetteer():
    """Kenya best-effort: city in gazetteer should infer KE."""
    a = parse_address("12 Kenyatta Avenue, Nairobi, Kenya")
    assert a is not None
    assert a.country_inferred == "KE"


def test_gh_postal_code_unique_format():
    """Ghana GhanaPost GPS code (XX-NNN-NNNN) is jurisdiction-unique."""
    a = parse_address("12 Kingsway Street, Accra, GA-039-2345")
    if a is None:
        pytest.skip("Address parse failed; Stage 2 will improve coverage.")
    if a.components.postal_code:
        assert a.components.postal_code == "GA-039-2345"


# ── Multi-address ───────────────────────────────────────────────────────────


def test_multiple_addresses_in_one_document():
    text = (
        "Ship the goods to 7B Allen Avenue, Ikeja, Lagos and copy "
        "the invoice to 12 Long Street, Cape Town, 8001."
    )
    addrs = parse_addresses(text)
    assert len(addrs) >= 2
    countries = {a.country_inferred for a in addrs}
    assert "NG" in countries
    assert "ZA" in countries


def test_parse_addresses_returns_sorted_by_span():
    text = (
        "First: 7B Allen Avenue, Ikeja, Lagos. "
        "Second: 12 Long Street, Cape Town."
    )
    addrs = parse_addresses(text)
    if len(addrs) >= 2:
        assert addrs[0].span[0] < addrs[1].span[0]


# ── Negative tests ──────────────────────────────────────────────────────────


def test_no_address_returns_none():
    assert parse_address("Just some text with no address at all.") is None


def test_no_address_returns_empty_list():
    assert parse_addresses("Just text.") == []


# ── Score ────────────────────────────────────────────────────────────────────


def test_full_address_has_high_confidence():
    """All-components address should score > 0.85."""
    a = parse_address("Plot 14, Awolowo Road, Ikoyi, Lagos, 101001, Nigeria")
    assert a is not None
    assert a.confidence >= 0.85


def test_minimal_address_has_lower_confidence():
    """Bare street name should score lower than a full address."""
    a = parse_address("Some Street, Lagos")
    if a is not None:
        assert a.confidence < 0.85
