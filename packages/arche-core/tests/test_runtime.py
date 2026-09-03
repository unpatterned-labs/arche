# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""M0 runtime foundation contracts."""

from __future__ import annotations

import subprocess
import sys
from dataclasses import replace
from datetime import UTC, datetime

import arche
import pytest
from arche.doc._extract import Extraction, FieldEvidence
from arche.doc.parse import ParsedDocument
from arche.runtime import (
    CaseEvent,
    Claim,
    Contradiction,
    DecisionReceipt,
    DocumentClaimSpec,
    DocumentRelationSpec,
    Entity,
    EntityRelation,
    Evidence,
    EvidenceAction,
    EvidenceGap,
    Observation,
    OpenQuestion,
    ProposalAcceptancePolicy,
    ResolutionBudget,
    ResolutionCase,
    ResolutionDecisionPolicy,
    ResolutionIntent,
    ResolutionMethod,
    ResolutionRun,
    ToolCapability,
    adapt_coreference_receipt,
    adapt_reconcile_result,
    new_entity_id,
    new_evidence_action_id,
    new_resolution_case_id,
    observation_from_document,
    what_would_resolve,
)


@pytest.fixture
def runtime():
    """An isolated local runtime with the optional DuckDB extra installed."""
    pytest.importorskip("duckdb")
    engine = arche.attach("duckdb:///:memory:")
    yield engine
    engine.store.close()


def test_attach_returns_a_usable_duckdb_runtime(runtime):
    """The public entry point gives callers an initialised local store."""
    runtime.store.ensure_schema()
    assert type(runtime.store).__name__ == "DuckDBStore"


def test_schema_initialisation_is_idempotent(runtime):
    """A caller may safely attach or initialise an existing store twice."""
    runtime.store.ensure_schema()
    runtime.store.ensure_schema()


def test_runtime_persists_stable_entity_observation_evidence_and_decision(runtime):
    """The M0 contracts round-trip without consulting a resolver or network."""
    timestamp = datetime(2026, 9, 2, 9, 0, tzinfo=UTC)
    entity = Entity(new_entity_id(), "organisation", "legal_entity", timestamp)
    observation = Observation("obs_01", "supplier_registry", "supplier-7", timestamp, "sha256:abc")
    evidence = Evidence(
        "ev_01",
        observation.observation_id,
        "registration_id",
        "supports",
        {"source": "registry"},
    )
    receipt = DecisionReceipt(
        "dec_01",
        "same_entity",
        "link",
        (evidence.evidence_id,),
        timestamp,
        raw_score=0.99,
        probability=0.98,
        policy_pin="supplier-v1",
        schema_pin="organisation-v1",
        provenance={"resolver_pins": {"engine": "crosswalk.v1"}},
    )

    runtime.store.write_entities([entity])
    runtime.store.write_observations([observation])
    runtime.store.write_evidence([evidence])
    runtime.store.write_decisions([receipt])

    assert runtime.store.get_entity(entity.entity_id) == entity
    assert runtime.store.get_observation(observation.observation_id) == observation
    assert runtime.store.get_evidence(evidence.evidence_id) == evidence
    assert runtime.store.get_decision(receipt.decision_id) == receipt


def test_document_observation_carries_parser_pins_into_a_permitted_case(runtime):
    """A parsed supply-chain document becomes an Observation, not a decision."""
    timestamp = datetime(2026, 9, 2, 9, 0, tzinfo=UTC)
    input_observation = Observation(
        "obs_tea_input", "tea-intake", "shipment-17", timestamp, "sha256:intake"
    )
    case = ResolutionCase(
        "case_tea_document",
        "Which tea supplier and estate does this shipment describe?",
        (input_observation.observation_id,),
        (),
        timestamp,
    )
    action = EvidenceAction(
        "act_tea_document",
        case.case_id,
        "document_extract",
        "unilever_tea_supply_chain",
        timestamp,
        "tea-pilot-v1",
    )
    parsed = ParsedDocument(
        source="unilever-global-tea-supply-chain.pdf",
        text="Reported supplier and estate labels.",
        provenance={
            "artifact_sha256": "a" * 64,
            "text_sha256": "b" * 64,
            "parser": "docling",
            "parser_version": "2.0",
            "ocr": False,
        },
    )

    observation = observation_from_document(
        parsed,
        observation_id="obs_tea_document",
        source_id=action.source_id,
        recorded_at=timestamp,
    )
    runtime.store.write_observations([input_observation])
    runtime.store.write_resolution_cases([case])
    runtime.store.write_evidence_actions([action])

    link = runtime.ingest_action_observation(action.action_id, observation)

    assert link.observation_id == observation.observation_id
    assert runtime.store.get_observation(observation.observation_id) == observation
    assert observation.content_hash == "sha256:" + "a" * 64
    assert observation.provenance["document"]["parser"] == "docling"


