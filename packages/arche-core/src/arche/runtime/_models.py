# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Small, durable contracts for the vNext runtime foundation."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from uuid import uuid4


def new_entity_id() -> str:
    """Create an opaque, source-independent entity identifier."""
    return f"ent_{uuid4().hex}"


@dataclass(frozen=True)
class Entity:
    """A stable real-world identity, separate from revisable claims."""

    entity_id: str
    entity_type: str
    identity_unit: str
    created_at: datetime
    status: str = "active"


@dataclass(frozen=True)
class Observation:
    """An immutable record of information supplied to the runtime."""

    observation_id: str
    source_id: str
    source_record_id: str | None
    recorded_at: datetime
    content_hash: str


@dataclass(frozen=True)
class Evidence:
    """Provenance-backed support or refutation derived from an observation."""

    evidence_id: str
    observation_id: str
    kind: str
    supports: str
    provenance: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class DecisionReceipt:
    """The policy-bound outcome of a resolution decision.

    This vNext receipt deliberately coexists with ``arche.resolve.Receipt``.
    A later adapter will translate current resolver results without changing the
    existing public result shape.
    """

    decision_id: str
    identity_result: str
    action: str
    evidence_ids: tuple[str, ...]
    created_at: datetime
    raw_score: float | None = None
    probability: float | None = None
    policy_pin: str | None = None
    schema_pin: str | None = None
