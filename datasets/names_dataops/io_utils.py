"""Shared I/O helpers for the names DataOps pipeline."""

from __future__ import annotations

import csv
import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError


def ensure_parent(path: Path) -> None:
    """Ensure a path's parent directory exists."""
    path.parent.mkdir(parents=True, exist_ok=True)


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    """Read JSONL into a list of dict rows."""
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    return rows


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> int:
    """Write rows to JSONL and return row count."""
    ensure_parent(path)
    count = 0
    with open(path, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
            count += 1
    return count


def read_csv(path: Path) -> list[dict[str, str]]:
    """Read CSV rows as dicts."""
    if not path.exists():
        return []
    with open(path, encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        return [dict(row) for row in reader]


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> int:
    """Write rows to CSV with deterministic ordering."""
    ensure_parent(path)
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    return len(rows)


def validate_rows(model: type[BaseModel], rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Validate rows against a Pydantic model."""
    out: list[dict[str, Any]] = []
    errors: list[str] = []
    for idx, row in enumerate(rows, start=1):
        try:
            out.append(model.model_validate(row).model_dump(mode="json"))
        except ValidationError as exc:
            errors.append(f"row {idx}: {exc}")
    if errors:
        joined = "\n".join(errors[:20])
        if len(errors) > 20:
            joined += f"\n... and {len(errors) - 20} more errors"
        raise ValueError(f"Schema validation failed:\n{joined}")
    return out


def dump_json(path: Path, payload: dict[str, Any]) -> None:
    """Write a JSON object to disk."""
    ensure_parent(path)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2, sort_keys=True)
