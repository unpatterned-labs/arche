#!/usr/bin/env python
"""X16: CQC providers against Companies House, scored on the provider's own company number.

Edges come from ``build_uk_ch.py``: per postcode district, the companies whose
name shares a distinctive word with a provider's, through
``reconcile(entity="organisation")`` as shipped. Truth is the company number CQC
records for the provider. The engine never sees it.

Arms, each kept one-to-one per district (a provider keeps one company, a company
one provider; higher score first, ties by id):

* ``exact``: folded names equal ("limited" read as "ltd", punctuation dropped)
  against **every** company registered in the district, and unique there.
* ``engine``: the engine's matches.

Metrics:

* ``precision``: links to the provider's own company / links of providers whose
  company is in the Companies House file;
* ``recall_all``: providers linked to their own company / providers whose
  company is in the file;
* ``recall_reachable``: the same over providers whose company is registered in
  their district and passes the first pass;
* the engine's ``review`` pairs, and how many hold the twin.

Rule and bounds: ``benchmark_x16_uk_ch_preregistration.json``. Only aggregates
are written.

    uv run --package arche-core python data/scripts/x16_uk_ch.py \\
        --out data/er_bench/benchmark_x16_uk_ch_result.json
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import io
import json
import math
import re
import sys
import time
import zipfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
_spec = importlib.util.spec_from_file_location("build_uk_ch", HERE / "build_uk_ch.py")
b = importlib.util.module_from_spec(_spec)
sys.modules["build_uk_ch"] = b
_spec.loader.exec_module(b)

PREREG = REPO / "data" / "er_bench" / "benchmark_x16_uk_ch_preregistration.json"


def sha(p: Path) -> str:
    return "sha256:" + hashlib.sha256(p.read_bytes()).hexdigest()


def fold(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", " ", name.casefold())
    s = re.sub(r"\blimited\b", "ltd", s)
    return " ".join(s.split())


def wilson(k: int, n: int, z: float = 1.96) -> list[float]:
    if n == 0:
        return [0.0, 1.0]
    p = k / n
    c = p + z * z / (2 * n)
    s = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return [round((c - s) / (1 + z * z / n), 5), round((c + s) / (1 + z * z / n), 5)]


def one_to_one(links: list[tuple[float, str, str]]) -> list[tuple[str, str]]:
    used_a: set[str] = set()
    used_b: set[str] = set()
    kept = []
    for _, a, bb in sorted(links, key=lambda x: (-x[0], x[1], x[2])):
        if a in used_a or bb in used_b:
            continue
        used_a.add(a)
        used_b.add(bb)
        kept.append((a, bb))
    return kept


def score(kept: list[tuple[str, str]], truth: dict[str, str], in_file: set[str],
          reachable: set[str]) -> dict[str, Any]:
    ev = [(a, x) for a, x in kept if truth[a] in in_file]
    correct = {a for a, x in ev if x == f"ch:{truth[a]}"}
    n_all = sum(1 for a in truth if truth[a] in in_file)
    return {"links": len(kept), "evaluable": len(ev), "correct": len(correct),
            "precision": round(len(correct) / len(ev), 5) if ev else None,
            "precision_wilson95": wilson(len(correct), len(ev)),
            "providers_in_file": n_all, "reachable": len(reachable),
            "recall_all": round(len(correct) / n_all, 5) if n_all else None,
            "recall_reachable": round(len(correct & reachable) / len(reachable), 5)
            if reachable else None}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", type=Path)
    args = ap.parse_args()
    prereg = json.loads(PREREG.read_text(encoding="utf-8"))
    if "sha256:" + hashlib.sha256(json.dumps(prereg["rule"], sort_keys=True).encode()) \
            .hexdigest() != prereg["rule_sha256"]:
        raise SystemExit("rule differs from its recorded digest")
    for name, digest in prereg["code"].items():
        if sha(HERE / name) != digest:
            raise SystemExit(f"{name} changed since the preregistration")
    if sha(b.OUT / "candidate_edges.csv") != prereg["edges"]:
        raise SystemExit("edges changed since the preregistration")
    started = time.time()
    providers = b.providers()
    truth = {r["id"]: r["company_number"] for r in providers}
    p_district = {r["id"]: r["district"] for r in providers}
    in_file: set[str] = set()
    with zipfile.ZipFile(b.ZIP) as z, z.open(z.namelist()[0]) as raw:
        reader = csv.reader(io.TextIOWrapper(raw, encoding="utf-8"))
        header = [h.strip() for h in next(reader)]
        i = header.index("CompanyNumber")
        for r in reader:
            if len(r) > i:
                in_file.add(b.number(r[i]))
    companies = b.companies()
    by_number = {}
    for d, rows in companies.items():
        for r in rows:
            by_number[r["id"][3:]] = (d, r["name"])
    vocab: dict[str, set[str]] = defaultdict(set)
    for r in providers:
        vocab[r["district"]] |= b.words(r["name"])
    reachable = {r["id"] for r in providers
                 if r["company_number"] in by_number
                 and by_number[r["company_number"]][0] == r["district"]
                 and b.words(by_number[r["company_number"]][1]) & vocab[r["district"]]}
    # exact arm, against every company in the district
    exact_links = []
    by_d_fold: dict[tuple[str, str], list[str]] = defaultdict(list)
    for d, rows in companies.items():
        for r in rows:
            by_d_fold[(d, fold(r["name"]))].append(r["id"])
    for r in providers:
        hits = by_d_fold.get((r["district"], fold(r["name"])), [])
        if len(hits) == 1:
            exact_links.append((1.0, r["id"], hits[0]))
    with (b.OUT / "candidate_edges.csv").open(encoding="utf-8") as fh:
        edges = list(csv.DictReader(fh))
    by_d_edges: dict[str, list[tuple[float, str, str]]] = defaultdict(list)
    review = Counter()
    for e in edges:
        if e["decision"] == "match":
            by_d_edges[e["district"]].append((float(e["score"]), e["cqc_id"], e["ch_id"]))
        elif e["decision"] == "review":
            review["pairs"] += 1
            review["pairs_on_twin"] += e["ch_id"] == f"ch:{truth[e['cqc_id']]}"
    engine_kept = [x for links in by_d_edges.values() for x in one_to_one(links)]
    exact_by_d: dict[str, list] = defaultdict(list)
    for x in exact_links:
        exact_by_d[p_district[x[1]]].append(x)
    exact_kept = [x for links in exact_by_d.values() for x in one_to_one(links)]
    arms = {"exact": score(exact_kept, truth, in_file, reachable),
            "engine": score(engine_kept, truth, in_file, reachable)}
    e, x = arms["engine"], arms["exact"]
    verdict = {"precision_at_least_99pct": e["precision"] >= 0.99
               and e["precision_wilson95"][0] >= 0.985,
               "recall_all_at_least_exact_plus_10pt": e["recall_all"] >= x["recall_all"] + 0.10}
    verdict["pass"] = all(verdict.values())
    result = {"schema": "arche.x16_uk_ch.v1", "preregistration_sha256": sha(PREREG),
              "providers": len(providers), "arms": arms, "engine_review": dict(review),
              "unreachable": {"company_not_in_file": sum(1 for r in providers
                                                         if r["company_number"] not in in_file),
                              "registered_in_other_district": sum(
                                  1 for r in providers if r["company_number"] in in_file
                                  and (r["company_number"] not in by_number
                                       or by_number[r["company_number"]][0] != r["district"])),
                              "no_shared_distinctive_word": sum(
                                  1 for r in providers if r["company_number"] in by_number
                                  and by_number[r["company_number"]][0] == r["district"]
                                  and r["id"] not in reachable)},
              "verdict": verdict, "seconds": round(time.time() - started, 1)}
    print(json.dumps(arms, indent=1), json.dumps(result["unreachable"]),
          json.dumps(review), json.dumps(verdict))
    if args.out:
        args.out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
