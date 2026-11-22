#!/usr/bin/env python
"""Build a review pack of the engine's near misses, for testing a pair decider.

The engine's review band in Edo, Kano and Ondo is now mostly true matches
(264 of 272 in the X1 pack), so a test there says little about false merges.
A near miss is what a decider most needs to refuse: a facility in the same LGA,
with a similar name, that the engine considered and called ``different``.

For each GRID3 facility, in salted-hash order, the pack takes the HFR facility
in the same LGA whose name is closest under character TF-IDF (cosine at least
``MIN_COSINE``), skipping any pair the engine surfaced as match or review, and
keeps it only if ``arche.compare`` calls it ``different``. Some will be true
matches the engine missed; that is for the reviewer to say.

Records in the 2026-08-19 pack (used for development) and pairs in the X1 pack
are excluded. At most ``PER_STATE`` pairs per state.

    uv run --package arche-core python data/scripts/build_near_miss_pack.py \\
        --edges-dir ~/.cache/arche/x1 --work ~/.cache/arche/nearmiss
    uv run --package arche-core python data/scripts/build_facility_adjudication_pack.py \\
        --sample Edo=~/.cache/arche/nearmiss/Edo/adjudication_sample.csv ... \\
        --output data/review_packs/nigeria_facilities_nearmiss_2026-11-21
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import sys
from collections import defaultdict
from pathlib import Path

import arche
from arche.retrieval import CharNgramIndex

HERE = Path(__file__).resolve().parent
DATA = HERE.parent
_spec = importlib.util.spec_from_file_location("evaluate_facility_master",
                                              HERE / "evaluate_facility_master.py")
efm = importlib.util.module_from_spec(_spec)
sys.modules["evaluate_facility_master"] = efm
_spec.loader.exec_module(efm)

STATES = ("Edo", "Kano", "Ondo")
PER_STATE = 80
MIN_COSINE = 0.35
DEV_PACK = DATA / "review_packs" / "nigeria_facilities_2026-08-19" / "adjudication_pack.csv"
X1_PACK = DATA / "review_packs" / "nigeria_facilities_x1_2026-11-21" / "adjudication_pack.csv"


def _salted(*parts: str) -> int:
    return int(hashlib.sha256("\0".join(("near-miss",) + parts).encode()).hexdigest()[:12], 16)


def _fold(s: str) -> str:
    return " ".join((s or "").casefold().split())


def _read(path: Path) -> list[dict]:
    with path.open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def build(state: str, edges: Path, excluded_records: set[str],
          excluded_pairs: set[tuple[str, str]]) -> tuple[list[dict], dict]:
    left = efm._grid3_records(DATA / "GRID3_NGA_health_facilities_v2.csv", state)
    right = efm._hfr_records(DATA / f"hfr_{state.casefold()}.csv", state)
    surfaced = {(r["grid3_id"], r["hfr_id"]) for r in _read(edges)}
    by_lga: dict[str, list[dict]] = defaultdict(list)
    for h in right:
        if h["id"] not in excluded_records:
            by_lga[_fold(h["admin_path"].get("admin2", ""))].append(h)
    index = {k: CharNgramIndex([h["name"] for h in v]) for k, v in by_lga.items()}
    stats = {"grid3_considered": 0, "no_candidate": 0, "engine_not_different": 0}
    rows = []
    for g in sorted(left, key=lambda r: _salted(state, r["id"])):
        if len(rows) >= PER_STATE:
            break
        if g["id"] in excluded_records:
            continue
        lga = _fold(g["admin_path"].get("admin2", ""))
        if lga not in index:
            continue
        stats["grid3_considered"] += 1
        pick = None
        for i, cos in index[lga].search(g["name"], k=5):
            h = by_lga[lga][i]
            if cos < MIN_COSINE:
                break
            if (g["id"], h["id"]) in surfaced or (g["id"], h["id"]) in excluded_pairs:
                continue
            pick = (h, cos)
            break
        if pick is None:
            stats["no_candidate"] += 1
            continue
        h, cos = pick
        verdict = arche.compare(g, h, entity="place")
        if verdict.identity != "different":
            stats["engine_not_different"] += 1
            continue
        rows.append({
            "decision_id": "nm:sha256:" + hashlib.sha256(
                f"{g['id']}\t{h['id']}".encode()).hexdigest(),
            "decision": verdict.identity,
            "score": verdict.score,
            "distinctive_max": verdict.gate.get("distinctive_max", ""),
            "distance_km": "",
            "grid3_id": g["id"], "grid3_code": g["source_code"], "grid3_name": g["name"],
            "grid3_admin_path": json.dumps(g["admin_path"], sort_keys=True),
            "hfr_id": h["id"], "hfr_code": h["source_code"], "hfr_name": h["name"],
            "hfr_admin_path": json.dumps(h["admin_path"], sort_keys=True),
            "evidence": json.dumps({"tfidf_cosine": round(cos, 4),
                                    "engine_identity": verdict.identity}, sort_keys=True),
            "review_outcome": "", "reviewer": "", "reviewed_at": "", "reason": "",
        })
    stats["kept"] = len(rows)
    return rows, stats


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--edges-dir", type=Path, required=True,
                    help="directory holding <State>/candidate_edges.csv from today's engine run")
    ap.add_argument("--work", type=Path, required=True, help="where per-state samples go")
    args = ap.parse_args()
    dev = _read(DEV_PACK)
    excluded_records = {r["grid3_id"] for r in dev} | {r["hfr_id"] for r in dev}
    excluded_pairs = {(r["grid3_id"], r["hfr_id"]) for r in _read(X1_PACK)}
    summary = {}
    for state in STATES:
        rows, stats = build(state, args.edges_dir / state / "candidate_edges.csv",
                            excluded_records, excluded_pairs)
        out = args.work / state
        out.mkdir(parents=True, exist_ok=True)
        efm._write_csv(out / "adjudication_sample.csv", rows)
        summary[state] = stats
        print(state, stats, flush=True)
    (args.work / "summary.json").write_text(json.dumps(
        {"per_state": PER_STATE, "min_cosine": MIN_COSINE, "states": summary},
        indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
