# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Deterministic control-plane helpers for unresolved resolution cases."""

from __future__ import annotations

from ._models import EvidenceGap, ResolutionCase


def what_would_resolve(case: ResolutionCase) -> tuple[EvidenceGap, ...]:
    """Return the case's known evidence gaps in deterministic priority order.

    Parameters:
        case: An unresolved case carrying the gaps identified by deterministic
            resolution logic.

    Returns:
        The evidence gaps, ordered by priority and then field name.
    """
    return tuple(sorted(case.evidence_gaps, key=lambda gap: (gap.priority, gap.field)))
