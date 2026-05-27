# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Workflow layer - composition primitives for identity workflows.

This is what makes arche a framework rather than a library of detectors.
Workflows compose detect + addr + policy + resolve + audit into production-
ready pipelines.

Two reference workflows ship in Stage 1 (PRD §7):

    arche.workflow.redact   - general redaction workflow
    arche.workflow.dsar     - citizen-side Data Subject Access Request
                              (draft-only in Stage 1; org-side in Stage 3;
                              autonomous dispatch in Stage 4)

Public API:
    from arche.workflow import Pipeline, Result, Detection
    from arche.workflow.dsar import DSARWorkflow  # Week 3
"""

from arche.workflow._primitive import Detection, Pipeline, Result
from arche.workflow.dsar import (
    DSARDraft,
    DSAROrganization,
    DSARRequestor,
    DSARResult,
    DSARWorkflow,
)

__all__ = [
    "Pipeline",
    "Result",
    "Detection",
    "DSARWorkflow",
    "DSARRequestor",
    "DSAROrganization",
    "DSARDraft",
    "DSARResult",
]