def test_reviewed_tea_document_fields_propose_but_do_not_assert_entity_memory(runtime):
    """Reviewed spans can propose supplier and estate beliefs without asserting them."""
    timestamp = datetime(2026, 9, 2, 9, 0, tzinfo=UTC)
    supplier = Entity("ent_tea_supplier", "organisation", "legal_entity", timestamp)
    estate = Entity("ent_tea_estate", "place", "estate", timestamp)
    input_observation = Observation(
        "obs_tea_case_input", "tea-intake", "shipment-18", timestamp, "sha256:intake"
    )
    case = ResolutionCase(
        "case_tea_proposal",
        "Which supplier and estate does this reviewed tea document describe?",
        (input_observation.observation_id,),
        (supplier.entity_id, estate.entity_id),
        timestamp,
    )
    parsed = ParsedDocument(
        source="reviewed-tea-supplier.pdf",
        text="Kijani Tea Exporters sources from Kijani Estate.",
        provenance={
            "artifact_sha256": "c" * 64,
            "text_sha256": "d" * 64,
            "parser": "docling",
            "parser_version": "2.0",
            "ocr": False,
        },
    )
    extraction = Extraction(
        data=None,
        fields={
            "supplier_name": FieldEvidence(
                "Kijani Tea Exporters", source="extractor", confidence=0.81, span=(0, 20), page=1
            ),
            "estate_name": FieldEvidence(
                "Kijani Estate", source="extractor", confidence=0.79, span=(34, 47), page=1
            ),
        },
        document=parsed.source,
    )
    runtime.store.write_entities([supplier, estate])
    runtime.store.write_observations([input_observation])
    runtime.store.write_resolution_cases([case])

    proposals = runtime.record_reviewed_document_proposals(
        case.case_id,
        parsed,
        extraction,
        observation_id="obs_tea_reviewed_document",
        source_id="tea_review_pack",
        recorded_at=timestamp,
        review_id="review:tea:18",
        claim_specs=(DocumentClaimSpec(supplier.entity_id, "display_name", "supplier_name"),),
        relation_specs=(
            DocumentRelationSpec(
                supplier.entity_id,
                "sources_from",
                estate.entity_id,
                ("supplier_name", "estate_name"),
            ),
        ),
        event_id="event_tea_reviewed_proposals",
    )

    assert [item.provenance["span"] for item in proposals.evidence] == [[34, 47], [0, 20]]
    assert proposals.claims[0].value_ref.startswith("sha256:")
    assert proposals.relations[0].predicate == "sources_from"
    assert runtime.get_entity_memory(supplier.entity_id).claims == ()
    assert runtime.get_entity_memory(supplier.entity_id).relations == ()
    history = runtime.get_case_history(case.case_id)
    assert history == (proposals.event,)
    assert history[0].provenance["review_id"] == "review:tea:18"
    assert "Kijani Tea Exporters" not in str(history[0].provenance)

    insufficient = runtime.accept_claim_proposal(
        proposals.claims[0],
        policy=ProposalAcceptancePolicy("tea-evidence-v1"),
        recorded_at=timestamp,
        event_id="event_tea_claim_needs_source",
    )

    assert insufficient.decision == "review"
    assert insufficient.reason == "needs more independent observation sources"
    assert runtime.get_entity_memory(supplier.entity_id).claims == ()

    registry_observation = Observation(
        "obs_tea_registry", "tea_supplier_registry", "supplier-18", timestamp, "sha256:registry"
    )
    registry_evidence = Evidence(
        "ev_tea_registry", registry_observation.observation_id, "registry_name", "claim_proposal"
    )
    runtime.store.write_observations([registry_observation])
    runtime.store.write_evidence([registry_evidence])

    accepted_claim = runtime.accept_claim_proposal(
        proposals.claims[0],
        policy=ProposalAcceptancePolicy("tea-evidence-v2"),
        recorded_at=timestamp,
        supplemental_evidence_ids=(registry_evidence.evidence_id,),
        claim_id="claim_tea_supplier_name",
        event_id="event_tea_claim_accepted",
    )
    accepted_relation = runtime.accept_relation_proposal(
        proposals.relations[0],
        policy=ProposalAcceptancePolicy("tea-evidence-v2"),
        recorded_at=timestamp,
        supplemental_evidence_ids=(registry_evidence.evidence_id,),
        relation_id="rel_tea_supplier_estate",
        event_id="event_tea_relation_accepted",
    )

    assert accepted_claim.decision == "accepted"
    assert accepted_claim.independent_source_ids == ("tea_review_pack", "tea_supplier_registry")
    assert accepted_relation.accepted_record_id == "rel_tea_supplier_estate"
    memory = runtime.get_entity_memory(supplier.entity_id)
    assert memory.claims[0].claim_id == "claim_tea_supplier_name"
    assert memory.relations[0].relation_id == "rel_tea_supplier_estate"


