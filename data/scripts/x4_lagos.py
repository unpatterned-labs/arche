#!/usr/bin/env python
"""X4: the pair decider on a state no part of it has seen (Lagos).

X0's cross-encoder was trained on the crosswalk of every state except Edo,
Kano and Ondo, so every other state's review band had been read in training.
X4 retrains it exactly as X0 did (same examples, seeds, schedule and Platt
calibration on X0's held-out development slice) with Lagos also held out, then
refits X3's control combiner (cross-encoder logit, log1p km, LGA agreement,
coordinates missing) on the 692 corrected development labels, with
out-of-fold thresholds. It is scored once on the X4 pack: a sample of the
engine's Lagos review band and two kinds of stress pair (``build_x4_pack.py``).
Only aggregates are written.

    python data/scripts/x4_lagos.py --train                  # the three seeds
    python data/scripts/x4_lagos.py                          # dry run: no test labels
    python data/scripts/x4_lagos.py --test-labels <csv> --out <json>
"""

from __future__ import annotations

import argparse
import contextlib
import csv
import importlib.util
import json
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("x3_level", HERE / "x3_level.py")
x3 = importlib.util.module_from_spec(_spec)
sys.modules["x3_level"] = x3
_spec.loader.exec_module(x3)
x2, x1, x0, tr, fc = x3.x2, x3.x1, x3.x0, x3.tr, x3.fc

HELD_OUT = frozenset({"edo", "kano", "ondo", "lagos"})
MODELS = Path.home() / ".cache" / "arche" / "models" / "x4"
PREREG = x3.DATA / "er_bench" / "benchmark_x4_lagos_preregistration.json"
TEST_PACK = x3.PACKS / "nigeria_facilities_lagos_x4_2026-11-22" / "adjudication_pack.csv"
KINDS = Path.home() / ".cache" / "arche" / "x4" / "kinds.json"     # kept out of the pack
MIN_DIFFERENT = 60


def examples() -> dict[str, list[tuple[str, str, int]]]:
    """X0's training examples, with Lagos held out as well."""
    saved = fc.TEST_STATES
    fc.TEST_STATES = HELD_OUT
    try:
        return x0.examples()
    finally:
        fc.TEST_STATES = saved


