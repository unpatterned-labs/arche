#!/usr/bin/env python
"""X17, dev districts only: which name refuter should the legal-entity pack carry?

A refuter only ever demotes a match to review, so each setting is applied to the
matches of one engine run without the premises refuter (``dev_no_premises.csv``)
rather than re-running the engine per setting. The setting chosen here is put in
the pack, and the pack itself is what runs on the held-out districts.

    uv run --package arche-core python data/scripts/x17_dev_refuters.py
"""

from __future__ import annotations

import csv
import importlib.util
import json
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("x17", HERE / "x17_uk_ch_legal_entity.py")
x17 = importlib.util.module_from_spec(_spec)
sys.modules["x17"] = x17
_spec.loader.exec_module(x17)
b, x16 = x17.b, x17.x16

SETTINGS = {
    "none": None,
    "rival_as_shipped": {},
    "mutual_no_shared_no_english": {"shared_overrides": False, "ordinary_words": False},
    "one_sided_no_shared_no_english": {"mutual": False, "shared_overrides": False,
                                       "ordinary_words": False},
    "one_sided_no_shared_no_english_near": {"mutual": False, "shared_overrides": False,
                                            "ordinary_words": False, "near": 0.85},
    "mutual_no_shared": {"shared_overrides": False},
}


def main() -> None:
    from arche.resolve._gate import rival_distinctive_tokens
    from arche.resolve._tokenfreq import TokenFrequencyTable
    from arche.resolve.reconcile import _text_values

    tf = TokenFrequencyTable.default("organisation")
    names = {r["id"]: r["name"] for r in b.providers()}
    names |= {r["id"]: r["name"] for rows in b.companies().values() for r in rows}
    with (x17.OUT / "dev_no_premises.csv").open(encoding="utf-8") as fh:
        edges = [e for e in csv.DictReader(fh) if e["decision"] == "match"]
    spec = {"field": "name", "strip_type": "organization"}
    out = {}
    for label, opts in SETTINGS.items():
        kept = []
        for e in edges:
            if opts is not None:
                a, c = _text_values(spec, {"name": names[e["cqc_id"]]},
                                    {"name": names[e["ch_id"]]}, "name")
                o = dict(opts)
                if rival_distinctive_tokens(a, c, tf, **o) == 0.0:
                    continue
            kept.append(e)
        path = x17.OUT / f"dev_refuter_{label}.csv"
        with path.open("w", encoding="utf-8", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(edges[0]))
            w.writeheader()
            w.writerows(kept)
        out[label] = path
    result = x17.score("dev", {"organisation": b.OUT / "candidate_edges.csv", **out})
    keep = defaultdict(dict)
    for arm, s in result["arms"].items():
        keep[arm] = {k: s[k] for k in ("links", "precision", "precision_wilson95",
                                       "recall_all", "recall_reachable")}
    print(json.dumps({"half": "dev", "providers": result["providers"], "arms": keep},
                     indent=1))
    (x17.OUT / "dev_refuters_result.json").write_text(
        json.dumps({"providers": result["providers"], "arms": keep}, indent=2) + "\n",
        encoding="utf-8")


if __name__ == "__main__":
    main()