def test_acceptance_routes_a_conflicting_document_claim_to_review(runtime):
    """An unaccepted value cannot create a ledger contradiction by itself."""
    timestamp = datetime(2026, 9, 2, 9, 0, tzinfo=UTC)
    supplier = Entity("ent_conflict_supplier", "organisation", "legal_entity", timestamp)
    input_observation = Observation(
        "obs_conflict_input", "file", "supplier-2", timestamp, "sha256:input"
    )
    case = ResolutionCase(
        "case_conflict_supplier",
        "Which supplier is named?",
        (input_observation.observation_id,),
        (supplier.entity_id,),
        timestamp,
    )
    prior_observation = Observation(
        "obs_prior_registry", "supplier_registry", "supplier-2", timestamp, "sha256:prior"
    )
    prior_evidence = Evidence(
        "ev_prior_registry", prior_observation.observation_id, "registry_name", "supports"
    )
    prior_claim = Claim(
        "claim_prior_supplier_name",
        supplier.entity_id,
        "display_name",
        "sha256:prior-name",
        (prior_evidence.evidence_id,),
        timestamp,
    )
    parsed = ParsedDocument(
        source="conflicting-supplier.pdf",
        text="Supplier: Different Tea Exporters",
        provenance={"text_sha256": "f" * 64, "parser": "docling"},
    )
    extraction = Extraction(
        data=None,
        fields={"supplier_name": FieldEvidence("Different Tea Exporters", span=(10, 32))},
        document=parsed.source,
    )
    corroborating_observation = Observation(
        "obs_conflict_registry", "second_registry", "supplier-2", timestamp, "sha256:second"
    )
    corroborating_evidence = Evidence(
        "ev_conflict_registry",
        corroborating_observation.observation_id,
        "registry_name",
        "claim_proposal",
    )
    runtime.store.write_entities([supplier])
    runtime.store.write_observations(
        [input_observation, prior_observation, corroborating_observation]
    )
    runtime.store.write_evidence([prior_evidence, corroborating_evidence])
    runtime.store.write_claims([prior_claim])
    runtime.store.write_resolution_cases([case])
    proposals = runtime.record_reviewed_document_proposals(
        case.case_id,
        parsed,
        extraction,
        observation_id="obs_conflicting_document",
        source_id="reviewed_file",
        recorded_at=timestamp,
        review_id="review:supplier:2",
        claim_specs=(DocumentClaimSpec(supplier.entity_id, "display_name", "supplier_name"),),
    )

    outcome = runtime.accept_claim_proposal(
        proposals.claims[0],
        policy=ProposalAcceptancePolicy("supplier-policy-v1"),
        recorded_at=timestamp,
        supplemental_evidence_ids=(corroborating_evidence.evidence_id,),
        event_id="event_conflicting_supplier_review",
    )

    assert outcome.decision == "review"
    assert outcome.conflicting_record_ids == (prior_claim.claim_id,)
    assert runtime.get_entity_memory(supplier.entity_id).claims == (prior_claim,)
    event = next(
        item
        for item in runtime.get_case_history(case.case_id)
        if item.event_id == "event_conflicting_supplier_review"
    )
    assert event.provenance["conflicting_record_ids"] == [prior_claim.claim_id]


def test_document_proposal_requires_an_existing_entity_and_review_reference(runtime):
    """A document cannot propose an unreviewed belief about an unknown entity."""
    timestamp = datetime(2026, 9, 2, 9, 0, tzinfo=UTC)
    input_observation = Observation(
        "obs_document_proposal_input", "file", "supplier-1", timestamp, "sha256:input"
    )
    case = ResolutionCase(
        "case_document_proposal",
        "Which supplier is named?",
        (input_observation.observation_id,),
        (),
        timestamp,
    )
    parsed = ParsedDocument(
        source="supplier.pdf",
        text="Supplier: Kijani Tea Exporters",
        provenance={"text_sha256": "e" * 64, "parser": "docling"},
    )
    extraction = Extraction(
        data=None,
        fields={"supplier_name": FieldEvidence("Kijani Tea Exporters", span=(10, 30))},
        document=parsed.source,
    )
    runtime.store.write_observations([input_observation])
    runtime.store.write_resolution_cases([case])

    with pytest.raises(ValueError, match="review_id"):
        runtime.record_reviewed_document_proposals(
            case.case_id,
            parsed,
            extraction,
            observation_id="obs_missing_review",
            source_id="file",
            recorded_at=timestamp,
            review_id="",
        )
    with pytest.raises(ValueError, match="proposal entity"):
        runtime.record_reviewed_document_proposals(
            case.case_id,
            parsed,
            extraction,
            observation_id="obs_unknown_entity",
            source_id="file",
            recorded_at=timestamp,
            review_id="review:supplier:1",
            claim_specs=(DocumentClaimSpec("ent_missing", "display_name", "supplier_name"),),
        )
    assert runtime.store.get_observation("obs_unknown_entity") is None


def test_runtime_persists_resolution_run_metrics(runtime):
    """Run metrics distinguish unsurfaced candidates from negative conclusions."""
    run = ResolutionRun(
        "run_01",
        "arche.resolve.reconcile",
        datetime(2026, 9, 2, 9, 0, tzinfo=UTC),
        candidate_pairs=10,
        emitted_decisions=3,
        match_count=1,
        review_count=2,
        unsurfaced_pairs=7,
        provenance={"blocking": {"candidate_pairs": 10}},
    )

    runtime.store.write_resolution_runs([run])

    assert runtime.store.get_resolution_run(run.run_id) == run


def test_case_permits_an_action_result_only_as_an_observation(runtime):
    """A permitted evidence action gains no direct authority over identity."""
    timestamp = datetime(2026, 9, 2, 9, 0, tzinfo=UTC)
    input_observation = Observation(
        "obs_case_input", "supplier_file", "supplier-7", timestamp, "sha256:input"
    )
    case = ResolutionCase(
        new_resolution_case_id(),
        "Does this supplier match an existing legal entity?",
        (input_observation.observation_id,),
        ("ent_supplier_01",),
        timestamp,
        uncertainty={"reason": "registration number absent"},
        evidence_gaps=(
            EvidenceGap("registration_id", "separates the two candidates", priority=1),
            EvidenceGap("address", "would corroborate the registry result", priority=2),
        ),
    )
    action = EvidenceAction(
        new_evidence_action_id(),
        case.case_id,
        "registry_lookup",
        "supplier_registry",
        timestamp,
        "supplier-policy-v1",
        max_cost=0.02,
    )
    output_observation = Observation(
        "obs_registry_result",
        "supplier_registry",
        "supplier-7",
        timestamp,
        "sha256:registry-result",
    )

    runtime.store.write_observations([input_observation])
    runtime.store.write_resolution_cases([case])
    runtime.store.write_evidence_actions([action])
    link = runtime.ingest_action_observation(action.action_id, output_observation)

    assert runtime.store.get_resolution_case(case.case_id) == case
    assert runtime.store.get_evidence_action(action.action_id) == action
    assert runtime.store.get_observation(output_observation.observation_id) == output_observation
    assert runtime.store.get_action_observation(action.action_id) == link