def coordinates():
    grid3, hfr = x1.coordinates()
    with (x3.DATA / "hfr_lagos.csv").open(encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            with contextlib.suppress(ValueError):
                hfr[r["id"]] = (float(r["lat"]), float(r["lon"]))
    return grid3, hfr


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--train", action="store_true")
    ap.add_argument("--test-labels", type=Path)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    started = time.time()
    device = "cuda" if x1._cuda() else "cpu"
    data = examples()
    for k, v in data.items():
        print(f"{k}: {len(v)} examples, {sum(d[2] for d in v)} positive", flush=True)
    if args.train:
        for seed in x0.SEEDS:
            x0.train(data["train"], seed, MODELS / f"seed{seed}", device)
        print(f"trained in {time.time() - started:.0f}s")
        return

    prereg = json.loads(PREREG.read_text(encoding="utf-8")) if PREREG.exists() else None
    if prereg is not None:
        if fc._digest(prereg["rule"]) != prereg["rule_sha256"]:
            raise SystemExit("rule differs from its recorded digest; refusing to run")
        for k, p in x3.DEV.items():
            if tr._sha(p) != prereg["development_labels_sha256"][k]:
                raise SystemExit(f"development labels {k} changed since the preregistration")
        if tr._sha(TEST_PACK) != prereg["test"]["pack_sha256"]:
            raise SystemExit("the X4 pack changed since the preregistration")
        for seed in x0.SEEDS:
            got = x0.weights_digest(MODELS / f"seed{seed}")
            if got != prereg["models"][f"seed{seed}"]:
                raise SystemExit(f"seed {seed} weights differ from the preregistered ones")
    elif args.test_labels:
        raise SystemExit("no preregistration; refusing to read test labels")

    dev = [r for p in x3.DEV.values() for r in x3.read(p)]
    y_dev = x1.labels(dev)
    folds = np.array([x3.fold_of(r) for r in dev])
    gxy, hxy = coordinates()
    test = x3.read(args.test_labels) if args.test_labels else []
    if test:
        with TEST_PACK.open(encoding="utf-8") as fh:
            known = {r["decision_id"] for r in csv.DictReader(fh)}
        if {r["decision_id"] for r in test} - known:
            raise SystemExit("test labels hold decisions that are not in the X4 pack")
        if tr._sha(KINDS) != prereg["test"]["kinds_sha256"]:
            raise SystemExit("the pair kinds changed since the preregistration")
        kind_of = json.loads(KINDS.read_text(encoding="utf-8"))
        kinds = [kind_of[r["decision_id"]] for r in test]
    dev_pairs = [(a, b) for a, b, _ in data["dev"]]
    y_ce = np.array([d[2] for d in data["dev"]])
    fitted: dict[int, Any] = {}
    for seed in x0.SEEDS:
        ce = x0.CrossEncoder(MODELS / f"seed{seed}", device)
        z_ce = ce.logits(dev_pairs)
        platt = x0.fit_logistic(z_ce[:, None], y_ce)
        ce_auc = round(tr.auc(z_ce, y_ce), 4)
        z_dev = ce.logits(x1.texts(dev))
        z_test = ce.logits(x1.texts(test)) if test else None
        del ce
        w, lo, hi = x3.fit(x1.features(dev, gxy, hxy, z_dev), y_dev, folds)
        fitted[seed] = {"w": w, "lo": lo, "hi": hi, "z_test": z_test,
                        "crosswalk_dev_auc": ce_auc,
                        "platt": [round(float(v), 5) for v in platt]}
        print(f"seed {seed}: crosswalk dev AUC {ce_auc}; combiner weights "
              f"{[round(float(v), 4) for v in w]} lo {lo:.4f} hi {hi:.4f}", flush=True)
    if not test:
        print("dry run: no test labels read")
        return

    y = x1.labels(test)
    kinds_arr = np.array(kinds)
    result: dict[str, Any] = {"x4": {}}
    band = kinds_arr == "review_band"
    for seed, f in fitted.items():
        p = x0.predict(f["w"], x1.features(test, gxy, hxy, f["z_test"]))
        res, _ = x3.score(f"x4 seed {seed}", p, f["lo"], f["hi"], y, kinds)
        sub = x0.apply(p[band], y[band], f["lo"], f["hi"])
        sub.pop("_decided")
        res["review_band"] = sub
        res["weights"] = [round(float(v), 4) for v in f["w"]]
        res["crosswalk_dev_auc"] = f["crosswalk_dev_auc"]
        result["x4"][f"seed{seed}"] = res
    result["match_everything"], _ = x3.score("match everything", np.ones(len(y)), -1.0, 0.5,
                                             y, kinds)
    n_diff = int((y == 0).sum())
    informative = n_diff >= MIN_DIFFERENT
    seeds = result["x4"].values()
    verdict = {
        "informative": informative,
        "x4_pass": informative and all(s["pass"] for s in seeds),
        "review_band_pass": all(s["review_band"]["fewer_held"] and s["review_band"]["error_bound"]
                                for s in seeds),
        "match_everything_pass": informative and result["match_everything"]["pass"],
    }
    print(json.dumps(verdict, indent=2))
    out = {"schema": "arche.x4_lagos.v1", "preregistration_sha256": tr._sha(PREREG),
           "test_labels_sha256": tr._sha(args.test_labels),
           "test": {"pairs": len(y), "same_entity": int(y.sum()), "different": n_diff,
                    "review_band_pairs": int(band.sum())},
           **result, "verdict": verdict, "seconds": round(time.time() - started, 1)}
    if args.out:
        Path(args.out).write_text(json.dumps(out, indent=2, sort_keys=True) + "\n",
                                  encoding="utf-8")
        print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
