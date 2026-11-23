#!/usr/bin/env python
"""Build a blind recheck of every far second-HFR-record pair marked same.

Definition fixed on 2026-11-23, before this pack was built: *same* means one
real facility, even if the HFR holds it twice. When the GRID3 facility already
has its own HFR record (its twin, sharing its source id), and the compared HFR
record is another one 2 km or more away tied to it only by the name, the answer
is *can't tell* unless something else on the card shows one facility.

The slice is chosen by that rule alone, never by what any model decided: every
development label (as X7 reads them) where the GRID3 facility's own HFR record
exists, the compared HFR record is a different one, the two points are 2 km or
more apart, and the pair is marked same. The earlier answer is not shown. This
script changes no label.

    ~/.cache/arche-scratch/e0/bin/python data/scripts/build_far_duplicate_recheck.py \\
        --work ~/.cache/arche/recheck2
    uv run --package arche-core python data/scripts/build_facility_adjudication_pack.py \\
        --sample <State>=~/.cache/arche/recheck2/<State>/adjudication_sample.csv ... \\
        --output data/review_packs/nigeria_facilities_far_duplicates_2026-11-23
"""

from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("x7_lagos_gate", HERE / "x7_lagos_gate.py")
x7 = importlib.util.module_from_spec(_spec)
sys.modules["x7_lagos_gate"] = x7
_spec.loader.exec_module(x7)
x6 = x7.x6
_spec = importlib.util.spec_from_file_location("build_recheck_pack", HERE / "build_recheck_pack.py")
rp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rp)

FAR_KM = 2.0


def source_of(decision_id: str) -> str:
    for key, path in x6.DEV.items():
        with path.open(encoding="utf-8") as fh:
            if any(r["decision_id"] == decision_id for r in csv.DictReader(fh)):
                return key
    return ""


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--work", type=Path, required=True)
    args = ap.parse_args()
    with x6.x3.HFR_NATIONAL.open(encoding="utf-8") as fh:
        hfr = {}
        for f in json.load(fh)["features"]:
            p, c = f["properties"], (f.get("geometry") or {}).get("coordinates") or [None, None]
            hfr[p["global_id"]] = {"name": p.get("name") or p.get("alternate_name") or "",
                                   "lga": p.get("lga_name") or "",
                                   "state": p.get("state_name") or "",
                                   "xy": (float(c[1]), float(c[0])) if c[0] is not None else None}
    gxy, _ = x6.coordinates()
    by_state: dict[str, list[dict]] = {}
    for r in x7.read_dev():
        gid, hid = r["grid3_id"].split(":", 1)[1], r["hfr_id"].split(":", 1)[1]
        if r["review_outcome"] != "same_entity" or gid == hid or gid not in hfr or hid not in hfr:
            continue
        a, b, own = gxy.get(gid), hfr[hid]["xy"], hfr[gid]
        if not (a and b) or x6.x1.haversine_km(a, b) < FAR_KM:
            continue
        row = {k: r.get(k, "") for k in rp.FIELDS}
        row.update({
            "grid3_own_hfr_id": "hfr:" + gid, "grid3_own_hfr_name": own["name"],
            "grid3_own_hfr_lga": own["lga"], "grid3_km_to_own_hfr": rp._km(a, own["xy"]),
            "grid3_own_hfr_plus_code": rp.plus_code(*own["xy"]) if own["xy"] else "",
            "hfr_name": hfr[hid]["name"] or r["hfr_name"],
            "hfr_km_from_grid3": rp._km(a, b), "distance_km": "", "score": "",
            "decision": "review", "source_pack": source_of(r["decision_id"]),
            **rp._where("grid3", a), **rp._where("hfr", b),
            "review_outcome": "", "reviewer": "", "reviewed_at": "", "reason": ""})
        if row.get("grid3_h3") and row.get("hfr_h3"):
            steps = rp.h3_steps(row["grid3_h3"], row["hfr_h3"])
            row["hfr_h3_steps"] = "" if steps is None else str(steps)
        by_state.setdefault(r["state"], []).append(row)
    for state, rows in by_state.items():
        out = args.work / state
        out.mkdir(parents=True, exist_ok=True)
        rows.sort(key=lambda r: r["decision_id"])
        with (out / "adjudication_sample.csv").open("w", encoding="utf-8", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=rp.FIELDS)
            w.writeheader()
            w.writerows(rows)
    print(json.dumps({s: len(v) for s, v in sorted(by_state.items())}))


if __name__ == "__main__":
    main()
