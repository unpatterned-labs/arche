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

"""Strong keyed tokeniser for cross-org exchange and deterministic hashed IDs.

This is the *strong* token layer, used by (a) the egress guard, where a PII
span is replaced by a deterministic hashed ID so an agent keeps join/reference
utility without seeing the raw value, and (b) the Entity Data Contract, where
two parties intersect token sets without exchanging raw identifiers.

It is deliberately SEPARATE from ``arche.policy.engine._tokenize``. That one is
a 32-bit blake2b (``digest_size=4``) used only for in-place *masking* — fine
there, unusable here: at 4 bytes, birthday collisions appear around ~65k
distinct values, which would turn a "deterministic ID" into a re-identification
vector and silently corrupt a cross-org join. This module uses a KEYED
blake2b-256 (``digest_size=32``).

Security boundary (full threat model: ``docs/entity-data-contract.md``): the
``key`` is a SHARED SECRET, not a public deployment salt. Two parties who both
hold the key can intersect tokens without revealing raw identifiers, but the
key is the *entire* security boundary — a key-holder can hash a low-entropy
identifier space (e.g. an 11-digit NIN) offline and invert every token. This is
a mutual-trust protocol, NOT zero-knowledge / private set intersection.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable

from arche.resolve._matcher import _normalise_id, _normalise_text

# Digest width in bytes: 32 -> 256-bit -> 64 hex chars. Collision-resistant
# enough to back a deterministic cross-org join (contrast the 4-byte masking
# token in ``policy.engine``).
_DIGEST_SIZE = 32


def _canon_email(value: str) -> str:
    """Case- and whitespace-insensitive email canonicalisation."""
    return value.strip().lower()


def _canon_phone(value: str) -> str:
    """Digits-only canonicalisation.

    Normalises ``+``, spaces, dashes and parentheses so formatting variants of
    the same number tokenise identically. National-vs-international
    normalisation (``0803…`` vs ``234803…``) is intentionally NOT done here —
    it needs a country assumption; callers that need it should pass an
    already-normalised value (see ``resolve._matcher.compare_phones`` for the
    match-time logic).
    """
    return "".join(ch for ch in value if ch.isdigit())


# id_type -> canonicaliser. Reuses the ``resolve._matcher`` normalisation so
# "same identifier, different formatting" yields the same token, which is what
# makes a token intersection meaningful across two independent systems.
CANONICALIZERS: dict[str, Callable[[str], str]] = {
    "id": _normalise_id,        # national IDs, account/reference numbers
    "name": _normalise_text,    # given/family names (lower, de-diacritic)
    "text": _normalise_text,
    "email": _canon_email,
    "phone": _canon_phone,
}


def _coerce_key(key: str | bytes) -> bytes:
    if isinstance(key, str):
        key = key.encode("utf-8")
    if not key:
        raise ValueError(
            "strong_token requires a non-empty key (the shared secret); an "
            "empty key would make every token trivially reproducible by anyone."
        )
    return key


def strong_token(canonical: str, key: str | bytes) -> str:
    """Return a deterministic, keyed 256-bit token for an already-canonical value.

    Same ``canonical`` + same ``key`` -> same token; a different key -> an
    unrelated token. Fail-closed: an empty ``key`` raises ``ValueError`` rather
    than emit a guessable token. The value is hashed exactly as given, so pass a
    canonicalised value (see :func:`canonicalize` / :func:`token`).
    """
    key_bytes = _coerce_key(key)
    return hashlib.blake2b(
        canonical.encode("utf-8"), key=key_bytes, digest_size=_DIGEST_SIZE
    ).hexdigest()


def canonicalize(value: str, id_type: str) -> str:
    """Canonicalise ``value`` for ``id_type`` so formatting variants collapse.

    Fail-closed: an unknown ``id_type`` raises ``KeyError`` so a caller can
    never accidentally tokenise a raw, un-normalised value (which would silently
    break cross-system joins).
    """
    try:
        canon = CANONICALIZERS[id_type]
    except KeyError:
        raise KeyError(
            f"no canonicaliser registered for id_type {id_type!r}; "
            f"known types: {sorted(CANONICALIZERS)}"
        ) from None
    return canon(value)


def token(value: str, id_type: str, key: str | bytes) -> str:
    """Canonicalise ``value`` for ``id_type``, then return its strong keyed token."""
    return strong_token(canonicalize(value, id_type), key)
