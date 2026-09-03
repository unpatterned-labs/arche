# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""A deterministic, policy-bounded planner for unresolved resolution cases."""

from __future__ import annotations

from dataclasses import dataclass

from ._cases import what_would_resolve
from ._models import (
    EvidenceAction,
    EvidenceGap,
    ResolutionCase,
    ResolutionIntent,
    ResolutionMethod,
    ToolCapability,
)


@dataclass(frozen=True)
class ResolutionBudget:
    """The maximum work a planner may schedule for one resolution case."""

    max_actions: int
    max_cost: float


@dataclass(frozen=True)
class CaseAssessment:
    """Structured understanding of a case before any action is selected."""

    case_id: str
    question: str
    candidate_entity_ids: tuple[str, ...]
    evidence_gaps: tuple[EvidenceGap, ...]
    eligible_action_ids: tuple[str, ...]
    unavailable_action_ids: tuple[str, ...]
    method_assessments: tuple[MethodAssessment, ...] = ()


@dataclass(frozen=True)
class MethodAssessment:
    """One configured resolver method's explicit eligibility rationale."""

    method_id: str
    eligible: bool
    reason: str


@dataclass(frozen=True)
class PlannedEvidenceAction:
    """One permitted evidence action selected to address a specific gap."""

    action_id: str
    gap_field: str
    estimated_cost: float
    rationale: str


@dataclass(frozen=True)
class PlannedResolutionMethod:
    """A configured resolver method selected for a later, separate execution step."""

    method_id: str
    resolver: str
    configuration_pin: str
    estimated_cost: float
    rationale: str


@dataclass(frozen=True)
class EvidencePlan:
    """A bounded plan produced from an assessment, without executing it."""

    assessment: CaseAssessment
    actions: tuple[PlannedEvidenceAction, ...]
    total_estimated_cost: float
    unresolved_gap_fields: tuple[str, ...]
    methods: tuple[PlannedResolutionMethod, ...] = ()


