#!/usr/bin/env python
"""X2: the X1 decider on a test with enough different pairs to mean something.

X1 passed on a pack of 264 same and 8 different, where auto-matching every
pair would also have passed. X2 scores the same fitted deciders, unchanged, on
the X1 labels together with the near-miss pack's: facilities in the same LGA,
with similar names, that the engine called different. The rule adds a
false-merge bound (different pairs auto-matched, over all different pairs) and
is void unless the test holds at least 60 different pairs.

The X1 combiner is refitted exactly as X1 fitted it and checked against X1's
recorded weights; X0's cross-encoder keeps its recorded crosswalk thresholds.
Only aggregates are written.

    python data/scripts/x2_near_miss.py --x1-labels <csv> --near-miss-labels <csv> \\
        --out data/er_bench/benchmark_x2_near_miss_result.json
"""

from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("x1_combiner", HERE / "x1_combiner.py")
x1 = importlib.util.module_from_spec(_spec)
sys.modules["x1_combiner"] = x1
_spec.loader.exec_module(x1)
x0, tr, fc = x1.x0, x1.tr, x1.fc

PREREG = x1.DATA / "er_bench" / "benchmark_x2_near_miss_preregistration.json"
X1_RESULT = x1.DATA / "er_bench" / "benchmark_x1_combiner_result.json"
NEAR_MISS_PACK = (x1.DATA / "review_packs" / "nigeria_facilities_nearmiss_2026-11-21"
                  / "adjudication_pack.csv")
MIN_DIFFERENT = 60


