#!/usr/bin/env python
# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0
"""The Febrl 4 record-linkage result, made re-runnable.

    python datasets/names_dataops/bench_febrl.py

Why this script exists
----------------------
`concepts/the-whole-picture` has claimed **precision 1.0, 87.7% auto-resolved,
96.2% surfaced** on Febrl 4 since v0.1. Nothing in this repository computed it:
no script, no data, no result file. The number may well have been measured, but
a reader could not check it, and neither could we. This script replaces the
claim with something that runs.

The benchmark
-------------
**Febrl 4** (Freely Extensible Biomedical Record Linkage, ANU), as distributed
with the BSD-licensed `recordlinkage` package. Two files of 5,000 records:
`dataset4a` holds originals (`rec-N-org`), `dataset4b` holds one corrupted
duplicate each (`rec-N-dup-0`). Ground truth is therefore exact and complete —
`rec-N-org` matches `rec-N-dup-0` and nothing else — which is why 25 million
candidate pairs can be scored without anyone labelling them.

The corruptions are generated: typos, transpositions, field swaps, missing
values. That makes truth trustworthy and realism limited, which is the standard
trade in this dataset and the reason it is a scale and calibration test rather
than evidence about real registers.

Two configurations, because one of them is a trap
--------------------------------------------------
Febrl carries `soc_sec_id`, a near-unique synthetic identifier. Feeding it to
the `id` comparator (weight 3.0) makes the task close to trivial: the engine
stops resolving names and starts joining on a key. That measures nothing about
representation, which is the thing under test.

So the headline configuration is **name and address only**, with the identifier
withheld deliberately. The identifier-included run is reported underneath, not
because it is the honest number but because withholding it silently would be
the kind of choice this project keeps criticising elsewhere.

Pass criteria, declared before the run
---------------------------------------
1. Precision >= 0.99 in the name-and-address configuration. The original claim
   was 1.0; this asks for substantially the same thing while allowing that a
   number reproduced years later on a re-derived pipeline may not land exactly.
2. `match` recall within 10 points of the claimed 87.7%.
3. `match` + `review` recall within 10 points of the claimed 96.2%.

Criteria 2 and 3 test whether the *abstention split* still behaves as
advertised, which is the part of the claim that matters: arche's argument is
that sending the hard cases to `review` is what buys the precision.

Published whichever way they fall.

Licence
-------
Febrl data is fetched at run time into `data/_cache/`, which is gitignored, never vendored. The
data is synthetic and contains no real people, so this is a licence courtesy
rather than a privacy requirement.

    https://github.com/J535D165/recordlinkage  (BSD-3-Clause)
"""

from __future__ import annotations

import csv
import json
import sys
import urllib.request
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_REPO = _HERE.parents[1]
CACHE = _REPO / "data" / "_cache" / "febrl"
BASE = ("https://raw.githubusercontent.com/J535D165/recordlinkage/"
        "master/recordlinkage/datasets/febrl/")
FILES = ("dataset4a.csv", "dataset4b.csv")

# The claim this script exists to check, so the comparison is stated in code
# rather than left to the reader.
CLAIMED = {"precision": 1.0, "auto_resolved": 0.877, "surfaced": 0.962}

sys.path.insert(0, str(_REPO / "packages" / "arche-core" / "src"))


def _fetch(name: str) -> list[dict]:
    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / name
    if not path.exists():
        print(f"  downloading {name}", flush=True)
        req = urllib.request.Request(BASE + name,
                                     headers={"User-Agent": "arche-dataops/0.4"})
        with urllib.request.urlopen(req, timeout=300) as r:  # noqa: S310
            path.write_bytes(r.read())
    with path.open(encoding="utf-8") as fh:
        # Febrl's header has a leading space on every column but the first.
        return [{k.strip(): (v or "").strip() for k, v in row.items()}
                for row in csv.DictReader(fh)]


def _record(row: dict, *, with_id: bool) -> dict:
    addr = " ".join(x for x in (row.get("street_number"), row.get("address_1"),
                                row.get("address_2"), row.get("suburb"),
                                row.get("postcode"), row.get("state")) if x)
    rec = {
        "id": row["rec_id"],
        "name": " ".join(x for x in (row.get("given_name"),
                                     row.get("surname")) if x),
        "address": addr,
    }
    if with_id:
        rec["national_id"] = row.get("soc_sec_id", "")
    return rec


def _truth_key(rec_id: str) -> str:
    """`rec-1070-org` and `rec-1070-dup-0` share the entity number 1070."""
    return rec_id.split("-")[1]


