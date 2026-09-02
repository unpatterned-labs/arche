# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Adapt reviewed document fields into vNext evidence and case proposals."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any

from ._document_observations import observation_from_document
from ._models import (
    CaseEvent,
    ClaimProposal,
    DocumentClaimSpec,
    DocumentRelationSpec,
    Evidence,
    Observation,
    RelationProposal,
    new_ledger_id,
)

if TYPE_CHECKING:
    from arche.doc._extract import Extraction
    from arche.doc.parse import ParsedDocument


@dataclass(frozen=True)
class DocumentProposalSet:
    """Evidence and review-pending proposals derived from one document."""

    observation: Observation
    evidence: tuple[Evidence, ...]
    claims: tuple[ClaimProposal, ...]
    relations: tuple[RelationProposal, ...]
    event: CaseEvent


def reviewed_document_evidence(
    document: ParsedDocument,
    extraction: Extraction[Any],
    *,
    observation_id: str,
    source_id: str,
    recorded_at: datetime,
    evidence_id_prefix: str = "ev_doc",
) -> tuple[Observation, tuple[Evidence, ...]]:
    """Turn reviewed extracted fields into provenance-backed Evidence.

    Field values deliberately do not enter runtime provenance. The Evidence
    points to the immutable document Observation and records only the field
    name, extraction method, confidence, and text location.

    Parameters:
        document: Parsed source document with artifact or text hash provenance.
        extraction: Reviewed field extraction from that document.
        observation_id: Caller-owned immutable observation identifier.
        source_id: Policy-controlled source identifier.
        recorded_at: Runtime ingestion timestamp.
        evidence_id_prefix: Namespace used to derive stable field evidence IDs.

    Returns:
        The document Observation and one Evidence item for every reviewed field.

    Raises:
        ValueError: If the extraction has no fields or a field name is unsafe for
            a durable evidence identifier.
    """
    if not extraction.fields:
        raise ValueError("reviewed document extraction needs at least one field")
    observation = observation_from_document(
        document,
        observation_id=observation_id,
        source_id=source_id,
        recorded_at=recorded_at,
    )
    evidence: list[Evidence] = []
    for field_name, field in sorted(extraction.fields.items()):
        if not field_name or any(char.isspace() for char in field_name):
            raise ValueError("reviewed document field names must be non-empty identifiers")
        provenance: dict[str, object] = {
            "field": field_name,
            "extraction_source": field.source,
            "confidence": field.confidence,
        }
        if field.span is not None:
            provenance["span"] = list(field.span)
        if field.page is not None:
            provenance["page"] = field.page
        evidence.append(
            Evidence(
                evidence_id=f"{evidence_id_prefix}:{observation_id}:{field_name}",
                observation_id=observation.observation_id,
                kind="document_field",
                supports="claim_proposal",
                provenance=provenance,
            )
        )
    return observation, tuple(evidence)


