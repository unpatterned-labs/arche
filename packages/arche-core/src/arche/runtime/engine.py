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
from typing import TYPE_CHECKING, Any

from arche.runtime._adapters import adapt_reconcile_result
from arche.runtime._document_proposals import (
    DocumentProposalSet,
    reviewed_document_proposals,
)
from arche.runtime._models import (
    ActionObservation,
    CaseEvent,
    Claim,
    ClaimProposal,
    DocumentClaimSpec,
    DocumentRelationSpec,
    EntityMemory,
    EntityRelation,
    Observation,
    PolicyDecision,
    ProposalAcceptance,
    ProposalAcceptancePolicy,
    RelationProposal,
    ResolutionDecisionPolicy,
    ResolutionRun,
    new_ledger_id,
)
from arche.runtime._planning import (
    DeterministicResolutionPlanner,
    EvidencePlan,
    ResolutionBudget,
)
from arche.store.base import ArcheStore

if TYPE_CHECKING:
    from arche.doc._extract import Extraction
    from arche.doc.parse import ParsedDocument
    from arche.runtime._connectors import EvidenceConnector
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
        return self.ingest_action_observation(action_id, connector.observe(action))

    def plan_case(
        self,
        case_id: str,
        *,
        capabilities: tuple[ToolCapability, ...],
        budget: ResolutionBudget,
    ) -> EvidencePlan:
        """Assess a case and select bounded, permitted evidence actions.

        Parameters:
            case_id: A persisted ResolutionCase identifier.
            capabilities: Read-only capabilities available to execute now.
            budget: Hard maximum action count and estimated cost.

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
            case,
            self.store.list_evidence_actions(case_id),
            capabilities,
            budget,
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
            },
        )
        self.store.write_case_events([event])
        return event

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
                    recorded_at=created_at,
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
