#!/usr/bin/env python
"""Settle the engine's held GRID3/HFR pairs for one state with a PairDecider bundle.

Input: the engine's candidate edges for a state
(``evaluate_facility_master.py``). The engine's matches are kept as they are:
the decider was never tested on them. Each held (``review``) pair goes to the
decider, which matches it, rejects it, or leaves it held. Writes:

* ``crosswalk.csv``: every edge, with the engine decision, the decider outcome
  and probability, the final decision, and the decider's pins;
* ``still_held.csv``: the pairs a person still has to look at, in the engine's
  edge format, ready for ``build_facility_adjudication_pack.py`` and Studio;
* ``summary.json``: the counts.

    uv run --package arche-core python data/scripts/evaluate_facility_master.py \\
        --state Kaduna --output ~/arche-runs/kaduna --sample-size 0
    ~/.cache/arche-scratch/e0/bin/python data/scripts/decide_facilities.py \\
        --edges ~/arche-runs/kaduna/candidate_edges.csv --state Kaduna \\
        --bundle ~/.cache/arche/models/nigeria-facility-decider-v1 --out ~/arche-runs/kaduna
"""

from __future__ import annotations

import argparse
import contextlib
import csv
import json
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "packages" / "arche-core" / "src"))
from arche.resolve import PairDecider  # noqa: E402

DATA = REPO / "data"


def points(state: str, hfr_csv: Path | None = None) -> tuple[dict, dict]:
    grid3, hfr = {}, {}
    with (DATA / "GRID3_NGA_health_facilities_v2.csv").open(encoding="utf-8-sig") as fh:
        for r in csv.DictReader(fh):
            if r["state"].strip().casefold() == state.casefold():
                with contextlib.suppress(ValueError):
                    grid3[r["globalid"]] = (float(r["latitude"]), float(r["longitude"]))
    with (hfr_csv or DATA / f"hfr_{state.casefold()}.csv").open(encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            with contextlib.suppress(ValueError):
                hfr[r["id"]] = (float(r["lat"]), float(r["lon"]))
    return grid3, hfr


def record(edge: dict, side: str, xy) -> dict:
    path = json.loads(edge[f"{side}_admin_path"])
    return {"name": edge[f"{side}_name"], "admin1": path.get("admin1", ""),
            "admin2": path.get("admin2", ""),
            "lat": xy[0] if xy else None, "lon": xy[1] if xy else None}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--edges", type=Path, required=True)
    ap.add_argument("--state", required=True)
    ap.add_argument("--bundle", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--hfr", type=Path, help="HFR state CSV; defaults to data/hfr_<state>.csv")
    args = ap.parse_args()
    decider = PairDecider.load(args.bundle.expanduser())
    grid3, hfr = points(args.state, args.hfr.expanduser() if args.hfr else None)
    with args.edges.expanduser().open(encoding="utf-8") as fh:
        edges = list(csv.DictReader(fh))
        fields = list(edges[0].keys()) if edges else []
    held = [e for e in edges if e["decision"] == "review"]
    pairs = [(record(e, "grid3", grid3.get(e["grid3_id"].split(":", 1)[1])),
              record(e, "hfr", hfr.get(e["hfr_id"].split(":", 1)[1]))) for e in held]
    decided = dict(zip((e["decision_id"] for e in held), decider.decide(pairs), strict=True))
    out = args.out.expanduser()
    out.mkdir(parents=True, exist_ok=True)
    counts: Counter = Counter()
    with (out / "crosswalk.csv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["decision_id", "grid3_id", "hfr_id", "engine", "decider", "probability",
                    "located", "final", "decider_spec", "cross_encoder"])
        for e in edges:
            d = decided.get(e["decision_id"])
            final = e["decision"] if d is None else d.outcome
            counts[(e["decision"], d.outcome if d else "-")] += 1
            w.writerow([e["decision_id"], e["grid3_id"], e["hfr_id"], e["decision"],
                        d.outcome if d else "", f"{d.probability:.6f}" if d else "",
                        "" if d is None else int(d.located), final,
                        d.pins["decider_spec"] if d else "", d.pins["cross_encoder"] if d else ""])
    with (out / "still_held.csv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        w.writerows(e for e in held if decided[e["decision_id"]].outcome == "review")
    summary = {"state": args.state, "edges": len(edges),
               "engine_match": sum(e["decision"] == "match" for e in edges),
               "engine_review": len(held),
               "decider": dict(Counter(d.outcome for d in decided.values())),
               "decider_without_location": sum(not d.located for d in decided.values()),
               "pins": decider.pins}
    (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary))


if __name__ == "__main__":
    main()
