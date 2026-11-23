#!/usr/bin/env python
"""Apply the recheck pack's outcomes to the packs it rechecked, as new files.

The recheck pack (``build_recheck_pack.py``) put each suspect same_entity mark
back in front of the reviewer with the GRID3 facility's own HFR record beside
it. This writes, next to each source pack's reviewed file, a corrected copy
(``adjudication_pack_corrected_reviewed.csv``) in which every rechecked pair
carries the recheck outcome, reviewer, time and reason. The original reviewed
files are never touched. Only counts are printed.

    python data/scripts/apply_recheck.py
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

DATA = Path(__file__).resolve().parents[1]
PACKS = DATA / "review_packs"
RECHECK = PACKS / "nigeria_facilities_recheck_2026-11-22" / "adjudication_pack_reviewed.csv"
SOURCES = {
    "2026-08-19": PACKS / "nigeria_facilities_2026-08-19",
    "x1_2026-11-21": PACKS / "nigeria_facilities_x1_2026-11-21",
}
CARRIED = ("review_outcome", "reviewer", "reviewed_at", "reason")


def main() -> None:
    with RECHECK.open(encoding="utf-8") as fh:
        recheck = [r for r in csv.DictReader(fh) if r["review_outcome"]]
    summary: dict[str, dict[str, int]] = {}
    for label, folder in SOURCES.items():
        mine = {r["decision_id"]: r for r in recheck if r["source_pack"] == label}
        src = folder / "adjudication_pack_reviewed.csv"
        with src.open(encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            fields, rows = reader.fieldnames, list(reader)
        seen = flipped = 0
        for r in rows:
            fix = mine.get(r["decision_id"])
            if fix is None:
                continue
            seen += 1
            flipped += fix["review_outcome"] != r["review_outcome"]
            r.update({k: fix[k] for k in CARRIED})
        if seen != len(mine):
            raise SystemExit(f"{label}: {len(mine) - seen} rechecked pairs not found in {src}")
        out = folder / "adjudication_pack_corrected_reviewed.csv"
        with out.open("w", encoding="utf-8", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=fields)
            w.writeheader()
            w.writerows(rows)
        summary[label] = {"rows": len(rows), "rechecked": seen, "changed": flipped}
    print(json.dumps(summary))


if __name__ == "__main__":
    main()
