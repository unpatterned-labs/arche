#!/usr/bin/env python
"""X11: does nigeria-facility-decider-v1 transfer, untouched, to English GP practices?

The engine's held pairs between CQC GP locations and ODS GP practices
(``build_uk_gp.py``, one run per English region) go to the Nigerian decider as
it ships: the same bundle, thresholds and alias table, with no UK training. Each
record is ``name | local authority`` with region and local authority from its
postcode and its point (CQC's own, ODS's postcode centroid).

Truth is the registries' own key: CQC's ``Location ODS Code``. A held pair is
**same** when the ODS record's code is the CQC location's ODS code; **different**
when the CQC location's code belongs to another ODS record in the region's
population; unscorable otherwise. This measures agreement with the registries'
key, not accuracy.

The rule (``benchmark_x11_uk_transfer_preregistration.json``) is the X-series
rule: coverage of the held pairs, errors among the decided, and false merges among
the different pairs, each with its bound. Only aggregates are written.

    ~/.cache/arche-scratch/e0/bin/python data/scripts/x11_uk_transfer.py \\
        --out data/er_bench/benchmark_x11_uk_transfer_result.json
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import math
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import numpy as np

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(REPO / "packages" / "arche-core" / "src"))
from arche.resolve import PairDecider  # noqa: E402

_spec = importlib.util.spec_from_file_location("build_uk_gp", HERE / "build_uk_gp.py")
uk = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(uk)

PREREG = REPO / "data" / "er_bench" / "benchmark_x11_uk_transfer_preregistration.json"
BUNDLE = Path.home() / ".cache" / "arche" / "models" / "nigeria-facility-decider-v1"
HELD_OUT = ("E12000002", "E12000005", "E12000008")   # every third region by code, from the 2nd


def sha(p: Path) -> str:
    return "sha256:" + hashlib.sha256(p.read_bytes()).hexdigest()


def wilson_upper(k: int, n: int, z: float = 1.96) -> float:
    if n == 0:
        return 1.0
    p = k / n
    return (p + z * z / (2 * n) + z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))) \
        / (1 + z * z / n)


def boot_lower(x: np.ndarray, n: int = 10_000, seed: int = 0) -> float:
    rng = np.random.default_rng(seed)
    means = x[rng.integers(0, len(x), size=(n, len(x)))].mean(axis=1)
    return float(np.quantile(means, 0.025))


def rule(outcome: list[str], y: np.ndarray) -> dict[str, Any]:
    match = np.array([o == "match" for o in outcome])
    reject = np.array([o == "reject" for o in outcome])
    decided = match | reject
    errors = int((match & (y == 0)).sum() + (reject & (y == 1)).sum())
    n = int(decided.sum())
    n_diff = int((y == 0).sum())
    fm = int((match & (y == 0)).sum())
    r: dict[str, Any] = {
        "pairs": len(y), "same": int((y == 1).sum()), "different": n_diff,
        "auto_match": int(match.sum()), "auto_reject": int(reject.sum()),
        "held": int((~decided).sum()),
        "coverage": round(float(decided.mean()), 4) if len(y) else None,
        "coverage_bootstrap95_lower": round(boot_lower(decided.astype(float)), 4)
        if len(y) else None,
        "errors": errors, "error_rate": round(errors / n, 4) if n else None,
        "error_wilson95_upper": round(wilson_upper(errors, n), 4),
        "false_merges": fm, "false_merge_rate": round(fm / n_diff, 4) if n_diff else None,
        "false_merge_wilson95_upper": round(wilson_upper(fm, n_diff), 4),
        "false_rejects": int((reject & (y == 1)).sum())}
    r["fewer_held"] = bool(r["coverage"] is not None and r["coverage"] >= 0.20
                           and r["coverage_bootstrap95_lower"] >= 0.10)
    r["error_bound"] = bool(n > 0 and errors / n <= 0.03 and r["error_wilson95_upper"] <= 0.10)
    r["false_merge_bound"] = bool(n_diff and fm / n_diff <= 0.02
                                  and r["false_merge_wilson95_upper"] <= 0.05)
    r["informative"] = n_diff >= 60
    r["pass"] = r["fewer_held"] and r["error_bound"] and r["false_merge_bound"] \
        and r["informative"]
    return r


def record(e: dict, side: str) -> dict:
    path = json.loads(e[f"{side}_admin_path"])
    lat, lon = e[f"{side}_lat"], e[f"{side}_lon"]
    return {"name": e[f"{side}_name"], "admin1": path.get("admin1", ""),
            "admin2": path.get("admin2", ""),
            "lat": float(lat) if lat else None, "lon": float(lon) if lon else None}


def best_per_cqc(edges: list[dict], column: str) -> dict[str, tuple[str, str]]:
    """compare_linkers' rule: best proposal per CQC location, match over held."""
    rank = {"match": 2, "review": 1}
    best: dict[str, tuple] = {}
    for e in edges:
        if e[column] not in rank:
            continue
        key = (rank[e[column]], float(e["_p"]) if column == "final" else float(e["score"] or 0))
        if e["cqc_id"] not in best or key > best[e["cqc_id"]][:2]:
            best[e["cqc_id"]] = (*key, e["ods_id"][4:])
    return {g: (h, "match" if k == 2 else "held") for g, (k, _, h) in best.items()}


