# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""The vNext runtime entry point and durable domain contracts."""

from __future__ import annotations

from ._adapters import adapt_coreference_receipt, adapt_reconcile_result
from ._cases import what_would_resolve
from ._connectors import EvidenceConnector
from ._document_observations import observation_from_document
from ._document_proposals import (
    DocumentProposalSet,
    reviewed_document_evidence,
    reviewed_document_proposals,
)
from ._models import (
    ActionObservation,
    CaseEvent,
    Claim,
    ClaimProposal,
    Contradiction,
    DecisionReceipt,
    DocumentClaimSpec,
    DocumentRelationSpec,
    Entity,
    EntityMemory,
    EntityRelation,
    Evidence,
    EvidenceAction,
    EvidenceGap,
    Observation,
    OpenQuestion,
    PolicyDecision,
    ProposalAcceptance,
    ProposalAcceptancePolicy,
    RelationProposal,
    ResolutionCase,
    ResolutionDecisionPolicy,
    ResolutionRun,
    ToolCapability,
    new_entity_id,
    new_evidence_action_id,
    new_ledger_id,
    new_resolution_case_id,
)
from ._planning import (
    CaseAssessment,
    DeterministicResolutionPlanner,
    EvidencePlan,
    PlannedEvidenceAction,
    ResolutionBudget,
)
from .engine import ArcheEngine, attach

__all__ = [
    "ArcheEngine",
    "ActionObservation",
    "CaseEvent",
    "CaseAssessment",
    "Claim",
    "ClaimProposal",
    "Contradiction",
    "DecisionReceipt",
    "DeterministicResolutionPlanner",
    "DocumentClaimSpec",
    "DocumentProposalSet",
    "DocumentRelationSpec",
    "EvidenceAction",
    "Entity",
    "EntityMemory",
    "EntityRelation",
    "EvidenceConnector",
    "EvidenceGap",
    "EvidencePlan",
    "Evidence",
    "Observation",
    "OpenQuestion",
    "PolicyDecision",
    "ProposalAcceptance",
    "ProposalAcceptancePolicy",
    "ResolutionCase",
    "ResolutionDecisionPolicy",
    "ResolutionBudget",
    "ResolutionRun",
    "RelationProposal",
    "ToolCapability",
    "PlannedEvidenceAction",
    "attach",
    "adapt_coreference_receipt",
    "adapt_reconcile_result",
    "new_evidence_action_id",
    "new_entity_id",
    "new_ledger_id",
    "new_resolution_case_id",
    "observation_from_document",
    "reviewed_document_evidence",
    "reviewed_document_proposals",
    "what_would_resolve",
]
