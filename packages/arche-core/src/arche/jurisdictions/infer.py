# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Infer which jurisdiction a document belongs to, from evidence in the document.

The bug this fixes
------------------
`Pipeline(jurisdiction=...)` made the caller type a country code. Type the wrong
one and the consequences are not subtle: running the Nigerian detector set over
a British bank statement reported **36 tax identification numbers**, every one a
Bolt ride reference or a Viator transaction ID, because a Nigerian TIN is ten
digits and so are they.

Why this is a proposer, not a decider
-------------------------------------
It reads evidence and proposes a country. It decides nothing: an explicit
``jurisdiction=`` always wins, and the proposal is recorded alongside the result
so a reviewer can see both. That placement is deliberate — `detect` finds spans,
`policy` chooses actions, and this sits before either, in the package that
already owns country knowledge.

**It cannot establish that a country's law applies to your processing.** That
turns on establishment, on where your data subjects are, on sector and on
transfers. A jurisdiction code selects a *policy template*; it does not perform
a legal applicability analysis, and nothing here should be read as doing so.

Abstention is a result, not a failure
-------------------------------------
The rules below are built so that not-knowing is reachable and common. Measured
on the four invoices in this repo, two abstain — one because a German issuer and
US currency genuinely conflict, one because a lone currency symbol is not enough
to name a country. Both are correct outcomes, and a detector that always answers
is not confident, it is unfalsifiable.

Three tiers, and one rule that matters
--------------------------------------
* **Tier A — near-unique.** A registration identifier or a regulator's name. A
  UK postcode. `Registered in England and Wales`. These name a country almost
  by themselves.
* **Tier B — moderate.** Currency, company-form suffix, phone country code.
  Several of these agreeing is meaningful; one alone is not.
* **Tier C — corroborating only.** A PDF timestamp's UTC offset, a date format.

**A Tier-C signal can never move a country from abstain to chosen.** It breaks
ties between candidates that already hold stronger evidence, and nothing more.
That is the mechanical form of this project's standing rule that identity
evidence has to be earned — a UK user printing a US invoice produces a UK
timestamp, and that must not be allowed to decide anything on its own.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Iterable, Literal

__all__ = [
    "JurisdictionEvidence",
    "JurisdictionInference",
    "RULESET_VERSION",
    "infer_jurisdiction",
]

#: Bumped when the signal set or the weights change. It enters the pins, so a
#: decision made under different rules is distinguishable from one made now.
RULESET_VERSION = "2026.08.1"

Tier = Literal["A", "B", "C"]

_TIER_WEIGHT: dict[Tier, float] = {"A": 1.0, "B": 0.35, "C": 0.10}

#: How many occurrences of one signal type can contribute. Without this the
#: Monzo statement's 166 dd/mm dates would swamp every other signal in the
#: document — what matters is how many *distinct kinds* of evidence agree, not
#: how chatty one of them is.
_MAX_COUNT_PER_SIGNAL = 3


@dataclass(frozen=True)
class JurisdictionEvidence:
    """One signal, what it pointed at, and how much it was allowed to count."""

    signal: str
    tier: Tier
    country: str
    count: int
    weight: float
    source: Literal["text", "metadata"] = "text"
    sample: str = ""

    def describe(self, reveal: bool = False) -> str:
        shown = self.sample if reveal else (self.sample[:4] + "…" if self.sample else "")
        detail = f" e.g. {shown!r}" if shown else ""
        return (f"{self.signal} ({self.tier}) -> {self.country} "
                f"x{self.count} = {self.weight:.2f}{detail}")


@dataclass(frozen=True)
class JurisdictionInference:
    """A proposal, with everything needed to disagree with it."""

    country: str | None
    confidence: float = 0.0
    margin: float = 0.0
    runner_up: str | None = None
    abstained: bool = True
    reason: str = ""
    evidence: tuple[JurisdictionEvidence, ...] = ()
    ruleset_version: str = RULESET_VERSION

    def explain(self, reveal: bool = False) -> str:
        """Why this came out the way it did, in words a reviewer can check."""
        head = (f"abstained — {self.reason}" if self.abstained
                else f"{self.country} (confidence {self.confidence:.2f}, "
                     f"margin {self.margin:.2f}) — {self.reason}")
        lines = [head]
        if self.evidence:
            lines.append("evidence:")
            lines += [f"  {e.describe(reveal)}" for e in self.evidence]
        else:
            lines.append("evidence: none found")
        return "\n".join(lines)

    def to_dict(self, reveal: bool = False) -> dict[str, Any]:
        return {
            "country": self.country,
            "confidence": round(self.confidence, 4),
            "margin": round(self.margin, 4),
            "runner_up": self.runner_up,
            "abstained": self.abstained,
            "reason": self.reason,
            "ruleset_version": self.ruleset_version,
            "evidence": [
                {"signal": e.signal, "tier": e.tier, "country": e.country,
                 "count": e.count, "weight": round(e.weight, 3),
                 "source": e.source,
                 "sample": e.sample if reveal else ""}
                for e in self.evidence
            ],
        }

    def __bool__(self) -> bool:
        return not self.abstained


