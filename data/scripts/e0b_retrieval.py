#!/usr/bin/env python
"""E0b, retrieval on lanes that leave room: E0's experiment, re-run where it can fail.

E0 could not pass anywhere: TF-IDF already found 97.6-100% of true pairs at
k=10 on all four lanes, so a 2-point gain was out of reach before training
started. E0b keeps E0's arms, splits and pass rule unchanged, and changes only
how lanes are chosen: a lane is admitted on its *development* split alone, and
only if character 3-gram TF-IDF recall@10 there is at most 0.92. The test
split is not read until the preregistration file
(data/er_bench/benchmark_e0b_preregistration.json) is written.

Candidate lanes:

* ``amazon_google``  Leipzig Amazon-GoogleProducts (CC BY 4.0, in data/er_bench/products)
* ``wikidata_ng``    Wikidata names of non-person items located in Nigeria: the
                     label and aliases in en, fr, ha, yo, ig, pcm of one item are
                     one entity (CC0)
* ``wikidata_wa``    the same for nine other West African countries, in en, fr,
                     wo, tw, ak, ee, bm, ff (CC0)

The Wikidata extracts live in ~/.cache/arche/e0b/ with the SPARQL that fetched
them, their sha256 sums and the fetch time; they are not committed. People
(``P31 = Q5``) are excluded: a person's name variants are identity data, and
this experiment does not need them.

Each Wikidata lane keeps at most 4,000 entities and 8 distinct names per
entity, chosen by a salted hash (not the split hash), so the self-join fits the
pure-Python TF-IDF index. Names are deduplicated case- and space-insensitively.

Amendment 1 (benchmark_e0b_amendment_1.json), made after the first test run was
read: Wikidata *properties* (ids ``P...``, e.g. "Boomplay ID") are excluded, as
they are not things located anywhere. ``--amendment 1`` applies it, re-checks
admission on dev, trains fresh models under models/e0b_a1, and refuses to run
unless the amendment's pass rule is E0's.

    python data/scripts/e0b_retrieval.py --headroom          # dev only
    python data/scripts/e0b_retrieval.py --out data/er_bench/benchmark_e0b_retrieval_result.json
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("e0_retrieval", HERE / "e0_retrieval.py")
e0 = importlib.util.module_from_spec(_spec)
sys.modules["e0_retrieval"] = e0
_spec.loader.exec_module(e0)

CACHE = Path.home() / ".cache" / "arche" / "e0b"
PREREG = e0.DATA / "er_bench" / "benchmark_e0b_preregistration.json"
ADMIT_MAX_DEV_TFIDF_AT_10 = 0.92
MAX_ENTITIES = 4000
MAX_NAMES = 8
AMENDMENTS = {1: e0.DATA / "er_bench" / "benchmark_e0b_amendment_1.json"}
#: Set by --amendment 1: keep only Wikidata items (Q ids), never properties (P ids).
ITEMS_ONLY = False
MODELS_DIR = "e0b"


def _salted(*parts: str) -> int:
    return int(hashlib.sha256("\0".join(("e0b-sample",) + parts).encode()).hexdigest()[:12], 16)


def lane_amazon_google() -> e0.Lane:
    folder = e0.DATA / "er_bench" / "products"
    amazon = {r["id"]: r for r in e0._read_csv(folder / "Amazon.csv")}
    google = {r["id"]: r for r in e0._read_csv(folder / "GoogleProducts.csv")}
    truth: dict[str, set[str]] = defaultdict(set)
    for r in e0._read_csv(folder / "Amzon_GoogleProducts_perfectMapping.csv"):
        if r["idAmazon"] in amazon and r["idGoogleBase"] in google:
            truth[r["idAmazon"]].add(r["idGoogleBase"])

    def text(name: str, maker: str) -> str:
        return " | ".join(x for x in (name, maker) if x)

    ent_g = {g: f"e{a}" for a, gs in truth.items() for g in gs}
    queries = [(a, f"e{a}", text(amazon[a]["title"], amazon[a].get("manufacturer", "")))
               for a in sorted(truth)]
    gallery = [(g, ent_g.get(g), text(r["name"], r.get("manufacturer", "")))
               for g, r in google.items()]
    block_a = [{"id": a, "name": amazon[a]["title"]} for a in sorted(truth)]
    block_b = [{"id": g, "name": r["name"]} for g, r in google.items()]
    return e0.Lane("amazon_google", queries, gallery, dict(truth),
                   sources={f: e0._sha(folder / f) for f in
                            ("Amazon.csv", "GoogleProducts.csv",
                             "Amzon_GoogleProducts_perfectMapping.csv")},
                   blocker_records=(block_a, block_b))


def _wikidata(name: str, pattern: str) -> e0.Lane:
    files = sorted(CACHE.glob(pattern))
    if not files:
        raise FileNotFoundError(f"no {pattern} in {CACHE}: fetch with the SPARQL in "
                                f"{CACHE / 'queries'}")
    names: dict[str, dict[str, str]] = defaultdict(dict)
    for f in files:
        with f.open(encoding="utf-8", newline="") as fh:
            for r in csv.DictReader(fh):
                shown = " ".join(r["name"].split())
                if shown:
                    q = r["item"].rsplit("/", 1)[1]
                    if ITEMS_ONLY and not q.startswith("Q"):
                        continue
                    names[q].setdefault(" ".join(shown.casefold().split()), shown)
    multi = sorted((q for q, v in names.items() if len(v) > 1), key=lambda q: _salted(name, q))
    keep = multi[:MAX_ENTITIES]
    gallery = []
    for q in sorted(keep):
        variants = sorted(names[q].values(), key=lambda s: _salted(name, q, s))[:MAX_NAMES]
        gallery += [(f"{q}#{i}", q, s) for i, s in enumerate(sorted(variants))]
    members: dict[str, set[str]] = defaultdict(set)
    for gid, ent, _ in gallery:
        members[ent].add(gid)
    queries = [(gid, ent, t) for gid, ent, t in gallery]
    truth = {gid: members[ent] - {gid} for gid, ent, _ in gallery}
    block = [{"id": gid, "name": t} for gid, _, t in gallery]
    return e0.Lane(name, queries, gallery, truth, self_join=True,
                   note=f"{len(keep)} of {len(multi)} multi-name entities, "
                        f"<= {MAX_NAMES} names each, salted-hash sample",
                   sources={f.name: e0._sha(f) for f in files},
                   blocker_records=(block, block))


def lane_wikidata_ng() -> e0.Lane:
    return _wikidata("wikidata_ng", "ng_*.csv")


def lane_wikidata_wa() -> e0.Lane:
    return _wikidata("wikidata_wa", "wa_*.csv")


CANDIDATES = {"amazon_google": lane_amazon_google, "wikidata_ng": lane_wikidata_ng,
              "wikidata_wa": lane_wikidata_wa}


def headroom() -> dict[str, Any]:
    """TF-IDF recall@10 on each candidate's development queries. Reads no test query."""
    out = {}
    for name, make in CANDIDATES.items():
        lane = make()
        dev = [q for q, e, _ in lane.queries if e0.split_of(name, e) == "dev"]
        dev_set = set(dev)
        sub = e0.Lane(name, [x for x in lane.queries if x[0] in dev_set], lane.gallery,
                      lane.truth, self_join=lane.self_join)
        ranked, _ = e0.rank_tfidf(sub, 10)
        hits = e0.hits_by_query(sub, ranked)
        r10 = e0.recall(sub, hits, 10, dev)
        z, zn = e0.zero_overlap_recall(sub, ranked, 10, dev)
        out[name] = {"dev_queries": len(dev), "gallery": len(lane.gallery),
                     "dev_tfidf_recall@10": round(r10, 4),
                     "dev_tfidf_recall@10_zero_overlap": round(z, 4),
                     "dev_zero_overlap_pairs": zn,
                     "admitted": r10 <= ADMIT_MAX_DEV_TFIDF_AT_10,
                     "sources": lane.sources, "note": lane.note}
        print(name, out[name]["dev_tfidf_recall@10"], "admitted" if out[name]["admitted"]
              else "rejected", flush=True)
    return out


