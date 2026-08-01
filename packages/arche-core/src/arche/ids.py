# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Content-addressed identifiers for arche resolution decisions.

Every id is a *pure function* of its inputs, so a decision re-runs to the same bytes:

* **Canonical JSON** — ``sort_keys=True``, compact separators, and **no raw
  floats**: every float is rendered as a fixed 4-decimal string, so hashing is
  reproducible across machines and float-repr quirks never leak in.
* **NFKD-normalised strings** via :func:`arche.resolve._matcher._normalise_text`
  (the same normaliser the matcher compares with).
* **No timestamps** in the reproducible core (``decision_id`` / ``reference_id``).
  These are HMAC-**keyed** with the issuer key when derived from PII and shared
  (so a low-entropy identifier can't be brute-forced back); keyless only for
  local, non-shared use. ``document_content_id`` is a keyless hash of the whole
  document.

The one keyed id is :func:`entity_id` — an HMAC pseudonym (C3): PII-safe (a bare
hash of an 11-digit national id is brute-forceable), stable *per issuer*, and not
cross-issuer-linkable. It lives in its own claim, never inside ``decision_id``.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from base64 import urlsafe_b64encode
from typing import TYPE_CHECKING, Any

from arche.resolve._matcher import _normalise_id, _normalise_text

if TYPE_CHECKING:
    from arche.canonical import Reference

# Distinctive exact identifiers, in binding priority (strongest first). A shared
# value on one of these mints a deterministic Tier-1 entity_id.
_BINDING_PRIORITY: tuple[str, ...] = (
    "national_id", "nin", "bvn", "ghana_card", "kenya_id", "sa_id",
    "passport", "passport_number", "phone", "phone_number", "email",
)
# Identifier types normalised as free text (case-fold) rather than alnum-strip.
_TEXT_NORMALISED = frozenset({"email"})
# Alias id-types onto one family so the SAME real id labelled two ways
# ("national_id" vs "nin") mints the SAME entity_id and links (M1).
_ID_FAMILY = {
    "nin": "national_id", "national_id": "national_id",
    "phone_number": "phone", "phone": "phone",
    "passport_number": "passport", "passport": "passport",
}
# Minimum issuer-key length (bytes). A short key lets an attacker who guesses it
# brute-force a low-entropy identifier through the HMAC (M1).
_MIN_KEY_LEN = 32


def _id_family(id_type: str) -> str:
    return _ID_FAMILY.get(id_type, id_type)


# ── canonicalization (the reproducibility contract) ──────────────────────────
def _canonicalize(obj: Any) -> Any:
    """Recursively render a payload hashable-reproducibly.

    Floats become fixed 4-decimal strings (``0.4170``) so no raw float — with its
    platform-dependent repr — ever enters a hash. Ints/str/bool/None pass through;
    dicts/lists recurse. (bool is checked before int: ``isinstance(True, int)``.)
    """
    if isinstance(obj, bool) or obj is None:
        return obj
    if isinstance(obj, float):
        return f"{obj:.4f}"
    if isinstance(obj, int):
        return obj
    if isinstance(obj, str):
        return obj
    if isinstance(obj, dict):
        return {str(k): _canonicalize(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_canonicalize(v) for v in obj]
    raise TypeError(f"non-canonicalizable value of type {type(obj).__name__!r}")


def canonical_json(obj: Any) -> str:
    """Deterministic JSON: sorted keys, compact, floats as fixed 4dp strings."""
    return json.dumps(
        _canonicalize(obj), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )


def _sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _keyed_hex(text: str, key: bytes | None) -> str:
    """HMAC-SHA256 when a key is given (PII-safe over low-entropy inputs), else
    a plain sha256 (keyless, publicly recomputable — see :func:`content_hash`)."""
    data = text.encode("utf-8")
    if key:
        return hmac.new(key, data, hashlib.sha256).hexdigest()
    return hashlib.sha256(data).hexdigest()


def content_hash(payload: Any, *, prefix: str, key: bytes | None = None) -> str:
    """``{prefix}:{alg}:{hex}`` over the canonical JSON of ``payload``.

    With ``key`` the digest is HMAC-SHA256 (``alg="hmac-sha256"``) — required
    whenever the id is derived from PII and will be shared, because a bare hash
    of a low-entropy identifier (an 11-digit NIN) is brute-forceable. Keyless
    (``alg="sha256"``) is publicly recomputable and must be treated as
    pseudonymous personal data, not "PII-free".
    """
    alg = "hmac-sha256" if key else "sha256"
    return f"{prefix}:{alg}:{_keyed_hex(canonical_json(payload), key)}"


# ── the ids ──────────────────────────────────────────────────────────────────
def document_content_id(text: str) -> str:
    """Content-address a source document by the sha256 of its raw UTF-8 bytes."""
    return "doc:sha256:" + _sha256_hex(text)


def _reference_attributes(ref: Reference) -> dict[str, str]:
    """Normalised ``{attribute_name: value}`` over a reference's attributes."""
    out: dict[str, str] = {}
    for attr in ref.attributes:
        if attr.value:
            out[attr.name] = _normalise_text(attr.value)
    return out


def reference_id(ref: Reference, *, key: bytes | None = None) -> str:
    """Content-address one extracted record (differs across documents).

    Pass the issuer ``key`` for any reference that enters a shareable
    attestation: the record's attributes are PII, so a keyless hash is a
    brute-forceable re-identification oracle over low-entropy identifiers.
    """
    payload = {
        "attributes": _reference_attributes(ref),
        "source_system": ref.source_system or "",
    }
    return content_hash(payload, prefix="ref", key=key)


def identity_binding_key(ref: Reference) -> tuple[str, str] | None:
    """The highest-priority shared-able exact identifier, normalised — or ``None``.

    Returns ``(id_type, normalized_value)``; drives the Tier-1 ``entity_id`` and
    tells the orchestrator whether a *distinctive* signal is even available.
    """
    have = {a.name: a.value for a in ref.attributes if a.value}
    for name in _BINDING_PRIORITY:
        raw = have.get(name)
        if not raw:
            continue
        norm = _normalise_text(raw) if name in _TEXT_NORMALISED else _normalise_id(raw)
        if norm:
            # Return the id FAMILY, not the raw attribute name, so "national_id"
            # and "nin" bind identically (link the same person; M1).
            return (_id_family(name), norm)
    return None


def entity_id(binding: tuple[str, str], *, key: bytes) -> str:
    """A **keyed** HMAC pseudonym for a Tier-1 entity (C3).

    ``key`` is the issuer's secret (injected by the platform; the SDK stays
    keyless). Same issuer + same identifier -> same id (issuer-stable correlation
    = "same identity across documents"); a different issuer's key yields an
    unlinkable id. Never call this without a distinctive exact identifier
    (:func:`identity_binding_key`); fuzzy-only matches carry no ``entity_id``.
    """
    if not key or len(key) < _MIN_KEY_LEN:
        raise ValueError(
            f"entity_id requires an issuer key of >= {_MIN_KEY_LEN} bytes "
            "(a short key lets an attacker brute-force the identifier)"
        )
    id_type, value = binding
    msg = canonical_json({"id_type": _id_family(id_type), "value": value}).encode("utf-8")
    digest = hmac.new(key, msg, hashlib.sha256).digest()
    return "ent:hmac:" + urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def decision_id(
    *,
    reference_id_a: str,
    reference_id_b: str,
    decision: str,
    factors: dict[str, float],
    gate: dict[str, Any],
    vetoes: dict[str, Any],
    jurisdiction: str,
    pins: dict[str, Any],
    key: bytes | None = None,
) -> str:
    """The reproducible address of a co-reference decision.

    A pure function of the (rounded) evidence and the pinned versions
    (``pins`` = engine / comparator_lib / priors / lexicon / tf / thresholds) —
    no timestamp, no raw float. Order of the two references is meaningful
    (``a`` = first document, ``b`` = second).

    Pass the issuer ``key`` for a shareable decision: it composes ids that are
    themselves keyed, so the reproducibility becomes *per-issuer* (the key-holder
    recomputes; third parties trust the signature) rather than a keyless hash an
    attacker could brute-force back to the source records.
    """
    payload = {
        "reference_id_a": reference_id_a,
        "reference_id_b": reference_id_b,
        "decision": decision,
        "factors": factors,
        "gate": gate,
        "vetoes": vetoes,
        "jurisdiction": jurisdiction,
        "pins": pins,
    }
    return content_hash(payload, prefix="dec", key=key)


__all__ = [
    "canonical_json",
    "content_hash",
    "document_content_id",
    "reference_id",
    "identity_binding_key",
    "entity_id",
    "decision_id",
]
