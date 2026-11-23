#!/usr/bin/env python
"""Build a recheck pack for same_entity marks that pair a facility with someone else's twin.

GRID3 v2 and the HFR share a source id (GRID3 ``globalid`` = HFR ``global_id``)
for most facilities. A same_entity mark is suspect when it pairs a GRID3
facility with an HFR record that is not its own while its own HFR record
exists: often a same-named facility in a neighbouring LGA. The review packs
never showed that twin, so the reviewer could not have seen it.

Each row is the pair as it was marked, with the GRID3 facility's own HFR record
shown beside it (``grid3_own_hfr_*``), both distances, and each point's
coordinates, Plus Code and H3 cell (``arche.addr.locate``). The earlier answer is
not shown. Outcomes go back to the reviewer; this script changes no label.

    uv run --package arche-core python data/scripts/build_recheck_pack.py \\
        --work ~/.cache/arche/recheck
    uv run --package arche-core python data/scripts/build_facility_adjudication_pack.py \\
        --sample Edo=~/.cache/arche/recheck/Edo/adjudication_sample.csv ... \\
        --output data/review_packs/nigeria_facilities_recheck_2026-11-22
"""

from __future__ import annotations

import argparse
import contextlib
import csv
import json
import math
from pathlib import Path

from arche.addr.locate import h3_cell, h3_steps, plus_code

DATA = Path(__file__).resolve().parents[1]
PACKS = {
    "2026-08-19": DATA / "review_packs" / "nigeria_facilities_2026-08-19"
                  / "adjudication_pack_reviewed.csv",
    "x1_2026-11-21": DATA / "review_packs" / "nigeria_facilities_x1_2026-11-21"
                     / "adjudication_pack_reviewed.csv",
}
FIELDS = [
    "decision_id", "decision", "score", "distinctive_max", "distance_km",
    "grid3_id", "grid3_code", "grid3_name", "grid3_admin_path",
    "grid3_lat", "grid3_lon", "grid3_plus_code", "grid3_h3",
    "grid3_own_hfr_id", "grid3_own_hfr_name", "grid3_own_hfr_lga", "grid3_km_to_own_hfr",
    "grid3_own_hfr_plus_code",
    "hfr_id", "hfr_code", "hfr_name", "hfr_admin_path",
    "hfr_lat", "hfr_lon", "hfr_plus_code", "hfr_h3", "hfr_km_from_grid3", "hfr_h3_steps",
    "source_pack", "evidence", "review_outcome", "reviewer", "reviewed_at", "reason",
]


def _km(a, b) -> str:
    if not a or not b:
        return ""
    la1, lo1, la2, lo2 = map(math.radians, (*a, *b))
    h = (math.sin((la2 - la1) / 2) ** 2
         + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2)
    return f"{12742.0 * math.asin(math.sqrt(h)):.2f}"


def _where(prefix: str, xy) -> dict[str, str]:
    if not xy:
        return {}
    return {f"{prefix}_lat": f"{xy[0]:.6f}", f"{prefix}_lon": f"{xy[1]:.6f}",
            f"{prefix}_plus_code": plus_code(*xy), f"{prefix}_h3": h3_cell(*xy)}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--work", type=Path, required=True)
    args = ap.parse_args()
    hfr, hfr_xy, grid3_xy = {}, {}, {}
    for state in ("edo", "kano", "ondo"):
        with (DATA / f"hfr_{state}.csv").open(encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                hfr[r["id"]] = r
                with contextlib.suppress(ValueError):
                    hfr_xy[r["id"]] = (float(r["lat"]), float(r["lon"]))
    with (DATA / "GRID3_NGA_health_facilities_v2.csv").open(encoding="utf-8-sig") as fh:
        for r in csv.DictReader(fh):
            with contextlib.suppress(ValueError):
                grid3_xy[r["globalid"]] = (float(r["latitude"]), float(r["longitude"]))
    by_state: dict[str, list[dict]] = {}
    counts: dict[str, int] = {}
    for label, path in PACKS.items():
        with path.open(encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                if r["review_outcome"] != "same_entity":
                    continue
                gid, hid = r["grid3_id"].split(":", 1)[1], r["hfr_id"].split(":", 1)[1]
                own = hfr.get(gid)
                if gid == hid or own is None:
                    continue
                row = {k: r.get(k, "") for k in FIELDS}
                row.update({
                    "grid3_own_hfr_id": "hfr:" + gid, "grid3_own_hfr_name": own["name"],
                    "grid3_own_hfr_lga": own["lga"],
                    "grid3_km_to_own_hfr": _km(grid3_xy.get(gid), hfr_xy.get(gid)),
                    "hfr_km_from_grid3": _km(grid3_xy.get(gid), hfr_xy.get(hid)),
                    "source_pack": label, "distance_km": "",
                    **_where("grid3", grid3_xy.get(gid)), **_where("hfr", hfr_xy.get(hid)),
                    "grid3_own_hfr_plus_code": (plus_code(*hfr_xy[gid]) if gid in hfr_xy
                                                else ""),
                    "review_outcome": "", "reviewer": "", "reviewed_at": "", "reason": "",
                })
                if row.get("grid3_h3") and row.get("hfr_h3"):
                    steps = h3_steps(row["grid3_h3"], row["hfr_h3"])
                    row["hfr_h3_steps"] = "" if steps is None else str(steps)
                by_state.setdefault(r["state"], []).append(row)
                counts[label] = counts.get(label, 0) + 1
    for state, rows in by_state.items():
        out = args.work / state
        out.mkdir(parents=True, exist_ok=True)
        rows.sort(key=lambda r: r["decision_id"])
        with (out / "adjudication_sample.csv").open("w", encoding="utf-8", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=FIELDS)
            w.writeheader()
            w.writerows(rows)
    print(json.dumps({"by_source_pack": counts,
                      "by_state": {s: len(v) for s, v in sorted(by_state.items())}}))


if __name__ == "__main__":
    main()
