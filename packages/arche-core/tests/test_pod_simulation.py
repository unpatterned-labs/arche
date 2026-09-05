# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Consent failures and the exact metadata budget of the offline Pod experiment."""

from __future__ import annotations

import json
from dataclasses import asdict, replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from arche.runtime import (
    CaseEvent,
    Evidence,
    EvidenceAction,
    EvidenceGap,
    Observation,
    ResolutionBudget,
    ResolutionCase,
    ResolutionDecisionPolicy,
    ResolutionIntent,
    ToolCapability,
    attach,
)
from arche.runtime.pod_simulation import (
    PodReviewRequest,
    SimulatedPod,
    approve_pod_review,
    execute_pod_review,
)

NOW = datetime(2026, 9, 5, 12, tzinfo=UTC)
END = NOW + timedelta(minutes=5)
SECRET = "Private Person 12345678901"


@pytest.fixture
def scenario(tmp_path):
    engine = attach(f"duckdb:///{tmp_path / 'requester.duckdb'}")
    observation = Observation("obs_local", "document", None, NOW, "sha256:local")
    case = ResolutionCase(
        "case_local", SECRET, (observation.observation_id,), (), NOW,
        evidence_gaps=(EvidenceGap(
            "independent_evidence", "Needs a second reviewed source",
            permitted_action_types=("pod_review_request",),
        ),),
        intent=ResolutionIntent("person", "compare", ("name",), "local-policy"),
    )
    action = EvidenceAction(
        "action_local", case.case_id, "pod_review_request", "pod-local-ref", NOW,
        "local-policy", max_cost=0,
    )
    engine.store.write_observations([observation])
    engine.store.write_resolution_cases([case])
    engine.store.write_evidence_actions([action])
    capability = ToolCapability(action.source_id, (action.action_type,), action.policy_pin)
    plan = engine.plan_case(
        case.case_id, capabilities=(capability,), budget=ResolutionBudget(1, 0)
    )
    event = engine.record_case_plan(plan, recorded_at=NOW)
    return engine, case, action, plan, event, SimulatedPod()


def _approve(scenario):
    engine, _, action, _, event, pod = scenario
    return approve_pod_review(
        engine, action.action_id, event.event_id, pod, approved_at=NOW, expires_at=END
    )


def test_plan_explains_external_need_but_does_not_execute(scenario):
    engine, _, action, plan, _, _ = scenario
    assert "Needs a second reviewed source" in plan.actions[0].rationale
    assert plan.actions[0].estimated_cost == 0
    assert engine.store.get_action_observation(action.action_id) is None
    assert all(e.event_type == "evidence_plan" for e in engine.get_case_history(action.case_id))


@pytest.mark.parametrize("failure", ["unapproved", "changed_request", "wrong_pod", "expired"])
def test_local_denial_precedes_exchange(scenario, monkeypatch, failure):
    engine, _, action, _, _, pod = scenario
    request = _approve(scenario) if failure != "unapproved" else PodReviewRequest(
        str(uuid4()), pod.audience
    )
    if failure == "changed_request":
        request = replace(request, request_id=str(uuid4()))
    if failure == "wrong_pod":
        pod = SimulatedPod()
    monkeypatch.setattr(pod, "exchange", lambda *a, **kw: pytest.fail("transport ran"))
    with pytest.raises(ValueError):
        execute_pod_review(
            engine, action.action_id, request, pod, "unknown-grant",
            now=END if failure == "expired" else NOW,
        )
    assert engine.store.get_action_observation(action.action_id) is None


@pytest.mark.parametrize("failure", ["absent", "revoked", "expired", "other_request", "replay"])
def test_responder_consent_denials_have_identical_wire_shape(failure):
    pod = SimulatedPod()
    request = PodReviewRequest(str(uuid4()), pod.audience)
    grant = pod.grant(request, now=NOW, expires_at=END)
    if failure == "revoked":
        pod.revoke(grant)
    elif failure == "absent":
        grant = "unknown"
    elif failure == "other_request":
        request = replace(request, request_id=str(uuid4()))
    elif failure == "replay":
        assert json.loads(pod.exchange(request, grant, now=NOW))["status"] == "consented"
    result = pod.exchange(request, grant, now=END if failure == "expired" else NOW)
    assert result == pod.exchange(request, "unknown", now=NOW)
    assert json.loads(result) == {"request_id": request.request_id, "status": "denied"}


