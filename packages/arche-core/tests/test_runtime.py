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
    AgentPlanAdvice,
    BenchmarkResultBundle,
    CaseEvent,
    Claim,
    Contradiction,
    DecisionReceipt,
    DoclingDocumentIngestionExecutor,
    DocumentClaimSpec,
    DocumentIngestion,
    DocumentIngestionRequest,
    DocumentRelationSpec,
    DomainResolutionMethodExecutor,
    Entity,
    EntityRelation,
    Evidence,
    EvidenceAction,
    EvidenceGap,
    ExternalEvidenceRequest,
    HttpEvidenceConnector,
    HttpEvidenceResponse,
    Observation,
    OpenQuestion,
    PolicyExecution,
    ProposalAcceptancePolicy,
    ResolutionBudget,
    ResolutionCase,
    ResolutionDecisionPolicy,
    ResolutionIntent,
    ResolutionMethod,
    ResolutionMethodApproval,
    ResolutionMethodExecution,
    ResolutionRun,
    ReviewedResolutionArtifact,
    ReviewedResolutionEdge,
    SplinkResolutionMethodExecutor,
    ToolCapability,
    adapt_coreference_receipt,
    adapt_reconcile_result,
    adapt_reviewed_resolution_artifact,
    benchmark_result_bundle_from_record,
    new_entity_id,
    new_evidence_action_id,
    new_resolution_case_id,
    observation_from_document,
    qualification_from_evaluated_result,
    read_benchmark_result_bundle,
    reviewed_resolution_evidence,
    what_would_resolve,
    write_benchmark_result_bundle,
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


def test_document_ocr_ingestion_action_keeps_scan_provenance_out_of_values(runtime):
    """A caller-owned scan/OCR result is an action Observation before review."""
    timestamp = datetime(2026, 9, 3, 15, 0, tzinfo=UTC)
    input_observation = Observation(
        "obs_document_ingestion_input", "tea-intake", "shipment-19", timestamp, "sha256:intake"
    )
    case = ResolutionCase(
        "case_document_ocr_ingestion",
        "What supplier is reported by this scanned tea shipment document?",
        (input_observation.observation_id,),
        (),
        timestamp,
    )
    action = EvidenceAction(
        "act_document_ocr_ingestion",
        case.case_id,
        "document_ocr",
        "tea_document_service",
        timestamp,
        "tea-pilot-v1",
    )
    ingestion = DocumentIngestion(
        "artifact:sha256:caller-managed",
        text_sha256="a" * 64,
        parser="docling",
        parser_version="2.0",
        ocr=True,
        artifact_sha256="b" * 64,
        page_count=2,
    )
    runtime.store.write_observations([input_observation])
    runtime.store.write_resolution_cases([case])
    runtime.store.write_evidence_actions([action])

    link = runtime.ingest_document_observation(
        action.action_id,
        ingestion,
        observation_id="obs_document_ocr_ingestion",
        recorded_at=timestamp,
    )
    observation = runtime.store.get_observation(link.observation_id)

    assert observation is not None
    assert observation.source_id == action.source_id
    assert observation.content_hash == "sha256:" + "b" * 64
    assert observation.provenance == {
        "kind": "document_ingestion",
        "document": {
            "artifact_sha256": "b" * 64,
            "text_sha256": "a" * 64,
            "parser": "docling",
            "parser_version": "2.0",
            "ocr": True,
            "page_count": 2,
        },
    }
    assert "supplier" not in str(observation.provenance)


