#!/usr/bin/env python
# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0
"""Stage an England schools crosswalk: GIAS against OpenStreetMap.

    python data/scripts/fetch_england_schools.py --la Leeds

What this stages, and why the truth set is honest
--------------------------------------------------
**GIAS** (Get Information About Schools) is the Department for Education's
register of educational establishments. It is the authority: every open school
in England has a **URN**, and GIAS is where it is issued.

    https://get-information-schools.service.gov.uk/

**OpenStreetMap** is surveyed and crowd-mapped, and a large share of English
school features carry `ref:edubase`, which is an editor asserting *this mapped
school is that URN*.

That tag is the truth label, and it is used the same way the London hospital
lane uses `wikidata=`: as the answer, never as an input. The matcher sees
**name and coordinates only**. If it saw the URN it would be performing a key
join and measuring nothing.

Coverage is high enough to be worth measuring. In Leeds, 286 of 311 OSM school
features carry the tag.

Three identifiers, and they do not mean the same thing
-------------------------------------------------------
GIAS carries all three, and conflating them is the first mistake available:

* **URN** identifies an *establishment*. Reissued when a school legally becomes
  a new establishment, which is what an academy conversion usually is.
* **UKPRN** identifies a *provider* in the UK Register of Learning Providers.
  Sparsely populated for schools; mostly present for colleges and academies.
* **LAESTAB** is the composite of `LA (code)` and `EstablishmentNumber`, the
  local-authority-scoped identifier that predates URN and still appears in
  funding and census returns.

All three are retained in the staged output so a later lane can ask which one
the two sides actually agreed on.

Licence
-------
GIAS is Crown copyright under the Open Government Licence. OSM is ODbL, which
is why it may be **benchmark evidence only** and can never enter a shipped
pack: share-alike would propagate into every derived artefact.

Both are fetched into `data/_cache/`, which is gitignored. Nothing this script
writes is committed.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import math
import sys
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
CACHE = _REPO / "data" / "_cache"
OUT = CACHE / "schools"
GIAS_URL = ("https://ea-edubase-api-prod.azurewebsites.net/edubase/downloads/"
            "public/edubasealldata{date}.csv")
OVERPASS = "https://overpass-api.de/api/interpreter"

# ISO 3166-2 subdivision codes for the local authorities this script knows how
# to pull from OSM. Extend as needed; the GIAS side keys on `LA (name)`.
LA_AREA = {"Leeds": "GB-LDS", "Birmingham": "GB-BIR", "Manchester": "GB-MAN",
           "Bristol, City of": "GB-BST", "Sheffield": "GB-SHF"}


# --- OSGB36 easting/northing -> WGS84 lat/lon --------------------------------
# GIAS publishes British National Grid, arche's geo comparator wants WGS84.
# Airy 1830 inverse transverse Mercator, then a Helmert transform onto WGS84.
# Accurate to a few metres, which is far inside the noise on a school centroid.

def _bng_to_wgs84(easting: float, northing: float) -> tuple[float, float]:
    a, b = 6377563.396, 6356256.909          # Airy 1830
    f0 = 0.9996012717
    lat0, lon0 = math.radians(49.0), math.radians(-2.0)
    n0, e0 = -100000.0, 400000.0
    e2 = 1 - (b * b) / (a * a)
    n = (a - b) / (a + b)

    lat = lat0
    m = 0.0
    while abs(northing - n0 - m) >= 0.00001:
        lat += (northing - n0 - m) / (a * f0)
        ma = (1 + n + 1.25 * n**2 + 1.25 * n**3) * (lat - lat0)
        mb = (3 * n + 3 * n**2 + 2.625 * n**3) * math.sin(lat - lat0) * math.cos(lat + lat0)
        mc = (1.875 * n**2 + 1.875 * n**3) * math.sin(2 * (lat - lat0)) * math.cos(2 * (lat + lat0))
        md = (35 / 24) * n**3 * math.sin(3 * (lat - lat0)) * math.cos(3 * (lat + lat0))
        m = b * f0 * (ma - mb + mc - md)

    sl = math.sin(lat)
    nu = a * f0 / math.sqrt(1 - e2 * sl * sl)
    rho = a * f0 * (1 - e2) / (1 - e2 * sl * sl) ** 1.5
    eta2 = nu / rho - 1
    tl = math.tan(lat)
    t2, t4, t6 = tl**2, tl**4, tl**6
    sec = 1 / math.cos(lat)
    vii = tl / (2 * rho * nu)
    viii = tl / (24 * rho * nu**3) * (5 + 3 * t2 + eta2 - 9 * t2 * eta2)
    ix = tl / (720 * rho * nu**5) * (61 + 90 * t2 + 45 * t4)
    x = sec / nu
    xi = sec / (6 * nu**3) * (nu / rho + 2 * t2)
    xii = sec / (120 * nu**5) * (5 + 28 * t2 + 24 * t4)
    xiia = sec / (5040 * nu**7) * (61 + 662 * t2 + 1320 * t4 + 720 * t6)
    de = easting - e0

    lat_o = lat - vii * de**2 + viii * de**4 - ix * de**6
    lon_o = lon0 + x * de - xi * de**3 + xii * de**5 - xiia * de**7

    # OSGB36 -> WGS84 (Helmert, seven parameters)
    return _helmert(lat_o, lon_o, a, b)


def _helmert(lat: float, lon: float, a: float, b: float) -> tuple[float, float]:
    tx, ty, tz = 446.448, -125.157, 542.060
    rx, ry, rz = (math.radians(v / 3600) for v in (0.1502, 0.2470, 0.8421))
    s = 20.4894e-6
    e2 = 1 - (b * b) / (a * a)
    nu = a / math.sqrt(1 - e2 * math.sin(lat) ** 2)
    x1 = nu * math.cos(lat) * math.cos(lon)
    y1 = nu * math.cos(lat) * math.sin(lon)
    z1 = (1 - e2) * nu * math.sin(lat)
    x2 = tx + x1 * (1 + s) - y1 * rz + z1 * ry
    y2 = ty + x1 * rz + y1 * (1 + s) - z1 * rx
    z2 = tz - x1 * ry + y1 * rx + z1 * (1 + s)

    a2, b2 = 6378137.000, 6356752.3141     # WGS84
    e2b = 1 - (b2 * b2) / (a2 * a2)
    p = math.sqrt(x2**2 + y2**2)
    lat2, prev = math.atan2(z2, p * (1 - e2b)), 0.0
    while abs(lat2 - prev) > 1e-12:
        prev = lat2
        nu2 = a2 / math.sqrt(1 - e2b * math.sin(lat2) ** 2)
        lat2 = math.atan2(z2 + e2b * nu2 * math.sin(lat2), p)
    return math.degrees(lat2), math.degrees(math.atan2(y2, x2))


# --- sources -----------------------------------------------------------------

def _gias_rows(when: str) -> list[dict]:
    CACHE.mkdir(parents=True, exist_ok=True)
    (CACHE / "gias").mkdir(exist_ok=True)
    path = CACHE / "gias" / f"edubasealldata{when}.csv"
    legacy = CACHE / "gias" / "gias.csv"
    if not path.exists() and legacy.exists():
        path = legacy
    if not path.exists():
        url = GIAS_URL.format(date=when)
        print(f"  downloading GIAS {when} (~65 MB)", flush=True)
        req = urllib.request.Request(url, headers={"User-Agent": "arche-dataops/0.4"})
        with urllib.request.urlopen(req, timeout=600) as r:  # noqa: S310
            path.write_bytes(r.read())
    return list(csv.DictReader(io.StringIO(path.read_text(encoding="latin-1"))))


def _osm_schools(area: str) -> list[dict]:
    (CACHE / "osm").mkdir(parents=True, exist_ok=True)
    path = CACHE / "osm" / f"schools_{area}.json"
    if not path.exists():
        q = (f'[out:json][timeout:180];area["ISO3166-2"="{area}"]->.a;'
             '(node["amenity"="school"](area.a);way["amenity"="school"](area.a););'
             'out tags center;')
        print(f"  querying Overpass for {area}", flush=True)
        req = urllib.request.Request(
            OVERPASS, data=urllib.parse.urlencode({"data": q}).encode(),
            headers={"User-Agent": "arche-dataops/0.4"})
        with urllib.request.urlopen(req, timeout=300) as r:  # noqa: S310
            path.write_bytes(r.read())
    return json.loads(path.read_text(encoding="utf-8"))["elements"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--la", default="Leeds", choices=sorted(LA_AREA))
    ap.add_argument("--date", default=date.today().strftime("%Y%m%d"),
                    help="GIAS export date, YYYYMMDD. Pin it for a repeatable run.")
    args = ap.parse_args()

    rows = _gias_rows(args.date)
    gias = []
    for r in rows:
        if r["LA (name)"] != args.la or r["EstablishmentStatus (name)"] != "Open":
            continue
        if not (r["Easting"].strip() and r["Northing"].strip()):
            continue
        lat, lon = _bng_to_wgs84(float(r["Easting"]), float(r["Northing"]))
        gias.append({
            "urn": r["URN"],
            "name": r["EstablishmentName"],
            "lat": f"{lat:.6f}", "lon": f"{lon:.6f}",
            "postcode": r["Postcode"],
            "laestab": f'{r["LA (code)"]}/{r["EstablishmentNumber"]}',
            "ukprn": r["UKPRN"],
            "phase": r["PhaseOfEducation (name)"],
            "type": r["TypeOfEstablishment (name)"],
        })

    els = _osm_schools(LA_AREA[args.la])
    osm, truth = [], []
    for e in els:
        t = e.get("tags", {})
        name = (t.get("name") or "").strip()
        lat = e.get("lat") or (e.get("center") or {}).get("lat")
        lon = e.get("lon") or (e.get("center") or {}).get("lon")
        if not name or lat is None:
            continue
        oid = f'{e["type"]}/{e["id"]}'
        osm.append({"osm_id": oid, "name": name,
                    "lat": f"{lat:.6f}", "lon": f"{lon:.6f}",
                    "ukprn": t.get("ref:GB:ukprn", ""),
                    "operator": t.get("operator", "")})
        urn = (t.get("ref:edubase") or "").strip()
        if urn:
            truth.append({"osm_id": oid, "urn": urn})

    OUT.mkdir(parents=True, exist_ok=True)
    for name, recs, cols in (
        ("gias.csv", gias, ["urn", "name", "lat", "lon", "postcode", "laestab", "ukprn", "phase", "type"]),
        ("osm.csv", osm, ["osm_id", "name", "lat", "lon", "ukprn", "operator"]),
        ("truth_pairs.csv", truth, ["osm_id", "urn"]),
    ):
        with (OUT / name).open("w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=cols)
            w.writeheader(); w.writerows(recs)

    known = {g["urn"] for g in gias}
    usable = [t for t in truth if t["urn"] in known]
    (OUT / "manifest.json").write_text(json.dumps({
        "local_authority": args.la, "gias_export": args.date,
        "gias_open": len(gias), "osm_features": len(osm),
        "osm_with_urn_tag": len(truth),
        "truth_pairs_resolving_into_gias": len(usable),
    }, indent=2), encoding="utf-8")

    print(f"\n  {args.la}, GIAS export {args.date}")
    print(f"    GIAS open establishments      {len(gias):>5}")
    print(f"    OSM school features (named)   {len(osm):>5}")
    print(f"    ... carrying ref:edubase      {len(truth):>5}"
          f"  ({100*len(truth)/len(osm):.0f}%)")
    print(f"    truth pairs resolving         {len(usable):>5}")
    print(f"\n  -> {OUT}  (gitignored, not committed)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
