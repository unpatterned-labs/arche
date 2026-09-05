# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""The M0 runtime handle.

Reconciliation intentionally does not live here yet. The runtime first owns
the durable contracts and store boundary that later resolution and agentic
control work will use.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from hashlib import sha256
from typing import TYPE_CHECKING, Any

from arche.runtime._adapters import adapt_reconcile_result, reviewed_reconcile_evidence
from arche.runtime._agent_planning import AgentPlanAdvice
from arche.runtime._case_progress import CaseProgress, assess_case_progress
from arche.runtime._document_execution import DocumentIngestionRequest
from arche.runtime._document_observations import (
    DocumentIngestion,
    observation_from_document_ingestion,
)
from arche.runtime._document_proposals import (
    DocumentProposalSet,
    reviewed_document_evidence_from_observation,
    reviewed_document_proposals,
    reviewed_document_proposals_from_evidence,
)
from arche.runtime._execution import PolicyExecution
from arche.runtime._method_execution import ResolutionMethodExecution
from arche.runtime._models import (
    ActionObservation,
    CaseEvent,
    Claim,
    ClaimProposal,
    DocumentClaimSpec,
    DocumentRelationSpec,
    EntityMemory,
    EntityRelation,
    Evidence,
    Observation,
    PolicyDecision,
    ProposalAcceptance,
    ProposalAcceptancePolicy,
    RelationProposal,
    ResolutionDecisionPolicy,
    ResolutionMethod,
    ResolutionMethodApproval,
    ResolutionRun,
    ReviewedActionEvidence,
    new_ledger_id,
)
from arche.runtime._planning import (
    DeterministicResolutionPlanner,
    EvidencePlan,
    MethodBenchmarkQualification,
    ResolutionBudget,
)
from arche.runtime._reassessment import CaseReassessment, reassess_case, reassessed_case
from arche.runtime._reviewed_artifacts import (
    ReviewedResolutionArtifact,
    adapt_reviewed_resolution_artifact,
    reviewed_resolution_evidence,
)
from arche.store.base import ArcheStore

if TYPE_CHECKING:
    from arche.doc._extract import Extraction
    from arche.doc.parse import ParsedDocument
    from arche.runtime._connectors import EvidenceConnector
    from arche.runtime._document_execution import DocumentIngestionExecutor
    from arche.runtime._execution import PolicyDecisionExecutor
    from arche.runtime._method_execution import ResolutionMethodExecutor
    from arche.runtime._models import DecisionReceipt, ToolCapability