def test_docling_executor_enters_a_permitted_document_action_without_text(runtime):
    """Docling/OCR stays caller-owned and emits only hash-pinned ingestion state."""
    timestamp = datetime(2026, 9, 3, 15, 15, tzinfo=UTC)
    input_observation = Observation(
        "obs_docling_executor_input", "tea-intake", "shipment-21", timestamp, "sha256:intake"
    )
    case = ResolutionCase(
        "case_docling_executor",
        "What supplier is reported by this scanned tea document?",
        (input_observation.observation_id,),
        (),
        timestamp,
    )
    action = EvidenceAction(
        "act_docling_executor",
        case.case_id,
        "document_ocr",
        "tea_document_service",
        timestamp,
        "tea-pilot-v1",
    )
    parsed = ParsedDocument(
        source="private-invoice.pdf",
        text="This text must not enter runtime provenance.",
        num_pages=1,
        provenance={
            "artifact_sha256": "c" * 64,
            "text_sha256": "d" * 64,
            "parser": "docling",
            "parser_version": "2.0",
            "ocr": True,
        },
    )
    executor = DoclingDocumentIngestionExecutor(
        parse_document=lambda source, do_ocr: parsed,
    )
    runtime.store.write_observations([input_observation])
    runtime.store.write_resolution_cases([case])
    runtime.store.write_evidence_actions([action])

    link = runtime.execute_document_ingestion_action(
        action.action_id,
        DocumentIngestionRequest("private-invoice.pdf", "artifact:private-21", do_ocr=True),
        executor,
        observation_id="obs_docling_executor",
        recorded_at=timestamp,
    )
    observation = runtime.store.get_observation(link.observation_id)

    assert observation is not None
    assert observation.source_record_id == "artifact:private-21"
    assert observation.provenance["document"]["ocr"] is True
    assert "This text" not in str(observation.provenance)


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


def test_reuses_reviewed_action_evidence_for_tea_proposals(runtime):
    """A semantic mapping must reuse the exact reviewed document Evidence."""
    timestamp = datetime(2026, 9, 3, 9, 0, tzinfo=UTC)
    supplier = Entity("ent_reuse_supplier", "organisation", "legal_entity", timestamp)
    distributor = Entity("ent_reuse_distributor", "organisation", "legal_entity", timestamp)
    estate = Entity("ent_reuse_estate", "place", "estate", timestamp)
    case = ResolutionCase(
        "case_reuse_tea_evidence", "Which tea organisations are reported?", (), (), timestamp
    )
    action = EvidenceAction(
        "act_reuse_tea_document",
        case.case_id,
        "document_extract",
        "local-document",
        timestamp,
        "tea-document-v1",
    )
    observation = Observation(
        "obs_reuse_tea_document",
        action.source_id,
        "document:fixture",
        timestamp,
        "sha256:document",
        provenance={"kind": "document_ingestion", "outcome": "success"},
    )
    extraction = Extraction(
        data=None,
        fields={
            "supplier_name": FieldEvidence("Kijani Tea Exporters", span=(0, 20)),
            "distributor_name": FieldEvidence("Nairobi Tea Trading", span=(32, 52)),
            "estate_name": FieldEvidence("Kericho Estate", span=(67, 81)),
        },
    )
    runtime.store.write_entities([supplier, distributor, estate])
    runtime.store.write_resolution_cases([case])
    runtime.store.write_evidence_actions([action])
    runtime.ingest_action_observation(action.action_id, observation)
    evidence, _ = runtime.record_reviewed_document_evidence(
        case.case_id,
        action.action_id,
        extraction,
        review_id="review:reuse:tea",
        recorded_at=timestamp,
    )

    proposals = runtime.record_reviewed_document_field_proposals(
        case.case_id,
        action.action_id,
        extraction,
        review_id="review:reuse:tea",
        recorded_at=timestamp,
        claim_specs=(DocumentClaimSpec(supplier.entity_id, "reported_supplier", "supplier_name"),),
        relation_specs=(
            DocumentRelationSpec(
                supplier.entity_id,
                "reported_distributor",
                distributor.entity_id,
                ("supplier_name", "distributor_name"),
            ),
            DocumentRelationSpec(
                supplier.entity_id,
                "reported_operates",
                estate.entity_id,
                ("supplier_name", "estate_name"),
            ),
        ),
    )

    assert proposals.evidence == evidence
    assert [item.predicate for item in proposals.relations] == [
        "reported_distributor",
        "reported_operates",
    ]
    assert runtime.get_entity_memory(supplier.entity_id).claims == ()
    changed = Extraction(
        data=None,
        fields={
            **extraction.fields,
            "supplier_name": FieldEvidence("Different Supplier", span=(0, 20)),
        },
    )
    with pytest.raises(ValueError, match="missing or differs"):
        runtime.record_reviewed_document_field_proposals(
            case.case_id,
            action.action_id,
            changed,
            review_id="review:reuse:tea",
            recorded_at=timestamp,
        )


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


