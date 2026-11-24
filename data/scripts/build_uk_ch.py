#!/usr/bin/env python
"""Candidate edges between CQC providers and Companies House, per postcode district.

Inputs (Open Government Licence, local, never redistributed):

* CQC HSCA active locations (2026-11-02): one record per provider whose
  ownership type is "Organisation" and that records a Companies House number.
  Name, provider street address, address line 2, city and postcode, with the
  provider's own latitude and longitude. The company number is kept for scoring
  only; the engine never sees it.
* Companies House BasicCompanyData (2026-11-01): every company in the file. Name,
  registered office (address lines 1 and 2, post town, postcode), with the
  postcode's centroid from ONSPD. The company number is kept for scoring only.

Blocking: a provider is compared with the companies whose registered office is in
its postcode district (the outward code, e.g. ``DN4``). A provider whose company
is registered elsewhere (often an accountant's office) cannot be found; it is
counted as unreachable.

First pass, per district: a company is a candidate only if its name shares a
distinctive word with some provider's name in the district (words of three or
more letters, folded, outside ``COMMON``). A twin that shares no such word is
unreachable too. Then each district runs through
``reconcile(entity="organisation")`` as shipped.

    uv run --package arche-core python data/scripts/build_uk_ch.py --extract
    uv run --package arche-core python data/scripts/build_uk_ch.py --build
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import re
import time
import zipfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

UK = Path.home() / ".cache" / "arche" / "uk"
CH = Path.home() / ".cache" / "arche" / "companies_house"
ZIP = CH / "raw" / "BasicCompanyDataAsOneFile-2026-11-01.zip"
OUT = UK / "x16"


def pc(v: str | None) -> str:
    return re.sub(r"\s+", "", (v or "")).upper()


def district(v: str | None) -> str:
    p = pc(v)
    return p[:-3] if len(p) >= 5 else ""


def number(v: str | None) -> str:
    v = (v or "").strip().upper()
    return v.zfill(8) if v.isdigit() else v


def joined(*parts: str | None) -> str:
    return ", ".join(p.strip() for p in parts if p and p.strip())


COMMON = frozenset([
    "the", "and", "of", "for", "ltd", "limited", "llp", "plc", "company", "co", "uk",
    "services", "service", "care", "carers", "caring", "group", "home", "homes", "health",
    "healthcare", "medical", "practice", "surgery", "centre", "center", "trust", "community",
    "support", "supported", "living", "solutions", "agency", "associates", "partners",
    "partnership", "holdings", "management", "enterprises", "international", "nursing",
    "residential", "dental", "clinic",
])


def words(name: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", name.casefold())
            if len(w) >= 3 and w not in COMMON}


def providers() -> list[dict[str, Any]]:
    seen: dict[str, dict] = {}
    with (UK / "hsca_active_locations.csv").open(encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            if r["Provider ID"] in seen or r["Provider Ownership Type"] != "Organisation":
                continue
            num = number(r["Provider Companies House Number"])
            if not num:
                continue
            lat, lon = r["Provider Latitude"], r["Provider Longitude"]
            seen[r["Provider ID"]] = {
                "id": f"cqc:{r['Provider ID']}", "name": r["Provider Name"].strip(),
                "address": joined(r["Provider Street Address"], r["Provider Address Line 2"],
                                  r["Provider City"], r["Provider Postal Code"]),
                "lat": float(lat) if lat else None, "lon": float(lon) if lon else None,
                "district": district(r["Provider Postal Code"]), "company_number": num}
    return list(seen.values())


def extract() -> None:
    """Keep the companies registered in a district that holds a CQC provider."""
    left = providers()
    wanted = {r["district"] for r in left if r["district"]}
    post = {}
    with (UK / "postcodes.csv").open(encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            if r["pc"][:-3] in wanted:
                post[r["pc"]] = (r["lat"], r["lon"])
    c: Counter = Counter()
    out = CH / "ch_in_cqc_districts.csv"
    with zipfile.ZipFile(ZIP) as z, z.open(z.namelist()[0]) as raw, \
            out.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["company_number", "name", "address", "district", "lat", "lon"])
        reader = csv.reader(io.TextIOWrapper(raw, encoding="utf-8"))
        header = [h.strip() for h in next(reader)]
        ix = {h: i for i, h in enumerate(header)}
        for r in reader:
            c["companies"] += 1
            if len(r) < len(header):
                c["short_rows"] += 1
                continue
            d = district(r[ix["RegAddress.PostCode"]])
            if d not in wanted:
                continue
            ll = post.get(pc(r[ix["RegAddress.PostCode"]]), ("", ""))
            w.writerow([number(r[ix["CompanyNumber"]]), r[ix["CompanyName"]].strip(),
                        joined(r[ix["RegAddress.AddressLine1"]], r[ix["RegAddress.AddressLine2"]],
                               r[ix["RegAddress.PostTown"]], r[ix["RegAddress.PostCode"]]),
                        d, *ll])
            c["kept"] += 1
    print(json.dumps({"providers": len(left), "districts": len(wanted), **c}))


def companies() -> dict[str, list[dict[str, Any]]]:
    by_d: dict[str, list[dict]] = defaultdict(list)
    with (CH / "ch_in_cqc_districts.csv").open(encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            by_d[r["district"]].append({
                "id": f"ch:{r['company_number']}", "name": r["name"], "address": r["address"],
                "lat": float(r["lat"]) if r["lat"] else None,
                "lon": float(r["lon"]) if r["lon"] else None})
    return by_d


def build() -> None:
    from arche.resolve import reconcile

    started = time.time()
    left = providers()
    right = companies()
    by_d: dict[str, list[dict]] = defaultdict(list)
    for r in left:
        by_d[r["district"]].append(r)
    OUT.mkdir(parents=True, exist_ok=True)
    rows: list[dict] = []
    backends: Counter = Counter()
    candidates: dict[str, int] = {}
    for d in sorted(by_d):
        lr = [{k: r[k] for k in ("id", "name", "address", "lat", "lon")} for r in by_d[d]]
        vocab = set().union(*(words(r["name"]) for r in lr))
        rr = [r for r in right.get(d, []) if words(r["name"]) & vocab]
        candidates[d] = len(rr)
        if not d or not rr:
            continue
        result = reconcile(lr, rr, entity="organisation")
        backends[str(result.get("backend", {}).get("chosen"))] += 1
        num = {r["id"]: r["company_number"] for r in by_d[d]}
        names = {r["id"]: r["name"] for r in rr}
        for e in result["matches"]:
            rows.append({"decision": e["decision"], "score": e["score"], "district": d,
                         "cqc_id": e["a_id"], "ch_id": e["b_id"], "ch_name": names[e["b_id"]],
                         "cqc_company_number": num[e["a_id"]]})
    rows.sort(key=lambda r: (r["cqc_id"], r["ch_id"]))
    with (OUT / "candidate_edges.csv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    summary = {"schema": "arche.uk_ch_edges.v1", "providers": len(left),
               "districts": len(by_d), "edges": len(rows),
               "decisions": dict(Counter(r["decision"] for r in rows)),
               "backends": dict(backends), "candidates": sum(candidates.values()),
               "largest_district_candidates": max(candidates.values()),
               "seconds": round(time.time() - started, 1)}
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n",
                                      encoding="utf-8")
    print(json.dumps(summary))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--extract", action="store_true")
    ap.add_argument("--build", action="store_true")
    args = ap.parse_args()
    if args.extract:
        extract()
    if args.build:
        build()


if __name__ == "__main__":
    main()
