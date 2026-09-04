# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Reviewed artifact contracts shared by Splink and domain matcher adapters."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from ._models import DecisionReceipt, Evidence, ResolutionRun


@dataclass(frozen=True)
class ReviewedResolutionEdge:
    """A reviewer-normalized conclusion from one non-core resolver output."""

    decision_id: str
    identity_result: str
    action: str
    raw_score: float | None = None
    probability: float | None = None

    def __post_init__(self) -> None:
        if not self.decision_id:
            raise ValueError("reviewed resolution edge needs a decision_id")
        if self.identity_result not in {"same_entity", "review", "different"}:
            raise ValueError("reviewed resolution edge has an unsupported identity_result")
        if self.action not in {"link", "create", "review", "reject"}:
            raise ValueError("reviewed resolution edge has an unsupported action")


@dataclass(frozen=True)
class ReviewedResolutionArtifact:
    """A value-free reviewed output artifact from Splink or a domain matcher."""

    resolver: str
    configuration_pin: str
    candidate_pairs: int
    edges: tuple[ReviewedResolutionEdge, ...]

    def __post_init__(self) -> None:
        if not self.resolver or not self.configuration_pin:
            raise ValueError("reviewed resolution artifact needs resolver and configuration pins")
        if self.candidate_pairs < 0 or len(self.edges) > self.candidate_pairs:
            raise ValueError("reviewed resolution artifact has invalid candidate-pair counts")
        if len({edge.decision_id for edge in self.edges}) != len(self.edges):
            raise ValueError("reviewed resolution artifact decision IDs must be unique")


def adapt_reviewed_resolution_artifact(
    artifact: ReviewedResolutionArtifact,
    *,
    run_id: str,
    created_at: datetime,
    evidence_ids_by_decision: dict[str, tuple[str, ...]],
) -> tuple[ResolutionRun, tuple[DecisionReceipt, ...]]:
    """Adapt normalized Splink or domain edges without inferring their labels."""
    if set(evidence_ids_by_decision) != {edge.decision_id for edge in artifact.edges}:
        raise ValueError("reviewed resolution evidence must cover exactly the emitted decisions")
    receipts = tuple(
        DecisionReceipt(
            decision_id=edge.decision_id,
            identity_result=edge.identity_result,
            action=edge.action,
            evidence_ids=evidence_ids_by_decision[edge.decision_id],
            created_at=created_at,
            raw_score=edge.raw_score,
            probability=edge.probability,
            policy_pin=f"{artifact.resolver}:{artifact.configuration_pin}",
            schema_pin="arche.reviewed_resolution_artifact.v1",
            provenance={
                "resolver": artifact.resolver,
                "configuration_pin": artifact.configuration_pin,
            },
        )
        for edge in artifact.edges
    )
    return (
        ResolutionRun(
            run_id=run_id,
            resolver=artifact.resolver,
            created_at=created_at,
            candidate_pairs=artifact.candidate_pairs,
            emitted_decisions=len(receipts),
            match_count=sum(item.identity_result == "same_entity" for item in receipts),
            review_count=sum(item.identity_result == "review" for item in receipts),
            unsurfaced_pairs=artifact.candidate_pairs - len(receipts),
            provenance={"configuration_pin": artifact.configuration_pin},
        ),
        receipts,
    )


def reviewed_resolution_evidence(
    artifact: ReviewedResolutionArtifact,
    *,
    observation_id: str,
    review_id: str,
    evidence_ids_by_decision: dict[str, str],
) -> tuple[Evidence, ...]:
    """Create traceability Evidence for each reviewed non-core resolver edge."""
    if not review_id:
        raise ValueError("reviewed resolution evidence needs a review_id")
    if set(evidence_ids_by_decision) != {edge.decision_id for edge in artifact.edges}:
        raise ValueError(
            "reviewed resolution evidence IDs must cover exactly the emitted decisions"
        )
    return tuple(
        Evidence(
            evidence_ids_by_decision[edge.decision_id],
            observation_id,
            "reviewed_resolution_edge",
            edge.decision_id,
            provenance={
                "review_id": review_id,
                "resolver": artifact.resolver,
                "configuration_pin": artifact.configuration_pin,
                "identity_result": edge.identity_result,
                "action": edge.action,
            },
        )
        for edge in artifact.edges
    )