def test_https_connector_records_hashed_external_results_and_terminal_failures(runtime):
    """External source values never enter durable provenance, including failures."""
    timestamp = datetime(2026, 9, 3, 10, 0, tzinfo=UTC)
    input_observation = Observation("obs_external_input", "file", "r-1", timestamp, "sha256:input")
    case = ResolutionCase(
        "case_external_connector",
        "Which supplier is this?",
        (input_observation.observation_id,),
        (),
        timestamp,
    )
    success, rate_limited, cost_limited = (
        EvidenceAction(
            "act_external_success",
            case.case_id,
            "registry_lookup",
            "registry",
            timestamp,
            "policy-v1",
            0.10,
        ),
        EvidenceAction(
            "act_external_rate",
            case.case_id,
            "registry_lookup",
            "registry",
            timestamp,
            "policy-v1",
            0.10,
        ),
        EvidenceAction(
            "act_external_cost",
            case.case_id,
            "registry_lookup",
            "registry",
            timestamp,
            "policy-v1",
            0.01,
        ),
    )
    requested_urls: list[str] = []

    def fetch(url: str, timeout: float) -> HttpEvidenceResponse:
        requested_urls.append(url)
        assert timeout == 5.0
        return HttpEvidenceResponse(200, b'{"supplier":"example"}')

    connector = HttpEvidenceConnector(
        ToolCapability("registry", ("registry_lookup",), "policy-v1"),
        "https://registry.example/v1",
        lambda action: ExternalEvidenceRequest(
            "/suppliers", (("query", "private supplier value"),)
        ),
        estimated_cost=0.05,
        max_requests=1,
        window_seconds=60.0,
        timeout_seconds=5.0,
        fetch=fetch,
        clock=lambda: 100.0,
        recorded_at=lambda: timestamp,
    )
    runtime.store.write_observations([input_observation])
    runtime.store.write_resolution_cases([case])
    runtime.store.write_evidence_actions([success, rate_limited, cost_limited])

    success_link = runtime.execute_evidence_action(success.action_id, connector)
    rate_link = runtime.execute_evidence_action(rate_limited.action_id, connector)
    cost_link = runtime.execute_evidence_action(cost_limited.action_id, connector)
    success_observation = runtime.store.get_observation(success_link.observation_id)
    rate_observation = runtime.store.get_observation(rate_link.observation_id)
    cost_observation = runtime.store.get_observation(cost_link.observation_id)

    assert requested_urls == ["https://registry.example/v1/suppliers?query=private+supplier+value"]
    assert success_observation is not None
    assert success_observation.provenance["outcome"] == "success"
    assert success_observation.provenance["response_status"] == 200
    assert "private supplier value" not in str(success_observation.provenance)
    assert rate_observation is not None
    assert rate_observation.provenance["failure_reason"] == "rate_limit"
    assert cost_observation is not None
    assert cost_observation.provenance["failure_reason"] == "cost_limit"
    with pytest.raises(ValueError, match="already has an Observation"):
        runtime.execute_evidence_action(success.action_id, connector)


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
    assert event.provenance["planned_methods"] == [
        {
            "method_id": "splink_supplier",
            "resolver": "splink",
            "policy_pin": "supplier-policy-v1",
            "configuration_pin": "splink-settings@sha256:approved",
            "estimated_cost": 0.15,
        }
    ]

    selected_method = methods[1]
    approval = ResolutionMethodApproval(
        "approval_splink_supplier",
        case.case_id,
        event.event_id,
        selected_method.method_id,
        selected_method.configuration_pin,
        "supplier-reviewer",
        max_cost=0.15,
    )
    approval_event = runtime.approve_planned_resolution_method(
        approval, selected_method, recorded_at=timestamp
    )

    class SplinkExecutor:
        def __init__(self):
            self.calls = []

        def execute(self, requested_case, requested_method):
            self.calls.append((requested_case, requested_method))
            return ResolutionMethodExecution(
                "exec_splink_supplier",
                requested_method.method_id,
                requested_method.configuration_pin,
                "success",
                "sha256:splink-result",
                actual_cost=0.14,
            )

    executor = SplinkExecutor()
    method_observation = runtime.execute_approved_resolution_method(
        case.case_id,
        approval.approval_id,
        selected_method,
        executor,
        recorded_at=timestamp,
    )

    assert approval_event.references == (event.event_id, selected_method.method_id)
    assert executor.calls == [(case, selected_method)]
    assert method_observation.source_id == "resolver:splink"
    assert method_observation.provenance["outcome"] == "success"
    assert runtime.store.get_decision("dec_not_created") is None
    with pytest.raises(ValueError, match="already has an execution Observation"):
        runtime.execute_approved_resolution_method(
            case.case_id,
            approval.approval_id,
            selected_method,
            executor,
            recorded_at=timestamp,
        )

    overrun_approval = ResolutionMethodApproval(
        "approval_splink_overrun",
        case.case_id,
        event.event_id,
        selected_method.method_id,
        selected_method.configuration_pin,
        "supplier-reviewer",
        max_cost=0.15,
    )
    runtime.approve_planned_resolution_method(
        overrun_approval, selected_method, recorded_at=timestamp
    )

    class CostOverrunExecutor:
        def execute(self, requested_case, requested_method):
            return ResolutionMethodExecution(
                "exec_splink_overrun",
                requested_method.method_id,
                requested_method.configuration_pin,
                "success",
                "sha256:splink-overrun-result",
                actual_cost=0.16,
            )

    overrun_observation = runtime.execute_approved_resolution_method(
        case.case_id,
        overrun_approval.approval_id,
        selected_method,
        CostOverrunExecutor(),
        recorded_at=timestamp,
    )

    assert overrun_observation.provenance["outcome"] == "failure"
    assert overrun_observation.provenance["failure_reason"] == "cost_limit"

    failed_approval = ResolutionMethodApproval(
        "approval_splink_failure",
        case.case_id,
        event.event_id,
        selected_method.method_id,
        selected_method.configuration_pin,
        "supplier-reviewer",
        max_cost=0.15,
    )
    runtime.approve_planned_resolution_method(
        failed_approval, selected_method, recorded_at=timestamp
    )

    class FailingExecutor:
        def execute(self, requested_case, requested_method):
            raise RuntimeError("adapter unavailable")

    failed_observation = runtime.execute_approved_resolution_method(
        case.case_id,
        failed_approval.approval_id,
        selected_method,
        FailingExecutor(),
        recorded_at=timestamp,
    )

    assert failed_observation.provenance["outcome"] == "failure"
    assert failed_observation.provenance["failure_reason"] == "executor_failed"
    assert runtime.store.get_resolution_run("run_not_executed") is None


