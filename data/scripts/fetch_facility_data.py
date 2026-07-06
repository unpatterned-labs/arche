#!/usr/bin/env python
"""Fetch Kano-state health facilities from two INDEPENDENT public sources for
the arche facility-resolution spike.

  - HFR : Nigeria Health Facility Registry (official MFL), via the HDX CC-BY
          mirror. Compiled by eHealth Africa from GRID-3 / government projects.
  - OSM : OpenStreetMap health facilities, via the Overpass API (ODbL).
          Crowd-mapped, genuinely independent of the government registry.

Writes ``data/hfr_kano.csv`` and ``data/osm_kano.csv``. Public data, re-runnable.
Run:  uv run python notebooks/fetch_facility_data.py
"""
from __future__ import annotations

import csv
import json
import urllib.parse
import urllib.request
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data"
STATE = "Kano"
UA = {"User-Agent": "arche-facility-spike/0.1 (research; unpatterned.org)"}

HFR_URL = (
    "https://data.humdata.org/dataset/3b4a119a-309c-4d3f-900f-18a1f6ca2dfa/"
    "resource/5a3bdd13-3ada-4bf4-ac38-643390bc0562/download/nigeriahealthfacilities.json"
)
OVERPASS_URL = "https://overpass-api.de/api/interpreter"
# Kano state bounding box (approx): south, west, north, east
KANO_BBOX = "10.3,7.6,12.7,9.5"


def _get(url: str, data: bytes | None = None, timeout: int = 180) -> bytes:
    req = urllib.request.Request(url, data=data, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310
        return r.read()


def _write(path: Path, rows: list[dict]) -> int:
    if not rows:
        print("WARN: no rows for", path)
        return 0
    cols = list(rows[0].keys())
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)
    print("wrote", path.name, len(rows), "rows")
    return len(rows)


def fetch_hfr() -> int:
    """Official registry — filter the national GeoJSON to Kano state."""
    d = json.loads(_get(HFR_URL, timeout=240))
    rows = []
    for f in d.get("features", []):
        p = f.get("properties", {})
        if (p.get("state_name") or "").strip().lower() != STATE.lower():
            continue
        coords = (f.get("geometry") or {}).get("coordinates") or [None, None]
        rows.append(
            {
                "id": p.get("global_id") or p.get("id"),
                "name": p.get("name") or "",
                "alternate_name": p.get("alternate_name") or "",
                "category": p.get("category") or "",
                "lga": p.get("lga_name") or "",
                "ward_code": p.get("ward_code") or "",
                "lon": coords[0],
                "lat": coords[1],
            }
        )
    return _write(DATA / "hfr_kano.csv", rows)


def fetch_osm() -> int:
    """OpenStreetMap health facilities in the Kano state bbox (Overpass)."""
    tags = 'amenity"~"hospital|clinic|doctors|pharmacy'
    q = (
        "[out:json][timeout:200];("
        f'node["{tags}"]["name"]({KANO_BBOX});'
        f'way["{tags}"]["name"]({KANO_BBOX});'
        f'node["healthcare"]["name"]({KANO_BBOX});'
        f'way["healthcare"]["name"]({KANO_BBOX});'
        ");out center;"
    )
    body = urllib.parse.urlencode({"data": q}).encode()
    d = json.loads(_get(OVERPASS_URL, data=body, timeout=220))
    rows = []
    for e in d.get("elements", []):
        t = e.get("tags", {})
        lat = e.get("lat") or (e.get("center") or {}).get("lat")
        lon = e.get("lon") or (e.get("center") or {}).get("lon")
        if lat is None or lon is None:
            continue
        rows.append(
            {
                "id": f"{e.get('type')}/{e.get('id')}",
                "name": t.get("name") or "",
                "amenity": t.get("amenity") or "",
                "healthcare": t.get("healthcare") or "",
                "lga": t.get("addr:district") or t.get("addr:city") or "",
                "lat": lat,
                "lon": lon,
            }
        )
    return _write(DATA / "osm_kano.csv", rows)


if __name__ == "__main__":
    DATA.mkdir(exist_ok=True)
    print("Fetching HFR (official registry, HDX CC-BY mirror)...")
    fetch_hfr()
    print("Fetching OSM (Overpass, ODbL)...")
    fetch_osm()