def test_case_evidence_gaps_are_deterministic_and_persisted(runtime):
    """Case gaps give a planner-free explanation of the next useful evidence."""
    timestamp = datetime(2026, 9, 2, 9, 0, tzinfo=UTC)
    observation = Observation("obs_gap", "file", "r-1", timestamp, "sha256:gap")
    case = ResolutionCase(
        "case_gap",
        "Which entity is this?",
        (observation.observation_id,),
        (),
        timestamp,
        evidence_gaps=(
            EvidenceGap("address", "breaks the tie", priority=2),
            EvidenceGap("registration_id", "breaks the tie", priority=1),
        ),
    )
    runtime.store.write_observations([observation])
    runtime.store.write_resolution_cases([case])

    assert [gap.field for gap in what_would_resolve(case)] == [
        "registration_id",
        "address",
    ]
    assert runtime.store.get_resolution_case(case.case_id) == case


def test_read_only_connector_can_only_return_a_permitted_observation(runtime):
    """Connector execution is constrained by source, action type, and policy pin."""
    timestamp = datetime(2026, 9, 2, 9, 0, tzinfo=UTC)
    input_observation = Observation("obs_connector_input", "file", "r-1", timestamp, "sha256:input")
    case = ResolutionCase(
        "case_connector",
        "Which entity is this?",
        (input_observation.observation_id,),
        (),
        timestamp,
    )
    action = EvidenceAction(
        "act_connector",
        case.case_id,
        "registry_lookup",
        "registry",
        timestamp,
        "policy-v1",
    )
    output_observation = Observation(
        "obs_connector_output", "registry", "r-1", timestamp, "sha256:output"
    )

    class RegistryConnector:
        capability = ToolCapability("registry", ("registry_lookup",), "policy-v1")

        def observe(self, requested_action):
            assert requested_action == action
            return output_observation

    runtime.store.write_observations([input_observation])
    runtime.store.write_resolution_cases([case])
    runtime.store.write_evidence_actions([action])
    link = runtime.execute_evidence_action(action.action_id, RegistryConnector())

    assert link.observation_id == output_observation.observation_id
    assert runtime.store.get_action_observation(action.action_id) == link


def test_connector_capability_cannot_broaden_a_permitted_action(runtime):
    """A connector with a different policy pin cannot execute the action."""
    timestamp = datetime(2026, 9, 2, 9, 0, tzinfo=UTC)
    input_observation = Observation("obs_policy_input", "file", "r-1", timestamp, "sha256:input")
    case = ResolutionCase(
        "case_policy",
        "Which entity is this?",
        (input_observation.observation_id,),
        (),
        timestamp,
    )
    action = EvidenceAction(
        "act_policy",
        case.case_id,
        "registry_lookup",
        "registry",
        timestamp,
        "policy-v1",
    )

    class WrongPolicyConnector:
        capability = ToolCapability("registry", ("registry_lookup",), "policy-v2")

        def observe(self, requested_action):
            raise AssertionError(f"connector should not execute {requested_action.action_id}")

    runtime.store.write_observations([input_observation])
    runtime.store.write_resolution_cases([case])
    runtime.store.write_evidence_actions([action])

    with pytest.raises(ValueError, match="does not permit"):
        runtime.execute_evidence_action(action.action_id, WrongPolicyConnector())


def test_planner_assesses_before_selecting_permitted_costed_actions(runtime):
    """Planning exposes its understanding and never executes an action itself."""
    timestamp = datetime(2026, 9, 2, 9, 0, tzinfo=UTC)
    observation = Observation("obs_plan", "file", "r-1", timestamp, "sha256:plan")
    case = ResolutionCase(
        "case_plan",
        "Which legal entity best explains this supplier record?",
        (observation.observation_id,),
        ("ent_supplier_a", "ent_supplier_b"),
        timestamp,
        evidence_gaps=(
            EvidenceGap(
                "registration_id",
                "separates the two legal entities",
                priority=1,
                permitted_action_types=("registry_lookup",),
            ),
            EvidenceGap(
                "address",
                "corroborates the registry result",
                priority=2,
                permitted_action_types=("address_lookup",),
            ),
        ),
    )
    registry_action = EvidenceAction(
        "act_registry",
        case.case_id,
        "registry_lookup",
        "registry",
        timestamp,
        "policy-v1",
        max_cost=0.20,
    )
    address_action = EvidenceAction(
        "act_address",
        case.case_id,
        "address_lookup",
        "address_book",
        timestamp,
        "policy-v1",
        max_cost=0.05,
    )
    capabilities = (
        ToolCapability("registry", ("registry_lookup",), "policy-v1"),
        ToolCapability("address_book", ("address_lookup",), "policy-v1"),
    )
    runtime.store.write_observations([observation])
    runtime.store.write_resolution_cases([case])
    runtime.store.write_evidence_actions([registry_action, address_action])

    plan = runtime.plan_case(
        case.case_id,
        capabilities=capabilities,
        budget=ResolutionBudget(max_actions=1, max_cost=0.25),
    )

    assert plan.assessment.question == case.question
    assert plan.assessment.candidate_entity_ids == case.candidate_entity_ids
    assert plan.assessment.eligible_action_ids == ("act_address", "act_registry")
    assert [(item.action_id, item.gap_field) for item in plan.actions] == [
        ("act_registry", "registration_id")
    ]
    assert plan.total_estimated_cost == pytest.approx(0.20)
    assert plan.unresolved_gap_fields == ("address",)
    assert runtime.store.get_action_observation(registry_action.action_id) is None

    event = runtime.record_case_plan(
        plan,
        recorded_at=timestamp,
        event_id="event_supplier_plan",
    )

    assert event.references == (registry_action.action_id,)
    assert event.provenance["unresolved_gap_fields"] == ["address"]
    assert runtime.get_case_history(case.case_id) == (event,)


