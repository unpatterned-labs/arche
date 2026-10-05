# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""A trusted monitor: typed, calibrated answers about a proposed action, never free text.

    from arche.monitor import Question, ask

    verdict = ask(
        {"entity": "organisation", "a": record_a, "b": record_b},
        [Question.yes_no("same_entity"), Question.choice("action", ("merge", "hold", "no_op"))],
    )
    verdict.answers["same_entity"].p          # a probability, not a paragraph
    verdict.answers["action"].distribution    # {"merge": 0.9, "hold": 0.1, "no_op": 0.0}

What this is
------------
The stochastic layer of an agent stack *proposes* -- a merge, a redaction, a
tool call. The monitor is the layer that says, before the proposal is acted
on, how likely it is to be right -- and says it as a **number with a type**,
never as text. That is the whole design, and it is the property the
non-generative-monitor literature rests on: a model that cannot emit prose has
no instruction pathway an adversary can write into. A record that says
"this is definitely the same company" cannot talk a probability up.

The rule is enforced by the types. :class:`Answer` has ``p``, ``distribution``
or ``value`` and a ``confidence``; its ``evidence`` is a tuple of factor names
drawn from a fixed vocabulary, not sentences. There is no field a free-text
answer could go in.

Implementations
---------------
:class:`EngineMonitor` -- arche's own resolution engine, wrapped. A
``compare`` receipt *is* a typed answer: the score is ``p``, the gate's
commitment is ``confidence``, the factors are the evidence. It runs offline,
needs no model and no key, and is the reference implementation every other
monitor is measured against.

Others are backends behind extras (plan §7i, M7.2), reached through the same
protocol and the same guard, never on by default. A monitor that phones out
is a provider like any other; the protocol does not care, the guard does.

