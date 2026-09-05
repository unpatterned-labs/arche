# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Read-only, deterministic progress assessment for persisted resolution cases."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ._models import ResolutionCase
from ._reassessment import reassessed_case

if TYPE_CHECKING:
    from arche.store.base import ArcheStore


@dataclass(frozen=True)
class CaseProgress:
    """The next safe move inferred from immutable case history.

    This is a control-plane view, not a decision.  It does not execute an
    action, create Evidence, invoke a resolver, or update entity memory.
    """

    case_id: str
    state: str
    next_step: str
    reason: str
    planned_action_ids: tuple[str, ...] = ()
    completed_action_ids: tuple[str, ...] = ()
    unresolved_gap_fields: tuple[str, ...] = ()
    resolver_decision_ids: tuple[str, ...] = ()
    policy_decision_ids: tuple[str, ...] = ()


def assess_case_progress(store: ArcheStore, case_id: str) -> CaseProgress:
    """Return the next permitted control-plane step for a persisted case.

    Observation output remains untrusted until a caller records reviewed
    Evidence.  In particular, a simulated Pod consent is never treated as
    identity evidence or as a reason to run a resolver.

    Parameters:
        store: The canonical store containing the case and immutable history.
        case_id: The opaque ResolutionCase identifier to inspect.

    Returns:
        A value-free status and next-step recommendation derived only from
        persisted case records.

    Raises:
        ValueError: If ``case_id`` is not present in the supplied store.
    """
    case = store.get_resolution_case(case_id)
    if case is None:
        raise ValueError(f"resolution case {case_id!r} does not exist")
    history = store.list_case_events(case_id)
    return _progress_for_case(store, reassessed_case(store, case), history)


def _progress_for_case(store: ArcheStore, case: ResolutionCase, history: tuple) -> CaseProgress:
    """Derive progress from one case's immutable event sequence."""
    plans = tuple(event for event in history if event.event_type == "evidence_plan")
    resolver_decisions = tuple(
        reference
        for event in history
        if event.event_type == "resolver_decision"
        for reference in event.references[1:]
    )
    policy_decisions = tuple(
        reference
        for event in history
        if event.event_type == "policy_decision"
        for reference in event.references[:1]
    )
    if policy_decisions:
        return _after_policy(case, history, resolver_decisions, policy_decisions)
    if resolver_decisions:
        return CaseProgress(
            case.case_id,
            "awaiting_policy",
            "apply_resolution_decision_policy",
            "Resolver receipts are recorded; apply a pinned decision policy before any release.",
            unresolved_gap_fields=_gap_fields(case),
            resolver_decision_ids=resolver_decisions,
        )
    if not plans:
        return CaseProgress(
            case.case_id,
            "awaiting_plan",
            "plan_permitted_evidence",
            "No bounded evidence plan is recorded for this unresolved case.",
            unresolved_gap_fields=_gap_fields(case),
        )

    plan = plans[-1]
    planned_action_ids = plan.references
    completed_action_ids = tuple(
        action_id
        for action_id in planned_action_ids
        if store.get_action_observation(action_id) is not None
    )
    if completed_action_ids:
        return _after_action_observations(
            store,
            case,
            history,
            plan,
            completed_action_ids,
        )
    planned_methods = tuple(str(value) for value in plan.provenance.get("planned_method_ids", ()))
    if planned_methods:
        return CaseProgress(
            case.case_id,
            "awaiting_method_approval",
            "approve_and_execute_resolution_method",
            "A qualified resolver method is planned; its exact configuration still needs "
            "caller approval.",
            planned_action_ids=planned_action_ids,
            unresolved_gap_fields=_gap_fields(case),
        )
    if planned_action_ids:
        return CaseProgress(
            case.case_id,
            "awaiting_action_execution",
            "approve_and_execute_evidence_action",
            "A permitted, costed action is planned; execution must remain caller controlled.",
            planned_action_ids=planned_action_ids,
            unresolved_gap_fields=_gap_fields(case),
        )
    return CaseProgress(
        case.case_id,
        "needs_new_permission",
        "request_permitted_evidence_action",
        "The recorded plan cannot address the remaining evidence gaps with currently "
        "permitted work.",
        unresolved_gap_fields=_gap_fields(case),
    )