def test_planner_refuses_actions_without_matching_capability_or_budget(runtime):
    """An unavailable or unpriced action stays visible but cannot be scheduled."""
    timestamp = datetime(2026, 9, 2, 9, 0, tzinfo=UTC)
    observation = Observation("obs_refuse", "file", "r-1", timestamp, "sha256:refuse")
    case = ResolutionCase(
        "case_refuse",
        "Which entity is this?",
        (observation.observation_id,),
        (),
        timestamp,
        evidence_gaps=(
            EvidenceGap(
                "registration_id",
                "needed to decide",
                permitted_action_types=("registry_lookup",),
            ),
        ),
    )
    action = EvidenceAction(
        "act_unavailable",
        case.case_id,
        "registry_lookup",
        "registry",
        timestamp,
        "policy-v1",
        max_cost=0.30,
    )
    runtime.store.write_observations([observation])
    runtime.store.write_resolution_cases([case])
    runtime.store.write_evidence_actions([action])

    plan = runtime.plan_case(
        case.case_id,
        capabilities=(ToolCapability("registry", ("registry_lookup",), "policy-v2"),),
        budget=ResolutionBudget(max_actions=1, max_cost=1.0),
    )

    assert plan.actions == ()
    assert plan.assessment.eligible_action_ids == ()
    assert plan.assessment.unavailable_action_ids == (action.action_id,)
    assert plan.unresolved_gap_fields == ("registration_id",)


def test_planner_reasons_about_configured_resolver_methods_before_execution(runtime):
    """Method choice is explicit, scale-aware, and remains a non-executing plan."""
    timestamp = datetime(2026, 9, 3, 9, 0, tzinfo=UTC)
    observation = Observation("obs_method_plan", "file", "supplier-7", timestamp, "sha256:plan")
    intent = ResolutionIntent(
        "organisation",
        "reconcile",
        ("name", "registration_id"),
        "supplier-policy-v1",
        candidate_pairs=250_000,
    )
    case = ResolutionCase(
        "case_method_plan",
        "Which legal entities represent this supplier ledger?",
        (observation.observation_id,),
        (),
        timestamp,
        evidence_gaps=(
            EvidenceGap(
                "registration_id",
                "confirms a proposed supplier match",
                permitted_action_types=("registry_lookup",),
            ),
        ),
        intent=intent,
    )
    action = EvidenceAction(
        "act_method_registry",
        case.case_id,
        "registry_lookup",
        "supplier_registry",
        timestamp,
        "supplier-policy-v1",
        max_cost=0.20,
    )
    methods = (
        ResolutionMethod(
            "arche_small",
            "arche.resolve.reconcile",
            ("organisation",),
            ("reconcile",),
            "supplier-policy-v1",
            "arche.resolve.reconcile@crosswalk.v1",
            required_fields=("name",),
            max_candidate_pairs=100_000,
            estimated_cost=0.02,
        ),
        ResolutionMethod(
            "splink_supplier",
            "splink",
            ("organisation",),
            ("reconcile",),
            "supplier-policy-v1",
            "splink-settings@sha256:approved",
            required_fields=("name", "registration_id"),
            estimated_cost=0.15,
            priority=1,
        ),
        ResolutionMethod(
            "person_pairwise",
            "arche.resolve.compare",
            ("person",),
            ("compare",),
            "supplier-policy-v1",
            "arche.resolve.compare@coreference.v1",
        ),
    )
    runtime.store.write_observations([observation])
    runtime.store.write_resolution_cases([case])
    runtime.store.write_evidence_actions([action])

    plan = runtime.plan_case(
        case.case_id,
        capabilities=(
            ToolCapability("supplier_registry", ("registry_lookup",), "supplier-policy-v1"),
        ),
        budget=ResolutionBudget(max_actions=1, max_cost=0.40),
        methods=methods,
    )

    assert runtime.store.get_resolution_case(case.case_id).intent == intent
    assert [(item.method_id, item.eligible) for item in plan.assessment.method_assessments] == [
        ("arche_small", False),
        ("splink_supplier", True),
        ("person_pairwise", False),
    ]
    assert [item.reason for item in plan.assessment.method_assessments] == [
        "candidate-pair scale exceeds method limit",
        "matches the case intent and configured limits",
        "does not support the requested operation",
    ]
    assert [(item.action_id, item.gap_field) for item in plan.actions] == [
        ("act_method_registry", "registration_id"),
    ]
    assert [(item.method_id, item.configuration_pin) for item in plan.methods] == [
        ("splink_supplier", "splink-settings@sha256:approved"),
    ]
    assert plan.total_estimated_cost == pytest.approx(0.35)

    event = runtime.record_case_plan(plan, recorded_at=timestamp)

    assert event.provenance["planned_method_ids"] == ["splink_supplier"]
    assert runtime.store.get_resolution_run("run_not_executed") is None


def test_resolution_intent_requires_field_name_sequence_and_numeric_pair_count():
    """Intent requires a field-name sequence and an integer candidate-pair scale."""
    with pytest.raises(ValueError, match="available_fields"):
        ResolutionIntent("organisation", "reconcile", "name", "supplier-policy-v1")
    with pytest.raises(ValueError, match="candidate_pairs"):
        ResolutionIntent("organisation", "reconcile", ("name",), "supplier-policy-v1", True)