def linker(edges: list[dict], twin_of: dict[str, str], column: str) -> dict[str, Any]:
    prop = best_per_cqc(edges, column)
    ev = [(g, h) for g, (h, k) in prop.items() if k == "match" and g in twin_of]
    correct = sum(twin_of[g] == h for g, h in ev)
    return {"matched": sum(k == "match" for _, k in prop.values()),
            "held": sum(k == "held" for _, k in prop.values()),
            "precision": round(correct / len(ev), 4) if ev else None,
            "recall": round(correct / len(twin_of), 4) if twin_of else None,
            "twins": len(twin_of)}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", type=Path)
    args = ap.parse_args()
    prereg = json.loads(PREREG.read_text(encoding="utf-8"))
    for name, digest in prereg["code"].items():
        if sha(HERE / name) != digest:
            raise SystemExit(f"{name} changed since the preregistration")
    for region, digest in prereg["edges"].items():
        if sha(uk.OUT / region / "candidate_edges.csv") != digest:
            raise SystemExit(f"{region} edges changed since the preregistration")
    started = time.time()
    decider = PairDecider.load(BUNDLE)
    if decider.pins != prereg["bundle_pins"]:
        raise SystemExit("decider bundle differs from the preregistered one")
    _, right, _ = uk.load()
    ods_region = {r["source_code"]: r["region"] for r in right}
    result: dict[str, Any] = {"schema": "arche.x11_uk_transfer.v1",
                              "preregistration_sha256": sha(PREREG),
                              "decider_pins": decider.pins, "regions": {}}
    pooled: dict[str, dict[str, list]] = {g: defaultdict(list) for g in ("all", "held_out")}
    linkers: dict[str, dict[str, Counter]] = {g: defaultdict(Counter)
                                              for g in ("all", "held_out")}
    for region in sorted(prereg["edges"]):
        with (uk.OUT / region / "candidate_edges.csv").open(encoding="utf-8") as fh:
            edges = list(csv.DictReader(fh))
        held = [e for e in edges if e["decision"] == "review"]
        decisions = decider.decide([(record(e, "cqc"), record(e, "ods")) for e in held])
        for e, d in zip(held, decisions, strict=True):
            e["_p"], e["_o"] = d.probability, d.outcome
        for e in edges:
            e["final"] = e["decision"] if e["decision"] == "match" else \
                ("match" if e.get("_o") == "match" else
                 "reject" if e.get("_o") == "reject" else "review")
            e.setdefault("_p", 1.0)
        outcome, y = [], []
        unscorable = Counter()
        for e in held:
            code = e["cqc_ods_code"]
            if e["ods_id"][4:] == code:
                label = 1
            elif code and ods_region.get(code) == region:
                label = 0
            else:
                unscorable[e["_o"]] += 1
                continue
            outcome.append(e["_o"])
            y.append(label)
        groups = ("all", "held_out") if region in HELD_OUT else ("all",)
        for g in groups:
            pooled[g]["outcome"] += outcome
            pooled[g]["y"] += y
            pooled[g]["unscorable"].append(unscorable)
        cqc_ids = {e["cqc_id"] for e in edges}
        twin_of = {e["cqc_id"]: e["cqc_ods_code"] for e in edges
                   if e["cqc_ods_code"] and ods_region.get(e["cqc_ods_code"]) == region}
        per = {"held_pairs": len(held), "scorable": len(y),
               "rule": rule(outcome, np.array(y)), "unscorable_outcomes": dict(unscorable),
               "engine": linker(edges, twin_of, "decision"),
               "engine_decider": linker(edges, twin_of, "final"),
               "cqc_surfaced": len(cqc_ids)}
        for arm in ("engine", "engine_decider"):
            for g in groups:
                c = linkers[g][arm]
                prop = best_per_cqc(edges, "decision" if arm == "engine" else "final")
                ev = [(q, h) for q, (h, k) in prop.items() if k == "match" and q in twin_of]
                c["evaluable"] += len(ev)
                c["correct"] += sum(twin_of[q] == h for q, h in ev)
                c["twins"] += len(twin_of)
                c["held"] += sum(k == "held" for _, k in prop.values())
        result["regions"][region] = per
        print(region, json.dumps({k: per["rule"][k] for k in
                                  ("pairs", "different", "auto_match", "auto_reject",
                                   "errors", "false_merges", "pass")}), flush=True)
    for g in ("all", "held_out"):
        y = np.array(pooled[g]["y"])
        res = rule(pooled[g]["outcome"], y)
        ref = rule(["match"] * len(y), y)
        unsc = sum(pooled[g]["unscorable"], Counter())
        result[g] = {"rule": res, "reference_match_everything_pass": ref["pass"],
                     "unscorable_outcomes": dict(unsc),
                     "linkers": {a: {**dict(c),
                                     "precision": round(c["correct"] / c["evaluable"], 4)
                                     if c["evaluable"] else None,
                                     "recall": round(c["correct"] / c["twins"], 4)
                                     if c["twins"] else None}
                                 for a, c in linkers[g].items()}}
        print(g, json.dumps(res), "reference pass:", ref["pass"], flush=True)
    result["verdict"] = {"transfer_pass": result["all"]["rule"]["pass"],
                         "held_out_pass": result["held_out"]["rule"]["pass"]}
    result["seconds"] = round(time.time() - started, 1)
    print(json.dumps(result["verdict"]), json.dumps(result["all"]["linkers"]))
    if args.out:
        args.out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