What a monitor's ``p`` is
-------------------------
For the engine, ``p`` on ``same_entity`` is the resolution score -- a
similarity in ``[0, 1]`` with a gate, **not a calibrated probability**. Whether
it is calibrated, and how the alternatives compare, is the measurement M7.3
owes before any monitor is trusted with a floor; until then ``p`` orders
proposals and ``confidence`` says whether the engine committed.
"""

from __future__ import annotations

from bisect import bisect_right
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from hashlib import sha256
from typing import Any, Literal, Protocol, runtime_checkable

QuestionKind = Literal["yes_no", "choice", "score"]


@dataclass(frozen=True)
class Question:
    """One thing the monitor is asked. ``key`` names the answer."""

    key: str
    kind: QuestionKind
    options: tuple[str, ...] = ()

    @classmethod
    def yes_no(cls, key: str) -> Question:
        return cls(key, "yes_no")

    @classmethod
    def choice(cls, key: str, options: Sequence[str]) -> Question:
        if len(options) < 2:
            raise ValueError("a choice needs at least two options")
        return cls(key, "choice", tuple(options))

    @classmethod
    def score(cls, key: str) -> Question:
        return cls(key, "score")


@dataclass(frozen=True)
class Answer:
    """A typed answer. Exactly one of ``p`` / ``distribution`` / ``value`` is set.

    ``answered`` is ``False`` when the monitor could not answer *this*
    question -- the key is not in its vocabulary, or the state lacks what it
    needs. That is reported as a flag, not a sentence, and the caller decides
    what an unanswered question means for the action.
    """

    key: str
    kind: QuestionKind
    p: float | None = None                       # yes_no: P(yes)
    distribution: dict[str, float] | None = None  # choice: option -> P
    value: float | None = None                    # score: in [0, 1]
    confidence: float = 0.0
    evidence: tuple[str, ...] = ()
    answered: bool = True

    @property
    def top(self) -> str | None:
        """The most probable option of a choice, else ``None``."""
        if not self.distribution:
            return None
        return max(self.distribution, key=lambda k: self.distribution[k])


@dataclass(frozen=True)
class Verdict:
    """Every answer, plus which monitor gave them and its pin."""

    monitor: str
    pin: str
    answers: dict[str, Answer]
    decision_id: str | None = None

    def unanswered(self) -> tuple[str, ...]:
        return tuple(k for k, a in self.answers.items() if not a.answered)


@runtime_checkable
class Monitor(Protocol):
    """What every monitor implements. Nothing here returns text."""

    name: str

    def pin(self) -> str: ...

    def ask(self, state: Mapping[str, Any], questions: Sequence[Question]) -> Verdict: ...


# ------------------------------------------------------------------ engine --

#: The questions the engine can answer, and nothing else. A question outside
#: this vocabulary comes back ``answered=False``.
ENGINE_QUESTIONS = frozenset({"same_entity", "action", "identity", "match_score"})


@dataclass
class EngineMonitor:
    """arche's resolution engine as a monitor over a proposed pair.

    ``state`` must carry ``a`` and ``b`` (records or texts) and may carry
    ``entity`` (default ``"person"``), ``jurisdiction`` and ``store``. The
    engine compares them once and answers every question from the one
    receipt, so the answers are consistent with each other by construction.
    """

    name: str = "engine"
    entity: str = "person"

    def pin(self) -> str:
        from arche import __version__

        return f"monitor:engine@arche-core/{__version__}"

    def ask(self, state: Mapping[str, Any], questions: Sequence[Question]) -> Verdict:
        from arche.resolve import compare

        if "a" not in state or "b" not in state:
            raise ValueError("EngineMonitor needs state['a'] and state['b']")
        kwargs: dict[str, Any] = {"entity": state.get("entity", self.entity)}
        if state.get("jurisdiction"):
            kwargs["jurisdiction"] = state["jurisdiction"]
        receipt = compare(state["a"], state["b"], store=state.get("store"), **kwargs)

        score = max(0.0, min(1.0, float(receipt.score)))
        # The gate either committed (same_entity / different) or it did not
        # (review). That commitment is what the engine's confidence means.
        confidence = 1.0 if receipt.identity in ("same_entity", "different") else 0.5
        evidence = tuple(sorted(k for k, v in receipt.factors.items()
                                if isinstance(v, (int, float))))
        answers: dict[str, Answer] = {}
        for q in questions:
            if q.key not in ENGINE_QUESTIONS:
                answers[q.key] = Answer(q.key, q.kind, answered=False)
                continue
            if q.key == "same_entity" and q.kind == "yes_no":
                answers[q.key] = Answer(q.key, q.kind, p=score, confidence=confidence,
                                        evidence=evidence)
            elif q.key == "match_score" and q.kind == "score":
                answers[q.key] = Answer(q.key, q.kind, value=score, confidence=confidence,
                                        evidence=evidence)
            elif q.key == "action" and q.kind == "choice":
                answers[q.key] = Answer(q.key, q.kind, confidence=confidence,
                                        evidence=evidence,
                                        distribution=_one_hot(q.options, receipt.action))
            elif q.key == "identity" and q.kind == "choice":
                answers[q.key] = Answer(q.key, q.kind, confidence=confidence,
                                        evidence=evidence,
                                        distribution=_one_hot(q.options, receipt.identity))
            else:
                # Right key, wrong kind: `same_entity` asked as a choice, say.
                answers[q.key] = Answer(q.key, q.kind, answered=False)
        return Verdict(monitor=self.name, pin=self.pin(), answers=answers,
                       decision_id=receipt.decision_id)


@dataclass(frozen=True)
class Calibration:
    """A monotone map from a score to a probability, fitted on labelled pairs.

    Isotonic regression by pool-adjacent-violators: the fit is the non-decreasing
    step function that minimises squared error against the labels. Chosen over a
    sigmoid because it assumes nothing about the shape of the miscalibration, and
    arche's score is a weighted mean through a gate rather than a log-odds, so a
    sigmoid's assumption is not met.

    No dependency. Twenty lines of PAV against a scikit-learn import that would
    make a monitor heavier than the engine it monitors.

    ``thresholds`` and ``values`` are parallel and ascending: a score at or above
    ``thresholds[i]`` and below ``thresholds[i+1]`` maps to ``values[i]``.
    """

    thresholds: tuple[float, ...]
    values: tuple[float, ...]
    fitted_on: int = 0

    @classmethod
    def fit(cls, scores: Sequence[float], labels: Sequence[bool]) -> Calibration:
        """Fit on (score, was-it-really-a-match) pairs.

        Fit on a split the monitor will not be scored on. Fitting and scoring on
        the same pairs measures how well isotonic regression can memorise, which
        is perfectly, and says nothing.
        """
        if len(scores) != len(labels):
            raise ValueError("scores and labels must be the same length")
        points = sorted(zip(scores, labels, strict=True), key=lambda sl: sl[0])
        if not points:
            raise ValueError("a calibration needs at least one labelled pair")

        # Blocks of (weight, mean), merged while the sequence decreases.
        blocks: list[list[float]] = []
        for score, label in points:
            blocks.append([1.0, float(label), score])
            while len(blocks) > 1 and blocks[-2][1] > blocks[-1][1]:
                weight_b, mean_b, _ = blocks.pop()
                weight_a, mean_a, low_a = blocks.pop()
                weight = weight_a + weight_b
                blocks.append([weight,
                               (weight_a * mean_a + weight_b * mean_b) / weight,
                               low_a])
        return cls(thresholds=tuple(b[2] for b in blocks),
                  values=tuple(min(1.0, max(0.0, b[1])) for b in blocks),
                  fitted_on=len(points))

    def __call__(self, score: float) -> float:
        """The calibrated probability for one score."""
        if not self.thresholds:
            return 0.0
        index = bisect_right(self.thresholds, score) - 1
        return self.values[max(0, index)]

    def digest(self) -> str:
        """A content address for this exact map, for the pin.

        A calibrated answer is only replayable if the decision names the map that
        produced it. Two monitors fitted on different splits are different
        monitors and must not share a pin.
        """
        body = ";".join(f"{a:.6f}:{b:.6f}"
                        for a, b in zip(self.thresholds, self.values, strict=True))
        return sha256(body.encode()).hexdigest()[:16]


@dataclass
class CalibratedMonitor:
    """Another monitor's score, mapped to a probability that means what it says.

    **What this buys, and what it costs.** Calibration cannot *improve* the best
    achievable queue cut, because a threshold swept against truth on the raw
    score finds the same pairs. What it changes is whether you can find that cut
    **without labels**.

    And it is not free, which an earlier version of this docstring got wrong.
    Isotonic regression is monotone but not *strictly* monotone: it maps ranges
    of scores to a single value, and those ties lose ranking information.
    Measured on DBLP-ACM's review band, calibrating the engine's score moved
    AUROC 0.8856 to 0.8605 and the best achievable cut 86.4% to 71.6%, while
    expected calibration error went 0.5993 to 0.0001. Trading a little ranking
    for a number that means what it says is usually the right trade, but it is a
    trade.

    Uncalibrated, "merge where p >= 0.98" is a sentence about a similarity and
    promises nothing; the operating point has to be swept against truth, which is
    what you do not have in production. Calibrated, the same sentence is a claim
    about an error rate, and the harness measures whether the claim holds. That
    is the difference between a score and a probability, and it is the whole
    reason the monitor lane exists.

    Wraps any :class:`Monitor`. ``base`` answers, this rewrites the probability
    on the questions a probability applies to and leaves the rest alone, so a
    ``choice`` distribution passes through untouched rather than being mangled by
    a map fitted on a binary outcome.
    """

    base: Monitor
    calibration: Calibration
    name: str = "calibrated"

    def pin(self) -> str:
        return (f"monitor:{self.name}@{self.base.pin()}"
                f"+cal/{self.calibration.digest()}"
                f"/n={self.calibration.fitted_on}")

    def ask(self, state: Mapping[str, Any], questions: Sequence[Question]) -> Verdict:
        inner = self.base.ask(state, questions)
        answers: dict[str, Answer] = {}
        for key, answer in inner.answers.items():
            if not answer.answered:
                answers[key] = answer
                continue
            if answer.kind == "yes_no" and answer.p is not None:
                answers[key] = replace(answer, p=self.calibration(answer.p))
            elif answer.kind == "score" and answer.value is not None:
                answers[key] = replace(answer, value=self.calibration(answer.value))
            else:
                # A choice distribution is not a single probability and a map
                # fitted on one outcome has nothing to say about it.
                answers[key] = answer
        return Verdict(monitor=self.name, pin=self.pin(), answers=answers,
                       decision_id=inner.decision_id)


def _one_hot(options: Sequence[str], chosen: str) -> dict[str, float]:
    """The engine decides, it does not distribute: all mass on its answer.

    An option outside the caller's list gets nothing, and the caller can see
    that the mass went nowhere -- which is the honest rendering of "the engine
    said something you did not offer".
    """
    return {o: (1.0 if o == chosen else 0.0) for o in options}


def ask(state: Mapping[str, Any], questions: Sequence[Question], *,
        monitor: Monitor | None = None) -> Verdict:
    """Ask the monitor -- the engine unless another is given."""
    return (monitor or EngineMonitor()).ask(state, questions)


__all__ = ["ENGINE_QUESTIONS", "Answer", "Calibration", "CalibratedMonitor",
           "EngineMonitor", "Monitor", "Question", "QuestionKind", "Verdict",
           "ask"]