def test_planner_requires_a_pinned_qualified_benchmark_for_splink_or_domain_methods(runtime):
    """Optional non-core runners remain unavailable until exact evaluation is supplied."""
    timestamp = datetime(2026, 9, 3, 16, 30, tzinfo=UTC)
    observation = Observation(
        "obs_benchmark_gate", "file", "supplier-22", timestamp, "sha256:input"
    )
    intent = ResolutionIntent(
        "organisation", "reconcile", ("name", "registration_id"), "tea-policy-v1", 100
    )
    case = ResolutionCase(
        "case_benchmark_gate",
        "Which supplier is represented by these records?",
        (observation.observation_id,),
        (),
        timestamp,
        intent=intent,
    )
    method = ResolutionMethod(
        "splink_supplier_benchmarked",
        "splink",
        ("organisation",),
        ("reconcile",),
        "tea-policy-v1",
        "splink-settings@sha256:tea-v1",
        required_fields=("name", "registration_id"),
        estimated_cost=0.10,
        benchmark_id="leipzig-abt-buy-v1",
    )
    runtime.store.write_observations([observation])
    runtime.store.write_resolution_cases([case])

    unqualified = runtime.plan_case(
        case.case_id,
        capabilities=(),
        budget=ResolutionBudget(max_actions=0, max_cost=0.20),
        methods=(method,),
    )
    bundle = BenchmarkResultBundle(
        "bundle_splink_abt_buy",
        method.method_id,
        method.resolver,
        method.configuration_pin,
        "leipzig-abt-buy-v1",
        "leipzig-abt-buy",
        "benchmark-runner@v1",
        timestamp,
        "complete",
        candidate_pairs=20,
        auto_match_count=10,
        review_count=4,
        true_pair_count=12,
        blocking_true_pair_count=12,
        true_positive_count=9,
        false_positive_count=1,
        reviewed_true_pair_count=3,
    )
    qualification = qualification_from_evaluated_result(
        bundle,
        qualification_id="qualification_splink_abt_buy",
        qualification_policy_pin="benchmark-acceptance@v1",
        qualified=True,
    )
    mismatched = runtime.plan_case(
        case.case_id,
        capabilities=(),
        budget=ResolutionBudget(max_actions=0, max_cost=0.20),
        methods=(method,),
        benchmark_qualifications=(
            replace(qualification, configuration_pin="splink-settings@sha256:other"),
        ),
    )
    qualified = runtime.plan_case(
        case.case_id,
        capabilities=(),
        budget=ResolutionBudget(max_actions=0, max_cost=0.20),
        methods=(method,),
        benchmark_qualifications=(qualification,),
    )
    event = runtime.record_case_plan(qualified, recorded_at=timestamp)

    assert unqualified.assessment.method_assessments[0].reason == (
        "requires qualified benchmark leipzig-abt-buy-v1"
    )
    assert unqualified.methods == ()
    assert mismatched.methods == ()
    assert qualified.methods[0].benchmark_qualification_id == qualification.qualification_id
    assert (
        event.provenance["planned_methods"][0]["benchmark_result_hash"] == qualification.result_hash
    )


