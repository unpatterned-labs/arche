#!/usr/bin/env python
"""X17: a legal-entity variant of the organisation pack, and an exact-name cascade.

X16 found two faults in ``reconcile(entity="organisation")`` on CQC providers
against Companies House: a shared address carried pairs whose names differ in a
distinctive word, and the premises refuter held pairs with the same name because
a registered office is not the trading address. X17 tests a pack built for a
register of legal entities:

* ``legal_entity``: the organisation pack without the premises refuter (an
  address supports, it never holds a pair back), plus ``rival`` on the name with
  the legal form stripped (each side naming something distinctive the other
  lacks holds the pair).

and two exact arms, because a company name is unique on the UK register:

* ``exact_district``: X16's exact arm (folded names equal, unique in the
  provider's postcode district);
* ``exact_national``: folded names equal and unique across the whole register,
  wherever the company is registered.

Cascades take an exact arm's links first, then the engine's for providers and
companies the exact arm left free.

The districts are split in two by ``sha256(district)``: ``dev`` (even) is where
the variant was shaped; ``test`` (odd) is scored once, under
``benchmark_x17_uk_ch_legal_entity_preregistration.json``.

    uv run --package arche-core python data/scripts/x17_uk_ch_legal_entity.py build --half dev
    uv run --package arche-core python data/scripts/x17_uk_ch_legal_entity.py score --half dev
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import io
import json
import sys
import time
import zipfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, HERE / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


b = _load("build_uk_ch")
x16 = _load("x16_uk_ch")
OUT = b.UK / "x17"
PREREG = REPO / "data" / "er_bench" / "benchmark_x17_uk_ch_legal_entity_preregistration.json"


def half_of(district: str) -> str:
    return "dev" if hashlib.sha256(district.encode()).digest()[0] % 2 == 0 else "test"


def variants() -> dict[str, dict[str, Any]]:
    from arche.resolve import ENTITY_PACKS

    base = [s for s in ENTITY_PACKS["organisation"] if s.get("kind") != "premises"]
    return {"no_premises": {"comparators": base, "tf": "organisation"},
            "legal_entity": {"entity": "legal_entity"}}


def build(half: str, only: str | None = None) -> None:
    from arche.resolve import reconcile

    started = time.time()
    left = [r for r in b.providers() if r["district"] and half_of(r["district"]) == half]
    right = b.companies()
    by_d: dict[str, list[dict]] = defaultdict(list)
    for r in left:
        by_d[r["district"]].append(r)
    OUT.mkdir(parents=True, exist_ok=True)
    for name, how in variants().items():
        if only and name != only:
            continue
        rows = []
        for d in sorted(by_d):
            lr = [{k: r[k] for k in ("id", "name", "address", "lat", "lon")} for r in by_d[d]]
            vocab = set().union(*(b.words(r["name"]) for r in lr))
            rr = [r for r in right.get(d, []) if b.words(r["name"]) & vocab]
            if not rr:
                continue
            result = reconcile(lr, rr, **how)
            for e in result["matches"]:
                rows.append({"decision": e["decision"], "score": e["score"], "district": d,
                             "cqc_id": e["a_id"], "ch_id": e["b_id"]})
        rows.sort(key=lambda r: (r["cqc_id"], r["ch_id"]))
        with (OUT / f"{half}_{name}.csv").open("w", encoding="utf-8", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=["decision", "score", "district", "cqc_id",
                                               "ch_id"])
            w.writeheader()
            w.writerows(rows)
        print(name, half, len(rows), dict(Counter(r["decision"] for r in rows)),
              round(time.time() - started), "s", flush=True)


def register() -> tuple[set[str], dict[str, list[str]]]:
    """Every company number on the register, and folded name -> numbers."""
    in_file: set[str] = set()
    by_fold: dict[str, list[str]] = defaultdict(list)
    with zipfile.ZipFile(b.ZIP) as z, z.open(z.namelist()[0]) as raw:
        reader = csv.reader(io.TextIOWrapper(raw, encoding="utf-8"))
        header = [h.strip() for h in next(reader)]
        i, n = header.index("CompanyNumber"), header.index("CompanyName")
        for r in reader:
            if len(r) > max(i, n):
                num = b.number(r[i])
                in_file.add(num)
                by_fold[x16.fold(r[n])].append(num)
    return in_file, by_fold


def links_from(path: Path) -> dict[str, list[tuple[float, str, str]]]:
    by_d: dict[str, list] = defaultdict(list)
    with path.open(encoding="utf-8") as fh:
        for e in csv.DictReader(fh):
            if e["decision"] == "match":
                by_d[e["district"]].append((float(e["score"]), e["cqc_id"], e["ch_id"]))
    return by_d


def cascade(first: list[tuple[str, str]], then: list[tuple[str, str]]) -> list[tuple[str, str]]:
    used_a = {a for a, _ in first}
    used_b = {x for _, x in first}
    return first + [(a, x) for a, x in then if a not in used_a and x not in used_b]


def score(half: str, edge_files: dict[str, Path]) -> dict[str, Any]:
    providers = [r for r in b.providers() if r["district"] and half_of(r["district"]) == half]
    truth = {r["id"]: r["company_number"] for r in providers}
    ids = set(truth)
    in_file, by_fold = register()
    companies = b.companies()
    by_number = {r["id"][3:]: (d, r["name"]) for d, rows in companies.items() for r in rows}
    vocab: dict[str, set[str]] = defaultdict(set)
    for r in providers:
        vocab[r["district"]] |= b.words(r["name"])
    reachable = {r["id"] for r in providers
                 if r["company_number"] in by_number
                 and by_number[r["company_number"]][0] == r["district"]
                 and b.words(by_number[r["company_number"]][1]) & vocab[r["district"]]}
    by_d_fold: dict[tuple[str, str], list[str]] = defaultdict(list)
    for d, rows in companies.items():
        for r in rows:
            by_d_fold[(d, x16.fold(r["name"]))].append(r["id"])
    ex_d: dict[str, list] = defaultdict(list)
    ex_n: list[tuple[float, str, str]] = []
    for r in providers:
        hits = by_d_fold.get((r["district"], x16.fold(r["name"])), [])
        if len(hits) == 1:
            ex_d[r["district"]].append((1.0, r["id"], hits[0]))
        nat = by_fold.get(x16.fold(r["name"]), [])
        if len(nat) == 1:
            ex_n.append((1.0, r["id"], f"ch:{nat[0]}"))
    kept: dict[str, list[tuple[str, str]]] = {
        "exact_district": [x for v in ex_d.values() for x in x16.one_to_one(v)],
        "exact_national": x16.one_to_one(ex_n)}
    for name, path in edge_files.items():
        by_d = links_from(path)
        kept[name] = [x for d, v in by_d.items() if half_of(d) == half
                      for x in x16.one_to_one(v) if x[0] in ids]
    for name in list(edge_files):
        for ex in ("exact_district", "exact_national"):
            kept[f"{ex}+{name}"] = cascade(kept[ex], kept[name])
    return {"half": half, "providers": len(providers),
            "arms": {k: x16.score(v, truth, in_file, reachable) for k, v in kept.items()}}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("step", choices=["build", "score"])
    ap.add_argument("--half", choices=["dev", "test"], required=True)
    ap.add_argument("--out", type=Path)
    ap.add_argument("--only", help="build one variant")
    args = ap.parse_args()
    if args.half == "test":
        prereg = json.loads(PREREG.read_text(encoding="utf-8"))
        rule = "sha256:" + hashlib.sha256(
            json.dumps(prereg["rule"], sort_keys=True).encode()).hexdigest()
        if rule != prereg["rule_sha256"]:
            raise SystemExit("rule differs from its recorded digest")
        for name, digest in prereg["code"].items():
            if x16.sha(REPO / name) != digest:
                raise SystemExit(f"{name} changed since the preregistration")
    if args.step == "build":
        build(args.half, args.only)
        return
    files = {"organisation": b.OUT / "candidate_edges.csv"}
    files |= {n: OUT / f"{args.half}_{n}.csv" for n in variants()
              if (OUT / f"{args.half}_{n}.csv").exists()}
    result = score(args.half, files)
    if args.half == "test":
        prereg = json.loads(PREREG.read_text(encoding="utf-8"))
        a = result["arms"]
        c = a["exact_national+legal_entity"]
        xd, xn = a["exact_district"], a["exact_national"]
        le, org = a["legal_entity"], a["organisation"]
        verdict = {
            "q1_cascade_precision_at_least_exact_district_minus_0.2pt":
                c["precision"] >= xd["precision"] - 0.002,
            "q1_cascade_wilson_lower_at_least_99pct": c["precision_wilson95"][0] >= 0.99,
            "q1_cascade_recall_all_at_least_exact_district_plus_5pt":
                c["recall_all"] >= xd["recall_all"] + 0.05,
            "q2_cascade_recall_all_at_least_exact_national_plus_0.5pt":
                c["recall_all"] >= xn["recall_all"] + 0.005,
            "q2_cascade_precision_at_least_exact_national_minus_0.2pt":
                c["precision"] >= xn["precision"] - 0.002,
            "q3_legal_entity_precision_at_least_organisation_plus_0.3pt":
                le["precision"] >= org["precision"] + 0.003,
            "q3_legal_entity_recall_all_at_least_organisation":
                le["recall_all"] >= org["recall_all"]}
        verdict["pass"] = all(verdict.values())
        result |= {"schema": "arche.x17_uk_ch.v1", "preregistration_sha256": x16.sha(PREREG),
                   "verdict": verdict}
    print(json.dumps(result, indent=1))
    if args.out:
        args.out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n",
                            encoding="utf-8")


if __name__ == "__main__":
    main()
