"""Apply approved review decisions to YAML naming groups."""

from __future__ import annotations

import ast
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from .io_utils import read_jsonl, write_jsonl
from .schemas import CandidateEquivalenceV1


def apply_approved_candidates(
    *,
    review_rows: list[dict[str, Any]],
    yaml_dir: Path,
    approved_registry_path: Path,
) -> dict[str, int]:
    """Apply approved rows to YAML source files and append registry entries."""
    typed = [CandidateEquivalenceV1.model_validate(_coerce_review_row(row)) for row in review_rows]
    approved = [row for row in typed if row.status == "approved"]
    if not approved:
        return {"approved": 0, "new_groups": 0, "new_variants": 0}

    yaml_state = _load_yaml_state(yaml_dir)
    new_groups = 0
    new_variants = 0
    applied_at = datetime.now(UTC).isoformat()

    for row in approved:
        if not row.source or not row.source_license:
            raise ValueError(
                f"Approved row {row.candidate_id} missing provenance or source license.",
            )

        target_file = _target_file_for_row(row, yaml_state)
        group = _find_group(yaml_state[target_file]["groups"], row.canonical)
        if group is None:
            variants = [row.variant] if row.variant != row.canonical else []
            yaml_state[target_file]["groups"].append(
                {"canonical": row.canonical, "variants": variants},
            )
            new_groups += 1
            if variants:
                new_variants += 1
            continue

        if row.variant == row.canonical:
            continue
        existing_variants = {v for v in group.get("variants", [])}
        if row.variant not in existing_variants:
            group.setdefault("variants", []).append(row.variant)
            new_variants += 1

    _write_yaml_state(yaml_dir, yaml_state)
    _append_registry(approved_registry_path, approved, applied_at)

    return {"approved": len(approved), "new_groups": new_groups, "new_variants": new_variants}


def _load_yaml_state(yaml_dir: Path) -> dict[str, dict[str, Any]]:
    state: dict[str, dict[str, Any]] = {}
    for yaml_file in sorted(yaml_dir.glob("*.yaml")):
        with open(yaml_file, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        data.setdefault("groups", [])
        state[yaml_file.stem] = data
    return state


def _write_yaml_state(yaml_dir: Path, state: dict[str, dict[str, Any]]) -> None:
    for stem, data in sorted(state.items()):
        groups = data.get("groups", [])
        for group in groups:
            variants = sorted(
                {
                    v
                    for v in group.get("variants", [])
                    if v and v != group["canonical"]
                },
            )
            group["variants"] = variants
        groups.sort(key=lambda g: g["canonical"].casefold())

        path = yaml_dir / f"{stem}.yaml"
        with open(path, "w", encoding="utf-8") as f:
            yaml.safe_dump(
                data,
                f,
                sort_keys=False,
                allow_unicode=True,
                indent=2,
            )


def _find_group(groups: list[dict[str, Any]], canonical: str) -> dict[str, Any] | None:
    for group in groups:
        if group.get("canonical") == canonical:
            return group
    return None


def _target_file_for_row(row: CandidateEquivalenceV1, state: dict[str, dict[str, Any]]) -> str:
    # Existing canonical location always wins.
    for stem, data in state.items():
        for group in data.get("groups", []):
            if group.get("canonical") == row.canonical:
                return stem

    if row.suggested_tradition in state:
        return row.suggested_tradition
    return "cross_linguistic"


def _append_registry(path: Path, approved: list[CandidateEquivalenceV1], applied_at: str) -> None:
    existing_rows = read_jsonl(path)
    by_candidate_id: dict[str, dict[str, Any]] = {
        row["candidate_id"]: row for row in existing_rows if "candidate_id" in row
    }
    for row in approved:
        payload = row.model_dump(mode="json")
        payload["applied_at"] = applied_at
        by_candidate_id[row.candidate_id] = payload
    rows = [by_candidate_id[cid] for cid in sorted(by_candidate_id.keys())]
    write_jsonl(path, rows)


def _coerce_review_row(row: dict[str, Any]) -> dict[str, Any]:
    payload = dict(row)
    for key in ("wikidata_qids", "countries", "languages"):
        value = payload.get(key)
        if isinstance(value, str):
            stripped = value.strip()
            if not stripped:
                payload[key] = []
                continue
            try:
                parsed = ast.literal_eval(stripped)
                payload[key] = parsed if isinstance(parsed, list) else [str(parsed)]
            except (ValueError, SyntaxError):
                payload[key] = [part for part in stripped.split("|") if part]
    if "conflict_flag" in payload and isinstance(payload["conflict_flag"], str):
        payload["conflict_flag"] = payload["conflict_flag"].strip().lower() == "true"
    if "confidence" in payload and isinstance(payload["confidence"], str):
        payload["confidence"] = float(payload["confidence"])
    return payload
