# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Identifiers for a synthetic world, and the one rule they must obey.

**A record id must not let a matcher recover the entity it belongs to.** That
sounds obvious and it is the easiest invariant in this whole package to break:
write ``obs:erp:org_991:1`` and the truth is derivable from the input by
string manipulation, so every score on the benchmark is meaningless and
nothing about the file says so. The v0.2 PRD's own examples (``syn:org:88``,
``obs:erp:991``) have this shape.

So a ``record_id`` is a hash over the world id, the source, and a counter --
**nothing about the entity goes into the payload**, which makes the id opaque
by construction rather than by hoping the hash holds. Truth-side ids
(``entity_id``, ``event_id``) may be readable, because they only ever appear
in files a matcher must not be given.

Deliberately self-contained: no ``arche`` import, no dependency beyond the
standard library, so this package can move to its own repository unchanged.
The id shape mirrors arche's (``prefix:sha256:hex``) so the two are legible
side by side, but nothing here requires arche to be installed.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

#: Hex characters kept from the digest. 16 gives a 64-bit space -- at the
#: scale this generator works in (10^4-10^6 records) a collision is far below
#: the probability of a bug elsewhere, and short ids keep the Parquet small
#: and a debugging session readable.
_WIDTH = 16


def _digest(payload: Any) -> str:
    """sha256 over canonical JSON: sorted keys, compact, no whitespace drift."""
    text = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def record_id(world_id: str, source: str, sequence: int) -> str:
    """An opaque id for one observation.

    The payload is ``(world_id, source, sequence)`` and nothing else. No entity
    id, no attribute, no timestamp that correlates with one -- there is nothing
    in here for a matcher to invert, because the entity was never in the input.
    """
    return "rec_" + _digest([world_id, source, sequence])[:_WIDTH]


def entity_id(world_id: str, entity_type: str, sequence: int) -> str:
    """A truth-side entity id. Readable on purpose: it never leaves the truth files."""
    return f"syn:{entity_type}:{sequence:06d}"


def event_id(world_id: str, sequence: int) -> str:
    """A truth-side event id, referenced by `differences.parquet`."""
    return f"evt:{sequence:06d}"


def difference_id(observation_a: str, observation_b: str, attribute: str, kind: str) -> str:
    """Stable id for one labelled difference, so a report can be diffed run to run."""
    return "dif_" + _digest([observation_a, observation_b, attribute, kind])[:_WIDTH]


def content_fingerprint(rows: list[dict[str, Any]]) -> str:
    """A digest over a table's logical content, order-independent.

    Reproducibility is asserted against this rather than against the bytes of a
    Parquet file: Parquet embeds a writer version and its own metadata, so two
    byte-different files can hold identical data and a byte comparison would
    fail for a reason that has nothing to do with the generator.
    """
    return _digest(sorted(json.dumps(r, sort_keys=True, default=str) for r in rows))


__all__ = ["content_fingerprint", "difference_id", "entity_id", "event_id", "record_id"]