def test_benchmark_bundles_are_hash_verified_and_unlabelled_review_packs_cannot_qualify(tmp_path):
    """Only the full, hash-addressed evaluation path can enable an optional method."""
    timestamp = datetime(2026, 9, 3, 17, 0, tzinfo=UTC)
    complete = BenchmarkResultBundle(
        "bundle_product_complete",
        "arche_products",
        "arche",
        "arche-products@sha256:v1",
        "leipzig-abt-buy-v1",
        "leipzig-abt-buy",
        "arche.crosswalk.complete-mapping.v1",
        timestamp,
        "complete",
        candidate_pairs=30,
        auto_match_count=8,
        review_count=6,
        true_pair_count=10,
        blocking_true_pair_count=10,
        true_positive_count=7,
        false_positive_count=1,
        reviewed_true_pair_count=3,
        provenance={"input_sha256": "sha256:source"},
    )
    path = tmp_path / "product-result.json"
    assert write_benchmark_result_bundle(path, complete) == complete.result_hash
    assert read_benchmark_result_bundle(path) == complete
    saved = complete.to_record()
    saved["provenance"]["input_sha256"] = "sha256:tampered"
    with pytest.raises(ValueError, match="hash does not match"):
        benchmark_result_bundle_from_record(saved)
    qualification = qualification_from_evaluated_result(
        complete,
        qualification_id="qualification_product_complete",
        qualification_policy_pin="product-quality@v1",
        qualified=True,
    )
    assert qualification.result_hash == complete.result_hash
    unlabelled = BenchmarkResultBundle(
        "bundle_facility_unlabelled",
        "facility-review-pack",
        "domain.facility",
        "facility-pack@sha256:v1",
        "facility-review-pack-v1",
        "facility-review-pack",
        "arche.review-pack.v1",
        timestamp,
        "unlabelled",
        candidate_pairs=20,
        auto_match_count=10,
        review_count=10,
    )
    with pytest.raises(ValueError, match="complete-truth"):
        qualification_from_evaluated_result(
            unlabelled,
            qualification_id="qualification_facility_unlabelled",
            qualification_policy_pin="facility-quality@v1",
            qualified=True,
        )


def test_pinned_splink_and_domain_runners_cannot_cross_resolver_boundaries():
    """Optional libraries use one method-execution contract with executor provenance."""
    timestamp = datetime(2026, 9, 3, 16, 45, tzinfo=UTC)
    case = ResolutionCase("case_pinned_runner", "Which entity is this?", (), (), timestamp)
    splink_method = ResolutionMethod(
        "splink_runner",
        "splink",
        ("organisation",),
        ("reconcile",),
        "policy-v1",
        "splink-settings@sha256:v1",
    )
    domain_method = ResolutionMethod(
        "domain_runner",
        "domain.supplier",
        ("organisation",),
        ("reconcile",),
        "policy-v1",
        "domain-supplier@sha256:v1",
    )

    def runner(requested_case, requested_method):
        return ResolutionMethodExecution(
            f"exec_{requested_method.method_id}",
            requested_method.method_id,
            requested_method.configuration_pin,
            "success",
            "sha256:caller-managed-artifact",
            0.01,
        )

    splink = SplinkResolutionMethodExecutor("application.splink.v1", runner)
    domain = DomainResolutionMethodExecutor("domain.supplier", "application.domain.v1", runner)

    assert splink.execute(case, splink_method).executor_id == "application.splink.v1"
    assert domain.execute(case, domain_method).executor_id == "application.domain.v1"
    with pytest.raises(ValueError, match="pinned to 'splink'"):
        splink.execute(case, domain_method)


