# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Caller-owned, hash-addressed benchmark artifacts for optional methods."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from datetime import datetime
from hashlib import sha256
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ._planning import MethodBenchmarkQualification


BENCHMARK_RESULT_BUNDLE_SCHEMA = "arche.benchmark_result_bundle.v1"


def _canonical_json(value: object) -> str:
    """Return the one serialization used when hashing an evaluation artifact."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


@dataclass(frozen=True)
class BenchmarkResultBundle:
    """A complete, caller-owned record of one benchmark evaluation.

    The bundle deliberately stores raw counts rather than a self-certified
    accuracy verdict.  A result with partial or absent truth is still useful
    operational evidence, but cannot enable a planned resolver method.
    """

    bundle_id: str
    method_id: str
    resolver: str
    configuration_pin: str
    benchmark_id: str
    dataset_id: str
    evaluator_pin: str
    completed_at: datetime
    truth_coverage: str
    candidate_pairs: int
    auto_match_count: int
    review_count: int
    true_pair_count: int | None = None
    blocking_true_pair_count: int | None = None
    true_positive_count: int | None = None
    false_positive_count: int | None = None
    reviewed_true_pair_count: int | None = None
    provenance: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not all(
            isinstance(value, str) and value
            for value in (
                self.bundle_id,
                self.method_id,
                self.resolver,
                self.configuration_pin,
                self.benchmark_id,
                self.dataset_id,
                self.evaluator_pin,
            )
        ):
            raise ValueError("benchmark result bundle identifiers must be non-empty strings")
        if self.truth_coverage not in {"complete", "partial", "unlabelled"}:
            raise ValueError("truth_coverage must be complete, partial, or unlabelled")
        count_values = (
            self.candidate_pairs,
            self.auto_match_count,
            self.review_count,
            self.true_pair_count,
            self.blocking_true_pair_count,
            self.true_positive_count,
            self.false_positive_count,
            self.reviewed_true_pair_count,
        )
        if any(
            value is not None and (isinstance(value, bool) or value < 0) for value in count_values
        ):
            raise ValueError("benchmark result bundle counts must be non-negative integers")
        if self.auto_match_count + self.review_count > self.candidate_pairs:
            raise ValueError("benchmark decisions cannot exceed candidate pairs")
        if self.truth_coverage == "complete":
            if any(
                value is None
                for value in (
                    self.true_pair_count,
                    self.blocking_true_pair_count,
                    self.true_positive_count,
                    self.false_positive_count,
                    self.reviewed_true_pair_count,
                )
            ):
                raise ValueError("complete benchmark truth needs all outcome counts")
            if self.blocking_true_pair_count > self.true_pair_count:
                raise ValueError("blocking true pairs cannot exceed known true pairs")
            if self.true_positive_count > self.true_pair_count:
                raise ValueError("true positives cannot exceed known true pairs")
            if self.reviewed_true_pair_count > self.review_count:
                raise ValueError("reviewed true pairs cannot exceed review decisions")
            if self.true_positive_count + self.false_positive_count != self.auto_match_count:
                raise ValueError("complete truth must account for every auto match")
        elif any(
            value is not None
            for value in (
                self.true_pair_count,
                self.blocking_true_pair_count,
                self.true_positive_count,
                self.false_positive_count,
                self.reviewed_true_pair_count,
            )
        ):
            raise ValueError("partial or unlabelled truth cannot claim complete outcome counts")
        try:
            _canonical_json(dict(self.provenance))
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "benchmark result bundle provenance must be JSON serializable"
            ) from exc

    @property
    def result_hash(self) -> str:
        """The content hash callers pin into qualifications and plans."""
        return "sha256:" + sha256(_canonical_json(self._record_without_hash()).encode()).hexdigest()

    @property
    def has_complete_truth(self) -> bool:
        """Whether this artifact can support a positive method qualification."""
        return self.truth_coverage == "complete"

    def _record_without_hash(self) -> dict[str, object]:
        record = asdict(self)
        record["schema"] = BENCHMARK_RESULT_BUNDLE_SCHEMA
        record["completed_at"] = self.completed_at.isoformat()
        record["provenance"] = dict(self.provenance)
        return record

    def to_record(self) -> dict[str, object]:
        """Return a JSON-safe record containing a self-verifying content hash."""
        return {**self._record_without_hash(), "result_hash": self.result_hash}


def benchmark_result_bundle_from_record(record: Mapping[str, object]) -> BenchmarkResultBundle:
    """Load one saved bundle and refuse corruption or a different schema."""
    if record.get("schema") != BENCHMARK_RESULT_BUNDLE_SCHEMA:
        raise ValueError("unsupported benchmark result bundle schema")
    supplied_hash = record.get("result_hash")
    if not isinstance(supplied_hash, str):
        raise ValueError("benchmark result bundle needs result_hash")
    values = {key: value for key, value in record.items() if key not in {"schema", "result_hash"}}
    completed_at = values.get("completed_at")
    if not isinstance(completed_at, str):
        raise ValueError("benchmark result bundle completed_at must be an ISO timestamp")
    values["completed_at"] = datetime.fromisoformat(completed_at)
    bundle = BenchmarkResultBundle(**values)  # type: ignore[arg-type]
    if bundle.result_hash != supplied_hash:
        raise ValueError("benchmark result bundle hash does not match its contents")
    return bundle


def read_benchmark_result_bundle(path: str | Path) -> BenchmarkResultBundle:
    """Read a caller-managed evaluation bundle from a chosen location."""
    return benchmark_result_bundle_from_record(json.loads(Path(path).read_text(encoding="utf-8")))


def write_benchmark_result_bundle(path: str | Path, bundle: BenchmarkResultBundle) -> str:
    """Write a bundle only to the explicit, caller-chosen destination."""
    destination = Path(path)
    destination.write_text(json.dumps(bundle.to_record(), indent=2) + "\n", encoding="utf-8")
    return bundle.result_hash


def qualification_from_evaluated_result(
    bundle: BenchmarkResultBundle,
    *,
    qualification_id: str,
    qualification_policy_pin: str,
    qualified: bool,
) -> MethodBenchmarkQualification:
    """Create a planner qualification from exactly one completed evaluation.

    ``qualified`` is deliberately a caller policy conclusion, rather than an
    implicit threshold hidden in the runtime.  Positive qualifications require
    complete truth; review-pack artifacts with unlabelled rows cannot be
    promoted by this function.
    """
    if qualified and not bundle.has_complete_truth:
        raise ValueError("only a complete-truth benchmark result can qualify a method")
    from ._planning import MethodBenchmarkQualification

    return MethodBenchmarkQualification(
        qualification_id=qualification_id,
        method_id=bundle.method_id,
        resolver=bundle.resolver,
        configuration_pin=bundle.configuration_pin,
        benchmark_id=bundle.benchmark_id,
        dataset_id=bundle.dataset_id,
        evaluator_pin=bundle.evaluator_pin,
        result_hash=bundle.result_hash,
        qualified=qualified,
        bundle_id=bundle.bundle_id,
        bundle_schema=BENCHMARK_RESULT_BUNDLE_SCHEMA,
        qualification_policy_pin=qualification_policy_pin,
    )
