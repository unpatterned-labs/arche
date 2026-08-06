# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Declaration-driven LLM extraction — bring your own model, keep the contract.

The user's :class:`~arche.declare.Declaration` supplies everything the model
needs (their fields, their descriptions, the generated JSON Schema) and
everything arche needs to stay honest afterwards (validation, roles,
restriction, the pin). The model proposes; the declaration validates; the
deterministic engine decides; attest signs — with provenance pins that say,
truthfully, that the *extraction* is not byte-reproducible even though the
*representation* is.

No network in this module's core path: ``complete_fn`` is an injectable
callable, and the default only wires up :func:`arche.llm.providers.complete`
when an :class:`LLMConfig` is given.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from arche.canonical import Reference
    from arche.declare import Declaration

_FENCE = re.compile(r"^```[a-zA-Z]*\n|\n```$")


def build_messages(decl: Declaration, text: str) -> list[dict[str, str]]:
    """The extraction prompt, generated from the declaration alone."""
    schema = json.dumps(decl.json_schema(), indent=2)
    field_lines = "\n".join(
        f"- {f.name}: {f.description or f'({f.role})'}"
        for f in decl.fields.values() if f.role != "ignore"
    )
    system = (
        f"You extract one {decl.entity} record from text.\n"
        f"Fields (emit ONLY these; omit any you cannot find — never invent):\n"
        f"{field_lines}\n\n"
        f"Respond with a single JSON object matching this schema exactly:\n"
        f"{schema}\n\n"
        f"Declaration: {decl.pin()}"
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": text},
    ]


def _parse_json_object(raw: str) -> dict:
    cleaned = _FENCE.sub("", raw.strip()).strip()
    try:
        obj = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise ValueError(f"model did not return valid JSON: {exc}") from exc
    if isinstance(obj, list) and len(obj) == 1 and isinstance(obj[0], dict):
        obj = obj[0]
    if not isinstance(obj, dict):
        raise ValueError(
            f"model returned {type(obj).__name__}, expected one JSON object"
        )
    return obj


@dataclass
class DeclaredExtraction:
    """One model-extracted record, validated against the declaration."""

    record: dict[str, Any]
    reference: Reference
    violations: list[str] = field(default_factory=list)
    model: str = ""
    prompt_sha256: str = ""

    def pins(self, decl: Declaration) -> dict[str, Any]:
        """Provenance pins for a decision built on this extraction.

        Merged into ``pairwise(..., extra_pins=...)`` these enter the decision
        hash — an honest account: which model proposed the record, under which
        prompt and declaration, and that the extraction step is
        **not** reproducible (the representation and the decision math are).
        """
        return {
            "extraction": {
                "model": self.model or "unknown",
                "prompt_sha256": self.prompt_sha256,
                "declaration": decl.pin(),
                "reproducible": False,
            }
        }


def extract_declared(
    text: str,
    decl: Declaration,
    *,
    config=None,
    complete_fn: Callable[[list[dict[str, str]]], str] | None = None,
    model: str = "",
) -> DeclaredExtraction:
    """Extract one record from ``text`` using the caller's model.

    Exactly one of ``config`` (an :class:`arche.llm.LLMConfig`, routed through
    the provider layer) or ``complete_fn`` (any callable taking the messages
    and returning the model's text — your own client, a local model, a test
    stub) must be supplied. The response is parsed, validated against the
    declaration (undeclared fields become *violations* and are excluded from
    the reference — never silently coerced), and returned with provenance.
    """
    if (config is None) == (complete_fn is None):
        raise ValueError("supply exactly one of config= or complete_fn=")
    messages = build_messages(decl, text)
    prompt_sha = hashlib.sha256(
        json.dumps(messages, sort_keys=True).encode("utf-8")
    ).hexdigest()[:16]
    if complete_fn is None:
        from arche.llm.providers import complete

        raw = complete(config, messages)
        model = model or getattr(config, "model", "") or ""
    else:
        raw = complete_fn(messages)
    record = _parse_json_object(raw)
    reference, violations = decl.validate_record(record)
    return DeclaredExtraction(
        record=record,
        reference=reference,
        violations=violations,
        model=model,
        prompt_sha256=prompt_sha,
    )