@dataclass(frozen=True)
class ArcheEngine:
    """A runtime bound to one canonical entity store."""

    store: ArcheStore

    def get_entity_memory(self, entity_id: str) -> EntityMemory:
        """Return the compact current ledger view for one stable entity.

        Parameters:
            entity_id: The opaque stable entity identifier to inspect.

        Returns:
            Entity metadata with claims, contradictions, relations, and open
            questions, each linked back to provenance records.

        Raises:
            ValueError: If the entity does not exist in this runtime.
        """
        entity = self.store.get_entity(entity_id)
        if entity is None:
            raise ValueError(
                f"entity {entity_id!r} does not exist; persist an Entity before "
                "requesting its memory view"
            )
        return EntityMemory(
            entity=entity,
            claims=self.store.list_claims(entity_id),
            contradictions=self.store.list_contradictions(entity_id),
            relations=self.store.list_relations(entity_id),
            open_questions=self.store.list_open_questions(entity_id),
        )

    def get_case_history(self, case_id: str) -> tuple[CaseEvent, ...]:
        """Return immutable history events for one persisted ResolutionCase.

        Parameters:
            case_id: The opaque ResolutionCase identifier to inspect.

        Returns:
            Case events in recorded order.

        Raises:
            ValueError: If the case does not exist in this runtime.
        """
        if self.store.get_resolution_case(case_id) is None:
            raise ValueError(
                f"resolution case {case_id!r} does not exist; open the case before "
                "requesting its history"
            )
        return self.store.list_case_events(case_id)

    def get_case_progress(self, case_id: str) -> CaseProgress:
        """Return a read-only statement of the next safe step for one case.

        Progress is derived from persisted case history. It cannot execute a
        connector or resolver, transform an Observation into Evidence, or
        release a decision.

        Parameters:
            case_id: The opaque ResolutionCase identifier to inspect.

        Returns:
            A deterministic control-plane status with the next permitted step.

        Raises:
            ValueError: If the case does not exist in this runtime.
        """
        return assess_case_progress(self.store, case_id)

    def reassess_case(self, case_id: str) -> CaseReassessment:
        """Report reviewed field coverage and remaining evidence gaps for a case.

        The persisted ResolutionCase remains immutable. This read-only view is
        used by planning after reviewed Evidence arrives from a permitted action.

        Parameters:
            case_id: The opaque ResolutionCase identifier to inspect.

        Returns:
            Reviewed field labels and the gaps they can satisfy.

        Raises:
            ValueError: If the case does not exist in this runtime.
        """
        return reassess_case(self.store, case_id)

    def ingest_action_observation(
        self,
        action_id: str,
        observation: Observation,
    ) -> ActionObservation:
        """Record a permitted evidence result as an immutable Observation.

        Parameters:
            action_id: A persisted policy-permitted EvidenceAction identifier.
            observation: The immutable result returned by that action's source.

        Returns:
            The durable link from the action to its resulting Observation.

        Raises:
            ValueError: If the action was not permitted or the source differs.
        """
        action = self.store.get_evidence_action(action_id)
        if action is None:
            raise ValueError(
                f"evidence action {action_id!r} is not permitted; persist an "
                "EvidenceAction before recording its result"
            )
        if observation.source_id != action.source_id:
            raise ValueError(
                f"observation source {observation.source_id!r} does not match "
                f"permitted action source {action.source_id!r}"
            )

        link = ActionObservation(
            action_id=action.action_id,
            observation_id=observation.observation_id,
            recorded_at=observation.recorded_at,
        )
        self.store.write_observations([observation])
        self.store.write_action_observations([link])
        return link

    def ingest_document_observation(
        self,
        action_id: str,
        ingestion: DocumentIngestion,
        *,
        observation_id: str,
        recorded_at: datetime,
    ) -> ActionObservation:
        """Record a permitted PDF, scan, image, or text ingestion result.

        Parser and OCR providers are application-owned. Their result becomes an
        immutable Observation before extraction fields can become Evidence.
        """
        action = self.store.get_evidence_action(action_id)
        if action is None:
            raise ValueError(
                f"evidence action {action_id!r} does not exist; permit document "
                "ingestion before recording its result"
            )
        if action.action_type not in {"document_extract", "document_ocr"}:
            raise ValueError(
                "document ingestion requires a document_extract or document_ocr EvidenceAction"
            )
        observation = observation_from_document_ingestion(
            ingestion,
            observation_id=observation_id,
            source_id=action.source_id,
            recorded_at=recorded_at,
        )
        return self.ingest_action_observation(action_id, observation)

    def execute_document_ingestion_action(
        self,
        action_id: str,
        request: DocumentIngestionRequest,
        executor: DocumentIngestionExecutor,
        *,
        observation_id: str,
        recorded_at: datetime,
    ) -> ActionObservation:
        """Run a caller-owned parser/OCR provider under a permitted action.

        The provider receives the document path or bytes reference in the
        caller's process. Arche records only its value-free ingestion result,
        or a hash-only failure Observation if parsing cannot complete.
        """
        action = self.store.get_evidence_action(action_id)
        if action is None:
            raise ValueError(
                f"evidence action {action_id!r} does not exist; permit document "
                "ingestion before executing it"
            )
        if action.action_type not in {"document_extract", "document_ocr"}:
            raise ValueError(
                "document ingestion requires a document_extract or document_ocr EvidenceAction"
            )
        try:
            ingestion = executor.ingest(request)
        except Exception as error:
            failure_hash = sha256(
                f"{executor.executor_id}:{type(error).__name__}".encode()
            ).hexdigest()
            observation = Observation(
                observation_id=observation_id,
                source_id=action.source_id,
                source_record_id=request.source_record_id,
                recorded_at=recorded_at,
                content_hash=f"sha256:{failure_hash}",
                provenance={
                    "kind": "document_ingestion",
                    "outcome": "failure",
                    "executor_id": executor.executor_id,
                    "failure_reason": "ingestion_failed",
                },
            )
            return self.ingest_action_observation(action_id, observation)
        return self.ingest_document_observation(
            action_id,
            ingestion,
            observation_id=observation_id,
            recorded_at=recorded_at,
        )

    def record_reviewed_document_evidence(
        self,
        case_id: str,
        action_id: str,
        extraction: Extraction,
        *,
        review_id: str,
        recorded_at: datetime,
        event_id: str | None = None,
    ) -> tuple[tuple[Evidence, ...], CaseEvent]:
        """Record reviewed field Evidence against one ingested document action.

        Parsing creates an immutable Observation, not Evidence. A caller-owned
        review supplies fields and spans later; this method records their
        value-free provenance against the exact Observation produced by the
        permitted action. It makes no claim, relation, receipt, or policy
        decision.

        Raises:
            ValueError: If the action is not case-bound document ingestion, has
                no successful Observation, or the review identifier is empty.
        """
        if not review_id:
            raise ValueError("reviewed document evidence needs a review_id")
        case, action, observation = self._reviewed_document_action_inputs(case_id, action_id)
        evidence = reviewed_document_evidence_from_observation(observation, extraction)
        event = CaseEvent(
            event_id=event_id or new_ledger_id("evt"),
            case_id=case.case_id,
            event_type="reviewed_document_evidence",
            recorded_at=recorded_at,
            references=(observation.observation_id, *(item.evidence_id for item in evidence)),
            provenance={
                "action_id": action.action_id,
                "review_id": review_id,
                "field_evidence": [
                    {
                        "evidence_id": item.evidence_id,
                        **dict(item.provenance),
                    }
                    for item in evidence
                ],
            },
        )
        self.store.write_evidence(evidence)
        self.store.write_case_events([event])
        return evidence, event

    def record_reviewed_action_evidence(
        self,
        case_id: str,
        action_id: str,
        reviewed: tuple[ReviewedActionEvidence, ...],
        *,
        review_id: str,
        recorded_at: datetime,
        event_id: str | None = None,
    ) -> tuple[tuple[Evidence, ...], CaseEvent]:
        """Record value-free reviewed Evidence from a non-document action result.

        A registry or supplier-master response remains an immutable Observation
        until the caller reviews it. The caller supplies only safe field labels;
        raw values and external response bodies stay outside the runtime.

        Parameters:
            case_id: Existing case that owns the permitted action.
            action_id: Successful non-document EvidenceAction to review.
            reviewed: Value-free labels accepted from the action result.
            review_id: Caller-managed review identifier.
            recorded_at: Timestamp of the review decision.
            event_id: Optional caller-owned event identifier.

        Returns:
            Persisted Evidence and its immutable case-history event.

        Raises:
            ValueError: If the action is not eligible, has no successful
                Observation, or the review would duplicate durable evidence.
        """
        if not review_id:
            raise ValueError("reviewed action evidence needs a review_id")
        if not reviewed:
            raise ValueError("reviewed action evidence needs at least one value-free field label")
        case = self.store.get_resolution_case(case_id)
        action = self.store.get_evidence_action(action_id)
        if case is None or action is None or action.case_id != case.case_id:
            raise ValueError(f"action {action_id!r} is not permitted for case {case_id!r}")
        if action.action_type in {"document_extract", "document_ocr"}:
            raise ValueError("document actions require record_reviewed_document_evidence")
        link = self.store.get_action_observation(action.action_id)
        if link is None:
            raise ValueError(f"action {action_id!r} has no Observation; execute it before review")
        observation = self.store.get_observation(link.observation_id)
        if observation is None or observation.provenance.get("outcome") == "failure":
            raise ValueError(f"action {action_id!r} has no successful Observation to review")
        evidence_ids = tuple(item.evidence_id for item in reviewed)
        if len(set(evidence_ids)) != len(evidence_ids):
            raise ValueError("reviewed action evidence IDs must be unique")
        if any(self.store.get_evidence(evidence_id) is not None for evidence_id in evidence_ids):
            raise ValueError("reviewed action evidence IDs must be new")
        if any(
            event.event_type == "reviewed_action_evidence"
            and event.provenance.get("action_id") == action.action_id
            and event.provenance.get("review_id") == review_id
            for event in self.get_case_history(case.case_id)
        ):
            raise ValueError("this action and review_id are already recorded")
        evidence = tuple(
            Evidence(
                item.evidence_id,
                observation.observation_id,
                item.kind,
                item.supports,
                provenance={
                    "action_id": action.action_id,
                    "field": item.field,
                    "review_id": review_id,
                    "reviewed": True,
                },
            )
            for item in reviewed
        )
        event = CaseEvent(
            event_id=event_id or new_ledger_id("evt"),
            case_id=case.case_id,
            event_type="reviewed_action_evidence",
            recorded_at=recorded_at,
            references=(observation.observation_id, *evidence_ids),
            provenance={
                "action_id": action.action_id,
                "review_id": review_id,
                "reviewed_fields": [item.field for item in reviewed],
            },
        )
        self.store.write_evidence(evidence)
        self.store.write_case_events([event])
        return evidence, event

    def record_reviewed_document_field_proposals(
        self,
        case_id: str,
        action_id: str,
        extraction: Extraction,
        *,
        review_id: str,
        recorded_at: datetime,
        claim_specs: tuple[DocumentClaimSpec, ...] = (),
        relation_specs: tuple[DocumentRelationSpec, ...] = (),
        event_id: str | None = None,
    ) -> DocumentProposalSet:
        """Record proposal-only semantic mappings from previously reviewed fields.

        The field Evidence must already have been recorded against the same
        successful document action. This keeps a semantic proposal downstream
        of review, while letting its caller retain reviewed values outside the
        runtime store.
        """
        if not review_id:
            raise ValueError("reviewed document proposals need a review_id")
        case, _, observation = self._reviewed_document_action_inputs(case_id, action_id)
        evidence = reviewed_document_evidence_from_observation(observation, extraction)
        if any(self.store.get_evidence(item.evidence_id) != item for item in evidence):
            raise ValueError(
                "reviewed field Evidence is missing or differs; record the exact reviewed "
                "fields before proposing claims or relationships"
            )
        if not any(
            event.event_type == "reviewed_document_evidence"
            and event.provenance.get("action_id") == action_id
            and event.provenance.get("review_id") == review_id
            for event in self.store.list_case_events(case.case_id)
        ):
            raise ValueError(
                "reviewed field Evidence needs a matching review_id before proposing claims "
                "or relationships"
            )
        proposals = reviewed_document_proposals_from_evidence(
            case_id=case.case_id,
            observation=observation,
            extraction=extraction,
            evidence=evidence,
            recorded_at=recorded_at,
            review_id=review_id,
            claim_specs=claim_specs,
            relation_specs=relation_specs,
            event_id=event_id,
        )
        target_entity_ids = (
            {proposal.entity_id for proposal in proposals.claims}
            | {proposal.subject_entity_id for proposal in proposals.relations}
            | {proposal.object_entity_id for proposal in proposals.relations}
        )
        for entity_id in target_entity_ids:
            if self.store.get_entity(entity_id) is None:
                raise ValueError(
                    f"proposal entity {entity_id!r} does not exist; persist the "
                    "stable entity before recording a document proposal"
                )
        self.store.write_case_events([proposals.event])
        return proposals

    def _reviewed_document_action_inputs(self, case_id: str, action_id: str):
        """Return the persisted case action and successful document Observation."""
        case = self.store.get_resolution_case(case_id)
        if case is None:
            raise ValueError(f"resolution case {case_id!r} does not exist")
        action = self.store.get_evidence_action(action_id)
        if action is None or action.case_id != case.case_id:
            raise ValueError(f"document action {action_id!r} is not permitted for this case")
        if action.action_type not in {"document_extract", "document_ocr"}:
            raise ValueError(
                "reviewed document evidence requires a document extraction or OCR action"
            )
        link = self.store.get_action_observation(action.action_id)
        if link is None:
            raise ValueError(
                f"document action {action_id!r} has no Observation; execute it before review"
            )
        observation = self.store.get_observation(link.observation_id)
        if observation is None:
            raise ValueError(f"document action {action_id!r} links to a missing Observation")
        if (
            observation.provenance.get("kind") != "document_ingestion"
            or observation.provenance.get("outcome") == "failure"
        ):
            raise ValueError(
                f"document action {action_id!r} has no successful ingestion Observation"
            )
        return case, action, observation

    def execute_evidence_action(
        self,
        action_id: str,
        connector: EvidenceConnector,
    ) -> ActionObservation:
        """Execute one permitted read-only connector action.

        Parameters:
            action_id: A persisted policy-permitted EvidenceAction identifier.
            connector: A connector whose declared capability permits that action.

        Returns:
            The durable link from the action to its resulting Observation.

        Raises:
            ValueError: If the action is unknown or the connector is not allowed.
        """
        action = self.store.get_evidence_action(action_id)
        if action is None:
            raise ValueError(
                f"evidence action {action_id!r} is not permitted; persist an "
                "EvidenceAction before executing it"
            )
        if not connector.capability.permits(action):
            raise ValueError(
                f"connector capability does not permit action {action_id!r}; "
                "use a read-only connector with the matching source, action type, "
                "and policy pin"
            )
        if self.store.get_action_observation(action_id) is not None:
            raise ValueError(
                f"evidence action {action_id!r} already has an Observation; issue a "
                "new permitted action for a retry so both attempts remain traceable"
            )
        return self.ingest_action_observation(action_id, connector.observe(action))

    def plan_case(
        self,
        case_id: str,
        *,
        capabilities: tuple[ToolCapability, ...],
        budget: ResolutionBudget,
        methods: tuple[ResolutionMethod, ...] = (),
        benchmark_qualifications: tuple[MethodBenchmarkQualification, ...] = (),
    ) -> EvidencePlan:
        """Assess a case and select bounded, permitted evidence actions.

        Parameters:
            case_id: A persisted ResolutionCase identifier.
            capabilities: Read-only capabilities available to execute now.
            budget: Hard maximum action count and estimated cost.
            methods: Configured resolver methods the planner may recommend.
            benchmark_qualifications: Hash-addressed evaluations required by
                optional configured methods.

        Returns:
            A deterministic EvidencePlan. It does not execute any action.

        Raises:
            ValueError: If the case does not exist.
        """
        case = self.store.get_resolution_case(case_id)
        if case is None:
            raise ValueError(
                f"resolution case {case_id!r} does not exist; open the case before "
                "planning evidence acquisition"
            )
        return DeterministicResolutionPlanner().plan(
            reassessed_case(self.store, case),
            self.store.list_evidence_actions(case_id),
            capabilities,
            budget,
            methods,
            benchmark_qualifications,
        )

    def record_case_plan(
        self,
        plan: EvidencePlan,
        *,
        recorded_at: datetime,
        event_id: str | None = None,
    ) -> CaseEvent:
        """Append a deterministic plan to its case's immutable history.

        This writes only the planner's structured output and action references;
        planning remains separate from connector execution.

        Parameters:
            plan: A plan returned by :meth:`plan_case`.
            recorded_at: Time at which the plan was accepted for the case history.
            event_id: Optional caller-owned opaque event identifier.

        Returns:
            The persisted immutable plan event.

        Raises:
            ValueError: If the plan's case does not exist in this runtime.
        """
        assessment = plan.assessment
        event = CaseEvent(
            event_id=event_id or new_ledger_id("evt"),
            case_id=assessment.case_id,
            event_type="evidence_plan",
            recorded_at=recorded_at,
            references=tuple(action.action_id for action in plan.actions),
            provenance={
                "eligible_action_ids": list(assessment.eligible_action_ids),
                "unavailable_action_ids": list(assessment.unavailable_action_ids),
                "unresolved_gap_fields": list(plan.unresolved_gap_fields),
                "total_estimated_cost": plan.total_estimated_cost,
                "planned_method_ids": [method.method_id for method in plan.methods],
                "planned_methods": [
                    {
                        "method_id": method.method_id,
                        "resolver": method.resolver,
                        "policy_pin": method.policy_pin,
                        "configuration_pin": method.configuration_pin,
                        "estimated_cost": method.estimated_cost,
                        **(
                            {
                                "benchmark_id": method.benchmark_id,
                                "benchmark_qualification_id": method.benchmark_qualification_id,
                                "benchmark_result_hash": method.benchmark_result_hash,
                            }
                            if method.benchmark_id is not None
                            else {}
                        ),
                    }
                    for method in plan.methods
                ],
                "method_assessments": [
                    {
                        "method_id": method.method_id,
                        "eligible": method.eligible,
                        "reason": method.reason,
                    }
                    for method in assessment.method_assessments
                ],
            },
        )
        self.store.write_case_events([event])
        return event

    def record_agent_plan_advice(
        self,
        advice: AgentPlanAdvice,
        *,
        recorded_at: datetime,
        event_id: str | None = None,
    ) -> CaseEvent:
        """Append bounded agent advice without allowing it to execute a plan.

        The advice can recommend only action and method IDs already selected by
        a persisted evidence plan. It records no raw reasoning, tool result,
        entity change, approval, or resolver execution.
        """
        plan_event = next(
            (
                event
                for event in self.get_case_history(advice.case_id)
                if event.event_id == advice.plan_event_id and event.event_type == "evidence_plan"
            ),
            None,
        )
        if plan_event is None:
            raise ValueError(
                f"agent plan advice {advice.advice_id!r} requires a persisted "
                "evidence plan for its case"
            )
        planned_action_ids = set(plan_event.references)
        planned_method_ids = set(plan_event.provenance.get("planned_method_ids", ()))
        unknown_actions = set(advice.recommended_action_ids) - planned_action_ids
        unknown_methods = set(advice.recommended_method_ids) - planned_method_ids
        if unknown_actions or unknown_methods:
            raise ValueError(
                "agent plan advice may recommend only actions and methods already "
                "selected by the persisted evidence plan"
            )
        if any(
            event.event_type == "agent_plan_advice"
            and event.provenance.get("advice_id") == advice.advice_id
            for event in self.get_case_history(advice.case_id)
        ):
            raise ValueError(f"agent plan advice {advice.advice_id!r} already exists")
        event = CaseEvent(
            event_id=event_id or new_ledger_id("evt"),
            case_id=advice.case_id,
            event_type="agent_plan_advice",
            recorded_at=recorded_at,
            references=(
                advice.plan_event_id,
                *advice.recommended_action_ids,
                *advice.recommended_method_ids,
            ),
            provenance={
                "advice_id": advice.advice_id,
                "advisor_id": advice.advisor_id,
                "recommendation": advice.recommendation,
                "recommended_action_ids": list(advice.recommended_action_ids),
                "recommended_method_ids": list(advice.recommended_method_ids),
                "uncertainty_targets": list(advice.uncertainty_targets),
                "reason_codes": list(advice.reason_codes),
                "reasoning_hash": advice.reasoning_hash,
            },
        )
        self.store.write_case_events([event])
        return event

    def approve_planned_resolution_method(
        self,
        approval: ResolutionMethodApproval,
        method: ResolutionMethod,
        *,
        recorded_at: datetime,
        event_id: str | None = None,
    ) -> CaseEvent:
        """Record an explicit approval for a method selected by a persisted plan.

        Parameters:
            approval: Caller or human approval bound to a specific plan and method pin.
            method: Configured method that must exactly match the selected plan entry.
            recorded_at: Timestamp for immutable approval history.
            event_id: Optional caller-owned immutable case-event identifier.

        Returns:
            The persisted method-approval event.

        Raises:
            ValueError: If the plan did not select this exact method or a duplicate
                approval already exists.
        """
        if (
            approval.method_id != method.method_id
            or approval.configuration_pin != method.configuration_pin
        ):
            raise ValueError("resolution method approval does not match the supplied method pin")
        plan_event = self._planned_method_event(approval.case_id, approval.plan_event_id, method)
        if method.estimated_cost > approval.max_cost:
            raise ValueError(
                "resolution method estimate exceeds the approved cost ceiling; "
                "raise the explicit approval limit or choose another method"
            )
        history = self.get_case_history(approval.case_id)
        if any(
            event.event_type == "method_approval"
            and event.provenance.get("approval_id") == approval.approval_id
            for event in history
        ):
            raise ValueError(f"resolution method approval {approval.approval_id!r} already exists")
        event = CaseEvent(
            event_id=event_id or new_ledger_id("evt"),
            case_id=approval.case_id,
            event_type="method_approval",
            recorded_at=recorded_at,
            references=(plan_event.event_id, approval.method_id),
            provenance={
                "approval_id": approval.approval_id,
                "approved_by": approval.approved_by,
                "max_cost": approval.max_cost,
                "method_id": method.method_id,
                "resolver": method.resolver,
                "policy_pin": method.policy_pin,
                "configuration_pin": method.configuration_pin,
                "estimated_cost": method.estimated_cost,
                **(
                    {"benchmark_id": method.benchmark_id} if method.benchmark_id is not None else {}
                ),
            },
        )
        self.store.write_case_events([event])
        return event

    def execute_approved_resolution_method(
        self,
        case_id: str,
        approval_id: str,
        method: ResolutionMethod,
        executor: ResolutionMethodExecutor,
        *,
        recorded_at: datetime,
        event_id: str | None = None,
    ) -> Observation:
        """Run an approved resolver method and record only its output Observation.

        Parameters:
            case_id: Existing case whose plan and approval selected the method.
            approval_id: Recorded explicit approval identifier.
            method: Configured method exactly matching that approval.
            executor: Caller-owned adapter that runs the method.
            recorded_at: Timestamp for the immutable execution record.
            event_id: Optional caller-owned immutable case-event identifier.

        Returns:
            A success or failure Observation for later Evidence derivation.

        Raises:
            ValueError: If approval is missing, mismatched, or already executed.
        """
        case = self.store.get_resolution_case(case_id)
        if case is None:
            raise ValueError(f"resolution case {case_id!r} does not exist")
        history = self.get_case_history(case_id)
        approval_event = next(
            (
                event
                for event in history
                if event.event_type == "method_approval"
                and event.provenance.get("approval_id") == approval_id
            ),
            None,
        )
        if approval_event is None or not _method_matches_event(method, approval_event):
            raise ValueError(
                f"resolution method {method.method_id!r} is not approved for case {case_id!r}"
            )
        if any(
            event.event_type == "method_execution" and approval_id in event.references
            for event in history
        ):
            raise ValueError(
                f"resolution method approval {approval_id!r} already has an execution Observation"
            )
        try:
            execution = executor.execute(case, method)
        except Exception as error:
            execution = ResolutionMethodExecution(
                execution_id=f"exec_{sha256(approval_id.encode()).hexdigest()[:24]}",
                method_id=method.method_id,
                configuration_pin=method.configuration_pin,
                outcome="failed",
                result_hash=f"sha256:{sha256(type(error).__name__.encode()).hexdigest()}",
                actual_cost=0.0,
            )
        if (
            execution.method_id != method.method_id
            or execution.configuration_pin != method.configuration_pin
        ):
            raise ValueError(
                "resolver execution does not match the approved method and configuration pin"
            )
        max_cost = approval_event.provenance["max_cost"]
        if not isinstance(max_cost, (int, float)) or isinstance(max_cost, bool):
            raise TypeError("stored method approval max_cost is not numeric")
        failed = execution.outcome == "failed" or execution.actual_cost > max_cost
        failure_reason = (
            ("executor_failed" if execution.outcome == "failed" else "cost_limit")
            if failed
            else None
        )
        observation = Observation(
            observation_id=f"obs_{execution.execution_id}",
            source_id=f"resolver:{method.resolver}",
            source_record_id=execution.execution_id,
            recorded_at=recorded_at,
            content_hash=execution.result_hash,
            provenance={
                "kind": "resolver_execution",
                "outcome": "failure" if failed else "success",
                "failure_reason": failure_reason,
                "approval_id": approval_id,
                "method_id": method.method_id,
                "configuration_pin": method.configuration_pin,
                "estimated_cost": method.estimated_cost,
                "actual_cost": execution.actual_cost,
                "executor_id": execution.executor_id,
            },
        )
        self.store.write_observations([observation])
        self.store.write_case_events(
            [
                CaseEvent(
                    event_id=event_id or new_ledger_id("evt"),
                    case_id=case_id,
                    event_type="method_execution",
                    recorded_at=recorded_at,
                    references=(approval_id, observation.observation_id),
                    provenance=observation.provenance,
                )
            ]
        )
        return observation

    def _planned_method_event(
        self,
        case_id: str,
        plan_event_id: str,
        method: ResolutionMethod,
    ) -> CaseEvent:
        """Load the evidence-plan event that selected one exact resolver method."""
        plan_event = next(
            (
                event
                for event in self.get_case_history(case_id)
                if event.event_id == plan_event_id and event.event_type == "evidence_plan"
            ),
            None,
        )
        if plan_event is None or not _method_matches_plan(method, plan_event):
            raise ValueError(
                f"plan event {plan_event_id!r} did not select method {method.method_id!r} "
                "with this configuration pin"
            )
        return plan_event

    def _record_case_resolver_receipts(
        self,
        case_id: str,
        run: ResolutionRun,
        receipts: tuple[DecisionReceipt, ...],
        *,
        recorded_at: datetime,
    ) -> tuple[ResolutionRun, tuple[DecisionReceipt, ...]]:
        """Persist resolver receipts and metrics through one case-history path."""
        if self.store.get_resolution_case(case_id) is None:
            raise ValueError(
                f"resolution case {case_id!r} does not exist; open the case before "
                "recording its resolver result"
            )
        case_run = replace(
            run,
            provenance={**run.provenance, "resolution_case_id": case_id},
        )
        self.store.write_decisions(receipts)
        self.store.write_resolution_runs([case_run])
        self.store.write_case_events(
            [
                CaseEvent(
                    event_id=new_ledger_id("evt"),
                    case_id=case_id,
                    event_type="resolver_decision",
                    recorded_at=recorded_at,
                    references=(case_run.run_id, receipt.decision_id),
                    provenance={
                        "identity_result": receipt.identity_result,
                        "action": receipt.action,
                    },
                )
                for receipt in receipts
            ]
        )
        return case_run, receipts

    def record_case_reconcile_result(
        self,
        case_id: str,
        result: dict[str, Any],
        *,
        run_id: str,
        created_at: datetime,
        evidence_ids_by_decision: dict[str, tuple[str, ...]] | None = None,
    ) -> tuple[ResolutionRun, tuple[DecisionReceipt, ...]]:
        """Persist normal resolver output as a run associated with one case.

        Parameters:
            case_id: A persisted ResolutionCase identifier.
            result: The dictionary returned by ``arche.resolve.reconcile``.
            run_id: Caller-owned opaque identifier for the resolver invocation.
            created_at: Time at which the re-resolution result is recorded.
            evidence_ids_by_decision: Persisted Evidence IDs supporting each edge.

        Returns:
            The case-associated run metrics and durable decision receipts.

        Raises:
            ValueError: If the case or any supplied Evidence ID is unknown.
        """
        if self.store.get_resolution_case(case_id) is None:
            raise ValueError(
                f"resolution case {case_id!r} does not exist; open the case before "
                "recording its resolver result"
            )
        evidence_ids_by_decision = evidence_ids_by_decision or {}
        for evidence_ids in evidence_ids_by_decision.values():
            for evidence_id in evidence_ids:
                if self.store.get_evidence(evidence_id) is None:
                    raise ValueError(
                        f"evidence {evidence_id!r} does not exist; persist Evidence "
                        "before linking it to a case decision"
                    )

        run, receipts = adapt_reconcile_result(
            result,
            run_id=run_id,
            created_at=created_at,
            evidence_ids_by_decision=evidence_ids_by_decision,
        )
        return self._record_case_resolver_receipts(
            case_id,
            run,
            receipts,
            recorded_at=created_at,
        )

    def record_reviewed_reconcile_artifact(
        self,
        case_id: str,
        observation_id: str,
        result: dict[str, Any],
        *,
        review_id: str,
        reviewed_at: datetime,
        run_id: str,
        artifact_evidence_ids_by_decision: dict[str, str],
        supporting_evidence_ids_by_decision: dict[str, tuple[str, ...]] | None = None,
        review_event_id: str | None = None,
    ) -> tuple[tuple[Evidence, ...], ResolutionRun, tuple[DecisionReceipt, ...]]:
        """Record reviewed reconcile output as Evidence before creating receipts.

        Parameters:
            case_id: Existing case that owns the successful resolver execution.
            observation_id: Persisted success Observation from the method gateway.
            result: Caller-managed current ``arche.resolve.reconcile`` output.
            review_id: Caller-managed identifier for the review of that output.
            reviewed_at: Timestamp for reviewed Evidence and receipt records.
            run_id: Caller-owned identifier for the durable resolver run.
            artifact_evidence_ids_by_decision: One Evidence ID for every emitted edge.
            supporting_evidence_ids_by_decision: Independent existing Evidence by edge.
            review_event_id: Optional caller-owned immutable review event identifier.

        Returns:
            Reviewed artifact Evidence, one persisted run, and its decision receipts.

        Raises:
            ValueError: If the Observation is not a successful deterministic
                reconciler execution, the review is incomplete, or supporting
                Evidence has not been persisted.
        """
        if self.store.get_resolution_case(case_id) is None:
            raise ValueError(f"resolution case {case_id!r} does not exist")
        observation = self.store.get_observation(observation_id)
        if observation is None:
            raise ValueError(f"resolver artifact Observation {observation_id!r} does not exist")
        if (
            observation.source_id != "resolver:arche.resolve.reconcile"
            or observation.provenance.get("kind") != "resolver_execution"
            or observation.provenance.get("outcome") != "success"
        ):
            raise ValueError(
                "reviewed reconcile artifacts require a successful "
                "arche.resolve.reconcile gateway Observation"
            )
        if not any(
            event.event_type == "method_execution" and observation_id in event.references
            for event in self.get_case_history(case_id)
        ):
            raise ValueError(
                f"resolver artifact Observation {observation_id!r} was not recorded "
                f"for case {case_id!r}"
            )
        artifact_evidence = reviewed_reconcile_evidence(
            result,
            observation_id=observation_id,
            review_id=review_id,
            evidence_ids_by_decision=artifact_evidence_ids_by_decision,
            reviewed_at=reviewed_at,
        )
        supporting_evidence_ids_by_decision = supporting_evidence_ids_by_decision or {}
        unknown_decisions = set(supporting_evidence_ids_by_decision) - {
            evidence.supports for evidence in artifact_evidence
        }
        if unknown_decisions:
            raise ValueError(
                "supporting reconcile evidence refers to decisions absent from the "
                "reviewed artifact"
            )
        combined_evidence_ids = {
            evidence.supports: (
                evidence.evidence_id,
                *supporting_evidence_ids_by_decision.get(evidence.supports, ()),
            )
            for evidence in artifact_evidence
        }
        for evidence_ids in supporting_evidence_ids_by_decision.values():
            for evidence_id in evidence_ids:
                if self.store.get_evidence(evidence_id) is None:
                    raise ValueError(
                        f"supporting evidence {evidence_id!r} does not exist; persist "
                        "it before review"
                    )
        self.store.write_evidence(artifact_evidence)
        self.store.write_case_events(
            [
                CaseEvent(
                    event_id=review_event_id or new_ledger_id("evt"),
                    case_id=case_id,
                    event_type="reviewed_resolver_evidence",
                    recorded_at=reviewed_at,
                    references=(observation_id, *(item.evidence_id for item in artifact_evidence)),
                    provenance={
                        "review_id": review_id,
                        "resolver": "arche.resolve.reconcile",
                        "artifact_hash": observation.content_hash,
                        "decision_ids": [item.supports for item in artifact_evidence],
                    },
                )
            ]
        )
        run, receipts = self.record_case_reconcile_result(
            case_id,
            result,
            run_id=run_id,
            created_at=reviewed_at,
            evidence_ids_by_decision=combined_evidence_ids,
        )
        return artifact_evidence, run, receipts

    def record_reviewed_resolution_artifact(
        self,
        case_id: str,
        observation_id: str,
        artifact: ReviewedResolutionArtifact,
        *,
        review_id: str,
        reviewed_at: datetime,
        run_id: str,
        artifact_evidence_ids_by_decision: dict[str, str],
        supporting_evidence_ids_by_decision: dict[str, tuple[str, ...]] | None = None,
        review_event_id: str | None = None,
    ) -> tuple[tuple[Evidence, ...], ResolutionRun, tuple[DecisionReceipt, ...]]:
        """Record reviewed Splink or domain output through case history.

        The artifact must describe a successful, case-linked resolver gateway
        Observation with the exact configuration that executed. Its reviewed
        edges become immutable Evidence before receipts and policy can use them.
        """
        if self.store.get_resolution_case(case_id) is None:
            raise ValueError(f"resolution case {case_id!r} does not exist")
        observation = self.store.get_observation(observation_id)
        if observation is None:
            raise ValueError(f"resolver artifact Observation {observation_id!r} does not exist")
        if (
            observation.source_id != f"resolver:{artifact.resolver}"
            or observation.provenance.get("kind") != "resolver_execution"
            or observation.provenance.get("outcome") != "success"
            or observation.provenance.get("configuration_pin") != artifact.configuration_pin
        ):
            raise ValueError(
                "reviewed resolution artifacts require a successful gateway Observation "
                "with the artifact resolver and configuration pin"
            )
        if not any(
            event.event_type == "method_execution" and observation_id in event.references
            for event in self.get_case_history(case_id)
        ):
            raise ValueError(
                f"resolver artifact Observation {observation_id!r} was not recorded "
                f"for case {case_id!r}"
            )

        artifact_evidence = reviewed_resolution_evidence(
            artifact,
            observation_id=observation_id,
            review_id=review_id,
            evidence_ids_by_decision=artifact_evidence_ids_by_decision,
        )
        supporting_evidence_ids_by_decision = supporting_evidence_ids_by_decision or {}
        artifact_decision_ids = {item.supports for item in artifact_evidence}
        unknown_decisions = set(supporting_evidence_ids_by_decision) - artifact_decision_ids
        if unknown_decisions:
            raise ValueError(
                "supporting resolution evidence refers to decisions absent from the "
                "reviewed artifact"
            )
        for evidence_ids in supporting_evidence_ids_by_decision.values():
            for evidence_id in evidence_ids:
                if self.store.get_evidence(evidence_id) is None:
                    raise ValueError(
                        f"supporting evidence {evidence_id!r} does not exist; persist "
                        "it before review"
                    )
        combined_evidence_ids = {
            evidence.supports: (
                evidence.evidence_id,
                *supporting_evidence_ids_by_decision.get(evidence.supports, ()),
            )
            for evidence in artifact_evidence
        }
        run, receipts = adapt_reviewed_resolution_artifact(
            artifact,
            run_id=run_id,
            created_at=reviewed_at,
            evidence_ids_by_decision=combined_evidence_ids,
        )
        self.store.write_evidence(artifact_evidence)
        self.store.write_case_events(
            [
                CaseEvent(
                    event_id=review_event_id or new_ledger_id("evt"),
                    case_id=case_id,
                    event_type="reviewed_resolver_evidence",
                    recorded_at=reviewed_at,
                    references=(observation_id, *(item.evidence_id for item in artifact_evidence)),
                    provenance={
                        "review_id": review_id,
                        "resolver": artifact.resolver,
                        "configuration_pin": artifact.configuration_pin,
                        "artifact_hash": observation.content_hash,
                        "decision_ids": [item.supports for item in artifact_evidence],
                    },
                )
            ]
        )
        case_run, receipts = self._record_case_resolver_receipts(
            case_id,
            run,
            receipts,
            recorded_at=reviewed_at,
        )
        return artifact_evidence, case_run, receipts

    def apply_resolution_decision_policy(
        self,
        case_id: str,
        decision_id: str,
        *,
        policy: ResolutionDecisionPolicy,
        recorded_at: datetime,
        event_id: str | None = None,
    ) -> PolicyDecision:
        """Release, review, reject, or abstain on one case decision receipt.

        This control-plane method never creates entities, claims, or links. It
        records the policy outcome in immutable case history, leaving a caller
        or human workflow to perform any consequential action.

        Parameters:
            case_id: Existing case that produced the receipt.
            decision_id: Existing receipt recorded for that case.
            policy: Evidence and source-independence requirements.
            recorded_at: Timestamp for the immutable policy event.
            event_id: Optional caller-owned immutable event identifier.

        Returns:
            The policy's operational action and its evidence basis.

        Raises:
            ValueError: If the case, receipt, or case/receipt relationship is
                unknown, or this policy has already decided the receipt.
        """
        if self.store.get_resolution_case(case_id) is None:
            raise ValueError(
                f"resolution case {case_id!r} does not exist; open the case before "
                "applying decision policy"
            )
        receipt = self.store.get_decision(decision_id)
        if receipt is None:
            raise ValueError(
                f"decision receipt {decision_id!r} does not exist; record resolver "
                "output before applying decision policy"
            )
        events = self.store.list_case_events(case_id)
        if not any(
            event.event_type == "resolver_decision" and decision_id in event.references
            for event in events
        ):
            raise ValueError(
                f"decision receipt {decision_id!r} was not recorded for case {case_id!r}"
            )
        if any(
            event.event_type == "policy_decision"
            and decision_id in event.references
            and event.provenance.get("policy_id") == policy.policy_id
            for event in events
        ):
            raise ValueError(
                f"policy {policy.policy_id!r} already decided receipt {decision_id!r} "
                f"for case {case_id!r}"
            )

        source_ids = self._evidence_source_ids(receipt.evidence_ids)
        action, reason = self._policy_action(receipt, policy, source_ids)
        outcome = PolicyDecision(
            decision_id=decision_id,
            case_id=case_id,
            action=action,
            reason=reason,
            evidence_ids=receipt.evidence_ids,
            independent_source_ids=source_ids,
            policy_id=policy.policy_id,
        )
        self.store.write_case_events(
            [
                CaseEvent(
                    event_id=event_id or new_ledger_id("evt"),
                    case_id=case_id,
                    event_type="policy_decision",
                    recorded_at=recorded_at,
                    references=(decision_id,),
                    provenance={
                        "policy_id": policy.policy_id,
                        "action": action,
                        "reason": reason,
                        "evidence_ids": list(receipt.evidence_ids),
                        "independent_source_ids": list(source_ids),
                    },
                )
            ]
        )
        return outcome

    def execute_released_policy_decision(
        self,
        decision: PolicyDecision,
        executor: PolicyDecisionExecutor,
        *,
        recorded_at: datetime,
        event_id: str | None = None,
    ) -> PolicyExecution:
        """Ask an application-controlled executor to perform one released decision.

        Parameters:
            decision: A link or create outcome previously released into case history.
            executor: Caller-owned application or human workflow implementation.
            recorded_at: Timestamp for the immutable execution event.
            event_id: Optional caller-owned immutable case-event identifier.

        Returns:
            The executor's hash-only outcome, recorded in case history.

        Raises:
            ValueError: If the decision was not released exactly as supplied, is not
                consequential, or was already submitted to an executor.
        """
        if decision.action not in {"link", "create"}:
            raise ValueError(
                "only released link or create decisions may reach an executor; "
                "review, reject, and abstain stay in case history"
            )
        history = self.get_case_history(decision.case_id)
        if not _released_policy_decision_is_recorded(history, decision):
            raise ValueError(
                f"decision {decision.decision_id!r} was not released by policy "
                f"{decision.policy_id!r} for case {decision.case_id!r}"
            )
        if any(
            event.event_type == "policy_execution" and decision.decision_id in event.references
            for event in history
        ):
            raise ValueError(
                f"decision {decision.decision_id!r} already has a recorded executor outcome"
            )
        execution = executor.execute(decision)
        if (
            execution.decision_id != decision.decision_id
            or execution.case_id != decision.case_id
            or execution.policy_id != decision.policy_id
            or execution.action != decision.action
        ):
            raise ValueError(
                "executor outcome does not match the released policy decision; "
                "return the same decision, case, policy, and action identifiers"
            )
        self.store.write_case_events(
            [
                CaseEvent(
                    event_id=event_id or new_ledger_id("evt"),
                    case_id=decision.case_id,
                    event_type="policy_execution",
                    recorded_at=recorded_at,
                    references=(decision.decision_id, execution.execution_id),
                    provenance={
                        "policy_id": decision.policy_id,
                        "action": decision.action,
                        "executor_id": execution.executor_id,
                        "outcome": execution.outcome,
                        "result_hash": execution.result_hash,
                    },
                )
            ]
        )
        return execution

    def record_reviewed_document_proposals(
        self,
        case_id: str,
        document: ParsedDocument,
        extraction: Extraction[Any],
        *,
        observation_id: str,
        source_id: str,
        recorded_at: datetime,
        review_id: str,
        claim_specs: tuple[DocumentClaimSpec, ...] = (),
        relation_specs: tuple[DocumentRelationSpec, ...] = (),
        event_id: str | None = None,
    ) -> DocumentProposalSet:
        """Record reviewed document evidence and review-pending case proposals.

        This persists the immutable document Observation, its field Evidence, and
        a value-hashed case-history event. It does not write a Claim or
        EntityRelation: a later policy or human-review step must accept a
        proposal before it enters entity memory.

        Parameters:
            case_id: Existing unresolved case that received the document.
            document: Parsed document carrying parser provenance and content hash.
            extraction: Human-reviewed document extraction with field spans.
            observation_id: Caller-owned immutable document observation ID.
            source_id: Policy-controlled source identifier.
            recorded_at: Runtime ingestion timestamp.
            review_id: Caller-managed reference to the approving review.
            claim_specs: Explicit field-to-claim mappings.
            relation_specs: Explicit field-evidence-to-relation mappings.
            event_id: Optional caller-owned immutable case event ID.

        Returns:
            Value-free claim and relationship proposals plus their durable inputs.

        Raises:
            ValueError: If the case or a proposal target entity is unknown.
        """
        if self.store.get_resolution_case(case_id) is None:
            raise ValueError(
                f"resolution case {case_id!r} does not exist; open the case before "
                "recording reviewed document proposals"
            )
        proposals = reviewed_document_proposals(
            case_id=case_id,
            document=document,
            extraction=extraction,
            observation_id=observation_id,
            source_id=source_id,
            recorded_at=recorded_at,
            review_id=review_id,
            claim_specs=claim_specs,
            relation_specs=relation_specs,
            event_id=event_id,
        )
        target_entity_ids = (
            {proposal.entity_id for proposal in proposals.claims}
            | {proposal.subject_entity_id for proposal in proposals.relations}
            | {proposal.object_entity_id for proposal in proposals.relations}
        )
        for entity_id in target_entity_ids:
            if self.store.get_entity(entity_id) is None:
                raise ValueError(
                    f"proposal entity {entity_id!r} does not exist; persist the "
                    "stable entity before recording a document proposal"
                )
        self.store.write_observations([proposals.observation])
        self.store.write_evidence(proposals.evidence)
        self.store.write_case_events([proposals.event])
        return proposals

    def accept_claim_proposal(
        self,
        proposal: ClaimProposal,
        *,
        policy: ProposalAcceptancePolicy,
        recorded_at: datetime,
        supplemental_evidence_ids: tuple[str, ...] = (),
        claim_id: str | None = None,
        event_id: str | None = None,
    ) -> ProposalAcceptance:
        """Promote a recorded claim proposal only when policy permits it.

        The policy requires distinct Observation source IDs, not merely several
        fields from one document. A conflicting active claim is recorded as a
        review outcome rather than becoming a contested ledger claim.

        Parameters:
            proposal: Claim proposal previously recorded in this case's history.
            policy: Minimum independent-source requirement for this promotion.
            recorded_at: Timestamp for the policy outcome and any accepted claim.
            supplemental_evidence_ids: Additional persisted supporting Evidence.
            claim_id: Optional caller-owned ledger claim identifier.
            event_id: Optional caller-owned immutable case event identifier.

        Returns:
            An auditable accepted or review outcome.

        Raises:
            ValueError: If the proposal is unrecorded, already decided, or cites
                missing evidence.
        """
        evidence_ids, source_ids = self._proposal_evidence(proposal, supplemental_evidence_ids)
        conflicts = tuple(
            claim.claim_id
            for claim in self.store.list_claims(proposal.entity_id)
            if claim.status == "active"
            and claim.predicate == proposal.predicate
            and claim.value_ref != proposal.value_ref
        )
        if conflicts:
            return self._record_proposal_review(
                proposal,
                policy=policy,
                recorded_at=recorded_at,
                evidence_ids=evidence_ids,
                source_ids=source_ids,
                reason="contradicts an active claim with the same predicate",
                conflicts=conflicts,
                event_id=event_id,
            )
        if len(source_ids) < policy.min_independent_sources:
            return self._record_proposal_review(
                proposal,
                policy=policy,
                recorded_at=recorded_at,
                evidence_ids=evidence_ids,
                source_ids=source_ids,
                reason="needs more independent observation sources",
                event_id=event_id,
            )
        claim = Claim(
            claim_id=claim_id or new_ledger_id("claim"),
            entity_id=proposal.entity_id,
            predicate=proposal.predicate,
            value_ref=proposal.value_ref,
            evidence_ids=evidence_ids,
            asserted_at=recorded_at,
            provenance={
                "accepted_proposal_id": proposal.proposal_id,
                "policy_id": policy.policy_id,
            },
        )
        outcome = ProposalAcceptance(
            proposal.proposal_id,
            proposal.case_id,
            "accepted",
            "meets independent-evidence requirement",
            evidence_ids,
            source_ids,
            accepted_record_id=claim.claim_id,
        )
        self.store.write_claims([claim])
        self.store.write_case_events(
            [self._acceptance_event(outcome, policy, recorded_at, event_id)]
        )
        return outcome

    def accept_relation_proposal(
        self,
        proposal: RelationProposal,
        *,
        policy: ProposalAcceptancePolicy,
        recorded_at: datetime,
        supplemental_evidence_ids: tuple[str, ...] = (),
        relation_id: str | None = None,
        event_id: str | None = None,
    ) -> ProposalAcceptance:
        """Promote a recorded relation proposal only when policy permits it.

        A relationship with the same subject and predicate but another active
        object is a contradiction signal and remains review-only.
        """
        evidence_ids, source_ids = self._proposal_evidence(proposal, supplemental_evidence_ids)
        conflicts = tuple(
            relation.relation_id
            for relation in self.store.list_relations(proposal.subject_entity_id)
            if relation.status == "active"
            and relation.subject_entity_id == proposal.subject_entity_id
            and relation.predicate == proposal.predicate
            and relation.object_entity_id != proposal.object_entity_id
        )
        if conflicts:
            return self._record_proposal_review(
                proposal,
                policy=policy,
                recorded_at=recorded_at,
                evidence_ids=evidence_ids,
                source_ids=source_ids,
                reason="contradicts an active relation with the same predicate",
                conflicts=conflicts,
                event_id=event_id,
            )
        if len(source_ids) < policy.min_independent_sources:
            return self._record_proposal_review(
                proposal,
                policy=policy,
                recorded_at=recorded_at,
                evidence_ids=evidence_ids,
                source_ids=source_ids,
                reason="needs more independent observation sources",
                event_id=event_id,
            )
        relation = EntityRelation(
            relation_id=relation_id or new_ledger_id("rel"),
            subject_entity_id=proposal.subject_entity_id,
            predicate=proposal.predicate,
            object_entity_id=proposal.object_entity_id,
            evidence_ids=evidence_ids,
            asserted_at=recorded_at,
        )
        outcome = ProposalAcceptance(
            proposal.proposal_id,
            proposal.case_id,
            "accepted",
            "meets independent-evidence requirement",
            evidence_ids,
            source_ids,
            accepted_record_id=relation.relation_id,
        )
        self.store.write_relations([relation])
        self.store.write_case_events(
            [self._acceptance_event(outcome, policy, recorded_at, event_id)]
        )
        return outcome

    def _evidence_source_ids(self, evidence_ids: tuple[str, ...]) -> tuple[str, ...]:
        """Return distinct observation sources required by durable evidence."""
        source_ids: set[str] = set()
        for evidence_id in evidence_ids:
            evidence = self.store.get_evidence(evidence_id)
            if evidence is None:
                raise ValueError(
                    f"evidence {evidence_id!r} does not exist; persist it before "
                    "applying decision policy"
                )
            observation = self.store.get_observation(evidence.observation_id)
            if observation is None:
                raise ValueError(f"evidence {evidence_id!r} lacks its required Observation")
            if observation.provenance.get("kind") in {
                "resolver_execution",
                "simulated_pod_consent",
            }:
                continue
            source_ids.add(observation.source_id)
        return tuple(sorted(source_ids))

    @staticmethod
    def _policy_action(
        receipt: DecisionReceipt,
        policy: ResolutionDecisionPolicy,
        source_ids: tuple[str, ...],
    ) -> tuple[str, str]:
        """Return a conservative operational action for one receipt."""
        if receipt.identity_result == "review" or receipt.action == "review":
            return "review", "resolver requires review"
        if receipt.identity_result == "same_entity":
            if receipt.action not in policy.releasable_actions:
                return "review", "resolver action is not releasable under this policy"
            if len(source_ids) < policy.min_independent_sources:
                return "review", "needs more independent observation sources"
            return receipt.action, "meets independent-evidence requirement"
        if receipt.identity_result == "different" and receipt.evidence_ids:
            return "reject", "resolver supplied evidence for a different-entity result"
        return "abstain", "receipt has no evidence-backed operational conclusion"

    def _proposal_evidence(
        self,
        proposal: ClaimProposal | RelationProposal,
        supplemental_evidence_ids: tuple[str, ...],
    ) -> tuple[tuple[str, ...], tuple[str, ...]]:
        """Validate durable proposal provenance and return its evidence sources."""
        kind = "claim" if isinstance(proposal, ClaimProposal) else "relation"
        if self.store.get_resolution_case(proposal.case_id) is None:
            raise ValueError(f"resolution case {proposal.case_id!r} does not exist")
        history = self.store.list_case_events(proposal.case_id)
        if not _proposal_is_recorded(history, proposal, kind):
            raise ValueError(
                f"{kind} proposal {proposal.proposal_id!r} is not recorded in case history"
            )
        if _proposal_is_decided(history, proposal.proposal_id):
            raise ValueError(
                f"proposal {proposal.proposal_id!r} already has an acceptance decision"
            )
        evidence_ids = tuple(dict.fromkeys((*proposal.evidence_ids, *supplemental_evidence_ids)))
        source_ids: set[str] = set()
        for evidence_id in evidence_ids:
            evidence = self.store.get_evidence(evidence_id)
            if evidence is None:
                raise ValueError(
                    f"evidence {evidence_id!r} does not exist; persist it before acceptance"
                )
            observation = self.store.get_observation(evidence.observation_id)
            if observation is None:
                raise ValueError(f"evidence {evidence_id!r} lacks its required Observation")
            if observation.provenance.get("kind") != "simulated_pod_consent":
                source_ids.add(observation.source_id)
        return evidence_ids, tuple(sorted(source_ids))

    def _record_proposal_review(
        self,
        proposal: ClaimProposal | RelationProposal,
        *,
        policy: ProposalAcceptancePolicy,
        recorded_at: datetime,
        evidence_ids: tuple[str, ...],
        source_ids: tuple[str, ...],
        reason: str,
        conflicts: tuple[str, ...] = (),
        event_id: str | None,
    ) -> ProposalAcceptance:
        """Persist a non-promoting acceptance-policy outcome."""
        outcome = ProposalAcceptance(
            proposal.proposal_id,
            proposal.case_id,
            "review",
            reason,
            evidence_ids,
            source_ids,
            conflicting_record_ids=conflicts,
        )
        self.store.write_case_events(
            [self._acceptance_event(outcome, policy, recorded_at, event_id)]
        )
        return outcome

    @staticmethod
    def _acceptance_event(
        outcome: ProposalAcceptance,
        policy: ProposalAcceptancePolicy,
        recorded_at: datetime,
        event_id: str | None,
    ) -> CaseEvent:
        """Represent one deterministic policy outcome in immutable case history."""
        return CaseEvent(
            event_id=event_id or new_ledger_id("evt"),
            case_id=outcome.case_id,
            event_type="proposal_acceptance",
            recorded_at=recorded_at,
            references=outcome.evidence_ids,
            provenance={
                "proposal_id": outcome.proposal_id,
                "policy_id": policy.policy_id,
                "decision": outcome.decision,
                "reason": outcome.reason,
                "independent_source_ids": list(outcome.independent_source_ids),
                "accepted_record_id": outcome.accepted_record_id,
                "conflicting_record_ids": list(outcome.conflicting_record_ids),
            },
        )


