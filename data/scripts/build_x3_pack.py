#!/usr/bin/env python
"""Build the X3 test pack: fresh, blind GRID3/HFR pairs in Edo, Kano and Ondo.

Every earlier pack in these states has been read, and the engine's review band
here is used up, so X3 is a stress set drawn from three kinds of pair, 20 of
each per state, in salted-hash order:

* ``lookalike``: a GRID3 facility and the HFR record in another LGA, within
  ``LOOKALIKE_KM``, whose name is closest to it (character TF-IDF cosine at
  least 0.5), when that record is not the GRID3 facility's own. The trap that
  misled the August labels.
* ``near_miss``: the HFR record in the same LGA with the closest name (cosine at
  least 0.35), not the GRID3 facility's own.
* ``drift``: the GRID3 facility and its own HFR record (shared source id) when
  their names differ (symmetric trigram cosine below 0.8). Hard true matches.

No GRID3 or HFR record that appears in any earlier pack is used, and each GRID3
facility appears at most once. Every row is written with decision ``review`` and
no score, so the reviewer sees neither the engine's call nor the kind of pair.
Each row shows the GRID3 facility's own HFR record, both points' Plus Code and
H3 cell, and both registries' facility level.

    uv run --package arche-core python data/scripts/build_x3_pack.py --work ~/.cache/arche/x3
    uv run --package arche-core python data/scripts/build_facility_adjudication_pack.py \\
        --sample Edo=~/.cache/arche/x3/Edo/adjudication_sample.csv ... \\
        --output data/review_packs/nigeria_facilities_x3_2026-11-22
"""

from __future__ import annotations

import argparse
import contextlib
import csv
import hashlib
import json
import math
from collections import Counter, defaultdict
from pathlib import Path

from arche.addr.locate import h3_cell, h3_steps, plus_code
from arche.retrieval import CharNgramIndex

DATA = Path(__file__).resolve().parents[1]
PACKS = DATA / "review_packs"
EARLIER = ("nigeria_facilities_2026-08-19", "nigeria_facilities_x1_2026-11-21",
           "nigeria_facilities_nearmiss_2026-11-21", "nigeria_facilities_recheck_2026-11-22")
HFR_NATIONAL = Path.home() / ".cache" / "arche" / "e0c" / "hfr_national.json"
STATES = ("Edo", "Kano", "Ondo")
PER_KIND = 20
LOOKALIKE_KM, LOOKALIKE_COS, NEAR_COS, DRIFT_COS = 50.0, 0.5, 0.35, 0.8
FIELDS = [
    "decision_id", "decision", "score", "distinctive_max", "distance_km",
    "grid3_id", "grid3_code", "grid3_name", "grid3_admin_path", "grid3_level",
    "grid3_lat", "grid3_lon", "grid3_plus_code", "grid3_h3",
    "grid3_own_hfr_id", "grid3_own_hfr_name", "grid3_own_hfr_lga", "grid3_km_to_own_hfr",
    "grid3_own_hfr_plus_code",
    "hfr_id", "hfr_code", "hfr_name", "hfr_admin_path", "hfr_level",
    "hfr_lat", "hfr_lon", "hfr_plus_code", "hfr_h3", "hfr_km_from_grid3", "hfr_h3_steps",
    "evidence", "review_outcome", "reviewer", "reviewed_at", "reason",
]


def salted(*parts: str) -> int:
    return int(hashlib.sha256("\0".join(("x3",) + parts).encode()).hexdigest()[:12], 16)


def fold(s: str) -> str:
    return " ".join((s or "").casefold().split())


def km(a, b) -> float | None:
    if not a or not b:
        return None
    la1, lo1, la2, lo2 = map(math.radians, (*a, *b))
    h = (math.sin((la2 - la1) / 2) ** 2
         + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2)
    return 12742.0 * math.asin(math.sqrt(h))


