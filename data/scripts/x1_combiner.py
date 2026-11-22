#!/usr/bin/env python
"""X1: the cross-encoder plus distance and district, on fresh review-band labels.

X0's cross-encoder decided 60% of the first review band and failed its error
bound by one error on two seeds. Two of its errors were same-name facilities in
different LGAs, 26 and 147 km apart: it reads names and LGAs, never distance.

X1 adds them. A logistic over three features, the cross-encoder's logit, the
log of the distance in km, and whether the two LGAs agree, is fitted on the
FIRST review band's 180 labels (already spent as a test, so used here only for
development), with thresholds set there by the same 1% error-rate rule as X0.
It is then scored once on the X1 pack's labels, which no design decision saw.

Distance is computed from source coordinates (GRID3 v2 latitude and longitude;
the HFR state file's lat and lon) the same way for both packs. It is not
learned from the GRID3/HFR crosswalk, where 98.3% of linked pairs are 0 km
apart because HFR copied GRID3's coordinates.

On the same fresh labels, X0 is replicated as it was (its crosswalk thresholds,
unchanged), as is its two-cosine logistic baseline. Only aggregates are written.

    python data/scripts/x1_combiner.py --labels <x1 reviewed csv> \\
        --out data/er_bench/benchmark_x1_combiner_result.json
"""

from __future__ import annotations

import argparse
import contextlib
import csv
import importlib.util
import json
import math
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("x0_cross_encoder", HERE / "x0_cross_encoder.py")
x0 = importlib.util.module_from_spec(_spec)
sys.modules["x0_cross_encoder"] = x0
_spec.loader.exec_module(x0)
tr, fc = x0.tr, x0.fc

DATA = tr.DATA
PREREG = DATA / "er_bench" / "benchmark_x1_combiner_preregistration.json"
X0_RESULT = DATA / "er_bench" / "benchmark_x0_cross_encoder_result.json"
DEV_LABELS = (DATA / "review_packs" / "nigeria_facilities_2026-08-19"
              / "adjudication_pack_reviewed.csv")
TEST_PACK = DATA / "review_packs" / "nigeria_facilities_x1_2026-11-21" / "adjudication_pack.csv"


def haversine_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    la1, lo1, la2, lo2 = map(math.radians, (*a, *b))
    h = (math.sin((la2 - la1) / 2) ** 2
         + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2)
    return 12742.0 * math.asin(math.sqrt(h))


