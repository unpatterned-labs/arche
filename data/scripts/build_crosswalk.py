#!/usr/bin/env python
"""Reconcile Kano health facilities across two independent lists with arche.

Pipeline: normalize facility names with the type-token vocab pack, block by
geographic proximity (both lists are 100% geocoded; OSM's LGA labels are
sparse), score each OSM->HFR candidate with the facility-tuned Fellegi-Sunter
matcher (distinctive name residual + geo proximity), and emit a crosswalk with
a probability + factor breakdown + explanation per match. Also runs a NAIVE
baseline (token-sort on the raw full names) to show where arche's African
context (type-token stripping + geo) changes the answer.

Inputs : data/hfr_kano.csv, data/osm_kano.csv  (fetch_facility_data.py)
Outputs: data/crosswalk_kano.csv               (best HFR match per OSM facility)
         data/crosswalk_sample_for_review.csv  (random sample to hand-label)

Run: uv run python notebooks/build_crosswalk.py
"""
from __future__ import annotations

import csv
import math
from collections import Counter, defaultdict
from pathlib import Path

from arche import compare_geo, load_type_vocab, normalize_type_token
from arche.resolve._matcher import (
    JurisdictionPriors,
    _jaro_winkler,
    _log_odds,
    _log_odds_to_probability,
    _token_sort_ratio,
)

DATA = Path(__file__).resolve().parent.parent / "data"
VOCAB = load_type_vocab("health_facility")

# OSM amenity/healthcare tag -> canonical type (for records the name doesn't type).
_OSM_TAG_TYPE = {"hospital": "HOSPITAL", "clinic": "CLINIC", "doctors": "CLINIC",
                 "pharmacy": "PHARMACY", "health_post": "HEALTH_POST"}

# Facility-tuned Fellegi-Sunter priors. The distinctive residual name is the
# primary signal. Geo is only a SUPPORTING one: within an ~11 km block many
# unrelated facilities sit close together, so geo's u-probability is high on
# purpose — a shared coordinate cannot, on its own, carry a weak name to a
# match. A tight (<0.5 km) coincidence still boosts, and an exact name still
# matches through noisy GPS (a quarter of true pairs are >2 km apart).
FACILITY_PRIORS = JurisdictionPriors(
    name="facility", name_m=0.92, name_u=0.04,   # facility names repeat (town names, "central")
    geo_m=0.85, geo_u=0.35, match_threshold=0.85, review_threshold=0.55,
)
# A confident match needs strong name agreement; a shared coordinate (often an
# OSM placeholder shared by several facilities) must not rescue a weak name.
# Pairs in 0.60-0.75 land in the review band for a human to adjudicate.
NAME_FLOOR_FOR_MATCH = 0.75

CELL = 0.05  # blocking grid ~5.5 km


def _haversine_km(a, b) -> float:
    r = 6371.0088
    p1, p2 = math.radians(a[0]), math.radians(b[0])
    dphi = math.radians(b[0] - a[0])
    dl = math.radians(b[1] - a[1])
    h = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(min(1.0, math.sqrt(h)))


def _facility_score(o: dict, h: dict) -> tuple[float, float, float]:
    """Place-calibrated match score. Same Fellegi-Sunter core arche uses for
    people (_log_odds + sigmoid), but the NAME comparator is pure string
    similarity, NOT compare_names — the person-name lexicon would spuriously
    equate facility name tokens. The engine is shared; the comparator is
    calibrated per entity class. Returns (probability, name_sim, geo_sim)."""
    ns = max(
        _jaro_winkler(o["residual"], h["residual"]),
        _token_sort_ratio(o["residual"], h["residual"]),
    )
    gs = compare_geo(o["lat"], o["lon"], h["lat"], h["lon"])
    log_odds = (
        _log_odds(ns, FACILITY_PRIORS.name_m, FACILITY_PRIORS.name_u)
        + _log_odds(gs, FACILITY_PRIORS.geo_m, FACILITY_PRIORS.geo_u)
    )
    return _log_odds_to_probability(log_odds), ns, gs


