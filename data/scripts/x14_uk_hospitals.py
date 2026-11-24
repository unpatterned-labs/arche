#!/usr/bin/env python
"""X14: the adopted England workflow on NHS hospitals, CQC against ODS trust sites.

Lists (Open Government Licence, local, never redistributed):

* CQC HSCA active locations whose primary inspection category is "Acute hospital
  - NHS non-specialist" or "Acute hospital - NHS specialist";
* ODS ``ets`` (NHS trust sites), every site without a close date.

Definition (user decision, 2026-11-23): a unit or centre with its own site code
on a hospital's grounds (a radiotherapy unit, a diagnostic centre) is a
**different** facility from the hospital.

Truth: CQC uses the ODS site code as the Location ID of NHS locations. A CQC
location's twin is the ets site whose code equals its Location ID, in the same
region.

Records as in X13: names upper-cased; admin1 = region and admin2 = local
authority from each record's postcode (ONSPD); CQC's own point, else the
postcode centroid; ets's postcode centroid. One engine run per region.

Workflow (adopted after X13): engine matches stand; held pairs go to
nigeria-facility-decider-v1 as shipped; then one-to-one (engine first by score,
then decider by probability); extra links become flags. The bounds are X13's,
pooled over all nine regions, which have never been looked at for hospitals.
Only aggregates are written.

    uv run --package arche-core python data/scripts/x14_uk_hospitals.py --build
    ~/.cache/arche-scratch/e0/bin/python data/scripts/x14_uk_hospitals.py \\
        --out data/er_bench/benchmark_x14_uk_hospitals_result.json
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import sys
import time
from collections import Counter
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
OUT = uk.UK / "x14"
PREREG = REPO / "data" / "er_bench" / "benchmark_x14_uk_hospitals_preregistration.json"
CATEGORIES = ("Acute hospital - NHS non-specialist", "Acute hospital - NHS specialist")


def sha(p: Path) -> str:
    return "sha256:" + hashlib.sha256(p.read_bytes()).hexdigest()


def load() -> tuple[list[dict], list[dict], Counter]:
    lad, rgn = uk._names(uk.LAD_NAMES), uk._names(uk.RGN_NAMES)
    post = {}
    with (uk.UK / "postcodes.csv").open(encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            post[r["pc"]] = r
    c: Counter = Counter()

    def place(code: str):
        p = post.get(uk.pc(code))
        if not p or not p["rgn"].startswith("E12"):
            return "", {}, (None, None)
        return p["rgn"], {"admin1": rgn[p["rgn"]], "admin2": lad.get(p["lad"], p["lad"])}, \
            (uk._f(p["lat"]), uk._f(p["lon"]))

    left = []
    with (uk.UK / "hsca_active_locations.csv").open(encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            if r["Location Primary Inspection Category"] not in CATEGORIES:
                continue
            c["cqc_hospitals"] += 1
            region, path, (lat, lon) = place(r["Location Postal Code"])
            own = (uk._f(r["Location Latitude"]), uk._f(r["Location Longitude"]))
            if own[0] is not None and own[1] is not None:
                lat, lon = own
            if not region:
                c["cqc_no_region"] += 1
                continue
            left.append({"id": f"cqc:{r['Location ID']}",
                         "name": r["Location Name"].strip().upper(), "lat": lat, "lon": lon,
                         "admin_path": path, "region": region,
                         "source_code": r["Location ID"].strip(), "source_name": "CQC"})
    right = []
    with (uk.UK / "ets.csv").open(encoding="latin-1") as fh:
        for r in csv.reader(fh):
            if r[11]:
                continue
            c["ets_open"] += 1
            region, path, (lat, lon) = place(r[9])
            if not region:
                c["ets_no_region"] += 1
                continue
            right.append({"id": f"ods:{r[0]}", "name": r[1].strip().upper(), "lat": lat,
                          "lon": lon, "admin_path": path, "region": region,
                          "source_code": r[0], "source_name": "ODS"})
    return left, right, c


def build() -> None:
    from arche.resolve import reconcile

    left, right, counts = load()
    summary: dict[str, Any] = {"schema": "arche.uk_hospital_edges.v1", "records": dict(counts),
                               "regions": {}}
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
        summary["regions"][region] = {"cqc": len(lr), "ets": len(rr), "edges": len(rows),
                                      "decisions": dict(Counter(r["decision"] for r in rows)),
                                      "backend": result.get("backend", {}).get("chosen")}
        print(region, summary["regions"][region], flush=True)
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n",
                                      encoding="utf-8")


def read_edges(region: str) -> list[dict]:
    with (OUT / region / "candidate_edges.csv").open(encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--build", action="store_true")
    ap.add_argument("--out", type=Path)
    args = ap.parse_args()
    if args.build:
        build()
        return
    x13 = _load("x13_uk_pipeline")
    x11 = x13.x11
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
    started = time.time()
    decider = x11.PairDecider.load(x11.BUNDLE)
    if decider.pins != prereg["bundle_pins"]:
        raise SystemExit("decider bundle differs from the preregistered one")
    left, right, _ = load()
    ets_region = {r["source_code"]: r["region"] for r in right}
    all_twins = {r["id"]: r["source_code"] for r in left
                 if ets_region.get(r["source_code"]) == r["region"]}
    cqc_region = {r["id"]: r["region"] for r in left}
    tot = {a: Counter() for a in ("engine", "pipeline_many", "pipeline")}
    flags_tot: Counter = Counter()
    outcome, y = [], []
    per: dict[str, Any] = {}
    for region in sorted(prereg["edges"]):
        edges = read_edges(region)
        held = [e for e in edges if e["decision"] == "review"]
        ds = decider.decide([(x11.record(e, "cqc"), x11.record(e, "ods")) for e in held]) \
            if held else []
        out = {e["decision_id"]: d for e, d in zip(held, ds, strict=True)}
        final = {e["decision_id"]: "match" if e["decision"] == "match" else
                 out[e["decision_id"]].outcome if e["decision"] == "review" else e["decision"]
                 for e in edges}
        prob = {k: d.probability for k, d in out.items()}
        # Every CQC hospital in the region whose twin is in the region, surfaced
        # or not (X13 counted only those in some edge).
        twin_of = {c: t for c, t in all_twins.items() if cqc_region[c] == region}
        for e in held:
            code = e["cqc_ods_code"]
            if e["ods_id"][4:] == code:
                lab = 1
            elif code and ets_region.get(code) == region:
                lab = 0
            else:
                continue
            outcome.append(out[e["decision_id"]].outcome)
            y.append(lab)
        engine_final = {e["decision_id"]: e["decision"] for e in edges}
        _, engine_kept, _ = x13.one_to_one(edges, engine_final, prob)
        many, kept, flags = x13.one_to_one(edges, final, prob)
        s = {"engine": x13.score(engine_kept, twin_of),
             "pipeline_many": x13.score(many, twin_of), "pipeline": x13.score(kept, twin_of)}
        lost = ({e["cqc_id"] for e in many if twin_of.get(e["cqc_id"]) == e["ods_id"][4:]}
                - {e["cqc_id"] for e in kept if twin_of.get(e["cqc_id"]) == e["ods_id"][4:]})
        s["pipeline"]["twins_lost"] = len(lost)
        fc = Counter(f for _, f in flags)
        fc["flags_on_twin"] = sum(twin_of.get(e["cqc_id"]) == e["ods_id"][4:] for e, _ in flags)
        fc["still_held"] = sum(final[e["decision_id"]] == "review" for e in held)
        fc["decider_rejected"] = sum(final[e["decision_id"]] == "reject" for e in held)
        for a in tot:
            tot[a].update(s[a])
        flags_tot.update(fc)
        per[region] = {a: x13.rates(c) for a, c in s.items()} | {"flags": dict(fc)}
        print(region, json.dumps({a: (v["precision"], v["recall"]) for a, v in per[region].items()
                                  if a != "flags"}), dict(fc), flush=True)
    arms = {a: x13.rates(c) for a, c in tot.items()}
    e, p = arms["engine"], arms["pipeline"]
    verdict = {"precision_within_0.1pt_of_engine": p["precision"] >= e["precision"] - 0.001,
               "recall_gain_at_least_5pt": p["recall"] >= e["recall"] + 0.05,
               "twins_lost_at_most_0.1pct": p["twins_lost"] <= 0.001 * p["twins"]}
    verdict["pass"] = all(verdict.values())
    result = {"schema": "arche.x14_uk_hospitals.v1", "preregistration_sha256": sha(PREREG),
              "arms": arms, "flags": dict(flags_tot), "regions": per,
              "pair_rule": x11.rule(outcome, np.array(y)), "verdict": verdict,
              "seconds": round(time.time() - started, 1)}
    print(json.dumps({a: (v["precision"], v["recall"], v["links"]) for a, v in arms.items()}))
    print(json.dumps(flags_tot), json.dumps(verdict))
    if args.out:
        args.out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