# --- the signal table ------------------------------------------------------
#
# (name, tier, country, pattern). Kept as data rather than branches so adding a
# country is an edit here plus a test, and so the whole set is readable at once.
_SIGNALS: tuple[tuple[str, Tier, str, str], ...] = (
    # Tier A — registration identifiers, regulators, and address shapes that
    # essentially name a country on their own.
    ("registrar.companies_house", "A", "GB",
     r"[Rr]egistered\s+in\s+England(?:\s+and\s+Wales)?|Companies\s+House"),
    ("regulator.fca", "A", "GB", r"\bFinancial\s+Conduct\s+Authority\b|\bFCA\s+registe"),
    ("regulator.hmrc", "A", "GB", r"\bHM\s+Revenue|\bHMRC\b"),
    ("postcode.uk", "A", "GB",
     r"\b[A-Z]{1,2}\d{1,2}[A-Z]?\s+\d[A-Z]{2}\b"),
    ("vat.gb", "A", "GB", r"\bGB\s?\d{9}\b"),
    ("bank.sortcode", "A", "GB", r"\b(?:sort\s*code|Sort\s*Code)\b"),
    ("registrar.cac", "A", "NG", r"\bCorporate\s+Affairs\s+Commission\b|\bRC\s?\d{5,8}\b"),
    ("regulator.firs", "A", "NG", r"\bFederal\s+Inland\s+Revenue\b|\bFIRS\b"),
    ("id.nin", "A", "NG", r"\bNIN\b|\bBVN\b"),
    ("regulator.sars", "A", "ZA", r"\bSouth\s+African\s+Revenue\s+Service\b|\bSARS\b"),
    ("regulator.kra", "A", "KE", r"\bKenya\s+Revenue\s+Authority\b|\bKRA\s+PIN\b"),
    ("id.ssn", "A", "US", r"\bSocial\s+Security\s+Number\b|\bSSN\b"),
    ("registrar.handelsregister", "A", "DE", r"\bHandelsregister\b|\bHRB\s?\d+"),
    ("vat.eu", "A", "EU",
     r"\b(?:ATU\d{8}|BE0\d{9}|FR[A-Z0-9]{2}\d{9}|DE\d{9}|IE\d{7}[A-Z]{1,2}|"
     r"NL\d{9}B\d{2}|ES[A-Z]\d{7}[A-Z0-9])\b"),

    # Tier B — meaningful in company, weak alone.
    ("currency.gbp", "B", "GB", r"£"),
    ("currency.usd", "B", "US", r"\$(?=\s?\d)"),
    ("currency.eur", "B", "EU", r"€"),
    ("currency.ngn", "B", "NG", r"₦|\bNGN\b"),
    ("currency.zar", "B", "ZA", r"\bZAR\b|\bR\s?\d+[.,]\d{2}\b"),
    ("company_form.uk", "B", "GB", r"\b(?:Ltd|Limited|PLC|LLP)\b"),
    ("company_form.us", "B", "US", r"\b(?:Inc\.?|LLC|Corp\.?)\b"),
    ("company_form.de", "B", "DE", r"\b(?:GmbH|AG|UG)\b"),
    ("company_form.ng", "B", "NG", r"\bNigeria\s+Limited\b|\bNig\.?\s+Ltd\b"),
    ("phone.uk", "B", "GB", r"\b(?:\+44|07\d{9}|0[12]\d{8,9})\b"),
    ("phone.ng", "B", "NG", r"\+234\b|\b0[789]\d{9}\b"),
    ("phone.us", "B", "US", r"\+1\s?\(?\d{3}\)?[\s.-]\d{3}[\s.-]\d{4}\b"),

    # Tier C — corroborating only. Never decisive; see the module docstring.
    ("date.dmy", "C", "GB", r"\b\d{1,2}/\d{1,2}/\d{4}\b"),
    ("date.mdy", "C", "US", r"\b\d{1,2}/\d{1,2}/\d{2}\b(?!\d)"),
)

_COMPILED = tuple(
    (name, tier, country, re.compile(pattern))
    for name, tier, country, pattern in _SIGNALS
)

