#!/usr/bin/env python
"""Compare Arche and common string rules on staged Nigeria school sources.

This produces candidate counts and a review pack. It does not calculate
precision, recall, F1, or false merges because the Nigeria sources have no
independent pair labels.

Example::

    uv run --package arche-core python data/scripts/evaluate_nigeria_school_reconciliation.py \
        --input C:\\tmp\\arche-nigeria-schools-ikeja \
        --output C:\\tmp\\arche-nigeria-schools-ikeja-evaluation
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from arche.resolve import crosswalk

try:
    from rapidfuzz import fuzz
except ModuleNotFoundError as error:  # pragma: no cover - dependency is in arche-core
    raise RuntimeError("rapidfuzz is required for the token-set comparison") from error

EDGE_FIELDS = [
    "decision_id", "comparison_source", "decision", "score", "distinctive_max",
    "distance_km", "reference_id", "reference_name", "reference_lat", "reference_lon",
    "source_id", "source_name", "source_lat", "source_lon", "source_category", "evidence",
    "review_outcome", "reviewer", "reviewed_at", "reason",
]


def _read_csv(path: Path) -> list[dict[str, str]]:
    """Read one UTF-8 staged CSV."""
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _write_csv(path: Path, fields: list[str], rows: list[dict[str, str]]) -> None:
    """Write rows with a stable CSV field order."""
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _sha256(path: Path) -> str:
    """Return a SHA-256 digest for one input artifact."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _tokens(value: str) -> set[str]:
    """Return lowercase word tokens for the simple Jaccard baseline."""
    return {token for token in re.split(r"[^\w]+", value.casefold()) if token}


def _jaccard(left: str, right: str) -> float:
    """Return word-token Jaccard similarity."""
    left_tokens, right_tokens = _tokens(left), _tokens(right)
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)


def _baseline_counts(
    reference: list[dict[str, str]], source: list[dict[str, str]]
) -> dict[str, int]:
    """Count pairs selected by simple rules, without calling them correct."""
    counts = Counter()
    for left in reference:
        for right in source:
            first, second = left["name"].strip(), right["name"].strip()
            if first.casefold() == second.casefold():
                counts["exact_name_casefold"] += 1
            if _jaccard(first, second) >= 0.5:
                counts["token_jaccard_gte_0_5"] += 1
            if fuzz.token_set_ratio(first, second) >= 90:
                counts["token_set_ratio_gte_90"] += 1
    return dict(counts)


def _as_arche_records(
    rows: list[dict[str, str]], prefix: str, identifier: str
) -> list[dict[str, Any]]:
    """Map a staged source to the Arche place-record contract."""
    return [
        {
            "id": f"{prefix}:{row[identifier]}",
            "name": row["name"],
            "lat": float(row["lat"]),
            "lon": float(row["lon"]),
        }
        for row in rows
    ]


def _edge_rows(
    result: dict[str, Any],
    reference: list[dict[str, str]],
    source: list[dict[str, str]],
    source_name: str,
    source_id: str,
) -> list[dict[str, str]]:
    """Render only surfaced Arche edges with source context for review."""
    left = {f"reference:{row['school_id']}": row for row in reference}
    right = {f"{source_name}:{row[source_id]}": row for row in source}
    rows = []
    for edge in result["matches"]:
        reference_row, source_row = left[edge["a_id"]], right[edge["b_id"]]
        rows.append({
            "decision_id": edge["decision_id"],
            "comparison_source": source_name,
            "decision": edge["decision"],
            "score": str(edge["score"]),
            "distinctive_max": str(edge["distinctive_max"]),
            "distance_km": str(edge["evidence"].get("distance_km", "")),
            "reference_id": reference_row["school_id"],
            "reference_name": reference_row["name"],
            "reference_lat": reference_row["lat"],
            "reference_lon": reference_row["lon"],
            "source_id": source_row[source_id],
            "source_name": source_row["name"],
            "source_lat": source_row["lat"],
            "source_lon": source_row["lon"],
            "source_category": source_row.get("category", source_row.get("amenity", "")),
            "evidence": json.dumps(edge["evidence"], sort_keys=True),
            "review_outcome": "",
            "reviewer": "",
            "reviewed_at": "",
            "reason": "",
        })
    return rows


