#!/usr/bin/env python
"""X6: hold dense neighbourhoods back from auto-matching, tested in Oyo.

X5's density features did not hold up in FCT: they settled more pairs but let
one different pair through on two seeds. Its control combiner (X4's features,
LGA agreement read through the alias table) passed. On every label read so far
(1,310 pairs, FCT included), five of that combiner's six out-of-fold false
merges are in Lagos, where a GRID3 point typically has 40 other HFR facilities
within 2 km.

So X6 does not ask the combiner to learn density. It gates it: a pair whose
GRID3 point has more than ``GATE_N`` other HFR facilities within ``RADIUS_KM``
(X5's count, the pair's own HFR record excluded) may be auto-rejected but never
auto-matched; it goes to review instead. ``GATE_N`` was fixed at 15 from those
development labels, before Oyo was built: it leaves 1-2 of the 6 out-of-fold
false merges and keeps out-of-fold coverage at about 0.71 (0.74-0.76 ungated).

Arms:

* ``gated``: the control combiner with the gate (the arm under test).
* ``control``: the same combiner without the gate (reported, not tested).
* ``match_everything``: the reference arm; it must fail.

The cross-encoder is retrained exactly as X0, X4 and X5 were, with Oyo held out
as well as every labelled state. The combiner is fitted on every label read so
far (X5's development labels plus the FCT pack as exported), thresholds from
5-fold out-of-fold predictions, and scored once on the Oyo pack
(``build_x6_pack.py``). Only aggregates are written.

    python data/scripts/x6_gate.py --train
    python data/scripts/x6_gate.py                      # dry run
    python data/scripts/x6_gate.py --test-labels <csv> --out <json>
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
_spec = importlib.util.spec_from_file_location("x5_density", HERE / "x5_density.py")
x5 = importlib.util.module_from_spec(_spec)
sys.modules["x5_density"] = x5
_spec.loader.exec_module(x5)
x3, x2, x1, x0, tr, fc = x5.x3, x5.x2, x5.x1, x5.x0, x5.tr, x5.fc

DATA, PACKS = x3.DATA, x3.PACKS
HELD_OUT = x5.HELD_OUT | {"oyo"}
MODELS = Path.home() / ".cache" / "arche" / "models" / "x6"
PREREG = DATA / "er_bench" / "benchmark_x6_gate_preregistration.json"
TEST_PACK = PACKS / "nigeria_facilities_oyo_x6_2026-11-22" / "adjudication_pack.csv"
KINDS = Path.home() / ".cache" / "arche" / "x6" / "kinds.json"     # kept out of the pack
DEV = {**x5.DEV,
       "x5": PACKS / "nigeria_facilities_fct_x5_2026-11-22" / x3.REVIEWED}
CORRECTIONS = x5.CORRECTIONS
GATE_N = 15
RADIUS_KM = x5.RADIUS_KM
MIN_DIFFERENT = 60


def examples() -> dict[str, list[tuple[str, str, int]]]:
    saved = fc.TEST_STATES
    fc.TEST_STATES = HELD_OUT
    try:
        return x0.examples()
    finally:
        fc.TEST_STATES = saved


def coordinates():
    grid3, hfr = x5.coordinates()
    with (DATA / "hfr_oyo.csv").open(encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            try:
                hfr[r["id"]] = (float(r["lat"]), float(r["lon"]))
            except ValueError:
                pass
    return grid3, hfr


def read_dev() -> list[dict]:
    saved = x5.DEV
    x5.DEV = DEV
    try:
        return x5.read_dev()
    finally:
        x5.DEV = saved


def crowd(rows, grid3, hfr, dens) -> np.ndarray:
    """Other HFR facilities within RADIUS_KM of the GRID3 point; -1 when it has none."""
    out = []
    for r in rows:
        gid, hid = r["grid3_id"].split(":", 1)[1], r["hfr_id"].split(":", 1)[1]
        a = grid3.get(gid)
        out.append(dens.around(a, {hid}) if a else -1)
    return np.array(out)


def gate(p: np.ndarray, n: np.ndarray, hi: float) -> np.ndarray:
    """Probabilities with auto-match removed where the neighbourhood is crowded."""
    return np.where(n > GATE_N, np.minimum(p, np.nextafter(hi, 0.0)), p)


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
        for k, p in {**DEV, "corrections": CORRECTIONS}.items():
            if tr._sha(p) != prereg["development_labels_sha256"][k]:
                raise SystemExit(f"development labels {k} changed since the preregistration")
        if tr._sha(TEST_PACK) != prereg["test"]["pack_sha256"]:
            raise SystemExit("the X6 pack changed since the preregistration")
        if tr._sha(x5.ALIASES) != prereg["lga_aliases_sha256"]:
            raise SystemExit("the LGA alias file changed since the preregistration")
        for seed in x0.SEEDS:
            if x0.weights_digest(MODELS / f"seed{seed}") != prereg["models"][f"seed{seed}"]:
                raise SystemExit(f"seed {seed} weights differ from the preregistered ones")
    elif args.test_labels:
        raise SystemExit("no preregistration; refusing to read test labels")

    dev = read_dev()
    y_dev = x1.labels(dev)
    folds = np.array([x3.fold_of(r) for r in dev])
    gxy, hxy = coordinates()
    dens = x5.Density()
    aliases = json.loads(x5.ALIASES.read_text(encoding="utf-8"))["aliases"]
    n_dev = crowd(dev, gxy, hxy, dens)
    print(f"development {len(dev)} ({int(y_dev.sum())} same, {int((y_dev == 0).sum())} different);"
          f" {float((n_dev > GATE_N).mean()):.3f} gated")
    test = x3.read(args.test_labels) if args.test_labels else []
    kinds = None
    if test:
        with TEST_PACK.open(encoding="utf-8") as fh:
            known = {r["decision_id"] for r in csv.DictReader(fh)}
        if {r["decision_id"] for r in test} - known:
            raise SystemExit("test labels hold decisions that are not in the X6 pack")
        if tr._sha(KINDS) != prereg["test"]["kinds_sha256"]:
            raise SystemExit("the pair kinds changed since the preregistration")
        kind_of = json.loads(KINDS.read_text(encoding="utf-8"))
        kinds = [kind_of[r["decision_id"]] for r in test]
    with TEST_PACK.open(encoding="utf-8") as fh:
        n_pack = crowd(list(csv.DictReader(fh)), gxy, hxy, dens)
    print(f"Oyo pack: {len(n_pack)} pairs, {float((n_pack > GATE_N).mean()):.3f} gated"
          f" (median crowd {float(np.median(n_pack)):.0f})")

    fitted: dict[int, Any] = {}
    for seed in x0.SEEDS:
        ce = x0.CrossEncoder(MODELS / f"seed{seed}", device)
        z_ce = ce.logits([(a, b) for a, b, _ in data["dev"]])
        ce_auc = round(tr.auc(z_ce, np.array([d[2] for d in data["dev"]])), 4)
        z_dev = ce.logits(x1.texts(dev))
        z_test = ce.logits(x1.texts(test)) if test else None
        del ce
        x = x5.features(dev, gxy, hxy, z_dev, aliases)
        w, lo, hi = x3.fit(x, y_dev, folds)
        oof = np.zeros(len(y_dev))
        for k in range(x3.FOLDS):
            a, b = folds != k, folds == k
            oof[b] = x0.predict(x0.fit_logistic(x[a], y_dev[a]), x[b])
        g = gate(oof, n_dev, hi)
        dev_fm = {"ungated": int(((oof >= hi) & (y_dev == 0)).sum()),
                  "gated": int(((g >= hi) & (y_dev == 0)).sum())}
        print(f"seed {seed}: weights {[round(float(v), 4) for v in w]} lo {lo:.4f} hi {hi:.4f};"
              f" out-of-fold false merges {dev_fm}", flush=True)
        fitted[seed] = {"w": w, "lo": lo, "hi": hi, "z_test": z_test,
                        "crosswalk_dev_auc": ce_auc, "dev_false_merges": dev_fm}
    if not test:
        print(f"crosswalk dev AUC: {[f['crosswalk_dev_auc'] for f in fitted.values()]}")
        print("dry run: no test labels read")
        return

    y = x1.labels(test)
    n_test = crowd(test, gxy, hxy, dens)
    band = np.array(kinds) == "review_band"
    result: dict[str, Any] = {"gated": {}, "control": {}}
    for seed, f in fitted.items():
        p = x0.predict(f["w"], x5.features(test, gxy, hxy, f["z_test"], aliases))
        for arm, q in (("gated", gate(p, n_test, f["hi"])), ("control", p)):
            res, _ = x3.score(f"{arm} seed {seed}", q, f["lo"], f["hi"], y, kinds)
            sub = x0.apply(q[band], y[band], f["lo"], f["hi"])
            sub.pop("_decided")
            res["review_band"] = sub
            res["weights"] = [round(float(v), 4) for v in f["w"]]
            result[arm][f"seed{seed}"] = res
    result["match_everything"], _ = x3.score("match everything", np.ones(len(y)), -1.0, 0.5,
                                             y, kinds)
    n_diff = int((y == 0).sum())
    informative = n_diff >= MIN_DIFFERENT
    verdict = {
        "informative": informative,
        "gated_pass": informative and all(s["pass"] for s in result["gated"].values()),
        "control_pass": informative and all(s["pass"] for s in result["control"].values()),
        "gated_review_band_pass": all(s["review_band"]["fewer_held"]
                                      and s["review_band"]["error_bound"]
                                      for s in result["gated"].values()),
        "match_everything_pass": informative and result["match_everything"]["pass"],
    }
    print(json.dumps(verdict, indent=2))
    out = {"schema": "arche.x6_gate.v1", "preregistration_sha256": tr._sha(PREREG),
           "test_labels_sha256": tr._sha(args.test_labels),
           "test": {"pairs": len(y), "same_entity": int(y.sum()), "different": n_diff,
                    "review_band_pairs": int(band.sum()),
                    "gated_share": round(float((n_test > GATE_N).mean()), 4)},
           "crosswalk_dev_auc": {f"seed{s}": f["crosswalk_dev_auc"] for s, f in fitted.items()},
           "development_false_merges": {f"seed{s}": f["dev_false_merges"]
                                        for s, f in fitted.items()},
           **result, "verdict": verdict, "seconds": round(time.time() - started, 1)}
    if args.out:
        Path(args.out).write_text(json.dumps(out, indent=2, sort_keys=True) + "\n",
                                  encoding="utf-8")
        print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