class DeterministicResolutionPlanner:
    """Reason about explicit gaps, then select feasible permitted actions."""

    def assess(
        self,
        case: ResolutionCase,
        actions: tuple[EvidenceAction, ...],
        capabilities: tuple[ToolCapability, ...],
        methods: tuple[ResolutionMethod, ...] = (),
    ) -> CaseAssessment:
        """Build the planner's structured case understanding.

        Parameters:
            case: The unresolved case to understand.
            actions: Persisted policy-permitted actions for that case.
            capabilities: Read-only capabilities currently available to execute.

        Returns:
            A deterministic assessment that exposes eligible and unavailable work,
            including the reason each configured resolver is or is not suitable.
        """
        capable_actions = tuple(
            action
            for action in actions
            if any(capability.permits(action) for capability in capabilities)
        )
        eligible_ids = tuple(
            action.action_id
            for action in capable_actions
            if action.max_cost is not None and action.max_cost >= 0
        )
        unavailable_ids = tuple(
            action.action_id for action in actions if action.action_id not in eligible_ids
        )
        return CaseAssessment(
            case_id=case.case_id,
            question=case.question,
            candidate_entity_ids=case.candidate_entity_ids,
            evidence_gaps=what_would_resolve(case),
            eligible_action_ids=eligible_ids,
            unavailable_action_ids=unavailable_ids,
            method_assessments=tuple(_assess_method(case.intent, method) for method in methods),
        )

    def plan(
        self,
        case: ResolutionCase,
        actions: tuple[EvidenceAction, ...],
        capabilities: tuple[ToolCapability, ...],
        budget: ResolutionBudget,
        methods: tuple[ResolutionMethod, ...] = (),
    ) -> EvidencePlan:
        """Select permitted, capable, costed actions after assessing a case.

        Parameters:
            case: The unresolved case to address.
            actions: Persisted policy-permitted actions for that case.
            capabilities: Read-only capabilities currently available to execute.
            budget: Hard maximum action count and estimated cost.

        Returns:
            A plan that does not execute actions or modify entity state.

        Raises:
            ValueError: If the budget is not non-negative.
        """
        if budget.max_actions < 0 or budget.max_cost < 0:
            raise ValueError("resolution budget limits must be non-negative")

        assessment = self.assess(case, actions, capabilities, methods)
        eligible = {
            action.action_id: action
            for action in actions
            if action.action_id in assessment.eligible_action_ids
        }
        selected: list[PlannedEvidenceAction] = []
        addressed_fields: set[str] = set()
        total_cost = 0.0
        for gap in assessment.evidence_gaps:
            candidates = sorted(
                (
                    action
                    for action in eligible.values()
                    if action.action_type in gap.permitted_action_types
                ),
                key=lambda action: (float(action.max_cost or 0), action.action_id),
            )
            if not candidates or len(selected) >= budget.max_actions:
                continue
            action = candidates[0]
            estimated_cost = float(action.max_cost or 0)
            if total_cost + estimated_cost > budget.max_cost:
                continue
            selected.append(
                PlannedEvidenceAction(
                    action_id=action.action_id,
                    gap_field=gap.field,
                    estimated_cost=estimated_cost,
                    rationale=(f"{action.action_type} is permitted for {gap.field}: {gap.reason}"),
                )
            )
            addressed_fields.add(gap.field)
            total_cost += estimated_cost
            eligible.pop(action.action_id)

        unresolved = tuple(
            gap.field for gap in assessment.evidence_gaps if gap.field not in addressed_fields
        )
        selected_methods: list[PlannedResolutionMethod] = []
        eligible_methods = {
            assessment.method_assessments[index].method_id
            for index, method in enumerate(methods)
            if assessment.method_assessments[index].eligible
        }
        for method in sorted(
            (method for method in methods if method.method_id in eligible_methods),
            key=lambda method: (method.priority, method.estimated_cost, method.method_id),
        ):
            if total_cost + method.estimated_cost > budget.max_cost:
                continue
            selected_methods.append(
                PlannedResolutionMethod(
                    method_id=method.method_id,
                    resolver=method.resolver,
                    configuration_pin=method.configuration_pin,
                    estimated_cost=method.estimated_cost,
                    rationale=(
                        f"{method.resolver} is configured for {case.intent.operation} "
                        f"of {case.intent.entity_type}"
                    ),
                )
            )
            total_cost += method.estimated_cost
            break

        return EvidencePlan(
            assessment=assessment,
            actions=tuple(selected),
            total_estimated_cost=total_cost,
            unresolved_gap_fields=unresolved,
            methods=tuple(selected_methods),
        )


def _assess_method(intent: ResolutionIntent | None, method: ResolutionMethod) -> MethodAssessment:
    """Explain whether one configured resolver is suitable for a case intent."""
    if intent is None:
        return MethodAssessment(method.method_id, False, "case has no structured resolution intent")
    if method.policy_pin != intent.policy_pin:
        return MethodAssessment(
            method.method_id, False, "policy pin does not match the case intent"
        )
    if intent.operation not in method.operations:
        return MethodAssessment(method.method_id, False, "does not support the requested operation")
    if intent.entity_type not in method.entity_types:
        return MethodAssessment(
            method.method_id, False, "does not support the requested entity type"
        )
    missing_fields = tuple(
        field for field in method.required_fields if field not in intent.available_fields
    )
    if missing_fields:
        return MethodAssessment(
            method.method_id,
            False,
            f"needs unavailable fields: {', '.join(missing_fields)}",
        )
    if (
        method.max_candidate_pairs is not None
        and intent.candidate_pairs is not None
        and intent.candidate_pairs > method.max_candidate_pairs
    ):
        return MethodAssessment(
            method.method_id, False, "candidate-pair scale exceeds method limit"
        )
    return MethodAssessment(method.method_id, True, "matches the case intent and configured limits")
