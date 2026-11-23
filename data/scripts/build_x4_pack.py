#!/usr/bin/env python
"""Build the X4 test pack in Lagos, the state held out of X4's training.

Three kinds of pair, all written blind (decision ``review``, no score; the kind
is kept out of the pack):

* ``review_band``: ``BAND`` pairs, in salted-hash order, from the pairs today's
  engine holds for review in Lagos (``evaluate_facility_master.py``). The
  population the decider is for.
* ``lookalike`` and ``near_miss``: ``STRESS`` of each, built as for X3
  (``build_x3_pack.py``) from GRID3 and HFR records not already in the sample,
  so the test holds enough different pairs to bound false merges.

Each row shows the GRID3 facility's own HFR record when it has one, both
points' Plus Code and H3 cell, and both registries' facility level.

    uv run --package arche-core python data/scripts/build_x4_pack.py \\
        --edges ~/.cache/arche/x4/Lagos/candidate_edges.csv --work ~/.cache/arche/x4
    uv run --package arche-core python data/scripts/build_facility_adjudication_pack.py \\
        --sample Lagos=~/.cache/arche/x4/Lagos/adjudication_sample.csv \\
        --output data/review_packs/nigeria_facilities_lagos_x4_2026-11-22
"""

from __future__ import annotations

import argparse
import contextlib
import csv
import importlib.util
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("build_x3_pack", HERE / "build_x3_pack.py")
x3p = importlib.util.module_from_spec(_spec)
sys.modules["build_x3_pack"] = x3p
_spec.loader.exec_module(x3p)

STATE = "Lagos"
BAND, STRESS = 150, 45


def records(levels: dict[str, str]) -> tuple[dict[str, dict], dict[str, dict]]:
    hfr, grid3 = {}, {}
    with (x3p.DATA / f"hfr_{STATE.casefold()}.csv").open(encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            xy = None
            with contextlib.suppress(ValueError):
                xy = (float(r["lat"]), float(r["lon"]))
            hfr[r["id"]] = {"id": r["id"], "name": r["name"] or r["alternate_name"],
                            "lga": r["lga"], "xy": xy, "level": levels.get(r["id"], "")}
    with (x3p.DATA / "GRID3_NGA_health_facilities_v2.csv").open(encoding="utf-8-sig") as fh:
        for r in csv.DictReader(fh):
            if x3p.fold(r["state"]) != x3p.fold(STATE):
                continue
            xy = None
            with contextlib.suppress(ValueError):
                xy = (float(r["latitude"]), float(r["longitude"]))
            grid3[r["globalid"]] = {"id": r["globalid"], "name": r["facility_name"].strip(),
                                    "lga": r["lga"], "xy": xy, "code": r["nhfr_facility_code"],
                                    "level": r["facility_level"]}
    return grid3, hfr


NO_TWIN = {"id": "", "name": "", "lga": "", "xy": None}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--edges", type=Path, required=True)
    ap.add_argument("--work", type=Path, required=True)
    args = ap.parse_args()
    with x3p.HFR_NATIONAL.open(encoding="utf-8") as fh:
        levels = {f["properties"]["global_id"]: f["properties"].get("type") or ""
                  for f in json.load(fh)["features"]}
    grid3, hfr = records(levels)
    with args.edges.open(encoding="utf-8") as fh:
        held = [r for r in csv.DictReader(fh) if r["decision"] == "review"]
    held.sort(key=lambda r: x3p.salted(STATE, "band", r["grid3_id"], r["hfr_id"]))
    rows, used, seen_g = [], set(), set()
    for e in held:
        if len(rows) >= BAND:
            break
        gid, hid = e["grid3_id"].split(":", 1)[1], e["hfr_id"].split(":", 1)[1]
        if gid in seen_g or gid not in grid3 or hid not in hfr:
            continue
        g, h = grid3[gid], hfr[hid]
        own = hfr.get(gid, NO_TWIN)
        row = x3p.row(STATE, "review_band", g, h, own, x3p.cosine(g["name"], h["name"]))
        if not own["id"]:
            for k in ("grid3_own_hfr_id", "grid3_own_hfr_name", "grid3_own_hfr_lga"):
                row[k] = ""
        rows.append(row)
        seen_g.add(gid)
        used |= {gid, hid} | ({own["id"]} if own["id"] else set())
    x3p.PER_KIND = STRESS
    stress, counts = x3p.build(STATE, levels, used)
    rows += [r for r in stress if r["_kind"] != "drift"]
    kinds = {}
    for r in rows:
        kinds[r["decision_id"]] = r.pop("_kind")
    rows.sort(key=lambda r: r["decision_id"])
    out = args.work / STATE
    out.mkdir(parents=True, exist_ok=True)
    with (out / "adjudication_sample.csv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=x3p.FIELDS)
        w.writeheader()
        w.writerows(rows)
    (args.work / "kinds.json").write_text(json.dumps(kinds, indent=1, sort_keys=True) + "\n",
                                          encoding="utf-8")
    summary = {"review_band_held": len(held), "review_band": BAND,
               "lookalike": counts["lookalike"], "near_miss": counts["near_miss"],
               "rows": len(rows)}
    (args.work / "summary_pack.json").write_text(json.dumps(summary, indent=2) + "\n",
                                                 encoding="utf-8")
    print(json.dumps(summary))


if __name__ == "__main__":
    main()
