#!/usr/bin/env python
"""Create a pinned, reviewable Nigeria health-facility crosswalk.

This is a reconciliation and adjudication workflow, not an accuracy benchmark.
It compares the local GRID3 master snapshot against an HFR state snapshot,
writes the surfaced candidate edges, and creates a deterministic sample for
domain review. It does not report precision or recall because the inputs do not
provide complete independent truth labels.

Example::

    uv run --package arche-core python data/scripts/evaluate_facility_master.py \
        --state Kano --output C:\\tmp\\arche-kano-evaluation
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

from arche.resolve import crosswalk

REPOSITORY = Path(__file__).resolve().parents[2]
DATA = REPOSITORY / "data"


def _sha256(path: Path) -> str:
    """Return the SHA-256 digest of one input file."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _float(value: str | None) -> float | None:
    """Return a finite coordinate value or ``None``."""
    try:
        parsed = float(value or "")
    except (TypeError, ValueError):
        return None
    return parsed if -180 <= parsed <= 180 else None


def _admin_path(state: str | None, lga: str | None, ward: str | None) -> dict[str, str]:
    """Build the structured administrative path expected by the place pack."""
    values = {
        "admin1": state,
        "admin2": lga,
        "settlement": ward,
    }
    return {
        level: str(value).strip()
        for level, value in values.items()
        if str(value or "").strip()
    }


def _grid3_records(path: Path, state: str) -> list[dict[str, Any]]:
    """Map one GRID3 state slice to the place-pack field contract."""
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = csv.DictReader(handle)
        records = []
        for row in rows:
            if (row.get("state") or "").strip().casefold() != state.casefold():
                continue
            name = (row.get("facility_name") or "").strip()
            if not name:
                continue
            records.append({
                "id": f"grid3:{row.get('globalid') or row.get('nhfr_uid') or row.get('OBJECTID')}",
                "name": name,
                "lat": _float(row.get("latitude")),
                "lon": _float(row.get("longitude")),
                "admin_path": _admin_path(row.get("state"), row.get("lga"), row.get("ward")),
                "source_code": row.get("nhfr_facility_code") or "",
                "source_name": "GRID3",
            })
    return records


def _hfr_records(path: Path, state: str) -> list[dict[str, Any]]:
    """Map one HFR state snapshot to the place-pack field contract."""
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = csv.DictReader(handle)
        records = []
        for row in rows:
            name = (row.get("name") or row.get("alternate_name") or "").strip()
            if not name:
                continue
            records.append({
                "id": f"hfr:{row.get('id')}",
                "name": name,
                "lat": _float(row.get("lat")),
                "lon": _float(row.get("lon")),
                "admin_path": _admin_path(state, row.get("lga"), row.get("ward_code")),
                "source_code": row.get("id") or "",
                "source_name": "HFR",
            })
    return records