def test_case_reconcile_result_requires_persisted_evidence(runtime):
    """Case re-resolution records normal resolver receipts only after evidence exists."""
    timestamp = datetime(2026, 9, 2, 9, 0, tzinfo=UTC)
    observation = Observation("obs_reresolve", "registry", "r-1", timestamp, "sha256:result")
    case = ResolutionCase(
        "case_reresolve",
        "Which entity is this?",
        (observation.observation_id,),
        (),
        timestamp,
    )
    evidence = Evidence("ev_reresolve", observation.observation_id, "registry_id", "supports")
    result = {
        "matches": [{"decision_id": "xwd:case", "decision": "match", "score": 0.99}],
        "pins": {"engine": "crosswalk.v1"},
        "blocking": {"candidate_pairs": 1},
    }
    runtime.store.write_observations([observation])
    runtime.store.write_resolution_cases([case])
    runtime.store.write_evidence([evidence])

    run, receipts = runtime.record_case_reconcile_result(
        case.case_id,
        result,
        run_id="run_case",
        created_at=timestamp,
        evidence_ids_by_decision={"xwd:case": (evidence.evidence_id,)},
    )

    assert run.provenance["resolution_case_id"] == case.case_id
    assert receipts[0].evidence_ids == (evidence.evidence_id,)
    assert runtime.store.get_resolution_run(run.run_id) == run
    assert runtime.store.get_decision(receipts[0].decision_id) == receipts[0]


def test_evidence_and_receipts_require_their_prior_provenance(runtime):
    """The store rejects a direct skip from a tool-like result to a decision."""
    timestamp = datetime(2026, 9, 2, 9, 0, tzinfo=UTC)
    evidence = Evidence("ev_missing", "obs_missing", "registry_id", "supports")
    receipt = DecisionReceipt(
        "dec_missing",
        "same_entity",
        "link",
        (evidence.evidence_id,),
        timestamp,
    )

    with pytest.raises(ValueError, match="persist an Observation"):
        runtime.store.write_evidence([evidence])
    with pytest.raises(ValueError, match="persist Evidence"):
        runtime.store.write_decisions([receipt])


def test_decision_policy_releases_only_evidence_backed_case_receipts(runtime):
    """A policy outcome guides work without mutating canonical entity memory."""
    timestamp = datetime(2026, 9, 3, 9, 0, tzinfo=UTC)
    input_observation = Observation("obs_decision_input", "file", "r-1", timestamp, "sha256:input")
    registry_observation = Observation(
        "obs_decision_registry", "registry", "r-1", timestamp, "sha256:registry"
    )
    case = ResolutionCase(
        "case_decision_policy",
        "Does this supplier reference identify the registered entity?",
        (input_observation.observation_id,),
        (),
        timestamp,
    )
    evidence = (
        Evidence(
            "ev_decision_input",
            input_observation.observation_id,
            "name",
            "supports",
        ),
        Evidence(
            "ev_decision_registry",
            registry_observation.observation_id,
            "registration_id",
            "supports",
        ),
    )
    result = {
        "matches": [{"decision_id": "xwd:release", "decision": "match", "score": 0.99}],
        "pins": {"engine": "crosswalk.v1"},
        "blocking": {"candidate_pairs": 1},
    }
    runtime.store.write_observations([input_observation, registry_observation])
    runtime.store.write_resolution_cases([case])
    runtime.store.write_evidence(evidence)
    runtime.record_case_reconcile_result(
        case.case_id,
        result,
        run_id="run_decision_policy",
        created_at=timestamp,
        evidence_ids_by_decision={"xwd:release": tuple(item.evidence_id for item in evidence)},
    )

    outcome = runtime.apply_resolution_decision_policy(
        case.case_id,
        "xwd:release",
        policy=ResolutionDecisionPolicy("supplier-link-v1"),
        recorded_at=timestamp,
    )

    assert outcome.action == "link"
    assert outcome.independent_source_ids == ("file", "registry")
    assert {event.event_type for event in runtime.get_case_history(case.case_id)} == {
        "resolver_decision",
        "policy_decision",
    }
    assert runtime.store.get_entity("ent_not_created") is None
    with pytest.raises(ValueError, match="already decided"):
        runtime.apply_resolution_decision_policy(
            case.case_id,
            "xwd:release",
            policy=ResolutionDecisionPolicy("supplier-link-v1"),
            recorded_at=timestamp,
        )


def test_decision_policy_reviews_weak_positive_and_abstains_on_unsupported_negative(runtime):
    """Missing evidence cannot silently create either a merge or a rejection."""
    timestamp = datetime(2026, 9, 3, 9, 0, tzinfo=UTC)
    observation = Observation("obs_policy", "file", "r-1", timestamp, "sha256:input")
    evidence = Evidence("ev_policy", observation.observation_id, "name", "supports")
    case = ResolutionCase(
        "case_policy", "Which record is this?", (observation.observation_id,), (), timestamp
    )
    runtime.store.write_observations([observation])
    runtime.store.write_resolution_cases([case])
    runtime.store.write_evidence([evidence])

    runtime.record_case_reconcile_result(
        case.case_id,
        {
            "matches": [
                {"decision_id": "xwd:weak", "decision": "match", "score": 0.99},
                {"decision_id": "xwd:negative", "decision": "no_match", "score": 0.01},
            ],
            "pins": {"engine": "crosswalk.v1"},
            "blocking": {"candidate_pairs": 2},
        },
        run_id="run_policy_outcomes",
        created_at=timestamp,
        evidence_ids_by_decision={"xwd:weak": (evidence.evidence_id,)},
    )
    policy = ResolutionDecisionPolicy("supplier-link-v1")

    weak = runtime.apply_resolution_decision_policy(
        case.case_id, "xwd:weak", policy=policy, recorded_at=timestamp
    )
    negative = runtime.apply_resolution_decision_policy(
        case.case_id, "xwd:negative", policy=policy, recorded_at=timestamp
    )

    assert (weak.action, negative.action) == ("review", "abstain")


