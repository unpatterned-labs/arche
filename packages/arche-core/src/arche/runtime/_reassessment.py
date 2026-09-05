# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Read-only evidence-gap reassessment for persisted resolution cases."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from ._models import ResolutionCase

if TYPE_CHECKING:
    from arche.store.base import ArcheStore


@dataclass(frozen=True)
class CaseReassessment:
    """The value-free field coverage gained through reviewed action evidence."""

    case_id: str
    reviewed_fields: tuple[str, ...]
    resolved_gap_fields: tuple[str, ...]
    remaining_gap_fields: tuple[str, ...]


def reassess_case(store: ArcheStore, case_id: str) -> CaseReassessment:
    """Return the reviewed field coverage and remaining gaps for one case.

    This never alters the stored case. It derives a temporary planning view from
    reviewed Evidence events, keeping source values outside the runtime.

    Parameters:
        store: Canonical store containing the case and immutable history.
        case_id: Opaque ResolutionCase identifier to inspect.

    Returns:
        Reviewed field labels and the gaps they can satisfy.

    Raises:
        ValueError: If the case does not exist.
    """
    case = store.get_resolution_case(case_id)
    if case is None:
        raise ValueError(f"resolution case {case_id!r} does not exist")
    return _reassess(case, store.list_case_events(case_id))


def reassessed_case(store: ArcheStore, case: ResolutionCase) -> ResolutionCase:
    """Return a temporary case view suitable for deterministic planning."""
    assessment = _reassess(case, store.list_case_events(case.case_id))
    intent = case.intent
    if intent is not None:
        intent = replace(
            intent,
            available_fields=tuple(
                sorted(set(intent.available_fields) | set(assessment.reviewed_fields))
            ),
        )
    return replace(
        case,
        evidence_gaps=tuple(
            gap for gap in case.evidence_gaps if gap.field not in assessment.resolved_gap_fields
        ),
        intent=intent,
    )


def _reassess(case: ResolutionCase, history: tuple) -> CaseReassessment:
    """Derive reviewed labels and satisfied gap fields from immutable events."""
    reviewed_fields: set[str] = set()
    for event in history:
        if event.event_type == "reviewed_action_evidence":
            reviewed_fields.update(
                str(field) for field in event.provenance.get("reviewed_fields", ())
            )
        elif event.event_type == "reviewed_document_evidence":
            reviewed_fields.update(
                str(item["field"])
                for item in event.provenance.get("field_evidence", ())
                if isinstance(item, dict) and isinstance(item.get("field"), str)
            )
    ordered_fields = tuple(sorted(reviewed_fields))
    ordered_gaps = tuple(sorted(case.evidence_gaps, key=lambda gap: (gap.priority, gap.field)))
    resolved = tuple(gap.field for gap in ordered_gaps if gap.field in reviewed_fields)
    remaining = tuple(gap.field for gap in ordered_gaps if gap.field not in reviewed_fields)
    return CaseReassessment(case.case_id, ordered_fields, resolved, remaining)