def reviewed_document_proposals(
    *,
    case_id: str,
    document: ParsedDocument,
    extraction: Extraction[Any],
    observation_id: str,
    source_id: str,
    recorded_at: datetime,
    review_id: str,
    claim_specs: tuple[DocumentClaimSpec, ...] = (),
    relation_specs: tuple[DocumentRelationSpec, ...] = (),
    event_id: str | None = None,
) -> DocumentProposalSet:
    """Build reviewed document proposals without asserting entity memory.

    A caller supplies the semantic mapping deliberately: an extractor finding a
    field named ``supplier`` does not establish whether it names an organisation,
    estate, brand, or recipient. Values are represented as hashes so this return
    object and its case-history event remain safe to persist without raw document
    values.
    """
    if not review_id:
        raise ValueError("review_id is required before document fields can propose claims")
    observation, evidence = reviewed_document_evidence(
        document,
        extraction,
        observation_id=observation_id,
        source_id=source_id,
        recorded_at=recorded_at,
    )
    evidence_by_field = {
        field_name: item
        for item in evidence
        if isinstance(field_name := item.provenance.get("field"), str)
    }
    claims = tuple(
        _claim_proposal(
            spec,
            case_id=case_id,
            extraction=extraction,
            evidence_by_field=evidence_by_field,
            recorded_at=recorded_at,
            review_id=review_id,
        )
        for spec in claim_specs
    )
    relations = tuple(
        _relation_proposal(
            spec,
            case_id=case_id,
            evidence_by_field=evidence_by_field,
            recorded_at=recorded_at,
            review_id=review_id,
        )
        for spec in relation_specs
    )
    event = CaseEvent(
        event_id=event_id or new_ledger_id("evt"),
        case_id=case_id,
        event_type="reviewed_document_proposals",
        recorded_at=recorded_at,
        references=(observation.observation_id, *(item.evidence_id for item in evidence)),
        provenance={
            "review_id": review_id,
            "claim_proposals": [_claim_event_value(item) for item in claims],
            "relation_proposals": [_relation_event_value(item) for item in relations],
        },
    )
    return DocumentProposalSet(observation, evidence, claims, relations, event)


def _claim_proposal(
    spec: DocumentClaimSpec,
    *,
    case_id: str,
    extraction: Extraction[Any],
    evidence_by_field: dict[str, Evidence],
    recorded_at: datetime,
    review_id: str,
) -> ClaimProposal:
    """Build one claim proposal from an explicit reviewed field mapping."""
    field = extraction.fields.get(spec.field)
    evidence = evidence_by_field.get(spec.field)
    if field is None or evidence is None:
        raise ValueError(f"claim proposal field {spec.field!r} is not in the reviewed extraction")
    return ClaimProposal(
        proposal_id=new_ledger_id("proposal"),
        case_id=case_id,
        entity_id=spec.entity_id,
        predicate=spec.predicate,
        value_ref=_value_ref(field.value),
        evidence_ids=(evidence.evidence_id,),
        proposed_at=recorded_at,
        review_id=review_id,
    )


def _relation_proposal(
    spec: DocumentRelationSpec,
    *,
    case_id: str,
    evidence_by_field: dict[str, Evidence],
    recorded_at: datetime,
    review_id: str,
) -> RelationProposal:
    """Build one relation proposal from explicitly selected field evidence."""
    if not spec.evidence_fields:
        raise ValueError("relation proposals need at least one reviewed evidence field")
    missing = [field for field in spec.evidence_fields if field not in evidence_by_field]
    if missing:
        raise ValueError(f"relation proposal fields are not in the reviewed extraction: {missing}")
    return RelationProposal(
        proposal_id=new_ledger_id("proposal"),
        case_id=case_id,
        subject_entity_id=spec.subject_entity_id,
        predicate=spec.predicate,
        object_entity_id=spec.object_entity_id,
        evidence_ids=tuple(evidence_by_field[field].evidence_id for field in spec.evidence_fields),
        proposed_at=recorded_at,
        review_id=review_id,
    )


def _value_ref(value: object) -> str:
    """Return a stable content reference without persisting a document value."""
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return f"sha256:{hashlib.sha256(payload.encode()).hexdigest()}"


def _claim_event_value(proposal: ClaimProposal) -> dict[str, object]:
    """Return the persistable, value-free shape of one claim proposal."""
    return {
        "proposal_id": proposal.proposal_id,
        "entity_id": proposal.entity_id,
        "predicate": proposal.predicate,
        "value_ref": proposal.value_ref,
        "evidence_ids": list(proposal.evidence_ids),
    }


def _relation_event_value(proposal: RelationProposal) -> dict[str, object]:
    """Return the persistable shape of one relation proposal."""
    return {
        "proposal_id": proposal.proposal_id,
        "subject_entity_id": proposal.subject_entity_id,
        "predicate": proposal.predicate,
        "object_entity_id": proposal.object_entity_id,
        "evidence_ids": list(proposal.evidence_ids),
    }