def test_entity_memory_recovers_claims_conflicts_relations_and_case_history(runtime):
    """A supplier ledger survives outside the resolver call that created it."""
    timestamp = datetime(2026, 9, 2, 9, 0, tzinfo=UTC)
    supplier = Entity("ent_supplier", "organisation", "legal_entity", timestamp)
    parent = Entity("ent_parent", "organisation", "legal_entity", timestamp)
    observation = Observation(
        "obs_supplier", "registry", "supplier-7", timestamp, "sha256:supplier"
    )
    evidence = Evidence("ev_supplier", observation.observation_id, "registration_id", "supports")
    claim = Claim(
        "claim_registration",
        supplier.entity_id,
        "registration_id",
        "sha256:registration-123",
        (evidence.evidence_id,),
        timestamp,
    )
    conflicting_claim = Claim(
        "claim_registration_conflict",
        supplier.entity_id,
        "registration_id",
        "sha256:registration-999",
        (evidence.evidence_id,),
        timestamp,
        status="contested",
    )
    contradiction = Contradiction(
        "conflict_registration",
        supplier.entity_id,
        (claim.claim_id, conflicting_claim.claim_id),
        "two registry observations report incompatible registrations",
        timestamp,
    )
    relation = EntityRelation(
        "rel_parent",
        supplier.entity_id,
        "subsidiary_of",
        parent.entity_id,
        (evidence.evidence_id,),
        timestamp,
    )
    case = ResolutionCase(
        "case_supplier",
        "Which legal entity owns this supplier record?",
        (observation.observation_id,),
        (supplier.entity_id,),
        timestamp,
    )
    question = OpenQuestion(
        "question_address",
        supplier.entity_id,
        "Which registered address is current?",
        timestamp,
        case_id=case.case_id,
    )
    event = CaseEvent(
        "event_case_opened",
        case.case_id,
        "case_opened",
        timestamp,
        references=(observation.observation_id,),
    )

    runtime.store.write_entities([supplier, parent])
    runtime.store.write_observations([observation])
    runtime.store.write_evidence([evidence])
    runtime.store.write_claims([claim, conflicting_claim])
    runtime.store.write_contradictions([contradiction])
    runtime.store.write_relations([relation])
    runtime.store.write_resolution_cases([case])
    runtime.store.write_open_questions([question])
    runtime.store.write_case_events([event])

    memory = runtime.get_entity_memory(supplier.entity_id)

    assert memory.entity == supplier
    assert memory.claims == (claim, conflicting_claim)
    assert memory.contradictions == (contradiction,)
    assert memory.relations == (relation,)
    assert memory.open_questions == (question,)
    assert runtime.get_case_history(case.case_id) == (event,)


def test_action_result_requires_a_permitted_action_and_matching_source(runtime):
    """Unknown or source-mismatched actions cannot inject case observations."""
    timestamp = datetime(2026, 9, 2, 9, 0, tzinfo=UTC)
    unknown = Observation("obs_unknown", "registry", "r-1", timestamp, "sha256:unknown")

    with pytest.raises(ValueError, match="not permitted"):
        runtime.ingest_action_observation("act_missing", unknown)

    input_observation = Observation("obs_input", "file", "r-1", timestamp, "sha256:input")
    case = ResolutionCase(
        "case_known", "Which entity is this?", (input_observation.observation_id,), (), timestamp
    )
    action = EvidenceAction(
        "act_known", case.case_id, "registry_lookup", "registry", timestamp, "policy-v1"
    )
    mismatched = Observation("obs_mismatch", "other_registry", "r-1", timestamp, "sha256:mismatch")
    runtime.store.write_observations([input_observation])
    runtime.store.write_resolution_cases([case])
    runtime.store.write_evidence_actions([action])

    with pytest.raises(ValueError, match="does not match"):
        runtime.ingest_action_observation(action.action_id, mismatched)

    assert runtime.store.get_observation(unknown.observation_id) is None
    assert runtime.store.get_observation(mismatched.observation_id) is None


def test_coreference_adapter_keeps_existing_decision_identifier_and_pins():
    """The pairwise adapter records a decision instead of recomputing it."""
    from arche import compare

    existing = compare(
        {"name": "Ada Lovelace", "national_id": "NIN-0001"},
        {"name": "Ada Lovelace", "national_id": "NIN-0001"},
    )

    adapted = adapt_coreference_receipt(
        existing,
        created_at=datetime(2026, 9, 2, 9, 0, tzinfo=UTC),
        evidence_ids=("ev_pair_01",),
    )

    assert adapted.decision_id == existing.decision_id
    assert adapted.identity_result == existing.identity
    assert adapted.action == "link"
    assert adapted.raw_score == existing.score
    assert adapted.evidence_ids == ("ev_pair_01",)
    assert adapted.provenance["resolver_pins"] == existing.pins


