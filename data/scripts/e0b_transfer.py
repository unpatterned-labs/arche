#!/usr/bin/env python
"""E0b transfer: does the Wikidata-trained encoder help on Nigerian facility records?

The labels are the maintainer's review of the Nigerian facility pack's review
band (``adjudication_pack_reviewed.csv``, git-ignored). The rule was written to
data/er_bench/benchmark_e0b_transfer_preregistration.json before any ranking
ran; this script refuses to run if the labels file no longer matches the digest
recorded there.

Primary: for each pair marked ``same_entity``, search every HFR facility name in
the state with the GRID3 name, and ask whether the reviewed HFR record is in the
top 10. Secondary: recall@1, MRR, and how well each arm's pair cosine separates
``same_entity`` from ``different`` (AUC), against the engine's own score.

Only aggregates are written. GRID3 and HFR rows are measured here, never copied.

    python data/scripts/e0b_transfer.py --out data/er_bench/benchmark_e0b_transfer_result.json
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import random
import time
from pathlib import Path
from typing import Any

import numpy as np
from arche.retrieval import CharNgramIndex, EncoderIndex, TextEncoder
from arche.retrieval._tfidf import char_ngrams

DATA = Path(__file__).resolve().parents[1]
PREREG = DATA / "er_bench" / "benchmark_e0b_transfer_preregistration.json"
MODELS = Path.home() / ".cache" / "arche" / "models" / "e0b_a1"
BASE = "intfloat/multilingual-e5-small"
PREFIX = "query: "
SEEDS = (0, 1, 2)
N_BOOT = 10_000


def _sha(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def load(prereg: dict) -> tuple[list[dict], dict[str, list[tuple[str, str]]]]:
    labels = DATA.parent / prereg["labels"]["file"]
    if _sha(labels) != prereg["labels"]["sha256"]:
        raise SystemExit("labels changed since the preregistration; refusing to run")
    rows = [r for r in csv.DictReader(labels.open(encoding="utf-8"))
            if r["decision"] == "review" and r["review_outcome"] in ("same_entity", "different")]
    galleries = {}
    for state in sorted({r["state"] for r in rows}):
        with (DATA / f"hfr_{state.lower()}.csv").open(encoding="utf-8") as fh:
            galleries[state] = [(g["id"], " ".join(g["name"].split())) for g in csv.DictReader(fh)]
    return rows, galleries


class TfidfArm:
    name = "tfidf_char3"

    def index(self, texts):
        return CharNgramIndex(texts)

    def cosine(self, a: list[str], b: list[str]) -> np.ndarray:
        ref = CharNgramIndex(a + b)
        out = []
        for x, y in zip(a, b, strict=True):
            wx, wy = ref._weights(char_ngrams(x)), ref._weights(char_ngrams(y))
            nx = math.sqrt(sum(v * v for v in wx.values())) or 1.0
            ny = math.sqrt(sum(v * v for v in wy.values())) or 1.0
            out.append(sum(v * wy.get(g, 0.0) for g, v in wx.items()) / (nx * ny))
        return np.array(out)


class EncoderArm:
    def __init__(self, name: str, path: str):
        self.name = name
        self.encoder = TextEncoder(path, prefix=PREFIX)

    def index(self, texts):
        return EncoderIndex(texts, self.encoder)

    def cosine(self, a, b):
        return np.sum(self.encoder.encode(a) * self.encoder.encode(b), axis=1)


def ranks(arm, rows, galleries) -> list[int]:
    """1-based rank of the reviewed HFR record, in the retriever's own order."""
    out = []
    for state, gallery in galleries.items():
        ids = [g for g, _ in gallery]
        index = arm.index([t for _, t in gallery])
        mine = [r for r in rows if r["state"] == state]
        queries = [" ".join(r["grid3_name"].split()) for r in mine]
        if hasattr(index, "search_many"):
            hits = index.search_many(queries, k=len(ids))
        else:
            hits = [index.search(q, k=len(ids)) for q in queries]
        for r, h in zip(mine, hits, strict=True):
            order = [ids[i] for i, _ in h]
            target = r["hfr_id"].split(":", 1)[1]
            out.append(order.index(target) + 1 if target in order else len(ids) + 1)
    return out


def auc(score: np.ndarray, y: np.ndarray) -> float:
    pos, neg = score[y == 1], score[y == 0]
    diff = pos[:, None] - neg[None, :]
    return float(((diff > 0) + 0.5 * (diff == 0)).mean())


