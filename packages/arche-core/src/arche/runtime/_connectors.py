# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""The narrow boundary between permitted actions and evidence connectors."""

from __future__ import annotations

from typing import Protocol

from ._models import EvidenceAction, Observation, ToolCapability


class EvidenceConnector(Protocol):
    """A read-only connector that turns one permitted action into an Observation."""

    capability: ToolCapability

    def observe(self, action: EvidenceAction) -> Observation:
        """Return an immutable Observation for the permitted action."""