def _score(a_rows: list[dict], b_rows: list[dict], *, with_id: bool) -> dict:
    from arche.resolve import reconcile

    list_a = [_record(r, with_id=with_id) for r in a_rows]
    list_b = [_record(r, with_id=with_id) for r in b_rows]
    res = reconcile(list_a, list_b, entity="person", id_field="id")

    n_true = len({_truth_key(r["rec_id"]) for r in a_rows}
                 & {_truth_key(r["rec_id"]) for r in b_rows})

    matched: set[str] = set()
    surfaced: set[str] = set()
    fp = 0
    for edge in res["matches"]:
        correct = _truth_key(edge["a_id"]) == _truth_key(edge["b_id"])
        if edge["decision"] == "match":
            if correct:
                matched.add(_truth_key(edge["a_id"]))
            else:
                fp += 1
        if edge["decision"] in ("match", "review") and correct:
            surfaced.add(_truth_key(edge["a_id"]))

    tp = len(matched)
    prec = tp / (tp + fp) if (tp + fp) else 0.0
    return {
        "pairs_truth": n_true,
        "true_merges": tp, "false_merges": fp,
        "precision": round(prec, 4),
        "auto_resolved": round(tp / n_true, 4) if n_true else 0.0,
        "surfaced": round(len(surfaced) / n_true, 4) if n_true else 0.0,
    }


def main() -> int:
    a_rows, b_rows = (_fetch(f) for f in FILES)
    a_rows, b_rows = list(a_rows), list(b_rows)
    print(f"Febrl 4: {len(a_rows):,} originals + {len(b_rows):,} duplicates "
          f"= {len(a_rows) * len(b_rows):,} candidate pairs\n", flush=True)

    results = {}
    for label, with_id in (("name + address", False),
                           ("name + address + soc_sec_id", True)):
        print(f"  running {label} ...", flush=True)
        results[label] = _score(a_rows, b_rows, with_id=with_id)

    print(f"\n  {'configuration':<30}{'precision':>11}{'auto':>9}"
          f"{'surfaced':>11}{'false merges':>14}")
    for label, r in results.items():
        print(f"  {label:<30}{r['precision']:>11.4f}{r['auto_resolved']:>9.1%}"
              f"{r['surfaced']:>11.1%}{r['false_merges']:>14,}")

    head = results["name + address"]
    print(f"\n  claimed since v0.1: precision {CLAIMED['precision']:.4f}, "
          f"auto {CLAIMED['auto_resolved']:.1%}, "
          f"surfaced {CLAIMED['surfaced']:.1%}")

    c1 = head["precision"] >= 0.99
    c2 = abs(head["auto_resolved"] - CLAIMED["auto_resolved"]) <= 0.10
    c3 = abs(head["surfaced"] - CLAIMED["surfaced"]) <= 0.10

    print("\n  pre-declared criteria (set before the run):")
    print(f"    1. precision >= 0.99                 : "
          f"{head['precision']:.4f}  {'PASS' if c1 else 'FAIL'}")
    print(f"    2. auto-resolved within 10pt of 87.7%: "
          f"{head['auto_resolved'] - CLAIMED['auto_resolved']:+.1%}  "
          f"{'PASS' if c2 else 'FAIL'}")
    print(f"    3. surfaced within 10pt of 96.2%     : "
          f"{head['surfaced'] - CLAIMED['surfaced']:+.1%}  "
          f"{'PASS' if c3 else 'FAIL'}")
    verdict = "PASS" if (c1 and c2 and c3) else "FAIL"
    print(f"\n  VERDICT: {verdict} — published either way, per standing practice.")

    # The identifier-included run reproduces the v0.1 claim to every figure
    # published. That is the finding, and it is worth more than the verdict.
    idr = results["name + address + soc_sec_id"]
    exact = (abs(idr["precision"] - CLAIMED["precision"]) < 5e-4
             and abs(idr["auto_resolved"] - CLAIMED["auto_resolved"]) < 5e-4
             and abs(idr["surfaced"] - CLAIMED["surfaced"]) < 5e-4)
    if exact:
        print("\n  FINDING: the identifier-included configuration reproduces the")
        print("  v0.1 claim exactly — precision, auto-resolved and surfaced all")
        print("  land on the published figures. So the number was real and is")
        print("  still reachable. What it measured is the question: with a")
        print("  near-unique synthetic key in play the engine is largely")
        print("  joining on that key, and the surrounding prose reads as though")
        print("  it resolved names and addresses at scale. Withhold the key and")
        print(f"  precision is {head['precision']:.4f} with "
              f"{head['false_merges']} false merges.")
        print("\n  The criteria above fail because they ask the harder")
        print("  configuration to hit the easier one's numbers. They are left")
        print("  failing: the point is that those numbers were never about")
        print("  name resolution.")

    out = _HERE / "bench_febrl_result.json"
    out.write_text(json.dumps({
        "benchmark": "Febrl 4 (ANU), via the recordlinkage package",
        "what_it_is": "synthetic record linkage with exact complete truth; "
                      "a scale and abstention test, not evidence about real "
                      "registers",
        "source_url": BASE,
        "records_a": len(a_rows), "records_b": len(b_rows),
        "claimed_since_v0_1": CLAIMED,
        "configurations": results,
        "criteria": {"precision_at_least_0_99": c1,
                     "auto_resolved_within_10pt": c2,
                     "surfaced_within_10pt": c3},
        "verdict": verdict,
    }, indent=2), encoding="utf-8")
    print(f"  -> {out.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
