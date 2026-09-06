#!/usr/bin/env python
# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0
"""The benchmark gate: did the resolver drift?

    python data/scripts/benchmark_gate.py            # compare against the recorded results
    python data/scripts/benchmark_gate.py --update   # re-record them, deliberately
    python data/scripts/benchmark_gate.py --json OUT # also write a machine-readable summary

Why this exists
---------------
On 2026-08-22 a blocking change nearly doubled the candidate pairs on Febrl 4
and the scorer merged 202 more wrong pairs: precision 0.9209 -> 0.8716. It was
a defensible trade -- the same change recovered 27,055 true pairs elsewhere --
but nobody knew it had happened until 2026-09-05, because the number lived in
a JSON file that nothing compared against the code. A benchmark that is not
gated is a benchmark that drifts.

What it runs
------------
The two complete-truth sets that finish in minutes on a CI runner, each with
exactly the configuration its result file records:

* **DBLP-ACM**, hand-declared bibliographic comparators, `year` refuting
  (`data/er_bench/benchmark_leipzig_result.json`, `year_refutes_below_0.99`).
* **Febrl 4**, name + address, identifier withheld
  (`datasets/names_dataops/bench_febrl_result.json`, `name + address`).

The rule
--------
FAIL when precision falls more than 0.005 below the recorded value, or true
merges fall more than 0.5% below it. An *improvement* passes and is reported,
so the recorded value can be raised with `--update` in the same change that
earned it; a silent improvement is the same species of drift as a silent
regression, just with the sign flipped.

Nothing here is a claim about accuracy. It is a claim that today's engine
produces today's recorded number, and a stop if it does not.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_REPO = _HERE.parents[1]
sys.path.insert(0, str(_REPO / "packages" / "arche-core" / "src"))
sys.path.insert(0, str(_REPO / "datasets" / "names_dataops"))

PRECISION_TOLERANCE = 0.005
TRUE_MERGE_TOLERANCE = 0.005

LEIPZIG = _REPO / "data" / "er_bench" / "benchmark_leipzig_result.json"
FEBRL = _REPO / "datasets" / "names_dataops" / "bench_febrl_result.json"


def _dblp_acm() -> dict:
    """The refuting configuration of `benchmark_leipzig.py`, scored the same way."""
    from arche.resolve import reconcile

    data = _REPO / "data" / "er_bench"

    def read(name: str) -> list[dict]:
        with open(data / name, encoding="utf-8-sig", errors="replace", newline="") as fh:
            return list(csv.DictReader(fh))

    dblp, acm = read("DBLP2.csv"), read("ACM.csv")
    truth = {(r["idDBLP"], r["idACM"]) for r in read("DBLP-ACM_perfectMapping.csv")}
    fields = ("title", "authors", "year")
    a = [{"id": r["id"], **{f: r[f] for f in fields}} for r in dblp]
    b = [{"id": r["id"], **{f: r[f] for f in fields}} for r in acm]
    comparators = [
        {"field": "title", "kind": "name", "weight": 3.0},
        {"field": "title", "kind": "tftoken", "weight": 2.0},
        {"field": "authors", "kind": "name", "weight": 2.0},
        {"field": "year", "kind": "date", "weight": 0.5, "refutes_below": 0.99},
    ]
    res = reconcile(a, b, comparators=comparators, id_field="id")
    matched = {(e["a_id"], e["b_id"]) for e in res["matches"] if e["decision"] == "match"}
    tp, fp = len(matched & truth), len(matched - truth)
    return {"true_merges": tp, "false_merges": fp,
            "precision": round(tp / (tp + fp), 4) if tp + fp else 0.0}


def _febrl() -> dict:
    """`bench_febrl.py`'s name + address configuration, via its own harness."""
    import bench_febrl

    a, b = (list(bench_febrl._fetch(f)) for f in bench_febrl.FILES)
    r = bench_febrl._score(a, b, with_id=False)
    return {"true_merges": r["true_merges"], "false_merges": r["false_merges"],
            "precision": r["precision"]}


def _recorded_dblp() -> dict:
    cfg = json.loads(LEIPZIG.read_text(encoding="utf-8"))["configurations"]
    c = cfg["year_refutes_below_0.99"]
    return {"true_merges": c["tp"], "false_merges": c["fp"], "precision": round(c["precision"], 4)}


