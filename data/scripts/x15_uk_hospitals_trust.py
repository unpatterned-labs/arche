#!/usr/bin/env python
"""X15: X14 with candidates limited to the hospital's own NHS trust.

X14 failed because ODS ``ets`` has one site code per trust operating at a site:
a hospital's postcode holds a median of 11 other open sites, often with the
same name. Both lists record the operating organisation: CQC's ``Provider ID``
is the trust's ODS code, and ets carries each site's parent trust code (column
15). X15 runs the engine once per trust, each CQC acute NHS location against the
open ets sites of its own provider only. Everything else is X14: lists, the
"unit on site is a different facility" definition, records, the workflow
(engine, then nigeria-facility-decider-v1, then one-to-one) and X13's bounds.

Twins: the CQC location's Location ID is an open ets site code. A twin whose
parent trust is not the CQC provider cannot be found under this rule; it stays
in the denominator.

    uv run --package arche-core python data/scripts/x15_uk_hospitals_trust.py --build
    ~/.cache/arche-scratch/e0/bin/python data/scripts/x15_uk_hospitals_trust.py \\
        --out data/er_bench/benchmark_x15_uk_hospitals_trust_result.json
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

import numpy as np

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, HERE / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


x14 = _load("x14_uk_hospitals")
uk = x14.uk
OUT = uk.UK / "x15"
PREREG = REPO / "data" / "er_bench" / "benchmark_x15_uk_hospitals_trust_preregistration.json"


def sha(p: Path) -> str:
    return "sha256:" + hashlib.sha256(p.read_bytes()).hexdigest()


def load():
    left, right, counts = x14.load()
    with (uk.UK / "hsca_active_locations.csv").open(encoding="utf-8") as fh:
        provider = {f"cqc:{r['Location ID']}": r["Provider ID"].strip() for r in csv.DictReader(fh)}
    with (uk.UK / "ets.csv").open(encoding="latin-1") as fh:
        parent = {f"ods:{r[0]}": r[14] for r in csv.reader(fh)}
    for r in left:
        r["trust"] = provider[r["id"]]
    for r in right:
        r["trust"] = parent[r["id"]]
    return left, right, counts


def build() -> None:
    from arche.resolve import reconcile

    left, right, counts = load()
    by_trust: dict[str, list[dict]] = {}
    for r in right:
        by_trust.setdefault(r["trust"], []).append(r)
    rows_all: list[dict] = []
    backends: Counter = Counter()
    for trust in sorted({r["trust"] for r in left}):
        lr = [{k: v for k, v in r.items() if k not in ("region", "trust")}
              for r in left if r["trust"] == trust]
        rr = [{k: v for k, v in r.items() if k not in ("region", "trust")}
              for r in by_trust.get(trust, [])]
        if not rr:
            counts["cqc_trust_without_sites"] += len(lr)
            continue
        result = reconcile(lr, rr, entity="place")
        backends[str(result.get("backend", {}).get("chosen"))] += 1
        for e in uk.edges(result, lr, rr):
            e["trust"] = trust
            rows_all.append(e)
    rows_all.sort(key=lambda r: (r["cqc_id"], r["ods_id"]))
    OUT.mkdir(parents=True, exist_ok=True)
    with (OUT / "candidate_edges.csv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows_all[0]))
        w.writeheader()
        w.writerows(rows_all)
    summary = {"schema": "arche.uk_hospital_trust_edges.v1", "records": dict(counts),
               "trusts": len({r["trust"] for r in left}), "backends": dict(backends),
               "edges": len(rows_all), "decisions": dict(Counter(r["decision"] for r in rows_all))}
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n",
                                      encoding="utf-8")
    print(json.dumps(summary))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--build", action="store_true")
    ap.add_argument("--out", type=Path)
    args = ap.parse_args()
    if args.build:
        build()
        return
    x13 = x14._load("x13_uk_pipeline")
    x11 = x13.x11
    prereg = json.loads(PREREG.read_text(encoding="utf-8"))
    if "sha256:" + hashlib.sha256(json.dumps(prereg["rule"], sort_keys=True).encode()) \
            .hexdigest() != prereg["rule_sha256"]:
        raise SystemExit("rule differs from its recorded digest")
    for name, digest in prereg["code"].items():
        if sha(HERE / name) != digest:
            raise SystemExit(f"{name} changed since the preregistration")
    if sha(OUT / "candidate_edges.csv") != prereg["edges"]:
        raise SystemExit("edges changed since the preregistration")
    started = time.time()
    decider = x11.PairDecider.load(x11.BUNDLE)
    if decider.pins != prereg["bundle_pins"]:
        raise SystemExit("decider bundle differs from the preregistered one")
    left, right, _ = load()
    open_sites = {r["source_code"]: r for r in right}
    twin_of = {r["id"]: r["source_code"] for r in left if r["source_code"] in open_sites
               and open_sites[r["source_code"]]["region"] == r["region"]}
    with (OUT / "candidate_edges.csv").open(encoding="utf-8") as fh:
        edges = list(csv.DictReader(fh))
    held = [e for e in edges if e["decision"] == "review"]
    ds = decider.decide([(x11.record(e, "cqc"), x11.record(e, "ods")) for e in held])
    out = {e["decision_id"]: d for e, d in zip(held, ds, strict=True)}
    final = {e["decision_id"]: e["decision"] if e["decision"] != "review"
             else out[e["decision_id"]].outcome for e in edges}
    prob = {k: d.probability for k, d in out.items()}
    outcome, y = [], []
    for e in held:
        code = e["cqc_ods_code"]
        if e["ods_id"][4:] == code:
            y.append(1)
        elif e["cqc_id"] in twin_of:
            y.append(0)
        else:
            continue
        outcome.append(out[e["decision_id"]].outcome)
    _, engine_kept, _ = x13.one_to_one(edges, {e["decision_id"]: e["decision"] for e in edges},
                                       prob)
    many, kept, flags = x13.one_to_one(edges, final, prob)
    s = {"engine": x13.score(engine_kept, twin_of), "pipeline_many": x13.score(many, twin_of),
         "pipeline": x13.score(kept, twin_of)}
    lost = ({e["cqc_id"] for e in many if twin_of.get(e["cqc_id"]) == e["ods_id"][4:]}
            - {e["cqc_id"] for e in kept if twin_of.get(e["cqc_id"]) == e["ods_id"][4:]})
    s["pipeline"]["twins_lost"] = len(lost)
    fc = Counter(f for _, f in flags)
    fc["flags_on_twin"] = sum(twin_of.get(e["cqc_id"]) == e["ods_id"][4:] for e, _ in flags)
    fc["still_held"] = sum(final[e["decision_id"]] == "review" for e in held)
    fc["decider_rejected"] = sum(final[e["decision_id"]] == "reject" for e in held)
    fc["twins_outside_own_trust"] = sum(
        1 for c, t in twin_of.items()
        if open_sites[t]["trust"] != next(r["trust"] for r in left if r["id"] == c))
    arms = {a: x13.rates(c) for a, c in s.items()}
    e, p = arms["engine"], arms["pipeline"]
    verdict = {"precision_within_0.1pt_of_engine": p["precision"] >= e["precision"] - 0.001,
               "recall_gain_at_least_5pt": p["recall"] >= e["recall"] + 0.05,
               "twins_lost_at_most_0.1pct": p["twins_lost"] <= 0.001 * p["twins"]}
    verdict["pass"] = all(verdict.values())
    result = {"schema": "arche.x15_uk_hospitals_trust.v1", "preregistration_sha256": sha(PREREG),
              "arms": arms, "flags": dict(fc), "pair_rule": x11.rule(outcome, np.array(y)),
              "verdict": verdict, "seconds": round(time.time() - started, 1)}
    print(json.dumps({a: (v["precision"], v["recall"], v["links"]) for a, v in arms.items()}))
    print(json.dumps(fc), json.dumps(verdict))
    if args.out:
        args.out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
