# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Canonical-store boundary for the vNext runtime."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol

from arche.runtime._models import (
    ActionObservation,
    CaseEvent,
    Claim,
    Contradiction,
    DecisionReceipt,
    Entity,
    EntityRelation,
    Evidence,
    EvidenceAction,
    Observation,
    OpenQuestion,
    ResolutionCase,
    ResolutionRun,
)


class ArcheStore(Protocol):
    """Persistence required by the vNext runtime foundation."""

    def ensure_schema(self) -> None:
        """Create the store schema if it does not already exist."""

    def write_entities(self, entities: Iterable[Entity]) -> None:
        """Persist stable entities without deriving their identifiers."""

    def get_entity(self, entity_id: str) -> Entity | None:
        """Load one stable entity by opaque identifier."""

    def write_observations(self, observations: Iterable[Observation]) -> None:
        """Persist immutable source observations."""

    def get_observation(self, observation_id: str) -> Observation | None:
        """Load one observation by identifier."""

    def write_evidence(self, evidence: Iterable[Evidence]) -> None:
        """Persist provenance-backed evidence."""

    def get_evidence(self, evidence_id: str) -> Evidence | None:
        """Load one evidence item by identifier."""

    def write_decisions(self, decisions: Iterable[DecisionReceipt]) -> None:
        """Persist policy-bound decision receipts."""

    def get_decision(self, decision_id: str) -> DecisionReceipt | None:
        """Load one decision receipt by identifier."""

    def write_resolution_runs(self, runs: Iterable[ResolutionRun]) -> None:
        """Persist cost and outcome metrics for resolver invocations."""

    def get_resolution_run(self, run_id: str) -> ResolutionRun | None:
        """Load one resolver-run metric record by identifier."""

    def write_resolution_cases(self, cases: Iterable[ResolutionCase]) -> None:
        """Persist unresolved cases without resolving them implicitly."""

    def get_resolution_case(self, case_id: str) -> ResolutionCase | None:
        """Load one unresolved case by identifier."""

    def write_evidence_actions(self, actions: Iterable[EvidenceAction]) -> None:
        """Persist policy-permitted evidence actions."""

    def get_evidence_action(self, action_id: str) -> EvidenceAction | None:
        """Load one permitted evidence action by identifier."""

    def list_evidence_actions(self, case_id: str) -> tuple[EvidenceAction, ...]:
        """List the persisted actions permitted for one resolution case."""

    def write_action_observations(self, links: Iterable[ActionObservation]) -> None:
        """Persist links from permitted actions to their resulting Observations."""

    def get_action_observation(self, action_id: str) -> ActionObservation | None:
        """Load the Observation yielded by one evidence action, if recorded."""

    def write_claims(self, claims: Iterable[Claim]) -> None:
        """Persist evidence-backed revisable entity claims."""

    def list_claims(self, entity_id: str) -> tuple[Claim, ...]:
        """List claims for one entity in assertion order."""

    def write_contradictions(self, contradictions: Iterable[Contradiction]) -> None:
        """Persist material contradictions without resolving them implicitly."""

    def list_contradictions(self, entity_id: str) -> tuple[Contradiction, ...]:
        """List contradictions for one entity in detection order."""

    def write_relations(self, relations: Iterable[EntityRelation]) -> None:
        """Persist evidence-backed relationships between stable entities."""

    def list_relations(self, entity_id: str) -> tuple[EntityRelation, ...]:
        """List relations incident to one entity in assertion order."""

    def write_open_questions(self, questions: Iterable[OpenQuestion]) -> None:
        """Persist material entity unknowns and their optional cases."""

    def list_open_questions(self, entity_id: str) -> tuple[OpenQuestion, ...]:
        """List open questions for one entity in opening order."""

    def write_case_events(self, events: Iterable[CaseEvent]) -> None:
        """Persist immutable ResolutionCase history events."""

    def list_case_events(self, case_id: str) -> tuple[CaseEvent, ...]:
        """List one case's events in recorded order."""
