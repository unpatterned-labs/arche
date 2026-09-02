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


def new_resolution_case_id() -> str:
    """Create an opaque identifier for one unresolved resolution question."""
    return f"case_{uuid4().hex}"


def new_evidence_action_id() -> str:
    """Create an opaque identifier for one policy-permitted evidence action."""
    return f"act_{uuid4().hex}"


def new_ledger_id(prefix: str) -> str:
    """Create an opaque identifier for one immutable ledger record."""
    return f"{prefix}_{uuid4().hex}"


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
    provenance: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class Evidence:
    """Provenance-backed support or refutation derived from an observation."""

    evidence_id: str
    observation_id: str
    kind: str
    supports: str
    provenance: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class DecisionReceipt:
    """The policy-bound outcome of a resolution decision.

    This vNext receipt deliberately coexists with ``arche.resolve.Receipt``.
    Resolver adapters preserve their pinned provenance here without changing
    existing public result shapes.
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
    provenance: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class ResolutionRun:
    """Cost and outcome metrics emitted by one resolver invocation.

    ``unsurfaced_pairs`` means the resolver considered a candidate but emitted
    no decision receipt for it. It is deliberately not a negative identity
    conclusion: missing evidence is not refuting evidence.
    """

    run_id: str
    resolver: str
    created_at: datetime
    candidate_pairs: int
    emitted_decisions: int
    match_count: int
    review_count: int
    unsurfaced_pairs: int
    provenance: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class EvidenceGap:
    """A deterministic statement of evidence needed to resolve a case."""

    field: str
    reason: str
    candidate_entity_ids: tuple[str, ...] = ()
    priority: int = 0
    permitted_action_types: tuple[str, ...] = ()


@dataclass(frozen=True)
class ResolutionCase:
    """An unresolved identity question that needs bounded additional evidence."""

    case_id: str
    question: str
    observation_ids: tuple[str, ...]
    candidate_entity_ids: tuple[str, ...]
    opened_at: datetime
    status: str = "open"
    uncertainty: Mapping[str, object] = field(default_factory=dict)
    evidence_gaps: tuple[EvidenceGap, ...] = ()


@dataclass(frozen=True)
class EvidenceAction:
    """A policy-permitted request for evidence, not a tool invocation itself."""

    action_id: str
    case_id: str
    action_type: str
    source_id: str
    permitted_at: datetime
    policy_pin: str
    max_cost: float | None = None
    provenance: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class ActionObservation:
    """The immutable Observation produced by one permitted evidence action."""

    action_id: str
    observation_id: str
    recorded_at: datetime


@dataclass(frozen=True)
class ToolCapability:
    """A read-only source capability available to a permitted evidence action."""

    source_id: str
    action_types: tuple[str, ...]
    policy_pin: str
    read_only: bool = True

    def permits(self, action: EvidenceAction) -> bool:
        """Return whether this capability can execute the policy permission."""
        return (
            self.read_only
            and self.source_id == action.source_id
            and self.policy_pin == action.policy_pin
            and action.action_type in self.action_types
        )


@dataclass(frozen=True)
class Claim:
    """A revisable belief about an entity, backed by immutable Evidence IDs."""

    claim_id: str
    entity_id: str
    predicate: str
    value_ref: str
    evidence_ids: tuple[str, ...]
    asserted_at: datetime
    status: str = "active"
    provenance: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class Contradiction:
    """An unresolved incompatibility between claims about one entity."""

    contradiction_id: str
    entity_id: str
    claim_ids: tuple[str, ...]
    reason: str
    detected_at: datetime
    status: str = "open"


@dataclass(frozen=True)
class EntityRelation:
    """An evidence-backed relationship between two stable entities."""

    relation_id: str
    subject_entity_id: str
    predicate: str
    object_entity_id: str
    evidence_ids: tuple[str, ...]
    asserted_at: datetime
    status: str = "active"


@dataclass(frozen=True)
class OpenQuestion:
    """A material unknown that remains open for one entity."""

    question_id: str
    entity_id: str
    question: str
    opened_at: datetime
    case_id: str | None = None
    status: str = "open"


@dataclass(frozen=True)
class CaseEvent:
    """An immutable event in the history of one ResolutionCase."""

    event_id: str
    case_id: str
    event_type: str
    recorded_at: datetime
    references: tuple[str, ...] = ()
    provenance: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class DocumentClaimSpec:
    """A reviewed mapping from one document field to a proposed entity claim."""

    entity_id: str
    predicate: str
    field: str


@dataclass(frozen=True)
class DocumentRelationSpec:
    """A reviewed mapping from document fields to a proposed entity relationship."""

    subject_entity_id: str
    predicate: str
    object_entity_id: str
    evidence_fields: tuple[str, ...]


@dataclass(frozen=True)
class ClaimProposal:
    """A review-pending claim proposal that has not entered entity memory."""

    proposal_id: str
    case_id: str
    entity_id: str
    predicate: str
    value_ref: str
    evidence_ids: tuple[str, ...]
    proposed_at: datetime
    review_id: str


@dataclass(frozen=True)
class RelationProposal:
    """A review-pending relation proposal that has not entered entity memory."""

    proposal_id: str
    case_id: str
    subject_entity_id: str
    predicate: str
    object_entity_id: str
    evidence_ids: tuple[str, ...]
    proposed_at: datetime
    review_id: str


@dataclass(frozen=True)
class ProposalAcceptancePolicy:
    """Deterministic requirements for promoting a reviewed case proposal."""

    policy_id: str
    min_independent_sources: int = 2

    def __post_init__(self) -> None:
        if not self.policy_id:
            raise ValueError("proposal acceptance policy needs a policy_id")
        if self.min_independent_sources < 1:
            raise ValueError("min_independent_sources must be at least one")


@dataclass(frozen=True)
class ProposalAcceptance:
    """The auditable accept-or-review result for one reviewed proposal."""

    proposal_id: str
    case_id: str
    decision: str
    reason: str
    evidence_ids: tuple[str, ...]
    independent_source_ids: tuple[str, ...]
    accepted_record_id: str | None = None
    conflicting_record_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class EntityMemory:
    """The compact current ledger view for one stable entity."""

    entity: Entity
    claims: tuple[Claim, ...]
    contradictions: tuple[Contradiction, ...]
    relations: tuple[EntityRelation, ...]
    open_questions: tuple[OpenQuestion, ...]
