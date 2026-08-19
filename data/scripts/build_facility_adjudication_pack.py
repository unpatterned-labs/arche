#!/usr/bin/env python
"""Assemble state review samples into one immutable facility adjudication pack.

The input files are `adjudication_sample.csv` artifacts created by
`evaluate_facility_master.py`. The output is intentionally limited to review
inputs and a manifest. Reviewers fill only the four outcome columns in the CSV:
`review_outcome`, `reviewer`, `reviewed_at`, and `reason`.

Example::

    uv run --package arche-core python data/scripts/build_facility_adjudication_pack.py \
        --sample Kano=C:\\tmp\\arche-kano-evaluation\\adjudication_sample.csv \
        --sample Ondo=C:\\tmp\\arche-ondo-evaluation\\adjudication_sample.csv \
        --sample Edo=C:\\tmp\\arche-edo-evaluation\\adjudication_sample.csv \
        --output data/review_packs/nigeria_facilities_2026-08-19
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

OUTCOME_FIELDS = ("review_outcome", "reviewer", "reviewed_at", "reason")


def _sha256(path: Path) -> str:
    """Return the SHA-256 digest of one source artifact."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _parse_sample(value: str) -> tuple[str, Path]:
    """Parse one ``STATE=PATH`` command-line value."""
    state, separator, raw_path = value.partition("=")
    if not separator or not state.strip() or not raw_path.strip():
        raise argparse.ArgumentTypeError("--sample must have the form STATE=PATH")
    path = Path(raw_path).expanduser()
    if not path.is_file():
        raise argparse.ArgumentTypeError(f"sample file not found: {path}")
    return state.strip(), path


def _read_sample(state: str, path: Path) -> list[dict[str, str]]:
    """Read and validate one state sample before it enters the pack."""
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        raise ValueError(f"{state}: sample has no rows: {path}")
    fields = set(rows[0])
    missing = {"decision_id", "decision", *OUTCOME_FIELDS} - fields
    if missing:
        raise ValueError(f"{state}: sample is missing columns {sorted(missing)}")
    for row in rows:
        if row["decision"] not in {"match", "review"}:
            raise ValueError(f"{state}: invalid decision {row['decision']!r}")
        if any((row.get(field) or "").strip() for field in OUTCOME_FIELDS):
            raise ValueError(f"{state}: sample is already annotated: {path}")
        row["state"] = state
    return rows


def main() -> None:
    """Build a new review pack from one or more state samples."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--sample", action="append", type=_parse_sample, required=True,
        help="State and input CSV as STATE=PATH; repeat for every state",
    )
    parser.add_argument("--output", type=Path, required=True, help="New output directory")
    args = parser.parse_args()

    if args.output.exists() and any(args.output.iterdir()):
        raise ValueError(f"output directory must be new or empty: {args.output}")
    if len({state.casefold() for state, _ in args.sample}) != len(args.sample):
        raise ValueError("each state may appear only once")

    rows: list[dict[str, str]] = []
    sources = []
    for state, path in sorted(args.sample, key=lambda item: item[0].casefold()):
        state_rows = _read_sample(state, path)
        rows.extend(state_rows)
        sources.append({
            "state": state,
            "path": str(path),
            "sha256": _sha256(path),
            "rows": len(state_rows),
            "decisions": dict(sorted(Counter(row["decision"] for row in state_rows).items())),
        })

    decision_ids = [row["decision_id"] for row in rows]
    if len(set(decision_ids)) != len(decision_ids):
        raise ValueError("samples contain duplicate decision_id values")

    args.output.mkdir(parents=True, exist_ok=True)
    output_csv = args.output / "adjudication_pack.csv"
    fields = ["state", *[field for field in rows[0] if field != "state"]]
    with output_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

    manifest: dict[str, Any] = {
        "schema": "arche.facility_adjudication_pack.v1",
        "review_outcomes": ["same_entity", "different", "unresolved"],
        "review_fields": list(OUTCOME_FIELDS),
        "sources": sources,
        "rows": len(rows),
        "decisions": dict(sorted(Counter(row["decision"] for row in rows).items())),
        "decision_ids_sha256": hashlib.sha256(
            "\n".join(sorted(decision_ids)).encode()
        ).hexdigest(),
    }
    (args.output / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(manifest, indent=2, sort_keys=True))
    print(f"wrote {output_csv}")


if __name__ == "__main__":
    main()
