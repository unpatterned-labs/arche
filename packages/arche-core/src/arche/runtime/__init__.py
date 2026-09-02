# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""The vNext runtime entry point and durable domain contracts."""

from __future__ import annotations

from ._models import DecisionReceipt, Entity, Evidence, Observation, new_entity_id
from .engine import ArcheEngine, attach

__all__ = [
    "ArcheEngine",
    "DecisionReceipt",
    "Entity",
    "Evidence",
    "Observation",
    "attach",
    "new_entity_id",
]
