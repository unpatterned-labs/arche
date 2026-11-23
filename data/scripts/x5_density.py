#!/usr/bin/env python
"""X5: does local facility density make distance a fair witness?

X4 failed in Lagos: the combiner learned in Edo, Kano and Ondo that "same LGA,
a few hundred metres apart" means one facility, and in a dense city it does
not. X5 tells the combiner how crowded the neighbourhood is. For a pair whose
GRID3 point has ``n`` other HFR facilities within ``RADIUS_KM`` and whose two
points are ``d`` km apart, the number of other facilities one would expect at
that distance or closer by chance is ``n * (d / RADIUS_KM) ** 2``. The density
arm adds ``log(expected + 0.05)`` and ``log1p(n)`` to the control features.
Density is read from the HFR's own coordinates (every state), never from
labels.

Two arms, otherwise identical:

* ``control``: [cross-encoder logit, log1p km, LGA agree, coordinates missing]
  (X4's combiner).
* ``density``: control plus the two density features.

The cross-encoder is retrained exactly as X0 and X4 were, with FCT held out
as well as Edo, Kano, Ondo and Lagos (every state with human labels stays out
of its training). Both arms are fitted on every label read so far (the
corrected 2026-08-19 and X1 copies, the near-miss pack, X3 and X4, with the
reviewer's stated corrections in ``CORRECTIONS``), thresholds from 5-fold
out-of-fold predictions, and scored once on the FCT pack
(``build_x5_pack.py``). Only aggregates are written.

    python data/scripts/x5_density.py --train
    python data/scripts/x5_density.py                      # dry run
    python data/scripts/x5_density.py --test-labels <csv> --out <json>
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
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("x4_lagos", HERE / "x4_lagos.py")
x4 = importlib.util.module_from_spec(_spec)
sys.modules["x4_lagos"] = x4
_spec.loader.exec_module(x4)
x3, x2, x1, x0, tr, fc = x4.x3, x4.x2, x4.x1, x4.x0, x4.tr, x4.fc

DATA, PACKS = x3.DATA, x3.PACKS
HELD_OUT = frozenset({"edo", "kano", "ondo", "lagos", "fct"})
MODELS = Path.home() / ".cache" / "arche" / "models" / "x5"
PREREG = DATA / "er_bench" / "benchmark_x5_density_preregistration.json"
TEST_PACK = PACKS / "nigeria_facilities_fct_x5_2026-11-22" / "adjudication_pack.csv"
KINDS = Path.home() / ".cache" / "arche" / "x5" / "kinds.json"     # kept out of the pack
DEV = {**x3.DEV,
       "x3": PACKS / "nigeria_facilities_x3_2026-11-22" / x3.REVIEWED,
       "x4": PACKS / "nigeria_facilities_lagos_x4_2026-11-22" / x3.REVIEWED}
# The reviewer's own stated corrections (decision id -> outcome), read before
# this file was written. Two Lagos pairs were exported as same while the
# reviewer meant can't tell: a Studio bug kept can't-tell pairs cycling.
CORRECTIONS = PACKS / "nigeria_facilities_lagos_x4_2026-11-22" / "corrections.json"
RADIUS_KM = 2.0
MIN_DIFFERENT = 60
STATE_FILES = ("edo", "kano", "ondo", "lagos", "fct")


def examples() -> dict[str, list[tuple[str, str, int]]]:
    saved = fc.TEST_STATES
    fc.TEST_STATES = HELD_OUT
    try:
        return x0.examples()
    finally:
        fc.TEST_STATES = saved


def coordinates():
    grid3, hfr = x1.coordinates()
    for state in ("lagos", "fct"):
        with (DATA / f"hfr_{state}.csv").open(encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                with contextlib.suppress(ValueError):
                    hfr[r["id"]] = (float(r["lat"]), float(r["lon"]))
    return grid3, hfr


class Density:
    """Other HFR facilities within RADIUS_KM of a point (all states, from the HFR)."""

    CELL = 0.05  # degrees, about 5.5 km: a point's neighbours are in its 3x3 block

    def __init__(self) -> None:
        with x3.HFR_NATIONAL.open(encoding="utf-8") as fh:
            feats = json.load(fh)["features"]
        self.grid: dict[tuple[int, int], list[tuple[str, float, float]]] = defaultdict(list)
        for f in feats:
            c = (f.get("geometry") or {}).get("coordinates") or [None, None]
            if c[0] is None or c[1] is None:
                continue
            lon, lat = float(c[0]), float(c[1])
            self.grid[self._key(lat, lon)].append((f["properties"]["global_id"], lat, lon))

    def _key(self, lat: float, lon: float) -> tuple[int, int]:
        return int(math.floor(lat / self.CELL)), int(math.floor(lon / self.CELL))

    def around(self, xy, exclude: set[str]) -> int:
        ki, kj = self._key(*xy)
        n = 0
        for di in (-1, 0, 1):
            for dj in (-1, 0, 1):
                for gid, lat, lon in self.grid.get((ki + di, kj + dj), ()):
                    if gid not in exclude and x1.haversine_km(xy, (lat, lon)) <= RADIUS_KM:
                        n += 1
        return n


ALIASES = DATA / "er_bench" / "lga_aliases_grid3_hfr.json"


def _fold(v: str) -> str:
    return " ".join((v or "").casefold().split())


def build_lga_aliases() -> dict[str, str]:
    """HFR LGA name -> GRID3 LGA name, per state, from where facilities stand.

    For each HFR facility, the nearest GRID3 facility within 2 km in the same
    state (never the one sharing its source id) votes for its LGA name. An HFR
    LGA name whose votes (at least 10) go 60% or more to one differently
    written GRID3 name is an alias of it. No id and no label is used, so the
    table can be built for any two registries with coordinates.
    """
    with x3.HFR_NATIONAL.open(encoding="utf-8") as fh:
        feats = json.load(fh)["features"]
    cell = Density.CELL
    grid: dict[tuple, list] = defaultdict(list)
    with (DATA / "GRID3_NGA_health_facilities_v2.csv").open(encoding="utf-8-sig") as fh:
        for r in csv.DictReader(fh):
            with contextlib.suppress(ValueError):
                lat, lon = float(r["latitude"]), float(r["longitude"])
                grid[(_fold(r["state"]), math.floor(lat / cell), math.floor(lon / cell))].append(
                    (r["globalid"], r["lga"], lat, lon))
    votes: dict[tuple[str, str], dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for f in feats:
        p, c = f["properties"], (f.get("geometry") or {}).get("coordinates") or [None, None]
        if c[0] is None or c[1] is None:
            continue
        state, lat, lon = _fold(p.get("state_name")), float(c[1]), float(c[0])
        best, best_km = None, 2.0
        for di in (-1, 0, 1):
            for dj in (-1, 0, 1):
                key = (state, math.floor(lat / cell) + di, math.floor(lon / cell) + dj)
                for gid, lga, glat, glon in grid.get(key, ()):
                    if gid == p["global_id"]:
                        continue
                    km = x1.haversine_km((lat, lon), (glat, glon))
                    if km <= best_km:
                        best, best_km = lga, km
        if best is not None:
            votes[(state, _fold(p.get("lga_name")))][_fold(best)] += 1
    out = {}
    for (state, lga), v in sorted(votes.items()):
        top, n = max(v.items(), key=lambda kv: (kv[1], kv[0]))
        total = sum(v.values())
        if total >= 10 and n / total >= 0.6 and top != lga:
            out[f"{state}|{lga}"] = top
    return out


def lga_agree(rows, aliases: dict[str, str]) -> np.ndarray:
    """1 when the two LGA names are the same once HFR aliases are applied."""
    out = []
    for r in rows:
        a = _fold(json.loads(r["grid3_admin_path"]).get("admin2", ""))
        hp = json.loads(r["hfr_admin_path"])
        b = _fold(hp.get("admin2", ""))
        b = aliases.get(f"{_fold(hp.get('admin1', r.get('state', '')))}|{b}", b)
        out.append(1.0 if a and a == b else 0.0)
    return np.array(out)


def features(rows, grid3, hfr, z, aliases) -> np.ndarray:
    """X4's features with LGA agreement read through the alias table (amendment 1)."""
    x = x1.features(rows, grid3, hfr, z)
    x[:, 2] = lga_agree(rows, aliases)
    return x


