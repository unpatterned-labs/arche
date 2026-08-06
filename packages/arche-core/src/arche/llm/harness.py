# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""The evaluation harness — arche grades your LLM, honestly.

The DSPy-shaped half of the LLM lane (roadmap §7.1): bring your own model for
extraction or match judgment, and the deterministic engine acts as the oracle.
Divergence is *flagged, not hidden*: every pair where the model and the engine
disagree is reported with the engine's evidence, so "the LLM is doing well"
becomes a measured claim instead of a mood.

Two graders:

* :func:`grade_pairs` — the model as **matcher**. The oracle is the signable
  pairwise path (the calibrated gate + veto). Engine ``review`` outcomes are
  abstentions: the engine deliberately doesn't know, so the model is neither
  right nor wrong there — they are reported, not scored.
* :func:`grade_extractions` — the model as **extractor**. There is no oracle
  for fields arche has never seen, so the honest metrics are contract metrics:
  schema-violation rate and per-field coverage.

No network anywhere in this module.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from arche.declare import Declaration
    from arche.llm.declarative import DeclaredExtraction

# The judge's answer vocabulary and how it maps onto engine identities.
_JUDGE_ANSWERS = frozenset({"same", "different", "unsure"})
_ENGINE_TO_JUDGE = {"same_entity": "same", "different": "different"}


@dataclass
class Divergence:
    a_id: str
    b_id: str
    engine: str
    judge: str
    score: float
    evidence: dict[str, Any] = field(default_factory=dict)


@dataclass
class HarnessReport:
    """The grade, with its working shown."""

    total_pairs: int = 0
    scored_pairs: int = 0            # engine gave a definite verdict
    engine_abstained: int = 0        # engine said `review` — not scored
    judge_unsure: int = 0
    agreements: int = 0
    divergences: list[Divergence] = field(default_factory=list)
    by_engine: dict[str, int] = field(default_factory=dict)

    @property
    def agreement_rate(self) -> float | None:
        """Agreement over pairs where BOTH the engine and the judge committed
        (``None`` when nothing was scorable — a grade over zero pairs is not
        a grade)."""
        denom = self.scored_pairs - self.judge_unsure
        return (self.agreements / denom) if denom > 0 else None

    def summary(self) -> dict[str, Any]:
        rate = self.agreement_rate
        return {
            "total_pairs": self.total_pairs,
            "scored_pairs": self.scored_pairs,
            "engine_abstained": self.engine_abstained,
            "judge_unsure": self.judge_unsure,
            "agreement_rate": round(rate, 4) if rate is not None else None,
            "divergences": len(self.divergences),
            "by_engine": dict(self.by_engine),
        }


def grade_pairs(
    decl: Declaration,
    pairs: list[tuple[dict, dict]],
    judge: Callable[[dict, dict], str],
    *,
    jurisdiction: str = "default",
) -> HarnessReport:
    """Grade a model's same/different judgments against the pairwise oracle.

    ``judge`` receives the two raw records and must return ``"same"``,
    ``"different"``, or ``"unsure"`` (anything else raises — a grader that
    silently coerces answers grades nothing). The oracle is
    :func:`arche.resolve.coreference.coref_references` under the declaration:
    the same gate and veto that make decisions signable.
    """
    from arche.canonical import Reference
    from arche.resolve.coreference import coref_references

    report = HarnessReport(total_pairs=len(pairs))
    counts: Counter[str] = Counter()
    for rec_a, rec_b in pairs:
        verdict = judge(rec_a, rec_b)
        if verdict not in _JUDGE_ANSWERS:
            raise ValueError(
                f"judge returned {verdict!r}; expected one of "
                f"{sorted(_JUDGE_ANSWERS)}"
            )
        ra = Reference.from_record(rec_a, decl=decl)
        rb = Reference.from_record(rec_b, decl=decl)
        decision = coref_references(ra, rb, jurisdiction=jurisdiction, decl=decl)
        counts[decision.identity] += 1
        if decision.identity == "review":
            report.engine_abstained += 1
            continue
        report.scored_pairs += 1
        if verdict == "unsure":
            report.judge_unsure += 1
            continue
        expected = _ENGINE_TO_JUDGE[decision.identity]
        if verdict == expected:
            report.agreements += 1
        else:
            report.divergences.append(
                Divergence(
                    a_id=ra.record_id, b_id=rb.record_id,
                    engine=decision.identity, judge=verdict,
                    score=decision.score,
                    evidence=dict(decision.factors or {}),
                )
            )
    report.by_engine = dict(counts)
    return report


def grade_extractions(
    extractions: list[DeclaredExtraction], decl: Declaration
) -> dict[str, Any]:
    """Contract metrics for model extraction: violations and field coverage."""
    n = len(extractions)
    violation_counts: Counter[str] = Counter()
    coverage: Counter[str] = Counter()
    declared = [f.name for f in decl.fields.values() if f.role != "ignore"]
    for ex in extractions:
        for v in ex.violations:
            violation_counts[v] += 1
        for name in declared:
            if str(ex.record.get(name, "") or ""):
                coverage[name] += 1
    return {
        "records": n,
        "records_with_violations": sum(
            1 for ex in extractions if ex.violations
        ),
        "violation_rate": (
            round(sum(1 for ex in extractions if ex.violations) / n, 4)
            if n else None
        ),
        "top_violations": violation_counts.most_common(10),
        "field_coverage": {
            name: round(coverage[name] / n, 4) if n else None
            for name in declared
        },
        "declaration": decl.pin(),
    }