def coordinates() -> tuple[dict[str, tuple[float, float]], dict[str, tuple[float, float]]]:
    grid3, hfr = {}, {}
    with (DATA / "GRID3_NGA_health_facilities_v2.csv").open(encoding="utf-8-sig") as fh:
        for r in csv.DictReader(fh):
            with contextlib.suppress(ValueError):
                grid3[r["globalid"]] = (float(r["latitude"]), float(r["longitude"]))
    for state in ("edo", "kano", "ondo"):
        with (DATA / f"hfr_{state}.csv").open(encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                with contextlib.suppress(ValueError):
                    hfr[r["id"]] = (float(r["lat"]), float(r["lon"]))
    return grid3, hfr


def load(path: Path, labelled: bool) -> list[dict]:
    with path.open(encoding="utf-8") as fh:
        rows = [r for r in csv.DictReader(fh) if r["decision"] == "review"]
    if labelled:
        rows = [r for r in rows if r["review_outcome"] in ("same_entity", "different")]
    return sorted(rows, key=lambda r: (r["state"], r["decision_id"]))


def features(rows, grid3, hfr, z: np.ndarray) -> np.ndarray:
    dist, agree, missing = [], [], []
    for r in rows:
        a = grid3.get(r["grid3_id"].split(":", 1)[1])
        b = hfr.get(r["hfr_id"].split(":", 1)[1])
        d = haversine_km(a, b) if a and b else 0.0
        dist.append(math.log1p(d))
        missing.append(0.0 if a and b else 1.0)
        la = fc.fold(json.loads(r["grid3_admin_path"]).get("admin2", ""))
        lb = fc.fold(json.loads(r["hfr_admin_path"]).get("admin2", ""))
        agree.append(1.0 if la and la == lb else 0.0)
    return np.c_[z, dist, agree, missing]


def texts(rows) -> list[tuple[str, str]]:
    return [(x0.side(r["grid3_name"], json.loads(r["grid3_admin_path"]).get("admin2", "")),
             x0.side(r["hfr_name"], json.loads(r["hfr_admin_path"]).get("admin2", "")))
            for r in rows]


def labels(rows) -> np.ndarray:
    return np.array([r["review_outcome"] == "same_entity" for r in rows], dtype=int)


def by_state(rows, decided: np.ndarray, y: np.ndarray, p: np.ndarray, lo: float, hi: float):
    out = {}
    for state in sorted({r["state"] for r in rows}):
        ix = np.array([r["state"] == state for r in rows])
        m, j = p[ix] >= hi, p[ix] <= lo
        out[state] = {"pairs": int(ix.sum()), "decided": int(decided[ix].sum()),
                      "errors": int((m & (y[ix] == 0)).sum() + (j & (y[ix] == 1)).sum())}
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--labels", type=Path, required=False,
                    help="the X1 pack's reviewed CSV; omit for a dry run that reads no labels")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    prereg = json.loads(PREREG.read_text(encoding="utf-8"))
    if fc._digest(prereg["rule"]) != prereg["rule_sha256"]:
        raise SystemExit("rule differs from its recorded digest; refusing to run")
    if tr._sha(DEV_LABELS) != prereg["development"]["labels_sha256"]:
        raise SystemExit("development labels changed since the preregistration")
    if tr._sha(TEST_PACK) != prereg["test"]["pack_sha256"]:
        raise SystemExit("the X1 pack changed since the preregistration")
    x0r = json.loads(X0_RESULT.read_text(encoding="utf-8"))
    started = time.time()
    grid3, hfr = coordinates()
    dev = load(DEV_LABELS, labelled=True)
    y_dev = labels(dev)
    test = load(args.labels, labelled=True) if args.labels else load(TEST_PACK, labelled=False)
    if args.labels:
        ids = {r["decision_id"] for r in load(TEST_PACK, labelled=False)}
        if {r["decision_id"] for r in test} - ids:
            raise SystemExit("labels file holds decisions that are not in the X1 pack")
    print(f"development {len(dev)} ({int(y_dev.sum())} same); test {len(test)}")

    fitted: dict[int, Any] = {}
    for seed in x0.SEEDS:
        ce = x0.CrossEncoder(x0.MODELS / f"seed{seed}", "cuda" if _cuda() else "cpu")
        if ce.weights != x0r["cross_encoder"][f"seed{seed}"]["weights"]:
            raise SystemExit(f"seed {seed} weights are not the ones X0 scored")
        z_dev, z_test = ce.logits(texts(dev)), ce.logits(texts(test))
        x_dev, x_test = features(dev, grid3, hfr, z_dev), features(test, grid3, hfr, z_test)
        w = x0.fit_logistic(x_dev, y_dev)
        lo, hi = x0.thresholds(x0.predict(w, x_dev), y_dev)
        a, b = x0r["cross_encoder"][f"seed{seed}"]["platt"]
        fitted[seed] = {"w": w, "lo": lo, "hi": hi, "p_test": x0.predict(w, x_test),
                        "x0_p_test": 1 / (1 + np.exp(-(a * z_test + b))),
                        "x0_thresholds": x0r["cross_encoder"][f"seed{seed}"]["thresholds"]}
        print(f"seed {seed}: weights {np.round(w, 3).tolist()} lo {lo:.4f} hi {hi:.4f}")
        del ce

    if not args.labels:
        print("dry run: model fitted on development labels only; no test labels read")
        return

    y = labels(test)
    result: dict[str, Any] = {"x1": {}, "x0_replication": {}}
    for seed, f in fitted.items():
        res = x0.apply(f["p_test"], y, f["lo"], f["hi"])
        decided = res.pop("_decided")
        res["by_state"] = by_state(test, decided, y, f["p_test"], f["lo"], f["hi"])
        res["weights"] = [round(float(v), 4) for v in f["w"]]
        res["review_auc"] = round(tr.auc(f["p_test"], y), 4)
        result["x1"][f"seed{seed}"] = res
        t = f["x0_thresholds"]
        rep = x0.apply(f["x0_p_test"], y, t["lo"], t["hi"])
        rep.pop("_decided")
        rep["review_auc"] = round(tr.auc(f["x0_p_test"], y), 4)
        result["x0_replication"][f"seed{seed}"] = rep
        print(f"seed {seed}: X1 {json.dumps(res)}\n         X0 {json.dumps(rep)}")

    # The two-cosine baseline, as X0 fitted it, with X0's thresholds.
    base = x0r["logistic_baseline"]
    enc = x0.TextEncoder(str(x0.E0C_ENCODER), prefix=tr.PREFIX)
    a_names = [r["grid3_name"] for r in test]
    b_names = [r["hfr_name"] for r in test]
    feats = np.c_[tr.TfidfArm().cosine(a_names, b_names),
                  np.sum(enc.encode(a_names) * enc.encode(b_names), axis=1)]
    p_base = x0.predict(np.array(base["weights"]), feats)
    rb = x0.apply(p_base, y, base["thresholds"]["lo"], base["thresholds"]["hi"])
    rb.pop("_decided")
    rb["review_auc"] = round(tr.auc(p_base, y), 4)
    result["baseline_replication"] = rb
    print("baseline", json.dumps(rb))

    verdict = {
        "x1_pass": all(s["fewer_held"] and s["error_bound"] for s in result["x1"].values()),
        "x0_replication_pass": all(s["fewer_held"] and s["error_bound"]
                                   for s in result["x0_replication"].values()),
        "baseline_replication_pass": rb["fewer_held"] and rb["error_bound"]}
    print(json.dumps(verdict, indent=2))
    out = {"schema": "arche.x1_combiner.v1", "preregistration_sha256": tr._sha(PREREG),
           "labels_sha256": tr._sha(args.labels),
           "test": {"pairs": len(y), "same_entity": int(y.sum()),
                    "by_state": {s: sum(r["state"] == s for r in test)
                                 for s in sorted({r["state"] for r in test})}},
           "gate_alone": {"coverage": 0.0, "held": len(y)},
           **result, "verdict": verdict, "seconds": round(time.time() - started, 1)}
    if args.out:
        Path(args.out).write_text(json.dumps(out, indent=2, sort_keys=True) + "\n",
                                  encoding="utf-8")
        print(f"wrote {args.out}")


def _cuda() -> bool:
    import torch

    return torch.cuda.is_available()


if __name__ == "__main__":
    main()