def _stratum(a: str, b: str) -> str:
    import re

    def norm(s: str) -> str:
        return " ".join(re.sub(r"[^\w ]", " ", s.casefold()).split())

    if re.search(r"\d", a) or re.search(r"\d", b):
        return "has_digit_code"
    if any(re.fullmatch(r"[A-Z.&]{2,8}", s.strip()) for s in (a, b)):
        return "acronym"
    na, nb = norm(a), norm(b)
    if na == nb:
        return "punct_or_accent_only"
    if na in nb or nb in na:
        return "one_contains_other"
    return "shared_token" if e0._tokens(a) & e0._tokens(b) else "no_shared_token"


def strata(lanes: list[str]) -> dict[str, Any]:
    """Post hoc, added after the verdict: test recall@10 by pair type, TF-IDF
    against fine_tuned:seed0. Reads the trained models; decides nothing."""
    from arche.retrieval import TextEncoder

    out: dict[str, Any] = {}
    for name in lanes:
        lane = CANDIDATES[name]()
        test = [q for q, e, _ in lane.queries if e0.split_of(name, e) == "test"]
        tf, _ = e0.rank_tfidf(lane, 10)
        enc = TextEncoder(str(Path.home() / ".cache" / "arche" / "models" / MODELS_DIR / name
                              / "seed0"), prefix=e0.PREFIX.get(e0.BASE, ""))
        ft, _ = e0.rank_encoder(lane, enc, 10)
        ids = [g for g, _, _ in lane.gallery]
        text = {g: t for g, _, t in lane.gallery}
        agg: dict[str, list[int]] = {}
        for q in test:
            top_tf = {ids[r] for r in [r for r in tf[q] if ids[r] != q][:10]}
            top_ft = {ids[r] for r in [r for r in ft[q] if ids[r] != q][:10]}
            for g in lane.truth[q]:
                a = agg.setdefault(_stratum(text[q], text[g]), [0, 0, 0])
                a[0] += 1
                a[1] += g in top_tf
                a[2] += g in top_ft
        total = sum(a[0] for a in agg.values())
        out[name] = {s: {"pairs": a[0], "share": round(a[0] / total, 3),
                         "tfidf@10": round(a[1] / a[0], 3),
                         "fine_tuned_seed0@10": round(a[2] / a[0], 3),
                         "gain_contribution_pt": round(100 * (a[2] - a[1]) / total, 2)}
                     for s, a in sorted(agg.items())}
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--headroom", action="store_true", help="dev-only admission check")
    ap.add_argument("--strata", action="store_true",
                    help="post hoc: test recall@10 by pair type (after the run)")
    ap.add_argument("--epochs", type=int, default=2)
    ap.add_argument("--retrain", action="store_true")
    ap.add_argument("--out", default=None)
    ap.add_argument("--amendment", type=int, choices=sorted(AMENDMENTS), default=None)
    args = ap.parse_args()
    global ITEMS_ONLY, PREREG, MODELS_DIR
    if args.amendment == 1:
        ITEMS_ONLY, PREREG, MODELS_DIR = True, AMENDMENTS[1], "e0b_a1"
    if args.headroom:
        print(json.dumps(headroom(), indent=2, sort_keys=True))
        return
    prereg = json.loads(PREREG.read_text(encoding="utf-8"))
    if args.strata:
        print(json.dumps(strata(prereg["lanes_admitted"]), indent=2, sort_keys=True))
        return
    if prereg["pass_rule"] != e0.PASS:
        raise SystemExit("pass rule differs from the preregistration; refusing to run")
    lanes = prereg["lanes_admitted"]
    e0.LANES.update(CANDIDATES)
    e0.MODELS = Path.home() / ".cache" / "arche" / "models" / MODELS_DIR
    import torch

    started = time.time()
    out: dict[str, Any] = {
        "schema": "arche.e0b_retrieval.v1", "base": e0.BASE, "seeds": list(e0.SEEDS),
        "amendment": args.amendment, "items_only": ITEMS_ONLY,
        "pass_rule": e0.PASS,
        "preregistration_sha256": "sha256:" + hashlib.sha256(PREREG.read_bytes()).hexdigest(),
        "torch": torch.__version__, "device": "cuda" if torch.cuda.is_available() else "cpu",
        "lanes": {name: e0.run_lane(name, args) for name in lanes},
    }
    out["seconds"] = round(time.time() - started, 1)
    if args.out:
        Path(args.out).write_text(json.dumps(out, indent=2, sort_keys=True) + "\n",
                                  encoding="utf-8")
        print(f"\nwrote {args.out}")


if __name__ == "__main__":
    main()