def where(prefix: str, xy) -> dict[str, str]:
    if not xy:
        return {}
    return {f"{prefix}_lat": f"{xy[0]:.6f}", f"{prefix}_lon": f"{xy[1]:.6f}",
            f"{prefix}_plus_code": plus_code(*xy), f"{prefix}_h3": h3_cell(*xy)}


def cosine(a: str, b: str) -> float:
    """Symmetric cosine of character-trigram counts (no IDF: two names only)."""
    def grams(s: str) -> Counter:
        s = f"  {fold(s)} "
        return Counter(s[i:i + 3] for i in range(len(s) - 2))
    x, y = grams(a), grams(b)
    dot = sum(v * y[k] for k, v in x.items())
    norm = math.sqrt(sum(v * v for v in x.values()) * sum(v * v for v in y.values()))
    return dot / norm if norm else 0.0


def earlier_records() -> set[str]:
    seen: set[str] = set()
    for pack in EARLIER:
        with (PACKS / pack / "adjudication_pack.csv").open(encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                seen |= {r["grid3_id"].split(":", 1)[1], r["hfr_id"].split(":", 1)[1]}
                if r.get("grid3_own_hfr_id"):
                    seen.add(r["grid3_own_hfr_id"].split(":", 1)[1])
    return seen


def row(state: str, kind: str, g: dict, h: dict, own: dict, cos: float) -> dict:
    gxy, hxy, oxy = g["xy"], h["xy"], own["xy"]
    d = km(gxy, hxy)
    out = {
        "decision_id": "x3:sha256:" + hashlib.sha256(f"{g['id']}\t{h['id']}".encode()).hexdigest(),
        "decision": "review", "score": "", "distinctive_max": "",
        "distance_km": "" if d is None else f"{d:.2f}",
        "grid3_id": "grid3:" + g["id"], "grid3_code": g["code"], "grid3_name": g["name"],
        "grid3_admin_path": json.dumps({"admin1": state, "admin2": g["lga"]}, sort_keys=True),
        "grid3_level": g["level"],
        "grid3_own_hfr_id": "hfr:" + own["id"], "grid3_own_hfr_name": own["name"],
        "grid3_own_hfr_lga": own["lga"],
        "grid3_km_to_own_hfr": "" if km(gxy, oxy) is None else f"{km(gxy, oxy):.2f}",
        "grid3_own_hfr_plus_code": plus_code(*oxy) if oxy else "",
        "hfr_id": "hfr:" + h["id"], "hfr_code": h["id"], "hfr_name": h["name"],
        "hfr_admin_path": json.dumps({"admin1": state, "admin2": h["lga"]}, sort_keys=True),
        "hfr_level": h["level"],
        "hfr_km_from_grid3": "" if d is None else f"{d:.2f}",
        "evidence": json.dumps({"tfidf_cosine": round(cos, 4)}, sort_keys=True),
        **where("grid3", gxy), **where("hfr", hxy),
        "review_outcome": "", "reviewer": "", "reviewed_at": "", "reason": "",
    }
    if out.get("grid3_h3") and out.get("hfr_h3"):
        steps = h3_steps(out["grid3_h3"], out["hfr_h3"])
        out["hfr_h3_steps"] = "" if steps is None else str(steps)
    return out | {"_kind": kind}


def build(state: str, hfr_levels: dict[str, str], used: set[str]) -> tuple[list[dict], dict]:
    hfr = {}
    with (DATA / f"hfr_{state.casefold()}.csv").open(encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            xy = None
            with contextlib.suppress(ValueError):
                xy = (float(r["lat"]), float(r["lon"]))
            hfr[r["id"]] = {"id": r["id"], "name": r["name"] or r["alternate_name"],
                            "lga": r["lga"], "xy": xy, "level": hfr_levels.get(r["id"], "")}
    grid3 = []
    with (DATA / "GRID3_NGA_health_facilities_v2.csv").open(encoding="utf-8-sig") as fh:
        for r in csv.DictReader(fh):
            if fold(r["state"]) != fold(state) or not r["facility_name"].strip():
                continue
            xy = None
            with contextlib.suppress(ValueError):
                xy = (float(r["latitude"]), float(r["longitude"]))
            grid3.append({"id": r["globalid"], "name": r["facility_name"].strip(),
                          "lga": r["lga"], "xy": xy, "code": r["nhfr_facility_code"],
                          "level": r["facility_level"]})
    pool = [h for h in hfr.values() if h["id"] not in used and h["name"]]
    by_lga: dict[str, list[dict]] = defaultdict(list)
    for h in pool:
        by_lga[fold(h["lga"])].append(h)
    index_lga = {k: CharNgramIndex([h["name"] for h in v]) for k, v in by_lga.items()}
    index_all = CharNgramIndex([h["name"] for h in pool])
    taken: dict[str, list[dict]] = {"lookalike": [], "near_miss": [], "drift": []}
    for g in sorted(grid3, key=lambda r: salted(state, r["id"])):
        own = hfr.get(g["id"])
        if g["id"] in used or own is None or own["id"] in used:
            continue
        if len(taken["drift"]) < PER_KIND:
            cos = cosine(g["name"], own["name"])
            if cos < DRIFT_COS:
                taken["drift"].append(row(state, "drift", g, own, own, cos))
                used |= {g["id"], own["id"]}
                continue
        if len(taken["lookalike"]) < PER_KIND and g["xy"]:
            for i, cos in index_all.search(g["name"], k=20):
                h = pool[i]
                if cos < LOOKALIKE_COS:
                    break
                d = km(g["xy"], h["xy"])
                other_lga = fold(h["lga"]) != fold(g["lga"])
                if (h["id"] != own["id"] and h["id"] not in used and other_lga
                        and d is not None and d <= LOOKALIKE_KM):
                    taken["lookalike"].append(row(state, "lookalike", g, h, own, cos))
                    used |= {g["id"], h["id"], own["id"]}
                    break
            if g["id"] in used:
                continue
        if len(taken["near_miss"]) < PER_KIND and fold(g["lga"]) in index_lga:
            for i, cos in index_lga[fold(g["lga"])].search(g["name"], k=5):
                h = by_lga[fold(g["lga"])][i]
                if cos < NEAR_COS:
                    break
                if h["id"] != own["id"] and h["id"] not in used:
                    taken["near_miss"].append(row(state, "near_miss", g, h, own, cos))
                    used |= {g["id"], h["id"], own["id"]}
                    break
        if all(len(v) >= PER_KIND for v in taken.values()):
            break
    rows = [r for v in taken.values() for r in v]
    return rows, {k: len(v) for k, v in taken.items()}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--work", type=Path, required=True)
    args = ap.parse_args()
    with HFR_NATIONAL.open(encoding="utf-8") as fh:
        levels = {f["properties"]["global_id"]: f["properties"].get("type") or ""
                  for f in json.load(fh)["features"]}
    used = earlier_records()
    summary, kinds = {}, {}
    for state in STATES:
        rows, counts = build(state, levels, used)
        rows.sort(key=lambda r: r["decision_id"])
        kinds.update({r["decision_id"]: r.pop("_kind") for r in rows})
        out = args.work / state
        out.mkdir(parents=True, exist_ok=True)
        with (out / "adjudication_sample.csv").open("w", encoding="utf-8", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=FIELDS)
            w.writeheader()
            w.writerows(rows)
        summary[state] = counts
        print(state, counts, flush=True)
    # The kind of each pair is kept out of the pack so the reviewer cannot see it.
    (args.work / "kinds.json").write_text(json.dumps(kinds, indent=1, sort_keys=True) + "\n",
                                          encoding="utf-8")
    (args.work / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n",
                                            encoding="utf-8")


if __name__ == "__main__":
    main()
