#!/usr/bin/env python
"""X12: a UK-trained decider for CQC GP locations against ODS GP practices.

Population, decided by the user after X11: the ODS side is **GP practices only**
(epraccur role ``RO76``, status not ``INACTIVE``). A hub, a clinic or another cost
centre at a practice's site is a different facility. Everything else is as in
``build_uk_gp.py``: names upper-cased, region and local authority from each
record's postcode (ONSPD), CQC's own point or the postcode centroid, ODS's
postcode centroid, and one engine run per English region.

Truth is CQC's ``Location ODS Code`` (same / different / unscorable, as in X11).

Training uses the six training regions only. Held out: North West, West Midlands,
South East (X11's split).

* **Cross-encoder**: X0's recipe and hyperparameters on ``name | local authority``
  text. Positives are CQC/ODS twins, with identical folded names kept one time in
  four. Negatives are the top-10 character n-gram neighbours of the CQC name among
  the ODS practices in its local authority, excluding the twin and identical
  names, first 3. Any CQC location that appears in a training-region held pair is
  left out, together with its twin, so the combiner's pairs are new to the
  cross-encoder.
* **Combiner**: X8's augmented arm on ``[logit, log1p km, LA agree, coordinates
  missing]``, fitted on the training regions' engine-held pairs that have a
  label. Five folds by decision id; located and hidden thresholds come from
  out-of-fold predictions (FPR and FNR each <= 1%).

Arms on the held-out regions' engine-held pairs: ``uk`` (3 seeds) and
``control`` (nigeria-facility-decider-v1 as shipped, on the same pairs).

    uv run --package arche-core python data/scripts/x12_uk_finetune.py --build
    ~/.cache/arche-scratch/e0/bin/python data/scripts/x12_uk_finetune.py --train
    ~/.cache/arche-scratch/e0/bin/python data/scripts/x12_uk_finetune.py \\
        --out data/er_bench/benchmark_x12_uk_finetune_result.json
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


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, HERE / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


uk = _load("build_uk_gp")
x11 = _load("x11_uk_transfer")

UKDIR = uk.UK
OUT = UKDIR / "x12"
MODELS = Path.home() / ".cache" / "arche" / "models" / "x12"
PREREG = REPO / "data" / "er_bench" / "benchmark_x12_uk_finetune_preregistration.json"
HELD_OUT = x11.HELD_OUT
FOLDS = 5


def sha(p: Path) -> str:
    return "sha256:" + hashlib.sha256(p.read_bytes()).hexdigest()


def fold(s: str) -> str:
    import re
    return " ".join(re.sub(r"[^a-z0-9]+", " ", (s or "").casefold()).split())


def side(name: str, la: str) -> str:
    name, la = " ".join((name or "").split()), " ".join((la or "").split())
    return f"{name} | {la}" if la else name


def salted(*parts: str) -> int:
    return int(hashlib.sha256("\0".join(("x12",) + parts).encode()).hexdigest()[:12], 16)


def ro76() -> set[str]:
    with (UKDIR / "epraccur.csv").open(encoding="latin-1") as fh:
        return {r[0] for r in csv.reader(fh) if r[25] == "RO76" and r[12] != "INACTIVE"}


def population() -> tuple[list[dict], list[dict], Counter]:
    left, right, counts = uk.load()
    keep = ro76()
    right = [r for r in right if r["source_code"] in keep]
    counts["ods_ro76_in_england"] = len(right)
    return left, right, counts


# ------------------------------------------------------------------ build


def build() -> None:
    from arche.resolve import reconcile

    left, right, counts = population()
    summary: dict[str, Any] = {"schema": "arche.uk_gp_edges.v1", "population": "ODS RO76",
                               "records": dict(counts), "regions": {}}
    for region in sorted({r["region"] for r in left}):
        lr = [{k: v for k, v in r.items() if k != "region"} for r in left if r["region"] == region]
        rr = [{k: v for k, v in r.items() if k != "region"} for r in right
              if r["region"] == region]
        result = reconcile(lr, rr, entity="place")
        rows = sorted(uk.edges(result, lr, rr), key=lambda r: (r["cqc_id"], r["ods_id"]))
        d = OUT / region
        d.mkdir(parents=True, exist_ok=True)
        with (d / "candidate_edges.csv").open("w", encoding="utf-8", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)
        summary["regions"][region] = {"cqc": len(lr), "ods": len(rr), "edges": len(rows),
                                      "decisions": dict(Counter(r["decision"] for r in rows))}
        print(region, summary["regions"][region], flush=True)
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n",
                                      encoding="utf-8")


def read_edges(region: str) -> list[dict]:
    with (OUT / region / "candidate_edges.csv").open(encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def label(e: dict, ods_region: dict[str, str], region: str) -> int | None:
    code = e["cqc_ods_code"]
    if e["ods_id"][4:] == code:
        return 1
    if code and ods_region.get(code) == region:
        return 0
    return None


# ------------------------------------------------------------------ training data


def training_examples(left, right) -> tuple[list[tuple[str, str, int]], dict[str, int]]:
    from arche.retrieval import CharNgramIndex

    regions = sorted({r["region"] for r in left} - set(HELD_OUT))
    ods = {r["source_code"]: r for r in right}
    excluded: set[str] = set()
    for region in regions:
        for e in read_edges(region):
            if e["decision"] == "review":
                excluded.add(e["cqc_id"])
    by_la: dict[str, list[dict]] = defaultdict(list)
    for r in right:
        if r["region"] in regions:
            by_la[r["admin_path"].get("admin2", "")].append(r)
    index = {k: CharNgramIndex([r["name"] for r in v]) for k, v in by_la.items()}
    out: list[tuple[str, str, int]] = []
    c: Counter = Counter()
    for g in left:
        if g["region"] not in regions:
            continue
        if g["id"] in excluded:
            c["cqc_excluded_held"] += 1
            continue
        twin = ods.get(g["source_code"])
        if not twin or twin["region"] != g["region"]:
            continue
        la_g, la_t = g["admin_path"].get("admin2", ""), twin["admin_path"].get("admin2", "")
        if fold(g["name"]) != fold(twin["name"]) or salted("ident", g["id"]) % 4 == 0:
            out.append((side(g["name"], la_g), side(twin["name"], la_t), 1))
            c["positives"] += 1
        rows = by_la.get(la_g, [])
        if not rows:
            continue
        found = [rows[i] for i, _ in index[la_g].search(g["name"], k=10)]
        negs = [r for r in found if r["source_code"] != twin["source_code"]
                and fold(r["name"]) not in (fold(g["name"]), fold(twin["name"]))][:3]
        out += [(side(g["name"], la_g), side(r["name"], r["admin_path"].get("admin2", "")), 0)
                for r in negs]
        c["negatives"] += len(negs)
    return out, dict(c)


# ------------------------------------------------------------------ decider


def held_rows(regions, ods_region) -> list[dict]:
    rows = []
    for region in regions:
        for e in read_edges(region):
            if e["decision"] != "review":
                continue
            e["_y"] = label(e, ods_region, region)
            e["_region"] = region
            rows.append(e)
    return rows


def features(rows: list[dict], z: np.ndarray) -> np.ndarray:
    dist, agree, missing = [], [], []
    for r in rows:
        a, b = x11.record(r, "cqc"), x11.record(r, "ods")
        located = None not in (a["lat"], a["lon"], b["lat"], b["lon"])
        d = haversine((a["lat"], a["lon"]), (b["lat"], b["lon"])) if located else 0.0
        dist.append(math.log1p(d))
        missing.append(0.0 if located else 1.0)
        agree.append(1.0 if fold(a["admin2"]) and fold(a["admin2"]) == fold(b["admin2"]) else 0.0)
    return np.c_[z, dist, agree, missing]


def haversine(a, b) -> float:
    la1, lo1, la2, lo2 = map(math.radians, (*a, *b))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) \
        * math.sin((lo2 - lo1) / 2) ** 2
    return 12742.0 * math.asin(math.sqrt(h))


def hide(x: np.ndarray) -> np.ndarray:
    h = x.copy()
    h[:, 1] = 0.0
    h[:, 3] = 1.0
    return h


def texts(rows):
    return [(side(r["cqc_name"], json.loads(r["cqc_admin_path"]).get("admin2", "")),
             side(r["ods_name"], json.loads(r["ods_admin_path"]).get("admin2", ""))) for r in rows]


def fold_of(r: dict) -> int:
    key = "x12\0" + r["cqc_id"] + "\0" + r["ods_id"]
    return int(hashlib.sha256(key.encode()).hexdigest()[:8], 16) % FOLDS


def fit(x0, x: np.ndarray, y: np.ndarray, folds: np.ndarray):
    xa, ya, fa = np.r_[x, hide(x)], np.r_[y, y], np.r_[folds, folds]
    oof = np.zeros(len(ya))
    for k in range(FOLDS):
        a, b = fa != k, fa == k
        oof[b] = x0.predict(x0.fit_logistic(xa[a], ya[a]), xa[b])
    n = len(y)
    return x0.fit_logistic(xa, ya), x0.thresholds(oof[:n], y), x0.thresholds(oof[n:], y)


def outcomes(p: np.ndarray, located: np.ndarray, loc_t, hid_t) -> list[str]:
    out = []
    for pi, li in zip(p, located, strict=True):
        lo, hi = loc_t if li else hid_t
        out.append("match" if pi >= hi else "reject" if pi <= lo else "review")
    return out


def linker(rows_by_region, finals, ods_region) -> dict[str, Any]:
    """Best proposal per CQC location (compare_linkers' rule), and one-to-one."""
    c: Counter = Counter()
    for region, edges in rows_by_region.items():
        twin_of = {e["cqc_id"]: e["cqc_ods_code"] for e in edges
                   if e["cqc_ods_code"] and ods_region.get(e["cqc_ods_code"]) == region}
        c["twins"] += len(twin_of)
        matched = [e for e in edges if finals[e["decision_id"]] == "match"]
        matched.sort(key=lambda e: (0 if e["decision"] == "match" else 1,
                                    -float(e["score"] if e["decision"] == "match"
                                           else e["_p"]), e["decision_id"]))
        used_c, used_o = set(), set()
        for e in matched:
            if e["cqc_id"] in used_c or e["ods_id"] in used_o:
                c["one_to_one_flags"] += 1
                continue
            used_c.add(e["cqc_id"])
            used_o.add(e["ods_id"])
            if e["cqc_id"] in twin_of:
                c["evaluable"] += 1
                c["correct"] += e["ods_id"][4:] == twin_of[e["cqc_id"]]
    return {**dict(c), "precision": round(c["correct"] / c["evaluable"], 4)
            if c["evaluable"] else None,
            "recall": round(c["correct"] / c["twins"], 4) if c["twins"] else None}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--build", action="store_true")
    ap.add_argument("--train", action="store_true")
    ap.add_argument("--examples", action="store_true", help="print training-set counts")
    ap.add_argument("--out", type=Path)
    args = ap.parse_args()
    if args.build:
        build()
        return
    x0 = _load("x0_cross_encoder")
    left, right, _ = population()
    ods_region = {r["source_code"]: r["region"] for r in right}
    if args.examples or args.train:
        data, counts = training_examples(left, right)
        print(json.dumps(counts), flush=True)
        if args.train:
            for seed in x0.SEEDS:
                x0.train(data, seed, MODELS / f"seed{seed}", "cuda")
        return
    prereg = json.loads(PREREG.read_text(encoding="utf-8"))
    if "sha256:" + hashlib.sha256(json.dumps(prereg["rule"], sort_keys=True).encode()) \
            .hexdigest() != prereg["rule_sha256"]:
        raise SystemExit("rule differs from its recorded digest")
    for name, digest in prereg["code"].items():
        if sha(HERE / name) != digest:
            raise SystemExit(f"{name} changed since the preregistration")
    for region, digest in prereg["edges"].items():
        if sha(OUT / region / "candidate_edges.csv") != digest:
            raise SystemExit(f"{region} edges changed since the preregistration")
    for seed in x0.SEEDS:
        if x0.weights_digest(MODELS / f"seed{seed}") != prereg["models"][f"seed{seed}"]:
            raise SystemExit(f"seed {seed} weights differ from the preregistered ones")
    started = time.time()
    train_regions = sorted(set(prereg["edges"]) - set(HELD_OUT))
    dev = [r for r in held_rows(train_regions, ods_region) if r["_y"] is not None]
    test_all = held_rows(HELD_OUT, ods_region)
    test = [r for r in test_all if r["_y"] is not None]
    y_dev = np.array([r["_y"] for r in dev])
    y = np.array([r["_y"] for r in test])
    folds = np.array([fold_of(r) for r in dev])
    by_region = {reg: read_edges(reg) for reg in HELD_OUT}
    result: dict[str, Any] = {"schema": "arche.x12_uk_finetune.v1",
                              "preregistration_sha256": sha(PREREG),
                              "development": {"pairs": len(dev), "same": int(y_dev.sum())},
                              "test": {"held_pairs": len(test_all), "scorable": len(test),
                                       "same": int(y.sum())}}

    def finals_for(outs: dict[str, str], probs: dict[str, float]) -> dict[str, str]:
        f = {}
        for edges in by_region.values():
            for e in edges:
                e["_p"] = probs.get(e["decision_id"], 1.0)
                f[e["decision_id"]] = "match" if e["decision"] == "match" else \
                    outs.get(e["decision_id"], "review")
        return f

    for seed in x0.SEEDS:
        ce = x0.CrossEncoder(MODELS / f"seed{seed}", "cuda")
        z_dev, z_all = ce.logits(texts(dev)), ce.logits(texts(test_all))
        del ce
        w, loc_t, hid_t = fit(x0, features(dev, z_dev), y_dev, folds)
        x_all = features(test_all, z_all)
        p_all = x0.predict(w, x_all)
        located = x_all[:, 3] == 0
        o_all = outcomes(p_all, located, loc_t, hid_t)
        ix = np.array([r["_y"] is not None for r in test_all])
        o = [oi for oi, k in zip(o_all, ix, strict=True) if k]
        p_hid = x0.predict(w, hide(x_all))[ix]
        o_hid = outcomes(p_hid, np.zeros(len(p_hid), bool), loc_t, hid_t)
        ids = [r["decision_id"] for r in test_all]
        finals = finals_for(dict(zip(ids, o_all, strict=True)),
                            dict(zip(ids, p_all.tolist(), strict=True)))
        result[f"uk_seed{seed}"] = {
            "weights": [round(float(v), 6) for v in w],
            "thresholds": {"located": [round(v, 6) for v in loc_t],
                           "hidden": [round(v, 6) for v in hid_t]},
            "rule": x11.rule(o, y), "hidden_rule": x11.rule(o_hid, y),
            "unscorable_outcomes": dict(Counter(oi for oi, k in zip(o_all, ix, strict=True)
                                                if not k)),
            "linker_one_to_one": linker(by_region, finals, ods_region)}
        print(f"seed{seed}", json.dumps({k: result[f"uk_seed{seed}"]["rule"][k] for k in
                                         ("coverage", "errors", "false_merges", "pass")}),
              "hidden pass", result[f"uk_seed{seed}"]["hidden_rule"]["pass"], flush=True)

    decider = x11.PairDecider.load(x11.BUNDLE)
    ds = decider.decide([(x11.record(r, "cqc"), x11.record(r, "ods")) for r in test_all])
    o_all = [d.outcome for d in ds]
    ids = [r["decision_id"] for r in test_all]
    finals = finals_for(dict(zip(ids, o_all, strict=True)),
                        {i: d.probability for i, d in zip(ids, ds, strict=True)})
    o = [oi for oi, r in zip(o_all, test_all, strict=True) if r["_y"] is not None]
    result["control"] = {"rule": x11.rule(o, y),
                         "linker_one_to_one": linker(by_region, finals, ods_region)}
    engine_only = finals_for({}, {})
    result["engine"] = {"linker_one_to_one": linker(by_region, engine_only, ods_region)}
    result["reference_match_everything_pass"] = x11.rule(["match"] * len(y), y)["pass"]
    seeds = [result[f"uk_seed{s}"]["rule"]["pass"] for s in x0.SEEDS]
    result["verdict"] = {"uk_pass_all_seeds": all(seeds), "uk_pass_seeds": sum(seeds),
                         "uk_hidden_pass_all_seeds": all(result[f"uk_seed{s}"]["hidden_rule"]
                                                         ["pass"] for s in x0.SEEDS),
                         "control_pass": result["control"]["rule"]["pass"]}
    result["seconds"] = round(time.time() - started, 1)
    print("control", json.dumps(result["control"]["rule"]))
    print(json.dumps(result["verdict"]))
    if args.out:
        args.out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
