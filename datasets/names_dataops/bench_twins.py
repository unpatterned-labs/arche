# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0
"""Twins and parents: people who share a surname, birth date or address and must not merge.

Febrl 4 (``bench_febrl.py``) has no twins, so a looser matcher can only gain on it. Here list B
also gets 800 people built from Febrl's own names, seeded, each different from the person they are
built on:

* 300 **twins**: same surname, birth date and address; a first name unlike the original's
  (Jaro-Winkler under 0.70)
* 300 **hard twins**: as twins, but the first name looks like a misspelling (0.80 to 0.95). With
  only
  a name, a birth date and an address these cannot be told from a typo; they are counted apart
* 200 **parents**: same surname and address, another birth date and first name

No ID. A match to any of them is a false merge.

    uv run python datasets/names_dataops/bench_twins.py            # print
    uv run python datasets/names_dataops/bench_twins.py --update   # record the result
"""
from __future__ import annotations

import json
import random
import sys
from collections import Counter
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))

from bench_febrl import FILES, _fetch, _truth_key  # noqa: E402

OUT = _HERE / "bench_twins_result.json"
SEED = 20261125
COUNTS = {"twin": 300, "hard_twin": 300, "parent": 200}
PACKS = ("person", "person_typos")


def build() -> tuple[list[dict], list[dict], dict[str, str]]:
    """List A, list B with the added people, and which added person is of which kind."""
    from jellyfish import jaro_winkler_similarity as jw

    a, b = (list(_fetch(f)) for f in FILES)
    rng = random.Random(SEED)
    given = sorted({r["given_name"] for r in a if len(r["given_name"]) > 2})
    base = [r for r in a if r["given_name"] and r["surname"] and r["date_of_birth"]
            and r["address_1"]]
    rng.shuffle(base)
    kind: dict[str, str] = {}
    added: list[dict] = []

    def add(row: dict, k: str, **change: str) -> None:
        rid = f"rec-{k}{len(added)}-x"
        added.append({**row, "rec_id": rid, **change})
        kind[rid] = k

    n: Counter = Counter()
    for row in base:
        name = row["given_name"]
        if n["hard_twin"] < COUNTS["hard_twin"]:
            alike = [g for g in given if g != name and 0.80 <= jw(g, name) <= 0.95]
            if alike:
                add(row, "hard_twin", given_name=rng.choice(alike))
                n["hard_twin"] += 1
                continue
        if n["twin"] < COUNTS["twin"]:
            k, change = "twin", {}
        elif n["parent"] < COUNTS["parent"]:
            k, change = "parent", {"date_of_birth": rng.choice(base)["date_of_birth"]}
        else:
            break
        add(row, k, given_name=rng.choice([g for g in given if jw(g, name) < 0.70]), **change)
        n[k] += 1
    assert dict(n) == COUNTS, n
    return a, b + added, kind


def _record(r: dict) -> dict:
    return {"id": r["rec_id"],
            "name": " ".join(x for x in (r["given_name"], r["surname"]) if x),
            "birth_date": r["date_of_birth"],
            "address": " ".join(x for x in (
                r["street_number"], r["address_1"], r["address_2"], r["suburb"],
                r["postcode"], r["state"]) if x)}


def score(pack: str) -> dict:
    from arche.resolve import reconcile

    a, b, kind = build()
    n_true = len({_truth_key(r["rec_id"]) for r in a}
                 & {_truth_key(r["rec_id"]) for r in b if r["rec_id"] not in kind})
    res = reconcile([_record(r) for r in a], [_record(r) for r in b],
                    entity=pack, id_field="id")
    true: set[str] = set()
    wrong: Counter = Counter()
    review = 0
    for e in res["matches"]:
        if e["decision"] == "review":
            review += 1
        elif e["decision"] == "match":
            if e["b_id"] in kind:
                wrong[kind[e["b_id"]]] += 1
            elif _truth_key(e["a_id"]) == _truth_key(e["b_id"]):
                true.add(_truth_key(e["a_id"]))
            else:
                wrong["other"] += 1
    fp = sum(wrong.values())
    return {"pairs_truth": n_true, "true_merges": len(true), "false_merges": fp,
            "precision": round(len(true) / (len(true) + fp), 4) if true else 0.0,
            "recall": round(len(true) / n_true, 4), "review": review,
            **{f"merged_{k}": wrong[k] for k in (*COUNTS, "other")}}


def main() -> int:
    doc = {"benchmark": "Febrl 4 with twins, hard twins and parents added", "seed": SEED,
           "added": COUNTS, "fields": ["name", "address", "birth_date"],
           "configurations": {p: score(p) for p in PACKS}}
    for p, r in doc["configurations"].items():
        print(p, json.dumps(r))
    if "--update" in sys.argv:
        OUT.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
        print(f"wrote {OUT.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
