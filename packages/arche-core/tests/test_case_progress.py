# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Read-only progression tests for the bounded ResolutionCase controller."""

from __future__ import annotations

from datetime import UTC, datetime

import arche
import pytest
from arche.runtime import (
    CaseEvent,
    EvidenceAction,
    EvidenceGap,
    Observation,
    ResolutionBudget,
    ResolutionCase,
    ResolutionIntent,
    ToolCapability,
    assess_case_progress,
)

NOW = datetime(2026, 9, 5, 15, tzinfo=UTC)


@pytest.fixture
def case_runtime():
    """Build an isolated case with one permitted document action."""
    pytest.importorskip("duckdb")
    engine = arche.attach("duckdb:///:memory:")
    case = ResolutionCase(
        "case_progress",
        "Which supplier is this?",
        ("obs_input",),
        (),
        NOW,
        evidence_gaps=(
            EvidenceGap(
                "registration_id",
                "An independent registration source is needed.",
                priority=1,
                permitted_action_types=("document_extract",),
            ),
        ),
        intent=ResolutionIntent("supplier", "reconcile", ("name",), "supplier-policy-v1"),
    )
    action = EvidenceAction(
        "act_document",
        case.case_id,
        "document_extract",
        "document",
        NOW,
        "supplier-policy-v1",
        max_cost=0,
    )
    engine.store.write_observations(
        [Observation("obs_input", "document", "input-1", NOW, "sha256:input")]
    )
    engine.store.write_resolution_cases([case])
    engine.store.write_evidence_actions([action])
    yield engine, case, action
    engine.store.close()


def test_progress_requires_a_recorded_plan(case_runtime):
    """A case has no implicit plan merely because an action is permitted."""
    engine, case, _ = case_runtime

    progress = engine.get_case_progress(case.case_id)

    assert progress.state == "awaiting_plan"
    assert progress.next_step == "plan_permitted_evidence"
    assert progress.unresolved_gap_fields == ("registration_id",)
    assert assess_case_progress(engine.store, case.case_id) == progress


def test_progress_moves_from_planned_action_to_review(case_runtime):
    """An action result cannot skip the Observation-to-reviewed-Evidence boundary."""
    engine, case, action = case_runtime
    plan = engine.plan_case(
        case.case_id,
        capabilities=(ToolCapability("document", ("document_extract",), "supplier-policy-v1"),),
        budget=ResolutionBudget(1, 0),
    )
    engine.record_case_plan(plan, recorded_at=NOW)

    planned = engine.get_case_progress(case.case_id)
    assert planned.state == "awaiting_action_execution"
    assert planned.planned_action_ids == (action.action_id,)

    engine.ingest_action_observation(
        action.action_id,
        Observation(
            "obs_document",
            "document",
            "document-1",
            NOW,
            "sha256:document",
            provenance={"kind": "document_ingestion", "outcome": "success"},
        ),
    )
    after = engine.get_case_progress(case.case_id)

    assert after.state == "awaiting_evidence_review"
    assert after.next_step == "review_document_observation"
    assert after.completed_action_ids == (action.action_id,)
    assert "Evidence" in after.reason


def test_progress_never_treats_simulated_consent_as_identity_evidence(case_runtime):
    """A Pod response must direct the controller to independent evidence, not inference."""
    engine, case, action = case_runtime
    pod_action = EvidenceAction(
        "act_pod",
        case.case_id,
        "pod_review_request",
        "pod",
        NOW,
        "supplier-policy-v1",
        max_cost=0,
    )
    engine.store.write_evidence_actions([pod_action])
    engine.store.write_case_events(
        [
            CaseEvent(
                "evt_pod_plan",
                case.case_id,
                "evidence_plan",
                NOW,
                references=(pod_action.action_id,),
            )
        ]
    )
    engine.ingest_action_observation(
        pod_action.action_id,
        Observation(
            "obs_pod",
            "pod",
            None,
            NOW,
            "sha256:pod",
            provenance={
                "kind": "simulated_pod_consent",
                "outcome": "consented",
                "identity_evidence": False,
            },
        ),
    )

    progress = engine.get_case_progress(case.case_id)

    assert action.action_id not in progress.planned_action_ids
    assert progress.state == "needs_independent_evidence"
    assert progress.next_step == "acquire_independent_evidence"
    assert "not identity evidence" in progress.reason


def test_progress_requires_policy_before_or_after_a_resolver_release(case_runtime):
    """Receipts and policy outcomes remain distinct, non-executing controller states."""
    engine, case, _ = case_runtime
    engine.store.write_case_events(
        [
            CaseEvent(
                "evt_receipt",
                case.case_id,
                "resolver_decision",
                NOW,
                references=("run_1", "decision_1"),
            )
        ]
    )

    awaiting_policy = engine.get_case_progress(case.case_id)
    assert awaiting_policy.state == "awaiting_policy"
    assert awaiting_policy.next_step == "apply_resolution_decision_policy"
    assert awaiting_policy.resolver_decision_ids == ("decision_1",)

    engine.store.write_case_events(
        [
            CaseEvent(
                "evt_policy",
                case.case_id,
                "policy_decision",
                NOW,
                references=("decision_1",),
                provenance={"action": "link"},
            )
        ]
    )
    released = engine.get_case_progress(case.case_id)

    assert released.state == "released_for_execution"
    assert released.next_step == "execute_released_policy_decision"
    assert released.policy_decision_ids == ("decision_1",)