def _released_policy_decision_is_recorded(
    history: tuple[CaseEvent, ...], decision: PolicyDecision
) -> bool:
    """Return whether immutable history contains this exact released policy outcome."""
    expected = {
        "policy_id": decision.policy_id,
        "action": decision.action,
        "reason": decision.reason,
        "evidence_ids": list(decision.evidence_ids),
        "independent_source_ids": list(decision.independent_source_ids),
    }
    return any(
        event.event_type == "policy_decision"
        and event.references == (decision.decision_id,)
        and all(event.provenance.get(key) == value for key, value in expected.items())
        for event in history
    )


def _method_matches_plan(method: ResolutionMethod, event: CaseEvent) -> bool:
    """Return whether an evidence-plan event selected this exact configured method."""
    planned_methods = event.provenance.get("planned_methods")
    if not isinstance(planned_methods, list):
        return False
    return any(
        isinstance(item, dict)
        and item.get("method_id") == method.method_id
        and item.get("resolver") == method.resolver
        and item.get("policy_pin") == method.policy_pin
        and item.get("configuration_pin") == method.configuration_pin
        and item.get("estimated_cost") == method.estimated_cost
        and item.get("benchmark_id") == method.benchmark_id
        for item in planned_methods
    )


def _method_matches_event(method: ResolutionMethod, event: CaseEvent) -> bool:
    """Return whether an approval event binds the supplied method configuration."""
    return (
        event.provenance.get("method_id") == method.method_id
        and event.provenance.get("resolver") == method.resolver
        and event.provenance.get("policy_pin") == method.policy_pin
        and event.provenance.get("configuration_pin") == method.configuration_pin
        and event.provenance.get("estimated_cost") == method.estimated_cost
        and event.provenance.get("benchmark_id") == method.benchmark_id
    )


