# Copyright 2026 unpatterned.org
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Obligation overlays — document-level compliance obligations over a run.

An *overlay* (e.g. the EU AI Act) governs the AI *system*, not personal-data
fields, so it is not a per-PII ``Statute``. It is applied to a ``Result`` and
asserts, at the document level, whether the run met each obligation (logging,
transparency, minimisation), recording the Article. It enforces nothing new
per-PII and adds no seventh policy action.

Honest boundary: this produces machine-readable *evidence the operator presents*,
never a compliance certificate or legal advice.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

_OVERLAYS_DIR = Path(__file__).resolve().parent / "statutes" / "overlays"

# Actions that reduce exposure (vs "retain"/"audit", which leave data in place).
_MINIMISING = {"mask", "tokenize", "generalize", "drop"}


@dataclass
class Obligation:
    """The evaluated state of one obligation for a run."""

    article: str
    name: str
    satisfied: bool
    rationale: str


@dataclass
class Overlay:
    """A loaded obligation overlay (the YAML spec, before evaluation)."""

    overlay_id: str
    framework: str
    version: str
    obligations_spec: list[dict[str, Any]] = field(default_factory=list)
    notes: str = ""
    raw: dict[str, Any] = field(default_factory=dict)


def list_available_overlays() -> list[str]:
    if not _OVERLAYS_DIR.is_dir():
        return []
    return sorted(p.stem for p in _OVERLAYS_DIR.glob("*.yaml"))


def load_overlay(overlay_id: str) -> Overlay:
    """Load an overlay YAML from ``policy/statutes/overlays/``."""
    path = _OVERLAYS_DIR / f"{overlay_id}.yaml"
    if not path.exists():
        available = ", ".join(list_available_overlays()) or "(none shipped)"
        raise FileNotFoundError(
            f"overlay {overlay_id!r} not found in {_OVERLAYS_DIR}. Available: {available}"
        )
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return Overlay(
        overlay_id=data["overlay_id"],
        framework=data.get("framework", ""),
        version=data.get("version", ""),
        obligations_spec=data.get("obligations", []),
        notes=data.get("notes", ""),
        raw=data,
    )


def _evaluate(spec: dict[str, Any], result: Any, transparency_notice: str | None) -> Obligation:
    kind = spec.get("kind")
    article = spec.get("article", "")
    name = spec.get("name", "")

    if kind == "log_exists":
        has = bool(getattr(result, "audit_log", None)) or bool(
            getattr(result, "policy_outcomes", None)
        )
        return Obligation(
            article, name, has,
            "machine-readable decision log present" if has
            else "no decision log recorded for this run",
        )

    if kind == "transparency_notice":
        has = transparency_notice is not None and str(transparency_notice).strip() != ""
        return Obligation(
            article, name, has,
            f"transparency notice supplied: {transparency_notice!r}" if has
            else "no transparency notice supplied by the operator",
        )

    if kind == "minimisation":
        actions = [getattr(o, "action", None) for o in getattr(result, "policy_outcomes", [])]
        total = len(actions)
        minimised = sum(1 for a in actions if a in _MINIMISING)
        non_min = total - minimised
        satisfied = total == 0 or non_min == 0
        return Obligation(
            article, name, satisfied,
            "no personal data detected to minimise" if total == 0
            else f"{minimised}/{total} detected fields minimised, {non_min} retained in place",
        )

    return Obligation(article, name, False, f"unknown obligation kind {kind!r}")


def apply_overlay(
    result: Any,
    overlay: Overlay,
    *,
    transparency_notice: str | None = None,
) -> Any:
    """Evaluate ``overlay`` against ``result`` and stamp the obligations block.

    Writes ``result.metadata[overlay.overlay_id.lower()...]`` — for the EU AI
    Act, ``result.metadata["ai_act"]`` — with the per-obligation verdicts, and
    returns ``result``. Enforces nothing new per-PII.
    """
    obligations = [
        _evaluate(spec, result, transparency_notice) for spec in overlay.obligations_spec
    ]
    block = {
        "overlay_id": overlay.overlay_id,
        "framework": overlay.framework,
        "version": overlay.version,
        "transparency_notice": transparency_notice,
        "obligations": [
            {"article": o.article, "name": o.name, "satisfied": o.satisfied,
             "rationale": o.rationale}
            for o in obligations
        ],
        "all_satisfied": all(o.satisfied for o in obligations),
        "disclaimer": "Evidence the operator presents; not a compliance certificate.",
    }
    # Stable, readable key for the EU AI Act; generic fallback otherwise.
    key = "ai_act" if overlay.overlay_id == "EU-AI-ACT" else overlay.overlay_id.lower()
    if not hasattr(result, "metadata") or result.metadata is None:
        result.metadata = {}
    result.metadata[key] = block
    return result
