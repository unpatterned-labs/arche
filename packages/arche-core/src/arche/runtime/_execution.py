# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""The explicit application boundary for released resolution decisions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from ._models import PolicyDecision


@dataclass(frozen=True)
class PolicyExecution:
    """An application-reported outcome for one released PolicyDecision."""

    execution_id: str
    decision_id: str
    case_id: str
    policy_id: str
    action: str
    executor_id: str
    outcome: str
    result_hash: str

    def __post_init__(self) -> None:
        if not all(
            isinstance(value, str) and value
            for value in (
                self.execution_id,
                self.decision_id,
                self.case_id,
                self.policy_id,
                self.action,
                self.executor_id,
                self.outcome,
                self.result_hash,
            )
        ):
            raise ValueError("policy execution fields must be non-empty strings")
        if self.outcome not in {"applied", "failed"}:
            raise ValueError("policy execution outcome must be applied or failed")


class PolicyDecisionExecutor(Protocol):
    """Application or human workflow that explicitly performs a released decision."""

    def execute(self, decision: PolicyDecision) -> PolicyExecution:
        """Perform the caller-controlled action and return a hash-only outcome."""
