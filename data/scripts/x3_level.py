#!/usr/bin/env python
"""X3: does the registries' facility level help the pair decider?

X1's combiner reads the cross-encoder logit, the distance and LGA agreement.
X3 refits it on every label read so far, corrected by the recheck (the
2026-08-19 and X1 packs' corrected copies and the near-miss pack), in two arms
that differ by one feature:

* ``control``: X1's four features, refitted.
* ``level``: the same plus a facility-level weight of evidence. GRID3 v2
  ``facility_level`` and the HFR ``type`` are each Primary, Secondary or
  Tertiary; the gap between them (0, 1 or 2) is scored as log(m/u), where m is
  how often that gap occurs between twins sharing a source id, and u how often
  it occurs between a GRID3 facility and a random other HFR facility in its
  LGA. Both rates come from the 34 states other than Edo, Kano and Ondo, never
  from review labels. An unknown level scores 0.

Thresholds are set from out-of-fold predictions on the development labels (5
folds), so they are not tuned on the rows the weights were fitted to. The
cross-encoder is X0's, unchanged. Both arms and match-everything are scored
once on the X3 pack, a fresh, blind pack (``build_x3_pack.py``). Only
aggregates are written.

    python data/scripts/x3_level.py                      # dry run: no test labels
    python data/scripts/x3_level.py --test-labels <csv> --out <json>
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import math
import random
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import numpy as np

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("x2_near_miss", HERE / "x2_near_miss.py")
x2 = importlib.util.module_from_spec(_spec)
sys.modules["x2_near_miss"] = x2
_spec.loader.exec_module(x2)
x1, x0, tr, fc = x2.x1, x2.x0, x2.tr, x2.fc

DATA = x1.DATA
PACKS = DATA / "review_packs"
PREREG = DATA / "er_bench" / "benchmark_x3_level_preregistration.json"
CORRECTED, REVIEWED = "adjudication_pack_corrected_reviewed.csv", "adjudication_pack_reviewed.csv"
DEV = {
    "2026-08-19": PACKS / "nigeria_facilities_2026-08-19" / CORRECTED,
    "x1": PACKS / "nigeria_facilities_x1_2026-11-21" / CORRECTED,
    "near_miss": PACKS / "nigeria_facilities_nearmiss_2026-11-21" / REVIEWED,
}
TEST_PACK = PACKS / "nigeria_facilities_x3_2026-11-22" / "adjudication_pack.csv"
HFR_NATIONAL = fc.CACHE / "hfr_national.json"
KINDS = Path.home() / ".cache" / "arche" / "x3" / "kinds.json"   # kept out of the pack
RANK = {"primary": 0, "secondary": 1, "tertiary": 2}
FOLDS = 5
MIN_DIFFERENT = 60


def hfr_rank(t: str | None) -> int | None:
    t = (t or "").strip().lower()
    if t.startswith(("primary", "health post")):
        return 0
    return RANK.get(t)


def levels() -> tuple[dict[str, int | None], dict[str, dict]]:
    with HFR_NATIONAL.open(encoding="utf-8") as fh:
        hfr = {f["properties"]["global_id"]: f["properties"] for f in json.load(fh)["features"]}
    grid3 = {}
    with (DATA / "GRID3_NGA_health_facilities_v2.csv").open(encoding="utf-8-sig") as fh:
        for r in csv.DictReader(fh):
            grid3[r["globalid"]] = {"rank": RANK.get(r["facility_level"].strip().lower()),
                                    "state": r["state"].strip().lower()}
    return grid3, hfr


def level_woe(grid3: dict, hfr: dict) -> dict[str, float]:
    """log(m/u) per level gap, from the training states' trusted links."""
    by_lga: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for h in hfr.values():
        state = (h.get("state_name") or "").strip().lower()
        if state not in fc.TEST_STATES:
            by_lga[(state, (h.get("lga_name") or "").strip().lower())].append(h)
    rng = random.Random(0)
    m, u = Counter(), Counter()
    for gid in sorted(grid3):
        g, h = grid3[gid], hfr.get(gid)
        if g["state"] in fc.TEST_STATES or h is None or g["rank"] is None:
            continue
        b = hfr_rank(h.get("type"))
        if b is None:
            continue
        m[abs(g["rank"] - b)] += 1
        pool = by_lga.get((g["state"], (h.get("lga_name") or "").strip().lower()), [])
        other = rng.choice(pool) if pool else None
        if other is not None and other["global_id"] != gid:
            ob = hfr_rank(other.get("type"))
            if ob is not None:
                u[abs(g["rank"] - ob)] += 1
    mt, ut = sum(m.values()), sum(u.values())
    return {str(k): round(math.log((m[k] / mt) / (u[k] / ut)), 4) for k in (0, 1, 2)}