def read(path: Path, labelled: bool) -> list[dict]:
    with path.open(encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    if labelled:
        rows = [r for r in rows if r["review_outcome"] in ("same_entity", "different")]
    return sorted(rows, key=lambda r: (r["state"], r["decision_id"]))


def false_merges(p: np.ndarray, y: np.ndarray, hi: float) -> dict[str, Any]:
    n_diff = int((y == 0).sum())
    fm = int(((p >= hi) & (y == 0)).sum())
    return {"different_pairs": n_diff, "auto_matched": fm,
            "rate": round(fm / n_diff, 4) if n_diff else None,
            "wilson95_upper": round(x0.wilson_upper(fm, n_diff), 4)}


def score(name: str, p: np.ndarray, lo: float, hi: float, y: np.ndarray, part: np.ndarray):
    res = x0.apply(p, y, lo, hi)
    res.pop("_decided")
    res["false_merges"] = false_merges(p, y, hi)
    fmr = res["false_merges"]
    res["false_merge_bound"] = (fmr["rate"] is not None and fmr["rate"] <= 0.02
                                and fmr["wilson95_upper"] <= 0.05)
    res["pass"] = res["fewer_held"] and res["error_bound"] and res["false_merge_bound"]
    res["by_part"] = {}
    for label in ("x1", "near_miss"):
        ix = part == label
        sub = x0.apply(p[ix], y[ix], lo, hi)
        sub.pop("_decided")
        res["by_part"][label] = {k: sub[k] for k in ("coverage", "auto_match", "auto_reject",
                                                     "held", "errors")}
        res["by_part"][label]["false_merges"] = false_merges(p[ix], y[ix], hi)
    res["review_auc"] = round(tr.auc(p, y), 4) if 0 < y.sum() < len(y) else None
    print(name, json.dumps(res), flush=True)
    return res


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--x1-labels", type=Path)
    ap.add_argument("--near-miss-labels", type=Path)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    prereg = json.loads(PREREG.read_text(encoding="utf-8"))
    if fc._digest(prereg["rule"]) != prereg["rule_sha256"]:
        raise SystemExit("rule differs from its recorded digest; refusing to run")
    if tr._sha(NEAR_MISS_PACK) != prereg["test"]["near_miss_pack_sha256"]:
        raise SystemExit("the near-miss pack changed since the preregistration")
    if tr._sha(x1.DEV_LABELS) != prereg["development_labels_sha256"]:
        raise SystemExit("development labels changed since the preregistration")
    x1r = json.loads(X1_RESULT.read_text(encoding="utf-8"))
    x0r = json.loads(x1.X0_RESULT.read_text(encoding="utf-8"))
    started = time.time()
    labelled = bool(args.x1_labels and args.near_miss_labels)
    allowed = {prereg["test"]["x1_labels_sha256"]}
    allowed |= {a["x1_labels_sha256"] for a in prereg.get("amendments", [])}
    if labelled and tr._sha(args.x1_labels) not in allowed:
        raise SystemExit("X1 labels are neither X1's nor an amended file")
    if labelled:
        named = {a.get("near_miss_labels_sha256") for a in prereg.get("amendments", [])}
        if named - {None} and tr._sha(args.near_miss_labels) not in named:
            raise SystemExit("near-miss labels differ from the file named in the amendment")
    a = read(args.x1_labels, True) if labelled else []
    b = read(args.near_miss_labels if labelled else NEAR_MISS_PACK, labelled)
    if labelled:
        known = {r["decision_id"] for r in read(NEAR_MISS_PACK, False)}
        if {r["decision_id"] for r in b} - known:
            raise SystemExit("near-miss labels hold decisions that are not in the pack")
    test = a + b
    part = np.array(["x1"] * len(a) + ["near_miss"] * len(b))
    grid3, hfr = x1.coordinates()
    dev = x1.load(x1.DEV_LABELS, labelled=True)
    y_dev = x1.labels(dev)
    print(f"development {len(dev)}; test {len(a)} X1 + {len(b)} near-miss")

    arms: dict[str, Any] = {}
    for seed in x0.SEEDS:
        ce = x0.CrossEncoder(x0.MODELS / f"seed{seed}", "cuda" if x1._cuda() else "cpu")
        z_dev, z = ce.logits(x1.texts(dev)), ce.logits(x1.texts(test))
        w = x0.fit_logistic(x1.features(dev, grid3, hfr, z_dev), y_dev)
        if [round(float(v), 4) for v in w] != x1r["x1"][f"seed{seed}"]["weights"]:
            raise SystemExit(f"seed {seed}: refit does not reproduce X1's weights")
        lo, hi = x0.thresholds(x0.predict(w, x1.features(dev, grid3, hfr, z_dev)), y_dev)
        pa, pb = x0r["cross_encoder"][f"seed{seed}"]["platt"]
        arms[seed] = {"x1": (x0.predict(w, x1.features(test, grid3, hfr, z)), lo, hi),
                      "x0": (1 / (1 + np.exp(-(pa * z + pb))),
                             x0r["cross_encoder"][f"seed{seed}"]["thresholds"]["lo"],
                             x0r["cross_encoder"][f"seed{seed}"]["thresholds"]["hi"])}
        print(f"seed {seed}: X1 weights reproduced; lo {lo:.4f} hi {hi:.4f}")
        del ce
    if not labelled:
        print("dry run: deciders reproduced; no test labels read")
        return

    y = x1.labels(test)
    n_diff = int((y == 0).sum())
    result: dict[str, Any] = {"x1_combiner": {}, "x0_cross_encoder": {}}
    for seed, arm in arms.items():
        result["x1_combiner"][f"seed{seed}"] = score(f"X1 seed {seed}", *arm["x1"], y, part)
        result["x0_cross_encoder"][f"seed{seed}"] = score(f"X0 seed {seed}", *arm["x0"], y,
                                                          part)
    everything = np.ones(len(y))
    result["match_everything"] = score("match everything", everything, -1.0, 0.5, y, part)
    informative = n_diff >= MIN_DIFFERENT
    verdict = {"informative": informative,
               "x1_pass": informative and all(s["pass"] for s in
                                              result["x1_combiner"].values()),
               "x0_pass": informative and all(s["pass"] for s in
                                              result["x0_cross_encoder"].values()),
               "match_everything_pass": informative and result["match_everything"]["pass"]}
    print(json.dumps(verdict, indent=2))
    out = {"schema": "arche.x2_near_miss.v1", "preregistration_sha256": tr._sha(PREREG),
           "labels_sha256": {"x1": tr._sha(args.x1_labels),
                             "near_miss": tr._sha(args.near_miss_labels)},
           "test": {"pairs": len(y), "same_entity": int(y.sum()), "different": n_diff,
                    "x1_part": len(a), "near_miss_part": len(b)},
           **result, "verdict": verdict, "seconds": round(time.time() - started, 1)}
    if args.out:
        Path(args.out).write_text(json.dumps(out, indent=2, sort_keys=True) + "\n",
                                  encoding="utf-8")
        print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
