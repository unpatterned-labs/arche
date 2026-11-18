# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Masking tokens are keyed, wide, and never minted unkeyed.

They are not only for display: `Deidentified.record()` links two redacted
copies on token equality. The old construction was ``blake2b(salt + value)``
at 32 bits with an empty default salt, so a tokenised phone number or NIN was
reversible by enumerating the value space, and two people could share a token
at register scale.
"""

from __future__ import annotations

import hashlib

from arche.policy.engine import _tokenize, token_key

_NIN = "12345678901"


def test_tokens_are_128_bit():
    label, digest = _tokenize("PII-2-NIN", _NIN, salt="k").split("_")
    assert label == "NIN"
    assert len(digest) == 32


def test_same_key_same_token_different_key_different_token():
    assert _tokenize("PII-2-NIN", _NIN, salt="k") == _tokenize("PII-2-NIN", _NIN, salt="k")
    assert _tokenize("PII-2-NIN", _NIN, salt="k") != _tokenize("PII-2-NIN", _NIN, salt="j")


def test_no_key_never_means_unkeyed():
    # The attack: hash every candidate value without a key and look the token
    # up. With no salt the token must not equal any unkeyed digest of the value.
    digest = _tokenize("PII-2-NIN", _NIN).split("_")[1]
    for width in (4, 16, 32):
        assert digest != hashlib.blake2b(_NIN.encode(), digest_size=width).hexdigest()
    assert token_key("") != hashlib.sha256(b"").digest()
    # Still consistent within the process, so a document's tokens agree.
    assert _tokenize("PII-2-NIN", _NIN) == _tokenize("PII-2-NIN", _NIN)


def test_the_key_is_a_mac_key_not_a_prefix():
    # `salt + value` let ("ab", "c") and ("a", "bc") collide.
    assert _tokenize("PII-1-NAME", "c", salt="ab") != _tokenize("PII-1-NAME", "bc", salt="a")


def test_the_key_is_never_stored_in_the_ledger(tmp_path):
    from arche.ledger import Ledger
    from arche.protect import deidentify

    ledger = Ledger(str(tmp_path / "l.duckdb"))
    deid = deidentify("Call Ada on 08031234567.", "NG", method="token",
                      salt="very-secret-key", store=ledger)
    call = ledger.decision(deid.decision_id).call
    assert "salt" not in call
    assert "very-secret-key" not in repr(call)