def test_agent_plan_advice_can_only_recommend_a_persisted_plan(runtime):
    """Optional agent reasoning is bounded advice, not a tool or identity authority."""
    timestamp = datetime(2026, 9, 3, 16, 0, tzinfo=UTC)
    input_observation = Observation(
        "obs_agent_advice_input", "tea-intake", "shipment-20", timestamp, "sha256:intake"
    )
    intent = ResolutionIntent(
        "organisation", "reconcile", ("name", "registration_id"), "tea-policy-v1", 10
    )
    case = ResolutionCase(
        "case_agent_advice",
        "Which supplier is reported by this reviewed tea submission?",
        (input_observation.observation_id,),
        (),
        timestamp,
        evidence_gaps=(
            EvidenceGap(
                "registration_id",
                "distinguishes similarly named suppliers",
                permitted_action_types=("registry_lookup",),
            ),
        ),
        intent=intent,
    )
    action = EvidenceAction(
        "act_agent_advice_registry",
        case.case_id,
        "registry_lookup",
        "supplier_registry",
        timestamp,
        "tea-policy-v1",
        max_cost=0.05,
    )
    method = ResolutionMethod(
        "splink_agent_advice",
        "splink",
        ("organisation",),
        ("reconcile",),
        "tea-policy-v1",
        "splink-settings@sha256:tea-v1",
        required_fields=("name", "registration_id"),
        estimated_cost=0.10,
    )
    runtime.store.write_observations([input_observation])
    runtime.store.write_resolution_cases([case])
    runtime.store.write_evidence_actions([action])
    plan = runtime.plan_case(
        case.case_id,
        capabilities=(ToolCapability("supplier_registry", ("registry_lookup",), "tea-policy-v1"),),
        budget=ResolutionBudget(max_actions=1, max_cost=0.20),
        methods=(method,),
    )
    plan_event = runtime.record_case_plan(plan, recorded_at=timestamp)
    advice = AgentPlanAdvice(
        "advice_tea_001",
        case.case_id,
        plan_event.event_id,
        "application-llm-planner",
        "proceed",
        recommended_action_ids=(action.action_id,),
        recommended_method_ids=(method.method_id,),
        uncertainty_targets=("registration_id",),
        reason_codes=("independent_identifier_needed", "configured_method_eligible"),
        reasoning_hash="sha256:agent-reasoning-kept-by-application",
    )

    advice_event = runtime.record_agent_plan_advice(advice, recorded_at=timestamp)

    assert advice_event.references == (plan_event.event_id, action.action_id, method.method_id)
    assert advice_event.provenance["reasoning_hash"] == advice.reasoning_hash
    assert runtime.store.get_action_observation(action.action_id) is None
    assert runtime.store.get_decision("dec_not_created") is None
    with pytest.raises(ValueError, match="already selected"):
        runtime.record_agent_plan_advice(
            AgentPlanAdvice(
                "advice_tea_invalid",
                case.case_id,
                plan_event.event_id,
                "application-llm-planner",
                "proceed",
                recommended_method_ids=("unplanned_method",),
                reasoning_hash="sha256:invalid-advice",
            ),
            recorded_at=timestamp,
        )


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


