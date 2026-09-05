# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Bounded, caller-directed exports of Arche artifacts.

Exports are projections, never a second canonical store. In particular, the
SOLID projection emits a case-bound resolution assertion rather than a global
identity fact.
"""

from .solid import (
    SOLID_ASSERTION_SCHEMA,
    SolidPodClient,
    SolidPodResponse,
    SolidPodTransport,
    SolidPublicationApproval,
    SolidPublicationResult,
    approve_solid_publication,
    record_solid_publication,
    solid_resolution_assertion,
)

__all__ = [
    "SOLID_ASSERTION_SCHEMA",
    "SolidPodClient",
    "SolidPodResponse",
    "SolidPodTransport",
    "SolidPublicationApproval",
    "SolidPublicationResult",
    "approve_solid_publication",
    "record_solid_publication",
    "solid_resolution_assertion",
]
