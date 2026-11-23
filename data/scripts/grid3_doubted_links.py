#!/usr/bin/env python
"""Score every GRID3 v2 / HFR id-linked pair in the decider's held-out states.

The pairs that share a source id (GRID3 ``globalid`` = HFR ``global_id``) are
the registries' own crosswalk. The decider never sees ids, so the pairs it does
not match on name, LGA and location alone are the links it "doubts". This is
outside its tested scope (it was built for the engine's held pairs), so the
output means "links the decider would not confirm on its own", not "wrong
links". Prints counts, reasons and a few examples, and writes ids only to
``~/.cache/arche/grid3_feedback/doubted_twin_links.json``.

    ~/.cache/arche-scratch/e0/bin/python data/scripts/grid3_doubted_links.py
"""

from __future__ import annotations

import collections
import csv
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "packages" / "arche-core" / "src"))
from arche.resolve import PairDecider  # noqa: E402

HELD_OUT = ("edo", "kano", "ondo", "lagos", "fct", "oyo", "anambra")
BUNDLE = Path.home() / ".cache" / "arche" / "models" / "nigeria-facility-decider-v1"
HFR_NATIONAL = Path.home() / ".cache" / "arche" / "e0c" / "hfr_national.json"
OUT = Path.home() / ".cache" / "arche" / "grid3_feedback" / "doubted_twin_links.json"
FAR = 1.0986  # log1p(2 km)


def reasons(decision) -> str:
    f, out = decision.features, []
    if f["cross_encoder_logit"] < 0:
        out.append("names disagree")
    if decision.located and f["log1p_km"] > FAR:
        out.append("points >2 km apart")
    if not decision.located:
        out.append("a point is missing")
    if f["admin2_agree"] == 0:
        out.append("LGAs disagree")
    return " + ".join(out) or "weak overall"


def main() -> None:
    decider = PairDecider.load(BUNDLE)
    with HFR_NATIONAL.open(encoding="utf-8") as fh:
        hfr = {}
        for f in json.load(fh)["features"]:
            p, c = f["properties"], (f.get("geometry") or {}).get("coordinates") or [None, None]
            hfr[p["global_id"]] = {"name": p.get("name") or p.get("alternate_name") or "",
                                   "admin1": p.get("state_name") or "",
                                   "admin2": p.get("lga_name") or "", "lat": c[1], "lon": c[0]}
    pairs, meta = [], []
    with (REPO / "data" / "GRID3_NGA_health_facilities_v2.csv").open(encoding="utf-8-sig") as fh:
        for r in csv.DictReader(fh):
            state = r["state"].strip().casefold()
            if state in HELD_OUT and r["globalid"] in hfr:
                pairs.append(({"name": r["facility_name"], "admin1": r["state"], "admin2": r["lga"],
                               "lat": r["latitude"], "lon": r["longitude"]}, hfr[r["globalid"]]))
                meta.append((state, r["globalid"]))
    decisions = decider.decide(pairs)
    by_state: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    why: collections.Counter = collections.Counter()
    examples: dict[str, list[str]] = collections.defaultdict(list)
    doubted = []
    for (state, gid), (a, b), d in zip(meta, pairs, decisions, strict=True):
        by_state[state][d.outcome] += 1
        if d.outcome == "match":
            continue
        key = reasons(d)
        why[(d.outcome, key)] += 1
        if len(examples[key]) < 4:
            examples[key].append(f"{a['name']} / {b['name']} ({state})")
        doubted.append({"state": state, "globalid": gid, "decider": d.outcome,
                        "probability": round(d.probability, 4), "reason": key})
    total: collections.Counter = collections.Counter()
    for state, counts in sorted(by_state.items()):
        total.update(counts)
        print(state, dict(counts))
    print("total", dict(total), sum(total.values()))
    for (outcome, key), n in why.most_common():
        print(n, outcome, key)
    for key, names in examples.items():
        print(key, "->", names)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"pins": decider.pins, "doubted_links": doubted}, indent=1) + "\n",
                   encoding="utf-8")
    print(f"wrote {len(doubted)} doubted links (ids only) to {OUT}")


if __name__ == "__main__":
    main()
