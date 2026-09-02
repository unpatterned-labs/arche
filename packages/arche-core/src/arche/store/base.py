# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Canonical-store boundary for the vNext runtime."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol

from arche.runtime._models import DecisionReceipt, Entity, Evidence, Observation


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
