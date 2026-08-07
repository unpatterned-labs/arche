# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""LLM-proposed spatial role labeling — the model proposes, the cue engine
verifies.

The deterministic :func:`arche.addr.extract_places` abstains where cues run
out. This module is the seam for callers who want a model to read the messy
tail — with one non-negotiable constraint carried over from the design:

    **A model-proposed role is only accepted when its cue can be located in
    the source text, adjacent to the span, and matched against the shipped
    cue pack for that role.** A proposal whose cue is missing, fabricated,
    non-adjacent, or inconsistent with the pack is downgraded to
    ``role="unknown"`` — kept as a mention, stripped of the guess.

That keeps the ``cue`` field meaning what it says (the linguistic evidence
that decided the role) rather than a post-hoc rationalization the model
wrote. Grade any of it — this proposer, your own prompt, a raw model —
against the shipped gold set with :func:`arche.addr.grade_places`.

Offline by design: ``complete_fn`` is any callable; no network in tests.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from arche.addr.parse import infer_jurisdiction, parse_address
from arche.addr.roles import (
    _BOUNDARY_RE,
    _CONFIDENCE,
    _ROLES,
    PlaceMention,
    RolePack,
    _gazetteer_index,
    load_role_pack,
)

_FENCE = re.compile(r"^```[a-zA-Z]*\n|\n```$")


def build_places_messages(pack: RolePack, text: str) -> list[dict[str, str]]:
    """The proposal prompt, generated from the cue pack alone."""
    by_role: dict[str, list[str]] = {}
    for r in pack.rules:
        if r.kind == "pair":
            continue
        by_role.setdefault(r.roles[0], []).extend(r.cues[:4])
    cue_lines = "\n".join(
        f"- {role}: e.g. {', '.join(repr(c) for c in cues[:6])}"
        for role, cues in sorted(by_role.items())
    )
    system = (
        "You label place/address mentions in text with their spatial role.\n"
        "Roles (use ONLY these): origin | destination | location | via | "
        "unknown.\n\n"
        "For EVERY place mention, emit one object:\n"
        '  {"text": "<verbatim substring>", "role": "<role>", '
        '"cue": "<the verbatim word(s) that decided the role, or null>"}\n\n'
        "Rules:\n"
        "- text and cue MUST be verbatim substrings of the input. Never "
        "invent an address.\n"
        "- If no cue in the text supports a role, use role \"unknown\" and "
        "cue null. Do not guess.\n"
        f"Example cues per role (pack {pack.pin}):\n{cue_lines}\n\n"
        "Respond with a JSON array only."
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": text},
    ]


@dataclass
class LLMPlaceExtraction:
    """Model-proposed place mentions after deterministic cue verification."""

    mentions: list[PlaceMention]
    violations: list[str] = field(default_factory=list)
    downgrades: list[str] = field(default_factory=list)
    model: str = ""
    prompt_sha256: str = ""
    pack: str = ""

    def pins(self) -> dict[str, Any]:
        """Provenance pins: which model proposed, under which prompt and cue
        pack, and that the proposal step is not reproducible (the
        verification step is)."""
        return {
            "place_extraction": {
                "model": self.model or "unknown",
                "prompt_sha256": self.prompt_sha256,
                "pack": self.pack,
                "reproducible": False,
            }
        }


def _role_map(pack: RolePack) -> dict[str, set[str]]:
    """``{cue phrase (lower): {roles it may license}}`` from the pack."""
    out: dict[str, set[str]] = {}
    for r in pack.rules:
        if r.kind == "pair":
            for c in r.cues:
                out.setdefault(c, set()).add(r.roles[0])
            for j in r.join:
                out.setdefault(j, set()).add(r.roles[1])
        else:
            for c in r.cues:
                out.setdefault(c, set()).add(r.roles[0])
    return out


def _locate(text: str, fragment: str, near: int | None = None) -> tuple[int, int] | None:
    """Span of ``fragment`` in ``text`` — the occurrence nearest ``near``."""
    low, frag = text.lower(), fragment.lower()
    best: tuple[int, int] | None = None
    at = low.find(frag)
    while at != -1:
        cand = (at, at + len(fragment))
        if near is None:
            return cand
        if best is None or abs(near - cand[0]) < abs(near - best[0]):
            best = cand
        at = low.find(frag, at + 1)
    return best


def _span_tier(span_text: str) -> int:
    addr = parse_address(span_text)
    if addr is not None and (addr.components.street or addr.components.plot
                             or addr.components.postal_code):
        return 2
    if span_text.lower() in _gazetteer_index():
        return 1
    return 0


