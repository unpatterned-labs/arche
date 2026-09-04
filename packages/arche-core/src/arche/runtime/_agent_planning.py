# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Value-free advice contracts for optional agentic resolution planning."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AgentPlanAdvice:
    """An agent's bounded recommendation over one persisted evidence plan.

    Free-form reasoning remains application-managed and is represented here by
    a hash. The advice may only select or abstain from plan items already
    permitted by deterministic policy and budget checks.
    """

    advice_id: str
    case_id: str
    plan_event_id: str
    advisor_id: str
    recommendation: str
    recommended_action_ids: tuple[str, ...] = ()
    recommended_method_ids: tuple[str, ...] = ()
    uncertainty_targets: tuple[str, ...] = ()
    reason_codes: tuple[str, ...] = ()
    reasoning_hash: str = ""

    def __post_init__(self) -> None:
        if not all(
            isinstance(value, str) and value
            for value in (self.advice_id, self.case_id, self.plan_event_id, self.advisor_id)
        ):
            raise ValueError("agent plan advice identifiers must be non-empty strings")
        if self.recommendation not in {"proceed", "abstain"}:
            raise ValueError("agent plan advice recommendation must be proceed or abstain")
        if self.recommendation == "abstain" and (
            self.recommended_action_ids or self.recommended_method_ids
        ):
            raise ValueError("abstaining agent plan advice cannot recommend plan items")
        for label, values in (
            ("recommended action IDs", self.recommended_action_ids),
            ("recommended method IDs", self.recommended_method_ids),
            ("uncertainty targets", self.uncertainty_targets),
            ("reason codes", self.reason_codes),
        ):
            if len(set(values)) != len(values) or not all(
                isinstance(value, str) and value for value in values
            ):
                raise ValueError(f"agent plan advice {label} must be unique non-empty strings")
        if not self.reasoning_hash.startswith("sha256:"):
            raise ValueError("agent plan advice reasoning_hash must be a sha256 reference")