def level_feature(rows, grid3, hfr, woe) -> np.ndarray:
    out = []
    for r in rows:
        a = grid3.get(r["grid3_id"].split(":", 1)[1], {}).get("rank")
        h = hfr.get(r["hfr_id"].split(":", 1)[1])
        b = hfr_rank(h.get("type")) if h else None
        out.append(0.0 if a is None or b is None else woe[str(abs(a - b))])
    return np.array(out)


def read(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as fh:
        rows = [r for r in csv.DictReader(fh)
                if r["review_outcome"] in ("same_entity", "different")]
    return sorted(rows, key=lambda r: r["decision_id"])


def fold_of(r: dict) -> int:
    return int(hashlib.sha256(("x3\0" + r["decision_id"]).encode()).hexdigest()[:8], 16) % FOLDS


def fit(x: np.ndarray, y: np.ndarray, folds: np.ndarray):
    """Weights on all rows; thresholds from out-of-fold predictions."""
    oof = np.zeros(len(y))
    for k in range(FOLDS):
        tr_ix, te_ix = folds != k, folds == k
        oof[te_ix] = x0.predict(x0.fit_logistic(x[tr_ix], y[tr_ix]), x[te_ix])
    lo, hi = x0.thresholds(oof, y)
    return x0.fit_logistic(x, y), lo, hi


def by_kind(p, lo, hi, y, kinds) -> dict[str, Any]:
    out = {}
    for kind in sorted(set(kinds)):
        ix = np.array([k == kind for k in kinds])
        m, j = p[ix] >= hi, p[ix] <= lo
        out[kind] = {"pairs": int(ix.sum()), "same_entity": int(y[ix].sum()),
                     "auto_match": int(m.sum()), "auto_reject": int(j.sum()),
                     "false_merges": int((m & (y[ix] == 0)).sum()),
                     "false_rejects": int((j & (y[ix] == 1)).sum())}
    return out


def score(name, p, lo, hi, y, kinds=None):
    res = x0.apply(p, y, lo, hi)
    decided = res.pop("_decided")
    res["false_merges"] = x2.false_merges(p, y, hi)
    fmr = res["false_merges"]
    res["false_merge_bound"] = (fmr["rate"] is not None and fmr["rate"] <= 0.02
                                and fmr["wilson95_upper"] <= 0.05)
    res["pass"] = res["fewer_held"] and res["error_bound"] and res["false_merge_bound"]
    res["review_auc"] = round(tr.auc(p, y), 4) if 0 < y.sum() < len(y) else None
    if kinds is not None:
        res["by_kind"] = by_kind(p, lo, hi, y, kinds)
    print(name, json.dumps(res), flush=True)
    return res, decided


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--test-labels", type=Path)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    started = time.time()
    grid3_lv, hfr_lv = levels()
    woe = level_woe(grid3_lv, hfr_lv)
    print("level weight of evidence by gap:", woe)
    prereg = json.loads(PREREG.read_text(encoding="utf-8")) if PREREG.exists() else None
    if prereg is not None:
        if fc._digest(prereg["rule"]) != prereg["rule_sha256"]:
            raise SystemExit("rule differs from its recorded digest; refusing to run")
        if woe != prereg["level_woe"]:
            raise SystemExit("level weights differ from the preregistered ones")
        for k, p in DEV.items():
            if tr._sha(p) != prereg["development_labels_sha256"][k]:
                raise SystemExit(f"development labels {k} changed since the preregistration")
        if tr._sha(TEST_PACK) != prereg["test"]["pack_sha256"]:
            raise SystemExit("the X3 pack changed since the preregistration")
    elif args.test_labels:
        raise SystemExit("no preregistration; refusing to read test labels")

    dev = [r for p in DEV.values() for r in read(p)]
    y_dev = x1.labels(dev)
    folds = np.array([fold_of(r) for r in dev])
    gxy, hxy = x1.coordinates()
    lv_dev = level_feature(dev, grid3_lv, hfr_lv, woe)
    print(f"development {len(dev)} ({int(y_dev.sum())} same, {int((y_dev == 0).sum())} different);"
          f" levels differ on {int((lv_dev < 0).sum())}")
    test = read(args.test_labels) if args.test_labels else []
    if args.test_labels:
        with TEST_PACK.open(encoding="utf-8") as fh:
            known = {r["decision_id"] for r in csv.DictReader(fh)}
        if {r["decision_id"] for r in test} - known:
            raise SystemExit("test labels hold decisions that are not in the X3 pack")
    arms: dict[int, dict[str, Any]] = {}
    for seed in x0.SEEDS:
        ce = x0.CrossEncoder(x0.MODELS / f"seed{seed}", "cuda" if x1._cuda() else "cpu")
        z_dev = ce.logits(x1.texts(dev))
        z_test = ce.logits(x1.texts(test)) if test else None
        del ce
        base_dev = x1.features(dev, gxy, hxy, z_dev)
        fitted = {"control": fit(base_dev, y_dev, folds),
                  "level": fit(np.c_[base_dev, lv_dev], y_dev, folds)}
        for arm, (w, lo, hi) in fitted.items():
            print(f"seed {seed} {arm}: weights {[round(float(v), 4) for v in w]}"
                  f" lo {lo:.4f} hi {hi:.4f}")
        arms[seed] = {"fitted": fitted, "z_test": z_test}
    if not test:
        print("dry run: no test labels read")
        return

    y = x1.labels(test)
    if tr._sha(KINDS) != prereg["test"]["kinds_sha256"]:
        raise SystemExit("the pair kinds changed since the preregistration")
    kind_of = json.loads(KINDS.read_text(encoding="utf-8"))
    kinds = [kind_of[r["decision_id"]] for r in test]
    base = {s: x1.features(test, gxy, hxy, a["z_test"]) for s, a in arms.items()}
    lv = level_feature(test, grid3_lv, hfr_lv, woe)
    result: dict[str, Any] = {"control": {}, "level": {}}
    decided: dict[str, list[np.ndarray]] = {"control": [], "level": []}
    for seed, a in arms.items():
        for arm, x in (("control", base[seed]), ("level", np.c_[base[seed], lv])):
            w, lo, hi = a["fitted"][arm]
            res, d = score(f"{arm} seed {seed}", x0.predict(w, x), lo, hi, y, kinds)
            res["weights"] = [round(float(v), 4) for v in w]
            result[arm][f"seed{seed}"] = res
            decided[arm].append(d)
    result["match_everything"], _ = score("match everything", np.ones(len(y)), -1.0, 0.5, y,
                                         kinds)
    dl, dc = np.mean(decided["level"], axis=0), np.mean(decided["control"], axis=0)
    diff = float((dl - dc).mean())
    lo_b, hi_b = tr.boot(lambda ix: float((dl[ix] - dc[ix]).mean()), len(y))
    n_diff = int((y == 0).sum())
    informative = n_diff >= MIN_DIFFERENT
    level_pass = informative and all(s["pass"] for s in result["level"].values())
    fewer_fm = all(result["level"][k]["false_merges"]["auto_matched"]
                   <= result["control"][k]["false_merges"]["auto_matched"]
                   for k in result["level"])
    verdict = {"informative": informative, "level_pass": level_pass,
               "control_pass": informative and all(s["pass"] for s in result["control"].values()),
               "match_everything_pass": informative and result["match_everything"]["pass"],
               "coverage_gain": round(diff, 4),
               "coverage_gain_bootstrap95": [round(lo_b, 4), round(hi_b, 4)],
               "level_false_merges_no_worse": fewer_fm,
               "level_helps": level_pass and fewer_fm and lo_b > 0}
    print(json.dumps(verdict, indent=2))
    out = {"schema": "arche.x3_level.v1", "preregistration_sha256": tr._sha(PREREG),
           "test_labels_sha256": tr._sha(args.test_labels),
           "test": {"pairs": len(y), "same_entity": int(y.sum()), "different": n_diff,
                    "levels_differ": int((lv < 0).sum())},
           **result, "verdict": verdict, "seconds": round(time.time() - started, 1)}
    if args.out:
        Path(args.out).write_text(json.dumps(out, indent=2, sort_keys=True) + "\n",
                                  encoding="utf-8")
        print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
