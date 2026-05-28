# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Policy layer - jurisdiction-aware enforcement of data protection statutes.

Per Stage 1 PRD §6. Loads machine-readable YAML statute files for the four
launch jurisdictions (NDPA-2023, POPIA, Kenya DPA, Ghana DPA), routes each
detection through the applicable statute, and applies one of six closed
actions:

    mask         - replace with category-label placeholder
    tokenize     - replace with deterministic non-reversible token
    drop         - remove span entirely
    generalize   - replace with less-specific value
    audit        - leave in place but record audit event
    retain       - leave in place without audit event

The action set is deliberately closed and small. Each action is unambiguous
and testable. The statute files (under `statutes/`) are versioned, community-
reviewable, and editable without code changes.

Public API:
    from arche.policy import load_statute, apply_policy, PolicyOutcome, Statute
    from arche.policy import ACTIONS, list_available_statutes
"""

from arche.policy.engine import (
    ACTIONS,
    PolicyOutcome,
    Statute,
    apply_policy,
    list_available_statutes,
    load_statute,
)

__all__ = [
    "ACTIONS",
    "PolicyOutcome",
    "Statute",
    "apply_policy",
    "list_available_statutes",
    "load_statute",
]