def test_reconcile_adapter_emits_receipts_and_candidate_cost_metrics():
    """Batch adaptation keeps review work visible without inferring rejections."""
    result = {
        "matches": [
            {
                "a_id": "left-1",
                "b_id": "right-1",
                "score": 0.99,
                "decision": "match",
                "evidence": {"name": 1.0},
                "decision_id": "xwd:match",
            },
            {
                "a_id": "left-2",
                "b_id": "right-2",
                "score": 0.8,
                "decision": "review",
                "evidence": {"name": 0.8},
                "decision_id": "xwd:review",
            },
        ],
        "pins": {"engine": "crosswalk.v1", "threshold": 0.9},
        "blocking": {"candidate_pairs": 5, "reduction_ratio": 0.5},
    }

    run, receipts = adapt_reconcile_result(
        result,
        run_id="run_reconcile_01",
        created_at=datetime(2026, 9, 2, 9, 0, tzinfo=UTC),
        evidence_ids_by_decision={"xwd:match": ("ev_match",)},
    )

    assert [(receipt.identity_result, receipt.action) for receipt in receipts] == [
        ("same_entity", "link"),
        ("review", "review"),
    ]
    assert receipts[0].evidence_ids == ("ev_match",)
    assert run.candidate_pairs == 5
    assert run.emitted_decisions == 2
    assert run.match_count == 1
    assert run.review_count == 1
    assert run.unsurfaced_pairs == 3


def test_reconcile_adapter_accepts_current_resolver_output():
    """The adapter wraps the existing batch resolver without changing its call."""
    from arche.resolve import reconcile

    result = reconcile(
        [{"id": "left-1", "name": "Ada Lovelace"}],
        [{"id": "right-1", "name": "Ada Lovelace"}],
        comparators=[{"field": "name", "kind": "name", "weight": 1.0}],
    )

    run, receipts = adapt_reconcile_result(
        result,
        run_id="run_current_resolver",
        created_at=datetime(2026, 9, 2, 9, 0, tzinfo=UTC),
    )

    assert run.candidate_pairs == result["blocking"]["candidate_pairs"]
    assert [receipt.decision_id for receipt in receipts] == [
        edge["decision_id"] for edge in result["matches"]
    ]


def test_runtime_schema_upgrades_a_pre_provenance_decision_table():
    """Existing M0 stores gain receipt provenance without a destructive reset."""
    from arche.store.duckdb import DuckDBStore

    store = DuckDBStore(":memory:")
    store._connection.execute(
        """
        CREATE TABLE arche_decisions (
            decision_id VARCHAR PRIMARY KEY,
            identity_result VARCHAR NOT NULL,
            action VARCHAR NOT NULL,
            evidence_ids JSON NOT NULL,
            raw_score DOUBLE,
            probability DOUBLE,
            policy_pin VARCHAR,
            schema_pin VARCHAR,
            created_at VARCHAR NOT NULL
        )
        """
    )
    try:
        store.ensure_schema()
        columns = {
            row[1]
            for row in store._connection.execute("PRAGMA table_info('arche_decisions')").fetchall()
        }
        assert "provenance" in columns
    finally:
        store.close()


def test_runtime_schema_upgrades_a_pre_intent_case_table():
    """Existing case stores gain planner intent without a destructive reset."""
    from arche.store.duckdb import DuckDBStore

    store = DuckDBStore(":memory:")
    store._connection.execute(
        """
        CREATE TABLE arche_resolution_cases (
            case_id VARCHAR PRIMARY KEY,
            question VARCHAR NOT NULL,
            observation_ids JSON NOT NULL,
            candidate_entity_ids JSON NOT NULL,
            opened_at VARCHAR NOT NULL,
            status VARCHAR NOT NULL,
            uncertainty JSON NOT NULL,
            evidence_gaps JSON NOT NULL DEFAULT '[]'
        )
        """
    )
    try:
        store.ensure_schema()
        columns = {
            row[1]
            for row in store._connection.execute(
                "PRAGMA table_info('arche_resolution_cases')"
            ).fetchall()
        }
        assert "intent" in columns
    finally:
        store.close()


def test_entity_identity_does_not_change_with_revisable_state(runtime):
    """Entity identity is opaque, not a hash of state that will later change."""
    entity = Entity(
        new_entity_id(),
        "organisation",
        "legal_entity",
        datetime(2026, 9, 2, tzinfo=UTC),
    )
    revised = replace(entity, status="inactive")

    runtime.store.write_entities([entity])

    assert entity.entity_id == revised.entity_id
    assert entity.entity_id.startswith("ent_")
    assert len(entity.entity_id) == len("ent_") + 32


def test_failed_entity_batch_rolls_back_without_a_partial_write(runtime):
    """A duplicate identity cannot leave earlier rows from the same batch behind."""
    import duckdb

    timestamp = datetime(2026, 9, 2, tzinfo=UTC)
    existing = Entity("ent_existing", "organisation", "legal_entity", timestamp)
    new_entity = Entity("ent_new", "organisation", "legal_entity", timestamp)
    runtime.store.write_entities([existing])

    with pytest.raises(duckdb.ConstraintException):
        runtime.store.write_entities([new_entity, existing])

    assert runtime.store.get_entity(new_entity.entity_id) is None


def test_attach_rejects_unknown_store_uri_before_opening_a_connection():
    """Callers receive an actionable error instead of an implicit backend choice."""
    with pytest.raises(ValueError, match="duckdb:///"):
        arche.attach("sqlite:///arche.db")


def test_importing_arche_does_not_eagerly_import_duckdb():
    """The new optional store keeps the existing cold-import boundary intact."""
    result = subprocess.run(
        [sys.executable, "-c", "import sys; import arche; assert 'duckdb' not in sys.modules"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
