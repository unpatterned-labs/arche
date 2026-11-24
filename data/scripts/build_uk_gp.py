#!/usr/bin/env python
"""Candidate edges between CQC GP locations and ODS GP practices, per English region.

Inputs (Open Government Licence, read from a local folder, never redistributed):

* ``hsca_active_locations.csv``: CQC's HSCA active locations sheet. The left side
  is every location whose primary inspection category is "GP Practices".
* ``epraccur.csv``: the ODS prescribing cost centres report. The right side is
  every row whose status is not ``INACTIVE`` (closed).
* ``postcodes.csv``: postcode -> lat, lon, local authority district code, region
  code, from the ONS Postcode Directory (built by ``--postcodes``). Live
  postcodes win over terminated ones.
* the ONSPD documents with LAD and region names.

Both sides get admin1 = region name and admin2 = local authority name from their
own postcode, so the two lists use one naming. Names are upper-cased on both
sides: ODS writes them in capitals, and the engine's Splink recipe trains on exact
name agreement, which is case-sensitive (with mixed case against capitals it
finds no training pairs and stops). Coordinates: CQC's own
latitude/longitude, else the postcode's; ODS has only the postcode's. A record
whose postcode is unknown has no admin path and no point.

Each region goes through ``arche.resolve.reconcile(entity="place")`` as it
ships, like a Nigerian state. Edges use the column names of
``evaluate_facility_master.py`` with ``cqc_``/``ods_`` prefixes, plus
``cqc_ods_code``. That is the CQC location's own ODS code, kept for scoring
only; the engine never sees it.

    uv run --package arche-core python data/scripts/build_uk_gp.py --postcodes
    uv run --package arche-core python data/scripts/build_uk_gp.py
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import re
import zipfile
from collections import Counter
from pathlib import Path
from typing import Any

from arche.resolve import reconcile

UK = Path.home() / ".cache" / "arche" / "uk"
OUT = UK / "x11"
DOCS = UK / "onspd" / "Documents"
LAD_NAMES = DOCS / "LAD Local Authority District names and codes UK as at 04_25.csv"
RGN_NAMES = DOCS / "RGN Region names and codes EN as at 05_25.csv"


def pc(v: str | None) -> str:
    return re.sub(r"\s+", "", (v or "")).upper()


def sha(p: Path) -> str:
    return "sha256:" + hashlib.sha256(p.read_bytes()).hexdigest()


def build_postcodes() -> None:
    out: dict[str, tuple] = {}
    with zipfile.ZipFile(UK / "ONSPD_AUG_2026.zip") as z, \
            z.open("Data/ONSPD_AUG_2026_UK.csv") as fh:
        for r in csv.DictReader(io.TextIOWrapper(fh, encoding="utf-8")):
            k = pc(r["pcds"])
            if k in out and r["doterm"]:
                continue
            out[k] = (r["lat"], r["long"], r["lad26cd"], r["rgn26cd"],
                      "terminated" if r["doterm"] else "live")
    with (UK / "postcodes.csv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["pc", "lat", "lon", "lad", "rgn", "status"])
        for k, v in out.items():
            w.writerow([k, *v])
    print(f"{len(out)} postcodes")


def _names(path: Path) -> dict[str, str]:
    with path.open(encoding="utf-8-sig") as fh:
        rows = list(csv.reader(fh))
    return {r[0]: r[1] for r in rows[1:]}


def _f(v: str | None) -> float | None:
    try:
        x = float(v or "")
    except ValueError:
        return None
    return x if -180 <= x <= 180 and x != 0 else None


def load() -> tuple[list[dict[str, Any]], list[dict[str, Any]], Counter]:
    lad, rgn = _names(LAD_NAMES), _names(RGN_NAMES)
    post = {}
    with (UK / "postcodes.csv").open(encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            post[r["pc"]] = r
    c: Counter = Counter()

    def place(code: str) -> tuple[str, dict[str, str], tuple[float | None, float | None]]:
        p = post.get(pc(code))
        if not p or not p["rgn"].startswith("E12"):
            return "", {}, (None, None)
        return p["rgn"], {"admin1": rgn[p["rgn"]], "admin2": lad.get(p["lad"], p["lad"])}, \
            (_f(p["lat"]), _f(p["lon"]))

    left = []
    with (UK / "hsca_active_locations.csv").open(encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            if r["Location Primary Inspection Category"] != "GP Practices":
                continue
            region, path, (lat, lon) = place(r["Location Postal Code"])
            own = (_f(r["Location Latitude"]), _f(r["Location Longitude"]))
            if own[0] is not None and own[1] is not None:
                lat, lon = own
            c["cqc_gp"] += 1
            if not region:
                c["cqc_no_region"] += 1
                continue
            left.append({"id": f"cqc:{r['Location ID']}",
                         "name": r["Location Name"].strip().upper(),
                         "lat": lat, "lon": lon, "admin_path": path, "region": region,
                         "source_code": (r["Location ODS Code"] or "").strip(),
                         "source_name": "CQC"})
    right = []
    with (UK / "epraccur.csv").open(encoding="latin-1") as fh:
        for r in csv.reader(fh):
            if r[12] == "INACTIVE":
                continue
            c["ods"] += 1
            region, path, (lat, lon) = place(r[9])
            if not region:
                c["ods_no_region"] += 1
                continue
            right.append({"id": f"ods:{r[0]}", "name": r[1].strip().upper(), "lat": lat, "lon": lon,
                          "admin_path": path, "region": region, "source_code": r[0],
                          "source_name": "ODS"})
    return left, right, c


def edges(result: dict[str, Any], left: list[dict], right: list[dict]) -> list[dict[str, Any]]:
    by_l = {r["id"]: r for r in left}
    by_r = {r["id"]: r for r in right}
    rows = []
    for e in result["matches"]:
        a, b = by_l[e["a_id"]], by_r[e["b_id"]]
        rows.append({"decision_id": e["decision_id"], "decision": e["decision"],
                     "score": e["score"], "distinctive_max": e["distinctive_max"],
                     "distance_km": e["evidence"].get("distance_km", ""),
                     "cqc_id": a["id"], "cqc_name": a["name"],
                     "cqc_admin_path": json.dumps(a["admin_path"], sort_keys=True),
                     "cqc_lat": a["lat"], "cqc_lon": a["lon"],
                     "ods_id": b["id"], "ods_name": b["name"],
                     "ods_admin_path": json.dumps(b["admin_path"], sort_keys=True),
                     "ods_lat": b["lat"], "ods_lon": b["lon"],
                     "cqc_ods_code": a["source_code"]})
    return rows


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--postcodes", action="store_true", help="build postcodes.csv from ONSPD")
    args = ap.parse_args()
    if args.postcodes:
        build_postcodes()
        return
    left, right, counts = load()
    summary: dict[str, Any] = {"schema": "arche.uk_gp_edges.v1", "records": dict(counts),
                               "inputs": {p: sha(UK / p) for p in
                                          ("hsca_active_locations.csv", "epraccur.csv",
                                           "postcodes.csv")},
                               "regions": {}}
    for region in sorted({r["region"] for r in left}):
        lr = [{k: v for k, v in r.items() if k != "region"} for r in left if r["region"] == region]
        rr = [{k: v for k, v in r.items() if k != "region"} for r in right if r["region"] == region]
        result = reconcile(lr, rr, entity="place")
        rows = edges(result, lr, rr)
        d = OUT / region
        d.mkdir(parents=True, exist_ok=True)
        with (d / "candidate_edges.csv").open("w", encoding="utf-8", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)
        name = json.loads(rows[0]["cqc_admin_path"])["admin1"]
        summary["regions"][region] = {"name": name, "cqc": len(lr), "ods": len(rr),
                                      "edges": len(rows),
                                      "decisions": dict(Counter(r["decision"] for r in rows)),
                                      "pins": result["pins"]}
        print(region, name, summary["regions"][region]["decisions"], flush=True)
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n",
                                      encoding="utf-8")
    print(json.dumps(summary["records"]))


if __name__ == "__main__":
    main()
