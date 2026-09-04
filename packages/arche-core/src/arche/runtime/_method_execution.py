# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""The explicit boundary for running a planned resolver method."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Protocol

from ._models import ResolutionCase, ResolutionMethod


@dataclass(frozen=True)
class ResolutionMethodExecution:
    """A hash-only result reported by the application-owned resolver adapter."""

    execution_id: str
    method_id: str
    configuration_pin: str
    outcome: str
    result_hash: str
    actual_cost: float
    executor_id: str = "caller-owned"

    def __post_init__(self) -> None:
        if not all(
            isinstance(value, str) and value
            for value in (
                self.execution_id,
                self.method_id,
                self.configuration_pin,
                self.outcome,
                self.result_hash,
                self.executor_id,
            )
        ):
            raise ValueError("resolution method execution identifiers must be non-empty strings")
        if self.outcome not in {"success", "failed"}:
            raise ValueError("resolution method execution outcome must be success or failed")
        if isinstance(self.actual_cost, bool) or not isinstance(self.actual_cost, (int, float)):
            raise ValueError("resolution method execution actual_cost must be numeric")
        if self.actual_cost < 0:
            raise ValueError("resolution method execution actual_cost must be non-negative")


class ResolutionMethodExecutor(Protocol):
    """Application adapter that runs a configured resolver without changing Arche state."""

    def execute(self, case: ResolutionCase, method: ResolutionMethod) -> ResolutionMethodExecution:
        """Run the approved method and return only its immutable result reference."""


class PinnedResolutionMethodExecutor:
    """Bind a caller-owned runner to one resolver identifier and executor pin."""

    def __init__(
        self,
        resolver: str,
        executor_id: str,
        runner: Callable[[ResolutionCase, ResolutionMethod], ResolutionMethodExecution],
    ) -> None:
        if not resolver or not executor_id:
            raise ValueError("pinned resolver executor needs resolver and executor_id")
        self.resolver = resolver
        self.executor_id = executor_id
        self._runner = runner

    def execute(self, case: ResolutionCase, method: ResolutionMethod) -> ResolutionMethodExecution:
        """Run only the resolver this adapter was explicitly configured to own."""
        if method.resolver != self.resolver:
            raise ValueError(
                f"executor {self.executor_id!r} is pinned to {self.resolver!r}, not "
                f"{method.resolver!r}"
            )
        execution = self._runner(case, method)
        if (
            execution.method_id != method.method_id
            or execution.configuration_pin != method.configuration_pin
        ):
            raise ValueError("runner result does not match the requested method configuration")
        return replace(execution, executor_id=self.executor_id)


class SplinkResolutionMethodExecutor(PinnedResolutionMethodExecutor):
    """Caller-owned adapter for one pinned Splink runner."""

    def __init__(
        self,
        executor_id: str,
        runner: Callable[[ResolutionCase, ResolutionMethod], ResolutionMethodExecution],
    ) -> None:
        super().__init__("splink", executor_id, runner)


class DomainResolutionMethodExecutor(PinnedResolutionMethodExecutor):
    """Caller-owned adapter for one pinned domain matcher runner."""

    def __init__(
        self,
        resolver: str,
        executor_id: str,
        runner: Callable[[ResolutionCase, ResolutionMethod], ResolutionMethodExecution],
    ) -> None:
        if not resolver.startswith("domain."):
            raise ValueError("domain resolver identifiers must start with 'domain.'")
        super().__init__(resolver, executor_id, runner)