def test_reviewed_reconcile_artifact_flows_through_evidence_receipts_and_policy(runtime):
    """Reviewed deterministic output is traceable but not independent corroboration."""
    timestamp = datetime(2026, 9, 3, 11, 0, tzinfo=UTC)
    case = ResolutionCase("case_reviewed_artifact", "Which supplier is this?", (), (), timestamp)
    artifact = Observation(
        "obs_reconcile_artifact",
        "resolver:arche.resolve.reconcile",
        "exec_reconcile",
        timestamp,
        "sha256:reconcile-artifact",
        provenance={
            "kind": "resolver_execution",
            "outcome": "success",
            "method_id": "arche_reconcile",
            "configuration_pin": "arche.resolve.reconcile@crosswalk.v1",
        },
    )
    file_observation = Observation("obs_review_file", "file", "r-1", timestamp, "sha256:file")
    registry_observation = Observation(
        "obs_review_registry", "registry", "r-2", timestamp, "sha256:registry"
    )
    supporting_evidence = (
        Evidence("ev_review_file", file_observation.observation_id, "name", "supports"),
        Evidence(
            "ev_review_registry",
            registry_observation.observation_id,
            "registration_id",
            "supports",
        ),
    )
    result = {
        "matches": [{"decision_id": "xwd:reviewed", "decision": "match", "score": 0.99}],
        "pins": {"engine": "crosswalk.v1"},
        "blocking": {"candidate_pairs": 1},
    }
    runtime.store.write_observations([artifact, file_observation, registry_observation])
    runtime.store.write_resolution_cases([case])
    runtime.store.write_evidence(supporting_evidence)
    runtime.store.write_case_events(
        [
            CaseEvent(
                "evt_reconcile_execution",
                case.case_id,
                "method_execution",
                timestamp,
                ("approval_reconcile", artifact.observation_id),
            )
        ]
    )

    artifact_evidence, run, receipts = runtime.record_reviewed_reconcile_artifact(
        case.case_id,
        artifact.observation_id,
        result,
        review_id="review_reconcile_01",
        reviewed_at=timestamp,
        run_id="run_reviewed_reconcile",
        artifact_evidence_ids_by_decision={"xwd:reviewed": "ev_reviewed_edge"},
        supporting_evidence_ids_by_decision={
            "xwd:reviewed": tuple(item.evidence_id for item in supporting_evidence)
        },
    )
    outcome = runtime.apply_resolution_decision_policy(
        case.case_id,
        receipts[0].decision_id,
        policy=ResolutionDecisionPolicy("supplier-link-v1"),
        recorded_at=timestamp,
    )

    assert run.provenance["resolution_case_id"] == case.case_id
    assert artifact_evidence[0].provenance["review_id"] == "review_reconcile_01"
    assert receipts[0].evidence_ids == (
        "ev_reviewed_edge",
        "ev_review_file",
        "ev_review_registry",
    )
    assert outcome.action == "link"
    assert outcome.independent_source_ids == ("file", "registry")
    assert {event.event_type for event in runtime.get_case_history(case.case_id)} == {
        "method_execution",
        "reviewed_resolver_evidence",
        "resolver_decision",
        "policy_decision",
    }


def test_reviewed_splink_and_domain_artifacts_share_one_value_free_adapter():
    """Library-specific scores are recorded, never interpreted as portable thresholds."""
    timestamp = datetime(2026, 9, 3, 12, 0, tzinfo=UTC)
    artifact = ReviewedResolutionArtifact(
        "splink",
        "splink-settings@sha256:approved",
        2,
        (
            ReviewedResolutionEdge("splink:1", "same_entity", "link", probability=0.99),
            ReviewedResolutionEdge("domain:2", "review", "review", raw_score=7.0),
        ),
    )
    evidence = reviewed_resolution_evidence(
        artifact,
        observation_id="obs_splink_artifact",
        review_id="review_splink_01",
        evidence_ids_by_decision={"splink:1": "ev_splink_1", "domain:2": "ev_domain_2"},
    )
    run, receipts = adapt_reviewed_resolution_artifact(
        artifact,
        run_id="run_splink_01",
        created_at=timestamp,
        evidence_ids_by_decision={
            "splink:1": ("ev_splink_1",),
            "domain:2": ("ev_domain_2",),
        },
    )

    assert [item.supports for item in evidence] == ["splink:1", "domain:2"]
    assert run.resolver == "splink"
    assert [(item.action, item.probability, item.raw_score) for item in receipts] == [
        ("link", 0.99, None),
        ("review", None, 7.0),
    ]
    assert all(item.schema_pin == "arche.reviewed_resolution_artifact.v1" for item in receipts)


