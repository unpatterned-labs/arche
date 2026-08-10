#!/usr/bin/env python
"""Nigeria health-facility -> Overture GERS bridge file + gap report.

Reconciles the HFR registry (per state, official MFL via HDX CC-BY) against
Overture Places (CDLA-Permissive, GERS stable IDs) using arche's gated
``compare_records``, blocked by H3. Emits ``data/bridge_<state>.csv`` and prints a
gap report — the artifact for the GRID3 conversation.

  arche corrects; Plehthore accumulates. This never stores a place; it emits a
  crosswalk edge {registry_id -> gers_id, confidence, decision}.

Run:  uv run python notebooks/build_bridge_file.py [State]   # default Kano
"""
from __future__ import annotations

import csv
import sys
from collections import defaultdict
from pathlib import Path

import duckdb
import h3

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fetch_facility_data as ffd  # noqa: E402
# `arche_mcp` never existed. The MCP `compare_records` handler this script was
# written against was lifted into arche-core as `resolve.reconcile` with the
# same signature, so the import was dead and this script raised ImportError.
from arche.resolve import reconcile  # noqa: E402

DATA = Path(__file__).resolve().parent.parent / "data"
OVERTURE_REL = "2026-07-22.0"
H3_RES = 7
# state -> (west, east, south, north) bounding box for the Overture pull.
STATE_BBOX = {"Kano": (7.6, 9.5, 10.4, 12.7)}
_HEALTH_RE = "hospital|health|clinic|pharmac|medical|doctor|dispensary|maternity"


def _cell(lat: float, lon: float) -> str:
    try:
        return h3.latlng_to_cell(lat, lon, H3_RES)
    except AttributeError:  # h3 v3
        return h3.geo_to_h3(lat, lon, H3_RES)


def _disk(cell: str, k: int = 1):
    try:
        return h3.grid_disk(cell, k)
    except AttributeError:
        return h3.k_ring(cell, k)


def load_hfr(state: str) -> list[dict]:
    path = DATA / f"hfr_{state.lower()}.csv"
    if not path.exists():
        ffd.DATA.mkdir(exist_ok=True)
        ffd.fetch_hfr(state)
    rows = []
    with open(path, encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            try:
                r["lat"], r["lon"] = float(r["lat"]), float(r["lon"])
            except (TypeError, ValueError):
                continue
            rows.append(r)
    return rows


def pull_overture(state: str) -> list[dict]:
    w, e, s, n = STATE_BBOX[state]
    con = duckdb.connect()
    con.execute("INSTALL httpfs; LOAD httpfs; SET s3_region='us-west-2';")
    q = f"""
    SELECT id AS gers_id, names.primary AS name, categories.primary AS category,
           (bbox.xmin + bbox.xmax) / 2 AS lon, (bbox.ymin + bbox.ymax) / 2 AS lat,
           confidence
    FROM read_parquet(
        's3://overturemaps-us-west-2/release/{OVERTURE_REL}/theme=places/type=place/*.parquet',
        hive_partitioning=1)
    WHERE bbox.xmin BETWEEN {w} AND {e} AND bbox.ymin BETWEEN {s} AND {n}
      AND names.primary IS NOT NULL
      AND regexp_matches(lower(coalesce(categories.primary, '')), '{_HEALTH_RE}')
    """
    cols = ("gers_id", "name", "category", "lon", "lat", "confidence")
    return [dict(zip(cols, row)) for row in con.execute(q).fetchall()]


def build(state: str) -> None:
    print(f"Loading HFR {state} (registry)...")
    hfr = load_hfr(state)
    print(f"  {len(hfr)} geolocated HFR facilities")
    print(f"Pulling Overture Places (health) for {state}...")
    overture = pull_overture(state)
    print(f"  {len(overture)} Overture health places with names + GERS")

    idx: dict[str, list[dict]] = defaultdict(list)
    for o in overture:
        idx[_cell(o["lat"], o["lon"])].append(o)

    comps = [
        {"field": "name", "kind": "name", "weight": 2.0},
        {"kind": "geo", "lat": "lat", "lon": "lon", "weight": 1.0},
    ]
    bridge: list[dict] = []
    matched = review = no_candidate = no_match = 0

    for f in hfr:
        c = _cell(f["lat"], f["lon"])
        cands: list[dict] = []
        for nb in _disk(c, 1):
            cands += idx.get(nb, [])
        if not cands:
            no_candidate += 1
            bridge.append({"hfr_id": f["id"], "hfr_name": f["name"], "gers_id": "",
                           "overture_name": "", "score": 0.0, "decision": "no_overture_place"})
            continue
        out = reconcile([f], cands, comps, threshold=0.75, id_field="gers_id")
        best = out["matches"][0] if out["matches"] else None
        if best is None:
            no_match += 1
            bridge.append({"hfr_id": f["id"], "hfr_name": f["name"], "gers_id": "",
                           "overture_name": "", "score": 0.0, "decision": "no_match"})
            continue
        o = next(x for x in cands if x["gers_id"] == best["b_id"])
        if best["decision"] == "match":
            matched += 1
        else:
            review += 1
        bridge.append({"hfr_id": f["id"], "hfr_name": f["name"],
                       "gers_id": o["gers_id"], "overture_name": o["name"],
                       "score": best["score"], "decision": best["decision"]})

    out_path = DATA / f"bridge_{state.lower()}.csv"
    with open(out_path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(bridge[0].keys()))
        w.writeheader()
        w.writerows(bridge)

    total = len(hfr)
    absent = no_candidate + no_match

    def pct(x: int) -> str:
        return f"{100 * x / total:.1f}%" if total else "-"

    print("\n" + "=" * 56)
    print(f"BRIDGE FILE + GAP REPORT — {state} (HFR -> Overture GERS)")
    print("=" * 56)
    print(f"  wrote {out_path.name} ({len(bridge)} rows)")
    print(f"  HFR facilities (registry)     : {total}")
    print(f"  Overture health places        : {len(overture)}")
    print(f"  confident GERS match          : {matched}  ({pct(matched)})")
    print(f"  needs review                  : {review}  ({pct(review)})")
    print(f"  ABSENT from Overture          : {absent}  ({pct(absent)})  <- the coverage gap")
    print("=" * 56)
    print("  => 'Overture is missing " + pct(absent) + " of the official Kano")
    print("     health registry' is the number that opens the GRID3 conversation.")


if __name__ == "__main__":
    state = sys.argv[1] if len(sys.argv) > 1 else "Kano"
    build(state)
