#!/usr/bin/env python
"""E0, retrieval: does a bi-encoder find true pairs that character n-grams miss?

The rule this experiment exists to apply (stated before any test number was
seen, and not to be edited after):

* The candidate arm is ``intfloat/multilingual-e5-small`` fine-tuned on each
  lane's *development* entities, three seeds.
* It is compared with character 3-gram TF-IDF top-k, the classical baseline,
  on the lane's *test* entities, searched against the lane's full gallery.
* It **passes** a lane only if all of these hold at once:
    1. mean recall@10 gain over TF-IDF, across the three seeds, >= 2 points;
    2. the paired entity-bootstrap 95% lower bound of that gain > 0;
    3. recall@10 on test pairs that share no word token is higher than TF-IDF's;
    4. the 95% lower bound of the recall@50 gain > -1 point;
    5. CPU query latency p95 <= 50 ms, and the model <= 500 MB on disk.
  Otherwise it fails that lane. A failing lane is a result, not a bug to fix.

Also reported, for reading the result rather than deciding it: arche's union
blocker (recall and the candidates it costs), two zero-shot encoders, and a
reciprocal-rank fusion of TF-IDF with the fine-tuned encoder.

Lanes (all public, truth complete unless noted; nothing here is redistributed):

* ``settlements``  Leipzig geographic settlements, 4 sources, 820 clusters
* ``london``       OSM London hospitals -> Wikidata (truth is recall-only)
* ``dblp_acm``     Leipzig DBLP-ACM bibliographic records
* ``abt_buy``      Leipzig Abt-Buy products

Not here: the Nigerian facility lane. It needs adjudicated pairs, and the
pack in data/review_packs/nigeria_facilities_2026-08-19 has none reviewed yet.

Splits are by entity: every record of one entity is in the same split, fixed
by a hash of the lane and the entity, never by a random draw. Training sees
development positives and negatives only; a test entity's record is never a
hard negative.

Run with a CUDA build of torch for training (CPU works, slowly)::

    python data/scripts/e0_retrieval.py --out data/er_bench/benchmark_e0_retrieval_result.json

Models are written under ~/.cache/arche/models/e0/ and never committed.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
import statistics
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
DATA = REPO / "data"
MODELS = Path.home() / ".cache" / "arche" / "models" / "e0"

BASE = "intfloat/multilingual-e5-small"
ZERO_SHOT = ("intfloat/multilingual-e5-small",
             "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2")
PREFIX = {"intfloat/multilingual-e5-small": "query: "}
SEEDS = (0, 1, 2)
KS = (1, 5, 10, 50)
#: CPU threads for the latency check. torch's default here (all 16) was about
#: 90x slower per query than 4 or 8 (556 ms against 6 ms, fresh processes).
CPU_THREADS = 4

#: The pass rule, fixed before the test split was read.
PASS = {"k": 10, "min_mean_gain": 0.02, "bootstrap_lower_gt": 0.0,
        "zero_overlap_must_improve": True, "k50_lower_gt": -0.01,
        "cpu_p95_ms_max": 50.0, "model_mb_max": 500.0, "bootstrap": 2000}


@dataclass
class Lane:
    name: str
    queries: list[tuple[str, str, str]]          # (id, entity, text)
    gallery: list[tuple[str, str | None, str]]   # (id, entity or None, text)
    truth: dict[str, set[str]]                   # query id -> gallery ids
    self_join: bool = False                      # gallery contains the queries
    note: str = ""
    sources: dict[str, str] = field(default_factory=dict)
    blocker_records: tuple[list[dict], list[dict]] | None = None
    blocker_fields: tuple[str, ...] = ("name",)


def _sha(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _read_csv(path: Path) -> list[dict[str, str]]:
    raw = path.read_bytes()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = raw.decode("latin-1")
    return list(csv.DictReader(text.splitlines()))


# ── lanes ────────────────────────────────────────────────────────────────────


def lane_settlements() -> Lane:
    folder = DATA / "er_bench" / "places"
    recs = {}
    for line in (folder / "settlements.json").read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            recs[str(row["id"])] = row["data"]
    entity_of: dict[str, str] = {}
    for line in (folder / "combinedSettlements_perfectMatch.json").read_text(
            encoding="utf-8").splitlines():
        if line.strip():
            c = json.loads(line)
            for v in c["data"]["clusteredVertices"]:
                entity_of[str(v)] = f"c{c['id']}"
    gallery = [(rid, entity_of.get(rid), d.get("label", "")) for rid, d in recs.items()]
    members: dict[str, set[str]] = defaultdict(set)
    for rid, ent, _ in gallery:
        if ent:
            members[ent].add(rid)
    queries, truth = [], {}
    for rid, ent, text in gallery:
        if ent and len(members[ent]) > 1:
            queries.append((rid, ent, text))
            truth[rid] = members[ent] - {rid}
    block = [{"id": rid, "name": d.get("label", ""), "lat": d.get("lat"), "lon": d.get("lon")}
             for rid, d in recs.items()]
    return Lane("settlements", queries, gallery, truth, self_join=True,
                sources={f: _sha(folder / f) for f in
                         ("settlements.json", "combinedSettlements_perfectMatch.json")},
                blocker_records=(block, block))


def lane_london() -> Lane:
    folder = DATA / "uk"
    osm = {r["osm_id"]: r for r in _read_csv(folder / "osm_london_hospitals.csv")}
    wd = {r["wd_id"]: r for r in _read_csv(folder / "wikidata_london_hospitals.csv")}
    truth: dict[str, set[str]] = defaultdict(set)
    for r in _read_csv(folder / "truth_pairs_london.csv"):
        if r["osm_id"] in osm and r["wd_id"] in wd:
            truth[r["osm_id"]].add(r["wd_id"])
    entity_of_wd = {w: f"e{q}" for q, ws in truth.items() for w in ws}
    queries = [(q, f"e{q}", osm[q]["name"]) for q in sorted(truth)]
    gallery = [(w, entity_of_wd.get(w), r["name"]) for w, r in wd.items()]
    block_a = [{"id": q, "name": osm[q]["name"], "lat": osm[q]["lat"], "lon": osm[q]["lon"]}
               for q in sorted(truth)]
    block_b = [{"id": w, "name": r["name"], "lat": r["lat"], "lon": r["lon"]}
               for w, r in wd.items()]
    return Lane("london", queries, gallery, dict(truth),
                note="truth is recall-only: unlabelled pairs may be true",
                sources={f: _sha(folder / f) for f in
                         ("osm_london_hospitals.csv", "wikidata_london_hospitals.csv",
                          "truth_pairs_london.csv")},
                blocker_records=(block_a, block_b))


def _biblio(r: dict[str, str]) -> str:
    return " | ".join(x for x in (r.get("title", ""), r.get("authors", ""), r.get("venue", ""),
                                  r.get("year", "")) if x)


def lane_dblp_acm() -> Lane:
    folder = DATA / "er_bench"
    acm = {r["id"]: r for r in _read_csv(folder / "ACM.csv")}
    dblp = {r["id"]: r for r in _read_csv(folder / "DBLP2.csv")}
    truth: dict[str, set[str]] = defaultdict(set)
    for r in _read_csv(folder / "DBLP-ACM_perfectMapping.csv"):
        if r["idACM"] in acm and r["idDBLP"] in dblp:
            truth[r["idACM"]].add(r["idDBLP"])
    ent_d = {d: f"e{a}" for a, ds in truth.items() for d in ds}
    queries = [(a, f"e{a}", _biblio(acm[a])) for a in sorted(truth)]
    gallery = [(d, ent_d.get(d), _biblio(r)) for d, r in dblp.items()]
    block_a = [{"id": a, "name": acm[a]["title"]} for a in sorted(truth)]
    block_b = [{"id": d, "name": r["title"]} for d, r in dblp.items()]
    return Lane("dblp_acm", queries, gallery, dict(truth),
                sources={f: _sha(folder / f) for f in
                         ("ACM.csv", "DBLP2.csv", "DBLP-ACM_perfectMapping.csv")},
                blocker_records=(block_a, block_b))


def lane_abt_buy() -> Lane:
    folder = DATA / "er_bench" / "products"
    abt = {r["id"]: r for r in _read_csv(folder / "Abt.csv")}
    buy = {r["id"]: r for r in _read_csv(folder / "Buy.csv")}
    truth: dict[str, set[str]] = defaultdict(set)
    for r in _read_csv(folder / "abt_buy_perfectMapping.csv"):
        if r["idAbt"] in abt and r["idBuy"] in buy:
            truth[r["idAbt"]].add(r["idBuy"])
    ent_b = {b: f"e{a}" for a, bs in truth.items() for b in bs}
    queries = [(a, f"e{a}", abt[a]["name"]) for a in sorted(truth)]
    gallery = [(b, ent_b.get(b), " | ".join(x for x in (r["name"], r.get("manufacturer", ""))
                                             if x)) for b, r in buy.items()]
    block_a = [{"id": a, "name": abt[a]["name"]} for a in sorted(truth)]
    block_b = [{"id": b, "name": r["name"]} for b, r in buy.items()]
    return Lane("abt_buy", queries, gallery, dict(truth),
                sources={f: _sha(folder / f) for f in
                         ("Abt.csv", "Buy.csv", "abt_buy_perfectMapping.csv")},
                blocker_records=(block_a, block_b))


LANES = {"settlements": lane_settlements, "london": lane_london,
         "dblp_acm": lane_dblp_acm, "abt_buy": lane_abt_buy}


# ── splits and training data ─────────────────────────────────────────────────


def split_of(lane: str, entity: str) -> str:
    h = int(hashlib.sha256(f"{lane}\0{entity}".encode()).hexdigest()[:8], 16)
    return "dev" if h % 2 == 0 else "test"


def training_data(lane: Lane, tfidf_hits: dict[str, list[int]]):
    """Development positives, and hard negatives from TF-IDF neighbours that
    belong to development entities (never a test entity's record)."""
    g_text = {gid: t for gid, _, t in lane.gallery}
    g_entity = {gid: e for gid, e, _ in lane.gallery}
    ids = [gid for gid, _, _ in lane.gallery]
    pairs, negatives = [], []
    for qid, ent, text in lane.queries:
        if split_of(lane.name, ent) != "dev":
            continue
        negs = []
        for row in tfidf_hits.get(qid, []):
            gid = ids[row]
            e = g_entity[gid]
            if gid in lane.truth[qid] or gid == qid or e is None or e == ent:
                continue
            if split_of(lane.name, e) == "dev":
                negs.append(g_text[gid])
        for gid in sorted(lane.truth[qid]):
            pairs.append((text, g_text[gid]))
            negatives.append(negs[:5])
    return pairs, negatives


# ── evaluation ───────────────────────────────────────────────────────────────


def _tokens(text: str) -> set[str]:
    import re

    return {t for t in re.split(r"[^a-z0-9]+", text.lower()) if len(t) >= 2}


def hits_by_query(lane: Lane, ranked: dict[str, list[int]]) -> dict[str, dict[int, int]]:
    """query id -> {k: true gallery rows within the top k}."""
    ids = [gid for gid, _, _ in lane.gallery]
    out = {}
    for qid, _, _ in lane.queries:
        rows = [r for r in ranked.get(qid, []) if ids[r] != qid]
        found = {k: sum(1 for r in rows[:k] if ids[r] in lane.truth[qid]) for k in KS}
        out[qid] = found
    return out


def recall(lane: Lane, hits: dict[str, dict[int, int]], k: int, qids: list[str]) -> float:
    n = sum(len(lane.truth[q]) for q in qids)
    return sum(hits[q][k] for q in qids) / n if n else float("nan")


def zero_overlap_recall(lane: Lane, ranked: dict[str, list[int]], k: int,
                        qids: list[str]) -> tuple[float, int]:
    ids = [gid for gid, _, _ in lane.gallery]
    g_text = {gid: t for gid, _, t in lane.gallery}
    q_text = {q: t for q, _, t in lane.queries}
    total = found = 0
    for q in qids:
        top = {ids[r] for r in [r for r in ranked.get(q, []) if ids[r] != q][:k]}
        for g in lane.truth[q]:
            if not (_tokens(q_text[q]) & _tokens(g_text[g])):
                total += 1
                found += g in top
    return (found / total if total else float("nan")), total


def bootstrap_gain(lane: Lane, arm_hits: list[dict], base_hits: dict, k: int,
                   qids: list[str], entity: dict[str, str], n: int, seed: int = 0):
    """Paired entity bootstrap of the recall@k gain, averaged over seeds."""
    by_entity: dict[str, list[str]] = defaultdict(list)
    for q in qids:
        by_entity[entity[q]].append(q)
    ents = sorted(by_entity)
    rng = random.Random(seed)
    gains = []
    for _ in range(n):
        sample = [q for e in (rng.choice(ents) for _ in ents) for q in by_entity[e]]
        denom = sum(len(lane.truth[q]) for q in sample)
        base = sum(base_hits[q][k] for q in sample) / denom
        arm = statistics.fmean(sum(h[q][k] for q in sample) / denom for h in arm_hits)
        gains.append(arm - base)
    gains.sort()
    return gains[int(0.025 * n)], gains[int(0.975 * n) - 1]


def rank_tfidf(lane: Lane, k: int):
    from arche.retrieval import CharNgramIndex

    index = CharNgramIndex([t for _, _, t in lane.gallery])
    extra = 1 if lane.self_join else 0
    return {q: [r for r, _ in index.search(t, k + extra)] for q, _, t in lane.queries}, index


def rank_encoder(lane: Lane, encoder, k: int):
    from arche.retrieval import EncoderIndex

    index = EncoderIndex([t for _, _, t in lane.gallery], encoder)
    extra = 1 if lane.self_join else 0
    found = index.search_many([t for _, _, t in lane.queries], k + extra)
    return {q: [r for r, _ in hits] for (q, _, _), hits in zip(lane.queries, found,
                                                              strict=True)}, index


def rrf(*rankings: dict[str, list[int]], k: int, c: int = 60) -> dict[str, list[int]]:
    out = {}
    for q in rankings[0]:
        score: dict[int, float] = defaultdict(float)
        for ranking in rankings:
            for pos, r in enumerate(ranking.get(q, [])):
                score[r] += 1.0 / (c + pos + 1)
        out[q] = sorted(score, key=lambda r: (-score[r], r))[:k]
    return out


def union_blocker(lane: Lane, qids: list[str]) -> dict[str, Any]:
    from arche.resolve._block import union_candidate_pairs

    a, b = lane.blocker_records
    pairs, _ = union_candidate_pairs(a, b, text_fields=lane.blocker_fields)
    cands: dict[str, set[str]] = defaultdict(set)
    for i, j in pairs:
        if a[i]["id"] != b[j]["id"]:
            cands[a[i]["id"]].add(b[j]["id"])
    n = sum(len(lane.truth[q]) for q in qids)
    found = sum(len(lane.truth[q] & cands[q]) for q in qids)
    return {"recall": round(found / n, 4),
            "mean_candidates_per_query": round(statistics.fmean(len(cands[q]) for q in qids), 1)}


def cpu_latency(model_dir: str, prefix: str, texts: list[str]) -> dict[str, float]:
    from arche.retrieval import TextEncoder

    enc = TextEncoder(model_dir, prefix=prefix, device="cpu", batch_size=1,
                      threads=CPU_THREADS)
    enc.encode(texts[:5])
    times = []
    for t in texts[:200]:
        t0 = time.perf_counter()
        enc.encode([t])
        times.append((time.perf_counter() - t0) * 1000)
    times.sort()
    size = sum(f.stat().st_size for f in Path(enc.path).glob("*.safetensors"))
    return {"threads": CPU_THREADS, "p50_ms": round(times[len(times) // 2], 1),
            "p95_ms": round(times[int(0.95 * len(times)) - 1], 1),
            "model_mb": round(size / 1e6, 1)}


# ── main ─────────────────────────────────────────────────────────────────────


def run_lane(name: str, args) -> dict[str, Any]:
    from arche.retrieval import TextEncoder
    from arche.retrieval._train import TrainConfig, fine_tune

    lane = LANES[name]()
    entity = {q: e for q, e, _ in lane.queries}
    test = [q for q, e, _ in lane.queries if split_of(name, e) == "test"]
    dev = [q for q, e, _ in lane.queries if split_of(name, e) == "dev"]
    kmax = max(KS)
    print(f"\n== {name}: {len(lane.queries)} queries ({len(dev)} dev / {len(test)} test), "
          f"gallery {len(lane.gallery)}", flush=True)
    result: dict[str, Any] = {"queries": {"dev": len(dev), "test": len(test)},
                              "gallery": len(lane.gallery), "sources": lane.sources,
                              "note": lane.note, "arms": {}}

    def report(arm: str, ranked, pins=None, extra=None):
        hits = hits_by_query(lane, ranked)
        z, zn = zero_overlap_recall(lane, ranked, PASS["k"], test)
        row = {f"recall@{k}": round(recall(lane, hits, k, test), 4) for k in KS}
        row["recall@10_zero_overlap"] = round(z, 4)
        row["zero_overlap_pairs"] = zn
        if pins:
            row["pins"] = pins
        if extra:
            row.update(extra)
        result["arms"][arm] = row
        print(f"  {arm:34} " + "  ".join(f"@{k} {row[f'recall@{k}']:.3f}" for k in KS)
              + f"  zero-overlap@10 {row['recall@10_zero_overlap']:.3f} (n={zn})", flush=True)
        return hits

    result["arms"]["union_blocker"] = union_blocker(lane, test)
    print(f"  {'union_blocker':34} recall {result['arms']['union_blocker']['recall']:.3f} "
          f"at {result['arms']['union_blocker']['mean_candidates_per_query']} candidates/query")
    tf_ranked, tf_index = rank_tfidf(lane, kmax)
    tf_hits = report("tfidf_char3", tf_ranked, tf_index.pins())

    for model in ZERO_SHOT:
        enc = TextEncoder(model, prefix=PREFIX.get(model, ""))
        ranked, index = rank_encoder(lane, enc, kmax)
        report(f"zero_shot:{model.split('/')[-1]}", ranked, index.pins())

    pairs, negs = training_data(lane, tf_ranked)
    result["training"] = {"pairs": len(pairs),
                          "with_hard_negatives": sum(1 for n in negs if n)}
    tuned_hits, tuned_ranked, model_dirs = [], [], []
    for seed in SEEDS:
        out = MODELS / name / f"seed{seed}"
        if not (out / "arche_training.json").exists() or args.retrain:
            fine_tune(BASE, pairs, out, hard_negatives=negs,
                      config=TrainConfig(epochs=args.epochs, seed=seed,
                                         prefix=PREFIX.get(BASE, "")),
                      log=lambda m, s=seed: print(f"    seed {s}: {m}", flush=True))
        enc = TextEncoder(str(out), prefix=PREFIX.get(BASE, ""))
        ranked, index = rank_encoder(lane, enc, kmax)
        tuned_ranked.append(ranked)
        tuned_hits.append(report(f"fine_tuned:seed{seed}", ranked, index.pins(),
                                 {"training": json.loads(
                                     (out / "arche_training.json").read_text())["pairs_sha256"]}))
        model_dirs.append(str(out))
    report("rrf(tfidf, fine_tuned:seed0)", rrf(tf_ranked, tuned_ranked[0], k=kmax))

    # The decision, by the rule above.
    k = PASS["k"]
    gains = [recall(lane, h, k, test) - recall(lane, tf_hits, k, test) for h in tuned_hits]
    lo, hi = bootstrap_gain(lane, tuned_hits, tf_hits, k, test, entity, PASS["bootstrap"])
    lo50, _ = bootstrap_gain(lane, tuned_hits, tf_hits, 50, test, entity, PASS["bootstrap"])
    z_tf = result["arms"]["tfidf_char3"]["recall@10_zero_overlap"]
    z_ft = statistics.fmean(result["arms"][f"fine_tuned:seed{s}"]["recall@10_zero_overlap"]
                            for s in SEEDS)
    latency = cpu_latency(model_dirs[0], PREFIX.get(BASE, ""), [t for _, _, t in lane.queries])
    checks = {
        "mean_gain>=2pt": statistics.fmean(gains) >= PASS["min_mean_gain"],
        "bootstrap_lower>0": lo > PASS["bootstrap_lower_gt"],
        "zero_overlap_improves": (z_ft > z_tf) if z_tf == z_tf else None,
        "k50_lower>-1pt": lo50 > PASS["k50_lower_gt"],
        "cpu_latency": latency["p95_ms"] <= PASS["cpu_p95_ms_max"],
        "model_size": latency["model_mb"] <= PASS["model_mb_max"],
    }
    verdict = "pass" if all(v is not False for v in checks.values()) else "fail"
    result["decision"] = {
        "mean_gain_at_10": round(statistics.fmean(gains), 4),
        "gain_per_seed": [round(g, 4) for g in gains],
        "bootstrap95_at_10": [round(lo, 4), round(hi, 4)],
        "bootstrap95_lower_at_50": round(lo50, 4),
        "zero_overlap_at_10": {"tfidf": z_tf, "fine_tuned_mean": round(z_ft, 4)},
        "cpu": latency, "checks": checks, "verdict": verdict,
    }
    print(f"  -> {verdict.upper()}: gain@10 {statistics.fmean(gains):+.4f} "
          f"[{lo:+.4f}, {hi:+.4f}], checks {checks}", flush=True)
    return result


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--lanes", nargs="*", default=list(LANES))
    ap.add_argument("--epochs", type=int, default=2)
    ap.add_argument("--retrain", action="store_true")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    import torch

    started = time.time()
    out: dict[str, Any] = {
        "schema": "arche.e0_retrieval.v1", "base": BASE, "seeds": list(SEEDS),
        "pass_rule": PASS, "torch": torch.__version__,
        "device": "cuda" if torch.cuda.is_available() else "cpu",
        "lanes": {name: run_lane(name, args) for name in args.lanes},
        "not_run": {"nigeria_facilities": "no adjudicated pairs yet"},
    }
    out["seconds"] = round(time.time() - started, 1)
    if args.out:
        Path(args.out).write_text(json.dumps(out, indent=2, sort_keys=True) + "\n",
                                  encoding="utf-8")
        print(f"\nwrote {args.out}")


if __name__ == "__main__":
    main()
