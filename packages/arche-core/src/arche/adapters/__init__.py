# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Provider adapters — external evidence, never external decisions.

An adapter asks a third party a question and brings back a *witnessed
observation*. It does not resolve, score, or merge. Four rules hold for every
adapter in this package, and they are the reason the package can exist at all
without compromising the rest of arche:

1. **Providers fetch references; arche resolves.** An adapter returns
   :class:`ProviderEvidence` — candidates in canonical form plus provenance.
   No adapter returns a verdict, and nothing an adapter says auto-merges.

2. **Adapter output is evidence with a measured reliability.** It enters the
   same gate as everything else. A provider that corroborates a merge does not
   thereby authorise it; a provider that contradicts one routes it to review.

3. **Every adapter is an egress destination.** Sending a facility name or a
   citizen's address to a geocoder *is* a cross-border transfer. Adapters
   route through :class:`arche.guard.EgressGuard`, and the statute pack decides
   whether a reference may be sent at all.

4. **The provenance firewall.** Provider responses never feed the data packs,
   the frequency tables, or the benchmark. The moment they do, those assets
   inherit the most restrictive licence in the chain. Every evidence object
   carries a ``licence`` and pack ingestion accepts open classes only.

The signing consequence: a decision that depends on a live API response cannot
be world-replayed, so the attestation pins the canonical query, the provider
identity, the retrieval timestamp, and a hash of the canonicalised response.
The *caller* retains the payload that hashes true — arche stores nothing.
"""

from __future__ import annotations

from arche.adapters._evidence import (
    LICENCE_CLASSES,
    OPEN_LICENCE_CLASSES,
    ProviderEvidence,
    Verdict,
)

__all__ = [
    "LICENCE_CLASSES",
    "OPEN_LICENCE_CLASSES",
    "ProviderEvidence",
    "Verdict",
]


def __getattr__(name: str):  # lazy: no adapter imports httpx until it is used
    if name in ("verify_place", "NominatimError", "NOMINATIM_LICENCE"):
        from arche.adapters import nominatim

        return getattr(nominatim, name)
    raise AttributeError(f"module 'arche.adapters' has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted({*__all__, "nominatim", "verify_place", "NominatimError"})
