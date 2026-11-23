#!/usr/bin/env python
"""X8: name uniqueness within an LGA, and a decider that knows when location is missing.

Two things are tested.

1. **Uniqueness.** In Nigeria a facility name is rarely used twice in one LGA:
   1.6% of GRID3 records and 1.7% of HFR records share an exact name with
   another record in their LGA. So the same name in the same LGA is strong
   evidence of one facility even when the two points disagree. For each pair,
   ``n`` counts the other facilities in the GRID3 record's state and LGA, in
   GRID3 and the HFR together (LGA names read through the alias table), whose
   name *core* equals the GRID3 name's core. The core is the folded name with
   facility-type words removed (``TYPE_WORDS``); numbers and other words stay,
   so "Zango 1" and "Zango 2" differ. Ids are used only to avoid counting the
   GRID3 record, its own HFR twin and the pair's HFR record. Two features:
   ``log1p(n)`` and ``core_equal * [n == 0] * same_lga`` (the two cores are
   equal, both records are in the same LGA, and no other facility there shares
   the core). An empty core (a name made only of
   type words) counts as n = 99.

2. **Missing location.** Until now a missing coordinate was scored as 0 km, and
   the coordinates-missing flag's weight was 0.0 because no labelled pair lacked
   coordinates. X8 trains on every labelled pair twice: as it is, and with both
   points removed (distance 0, flag 1). Each copy keeps its pair's fold.
   Thresholds are set separately for located pairs (out-of-fold predictions on
   the originals) and for pairs without location (out-of-fold on the copies).

Arms, on X8's cross-encoder (Anambra held out as well as every labelled state):

* ``control``: X7's ungated decider (no copies, no uniqueness; located
  thresholds used everywhere, which is how it behaves today).
* ``augmented``: control features, trained with the location-free copies.
* ``x8``: augmented plus the two uniqueness features. The arm under test.

The test pack (``build_x8_pack.py``) is scored twice: ``located`` as labelled,
and ``hidden``, the same pairs and labels with both points removed. Only
aggregates are written.

    python data/scripts/x8_uniqueness.py --train
    python data/scripts/x8_uniqueness.py                      # dry run
    python data/scripts/x8_uniqueness.py --test-labels <csv> --out <json>
"""

from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import math
import re
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("x7_lagos_gate", HERE / "x7_lagos_gate.py")
x7 = importlib.util.module_from_spec(_spec)
sys.modules["x7_lagos_gate"] = x7
_spec.loader.exec_module(x7)
x6 = x7.x6
x5, x3, x2, x1, x0, tr, fc = x6.x5, x6.x3, x6.x2, x6.x1, x6.x0, x6.tr, x6.fc

DATA, PACKS = x3.DATA, x3.PACKS
HELD_OUT = x6.HELD_OUT | {"anambra"}
MODELS = Path.home() / ".cache" / "arche" / "models" / "x8"
PREREG = DATA / "er_bench" / "benchmark_x8_uniqueness_preregistration.json"
TEST_PACK = PACKS / "nigeria_facilities_anambra_x8_2026-11-23" / "adjudication_pack.csv"
KINDS = Path.home() / ".cache" / "arche" / "x8" / "kinds.json"     # kept out of the pack
DEV = {**x6.DEV,
       "x7": PACKS / "nigeria_facilities_lagos_x7_2026-11-23" / x3.REVIEWED}
CORRECTIONS = x5.CORRECTIONS
RESTORE = x7.RESTORE
FAR_DUPLICATES = PACKS / "nigeria_facilities_far_duplicates_2026-11-23" / "corrections.json"
MIN_DIFFERENT = 60
EMPTY_CORE_N = 99
HIDDEN_MIN_COVERAGE = 0.10
TYPE_WORDS = frozenset("""
    primary health healthcare care center centre centers clinic clinics post basic
    comprehensive hospital hosp maternity home nursing medical dispensary phc bhc chc
    mch and of the unit facility
""".split())


def examples() -> dict[str, list[tuple[str, str, int]]]:
    saved = fc.TEST_STATES
    fc.TEST_STATES = HELD_OUT
    try:
        return x0.examples()
    finally:
        fc.TEST_STATES = saved