def boot(fn, n: int, seed: int = 0) -> tuple[float, float]:
    rng = random.Random(seed)
    vals = sorted(fn([rng.randrange(n) for _ in range(n)]) for _ in range(N_BOOT))
    return vals[int(0.025 * N_BOOT)], vals[int(0.975 * N_BOOT) - 1]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    prereg = json.loads(PREREG.read_text(encoding="utf-8"))
    rule_sha = "sha256:" + hashlib.sha256(json.dumps(prereg["rule"], sort_keys=True)
                                          .encode()).hexdigest()
    if rule_sha != prereg["rule_sha256"]:
        raise SystemExit("rule differs from its recorded digest; refusing to run")
    rows, galleries = load(prereg)
    rows.sort(key=lambda r: (r["state"], r["decision_id"]))
    same = [r for r in rows if r["review_outcome"] == "same_entity"]
    y = np.array([r["review_outcome"] == "same_entity" for r in rows], dtype=int)

    arms: list[Any] = [TfidfArm(), EncoderArm("zero_shot:" + BASE, BASE)]
    for lane in ("wikidata_ng", "wikidata_wa"):
        arms += [EncoderArm(f"fine_tuned:{lane}:seed{s}", str(MODELS / lane / f"seed{s}"))
                 for s in SEEDS]

    started = time.time()
    by_arm: dict[str, dict[str, Any]] = {}
    for arm in arms:
        rk = np.array(ranks(arm, same, galleries))
        cos = arm.cosine([r["grid3_name"] for r in rows], [r["hfr_name"] for r in rows])
        by_arm[arm.name] = {"rank": rk, "cos": cos}
        print(f"{arm.name:60s} r@1 {np.mean(rk <= 1):.3f}  r@10 {np.mean(rk <= 10):.3f}  "
              f"AUC {auc(cos, y):.3f}")

    engine = np.array([float(r["score"]) for r in rows])
    base = by_arm["tfidf_char3"]
    n = len(same)

    def summary(names: list[str]) -> dict[str, Any]:
        hit10 = np.mean([by_arm[a]["rank"] <= 10 for a in names], axis=0)
        hit1 = np.mean([by_arm[a]["rank"] <= 1 for a in names], axis=0)
        rr = np.mean([1.0 / by_arm[a]["rank"] for a in names], axis=0)
        cos = np.mean([by_arm[a]["cos"] for a in names], axis=0)
        b10 = (base["rank"] <= 10).astype(float)
        gain = hit10 - b10
        lo, hi = boot(lambda ix: float(np.mean(gain[ix])), n)
        auc_d = auc(cos, y) - auc(base["cos"], y)
        alo, ahi = boot(lambda ix: auc(cos[ix], y[ix]) - auc(base["cos"][ix], y[ix])
                        if 0 < y[ix].sum() < len(ix) else 0.0, len(rows), seed=1)
        return {"arms": names, "recall@1": round(float(hit1.mean()), 4),
                "recall@10": round(float(hit10.mean()), 4), "mrr": round(float(rr.mean()), 4),
                "gain@10_vs_tfidf": round(float(gain.mean()), 4),
                "gain@10_bootstrap95": [round(lo, 4), round(hi, 4)],
                "queries_won": int((hit10 > b10).sum()), "queries_lost": int((hit10 < b10).sum()),
                "pair_auc": round(auc(cos, y), 4), "pair_auc_minus_tfidf": round(auc_d, 4),
                "pair_auc_minus_tfidf_bootstrap95": [round(alo, 4), round(ahi, 4)]}

    groups = {"tfidf_char3": ["tfidf_char3"], "zero_shot": ["zero_shot:" + BASE]}
    for lane in ("wikidata_ng", "wikidata_wa"):
        groups[f"fine_tuned:{lane}"] = [f"fine_tuned:{lane}:seed{s}" for s in SEEDS]
    result = {name: summary(names) for name, names in groups.items()}
    primary = result["fine_tuned:wikidata_ng"]
    lo = primary["gain@10_bootstrap95"][0]
    verdict = {"transfer_shown": primary["gain@10_vs_tfidf"] >= 0.02 and lo > 0,
               "no_harm": lo > -0.02}
    print(json.dumps({"primary": primary, "verdict": verdict}, indent=2))
    out = {"schema": "arche.e0b_transfer.v1",
           "preregistration_sha256": _sha(PREREG), "rule_sha256": rule_sha,
           "labels_sha256": prereg["labels"]["sha256"],
           "pairs": {"same_entity": int(y.sum()), "different": int(len(y) - y.sum())},
           "gallery_sizes": {s: len(g) for s, g in galleries.items()},
           "engine_score_pair_auc": round(auc(engine, y), 4),
           "result": result, "verdict": verdict, "seconds": round(time.time() - started, 1)}
    if args.out:
        Path(args.out).write_text(json.dumps(out, indent=2, sort_keys=True) + "\n",
                                  encoding="utf-8")
        print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
