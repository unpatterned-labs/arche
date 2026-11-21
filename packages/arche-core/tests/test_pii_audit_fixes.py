# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Fixes from the PII audit of 20 Nov 2026, each pinned by its failing input.

All values are invented. Each test names the defect it guards.
"""

from __future__ import annotations

import pytest
from arche import deidentify
from arche.detect.financial import card_shape
from arche.detect.za.ids import _validate_sa_id


def _mask(text: str, jurisdiction: str) -> str:
    return deidentify(text, jurisdiction, backend="basic", method="mask").text


class TestNigerianLabelledIds:
    def test_a_nin_that_starts_like_a_mobile_is_still_a_nin_after_its_label(self):
        assert _mask("pls send ur nin 08724385469", "NG") == "pls send ur nin [NIN]"

    def test_spaced_nin_and_bvn(self):
        assert _mask("NIN 4829 173 6451 and BVN 2215 678 9012", "NG") == \
            "NIN [NIN] and BVN [BVN]"

    def test_an_unlabelled_mobile_is_still_a_phone(self):
        assert "[NIN]" not in _mask("Call 08031234567 today", "NG")


class TestIPv6:
    @pytest.mark.parametrize("addr", ["2001:db8:85a3::8a2e:370:7334", "fe80::1:2:3",
                                      "2001:db8::1"])
    def test_compressed_forms(self, addr):
        assert addr not in _mask(f"Server {addr} up", "GB")

    @pytest.mark.parametrize("text", ["a lone :: here", "at 10:30:00 sharp"])
    def test_not_addresses(self, text):
        assert _mask(text, "GB") == text

    def test_a_mac_address_is_a_device_id_not_an_ip(self):
        r = deidentify("MAC 00:1A:2B:3C:4D:5E", "GB", backend="basic")
        assert {s["category"] for s in r.spans()} == {"PII-8-DEVICE_ID"}


class TestSouthAfricanIds:
    def test_impossible_dates_and_citizenship_digits_are_not_ids(self):
        assert not _validate_sa_id("9002305123082")[0]  # 30 February
        assert not _validate_sa_id("8804125123783")[0]  # citizenship digit 7
        ok, meta = _validate_sa_id("8001015009087")
        assert ok and meta["citizenship"] == "citizen"

    def test_a_spaced_sa_id(self):
        assert _mask("ID 800101 5009 087", "ZA") == "ID [NATIONAL_ID]"

    def test_a_sa_id_is_not_also_a_card(self):
        r = deidentify("ID 8001015009087", "ZA", backend="basic")
        assert {s["category"] for s in r.spans()} == {"PII-2-NATIONAL_ID"}

    def test_passport_needs_its_word(self):
        out = _mask("Model A12345678 SKU B87654321; passport no A12345678", "ZA")
        assert out.startswith("Model A12345678 SKU B87654321") and out.endswith("[PASSPORT]")

    def test_an_invoice_number_after_tax_invoice_is_not_a_tax_reference(self):
        assert "INV-0012345678" in _mask("TAX INVOICE INV-0012345678", "ZA")


class TestCards:
    def test_issuer_range_length_and_context(self):
        assert card_shape("4111 1111 1111 1111")
        assert card_shape("378282246310005")  # Amex test number
        assert not card_shape("4000123412341234", "order ")
        assert not card_shape("490154203237518", "IMEI ")  # 15 digits, not 34/37
        assert not card_shape("8001015009087")  # a ZA ID: 13 digits, no card word
        assert card_shape("4222222222222", "card ")  # legacy 13-digit Visa, with its word


class TestPacks:
    def test_baseline_national_id_key_is_the_emitted_category(self):
        from arche.policy.engine import load_statute

        loaded = load_statute("BASELINE")
        rules = getattr(loaded, "policy_mappings", None) or loaded["policy_mappings"]
        assert "PII-2-NATIONAL_ID" in rules and "PII-2-NATIONAL-ID" not in rules

    def test_popia_does_not_call_an_id_number_biometric(self):
        r = deidentify("ID 8001015009087", "ZA", backend="basic")
        assert all("biometric" not in s["citation"] for s in r.spans())

    def test_uk_gdpr_generalises_ip_addresses(self):
        assert deidentify("Login from 192.168.10.44", "GB", backend="basic").text == \
            "Login from 192.168.10.0/24"


class TestMethodNeverOverridesWhatTheStatuteKeeps:
    def test_retained_categories_stay_under_mask(self):
        # NDPA keeps a company number and a city; `method=` changes how a
        # removal is done, not whether.
        assert _mask("Company RC 1234567 in Kano", "NG") == "Company RC 1234567 in Kano"

    def test_removed_categories_still_follow_the_method(self):
        assert "[NIN]" in _mask("NIN 48291736451", "NG")


def test_hipaa_keeps_clinical_content():
    from arche.policy.engine import load_statute

    loaded = load_statute("HIPAA-SAFE-HARBOR")
    rules = getattr(loaded, "policy_mappings", None) or loaded["policy_mappings"]
    rule = rules["PII-6-HEALTH"]
    assert (rule["action"] if isinstance(rule, dict) else rule.action) == "retain"
