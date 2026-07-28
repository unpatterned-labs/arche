# Copyright 2026 unpatterned.org
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Tests for the strong keyed tokeniser (``arche._tokens``)."""

import pytest

from arche._tokens import canonicalize, strong_token, token


def test_deterministic_same_value_same_key():
    assert token("2348031234567", "phone", "s3cret") == token(
        "2348031234567", "phone", "s3cret"
    )


def test_phone_formatting_variants_collapse():
    # Same number, different formatting -> same token.
    assert token("+234 803 123 4567", "phone", "k") == token(
        "2348031234567", "phone", "k"
    )
    assert token("(234)803-123-4567", "phone", "k") == token(
        "2348031234567", "phone", "k"
    )


def test_id_formatting_variants_collapse():
    assert token("AB-123 456", "id", "k") == token("ab123456", "id", "k")


def test_email_case_and_whitespace_collapse():
    assert token("  User@Example.COM ", "email", "k") == token(
        "user@example.com", "email", "k"
    )


def test_name_diacritics_and_spacing_collapse():
    assert token("Mamadou  Diallo", "name", "k") == token(
        "mamadou diallo", "name", "k"
    )
    # Yoruba tonal diacritics stripped via NFKD.
    assert token("Adébáyò", "name", "k") == token("Adebayo", "name", "k")


def test_different_key_yields_unrelated_token():
    assert token("2348031234567", "phone", "keyA") != token(
        "2348031234567", "phone", "keyB"
    )


def test_empty_key_is_refused():
    # Fail-closed: never emit a guessable token.
    with pytest.raises(ValueError):
        strong_token("x", "")
    with pytest.raises(ValueError):
        strong_token("x", b"")
    with pytest.raises(ValueError):
        token("x", "id", "")


def test_unknown_id_type_is_refused():
    # Fail-closed: never tokenise a raw, un-normalised value by accident.
    with pytest.raises(KeyError):
        canonicalize("x", "passport_nonexistent")
    with pytest.raises(KeyError):
        token("x", "passport_nonexistent", "k")


def test_token_is_256_bit_hex():
    t = strong_token("anything", "k")
    assert len(t) == 64  # 32 bytes -> 64 hex chars
    int(t, 16)  # parses as hex


def test_bytes_key_equivalent_to_str_key():
    assert strong_token("v", "k") == strong_token("v", b"k")


def test_no_trivial_collisions_over_range():
    key = "k"
    values = [f"id{i}" for i in range(2000)]
    tokens = {token(v, "id", key) for v in values}
    assert len(tokens) == len(values)


def test_is_distinct_from_masking_tokenizer():
    # The strong token must NOT equal the 32-bit masking token — different
    # width, different construction. This guards against a caller wiring the
    # weak tokeniser into an exchange/hashed-ID path.
    from arche.policy.engine import _tokenize

    weak = _tokenize("PII-2-NIN", "12345678901", salt="k")
    strong = token("12345678901", "id", "k")
    assert strong != weak
    assert len(strong) == 64
    assert len(weak) < 64
