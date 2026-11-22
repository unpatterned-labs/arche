#!/usr/bin/env python
"""E0f: do encoders trained on LEI names find a UK company's Companies House name?

GLEIF records, for every LEI registered with Companies House (registration
authority RA000585), the company number. That number links an LEI's legal name
to the company's current name on the register, which is a real KYB pair: the
same company, named by two registries that format names differently.

The query is the LEI legal name; the target is the Companies House name of the
same company number. The primary test set is the pairs whose names differ after
case and space folding. The E0d (``lei_global``) and E0e (``ch_gb``) training
entities are excluded, and so is any company number carried by two LEIs.

The gallery is every target plus salted-hash random Companies House names, to
about 20,000 in all. Two steps:

    uv run --package arche-core python data/scripts/e0f_lei_ch.py --build
    python data/scripts/e0f_lei_ch.py \
        --out data/er_bench/benchmark_e0f_lei_ch_result.json

``--build`` needs duckdb (the arche-core environment); the run needs torch. The
rule is in data/er_bench/benchmark_e0f_lei_ch_preregistration.json, written
before any ranking; the run refuses to start if the built files or the models
no longer match the digests recorded there. Only aggregates are written.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import re
import statistics
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA = HERE.parent
CACHE = Path.home() / ".cache" / "arche" / "lei_ch"
PAIRS, GALLERY = CACHE / "pairs.jsonl", CACHE / "gallery.jsonl"
PREREG = DATA / "er_bench" / "benchmark_e0f_lei_ch_preregistration.json"
CH_PARQUET = DATA / "_cache" / "companies_house" / "companies_2026-11-01.parquet"
MODELS = Path.home() / ".cache" / "arche" / "models"
MAX_TEST, GALLERY_SIZE = 4000, 20_000


def _salted(*parts: str) -> int:
    return int(hashlib.sha256("\0".join(("e0f",) + parts).encode()).hexdigest()[:12], 16)


def fold(s: str) -> str:
    return " ".join(s.casefold().split())


def company_number(raw: str) -> str:
    x = re.sub(r"\s", "", raw.upper())
    if x.isdigit():
        return x.zfill(8)
    if re.fullmatch(r"[A-Z]{2}\d{1,6}", x):
        return x[:2] + x[2:].zfill(6)
    return x


def sha(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


# ------------------------------------------------------------------ build


def build() -> None:
    import duckdb

    exclude = json.loads((CACHE / "exclude.json").read_text(encoding="utf-8"))
    no_lei, no_ch = set(exclude["lei_global_leis"]), set(exclude["ch_gb_company_numbers"])
    ch = dict(duckdb.sql(f"select CompanyNumber, CompanyName from '{CH_PARQUET}'").fetchall())
    with (CACHE / "lei_ra000585.csv").open(encoding="utf-8", newline="") as fh:
        lei = list(csv.DictReader(fh))
    per_number: dict[str, int] = {}
    for r in lei:
        n = company_number(r["ra_entity_id"])
        per_number[n] = per_number.get(n, 0) + 1
    counts = {"lei_ra000585_kept": len(lei)}
    pairs = []
    for r in lei:
        n = company_number(r["ra_entity_id"])
        if n not in ch:
            counts["not_on_register"] = counts.get("not_on_register", 0) + 1
            continue
        if per_number[n] > 1:
            counts["number_on_two_leis"] = counts.get("number_on_two_leis", 0) + 1
            continue
        if r["lei"] in no_lei or n in no_ch:
            counts["in_e0d_or_e0e_lanes"] = counts.get("in_e0d_or_e0e_lanes", 0) + 1
            continue
        if not r["legal_name"].strip() or not (ch[n] or "").strip():
            continue
        pairs.append({"lei": r["lei"], "number": n, "query": " ".join(r["legal_name"].split()),
                      "target": " ".join(ch[n].split())})
    counts["joined_usable"] = len(pairs)
    differ = [p for p in pairs if fold(p["query"]) != fold(p["target"])]
    counts["names_differ"] = len(differ)
    counts["identical_share"] = round(1 - len(differ) / len(pairs), 4)
    test = sorted(differ, key=lambda p: _salted("test", p["lei"]))[:MAX_TEST]
    test_numbers = {p["number"] for p in test}
    gallery = [{"id": p["number"], "text": p["target"]}
               for p in sorted(test, key=lambda p: p["number"])]
    pool = sorted((n for n in ch if n not in test_numbers and (ch[n] or "").strip()),
                  key=lambda n: _salted("gallery", n))
    gallery += [{"id": n, "text": " ".join(ch[n].split())}
                for n in pool[:GALLERY_SIZE - len(gallery)]]
    with PAIRS.open("w", encoding="utf-8") as fh:
        for p in sorted(test, key=lambda p: p["lei"]):
            fh.write(json.dumps(p, sort_keys=True) + "\n")
    with GALLERY.open("w", encoding="utf-8") as fh:
        for g in gallery:
            fh.write(json.dumps(g, sort_keys=True) + "\n")
    counts.update({"test_pairs": len(test), "gallery": len(gallery),
                   "pairs_sha256": sha(PAIRS), "gallery_sha256": sha(GALLERY)})
    (CACHE / "build.json").write_text(json.dumps(counts, indent=2, sort_keys=True) + "\n",
                                      encoding="utf-8")
    print(json.dumps(counts, indent=2, sort_keys=True))


# ------------------------------------------------------------------ run


def _e0():
    spec = importlib.util.spec_from_file_location("e0_retrieval", HERE / "e0_retrieval.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["e0_retrieval"] = mod
    spec.loader.exec_module(mod)
    return mod


def lane(e0):
    pairs = [json.loads(line) for line in PAIRS.open(encoding="utf-8")]
    gallery = [json.loads(line) for line in GALLERY.open(encoding="utf-8")]
    queries = [(f"q:{p['lei']}", p["number"], p["query"]) for p in pairs]
    g = [(x["id"], x["id"], x["text"]) for x in gallery]
    truth = {f"q:{p['lei']}": {p["number"]} for p in pairs}
    return e0.Lane("lei_ch", queries, g, truth), pairs


def arms() -> dict[str, list[str]]:
    return {"lei_trained": [str(MODELS / "e0d" / "lei_global" / f"seed{s}") for s in (0, 1, 2)],
            "ch_trained": [str(MODELS / "e0e" / "ch_gb" / f"seed{s}") for s in (0, 1, 2)]}


def run(out_path: str | None) -> None:
    from arche.retrieval import TextEncoder
    from arche.retrieval._encoder import weights_digest

    e0 = _e0()
    prereg = json.loads(PREREG.read_text(encoding="utf-8"))
    if sha(PAIRS) != prereg["data"]["pairs_sha256"] or \
            sha(GALLERY) != prereg["data"]["gallery_sha256"]:
        raise SystemExit("built files changed since the preregistration; refusing to run")
    for group, paths in arms().items():
        for p in paths:
            if weights_digest(p) != prereg["models"][group][Path(p).name]:
                raise SystemExit(f"{p} changed since the preregistration; refusing to run")
    ln, _ = lane(e0)
    qids = [q for q, _, _ in ln.queries]
    started = time.time()
    k_max = max(e0.KS)
    tf_rank, _ = e0.rank_tfidf(ln, k_max)
    print(f"tfidf ranked in {time.time() - started:.0f}s", flush=True)
    ranked: dict[str, dict] = {"tfidf_char3": tf_rank}
    zs = TextEncoder(e0.BASE, prefix=e0.PREFIX[e0.BASE])
    ranked["zero_shot:multilingual-e5-small"], _ = e0.rank_encoder(ln, zs, k_max)
    for group, paths in arms().items():
        for p in paths:
            enc = TextEncoder(p, prefix=e0.PREFIX[e0.BASE])
            ranked[f"{group}:{Path(p).name}"], _ = e0.rank_encoder(ln, enc, k_max)
            print(f"{group}:{Path(p).name} ranked", flush=True)
    ranked["rrf(tfidf, lei_trained:seed0)"] = e0.rrf(tf_rank, ranked["lei_trained:seed0"],
                                                     k=k_max)
    hits = {name: e0.hits_by_query(ln, r) for name, r in ranked.items()}
    table = {}
    for name, r in ranked.items():
        z, zn = e0.zero_overlap_recall(ln, r, 10, qids)
        table[name] = {f"recall@{k}": round(e0.recall(ln, hits[name], k, qids), 4)
                       for k in (1, 10, 50)}
        table[name]["recall@10_no_shared_word"] = round(z, 4)
        table[name]["no_shared_word_pairs"] = zn
        print(name, table[name], flush=True)
    entity = {q: q for q in qids}       # one query per company: a query bootstrap
    base = hits["tfidf_char3"]
    groups = {"lei_trained": [f"lei_trained:seed{s}" for s in (0, 1, 2)],
              "ch_trained": [f"ch_trained:seed{s}" for s in (0, 1, 2)],
              "rrf(tfidf, lei_trained:seed0)": ["rrf(tfidf, lei_trained:seed0)"],
              "zero_shot:multilingual-e5-small": ["zero_shot:multilingual-e5-small"]}
    gains = {}
    for g, names in groups.items():
        lo, hi = e0.bootstrap_gain(ln, [hits[n] for n in names], base, 10, qids, entity,
                                   prereg["rule"]["bootstrap"]["n"])
        mean = statistics.fmean(table[n]["recall@10"] for n in names) - \
            table["tfidf_char3"]["recall@10"]
        gains[g] = {"gain@10": round(mean, 4), "bootstrap95": [round(lo, 4), round(hi, 4)]}
        print(g, gains[g], flush=True)
    primary = gains["lei_trained"]
    verdict = {"transfer_shown": primary["gain@10"] >= 0.02 and primary["bootstrap95"][0] > 0,
               "no_harm": primary["bootstrap95"][0] > -0.02}
    result = {"schema": "arche.e0f_lei_ch.v1", "preregistration_sha256": sha(PREREG),
              "queries": len(qids), "gallery": len(ln.gallery), "arms": table,
              "gains_vs_tfidf": gains, "verdict": verdict,
              "seconds": round(time.time() - started, 1)}
    print(json.dumps(verdict))
    if out_path:
        Path(out_path).write_text(json.dumps(result, indent=2, sort_keys=True) + "\n",
                                  encoding="utf-8")
        print(f"wrote {out_path}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--build", action="store_true", help="write the pairs and gallery")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    if args.build:
        build()
    else:
        run(args.out)


if __name__ == "__main__":
    main()