def extract_places_llm(
    text: str,
    *,
    config=None,
    complete_fn: Callable[[list[dict[str, str]]], str] | None = None,
    model: str = "",
    rules: RolePack | None = None,
) -> LLMPlaceExtraction:
    """Have the caller's model propose place mentions; verify every role.

    Exactly one of ``config`` (an :class:`arche.llm.LLMConfig`) or
    ``complete_fn`` (any callable taking the messages and returning the
    model's text) must be supplied.

    Verification, per proposal: the span must be a verbatim substring of the
    source (else it is a **violation**, dropped — a hallucinated address never
    becomes a value); the role must be in the closed vocabulary (else a
    violation); and a committed role must carry a cue that (a) exists in the
    source adjacent to the span and (b) the pack maps to that role — else the
    mention is kept but **downgraded** to ``unknown``.
    """
    if (config is None) == (complete_fn is None):
        raise ValueError("supply exactly one of config= or complete_fn=")
    pack = rules or load_role_pack()
    messages = build_places_messages(pack, text)
    prompt_sha = hashlib.sha256(
        json.dumps(messages, sort_keys=True).encode("utf-8")
    ).hexdigest()

    if complete_fn is None:
        from arche.llm.providers import complete as _provider_complete

        raw = _provider_complete(messages, config)
        model = model or getattr(config, "model", "")
    else:
        raw = complete_fn(messages)

    cleaned = _FENCE.sub("", raw.strip()).strip()
    try:
        proposals = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise ValueError(f"model did not return valid JSON: {exc}") from exc
    if isinstance(proposals, dict):
        proposals = [proposals]
    if not isinstance(proposals, list):
        raise ValueError(
            f"model returned {type(proposals).__name__}, expected a JSON array"
        )

    role_map = _role_map(pack)
    mentions: list[PlaceMention] = []
    violations: list[str] = []
    downgrades: list[str] = []

    for i, prop in enumerate(proposals):
        if not isinstance(prop, dict) or "text" not in prop:
            violations.append(f"proposal[{i}]: not an object with 'text'")
            continue
        frag = str(prop["text"])
        role = str(prop.get("role", "unknown"))
        cue = prop.get("cue")

        if role not in _ROLES:
            violations.append(
                f"proposal[{i}]: role {role!r} is not in the closed "
                f"vocabulary {sorted(_ROLES)}"
            )
            continue
        span = _locate(text, frag)
        if span is None or text[span[0]:span[1]] != frag:
            violations.append(
                f"proposal[{i}]: span is not a verbatim substring of the "
                "source — a hallucinated address never becomes a value"
            )
            continue

        cue_span = None
        cue_text = None
        cue_phrase = None
        evidence: list[str] = [
            {2: "span:parsed", 1: "span:gazetteer",
             0: "span:model_proposed"}[_span_tier(frag)]
        ]
        verified = False
        if role != "unknown":
            reason = None
            if not cue:
                reason = "no cue offered"
            else:
                located = _locate(text, str(cue), near=span[0])
                if located is None:
                    reason = f"cue {cue!r} not found in source"
                else:
                    gap = text[located[1]:span[0]]
                    inside = span[0] <= located[0] < span[1]
                    adjacent = (
                        located[1] <= span[0] and len(gap) <= pack.max_gap
                        and not _BOUNDARY_RE.search(gap)
                    )
                    allowed = role_map.get(str(cue).lower().strip(), set())
                    if not (adjacent or inside):
                        reason = f"cue {cue!r} is not adjacent to the span"
                    elif role not in allowed:
                        reason = (
                            f"pack maps cue {cue!r} to {sorted(allowed) or 'nothing'}, "
                            f"not {role!r}"
                        )
                    else:
                        cue_span, cue_text = located, text[located[0]:located[1]]
                        cue_phrase = str(cue).lower().strip()
                        verified = True
            if not verified:
                downgrades.append(
                    f"proposal[{i}] ({frag[:32]!r}): role {role!r} downgraded "
                    f"to unknown — {reason}"
                )
                role = "unknown"
                evidence.append("cue:unverified")
            else:
                evidence.append("cue:model_proposed_verified")

        tier = _span_tier(frag)
        confidence = _CONFIDENCE[(2 if verified else 0, tier)]
        address = parse_address(frag)
        if address is not None:
            juris = address.country_inferred or "XX"
            juris_conf = address.country_confidence
        else:
            juris, juris_conf, _trigger = infer_jurisdiction(frag)
        mentions.append(PlaceMention(
            role=role, text=frag, span=span,  # type: ignore[arg-type]
            cue=cue_text, cue_span=cue_span, cue_rule=None,
            cue_phrase=cue_phrase, confidence=confidence,
            evidence=tuple(evidence), address=address,
            jurisdiction=juris, jurisdiction_confidence=juris_conf,
        ))

    mentions.sort(key=lambda m: m.span[0])
    return LLMPlaceExtraction(
        mentions=mentions, violations=violations, downgrades=downgrades,
        model=model, prompt_sha256=prompt_sha, pack=pack.pin,
    )


__all__ = ["LLMPlaceExtraction", "build_places_messages", "extract_places_llm"]