#: PDF timezone offset (minutes) -> a country it is consistent with. Tier C.
_TZ_HINTS: tuple[tuple[int, int, str], ...] = (
    (0, 0, "GB"), (60, 60, "EU"), (-480, -420, "US"), (-360, -300, "US"),
)


def infer_jurisdiction(
    text: str,
    *,
    metadata: Any = None,
    candidates: Iterable[str] | None = None,
    min_confidence: float = 0.60,
    min_margin: float = 0.15,
) -> JurisdictionInference:
    """Propose the jurisdiction a document belongs to, or abstain.

    >>> infer_jurisdiction(statement_text).country      # doctest: +SKIP
    'GB'
    >>> infer_jurisdiction(ambiguous_invoice).abstained # doctest: +SKIP
    True

    Returns a :class:`JurisdictionInference`. When it abstains, ``country`` is
    ``None`` and ``reason`` says why in words — thin evidence, or a genuine
    conflict between signals.
    """
    text = text or ""
    scores: dict[str, float] = defaultdict(float)
    tiers_seen: dict[str, set[str]] = defaultdict(set)
    signal_types: dict[str, set[str]] = defaultdict(set)
    evidence: list[JurisdictionEvidence] = []

    for name, tier, country, pattern in _COMPILED:
        found = pattern.findall(text)
        if not found:
            continue
        counted = min(len(found), _MAX_COUNT_PER_SIGNAL)
        weight = _TIER_WEIGHT[tier] * counted
        scores[country] += weight
        tiers_seen[country].add(tier)
        signal_types[country].add(name)
        sample = next((f for f in found if isinstance(f, str) and f.strip()), "")
        evidence.append(JurisdictionEvidence(
            signal=name, tier=tier, country=country, count=len(found),
            weight=weight, source="text", sample=str(sample)[:40],
        ))

    offset = getattr(metadata, "tz_offset_minutes", None)
    if offset is not None:
        for low, high, country in _TZ_HINTS:
            if low <= offset <= high:
                scores[country] += _TIER_WEIGHT["C"]
                tiers_seen[country].add("C")
                signal_types[country].add("timezone.pdf")
                evidence.append(JurisdictionEvidence(
                    signal="timezone.pdf", tier="C", country=country, count=1,
                    weight=_TIER_WEIGHT["C"], source="metadata",
                    sample=f"{offset:+d}min",
                ))
                break

    if candidates:
        allowed = {c.upper() for c in candidates}
        scores = defaultdict(float, {k: v for k, v in scores.items() if k in allowed})

    evidence.sort(key=lambda e: (-e.weight, e.signal))
    if not scores:
        return JurisdictionInference(
            country=None, abstained=True, evidence=tuple(evidence),
            reason="no jurisdiction signals found in the document",
        )

    ranked = sorted(scores.items(), key=lambda kv: -kv[1])
    top, top_score = ranked[0]
    runner_up, runner_score = (ranked[1] if len(ranked) > 1 else (None, 0.0))
    total = sum(scores.values()) or 1.0
    confidence = top_score / total
    margin = (top_score - runner_score) / total

    # A Tier-C signal alone can never name a country. This is the rule that
    # keeps a printer's clock from deciding which law a reviewer sees.
    earned = bool(tiers_seen[top] & {"A"}) or len(
        {s for s in signal_types[top] if not s.startswith(("date.", "timezone."))}
    ) >= 2
    if not earned:
        return JurisdictionInference(
            country=None, confidence=confidence, margin=margin, runner_up=runner_up,
            abstained=True, evidence=tuple(evidence),
            reason=(f"{top} leads but only on weak or corroborating evidence; "
                    "a registration identifier or two independent signals are "
                    "needed to name a country"),
        )
    if confidence < min_confidence:
        return JurisdictionInference(
            country=None, confidence=confidence, margin=margin, runner_up=runner_up,
            abstained=True, evidence=tuple(evidence),
            reason=(f"evidence is split — {top} at {confidence:.0%} is below the "
                    f"{min_confidence:.0%} floor"),
        )
    if margin < min_margin:
        return JurisdictionInference(
            country=None, confidence=confidence, margin=margin, runner_up=runner_up,
            abstained=True, evidence=tuple(evidence),
            reason=(f"{top} and {runner_up} are too close "
                    f"({margin:.0%} apart, {min_margin:.0%} needed)"),
        )

    strongest = next((e.signal for e in evidence if e.country == top and e.tier == "A"),
                     None)
    because = (f"strongest signal {strongest}" if strongest
               else f"{len(signal_types[top])} independent signals agree")
    return JurisdictionInference(
        country=top, confidence=confidence, margin=margin, runner_up=runner_up,
        abstained=False, evidence=tuple(evidence),
        reason=f"{because}, {confidence:.0%} of total evidence weight",
    )