def _load(path: Path) -> list[dict]:
    with open(path, encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    out = []
    for row in rows:
        try:
            lat, lon = float(row["lat"]), float(row["lon"])
        except (TypeError, ValueError):
            continue
        if not (4 < lat < 14 and 2 < lon < 15):  # Nigeria sanity box
            continue
        row["lat"], row["lon"] = lat, lon
        out.append(row)
    return out


def _typed(name: str, type_field: str) -> tuple[str | None, str]:
    """Return (canonical_type, residual_name). Name token wins; the OSM/HFR
    type field is the fallback (OSM often mistags, e.g. a PHC as 'hospital')."""
    t_name, residual = normalize_type_token(name, VOCAB)
    if t_name:
        return t_name, residual
    tf = (type_field or "").strip().lower()
    t_field = _OSM_TAG_TYPE.get(tf) or normalize_type_token(type_field, VOCAB)[0]
    return t_field, residual


def build() -> None:
    hfr = _load(DATA / "hfr_kano.csv")
    osm = _load(DATA / "osm_kano.csv")
    print(f"HFR: {len(hfr)} facilities | OSM: {len(osm)} facilities")

    # Precompute residual name + type for both sides.
    for h in hfr:
        h["ftype"], h["residual"] = _typed(h["name"], h.get("category", ""))
    for o in osm:
        o["ftype"], o["residual"] = _typed(o["name"], o.get("amenity") or o.get("healthcare", ""))

    # Geographic blocking: index HFR by grid cell.
    grid: dict[tuple, list] = defaultdict(list)
    for h in hfr:
        grid[(round(h["lat"] / CELL), round(h["lon"] / CELL))].append(h)

    def candidates(o):
        ci, cj = round(o["lat"] / CELL), round(o["lon"] / CELL)
        out = []
        for di in (-1, 0, 1):
            for dj in (-1, 0, 1):
                out.extend(grid.get((ci + di, cj + dj), ()))
        return out

    rows, decisions, arche_pairs, naive_pairs = [], Counter(), set(), set()
    n_candidates = 0
    for o in osm:
        cands = candidates(o)
        n_candidates += len(cands)
        best, best_naive = None, None
        for h in cands:
            prob, ns, gs = _facility_score(o, h)
            if best is None or prob > best[0]:
                best = (prob, ns, gs, h)
            naive = _token_sort_ratio(o["name"].lower(), h["name"].lower())
            if best_naive is None or naive > best_naive[0]:
                best_naive = (naive, h)
        if best is None:
            decisions["no_candidate"] += 1
            continue
        prob, ns, gs, h = best
        dist = _haversine_km((o["lat"], o["lon"]), (h["lat"], h["lon"]))
        if prob >= FACILITY_PRIORS.match_threshold and ns >= NAME_FLOOR_FOR_MATCH:
            decision = "match"
        elif prob >= FACILITY_PRIORS.review_threshold:
            decision = "review"
        else:
            decision = "no_match"
        decisions[decision] += 1
        if decision == "match":
            arche_pairs.add((o["id"], h["id"]))
        # naive "match": raw token-sort >= 0.85 (a common default cutoff)
        if best_naive and best_naive[0] >= 0.85:
            naive_pairs.add((o["id"], best_naive[1]["id"]))
        expl = f"name {ns:.0%}" + (f"; {dist:.1f} km apart" if gs > 0 else "")
        if o["ftype"] and h["ftype"]:
            expl += f"; type {'match' if o['ftype'] == h['ftype'] else 'differs'}"
        rows.append({
            "osm_id": o["id"], "osm_name": o["name"], "osm_type": o["ftype"] or "",
            "hfr_id": h["id"], "hfr_name": h["name"], "hfr_type": h["ftype"] or "",
            "hfr_lga": h.get("lga", ""),
            "probability": round(prob, 4), "decision": decision,
            "factor_name": round(ns, 4), "factor_geo": round(gs, 4),
            "distance_km": round(dist, 3),
            "type_agree": bool(o["ftype"] and h["ftype"] and o["ftype"] == h["ftype"]),
            "explanation": expl,
        })

    rows.sort(key=lambda r: -r["probability"])
    _write(DATA / "crosswalk_kano.csv", rows)

    # ---- Report -------------------------------------------------------------
    print(f"\nBlocking: {n_candidates:,} candidate pairs "
          f"({n_candidates / (len(osm) * len(hfr)):.1%} of the full cross-product)")
    print("Decisions:", dict(decisions))
    matches = [r for r in rows if r["decision"] == "match"]
    if matches:
        dists = sorted(r["distance_km"] for r in matches)
        print(f"Matches: {len(matches)} | median match distance "
              f"{dists[len(dists) // 2]:.2f} km | "
              f"{sum(d > 2 for d in dists)} matches are >2 km apart (GPS noise)")

    only_arche = arche_pairs - naive_pairs
    only_naive = naive_pairs - arche_pairs
    print("\narche vs naive token-sort baseline:")
    print(f"  arche matches:       {len(arche_pairs)}")
    print(f"  naive (>=0.85):      {len(naive_pairs)}")
    print(f"  arche found, naive missed: {len(only_arche)}  (spelling/type variants + geo)")
    print(f"  naive matched, arche rejected: {len(only_naive)}  (name collisions, far apart)")

    _examples(rows, only_arche)

    # Random sample for hand-labelling (deterministic: every Nth candidate match/review).
    review = [r for r in rows if r["decision"] in ("match", "review")]
    sample = review[:: max(1, len(review) // 150)][:150]
    _write(DATA / "crosswalk_sample_for_review.csv",
           [{**r, "human_label": ""} for r in sample])
    print(f"\nWrote {len(sample)} pairs to crosswalk_sample_for_review.csv "
          f"(add human_label = same/different to score precision/recall).")


def _examples(rows, only_arche) -> None:
    print("\n--- Example rows ---")
    conf = next((r for r in rows if r["decision"] == "match"), None)
    if conf:
        print(f"[confident] {conf['osm_name']!r} == {conf['hfr_name']!r} "
              f"p={conf['probability']} ({conf['explanation']})")
    amb = next((r for r in rows if r["decision"] == "review"), None)
    if amb:
        print(f"[review]    {amb['osm_name']!r} ~ {amb['hfr_name']!r} "
              f"p={amb['probability']} ({amb['explanation']})")
    win = next((r for r in rows if (r["osm_id"], r["hfr_id"]) in only_arche
               and r["factor_name"] and r["factor_name"] < 0.99), None)
    if win:
        print(f"[arche wins] {win['osm_name']!r} == {win['hfr_name']!r} "
              f"p={win['probability']} name_sim={win['factor_name']} "
              f"{win['distance_km']}km — naive token-sort missed this")


def _write(path: Path, rows: list[dict]) -> None:
    if not rows:
        print("WARN: no rows for", path.name)
        return
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print("wrote", path.name, len(rows), "rows")


if __name__ == "__main__":
    build()