def test_reviewed_splink_artifact_flows_through_case_evidence_receipts_and_policy(runtime):
    """Generic resolver artifacts use the same controlled case path as Arche output."""
    timestamp = datetime(2026, 9, 3, 12, 30, tzinfo=UTC)
    case = ResolutionCase("case_reviewed_splink", "Which supplier is this?", (), (), timestamp)
    artifact_observation = Observation(
        "obs_splink_artifact",
        "resolver:splink",
        "exec_splink_supplier",
        timestamp,
        "sha256:splink-artifact",
        provenance={
            "kind": "resolver_execution",
            "outcome": "success",
            "method_id": "splink_supplier",
            "configuration_pin": "splink-settings@sha256:approved",
        },
    )
    file_observation = Observation("obs_splink_file", "file", "r-1", timestamp, "sha256:file")
    registry_observation = Observation(
        "obs_splink_registry", "registry", "r-2", timestamp, "sha256:registry"
    )
    supporting_evidence = (
        Evidence("ev_splink_file", file_observation.observation_id, "name", "supports"),
        Evidence(
            "ev_splink_registry",
            registry_observation.observation_id,
            "registration_id",
            "supports",
        ),
    )
    artifact = ReviewedResolutionArtifact(
        "splink",
        "splink-settings@sha256:approved",
        1,
        (ReviewedResolutionEdge("splink:reviewed", "same_entity", "link", probability=0.99),),
    )
    runtime.store.write_observations([artifact_observation, file_observation, registry_observation])
    runtime.store.write_resolution_cases([case])
    runtime.store.write_evidence(supporting_evidence)
    runtime.store.write_case_events(
        [
            CaseEvent(
                "evt_splink_execution",
                case.case_id,
                "method_execution",
                timestamp,
                ("approval_splink_supplier", artifact_observation.observation_id),
            )
        ]
    )

    artifact_evidence, run, receipts = runtime.record_reviewed_resolution_artifact(
        case.case_id,
        artifact_observation.observation_id,
        artifact,
        review_id="review_splink_01",
        reviewed_at=timestamp,
        run_id="run_reviewed_splink",
        artifact_evidence_ids_by_decision={"splink:reviewed": "ev_splink_edge"},
        supporting_evidence_ids_by_decision={
            "splink:reviewed": tuple(item.evidence_id for item in supporting_evidence)
        },
    )
    outcome = runtime.apply_resolution_decision_policy(
        case.case_id,
        receipts[0].decision_id,
        policy=ResolutionDecisionPolicy("supplier-link-v1"),
        recorded_at=timestamp,
    )

    assert artifact_evidence[0].provenance["review_id"] == "review_splink_01"
    assert run.provenance["resolution_case_id"] == case.case_id
    assert run.resolver == "splink"
    assert receipts[0].evidence_ids == (
        "ev_splink_edge",
        "ev_splink_file",
        "ev_splink_registry",
    )
    assert outcome.action == "link"
    assert outcome.independent_source_ids == ("file", "registry")
    assert {event.event_type for event in runtime.get_case_history(case.case_id)} == {
        "method_execution",
        "reviewed_resolver_evidence",
        "resolver_decision",
        "policy_decision",
    }


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

    class ApplicationExecutor:
        def __init__(self):
            self.received = []

        def execute(self, decision):
            self.received.append(decision)
            return PolicyExecution(
                "exec_supplier_link",
                decision.decision_id,
                decision.case_id,
                decision.policy_id,
                decision.action,
                "supplier-application",
                "applied",
                "sha256:application-result",
            )

    executor = ApplicationExecutor()
    execution = runtime.execute_released_policy_decision(outcome, executor, recorded_at=timestamp)

    assert executor.received == [outcome]
    assert execution.outcome == "applied"
    execution_event = next(
        event
        for event in runtime.get_case_history(case.case_id)
        if event.event_type == "policy_execution"
    )
    assert execution_event.provenance == {
        "policy_id": "supplier-link-v1",
        "action": "link",
        "executor_id": "supplier-application",
        "outcome": "applied",
        "result_hash": "sha256:application-result",
    }
    with pytest.raises(ValueError, match="already has a recorded executor outcome"):
        runtime.execute_released_policy_decision(outcome, executor, recorded_at=timestamp)
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

    class UnexpectedExecutor:
        def execute(self, decision):
            raise AssertionError(f"executor should not receive {decision.action}")

    with pytest.raises(ValueError, match="only released link or create"):
        runtime.execute_released_policy_decision(weak, UnexpectedExecutor(), recorded_at=timestamp)


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
