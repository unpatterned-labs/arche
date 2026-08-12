# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Fetch two independent lists of London hospitals for the UK place benchmark.

Why these two sources
---------------------
The Kano benchmark could not answer whether the place pack is *calibrated* to
Nigeria or *overfitted* to it, because its two sources shared lineage: OSM's
Kano health facilities descend from the same registry as GRID3. This pair is
chosen to avoid that and to change exactly one variable against Kano — the
country — while holding the entity type and the name structure constant.
``Bethlem Royal Hospital`` has the same shape as ``Karfi Health Post``: a
distinctive residual plus a generic type word.

* **Wikidata** (CC0) — curated from published references, per-item, by editors.
* **OpenStreetMap** (ODbL) — surveyed and crowd-mapped.

Different collection methods, different contributor populations, no shared
identifier. That is the claim; ``evaluate_independence`` in the benchmark script
is what actually tests it, and it runs before any matching.

Licensing
---------
Wikidata is CC0 and may enter a pack. **OpenStreetMap is ODbL and may not** —
it is benchmark evidence only, never a shipped asset, which is the same rule the
Kano work follows.

Usage
-----
    python data/scripts/fetch_london_hospitals.py
    python data/scripts/fetch_london_hospitals.py --refresh
"""

from __future__ import annotations

import argparse
import csv
import json
import time
import urllib.parse
import urllib.request
from pathlib import Path

_UA = "arche-dataops/0.3 (https://unpatterned.org; connect@unpatterned.org)"
_OUT = Path(__file__).resolve().parents[1] / "uk"
# Greater London, roughly the M25 envelope.
_BBOX = (51.28, -0.51, 51.70, 0.33)  # S, W, N, E

_WD_SPARQL = "https://query.wikidata.org/sparql"
_OVERPASS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
]


def fetch_wikidata() -> list[dict]:
    """Hospitals in the bbox with coordinates, via SPARQL."""
    s, w, n, e = _BBOX
    query = f"""
SELECT ?item ?itemLabel ?lat ?lon WHERE {{
  ?item wdt:P31/wdt:P279* wd:Q16917 .
  ?item wdt:P17 wd:Q145 .
  ?item p:P625/psv:P625 ?coord .
  ?coord wikibase:geoLatitude ?lat ; wikibase:geoLongitude ?lon .
  FILTER(?lat > {s} && ?lat < {n} && ?lon > {w} && ?lon < {e})
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en". }}
}}
"""
    url = f"{_WD_SPARQL}?format=json&query={urllib.parse.quote(query)}"
    req = urllib.request.Request(
        url, headers={"User-Agent": _UA, "Accept": "application/sparql-results+json"}
    )
    with urllib.request.urlopen(req, timeout=300) as resp:  # noqa: S310
        rows = json.loads(resp.read())["results"]["bindings"]
    out = []
    for r in rows:
        out.append({
            "wd_id": r["item"]["value"].rsplit("/", 1)[-1],
            "name": r["itemLabel"]["value"],
            "lat": round(float(r["lat"]["value"]), 6),
            "lon": round(float(r["lon"]["value"]), 6),
        })
    return out


def _overpass(query: str) -> list[dict] | None:
    """One Overpass query across mirrors, with backoff.

    Overpass returns 504 under load often enough that a single attempt makes
    the whole benchmark look unreachable when it is merely busy.
    """
    body = urllib.parse.urlencode({"data": query}).encode()
    for endpoint in _OVERPASS:
        for attempt in range(3):
            try:
                req = urllib.request.Request(
                    endpoint, data=body, headers={"User-Agent": _UA}
                )
                with urllib.request.urlopen(req, timeout=300) as resp:  # noqa: S310
                    return json.loads(resp.read()).get("elements", [])
            except Exception as exc:  # noqa: BLE001 — a busy mirror is not fatal
                print(f"    {endpoint.split('/')[2]} try {attempt + 1}: "
                      f"{type(exc).__name__}")
                time.sleep(6 * (attempt + 1))
    return None


def fetch_osm() -> list[dict]:
    """Hospitals in the bbox, tiled so a busy Overpass still completes."""
    s, w, n, e = _BBOX
    rows: list[dict] = []
    seen: set[int] = set()
    # 2x2 tiling keeps each query small enough to survive a loaded mirror.
    lat_mid, lon_mid = (s + n) / 2, (w + e) / 2
    tiles = [
        (s, w, lat_mid, lon_mid), (s, lon_mid, lat_mid, e),
        (lat_mid, w, n, lon_mid), (lat_mid, lon_mid, n, e),
    ]
    for i, (ts, tw, tn, te) in enumerate(tiles, 1):
        q = (
            f'[out:json][timeout:180];('
            f'node["amenity"="hospital"]({ts},{tw},{tn},{te});'
            f'way["amenity"="hospital"]({ts},{tw},{tn},{te});'
            f');out center;'
        )
        print(f"  tile {i}/4 ...", flush=True)
        els = _overpass(q)
        if els is None:
            print(f"  tile {i}: all mirrors failed — partial result")
            continue
        for el in els:
            if el["id"] in seen:
                continue
            seen.add(el["id"])
            tags = el.get("tags", {})
            centre = el if "lat" in el else el.get("center", {})
            if not centre.get("lat"):
                continue
            rows.append({
                "osm_id": el["id"],
                "osm_type": el["type"],
                "name": tags.get("name", ""),
                "operator": tags.get("operator", ""),
                "lat": round(float(centre["lat"]), 6),
                "lon": round(float(centre["lon"]), 6),
            })
        time.sleep(2)
    return rows


def _write(rows: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    print(f"  wrote {len(rows):>5} rows -> {path}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--refresh", action="store_true", help="re-fetch even if cached")
    args = ap.parse_args()

    wd_path, osm_path = _OUT / "wikidata_london_hospitals.csv", _OUT / "osm_london_hospitals.csv"

    if args.refresh or not wd_path.exists():
        print("Wikidata (CC0)")
        _write(fetch_wikidata(), wd_path)
    else:
        print(f"  cached {wd_path}")

    if args.refresh or not osm_path.exists():
        print("OpenStreetMap (ODbL — benchmark evidence only, never a pack)")
        rows = fetch_osm()
        if rows:
            _write(rows, osm_path)
        else:
            print("  Overpass unavailable; re-run when the mirrors recover")
            return 1
    else:
        print(f"  cached {osm_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
