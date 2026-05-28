# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""The canonical ``ArcheSignedDocument`` envelope for sign-share-extract.

Per the verifiability roadmap locked decisions (2026-06-02): the wire
format is a JWS-wrapped envelope carrying the full ``Pipeline.Result``
plus signed provenance metadata. Party A signs once; Party B verifies
offline against the embedded ``did:key`` and recovers the redacted
text + detection set + policy outcomes without ever seeing the
original document.

Schema (mirrors PRD §10.2 Result, with provenance fields added)::

    {
      "doc_hash":       "<sha256 of original>",
      "redacted_text":  "<post-policy text>",
      "detections":     [<Detection-as-dict>, ...],
      "addresses":      [<Address-as-dict>, ...],
      "policy_outcomes":[<PolicyOutcome-as-dict>, ...],
      "issuer":         "did:key:z6Mk...",
      "issued_at":      "<ISO 8601 UTC>",
      "expires_at":     "<ISO 8601 UTC>" | null,
      "purpose":        "dsar_response" | "kyb_attestation" | ...,
      "jurisdiction":   "NG" | "KE" | "ZA" | "GH" | ...,
      "statute":        "NDPA-2023@v1.0",
      "schema_version": "arche+envelope/v1"
    }

Important non-properties:

- The audit log is intentionally *not* in the signed envelope. Audit
  events are local to the issuer's deployment and may contain
  jurisdiction-sensitive context; signing them invites cross-border
  data-transfer questions. The recipient gets the policy outcomes,
  which is enough to know what was redacted and why.
- The tokenize salt is also not in the envelope. Tokens are
  deterministic to the issuer's deployment; the recipient can match
  identical tokens across signed envelopes from the same issuer but
  cannot reverse them.

Canonical JSON: we use ``json.dumps(..., sort_keys=True,
separators=(",", ":"), ensure_ascii=False)``. This is not full
JCS (RFC 8785) — it doesn't normalize numeric forms like ``1.0`` vs
``1`` — but our schema doesn't carry numbers where representation
matters, so the simpler form is sufficient and avoids a new
dependency.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import datetime, timezone
from typing import Any

ENVELOPE_SCHEMA_VERSION = "arche+envelope/v1"


@dataclass
class ArcheSignedDocument:
    """The canonical payload that gets signed and shared.

    This is the dict-shape under the JWS signature. Instantiate via
    ``from_pipeline_result`` (issuer side) or ``from_dict`` (verifier side).
    """

    doc_hash: str
    redacted_text: str
    detections: list[dict[str, Any]] = field(default_factory=list)
    addresses: list[dict[str, Any]] = field(default_factory=list)
    policy_outcomes: list[dict[str, Any]] = field(default_factory=list)
    issuer: str = ""
    issued_at: str = ""
    expires_at: str | None = None
    purpose: str = ""
    jurisdiction: str | None = None
    statute: str | None = None
    schema_version: str = ENVELOPE_SCHEMA_VERSION

    # -----------------------------------------------------------------------
    # Construction
    # -----------------------------------------------------------------------

    @classmethod
    def from_pipeline_result(
        cls,
        result: Any,
        *,
        issuer_did: str,
        purpose: str = "",
        expires_at: datetime | None = None,
        issued_at: datetime | None = None,
    ) -> "ArcheSignedDocument":
        """Build an envelope from a :class:`arche.workflow.Result`.

        Only the fields that cross trust boundaries are copied — audit
        log entries stay local to the issuer.
        """
        when = issued_at or datetime.now(timezone.utc)
        metadata = getattr(result, "metadata", {}) or {}
        jurisdiction = metadata.get("jurisdiction")
        statute_id = metadata.get("statute_id")
        statute_version = metadata.get("statute_version")
        statute = (
            f"{statute_id}@v{statute_version}"
            if statute_id and statute_version
            else statute_id
        )
        return cls(
            doc_hash=getattr(result, "document_hash", ""),
            redacted_text=getattr(result, "redacted_text", ""),
            detections=[_to_dict(d) for d in getattr(result, "detections", []) or []],
            addresses=[_to_dict(a) for a in getattr(result, "addresses", []) or []],
            policy_outcomes=[_to_dict(o) for o in getattr(result, "policy_outcomes", []) or []],
            issuer=issuer_did,
            issued_at=when.isoformat(),
            expires_at=expires_at.isoformat() if expires_at else None,
            purpose=purpose,
            jurisdiction=jurisdiction,
            statute=statute,
            schema_version=ENVELOPE_SCHEMA_VERSION,
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ArcheSignedDocument":
        """Re-hydrate an envelope from a verified JWS payload."""
        return cls(
            doc_hash=data.get("doc_hash", ""),
            redacted_text=data.get("redacted_text", ""),
            detections=list(data.get("detections", []) or []),
            addresses=list(data.get("addresses", []) or []),
            policy_outcomes=list(data.get("policy_outcomes", []) or []),
            issuer=data.get("issuer", ""),
            issued_at=data.get("issued_at", ""),
            expires_at=data.get("expires_at"),
            purpose=data.get("purpose", ""),
            jurisdiction=data.get("jurisdiction"),
            statute=data.get("statute"),
            schema_version=data.get("schema_version", ENVELOPE_SCHEMA_VERSION),
        )

    # -----------------------------------------------------------------------
    # Serialization
    # -----------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """Convert to a plain dict suitable for JSON encoding."""
        return asdict(self)

    def to_canonical_json(self) -> str:
        """Serialize to the canonical JSON form used for signing.

        Stable across Python versions / dict insertion orders because
        ``sort_keys=True``. The encoded byte sequence is what gets
        signed; the verifier reconstructs it on the other side.
        """
        return json.dumps(
            self.to_dict(),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )

    # -----------------------------------------------------------------------
    # Expiry helpers
    # -----------------------------------------------------------------------

    def is_expired(self, now: datetime | None = None) -> bool:
        """True iff ``expires_at`` is set and earlier than ``now`` (or
        the current UTC time)."""
        if not self.expires_at:
            return False
        when = now or datetime.now(timezone.utc)
        try:
            expiry = datetime.fromisoformat(self.expires_at)
        except ValueError:
            return False
        if expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=timezone.utc)
        return expiry < when


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _to_dict(obj: Any) -> dict[str, Any]:
    """Convert dataclasses or arbitrary objects with ``__dict__`` to dict.

    Detection / PolicyOutcome / Address are all dataclasses; the generic
    branch handles future-shaped records.
    """
    if obj is None:
        return {}
    if isinstance(obj, dict):
        return obj
    if is_dataclass(obj):
        return asdict(obj)
    if hasattr(obj, "__dict__"):
        return {k: v for k, v in vars(obj).items() if not k.startswith("_")}
    raise TypeError(f"Cannot convert {type(obj).__name__} to dict for envelope")


def document_hash(text: str) -> str:
    """Compute the SHA-256 hex digest of a document. Convenience helper."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
