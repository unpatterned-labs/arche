#!/usr/bin/env python
"""Compare record linkers on GRID3 v2 -> HFR health facilities, against the id crosswalk.

The truth is the registries' own crosswalk: a GRID3 facility and an HFR record
that share a source id (GRID3 ``globalid`` = HFR ``global_id``) in the same
state. No arm sees ids. Each arm proposes, for each GRID3 facility, at most one
HFR record, either **matched** (settled automatically) or **held** (for a
person). The metrics:

* ``precision``: auto-matches that are the facility's twin, among auto-matches
  of facilities that have a twin in the state;
* ``recall``: twins auto-matched, out of all twins;
* ``held``: facilities whose proposal is held for a person;
* ``recall_with_held``: twins proposed at all, matched or held.

The id crosswalk has its own errors (wrong links, HFR duplicates), so these
measure **agreement with the registries' crosswalk**, not accuracy. Scored on
the seven states the decider's cross-encoder never saw. The combiner was fitted
on about 1,700 labelled pairs from those states, about 1 in 5 of their twins,
which favours the decider arm slightly.

Arms (frozen in ``benchmark_linkers_preregistration.json`` before any arm ran):

* ``exact``: folded name and folded LGA identical, and unique on the HFR side.
* ``splink``: a standard Splink 4 model (DuckDB). Jaro-Winkler on the name, exact
  LGA, and distance bands. Trained unsupervised (u by random sampling, lambda
  from a deterministic rule, m by EM). Matched at probability >= 0.9, held at
  >= 0.5. Best candidate per GRID3 facility.
* ``arche_engine``: arche's engine (``evaluate_facility_master.py``) as it ships.
* ``arche_decider``: the engine, with its held pairs decided by
  nigeria-facility-decider-v1 (``decide_facilities.py``).

    uv run --package arche-core python data/scripts/compare_linkers.py \\
        --national ~/.cache/arche/national --out data/er_bench/benchmark_linkers_result.json
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
DATA = REPO / "data"
PREREG = DATA / "er_bench" / "benchmark_linkers_preregistration.json"
STATES = ("Anambra", "Edo", "Fct", "Kano", "Lagos", "Ondo", "Oyo")
MATCH_P, HOLD_P = 0.9, 0.5


def fold(v: str | None) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", (v or "").casefold()).split())


def sha(p: Path) -> str:
    return "sha256:" + hashlib.sha256(p.read_bytes()).hexdigest()


def load(state: str, national: Path) -> tuple[list[dict], list[dict]]:
    grid3 = []
    with (DATA / "GRID3_NGA_health_facilities_v2.csv").open(encoding="utf-8-sig") as fh:
        for r in csv.DictReader(fh):
            if r["state"].strip().casefold() == state.casefold():
                grid3.append({"id": r["globalid"], "name": fold(r["facility_name"]),
                              "lga": fold(r["lga"]), "lat": _f(r["latitude"]),
                              "lon": _f(r["longitude"])})
    hfr = []
    with (national / "hfr" / f"hfr_{state.casefold()}.csv").open(encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            hfr.append({"id": r["id"], "name": fold(r["name"] or r["alternate_name"]),
                        "lga": fold(r["lga"]), "lat": _f(r["lat"]), "lon": _f(r["lon"])})
    return grid3, hfr


def _f(v: str) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


# -- arms: each returns {grid3_id: (hfr_id, "match" | "held")} -------------------

def arm_exact(grid3, hfr) -> dict[str, tuple[str, str]]:
    index: dict[tuple[str, str], list[str]] = defaultdict(list)
    for h in hfr:
        index[(h["name"], h["lga"])].append(h["id"])
    out = {}
    for g in grid3:
        hits = index.get((g["name"], g["lga"]), [])
        if len(hits) == 1:
            out[g["id"]] = (hits[0], "match")
    return out


def arm_splink(grid3, hfr) -> dict[str, tuple[str, str]]:
    import splink.comparison_library as cl
    from splink import DuckDBAPI, Linker, SettingsCreator, block_on

    def frame(rows, tag):
        return [{"unique_id": f"{tag}:{r['id']}", "name": r["name"], "lga": r["lga"],
                 "lat": r["lat"], "lon": r["lon"], "name4": r["name"][:4]} for r in rows]

    settings = SettingsCreator(
        link_type="link_only",
        comparisons=[cl.JaroWinklerAtThresholds("name", [0.95, 0.88, 0.7]),
                     cl.ExactMatch("lga"),
                     cl.DistanceInKMAtThresholds("lat", "lon", [0.1, 1, 5])],
        blocking_rules_to_generate_predictions=[block_on("lga"), block_on("name4")],
        retain_intermediate_calculation_columns=False)
    linker = Linker([frame(grid3, "g"), frame(hfr, "h")], settings, db_api=DuckDBAPI())
    linker.training.estimate_probability_two_random_records_match(
        [block_on("name", "lga")], recall=0.7)
    linker.training.estimate_u_using_random_sampling(max_pairs=1e6, seed=0)
    linker.training.estimate_parameters_using_expectation_maximisation(block_on("lga"))
    linker.training.estimate_parameters_using_expectation_maximisation(block_on("name4"))
    df = linker.inference.predict(threshold_match_probability=HOLD_P).as_record_dict()
    best: dict[str, tuple[float, str]] = {}
    for r in df:
        a, b = r["unique_id_l"], r["unique_id_r"]
        g, h = (a, b) if a.startswith("g:") else (b, a)
        p = float(r["match_probability"])
        if g not in best or p > best[g][0]:
            best[g] = (p, h)
    return {g[2:]: (h[2:], "match" if p >= MATCH_P else "held") for g, (p, h) in best.items()}


def arm_from_crosswalk(path: Path, column: str) -> dict[str, tuple[str, str]]:
    """Best proposal per GRID3 facility from a crosswalk.csv (engine or final column)."""
    rank = {"match": 2, "review": 1}
    best: dict[str, tuple[int, float, str]] = {}
    with path.open(encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            outcome = r[column]
            if outcome not in rank:
                continue
            g, h = r["grid3_id"].split(":", 1)[1], r["hfr_id"].split(":", 1)[1]
            key = (rank[outcome], float(r["probability"] or 0), h)
            if g not in best or key[:2] > best[g][:2]:
                best[g] = key
    return {g: (h, "match" if k == 2 else "held") for g, (k, _, h) in best.items()}


def score(proposals: dict[str, tuple[str, str]], grid3: list[dict], hfr_ids: set[str]
          ) -> dict[str, Any]:
    twins = {g["id"] for g in grid3 if g["id"] in hfr_ids}
    matched = {g: h for g, (h, k) in proposals.items() if k == "match"}
    held = {g: h for g, (h, k) in proposals.items() if k == "held"}
    evaluable = {g: h for g, h in matched.items() if g in twins}
    correct = sum(g == h for g, h in evaluable.items())
    found = sum(proposals[g][0] == g for g in twins if g in proposals)
    return {"grid3": len(grid3), "twins": len(twins), "matched": len(matched),
            "matched_evaluable": len(evaluable), "matched_correct": correct,
            "precision": round(correct / len(evaluable), 4) if evaluable else None,
            "recall": round(sum(matched.get(g) == g for g in twins) / len(twins), 4)
            if twins else None,
            "held": len(held),
            "recall_with_held": round(found / len(twins), 4) if twins else None,
            "matched_without_twin": len(matched) - len(evaluable)}


def pool(rows: list[dict[str, Any]]) -> dict[str, Any]:
    c = Counter()
    for r in rows:
        c.update({k: v for k, v in r.items() if isinstance(v, int)})
    return {**dict(c),
            "precision": round(c["matched_correct"] / c["matched_evaluable"], 4),
            "recall": None, "recall_with_held": None}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--national", type=Path, required=True)
    ap.add_argument("--out", type=Path)
    args = ap.parse_args()
    national = args.national.expanduser()
    prereg = json.loads(PREREG.read_text(encoding="utf-8"))
    if sha(Path(__file__)) != prereg["code_sha256"]:
        raise SystemExit("this script changed since the preregistration")
    started = time.time()
    per_state: dict[str, dict[str, Any]] = {}
    recall_num: dict[str, Counter] = defaultdict(Counter)
    for state in STATES:
        grid3, hfr = load(state, national)
        hfr_ids = {h["id"] for h in hfr}
        xw = national / state.casefold() / "crosswalk.csv"
        arms = {"exact": arm_exact(grid3, hfr), "splink": arm_splink(grid3, hfr),
                "arche_engine": arm_from_crosswalk(xw, "engine"),
                "arche_decider": arm_from_crosswalk(xw, "final")}
        per_state[state] = {}
        for name, proposals in arms.items():
            s = score(proposals, grid3, hfr_ids)
            per_state[state][name] = s
            twins = {g["id"] for g in grid3 if g["id"] in hfr_ids}
            recall_num[name]["twins"] += len(twins)
            recall_num[name]["recalled"] += sum(proposals.get(g, ("", ""))[0] == g
                                                and proposals[g][1] == "match" for g in twins)
            recall_num[name]["found"] += sum(proposals.get(g, ("", ""))[0] == g for g in twins)
        print(state, json.dumps({k: (v["precision"], v["recall"], v["held"])
                                 for k, v in per_state[state].items()}), flush=True)
    pooled = {}
    for name in ("exact", "splink", "arche_engine", "arche_decider"):
        p = pool([per_state[s][name] for s in STATES])
        n = recall_num[name]
        p["recall"] = round(n["recalled"] / n["twins"], 4)
        p["recall_with_held"] = round(n["found"] / n["twins"], 4)
        pooled[name] = p
    print(json.dumps(pooled, indent=1))
    out = {"schema": "arche.linkers_comparison.v1", "preregistration_sha256": sha(PREREG),
           "states": list(STATES), "pooled": pooled, "per_state": per_state,
           "seconds": round(time.time() - started, 1)}
    if args.out:
        args.out.write_text(json.dumps(out, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