def _review_sample(rows: list[dict[str, str]], per_group: int) -> list[dict[str, str]]:
    """Select a deterministic source and decision-balanced reviewer sample."""
    groups: dict[tuple[str, str], list[dict[str, str]]] = {}
    for row in rows:
        groups.setdefault((row["comparison_source"], row["decision"]), []).append(row)
    selected = []
    for key in sorted(groups):
        selected.extend(sorted(groups[key], key=lambda row: row["decision_id"])[:per_group])
    return selected


def _evaluate_source(
    reference: list[dict[str, str]],
    source: list[dict[str, str]],
    source_name: str,
    source_id: str,
    block: str,
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    """Run one source against the inventory and return counts plus review rows."""
    result = crosswalk(
        _as_arche_records(reference, "reference", "school_id"),
        _as_arche_records(source, source_name, source_id),
        entity="place",
        block=block,
    )
    edges = _edge_rows(result, reference, source, source_name, source_id)
    decisions = Counter(row["decision"] for row in edges)
    return {
        "records": len(source),
        "all_possible_pairs": len(reference) * len(source),
        "simple_string_selected_pairs": _baseline_counts(reference, source),
        "arche_surfaced_edges": len(edges),
        "arche_decisions": dict(sorted(decisions.items())),
        "arche_pins": result["pins"],
        "arche_blocking": result["blocking"],
    }, edges


def _prepare_output(path: Path) -> None:
    """Create an empty output directory without overwriting a prior evaluation."""
    if path.exists() and any(path.iterdir()):
        raise FileExistsError(f"Output directory is not empty: {path}")
    path.mkdir(parents=True, exist_ok=True)


def main() -> None:
    """Run candidate comparison for staged Nigeria school sources."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input", type=Path, required=True, help="Directory from stage_nigeria_schools.py"
    )
    parser.add_argument("--output", type=Path, required=True, help="New or empty output directory")
    parser.add_argument(
        "--sample-per-group", type=int, default=50, help="Review rows per source and decision"
    )
    parser.add_argument(
        "--block", choices=("h3", "union"), default="h3",
        help="Candidate blocker. h3 is appropriate because all staged rows have coordinates.",
    )
    args = parser.parse_args()
    if args.sample_per_group < 0:
        raise ValueError("--sample-per-group must be zero or greater")
    names = ("reference.csv", "osm.csv", "overture.csv", "manifest.json")
    files = {name: args.input / name for name in names}
    missing = [str(path) for path in files.values() if not path.is_file()]
    if missing:
        raise FileNotFoundError("Missing staged input: " + ", ".join(missing))
    _prepare_output(args.output)
    reference, osm, overture = (
        _read_csv(files[name]) for name in ("reference.csv", "osm.csv", "overture.csv")
    )
    if not all((reference, osm, overture)):
        raise ValueError(
            "Reference, OSM, and Overture inputs must each contain at least one record"
        )

    comparisons = {}
    all_edges = []
    for rows, name, identifier in ((osm, "osm", "osm_id"), (overture, "overture", "overture_id")):
        comparison, edges = _evaluate_source(reference, rows, name, identifier, args.block)
        comparisons[name] = comparison
        all_edges.extend(edges)
    _write_csv(args.output / "candidate_edges.csv", EDGE_FIELDS, all_edges)
    sample = _review_sample(all_edges, args.sample_per_group)
    _write_csv(args.output / "review_sample.csv", EDGE_FIELDS, sample)
    summary = {
        "schema": "arche.nigeria_school_reconciliation.v1",
        "scope": (
            "candidate comparison only. The sources have no independent pair labels, "
            "so this file reports no accuracy metrics."
        ),
        "inputs": {
            name: {"path": str(path), "sha256": _sha256(path)}
            for name, path in files.items()
        },
        "reference_records": len(reference),
        "comparisons": comparisons,
        "candidate_edges": len(all_edges),
        "review_sample_size": len(sample),
    }
    (args.output / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps({"candidate_edges": len(all_edges), "review_sample": len(sample)}, indent=2))


if __name__ == "__main__":
    try:
        main()
    except (FileExistsError, FileNotFoundError, RuntimeError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(2) from error