def test_success_returns_observation_and_never_identity_or_credentials(scenario, monkeypatch):
    engine, case, action, _, _, pod = scenario
    request = _approve(scenario)
    grant = pod.grant(request, now=NOW, expires_at=END)
    assert set(json.loads(request.to_bytes())) == {
        "request_id", "audience", "purpose", "disclosure",
    }
    wire = []
    exchange = pod.exchange

    def capture(req, handle, *, now):
        response = exchange(req, handle, now=now)
        wire.extend([req.to_bytes(), response])
        return response

    monkeypatch.setattr(pod, "exchange", capture)
    observation = execute_pod_review(engine, action.action_id, request, pod, grant, now=NOW)
    assert observation.provenance["outcome"] == "consented"
    assert observation.provenance["identity_evidence"] is False
    assert engine.store.get_observation(observation.observation_id) == observation
    assert engine.store.get_action_observation(action.action_id) is not None
    for private in (SECRET, case.case_id, action.action_id, action.source_id, action.policy_pin):
        assert private.encode() not in b"".join(wire)
    history = json.dumps([asdict(e) for e in engine.get_case_history(case.case_id)], default=str)
    for private in (SECRET, grant, request.request_id, pod.audience):
        assert private not in history
    assert set(json.loads(wire[1])) == {"request_id", "status"}
    with pytest.raises(ValueError, match="already attempted"):
        execute_pod_review(engine, action.action_id, request, pod, grant, now=NOW)
    assert len(wire) == 2


@pytest.mark.parametrize("response", [b'{"status":"consented","name":"secret"}', None])
def test_bad_or_failed_response_is_a_failure_observation(scenario, monkeypatch, response):
    engine, _, action, _, _, pod = scenario
    request = _approve(scenario)

    def exchange(*args, **kwargs):
        if response is None:
            raise OSError(SECRET)
        return response

    monkeypatch.setattr(pod, "exchange", exchange)
    observation = execute_pod_review(engine, action.action_id, request, pod, "grant", now=NOW)
    assert observation.provenance["outcome"] == "failed"
    assert SECRET not in json.dumps(asdict(observation), default=str)


def test_consent_cannot_be_used_as_independent_identity_corroboration(scenario):
    engine, case, action, _, _, pod = scenario
    request = _approve(scenario)
    grant = pod.grant(request, now=NOW, expires_at=END)
    observation = execute_pod_review(engine, action.action_id, request, pod, grant, now=NOW)
    evidence = (
        Evidence("ev_local", "obs_local", "name", "supports"),
        Evidence("ev_consent", observation.observation_id, "consent", "supports"),
    )
    engine.store.write_evidence(evidence)
    engine.record_case_reconcile_result(
        case.case_id,
        {"matches": [{"decision_id": "decision", "decision": "match", "score": .99}],
         "pins": {}, "blocking": {"candidate_pairs": 1}},
        run_id="run", created_at=NOW,
        evidence_ids_by_decision={"decision": tuple(e.evidence_id for e in evidence)},
    )
    result = engine.apply_resolution_decision_policy(
        case.case_id, "decision", policy=ResolutionDecisionPolicy("two-sources"), recorded_at=NOW
    )
    assert result.action == "review"
    assert result.independent_source_ids == ("document",)


def test_purpose_and_disclosure_cannot_carry_personal_data():
    with pytest.raises(ValueError, match="purpose"):
        PodReviewRequest(str(uuid4()), str(uuid4()), purpose=SECRET)
    with pytest.raises(ValueError, match="disclosure"):
        PodReviewRequest(str(uuid4()), str(uuid4()), disclosure=SECRET)
    with pytest.raises(ValueError):
        PodReviewRequest(SECRET, str(uuid4()))


def test_fresh_sessions_do_not_reuse_request_or_audience_identifiers():
    first, second = SimulatedPod(), SimulatedPod()
    a = PodReviewRequest(str(uuid4()), first.audience)
    b = PodReviewRequest(str(uuid4()), second.audience)
    assert a.request_id != b.request_id
    assert a.audience != b.audience