def _after_action_observations(
    store: ArcheStore, case: ResolutionCase, history: tuple, plan, completed: tuple[str, ...]
) -> CaseProgress:
    """Return the safe state after one or more selected actions yielded Observations."""
    observations = tuple(
        store.get_observation(store.get_action_observation(action_id).observation_id)
        for action_id in completed
    )
    if any(
        observation is not None and observation.provenance.get("kind") == "simulated_pod_consent"
        for observation in observations
    ):
        return CaseProgress(
            case.case_id,
            "needs_independent_evidence",
            "acquire_independent_evidence",
            "Pod consent only permits a review exchange; it is not identity evidence and "
            "cannot support a resolution decision.",
            planned_action_ids=plan.references,
            completed_action_ids=completed,
            unresolved_gap_fields=_gap_fields(case),
        )
    failures = tuple(
        action_id
        for action_id, observation in zip(completed, observations, strict=True)
        if observation is None or observation.provenance.get("outcome") == "failure"
    )
    if failures:
        return CaseProgress(
            case.case_id,
            "needs_new_permission",
            "request_retry_or_alternative_action",
            "An executed action failed. Its immutable result cannot be retried; permit a "
            "new bounded action instead.",
            planned_action_ids=plan.references,
            completed_action_ids=completed,
            unresolved_gap_fields=_gap_fields(case),
        )
    reviewed_action_ids = {
        str(event.provenance["action_id"])
        for event in history
        if event.event_type in {"reviewed_action_evidence", "reviewed_document_evidence"}
        and "action_id" in event.provenance
    }
    pending_document_review = tuple(
        action_id
        for action_id in completed
        if _action_type(store, action_id) in {"document_extract", "document_ocr"}
        and action_id not in reviewed_action_ids
    )
    if pending_document_review:
        return CaseProgress(
            case.case_id,
            "awaiting_evidence_review",
            "review_document_observation",
            "Document output is an Observation only; review fields and spans before it can "
            "become Evidence.",
            planned_action_ids=plan.references,
            completed_action_ids=completed,
            unresolved_gap_fields=_gap_fields(case),
        )
    if any(
        _action_type(store, action_id) not in {"document_extract", "document_ocr"}
        and action_id not in reviewed_action_ids
        for action_id in completed
    ):
        return CaseProgress(
            case.case_id,
            "awaiting_evidence_review",
            "review_action_observation",
            "External action output is an Observation only; independently review it before "
            "recording Evidence.",
            planned_action_ids=plan.references,
            completed_action_ids=completed,
            unresolved_gap_fields=_gap_fields(case),
        )
    planned_methods = tuple(str(value) for value in plan.provenance.get("planned_method_ids", ()))
    if planned_methods:
        return CaseProgress(
            case.case_id,
            "awaiting_method_approval",
            "approve_and_execute_resolution_method",
            "Reviewed Evidence is available; the selected resolver still needs caller approval.",
            planned_action_ids=plan.references,
            completed_action_ids=completed,
            unresolved_gap_fields=_gap_fields(case),
        )
    return CaseProgress(
        case.case_id,
        "needs_resolution_plan",
        "plan_qualified_resolution_method",
        "Reviewed Evidence is available, but no resolver method is selected for this case.",
        planned_action_ids=plan.references,
        completed_action_ids=completed,
        unresolved_gap_fields=_gap_fields(case),
    )


def _after_policy(
    case: ResolutionCase, history: tuple, receipts: tuple[str, ...], decisions: tuple[str, ...]
) -> CaseProgress:
    """Describe what remains after a policy outcome without executing it."""
    latest = next(event for event in reversed(history) if event.event_type == "policy_decision")
    action = str(latest.provenance.get("action", ""))
    if action in {"link", "create"}:
        state, next_step, reason = (
            "released_for_execution",
            "execute_released_policy_decision",
            "A recorded policy release exists; only the caller-owned application executor "
            "may perform it.",
        )
    else:
        state, next_step, reason = (
            "policy_decided",
            "review_or_reassess_case",
            "Policy recorded a non-releasing outcome; preserve it and obtain new permitted "
            "evidence only if the case continues.",
        )
    return CaseProgress(
        case.case_id,
        state,
        next_step,
        reason,
        unresolved_gap_fields=_gap_fields(case),
        resolver_decision_ids=receipts,
        policy_decision_ids=decisions,
    )


def _action_type(store: ArcheStore, action_id: str) -> str | None:
    """Return an action type defensively for a persisted action identifier."""
    action = store.get_evidence_action(action_id)
    return action.action_type if action is not None else None


def _gap_fields(case: ResolutionCase) -> tuple[str, ...]:
    """Expose only deterministic field labels, sorted as the planner does."""
    return tuple(
        gap.field for gap in sorted(case.evidence_gaps, key=lambda gap: (gap.priority, gap.field))
    )
