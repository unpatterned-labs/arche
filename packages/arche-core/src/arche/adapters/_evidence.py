# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""The evidence object every adapter returns.

Deliberately not a decision. A provider observed something at a moment in time
under a licence; that is all this records. What it means for a merge is arche's
business, and the gate's.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Literal

__all__ = ["LICENCE_CLASSES", "OPEN_LICENCE_CLASSES", "ProviderEvidence", "Verdict"]

#: Verdicts an adapter may return. Note what is absent: ``match`` and
#: ``different``. A geocoder is not entitled to an opinion about identity — it
#: can only agree or disagree with a claim about where something is.
Verdict = Literal["corroborates", "contradicts", "inconclusive"]

#: Licence classes an adapter may declare, loosest constraint first.
LICENCE_CLASSES = (
    "cc0",
    "odbl-attribution",
    "cc-by",
    "gers",
    "user-owned",
    "proprietary",
    "unknown",
)

#: Classes whose data may be ingested into arche's own packs. Everything else
#: is usable as evidence for a single decision and must never be retained into
#: a pack, a frequency table, or a benchmark row — that is the provenance
#: firewall, and it is what keeps the crown-jewel assets unencumbered.
OPEN_LICENCE_CLASSES = frozenset({"cc0", "gers", "user-owned"})


@dataclass(frozen=True)
class ProviderEvidence:
    """One witnessed observation from an external provider.

    Attributes
    ----------
    provider:
        Stable provider identity, e.g. ``"nominatim"``.
    query:
        The canonical query sent. Pinned so the observation can be re-made,
        even though it cannot be replayed.
    verdict:
        ``corroborates`` / ``contradicts`` / ``inconclusive``. Never a merge
        decision — see :data:`Verdict`.
    retrieved_at:
        ISO-8601 UTC timestamp supplied by the caller. Adapters do not read the
        clock themselves, so a cached or recorded response replays identically.
    licence:
        One of :data:`LICENCE_CLASSES`. Checked before anything is retained.
    response_sha256:
        Hash of the canonicalised provider response. arche stores nothing; the
        caller keeps the payload that hashes true, and the attestation pins
        this digest.
    candidates:
        Provider results in canonical form. Advisory, never authoritative.
    detail:
        Adapter-specific measurements — for a geocoder, the distance between
        the claimed and observed positions.
    """

    provider: str
    query: str
    verdict: Verdict
    retrieved_at: str
    licence: str
    response_sha256: str
    candidates: tuple[dict[str, Any], ...] = ()
    detail: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.licence not in LICENCE_CLASSES:
            raise ValueError(
                f"unknown licence class {self.licence!r}; "
                f"expected one of {list(LICENCE_CLASSES)}. A licence class is "
                "not optional — it is what the provenance firewall checks."
            )

    @property
    def may_enter_packs(self) -> bool:
        """Whether this evidence's licence permits ingestion into arche packs.

        False for everything except the open classes. Read this before
        retaining an adapter response anywhere durable.
        """
        return self.licence in OPEN_LICENCE_CLASSES

    def pin(self) -> dict[str, Any]:
        """The provenance pin for an attestation.

        A decision resting on this evidence is *witnessed*, not reproducible:
        re-running it tomorrow re-asks a live service. The pin records exactly
        what was asked, of whom, when, under what licence, and what came back —
        so a verifier holding the payload can confirm the derivation even
        though they cannot re-derive the observation.
        """
        return {
            "provider": self.provider,
            "query": self.query,
            "retrieved_at": self.retrieved_at,
            "licence": self.licence,
            "response_sha256": self.response_sha256,
            "verdict": self.verdict,
            "reproducible": False,
        }


def canonical_response_hash(payload: Any) -> str:
    """SHA-256 over a canonicalised provider response.

    Sorted keys and compact separators, so two structurally identical
    responses hash identically regardless of how the provider ordered them.
    """
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()
