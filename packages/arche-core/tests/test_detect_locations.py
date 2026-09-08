# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""The gazetteer location detector, and the word it mistook for a city."""

from __future__ import annotations

from arche.detect.locations import detect_locations


def test_next_of_kin_is_not_kinshasa():
    # Found by the detection benchmark: "Next of kin" matched the alias "Kin"
    # 32 times in 240 texts. A three-letter lowercase word is a word.
    assert not [d for d in detect_locations("Next of kin on 0803 555 7890.")
                if d.text.lower() == "kin"]


def test_a_capitalised_place_is_still_found():
    found = {d.text for d in detect_locations("Seen at the clinic in Kano on Monday.")}
    assert "Kano" in found


def test_a_long_lowercase_place_is_still_found():
    # Chat text rarely capitalises; "lagos" is not an ordinary English word.
    found = {d.text for d in detect_locations("pls send it to lagos by friday")}
    assert "lagos" in found


def test_a_short_lowercase_place_is_not_guessed():
    assert not [d for d in detect_locations("kano") if d.text == "kano"]