def _edge_rows(
    result: dict[str, Any], left: list[dict[str, Any]], right: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Render surfaced edges with source context for review."""
    by_left = {record["id"]: record for record in left}
    by_right = {record["id"]: record for record in right}
    rows = []
    for edge in result["matches"]:
        a = by_left[edge["a_id"]]
        b = by_right[edge["b_id"]]
        rows.append({
            "decision_id": edge["decision_id"],
            "decision": edge["decision"],
            "score": edge["score"],
            "distinctive_max": edge["distinctive_max"],
            "distance_km": edge["evidence"].get("distance_km", ""),
            "grid3_id": a["id"],
            "grid3_code": a["source_code"],
            "grid3_name": a["name"],
            "grid3_admin_path": json.dumps(a["admin_path"], sort_keys=True),
            "hfr_id": b["id"],
            "hfr_code": b["source_code"],
            "hfr_name": b["name"],
            "hfr_admin_path": json.dumps(b["admin_path"], sort_keys=True),
            "evidence": json.dumps(edge["evidence"], sort_keys=True),
            "review_outcome": "",
            "reviewer": "",
            "reviewed_at": "",
            "reason": "",
        })
    return rows


def _sample(rows: list[dict[str, Any]], size: int) -> list[dict[str, Any]]:
    """Select a deterministic, decision-balanced adjudication sample."""
    groups: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        groups.setdefault(row["decision"], []).append(row)
    active = [decision for decision, items in groups.items() if items]
    if not active or size <= 0:
        return []
    quota, remainder = divmod(size, len(active))
    selected = []
    for index, decision in enumerate(sorted(active)):
        items = sorted(groups[decision], key=lambda item: item["decision_id"])
        selected.extend(items[:quota + (1 if index < remainder else 0)])
    return selected


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    """Write rows with a stable empty-file header when needed."""
    fields = [
        "decision_id", "decision", "score", "distinctive_max", "distance_km",
        "grid3_id", "grid3_code", "grid3_name", "grid3_admin_path",
        "hfr_id", "hfr_code", "hfr_name", "hfr_admin_path", "evidence",
        "review_outcome", "reviewer", "reviewed_at", "reason",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    """Run the reconciliation and write review artifacts."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", required=True, help="State name, for example Kano")
    parser.add_argument(
        "--grid3", type=Path, default=DATA / "GRID3_NGA_health_facilities_v2.csv",
        help="GRID3 master CSV",
    )
    parser.add_argument(
        "--hfr", type=Path, default=None,
        help="HFR state CSV, defaults to data/hfr_<state>.csv",
    )
    parser.add_argument("--output", type=Path, required=True, help="Empty or new output directory")
    parser.add_argument(
        "--sample-size", type=int, default=200, help="Maximum review rows to sample"
    )
    args = parser.parse_args()

    hfr_path = args.hfr or DATA / f"hfr_{args.state.casefold()}.csv"
    if not args.grid3.is_file():
        raise FileNotFoundError(f"GRID3 input not found: {args.grid3}")
    if not hfr_path.is_file():
        raise FileNotFoundError(f"HFR input not found: {hfr_path}")
    if args.sample_size < 0:
        raise ValueError("--sample-size must be zero or greater")

    left = _grid3_records(args.grid3, args.state)
    right = _hfr_records(hfr_path, args.state)
    if not left or not right:
        raise ValueError(
            f"No usable records for {args.state!r}: GRID3={len(left)}, HFR={len(right)}"
        )

    result = crosswalk(left, right, entity="place")
    rows = _edge_rows(result, left, right)
    counts = Counter(row["decision"] for row in rows)
    surfaced_left = {row["grid3_id"] for row in rows}
    surfaced_right = {row["hfr_id"] for row in rows}

    args.output.mkdir(parents=True, exist_ok=True)
    _write_csv(args.output / "candidate_edges.csv", rows)
    _write_csv(args.output / "adjudication_sample.csv", _sample(rows, args.sample_size))
    summary = {
        "schema": "arche.facility_reconciliation.v1",
        "scope": "candidate generation and adjudication only; no accuracy claim without labels",
        "state": args.state,
        "inputs": {
            "grid3": {"path": str(args.grid3), "sha256": _sha256(args.grid3)},
            "hfr": {"path": str(hfr_path), "sha256": _sha256(hfr_path)},
        },
        "records": {"grid3": len(left), "hfr": len(right)},
        "crosswalk": {
            "pins": result["pins"],
            "blocking": result["blocking"],
            "candidate_edges": len(rows),
            "decisions": dict(sorted(counts.items())),
            "grid3_records_surfaced": len(surfaced_left),
            "hfr_records_surfaced": len(surfaced_right),
            "adjudication_sample_size": len(_sample(rows, args.sample_size)),
        },
    }
    (args.output / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary["crosswalk"], indent=2, sort_keys=True))
    print(f"wrote {args.output / 'candidate_edges.csv'}")
    print(f"wrote {args.output / 'adjudication_sample.csv'}")
    print(f"wrote {args.output / 'summary.json'}")


if __name__ == "__main__":
    main()
