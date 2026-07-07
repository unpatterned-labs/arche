#!/usr/bin/env python
"""Fetch health facilities for a Nigerian state from two INDEPENDENT public
sources for the arche facility-resolution spike.

  - HFR : Nigeria Health Facility Registry (official MFL), via the HDX CC-BY
          mirror. Compiled by eHealth Africa from GRID-3 / government projects.
  - OSM : OpenStreetMap health facilities, via the Overpass API (ODbL).
          Crowd-mapped, genuinely independent of the government registry.

Writes ``data/hfr_<state>.csv`` and ``data/osm_<state>.csv``. Public data.
Run:  uv run python notebooks/fetch_facility_data.py [State]   # default Kano
"""
from __future__ import annotations

import csv
import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data"
UA = {"User-Agent": "arche-facility-spike/0.1 (research; unpatterned.org)"}

HFR_URL = (
    "https://data.humdata.org/dataset/3b4a119a-309c-4d3f-900f-18a1f6ca2dfa/"
    "resource/5a3bdd13-3ada-4bf4-ac38-643390bc0562/download/nigeriahealthfacilities.json"
)
OVERPASS_URL = "https://overpass-api.de/api/interpreter"

# state -> ISO 3166-2 code. OSM is fetched INSIDE each state's admin boundary
# (resolved from the ISO code, admin_level=4), i.e. admin-polygon clipping — not
# a rectangular bbox — so the catch doesn't bleed into neighbouring states.
STATES = {"Kano": "NG-KN", "Edo": "NG-ED", "Ondo": "NG-ON"}


def _get(url: str, data: bytes | None = None, timeout: int = 240) -> bytes:
    req = urllib.request.Request(url, data=data, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310
        return r.read()


def _write(path: Path, rows: list[dict]) -> int:
    if not rows:
        print("WARN: no rows for", path.name)
        return 0
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print("wrote", path.name, len(rows), "rows")
    return len(rows)


def fetch_hfr(state: str) -> int:
    d = json.loads(_get(HFR_URL))
    rows = []
    for f in d.get("features", []):
        p = f.get("properties", {})
        if (p.get("state_name") or "").strip().lower() != state.lower():
            continue
        coords = (f.get("geometry") or {}).get("coordinates") or [None, None]
        rows.append({
            "id": p.get("global_id") or p.get("id"),
            "name": p.get("name") or "",
            "alternate_name": p.get("alternate_name") or "",
            "category": p.get("category") or "",
            "lga": p.get("lga_name") or "",
            "ward_code": p.get("ward_code") or "",
            "lon": coords[0], "lat": coords[1],
        })
    return _write(DATA / f"hfr_{state.lower()}.csv", rows)


def fetch_osm(state: str) -> int:
    # Admin-polygon clip: resolve the state's admin_level=4 boundary from its ISO
    # 3166-2 code to an area, then query only facilities inside it.
    tags = 'amenity"~"hospital|clinic|doctors|pharmacy'
    q = (
        "[out:json][timeout:220];"
        f'area["boundary"="administrative"]["admin_level"="4"]["ISO3166-2"="{STATES[state]}"]->.a;'
        "("
        f'node["{tags}"]["name"](area.a);'
        f'way["{tags}"]["name"](area.a);'
        f'node["healthcare"]["name"](area.a);'
        f'way["healthcare"]["name"](area.a);'
        ");out center;"
    )
    body = urllib.parse.urlencode({"data": q}).encode()
    d = json.loads(_get(OVERPASS_URL, data=body))
    rows = []
    for e in d.get("elements", []):
        t = e.get("tags", {})
        lat = e.get("lat") or (e.get("center") or {}).get("lat")
        lon = e.get("lon") or (e.get("center") or {}).get("lon")
        if lat is None or lon is None:
            continue
        rows.append({
            "id": f"{e.get('type')}/{e.get('id')}",
            "name": t.get("name") or "",
            "amenity": t.get("amenity") or "",
            "healthcare": t.get("healthcare") or "",
            "lga": t.get("addr:district") or t.get("addr:city") or "",
            "lat": lat, "lon": lon,
        })
    return _write(DATA / f"osm_{state.lower()}.csv", rows)


if __name__ == "__main__":
    state = sys.argv[1] if len(sys.argv) > 1 else "Kano"
    if state not in STATES:
        raise SystemExit(f"Unknown state {state!r}; known: {', '.join(STATES)}")
    DATA.mkdir(exist_ok=True)
    print(f"Fetching {state}: HFR (official, HDX CC-BY) + OSM (Overpass, ODbL)...")
    fetch_hfr(state)
    fetch_osm(state)
