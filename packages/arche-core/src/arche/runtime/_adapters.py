# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Adapters that record current resolver outputs in vNext contracts."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import TYPE_CHECKING, Any

from ._models import DecisionReceipt, ResolutionRun

if TYPE_CHECKING:
    from arche.resolve.coreference import Receipt


_EDGE_OUTCOMES = {
    "match": ("same_entity", "link"),
    "review": ("review", "review"),
    "different": ("different", "reject"),
    "no_match": ("different", "reject"),
}


def adapt_coreference_receipt(
    receipt: Receipt,
    *,
    created_at: datetime,
    evidence_ids: tuple[str, ...] = (),
) -> DecisionReceipt:
    """Translate a pairwise resolver receipt without rerunning it.

    Parameters:
        receipt: The existing ``arche.resolve.coreference.Receipt`` output.
        created_at: Time at which this receipt enters the durable runtime.
        evidence_ids: Persisted Evidence IDs backing the decision, if available.

    Returns:
        A vNext receipt retaining the existing decision identifier, score, and
        resolver provenance.
    """
    schema = f"arche.resolve.coreference.receipt.v{receipt.pins.get('receipt_schema', 1)}"
    return DecisionReceipt(
        decision_id=receipt.decision_id,
        identity_result=receipt.identity,
        action=receipt.action,
        evidence_ids=evidence_ids,
        created_at=created_at,
        raw_score=receipt.score,
        policy_pin=f"arche.resolve.coreference:{receipt.jurisdiction}",
        schema_pin=schema,
        provenance={
            "resolver_pins": dict(receipt.pins),
            "factors": dict(receipt.factors),
            "gate": dict(receipt.gate),
            "vetoes": dict(receipt.vetoes),
        },
    )


def adapt_reconcile_result(
    result: Mapping[str, Any],
    *,
    run_id: str,
    created_at: datetime,
    evidence_ids_by_decision: Mapping[str, tuple[str, ...]] | None = None,
) -> tuple[ResolutionRun, tuple[DecisionReceipt, ...]]:
    """Translate one current ``reconcile`` result into vNext records.

    Parameters:
        result: The dictionary returned by ``arche.resolve.reconcile``.
        run_id: Caller-owned opaque ID for this resolver invocation.
        created_at: Time at which this run enters the durable runtime.
        evidence_ids_by_decision: Optional persisted Evidence IDs by edge ID.

    Returns:
        One run-metric record and the receipts emitted by the current resolver.

    Raises:
        ValueError: If the result cannot be identified as a current resolver run.
    """
    pins = _mapping(result.get("pins"), "result.pins")
    matches = _sequence(result.get("matches"), "result.matches")
    blocking = _mapping(result.get("blocking"), "result.blocking")
    candidate_pairs = _integer(blocking.get("candidate_pairs"), "candidate_pairs")
    evidence_ids_by_decision = evidence_ids_by_decision or {}

    receipts: list[DecisionReceipt] = []
    for edge in matches:
        edge_mapping = _mapping(edge, "result.matches item")
        decision_id = _string(edge_mapping.get("decision_id"), "decision_id")
        decision = _string(edge_mapping.get("decision"), "decision")
        try:
            identity_result, action = _EDGE_OUTCOMES[decision]
        except KeyError:
            raise ValueError(f"unsupported reconcile decision {decision!r}") from None
        receipts.append(
            DecisionReceipt(
                decision_id=decision_id,
                identity_result=identity_result,
                action=action,
                evidence_ids=tuple(evidence_ids_by_decision.get(decision_id, ())),
                created_at=created_at,
                raw_score=_number(edge_mapping.get("score"), "score"),
                policy_pin=f"arche.resolve.reconcile:{pins.get('engine', 'unknown')}",
                schema_pin="arche.crosswalk_edge.v1",
                provenance={
                    "resolver_pins": dict(pins),
                    "edge": {
                        key: value
                        for key, value in edge_mapping.items()
                        if key != "decision_id"
                    },
                },
            )
        )

    match_count = sum(receipt.identity_result == "same_entity" for receipt in receipts)
    review_count = sum(receipt.identity_result == "review" for receipt in receipts)
    emitted_decisions = len(receipts)
    if emitted_decisions > candidate_pairs:
        raise ValueError("reconcile result has more decisions than candidate pairs")

    return (
        ResolutionRun(
            run_id=run_id,
            resolver="arche.resolve.reconcile",
            created_at=created_at,
            candidate_pairs=candidate_pairs,
            emitted_decisions=emitted_decisions,
            match_count=match_count,
            review_count=review_count,
            unsurfaced_pairs=candidate_pairs - emitted_decisions,
            provenance={"resolver_pins": dict(pins), "blocking": dict(blocking)},
        ),
        tuple(receipts),
    )


def _mapping(value: object, name: str) -> Mapping[str, Any]:
    """Validate a resolver mapping without accepting arbitrary objects."""
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be a mapping")
    return value


def _sequence(value: object, name: str) -> tuple[object, ...]:
    """Validate a resolver sequence without accepting text as an edge list."""
    if isinstance(value, (str, bytes)) or not isinstance(value, (list, tuple)):
        raise ValueError(f"{name} must be a sequence")
    return tuple(value)


def _string(value: object, name: str) -> str:
    """Return a required resolver string field."""
    if not isinstance(value, str) or not value:
        raise ValueError(f"{name} must be a non-empty string")
    return value


def _integer(value: object, name: str) -> int:
    """Return a non-negative resolver count."""
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")
    return value


def _number(value: object, name: str) -> float | None:
    """Return an optional numeric resolver score."""
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be numeric when present")
    return float(value)
