# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""The memoised hot paths: same answers, and no cached object a caller can poison."""
from __future__ import annotations

from arche.resolve._matcher import (
    _address_components,
    _compiled_vocab,
    _normalise_text,
    normalize_type_token,
)
from arche.resolve._tokenfreq import _tokens


class TestNormaliseText:
    def test_memoised_result_is_the_same_string_value(self):
        a = _normalise_text("  Élim  PHARMACY ")
        assert a == "elim pharmacy"
        assert _normalise_text("  Élim  PHARMACY ") == a

    def test_format_and_control_codepoints_still_stripped(self):
        assert _normalise_text("Bel​lo") == "bello"


class TestTypeVocab:
    VOCAB = {"primary health centre": "PHC", "phc": "PHC", "dispensary": "DISPENSARY"}

    def test_longest_synonym_wins_and_the_residual_is_normalised(self):
        assert normalize_type_token("Karfi Primary Health Centre", self.VOCAB) == ("PHC", "karfi")
        assert normalize_type_token("Karfi PHC", self.VOCAB) == ("PHC", "karfi")
        assert normalize_type_token("Karfi Clinic", self.VOCAB) == (None, "karfi clinic")

    def test_the_compiled_vocabulary_is_built_once_per_vocab(self):
        items = tuple(self.VOCAB.items())
        assert _compiled_vocab(items) is _compiled_vocab(items)

    def test_a_different_vocab_is_a_different_compilation(self):
        assert normalize_type_token("Karfi Clinic", {"clinic": "CLINIC"}) == ("CLINIC", "karfi")


class TestCachedContainersAreNotShared:
    def test_tokens_returns_a_fresh_list_each_call(self):
        first = _tokens("Bello Freight")
        first.append("poison")
        assert "poison" not in _tokens("Bello Freight")

    def test_address_components_is_read_only_by_convention(self):
        a = _address_components("12 Aminu Kano Crescent, Wuse, Abuja")
        b = _address_components("12 Aminu Kano Crescent, Wuse, Abuja")
        # One object, by design (the cache); nothing in the engine mutates it,
        # and this test is here so that the day something does, it fails loudly.
        assert a is b
