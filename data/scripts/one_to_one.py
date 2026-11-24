#!/usr/bin/env python
"""Make the national crosswalk one-to-one, and turn extra matches into duplicate flags.

The engine plus nigeria-facility-decider-v1 can match one GRID3 facility to two
HFR records (usually one facility listed twice in the HFR), or one HFR record to
two GRID3 facilities. This rule keeps one link per facility on each side:

1. Rank every matched link in a state: the engine's matches first, by engine
   score, then the decider's matches, by decider probability. Ties break by
   decision id.
2. Accept links in that order. A link whose GRID3 facility is already linked
   becomes a ``possible_hfr_duplicate`` flag. A link whose HFR record is already
   linked becomes a ``possible_grid3_duplicate`` flag.

Scored against the registries' id crosswalk (GRID3 ``globalid`` = HFR
``global_id`` in the same state) on every link, with no best-per-facility pick:

* ``precision``: links joining a facility to its twin, among links whose GRID3
  facility has a twin in the state;
* ``recall``: twins linked / twins;
* ``extra_links``: links beyond the first for a GRID3 facility (zero under the
  rule, by construction);
* ``twins_lost``: twins that the many-to-many crosswalk matched but the rule
  turned into a flag.

The arms (``engine``, ``decider`` many-to-many, ``one_to_one``) and the pass
rule are frozen in ``benchmark_one_to_one_preregistration.json``. Writes
``links.csv`` and ``flags.csv`` per state, and aggregates.

    python data/scripts/one_to_one.py --national ~/.cache/arche/national \\
        --out data/er_bench/benchmark_one_to_one_result.json
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
DATA = REPO / "data"
PREREG = DATA / "er_bench" / "benchmark_one_to_one_preregistration.json"
HFR_NATIONAL = Path.home() / ".cache" / "arche" / "e0c" / "hfr_national.json"
SEEN = ("anambra", "edo", "fct", "kano", "lagos", "ondo", "oyo")   # scored in the comparison


def sha(p: Path) -> str:
    return "sha256:" + hashlib.sha256(p.read_bytes()).hexdigest()


def state_links(state_dir: Path) -> list[dict[str, Any]]:
    scores = {}
    with (state_dir / "candidate_edges.csv").open(encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            scores[r["decision_id"]] = float(r["score"] or 0)
    links = []
    with (state_dir / "crosswalk.csv").open(encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            links.append({"decision_id": r["decision_id"],
                          "grid3": r["grid3_id"].split(":", 1)[1],
                          "hfr": r["hfr_id"].split(":", 1)[1],
                          "engine": r["engine"], "final": r["final"],
                          "engine_score": scores.get(r["decision_id"], 0.0),
                          "probability": float(r["probability"] or 0)})
    return links


def one_to_one(links: list[dict[str, Any]]) -> tuple[list[dict], list[dict]]:
    matched = [x for x in links if x["final"] == "match"]
    matched.sort(key=lambda x: (0 if x["engine"] == "match" else 1,
                                -(x["engine_score"] if x["engine"] == "match" else x["probability"]),
                                x["decision_id"]))
    used_g: set[str] = set()
    used_h: set[str] = set()
    kept, flags = [], []
    for x in matched:
        if x["grid3"] in used_g:
            flags.append({**x, "flag": "possible_hfr_duplicate"})
        elif x["hfr"] in used_h:
            flags.append({**x, "flag": "possible_grid3_duplicate"})
        else:
            used_g.add(x["grid3"])
            used_h.add(x["hfr"])
            kept.append(x)
    return kept, flags


def score(links: list[dict], twins: set[str]) -> Counter:
    c: Counter = Counter()
    per_g: Counter = Counter(x["grid3"] for x in links)
    c["links"] = len(links)
    c["extra_links"] = sum(n - 1 for n in per_g.values())
    for x in links:
        if x["grid3"] in twins:
            c["links_evaluable"] += 1
            c["links_correct"] += x["hfr"] == x["grid3"]
    c["twins"] = len(twins)
    c["twins_linked"] = len({x["grid3"] for x in links if x["hfr"] == x["grid3"]} & twins)
    return c


def rates(c: Counter) -> dict[str, Any]:
    return {**dict(c),
            "precision": round(c["links_correct"] / c["links_evaluable"], 5)
            if c["links_evaluable"] else None,
            "recall": round(c["twins_linked"] / c["twins"], 5) if c["twins"] else None}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--national", type=Path, required=True)
    ap.add_argument("--out", type=Path)
    args = ap.parse_args()
    prereg = json.loads(PREREG.read_text(encoding="utf-8"))
    if sha(Path(__file__)) != prereg["code_sha256"]:
        raise SystemExit("this script changed since the preregistration")
    national = args.national.expanduser()
    with HFR_NATIONAL.open(encoding="utf-8") as fh:
        hfr_state = {f["properties"]["global_id"]: (f["properties"].get("state_name") or "")
                     .strip().casefold() for f in json.load(fh)["features"]}
    grid3_state = {}
    with (DATA / "GRID3_NGA_health_facilities_v2.csv").open(encoding="utf-8-sig") as fh:
        for r in csv.DictReader(fh):
            grid3_state[r["globalid"]] = r["state"].strip().casefold()
    totals: dict[str, dict[str, Counter]] = {g: {a: Counter() for a in
                                                 ("engine", "decider", "one_to_one")}
                                             for g in ("primary", "seen")}
    flag_counts: dict[str, Counter] = {"primary": Counter(), "seen": Counter()}
    for state_dir in sorted(p for p in national.iterdir() if (p / "crosswalk.csv").exists()):
        state = state_dir.name.replace("_", " ")
        group = "seen" if state in SEEN else "primary"
        links = state_links(state_dir)
        twins = {g for g, s in grid3_state.items() if s == state and hfr_state.get(g) == state}
        engine = [x for x in links if x["engine"] == "match"]
        decider = [x for x in links if x["final"] == "match"]
        kept, flags = one_to_one(links)
        lost = ({x["grid3"] for x in decider if x["hfr"] == x["grid3"]}
                - {x["grid3"] for x in kept if x["hfr"] == x["grid3"]}) & twins
        for arm, ls in (("engine", engine), ("decider", decider), ("one_to_one", kept)):
            totals[group][arm].update(score(ls, twins))
        totals[group]["one_to_one"]["twins_lost"] += len(lost)
        flag_counts[group].update(f["flag"] for f in flags)
        flag_counts[group]["flags_on_twin"] += sum(f["hfr"] == f["grid3"] for f in flags)
        for name, rows in (("links.csv", kept), ("flags.csv", flags)):
            with (state_dir / name).open("w", encoding="utf-8", newline="") as fh:
                fields = ["decision_id", "grid3", "hfr", "engine", "final", "engine_score",
                          "probability"] + (["flag"] if name == "flags.csv" else [])
                w = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
                w.writeheader()
                w.writerows(rows)
    result: dict[str, Any] = {"schema": "arche.one_to_one.v1", "preregistration_sha256": sha(PREREG)}
    for group in ("primary", "seen"):
        arms = {a: rates(c) for a, c in totals[group].items()}
        o, d, e = arms["one_to_one"], arms["decider"], arms["engine"]
        result[group] = {"arms": arms, "flags": dict(flag_counts[group]),
                         "verdict": {
                             "precision_at_least_engine": o["precision"] >= e["precision"],
                             "recall_within_0.1pt_of_decider": o["recall"] >= d["recall"] - 0.001,
                             "twins_lost_at_most_0.1pct": o["twins_lost"] <= 0.001 * o["twins"]}}
        result[group]["verdict"]["pass"] = all(result[group]["verdict"].values())
        print(group, json.dumps({a: (v["precision"], v["recall"], v["links"], v["extra_links"])
                                 for a, v in arms.items()}), flag_counts[group],
              result[group]["verdict"], flush=True)
    if args.out:
        args.out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
