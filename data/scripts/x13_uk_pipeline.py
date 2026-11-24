#!/usr/bin/env python
"""X13: engine + nigeria-facility-decider-v1 + one-to-one on English GP practices.

The edges are X12's (CQC GP locations against ODS GP practices, role RO76), in
the six regions X12 used for training. The Nigerian decider has never trained on
UK data, and nobody has looked at the one-to-one view of these regions. Held-out
regions (X11 and X12 test) are not scored here.

Pipeline per region:

1. the engine's matches stand; each held pair goes to the decider as it ships;
2. one-to-one: rank matched links, the engine's by engine score, then the
   decider's by probability, ties by decision id; accept in order; a link whose
   CQC location or ODS practice is already linked becomes a flag.

Scored on every kept link against CQC's ``Location ODS Code``:

* ``precision``: links that join a CQC location to its twin, among links whose
  CQC location has a twin among the region's RO76 practices;
* ``recall``: twins linked / twins;
* ``twins_lost``: twins the pipeline matched before one-to-one but not after.

Baseline: the engine's matches under the same one-to-one rule. Rule and bounds in
``benchmark_x13_uk_pipeline_preregistration.json``. Only aggregates are written.

    ~/.cache/arche-scratch/e0/bin/python data/scripts/x13_uk_pipeline.py \\
        --out data/er_bench/benchmark_x13_uk_pipeline_result.json
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
_spec = importlib.util.spec_from_file_location("x12_uk_finetune", HERE / "x12_uk_finetune.py")
x12 = importlib.util.module_from_spec(_spec)
sys.modules["x12_uk_finetune"] = x12
_spec.loader.exec_module(x12)
x11 = x12.x11

PREREG = REPO / "data" / "er_bench" / "benchmark_x13_uk_pipeline_preregistration.json"


def sha(p: Path) -> str:
    return "sha256:" + hashlib.sha256(p.read_bytes()).hexdigest()


def one_to_one(edges: list[dict], final: dict[str, str], prob: dict[str, float]):
    matched = [e for e in edges if final[e["decision_id"]] == "match"]
    matched.sort(key=lambda e: (0 if e["decision"] == "match" else 1,
                                -(float(e["score"]) if e["decision"] == "match"
                                  else prob[e["decision_id"]]), e["decision_id"]))
    used_c: set[str] = set()
    used_o: set[str] = set()
    kept, flags = [], []
    for e in matched:
        if e["cqc_id"] in used_c:
            flags.append((e, "possible_ods_duplicate"))
        elif e["ods_id"] in used_o:
            flags.append((e, "possible_cqc_duplicate"))
        else:
            used_c.add(e["cqc_id"])
            used_o.add(e["ods_id"])
            kept.append(e)
    return matched, kept, flags


def score(links: list[dict], twin_of: dict[str, str]) -> Counter:
    c: Counter = Counter()
    c["links"] = len(links)
    for e in links:
        if e["cqc_id"] in twin_of:
            c["evaluable"] += 1
            c["correct"] += e["ods_id"][4:] == twin_of[e["cqc_id"]]
    c["twins"] = len(twin_of)
    c["twins_linked"] = len({e["cqc_id"] for e in links
                             if twin_of.get(e["cqc_id"]) == e["ods_id"][4:]})
    return c


def rates(c: Counter) -> dict[str, Any]:
    return {**dict(c),
            "precision": round(c["correct"] / c["evaluable"], 5) if c["evaluable"] else None,
            "recall": round(c["twins_linked"] / c["twins"], 5) if c["twins"] else None}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", type=Path)
    args = ap.parse_args()
    prereg = json.loads(PREREG.read_text(encoding="utf-8"))
    if "sha256:" + hashlib.sha256(json.dumps(prereg["rule"], sort_keys=True).encode()) \
            .hexdigest() != prereg["rule_sha256"]:
        raise SystemExit("rule differs from its recorded digest")
    for name, digest in prereg["code"].items():
        if sha(HERE / name) != digest:
            raise SystemExit(f"{name} changed since the preregistration")
    for region, digest in prereg["edges"].items():
        if sha(x12.OUT / region / "candidate_edges.csv") != digest:
            raise SystemExit(f"{region} edges changed since the preregistration")
    started = time.time()
    decider = x11.PairDecider.load(x11.BUNDLE)
    if decider.pins != prereg["bundle_pins"]:
        raise SystemExit("decider bundle differs from the preregistered one")
    _, right, _ = x12.population()
    ods_region = {r["source_code"]: r["region"] for r in right}
    tot = {a: Counter() for a in ("engine", "pipeline_many", "pipeline")}
    flags_tot: Counter = Counter()
    per: dict[str, Any] = {}
    for region in sorted(prereg["edges"]):
        edges = x12.read_edges(region)
        held = [e for e in edges if e["decision"] == "review"]
        ds = decider.decide([(x11.record(e, "cqc"), x11.record(e, "ods")) for e in held])
        out = {e["decision_id"]: d for e, d in zip(held, ds, strict=True)}
        final = {e["decision_id"]: "match" if e["decision"] == "match" else
                 out[e["decision_id"]].outcome for e in edges}
        prob = {k: d.probability for k, d in out.items()}
        engine_final = {e["decision_id"]: e["decision"] for e in edges}
        twin_of = {e["cqc_id"]: e["cqc_ods_code"] for e in edges
                   if e["cqc_ods_code"] and ods_region.get(e["cqc_ods_code"]) == region}
        _, engine_kept, _ = one_to_one(edges, engine_final, prob)
        many, kept, flags = one_to_one(edges, final, prob)
        s = {"engine": score(engine_kept, twin_of), "pipeline_many": score(many, twin_of),
             "pipeline": score(kept, twin_of)}
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
        per[region] = {a: rates(c) for a, c in s.items()} | {"flags": dict(fc)}
        print(region, json.dumps({a: (v["precision"], v["recall"]) for a, v in per[region].items()
                                  if a != "flags"}), dict(fc), flush=True)
    arms = {a: rates(c) for a, c in tot.items()}
    e, p = arms["engine"], arms["pipeline"]
    verdict = {"precision_within_0.1pt_of_engine": p["precision"] >= e["precision"] - 0.001,
               "recall_gain_at_least_5pt": p["recall"] >= e["recall"] + 0.05,
               "twins_lost_at_most_0.1pct": p["twins_lost"] <= 0.001 * p["twins"]}
    verdict["pass"] = all(verdict.values())
    result = {"schema": "arche.x13_uk_pipeline.v1", "preregistration_sha256": sha(PREREG),
              "arms": arms, "flags": dict(flags_tot), "regions": per, "verdict": verdict,
              "seconds": round(time.time() - started, 1)}
    print(json.dumps({a: (v["precision"], v["recall"], v["links"]) for a, v in arms.items()}))
    print(json.dumps(flags_tot), json.dumps(verdict))
    if args.out:
        args.out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
