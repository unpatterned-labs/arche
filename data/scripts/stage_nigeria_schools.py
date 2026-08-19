#!/usr/bin/env python
# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0
"""Stage the GRID3 Nigeria schools register into the gitignored cache.

    python data/scripts/stage_nigeria_schools.py --csv Schools_in_Nigeria.csv

The register is public (GRID3 / NGA schools), but it is 25 MB of real facility
records and it is not this repository's to redistribute. It is copied into
`data/_cache/schools/`, which is gitignored, and the notebook reads it there.
"""
from __future__ import annotations

import argparse
import csv
import shutil
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
OUT = _REPO / "data" / "_cache" / "schools" / "nigeria_schools.csv"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", required=True, type=Path)
    a = ap.parse_args()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(a.csv, OUT)
    rows = list(csv.DictReader(OUT.open(encoding="utf-8-sig")))
    need = {"name", "source", "statename", "uniq_id", "x", "y"}
    missing = need - set(rows[0]) if rows else need
    if missing:
        raise SystemExit(f"staged file is missing columns: {sorted(missing)}")
    print(f"  staged {len(rows):,} records -> {OUT}  (gitignored)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
