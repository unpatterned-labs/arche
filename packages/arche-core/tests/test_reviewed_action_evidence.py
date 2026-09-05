# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""External action results need review before they can affect a case plan."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import arche
import pytest
from arche.runtime import (
    EvidenceAction,
    EvidenceGap,
    Observation,
    ResolutionBudget,
    ResolutionCase,
    ResolutionIntent,
    ResolutionMethod,
    ReviewedActionEvidence,
    ToolCapability,
)

NOW = datetime(2026, 9, 5, 16, tzinfo=UTC)


@pytest.fixture
def registry_case():
    """Create a persisted supplier case with an approved registry action."""
    pytest.importorskip("duckdb")
    engine = arche.attach("duckdb:///:memory:")
    input_observation = Observation("obs_input", "document", "input-1", NOW, "sha256:input")
    case = ResolutionCase(
        "case_registry",
        "Which supplier does this document describe?",
        (input_observation.observation_id,),
        (),
        NOW,
        evidence_gaps=(
            EvidenceGap(
                "registration_id",
                "An independent registry record is needed.",
                permitted_action_types=("registry_lookup",),
            ),
        ),
        intent=ResolutionIntent("organisation", "find", ("name",), "supplier-policy-v1"),
    )
    action = EvidenceAction(
        "act_registry",
        case.case_id,
        "registry_lookup",
        "supplier_registry",
        NOW,
        "supplier-policy-v1",
        max_cost=0.1,
    )
    method = ResolutionMethod(
        "registry_ready_matcher",
        "arche.resolve.reconcile",
        ("organisation",),
        ("find",),
        "supplier-policy-v1",
        "arche.resolve.reconcile@registry-v1",
        required_fields=("registration_id",),
    )
    engine.store.write_observations([input_observation])
    engine.store.write_resolution_cases([case])
    engine.store.write_evidence_actions([action])
    yield engine, case, action, method
    engine.store.close()


def test_reviewed_registry_evidence_unblocks_reassessment_and_method_planning(registry_case):
    """Only value-free reviewed labels let an external result change the plan."""
    engine, case, action, method = registry_case
    capability = ToolCapability("supplier_registry", ("registry_lookup",), "supplier-policy-v1")
    initial_plan = engine.plan_case(
        case.case_id,
        capabilities=(capability,),
        budget=ResolutionBudget(1, 1),
        methods=(method,),
    )
    assert [item.action_id for item in initial_plan.actions] == [action.action_id]
    assert initial_plan.methods == ()
    engine.record_case_plan(initial_plan, recorded_at=NOW)
    engine.ingest_action_observation(
        action.action_id,
        Observation(
            "obs_registry",
            "supplier_registry",
            "caller-held-record",
            NOW,
            "sha256:registry-response",
            provenance={"kind": "external_evidence", "outcome": "success"},
        ),
    )

    waiting_for_review = engine.get_case_progress(case.case_id)
    assert waiting_for_review.state == "awaiting_evidence_review"
    assert waiting_for_review.next_step == "review_action_observation"

    evidence, event = engine.record_reviewed_action_evidence(
        case.case_id,
        action.action_id,
        (ReviewedActionEvidence("ev_registry_id", "registration_id", "registry_identifier"),),
        review_id="review_registry_01",
        recorded_at=NOW,
    )

    assert evidence[0].observation_id == "obs_registry"
    assert evidence[0].provenance["field"] == "registration_id"
    assert event.event_type == "reviewed_action_evidence"
    assert "caller-held-record" not in str(event)
    reassessment = engine.reassess_case(case.case_id)
    assert reassessment.reviewed_fields == ("registration_id",)
    assert reassessment.resolved_gap_fields == ("registration_id",)
    assert reassessment.remaining_gap_fields == ()

    revised_plan = engine.plan_case(
        case.case_id,
        capabilities=(capability,),
        budget=ResolutionBudget(1, 1),
        methods=(method,),
    )
    assert revised_plan.actions == ()
    assert [item.method_id for item in revised_plan.methods] == [method.method_id]
    engine.record_case_plan(revised_plan, recorded_at=NOW + timedelta(seconds=1))
    progress = engine.get_case_progress(case.case_id)
    assert progress.state == "awaiting_method_approval"
    assert progress.next_step == "approve_and_execute_resolution_method"


def test_reviewed_action_evidence_rejects_document_actions_and_duplicate_review_ids(registry_case):
    """The generic bridge cannot bypass document spans or duplicate its review."""
    engine, case, _, _ = registry_case
    document_action = EvidenceAction(
        "act_document",
        case.case_id,
        "document_extract",
        "document",
        NOW,
        "supplier-policy-v1",
        max_cost=0,
    )
    engine.store.write_evidence_actions([document_action])
    engine.ingest_action_observation(
        document_action.action_id,
        Observation(
            "obs_document",
            "document",
            "doc-1",
            NOW,
            "sha256:document",
            provenance={"kind": "document_ingestion", "outcome": "success"},
        ),
    )
    reviewed = (ReviewedActionEvidence("ev_document", "registration_id", "registry_identifier"),)

    with pytest.raises(ValueError, match="record_reviewed_document_evidence"):
        engine.record_reviewed_action_evidence(
            case.case_id,
            document_action.action_id,
            reviewed,
            review_id="review_document_01",
            recorded_at=NOW,
        )

    with pytest.raises(ValueError, match="value-free label"):
        ReviewedActionEvidence("ev_private", "registration_id", "Private Supplier Name")
