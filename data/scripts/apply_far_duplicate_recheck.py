#!/usr/bin/env python
"""Turn the far-duplicate recheck's outcomes into a corrections file for training.

Reads the reviewed recheck pack and writes ``corrections.json`` beside it:
decision id -> the recheck outcome. Development reads from the next experiment
on apply it over the labels they correct. No source file is changed. Only
counts are printed.

    python data/scripts/apply_far_duplicate_recheck.py
"""

from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter
from pathlib import Path

PACK = (Path(__file__).resolve().parents[1] / "review_packs"
        / "nigeria_facilities_far_duplicates_2026-11-23")


def main() -> None:
    src = PACK / "adjudication_pack_reviewed.csv"
    with src.open(encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    outcomes = {r["decision_id"]: r["review_outcome"] for r in rows if r["review_outcome"]}
    out = {"schema": "arche.label_corrections.v1",
           "source": src.name,
           "source_sha256": "sha256:" + hashlib.sha256(src.read_bytes()).hexdigest(),
           "outcomes": dict(sorted(outcomes.items()))}
    (PACK / "corrections.json").write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"rows": len(rows), "outcomes": Counter(outcomes.values()),
                      "by_source_pack": Counter((r["source_pack"], r["review_outcome"])
                                                for r in rows).most_common()}, default=str))


if __name__ == "__main__":
    main()