def density_features(rows, grid3, hfr, dens: Density) -> np.ndarray:
    out = []
    for r in rows:
        gid, hid = r["grid3_id"].split(":", 1)[1], r["hfr_id"].split(":", 1)[1]
        a, b = grid3.get(gid), hfr.get(hid)
        if not (a and b):
            out.append((0.0, 0.0))
            continue
        n = dens.around(a, {hid})
        d = x1.haversine_km(a, b)
        out.append((math.log(n * (d / RADIUS_KM) ** 2 + 0.05), math.log1p(n)))
    return np.array(out)


def read_dev() -> list[dict]:
    fixes = json.loads(CORRECTIONS.read_text(encoding="utf-8"))["outcomes"]
    rows = []
    for p in DEV.values():
        with p.open(encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                r["review_outcome"] = fixes.get(r["decision_id"], r["review_outcome"])
                if r["review_outcome"] in ("same_entity", "different"):
                    rows.append(r)
    return sorted(rows, key=lambda r: r["decision_id"])


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--train", action="store_true")
    ap.add_argument("--test-labels", type=Path)
    ap.add_argument("--out", default=None)
    ap.add_argument("--write-aliases", action="store_true")
    args = ap.parse_args()
    if args.write_aliases:
        table = build_lga_aliases()
        ALIASES.write_text(json.dumps({"schema": "arche.lga_aliases.v1",
                                       "built_by": "data/scripts/x5_density.py build_lga_aliases",
                                       "aliases": table}, indent=2, sort_keys=True) + "\n",
                           encoding="utf-8")
        print(f"wrote {len(table)} aliases")
        return
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
            raise SystemExit("the X5 pack changed since the preregistration")
        for seed in x0.SEEDS:
            if x0.weights_digest(MODELS / f"seed{seed}") != prereg["models"][f"seed{seed}"]:
                raise SystemExit(f"seed {seed} weights differ from the preregistered ones")
    elif args.test_labels:
        raise SystemExit("no preregistration; refusing to read test labels")

    dev = read_dev()
    y_dev = x1.labels(dev)
    folds = np.array([x3.fold_of(r) for r in dev])
    gxy, hxy = coordinates()
    dens = Density()
    aliases = build_lga_aliases()
    if prereg is not None and tr._sha(ALIASES) != prereg["amendments"][0]["lga_aliases_sha256"]:
        raise SystemExit("the LGA alias file changed since amendment 1")
    stored = json.loads(ALIASES.read_text(encoding="utf-8")) if ALIASES.exists() else None
    if stored is not None and stored["aliases"] != aliases:
        raise SystemExit("the LGA aliases rebuilt differently from the stored table")
    print(f"LGA aliases: {len(aliases)}")
    dd_dev = density_features(dev, gxy, hxy, dens)
    print(f"development {len(dev)} ({int(y_dev.sum())} same, {int((y_dev == 0).sum())} different)")
    test = x3.read(args.test_labels) if args.test_labels else []
    kinds = None
    if test:
        with TEST_PACK.open(encoding="utf-8") as fh:
            known = {r["decision_id"] for r in csv.DictReader(fh)}
        if {r["decision_id"] for r in test} - known:
            raise SystemExit("test labels hold decisions that are not in the X5 pack")
        if tr._sha(KINDS) != prereg["test"]["kinds_sha256"]:
            raise SystemExit("the pair kinds changed since the preregistration")
        kind_of = json.loads(KINDS.read_text(encoding="utf-8"))
        kinds = [kind_of[r["decision_id"]] for r in test]
    dd_test = density_features(test, gxy, hxy, dens) if test else None

    fitted: dict[int, Any] = {}
    for seed in x0.SEEDS:
        ce = x0.CrossEncoder(MODELS / f"seed{seed}", device)
        z_ce = ce.logits([(a, b) for a, b, _ in data["dev"]])
        ce_auc = round(tr.auc(z_ce, np.array([d[2] for d in data["dev"]])), 4)
        z_dev = ce.logits(x1.texts(dev))
        z_test = ce.logits(x1.texts(test)) if test else None
        del ce
        base = features(dev, gxy, hxy, z_dev, aliases)
        arms = {"control": x3.fit(base, y_dev, folds),
                "density": x3.fit(np.c_[base, dd_dev], y_dev, folds)}
        for arm, (w, lo, hi) in arms.items():
            print(f"seed {seed} {arm}: weights {[round(float(v), 4) for v in w]}"
                  f" lo {lo:.4f} hi {hi:.4f}", flush=True)
        fitted[seed] = {"arms": arms, "z_test": z_test, "crosswalk_dev_auc": ce_auc}
    if not test:
        print(f"crosswalk dev AUC: {[f['crosswalk_dev_auc'] for f in fitted.values()]}")
        print("dry run: no test labels read")
        return

    y = x1.labels(test)
    band = np.array(kinds) == "review_band"
    result: dict[str, Any] = {"control": {}, "density": {}}
    decided: dict[str, list[np.ndarray]] = {"control": [], "density": []}
    for seed, f in fitted.items():
        base = features(test, gxy, hxy, f["z_test"], aliases)
        for arm, x in (("control", base), ("density", np.c_[base, dd_test])):
            w, lo, hi = f["arms"][arm]
            p = x0.predict(w, x)
            res, d = x3.score(f"{arm} seed {seed}", p, lo, hi, y, kinds)
            sub = x0.apply(p[band], y[band], lo, hi)
            sub.pop("_decided")
            res["review_band"] = sub
            res["weights"] = [round(float(v), 4) for v in w]
            result[arm][f"seed{seed}"] = res
            decided[arm].append(d)
    result["match_everything"], _ = x3.score("match everything", np.ones(len(y)), -1.0, 0.5,
                                             y, kinds)
    n_diff = int((y == 0).sum())
    informative = n_diff >= MIN_DIFFERENT
    fm = {arm: [s["false_merges"]["auto_matched"] for s in result[arm].values()]
          for arm in ("control", "density")}
    verdict = {
        "informative": informative,
        "density_pass": informative and all(s["pass"] for s in result["density"].values()),
        "control_pass": informative and all(s["pass"] for s in result["control"].values()),
        "density_review_band_pass": all(s["review_band"]["fewer_held"]
                                        and s["review_band"]["error_bound"]
                                        for s in result["density"].values()),
        "density_false_merges_no_worse": all(a <= b for a, b in zip(fm["density"],
                                                                    fm["control"], strict=True)),
        "match_everything_pass": informative and result["match_everything"]["pass"],
    }
    verdict["density_helps"] = verdict["density_pass"] and verdict["density_false_merges_no_worse"]
    print(json.dumps(verdict, indent=2))
    out = {"schema": "arche.x5_density.v1", "preregistration_sha256": tr._sha(PREREG),
           "test_labels_sha256": tr._sha(args.test_labels),
           "test": {"pairs": len(y), "same_entity": int(y.sum()), "different": n_diff,
                    "review_band_pairs": int(band.sum())},
           "crosswalk_dev_auc": {f"seed{s}": f["crosswalk_dev_auc"] for s, f in fitted.items()},
           **result, "verdict": verdict, "seconds": round(time.time() - started, 1)}
    if args.out:
        Path(args.out).write_text(json.dumps(out, indent=2, sort_keys=True) + "\n",
                                  encoding="utf-8")
        print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