def coordinates():
    grid3, hfr = x6.coordinates()
    for state in ("anambra",):
        with (DATA / f"hfr_{state}.csv").open(encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                try:
                    hfr[r["id"]] = (float(r["lat"]), float(r["lon"]))
                except ValueError:
                    pass
    return grid3, hfr


def read_dev() -> list[dict]:
    """X7's development labels plus X7's Lagos pack, with the far-duplicate recheck applied."""
    saved = x6.DEV
    x6.DEV = DEV
    try:
        rows = x7.read_dev()          # X4 corrections and the Oyo restore, as X7 read them
    finally:
        x6.DEV = saved
    fixes = json.loads(FAR_DUPLICATES.read_text(encoding="utf-8"))["outcomes"]
    out = []
    for r in rows:
        r["review_outcome"] = fixes.get(r["decision_id"], r["review_outcome"])
        if r["review_outcome"] in ("same_entity", "different"):
            out.append(r)
    return out


def _fold(v: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", (v or "").casefold()).split())


def core(name: str) -> str:
    return " ".join(t for t in _fold(name).split() if t not in TYPE_WORDS)


class Uniqueness:
    """Facilities per (state, LGA, name core), from GRID3 and the HFR together."""

    def __init__(self, aliases: dict[str, str]) -> None:
        self.ids: dict[tuple[str, str, str], set[str]] = defaultdict(set)
        with (DATA / "GRID3_NGA_health_facilities_v2.csv").open(encoding="utf-8-sig") as fh:
            for r in csv.DictReader(fh):
                c = core(r["facility_name"])
                if c:
                    self.ids[(_fold(r["state"]), _fold(r["lga"]), c)].add(r["globalid"])
        with x3.HFR_NATIONAL.open(encoding="utf-8") as fh:
            for f in json.load(fh)["features"]:
                p = f["properties"]
                s5, l5 = x5._fold(p.get("state_name")), x5._fold(p.get("lga_name"))
                state, lga = _fold(s5), _fold(aliases.get(f"{s5}|{l5}", l5))
                c = core(p.get("name") or p.get("alternate_name") or "")
                if c:
                    self.ids[(state, lga, c)].add(p["global_id"])

    def others(self, state: str, lga: str, name: str, exclude: set[str]) -> int:
        c = core(name)
        if not c:
            return EMPTY_CORE_N
        return len(self.ids.get((_fold(state), _fold(lga), c), set()) - exclude)


def uniqueness_features(rows, uniq: Uniqueness, aliases: dict[str, str]) -> np.ndarray:
    agree = x5.lga_agree(rows, aliases)
    out = []
    for r, same_lga in zip(rows, agree, strict=True):
        gid, hid = r["grid3_id"].split(":", 1)[1], r["hfr_id"].split(":", 1)[1]
        path = json.loads(r["grid3_admin_path"])
        state = path.get("admin1") or r.get("state", "")
        n = uniq.others(state, path.get("admin2", ""), r["grid3_name"], {gid, hid})
        cg, ch = core(r["grid3_name"]), core(r["hfr_name"])
        out.append((math.log1p(n), 1.0 if cg and cg == ch and n == 0 and same_lga else 0.0))
    return np.array(out)


def hide(x: np.ndarray) -> np.ndarray:
    """The same pairs with both points removed: distance 0, coordinates-missing 1."""
    h = x.copy()
    h[:, 1] = 0.0
    h[:, 3] = 1.0
    return h


def fit_arm(x: np.ndarray, y: np.ndarray, folds: np.ndarray, augment: bool):
    """Weights, located thresholds and (when augmented) no-location thresholds."""
    xa, ya, fa = (np.r_[x, hide(x)], np.r_[y, y], np.r_[folds, folds]) if augment else (x, y, folds)
    oof = np.zeros(len(ya))
    for k in range(x3.FOLDS):
        a, b = fa != k, fa == k
        oof[b] = x0.predict(x0.fit_logistic(xa[a], ya[a]), xa[b])
    n = len(y)
    located = x0.thresholds(oof[:n], y)
    hidden = x0.thresholds(oof[n:], y) if augment else located
    return x0.fit_logistic(xa, ya), located, hidden, oof


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
        files = {**DEV, "corrections": CORRECTIONS, "restore": RESTORE,
                 "far_duplicates": FAR_DUPLICATES}
        for k, p in files.items():
            if tr._sha(p) != prereg["development_labels_sha256"][k]:
                raise SystemExit(f"development labels {k} changed since the preregistration")
        if tr._sha(TEST_PACK) != prereg["test"]["pack_sha256"]:
            raise SystemExit("the X8 pack changed since the preregistration")
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
    aliases = json.loads(x5.ALIASES.read_text(encoding="utf-8"))["aliases"]
    uniq = Uniqueness(aliases)
    u_dev = uniqueness_features(dev, uniq, aliases)
    print(f"development {len(dev)} ({int(y_dev.sum())} same, {int((y_dev == 0).sum())} different);"
          f" unique-core share {float((u_dev[:, 0] == 0).mean()):.3f}")
    test = x3.read(args.test_labels) if args.test_labels else []
    kinds = None
    if test:
        with TEST_PACK.open(encoding="utf-8") as fh:
            known = {r["decision_id"] for r in csv.DictReader(fh)}
        if {r["decision_id"] for r in test} - known:
            raise SystemExit("test labels hold decisions that are not in the X8 pack")
        if tr._sha(KINDS) != prereg["test"]["kinds_sha256"]:
            raise SystemExit("the pair kinds changed since the preregistration")
        kind_of = json.loads(KINDS.read_text(encoding="utf-8"))
        kinds = [kind_of[r["decision_id"]] for r in test]
    u_test = uniqueness_features(test, uniq, aliases) if test else None

    fitted: dict[int, Any] = {}
    for seed in x0.SEEDS:
        ce = x0.CrossEncoder(MODELS / f"seed{seed}", device)
        z_ce = ce.logits([(a, b) for a, b, _ in data["dev"]])
        ce_auc = round(tr.auc(z_ce, np.array([d[2] for d in data["dev"]])), 4)
        z_dev = ce.logits(x1.texts(dev))
        z_test = ce.logits(x1.texts(test)) if test else None
        del ce
        base = x5.features(dev, gxy, hxy, z_dev, aliases)
        arms = {"control": fit_arm(base, y_dev, folds, augment=False),
                "augmented": fit_arm(base, y_dev, folds, augment=True),
                "x8": fit_arm(np.c_[base, u_dev], y_dev, folds, augment=True)}
        dev_fm = {}
        for arm, (w, (lo, hi), (hlo, hhi), oof) in arms.items():
            n = len(y_dev)
            dev_fm[arm] = {"located": int(((oof[:n] >= hi) & (y_dev == 0)).sum()),
                           "hidden": int((((oof[n:] if len(oof) > n else
                                            x0.predict(w, hide(base if arm != "x8" else
                                                               np.c_[base, u_dev])))
                                           >= hhi) & (y_dev == 0)).sum())}
            print(f"seed {seed} {arm}: weights {[round(float(v), 4) for v in w]}"
                  f" located {lo:.4f}/{hi:.4f} hidden {hlo:.4f}/{hhi:.4f}", flush=True)
        print(f"seed {seed} development false merges (out of fold): {dev_fm}", flush=True)
        fitted[seed] = {"arms": arms, "z_test": z_test, "crosswalk_dev_auc": ce_auc,
                        "dev_false_merges": dev_fm}
    if not test:
        print(f"crosswalk dev AUC: {[f['crosswalk_dev_auc'] for f in fitted.values()]}")
        print("dry run: no test labels read")
        return

    y = x1.labels(test)
    band = np.array(kinds) == "review_band"
    result: dict[str, Any] = {}
    for seed, f in fitted.items():
        base = x5.features(test, gxy, hxy, f["z_test"], aliases)
        for arm, (w, (lo, hi), (hlo, hhi), _) in f["arms"].items():
            x = np.c_[base, u_test] if arm == "x8" else base
            for view, xv, a, b in (("located", x, lo, hi), ("hidden", hide(x), hlo, hhi)):
                p = x0.predict(w, xv)
                res, _ = x3.score(f"{arm} {view} seed {seed}", p, a, b, y, kinds)
                sub = x0.apply(p[band], y[band], a, b)
                sub.pop("_decided")
                res["review_band"] = sub
                res["weights"] = [round(float(v), 4) for v in w]
                result.setdefault(f"{arm}_{view}", {})[f"seed{seed}"] = res
    result["match_everything"], _ = x3.score("match everything", np.ones(len(y)), -1.0, 0.5,
                                             y, kinds)
    n_diff = int((y == 0).sum())
    informative = n_diff >= MIN_DIFFERENT

    def hidden_ok(s):
        return s["error_bound"] and s["false_merge_bound"] and s["coverage"] >= HIDDEN_MIN_COVERAGE

    fm = {k: [s["false_merges"]["auto_matched"] for s in v.values()]
          for k, v in result.items() if k != "match_everything"}
    cov = {k: [s["coverage"] for s in v.values()]
           for k, v in result.items() if k != "match_everything"}
    verdict = {
        "informative": informative,
        "x8_located_pass": informative and all(s["pass"] for s in result["x8_located"].values()),
        "x8_hidden_pass": informative and all(hidden_ok(s) for s in result["x8_hidden"].values()),
        "control_located_pass": informative and all(s["pass"]
                                                    for s in result["control_located"].values()),
        "control_hidden_pass": informative and all(hidden_ok(s)
                                                   for s in result["control_hidden"].values()),
        "augmented_hidden_pass": informative and all(hidden_ok(s)
                                                     for s in result["augmented_hidden"].values()),
        "uniqueness_helps_hidden": all(c8 > ca and f8 <= fa for c8, ca, f8, fa in zip(
            cov["x8_hidden"], cov["augmented_hidden"], fm["x8_hidden"], fm["augmented_hidden"],
            strict=True)),
        "match_everything_pass": informative and result["match_everything"]["pass"],
    }
    verdict["x8_pass"] = verdict["x8_located_pass"] and verdict["x8_hidden_pass"]
    print(json.dumps(verdict, indent=2))
    out = {"schema": "arche.x8_uniqueness.v1", "preregistration_sha256": tr._sha(PREREG),
           "test_labels_sha256": tr._sha(args.test_labels),
           "test": {"pairs": len(y), "same_entity": int(y.sum()), "different": n_diff,
                    "review_band_pairs": int(band.sum()),
                    "unique_core_share": round(float((u_test[:, 0] == 0).mean()), 4)},
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