def test_durable_attempt_blocks_retry_after_requester_restart(scenario, tmp_path, monkeypatch):
    engine, case, action, _, _, pod = scenario
    request = _approve(scenario)
    engine.store.write_case_events([
        CaseEvent("evt_interrupted", case.case_id, "pod_review_attempt", NOW,
                  references=(action.action_id,))
    ])
    engine.store.close()
    reopened = attach(f"duckdb:///{tmp_path / 'requester.duckdb'}")
    monkeypatch.setattr(pod, "exchange", lambda *a, **kw: pytest.fail("transport ran"))
    try:
        with pytest.raises(ValueError, match="already attempted"):
            execute_pod_review(reopened, action.action_id, request, pod, "grant", now=NOW)
    finally:
        reopened.store.close()


def test_approval_requires_a_plan_and_a_capable_zero_cost_action(scenario):
    engine, case, action, _, _, pod = scenario
    plan = engine.plan_case(case.case_id, capabilities=(), budget=ResolutionBudget(1, 0))
    assert plan.actions == ()
    assert plan.unresolved_gap_fields == ("independent_evidence",)
    event = engine.record_case_plan(plan, recorded_at=NOW)
    with pytest.raises(ValueError, match="plan selecting"):
        approve_pod_review(engine, action.action_id, event.event_id, pod,
                           approved_at=NOW, expires_at=END)


def test_responder_future_consent_is_not_yet_valid_and_wrong_audience_fails():
    pod = SimulatedPod()
    request = PodReviewRequest(str(uuid4()), pod.audience)
    grant = pod.grant(request, now=NOW + timedelta(seconds=1), expires_at=END)
    assert json.loads(pod.exchange(request, grant, now=NOW))["status"] == "denied"
    with pytest.raises(ValueError, match="audience"):
        SimulatedPod().grant(request, now=NOW, expires_at=END)
    with pytest.raises(ValueError, match="timezone"):
        pod.grant(request, now=NOW.replace(tzinfo=None), expires_at=END)


def test_consent_cannot_promote_claims_or_relationships(scenario):
    from arche.doc._extract import Extraction, FieldEvidence
    from arche.doc.parse import ParsedDocument
    from arche.runtime import (
        DocumentClaimSpec,
        DocumentRelationSpec,
        Entity,
        ProposalAcceptancePolicy,
    )

    engine, case, action, _, _, pod = scenario
    request = _approve(scenario)
    grant = pod.grant(request, now=NOW, expires_at=END)
    observation = execute_pod_review(engine, action.action_id, request, pod, grant, now=NOW)
    consent = Evidence("ev_consent", observation.observation_id, "consent", "supports")
    engine.store.write_evidence([consent])
    engine.store.write_entities([
        Entity("ent_supplier", "organisation", "legal_entity", NOW),
        Entity("ent_estate", "place", "estate", NOW),
    ])
    proposals = engine.record_reviewed_document_proposals(
        case.case_id,
        ParsedDocument(source="synthetic.txt", text="Synthetic supplier",
                       provenance={"text_sha256": "a" * 64, "parser": "synthetic"}),
        Extraction(data=None, fields={"name": FieldEvidence("Synthetic supplier", span=(0, 18))}),
        observation_id="obs_reviewed", source_id="document", recorded_at=NOW,
        review_id="review_demo",
        claim_specs=(DocumentClaimSpec("ent_supplier", "name", "name"),),
        relation_specs=(DocumentRelationSpec("ent_supplier", "operates", "ent_estate", ("name",)),),
    )
    for proposal, accept in (
        (proposals.claims[0], engine.accept_claim_proposal),
        (proposals.relations[0], engine.accept_relation_proposal),
    ):
        outcome = accept(proposal, policy=ProposalAcceptancePolicy("two_sources"),
                         recorded_at=NOW, supplemental_evidence_ids=(consent.evidence_id,))
        assert outcome.decision == "review"
        assert outcome.independent_source_ids == ("document",)
    memory = engine.get_entity_memory("ent_supplier")
    assert memory.claims == ()
    assert memory.relations == ()