def _recorded_febrl() -> dict:
    cfg = json.loads(FEBRL.read_text(encoding="utf-8"))["configurations"]["name + address"]
    return {"true_merges": cfg["true_merges"], "false_merges": cfg["false_merges"],
            "precision": cfg["precision"]}


def _write_dblp(now: dict) -> None:
    doc = json.loads(LEIPZIG.read_text(encoding="utf-8"))
    c = doc["configurations"]["year_refutes_below_0.99"]
    c["tp"], c["fp"] = now["true_merges"], now["false_merges"]
    c["precision"] = now["precision"]
    LEIPZIG.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")


def _write_febrl(now: dict) -> None:
    doc = json.loads(FEBRL.read_text(encoding="utf-8"))
    c = doc["configurations"]["name + address"]
    c["true_merges"], c["false_merges"] = now["true_merges"], now["false_merges"]
    c["precision"] = now["precision"]
    FEBRL.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")


BENCHMARKS = (
    ("DBLP-ACM, year refutes", _dblp_acm, _recorded_dblp, _write_dblp, LEIPZIG),
    ("Febrl 4, name + address", _febrl, _recorded_febrl, _write_febrl, FEBRL),
)


def judge(name: str, recorded: dict, now: dict) -> dict:
    precision_drop = recorded["precision"] - now["precision"]
    true_floor = recorded["true_merges"] * (1 - TRUE_MERGE_TOLERANCE)
    failed = precision_drop > PRECISION_TOLERANCE or now["true_merges"] < true_floor
    improved = (now["precision"] > recorded["precision"] + 1e-9
                or now["true_merges"] > recorded["true_merges"])
    return {
        "benchmark": name,
        "recorded": recorded,
        "now": now,
        "status": "FAIL" if failed else ("IMPROVED" if improved else "PASS"),
        "precision_delta": round(now["precision"] - recorded["precision"], 4),
        "true_merge_delta": now["true_merges"] - recorded["true_merges"],
        "false_merge_delta": now["false_merges"] - recorded["false_merges"],
    }


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--update", action="store_true",
                    help="re-record the baselines from this run (a deliberate act)")
    ap.add_argument("--json", default=None, help="write the summary here as JSON")
    ap.add_argument("--only", choices=["dblp-acm", "febrl"], default=None)
    args = ap.parse_args(argv[1:])

    results = []
    for name, run, recorded_fn, write, path in BENCHMARKS:
        if args.only and not name.lower().startswith(args.only):
            continue
        t0 = time.perf_counter()
        now = run()
        seconds = round(time.perf_counter() - t0, 1)
        verdict = judge(name, recorded_fn(), now)
        verdict["seconds"] = seconds
        verdict["file"] = str(path.relative_to(_REPO))
        results.append(verdict)
        r, n = verdict["recorded"], verdict["now"]
        print(f"{verdict['status']:<9} {name:<26} "
              f"precision {r['precision']:.4f} -> {n['precision']:.4f}"
              f"  true {r['true_merges']} -> {n['true_merges']}"
              f"  false {r['false_merges']} -> {n['false_merges']}  ({seconds}s)", flush=True)
        if args.update and verdict["status"] != "PASS":
            write(now)
            print(f"          re-recorded in {verdict['file']}")

    if args.json:
        Path(args.json).write_text(json.dumps({
            "tolerances": {"precision": PRECISION_TOLERANCE, "true_merges": TRUE_MERGE_TOLERANCE},
            "results": results,
        }, indent=2), encoding="utf-8")

    failed = [r for r in results if r["status"] == "FAIL"]
    improved = [r for r in results if r["status"] == "IMPROVED"]
    if failed:
        print(f"\nGATE FAILED: {len(failed)} benchmark(s) below the recorded result. "
              "If the change is intended, re-record with --update and say why in the changelog.")
        return 1
    if improved and not args.update:
        print(f"\nGATE PASSED with {len(improved)} improvement(s) not yet recorded. "
              "Run with --update in the same change so the new number is the one guarded.")
    else:
        print("\nGATE PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
