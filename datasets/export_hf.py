#!/usr/bin/env python3
# Copyright 2026 unpatterned.ai
#
# Licensed under CC-BY-NC-SA 4.0 (dataset) / Apache 2.0 (this script).
# See DATASET_LICENSE.md for dataset terms.

"""Export the African Cultural Naming Intelligence Dataset to HuggingFace-compatible formats.

Reads the YAML source files in name_equivalences/ and produces:
  - CSV  (one row per canonical-variant pair)
  - JSONL (one JSON object per line)
  - Parquet (if pyarrow is installed)

All output goes to datasets/data/.

Usage:
    python datasets/export_hf.py
    # or from the repo root:
    python -m datasets.export_hf
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    print(
        "ERROR: PyYAML is required. Install with: pip install pyyaml",
        file=sys.stderr,
    )
    sys.exit(1)


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

SCRIPT_DIR = Path(__file__).resolve().parent
YAML_DIR = SCRIPT_DIR / "name_equivalences"
OUTPUT_DIR = SCRIPT_DIR / "data"

STEM = "african_naming_equivalences"


# ---------------------------------------------------------------------------
# Load
# ---------------------------------------------------------------------------

def load_all_groups() -> list[dict[str, str]]:
    """Load all YAML files and flatten into one-row-per-variant records.

    Returns a list of dicts with keys: canonical, variant, tradition, file.
    Each canonical name also gets a self-referencing row (variant == canonical)
    so the dataset is complete -- every name form appears as a variant.
    """
    rows: list[dict[str, str]] = []

    if not YAML_DIR.is_dir():
        print(f"ERROR: YAML directory not found at {YAML_DIR}", file=sys.stderr)
        sys.exit(1)

    yaml_files = sorted(YAML_DIR.glob("*.yaml"))
    if not yaml_files:
        print(f"ERROR: No YAML files found in {YAML_DIR}", file=sys.stderr)
        sys.exit(1)

    for yaml_file in yaml_files:
        with open(yaml_file, encoding="utf-8") as f:
            data = yaml.safe_load(f)

        if not data or "groups" not in data:
            print(f"WARNING: Skipping {yaml_file.name} (no 'groups' key)", file=sys.stderr)
            continue

        tradition = data.get("tradition", yaml_file.stem)
        file_stem = yaml_file.stem

        for group in data["groups"]:
            canonical = group.get("canonical", "")
            variants = group.get("variants", [])

            if not canonical:
                continue

            # Self-referencing row for the canonical form
            rows.append({
                "canonical": canonical,
                "variant": canonical,
                "tradition": tradition,
                "file": file_stem,
            })

            # One row per variant
            for variant in variants:
                rows.append({
                    "canonical": canonical,
                    "variant": variant,
                    "tradition": tradition,
                    "file": file_stem,
                })

    return rows


# ---------------------------------------------------------------------------
# Export functions
# ---------------------------------------------------------------------------

FIELDNAMES = ["canonical", "variant", "tradition", "file"]


def export_csv(rows: list[dict[str, str]], output_path: Path) -> None:
    """Write rows to a CSV file."""
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)
    print(f"  CSV:     {output_path}  ({len(rows)} rows)")


def export_jsonl(rows: list[dict[str, str]], output_path: Path) -> None:
    """Write rows to a JSON Lines file."""
    with open(output_path, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"  JSONL:   {output_path}  ({len(rows)} rows)")


def export_parquet(rows: list[dict[str, str]], output_path: Path) -> None:
    """Write rows to a Parquet file (requires pyarrow)."""
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError:
        print("  Parquet: SKIPPED (pyarrow not installed -- pip install pyarrow)")
        return

    table = pa.table({
        field: [row[field] for row in rows]
        for field in FIELDNAMES
    })
    pq.write_table(table, output_path)
    print(f"  Parquet: {output_path}  ({len(rows)} rows)")


# ---------------------------------------------------------------------------
# Summary statistics
# ---------------------------------------------------------------------------

def print_summary(rows: list[dict[str, str]]) -> None:
    """Print dataset summary statistics."""
    # Exclude self-referencing rows for variant count
    variant_rows = [r for r in rows if r["canonical"] != r["variant"]]
    canonicals = {r["canonical"] for r in rows}
    traditions = {r["file"] for r in rows}

    print("\n--- Dataset Summary ---")
    print(f"  Equivalence groups:  {len(canonicals)}")
    print(f"  Variant spellings:   {len(variant_rows)}")
    print(f"  Total rows (incl. self-ref): {len(rows)}")
    print(f"  Source files:        {len(traditions)}")
    print()

    print("  By tradition:")
    for tradition in sorted(traditions):
        t_rows = [r for r in rows if r["file"] == tradition]
        t_canonicals = {r["canonical"] for r in t_rows}
        t_variants = [r for r in t_rows if r["canonical"] != r["variant"]]
        label = t_rows[0]["tradition"] if t_rows else tradition
        print(f"    {tradition:25s}  {len(t_canonicals):3d} groups, {len(t_variants):3d} variants  ({label})")
    print()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    """Load YAML data and export to all formats."""
    print(f"Loading YAML files from {YAML_DIR}...")
    rows = load_all_groups()

    if not rows:
        print("ERROR: No data loaded.", file=sys.stderr)
        sys.exit(1)

    print_summary(rows)

    # Create output directory
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    print(f"Exporting to {OUTPUT_DIR}/...")
    export_csv(rows, OUTPUT_DIR / f"{STEM}.csv")
    export_jsonl(rows, OUTPUT_DIR / f"{STEM}.jsonl")
    export_parquet(rows, OUTPUT_DIR / f"{STEM}.parquet")

    print("\nDone. Upload to HuggingFace with:")
    print(f"  huggingface-cli upload unpatterned/african-cultural-naming {OUTPUT_DIR} data/")
    print()


if __name__ == "__main__":
    main()
