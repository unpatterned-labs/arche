# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Name coverage, whole-span masking and context false positives (audit items 4, 12)."""

from __future__ import annotations

import pytest
from arche.detect.names import detect_names, person_spans


def _names(text: str) -> list[str]:
    return [d.text for d in detect_names(text)]


def _covered(text: str, value: str) -> bool:
    """Every letter of ``value`` lies inside some name detection."""
    start = text.index(value)
    spans = [(d.start, d.end) for d in detect_names(text)]
    return all(any(s <= i < e for s, e in spans)
               for i in range(start, start + len(value)) if text[i].isalnum())


class TestCoverage:
    @pytest.mark.parametrize("name", [
        "Annelie Botha", "Johan du Plessis", "Sipho Mokoena", "Thabo Khumalo",
        "Robert Kowalski", "Carlos Mendez", "Marcus O'Neill",
    ])
    def test_south_african_and_anglo_names(self, name):
        text = f"Seen today: {name}, file 12."
        assert _covered(text, name), _names(text)


class TestWholeSpans:
    def test_all_caps_hyphenated_name_masks_whole(self):
        text = "KYC: MARY-JANE FOTHERINGHAM-SMYTHE, NINO QQ 12 34 56 C"
        assert _names(text)[:2] == ["MARY-JANE", "FOTHERINGHAM-SMYTHE"]

    def test_particles_join_the_name(self):
        text = "Discharge: Pieter van der Merwe, admitted"
        assert _names(text) == ["Pieter", "van", "der", "Merwe"]
        assert person_spans(text) == [(11, 31, "Pieter van der Merwe")]

    def test_arabic_prefix_and_igbo_suffix(self):
        assert _covered("Customer Abdullahi Ibrahim Al-Amin (NI", "Abdullahi Ibrahim Al-Amin")
        assert _covered("Customer ngozi okafor-eze NIN 4829", "ngozi okafor-eze")

    def test_lowercase_only_after_a_cue(self):
        assert _covered("pt tom hargreaves (nhs 4010232137)", "tom hargreaves")
        assert _names("patient presented with fever") == []
        assert _names("we will hope it lands and tom said") == []

    def test_weak_word_counts_beside_another_name(self):
        assert _names("Next of kin Will Bishop 07700 900461") == ["Will", "Bishop"]

    def test_sentence_start_word_is_not_taken(self):
        assert _names("Reach Amina Wanjiru on +254") == ["Amina", "Wanjiru"]


class TestFalsePositives:
    @pytest.mark.parametrize("text", [
        "Husband +234 812 345 6789",
        "TAX INVOICE INV-0012345678",
        "Admitted to Mass General, Boston, MA 02139.",
        "Bill to: 4 Mill Lane",
        "State of origin: Ogun.",
        "Seen at St James's Hospital.",
        "meeting is at Rose Hill station.",
        "Lives at 12 Ahmadu Bello Way, Kaduna.",
        "attended with Parkinson's tremor, Addison's ruled out",
        "Certified AWS SAA-C03.",
        "Dx: type 2 diabetes. Religion: Methodist. See https://portal.example.com/x.",
        "Please call. Note: ok. Thanks, Call me. Patient notes attached.",
        "May I introduce Will? We met on Monday in June.",
    ])
    def test_not_a_name(self, text):
        assert _names(text) == []
