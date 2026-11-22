#!/usr/bin/env python
"""E0c: retrieval trained on facility names, and a facility-type tier map, on Nigeria.

E0b's encoder learned Wikidata's naming and lost 8.5 points on Nigerian
facilities. E0c trains on the GRID3 v2 / HFR crosswalk instead (GRID3
``globalid`` = HFR ``global_id``), from the 34 states other than the three test
states, and separately tests a tier map that turns every primary-care type
phrase into one word, because between these two registries "Health Post" and
"Dispensary" (and eight other phrases) name the same kind of facility.

The rule, the tier map and the training recipe were written to
data/er_bench/benchmark_e0c_facility_preregistration.json before any training
or test ranking; this script refuses to run if any digest no longer matches.

T1 is the 86 reviewed ``same_entity`` pairs (proposed by the engine, so lexical
search is favoured). T2 is every crosswalk pair in Edo, Kano and Ondo whose
names differ (independent of the engine). Only aggregates are written.

    python data/scripts/e0c_facility.py --out data/er_bench/benchmark_e0c_facility_result.json
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import re
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np
from arche.retrieval import CharNgramIndex, EncoderIndex, TextEncoder
from arche.retrieval._train import TrainConfig, fine_tune

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("e0b_transfer", HERE / "e0b_transfer.py")
tr = importlib.util.module_from_spec(_spec)
sys.modules["e0b_transfer"] = tr
_spec.loader.exec_module(tr)

DATA = tr.DATA
PREREG = DATA / "er_bench" / "benchmark_e0c_facility_preregistration.json"
CACHE = Path.home() / ".cache" / "arche" / "e0c"
MODELS = Path.home() / ".cache" / "arche" / "models" / "e0c"
TEST_STATES = {"edo", "kano", "ondo"}
BASE, PREFIX, SEEDS = tr.BASE, tr.PREFIX, tr.SEEDS
RRF_K = 60


def fold(s: str) -> str:
    return " ".join(s.casefold().split())


def _digest(obj: Any) -> str:
    return "sha256:" + hashlib.sha256(json.dumps(obj, sort_keys=True).encode()).hexdigest()


def tier_normaliser(tiers: dict[str, list[str]]):
    phrases = sorted(((p, t) for t, ps in tiers.items() for p in ps), key=lambda x: -len(x[0]))
    pattern = re.compile(r"\b(" + "|".join(re.escape(p) for p, _ in phrases) + r")\b")
    tier_of = dict(phrases)

    def norm(name: str) -> str:
        text = " ".join(re.findall(r"[a-z0-9]+", name.casefold()))
        found = [tier_of[m.group(1)] for m in pattern.finditer(text)]
        rest = " ".join(pattern.sub(" ", text).split())
        return " ".join(x for x in (rest, found[0] if found else "") if x) or text

    return norm


def crosswalk() -> tuple[list[tuple[dict, dict]], dict[str, dict]]:
    with (CACHE / "hfr_national.json").open(encoding="utf-8") as fh:
        hfr = {f["properties"]["global_id"]: f["properties"] for f in json.load(fh)["features"]}
    with (DATA / "GRID3_NGA_health_facilities_v2.csv").open(encoding="utf-8-sig") as fh:
        grid3 = list(csv.DictReader(fh))
    return [(g, hfr[g["globalid"]]) for g in grid3 if g["globalid"] in hfr], hfr


def training_data(pairs, hfr) -> tuple[list[tuple[str, str]], list[list[str]]]:
    """Pairs and hard negatives from the 34 training states only."""
    train = [(g, h) for g, h in pairs if g["state"].strip().lower() not in TEST_STATES
             and h["state_name"].strip().lower() not in TEST_STATES]
    by_lga: dict[tuple[str, str], list[tuple[str, str]]] = defaultdict(list)
    for gid, h in hfr.items():
        if h["state_name"].strip().lower() not in TEST_STATES and h.get("name"):
            by_lga[(h["state_name"], h["lga_name"])].append((gid, " ".join(h["name"].split())))
    indexes = {k: CharNgramIndex([t for _, t in v]) for k, v in by_lga.items()}
    out, negs = [], []
    for g, h in train:
        a, b = " ".join(g["facility_name"].split()), " ".join((h["name"] or "").split())
        key = (h["state_name"], h["lga_name"])
        rows = by_lga.get(key, [])

        def neg(anchor: str, own: str = h["global_id"], rows=rows, key=key,
                pos: str = b) -> list[str]:
            if not rows:
                return []
            found = [rows[i] for i, _ in indexes[key].search(anchor, k=10)]
            return [t for gid, t in found
                    if gid != own and fold(t) not in (fold(pos), fold(anchor))][:3]

        if a and b and fold(a) != fold(b):
            out.append((a, b))
            negs.append(neg(a))
        alt = " ".join((h.get("alternate_name") or "").split())
        if alt and b and fold(alt) != fold(b):
            out.append((b, alt))
            negs.append(neg(b))
    return out, negs


def test_sets(pairs, prereg) -> tuple[dict[str, list[dict]], dict[str, list[tuple[str, str]]]]:
    t1_rows, galleries = tr.load({"labels": prereg["labels"]})
    t1 = sorted((r for r in t1_rows if r["review_outcome"] == "same_entity"),
                key=lambda r: (r["state"], r["decision_id"]))
    ids = {s: {g for g, _ in gal} for s, gal in galleries.items()}
    state_of = {s.lower(): s for s in galleries}
    t2, missing = [], 0
    for g, h in pairs:
        s = g["state"].strip().lower()
        if s in TEST_STATES and fold(g["facility_name"]) != fold(h["name"] or ""):
            st = state_of[s]
            if h["global_id"] not in ids[st]:
                missing += 1
                continue
            t2.append({"state": st, "grid3_name": g["facility_name"],
                       "hfr_id": "hfr:" + h["global_id"], "decision_id": g["globalid"]})
    t2.sort(key=lambda r: (r["state"], r["decision_id"]))
    print(f"T1 {len(t1)} queries; T2 {len(t2)} queries ({missing} not in the state HFR file)")
    return {"T1": t1, "T2": t2}, galleries


class Arm:
    def __init__(self, name: str, make_index, prep=lambda s: s):
        self.name, self.make_index, self.prep = name, make_index, prep

    def orders(self, rows, galleries) -> list[list[str]]:
        out = []
        for state, gallery in galleries.items():
            mine = [r for r in rows if r["state"] == state]
            if not mine:
                continue
            ids = [g for g, _ in gallery]
            index = self.make_index([self.prep(t) for _, t in gallery])
            qs = [self.prep(" ".join(r["grid3_name"].split())) for r in mine]
            hits = (index.search_many(qs, k=len(ids)) if hasattr(index, "search_many")
                    else [index.search(q, k=len(ids)) for q in qs])
            out += [[ids[i] for i, _ in h] for h in hits]
        return out


def ordered(rows, galleries):
    """Rows in the order Arm.orders emits them."""
    return [r for state in galleries for r in rows if r["state"] == state]


def rank_of(order: list[str], target: str, size: int) -> int:
    try:
        return order.index(target) + 1
    except ValueError:
        return size + 1


def rrf(a: list[str], b: list[str]) -> list[str]:
    score: dict[str, float] = defaultdict(float)
    for lst in (a, b):
        for i, g in enumerate(lst):
            score[g] += 1.0 / (RRF_K + i + 1)
    return sorted(score, key=lambda g: (-score[g], g))


def gain(hit: np.ndarray, base: np.ndarray) -> dict[str, Any]:
    d = hit - base
    lo, hi = tr.boot(lambda ix: float(np.mean(d[ix])), len(d))
    return {"recall@10": round(float(hit.mean()), 4), "gain@10": round(float(d.mean()), 4),
            "bootstrap95": [round(lo, 4), round(hi, 4)],
            "won": int((d > 0).sum()), "lost": int((d < 0).sum())}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", default=None)
    ap.add_argument("--retrain", action="store_true")
    args = ap.parse_args()
    prereg = json.loads(PREREG.read_text(encoding="utf-8"))
    if _digest(prereg["rule"]) != prereg["rule_sha256"] or \
            _digest(prereg["tier_map"]) != prereg["tier_map_sha256"]:
        raise SystemExit("rule or tier map differs from its recorded digest; refusing to run")
    hfr_sha = tr._sha(CACHE / "hfr_national.json").split(":")[1]
    if hfr_sha != prereg["training"]["hfr_source"]["sha256"]:
        raise SystemExit("HFR national file changed since the preregistration; refusing to run")
    norm = tier_normaliser(prereg["tier_map"])
    started = time.time()
    pairs, hfr = crosswalk()
    train_pairs, negs = training_data(pairs, hfr)
    print(f"training pairs {len(train_pairs)}, with hard negatives "
          f"{sum(bool(n) for n in negs)}")

    encoders = []
    for seed in SEEDS:
        out = MODELS / "crosswalk" / f"seed{seed}"
        if args.retrain or not (out / "arche_training.json").exists():
            fine_tune(BASE, train_pairs, out, hard_negatives=negs,
                      config=TrainConfig(seed=seed, prefix=PREFIX),
                      log=lambda m, s=seed: print(f"  seed {s}: {m}", flush=True))
        encoders.append(TextEncoder(str(out), prefix=PREFIX))

    sets, galleries = test_sets(pairs, prereg)
    result: dict[str, Any] = {}
    for name, rows in sets.items():
        rows = ordered(rows, galleries)
        size = {r["decision_id"]: len(galleries[r["state"]]) for r in rows}
        tgt = [r["hfr_id"].split(":", 1)[1] for r in rows]

        def hits(orders, rows=rows, size=size, tgt=tgt):
            return np.array([rank_of(o, t, size[r["decision_id"]]) <= 10
                             for o, t, r in zip(orders, tgt, rows, strict=True)], dtype=float)

        tf = Arm("tfidf_char3", tr.CharNgramIndex).orders(rows, galleries)
        tier = Arm("tfidf_char3_tier", CharNgramIndex, norm).orders(rows, galleries)
        enc = [Arm(f"seed{s}", lambda t, e=e: EncoderIndex(t, e)).orders(rows, galleries)
               for s, e in zip(SEEDS, encoders, strict=True)]
        base = hits(tf)
        h1 = np.mean([hits(o) for o in enc], axis=0)
        h3 = np.mean([hits([rrf(a, b) for a, b in zip(tier, o, strict=True)]) for o in enc],
                     axis=0)
        result[name] = {"queries": len(rows),
                        "tfidf_char3": {"recall@10": round(float(base.mean()), 4)},
                        "H1_encoder_transfer": gain(h1, base),
                        "H2_tier_normalisation": gain(hits(tier), base),
                        "H3_union": gain(h3, base),
                        "encoder_seeds_recall@10": [round(float(hits(o).mean()), 4) for o in enc]}
        print(name, json.dumps(result[name], indent=1))

    verdict = {}
    for h in ("H1_encoder_transfer", "H2_tier_normalisation", "H3_union"):
        t2, t1 = result["T2"][h], result["T1"][h]
        verdict[h] = {"shown": t2["gain@10"] >= 0.02 and t2["bootstrap95"][0] > 0
                      and t1["bootstrap95"][0] > -0.02,
                      "T1_no_harm": t1["bootstrap95"][0] > -0.02}
    print(json.dumps(verdict, indent=2))
    out = {"schema": "arche.e0c_facility.v1", "preregistration_sha256": tr._sha(PREREG),
           "training_pairs": len(train_pairs),
           "training_pairs_with_hard_negatives": sum(bool(n) for n in negs),
           "models": str(MODELS / "crosswalk"), "result": result, "verdict": verdict,
           "seconds": round(time.time() - started, 1)}
    if args.out:
        Path(args.out).write_text(json.dumps(out, indent=2, sort_keys=True) + "\n",
                                  encoding="utf-8")
        print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
