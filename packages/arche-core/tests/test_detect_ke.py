# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Kenyan identifier detection.

Huduma Namba was listed in the README as a detected government ID while no
pattern for it existed, so its numbers were matched by the NHIF pattern and
reported as ``PII-2-NHIF``. These tests pin the corrected behaviour and, just
as importantly, pin what it must NOT do: claim a bare number as a Huduma
Namba, which would invert the bug rather than fix it.
"""

from __future__ import annotations
# ── Huduma Namba (NIIMS) ─────────────────────────────────────────────────────
#
# The README listed Huduma under detected government IDs while no pattern
# existed, so a Huduma number was matched by the NHIF pattern and reported as
# PII-2-NHIF — mislabelled, not merely missed. Detection is cue-anchored on
# purpose: a Huduma Namba has no check digit and shares its length range with
# NHIF and the National ID, so a bare number carries no evidence of which it is.


class TestHudumaNamba:
    def _cats(self, text):
        from arche import Pipeline
        return [(d.category, d.text) for d in Pipeline(jurisdiction="KE").process(text).detections]

    def test_cue_anchored_number_is_huduma_not_nhif(self):
        assert ("PII-2-HUDUMA", "12345678") in self._cats("Huduma number 12345678")

    def test_accepts_namba_colon_and_twelve_digits(self):
        assert ("PII-2-HUDUMA", "987654321012") in self._cats("Huduma Namba: 987654321012")

    def test_case_insensitive_and_abbreviated_cue(self):
        assert ("PII-2-HUDUMA", "11223344") in self._cats("huduma no. 11223344")

    def test_bare_number_is_not_claimed_as_huduma(self):
        # The whole point of anchoring. Without the cue there is no evidence,
        # and inventing HUDUMA here would just invert the original bug.
        cats = self._cats("Reference 12345678 with no cue")
        assert all(c != "PII-2-HUDUMA" for c, _ in cats)

    def test_nhif_still_detected_when_it_is_the_one_present(self):
        assert ("PII-2-NHIF", "123456789") in self._cats("NHIF 123456789 only")

    def test_word_boundary_guards_the_cue(self):
        cats = self._cats("My shuduma 12345678")
        assert all(c != "PII-2-HUDUMA" for c, _ in cats)

    def test_both_ids_in_one_string_keep_their_own_categories(self):
        cats = self._cats("Huduma number 12345678 and NHIF 123456789")
        assert ("PII-2-HUDUMA", "12345678") in cats
        assert ("PII-2-NHIF", "123456789") in cats

    def test_statute_maps_huduma_to_mask_at_high_tier(self):
        from arche import Pipeline
        result = Pipeline(jurisdiction="KE").process("Huduma number 12345678")
        outcome = next(o for o in result.policy_outcomes if o.category == "PII-2-HUDUMA")
        assert outcome.action == "mask"
        assert "Huduma" in outcome.statute_reference

    def test_huduma_is_a_foundational_identifier(self):
        from arche import Pipeline
        det = next(
            d for d in Pipeline(jurisdiction="KE").process("Huduma number 12345678").detections
            if d.category == "PII-2-HUDUMA"
        )
        assert det.identity_class == "foundational"

    def test_pan_african_fallback_also_recognises_the_cue(self):
        # No jurisdiction configured: the _africa pattern set must agree with
        # the Kenya-specific one rather than diverging.
        from arche.detect._africa.ids import detect_african_ids
        found = detect_african_ids("Huduma number 12345678")
        assert any(x.id_type == "HUDUMA" for x in found)