def _proposal_is_recorded(
    history: tuple[CaseEvent, ...],
    proposal: ClaimProposal | RelationProposal,
    kind: str,
) -> bool:
    """Return whether case history contains this exact review proposal."""
    key = f"{kind}_proposals"
    expected = _proposal_value(proposal)
    for event in history:
        proposals = event.provenance.get(key, ())
        if not isinstance(proposals, list):
            continue
        if any(item == expected for item in proposals):
            return True
    return False


def _proposal_is_decided(history: tuple[CaseEvent, ...], proposal_id: str) -> bool:
    """Return whether an immutable policy outcome already accepted the proposal."""
    return any(
        event.event_type == "proposal_acceptance"
        and event.provenance.get("proposal_id") == proposal_id
        and event.provenance.get("decision") == "accepted"
        for event in history
    )


def _proposal_value(proposal: ClaimProposal | RelationProposal) -> dict[str, object]:
    """Return the value-free case-history representation of one proposal."""
    if isinstance(proposal, ClaimProposal):
        return {
            "proposal_id": proposal.proposal_id,
            "entity_id": proposal.entity_id,
            "predicate": proposal.predicate,
            "value_ref": proposal.value_ref,
            "evidence_ids": list(proposal.evidence_ids),
        }
    return {
        "proposal_id": proposal.proposal_id,
        "subject_entity_id": proposal.subject_entity_id,
        "predicate": proposal.predicate,
        "object_entity_id": proposal.object_entity_id,
        "evidence_ids": list(proposal.evidence_ids),
    }


def attach(uri: str) -> ArcheEngine:
    """Attach Arche to a local DuckDB entity store.

    Example:
        >>> engine = attach("duckdb:///:memory:")
        >>> engine.store.ensure_schema()

    Parameters:
        uri: A ``duckdb:///`` URI. Use ``duckdb:///:memory:`` for an ephemeral store.

    Returns:
        An engine whose store has an idempotently initialised schema.

    Raises:
        ValueError: If ``uri`` is not a supported DuckDB URI.
        ImportError: If the optional runtime dependency is not installed.
    """
    if not uri.startswith("duckdb:///"):
        raise ValueError(
            f"unsupported Arche store URI {uri!r}; use duckdb:///:memory: or duckdb:///arche.duckdb"
        )

    database = uri.removeprefix("duckdb:///")
    if not database:
        raise ValueError(
            "DuckDB store URI needs a database path; use duckdb:///:memory: or "
            "duckdb:///arche.duckdb"
        )

    from arche.store.duckdb import DuckDBStore

    store = DuckDBStore(database)
    store.ensure_schema()
    return ArcheEngine(store=store)
