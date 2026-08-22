# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0
"""Generate 16_three_matchers.ipynb.

    python examples/notebooks/build_16.py

arche's matcher, Splink's matcher, and arche running Splink as a backend, on the
same records against the same truth.
"""
from __future__ import annotations

import json
from pathlib import Path

MD, CODE = "markdown", "code"
cells: list[tuple[str, str]] = []
md = lambda t: cells.append((MD, t.strip("\n")))      # noqa: E731
code = lambda t: cells.append((CODE, t.strip("\n")))  # noqa: E731


md("""
# Three matchers, one task

**arche's own engine, Splink, and arche with Splink as its backend, on Febrl 4 against complete truth.**

There are two separate questions here and they are easy to run together by accident.

1. **Is arche's matcher as good as Splink's?** No, and this notebook shows by how much. That is why the backend exists.
2. **Does putting Splink behind arche change what Splink says?** It should not. An adapter that quietly moves the numbers is worse than no adapter.

The first question wants a gap. The second wants no gap at all. Watch them separately.

**What this cannot tell you.** Febrl is synthetic: its errors came from a generator with a model of how people mistype, which is not the same as how people mistype. A result here is evidence that the mechanism works as designed, not that the design suits your register.
""")

md("""
## The data

Febrl 4 is 5,000 original records and 5,000 duplicates of them, distributed with the [`recordlinkage`](https://github.com/J535D165/recordlinkage) package. Truth is in the record id: `rec-1070-org` and `rec-1070-dup-0` are the same person, so every pair not sharing that number is a known non-match. Complete truth is rare and it is why false merges are countable here.

`soc_sec_id` is excluded throughout. It is a near-unique synthetic identifier, and a linkage that has one is a much easier and much less interesting problem.
""")

code('''
import sys, warnings
warnings.filterwarnings("ignore")
sys.path.insert(0, "../../datasets/names_dataops")

from bench_febrl import _fetch, _truth_key
from bench_splink_febrl import splink_record, splink_settings, splink_train

a_rows = list(_fetch("dataset4a.csv"))
b_rows = list(_fetch("dataset4b.csv"))
n_true = len({_truth_key(r["rec_id"]) for r in a_rows}
             & {_truth_key(r["rec_id"]) for r in b_rows})

print(f"originals  {len(a_rows):,}")
print(f"duplicates {len(b_rows):,}")
print(f"true pairs {n_true:,}")
print()
print("one record, as Febrl ships it:")
for k, v in list(a_rows[0].items())[:8]:
    print(f"  {k:<16} {v}")
''')

md("""
## One scorer, three ways to reach it

The three arms differ only in who does the scoring.

**arche** uses the shipped `person` pack: a fuzzy name comparator, a token-frequency view of the name, a date comparator, and an address comparator, combined by a weighted mean and then judged by the distinctive-signal gate.

**Splink** uses the recipe from `bench_splink_febrl.py`, which follows Splink's own published Febrl example: Fellegi-Sunter with EM-trained m and u parameters and term-frequency adjustments.

**arche + Splink** calls `crosswalk(backend="splink")` and hands it *the same settings object* the second arm uses. That matters: a second copy of the configuration could drift until the two arms stopped being comparable, so they import the same function.

Note the two schemas. arche's pack wants one `name` field and one `address` field; the Splink recipe wants `given_name` and `surname` as separate columns with their own m and u. The adapter passes the caller's own schema through, which is the point of it.
""")

code('''
from arche.resolve import crosswalk

def arche_record(r):
    """Febrl row in the shape the shipped `person` pack expects."""
    address = " ".join(x for x in (r.get("street_number"), r.get("address_1"),
                                   r.get("address_2"), r.get("suburb"),
                                   r.get("postcode"), r.get("state")) if x)
    return {"id": r["rec_id"],
            "name": " ".join(x for x in (r.get("given_name"),
                                         r.get("surname")) if x),
            "address": address,
            "birth_date": r.get("date_of_birth", "")}

arche_a = [arche_record(r) for r in a_rows]
arche_b = [arche_record(r) for r in b_rows]

# The Splink recipe keeps the columns Febrl actually has.
splink_a = [splink_record(r) for r in a_rows]
splink_b = [splink_record(r) for r in b_rows]

print("arche sees :", sorted(arche_a[0]))
print("splink sees:", sorted(splink_a[0]))
''')

md("""
## Scoring, identically for all three

Every arm produces pairs it calls a match. Each is scored the same way: one best partner per left-hand record, then counted against truth.

A note on thresholds, because it is the thing most likely to mislead. arche's `match` is its own decision, reached by a weighted mean and a gate. Splink emits a probability with no portable scale, so a threshold has to be chosen and named. `p >= 0.99` is used here for both Splink arms, which is what Splink's published example clusters at.
""")

code('''
def score(pairs, label):
    """pairs: iterable of (left_id, right_id) called a match."""
    best = {}
    for left, right, prob in pairs:
        if left not in best or prob > best[left][1]:
            best[left] = (right, prob)
    tp = sum(1 for left, (right, _) in best.items()
             if _truth_key(left) == _truth_key(right))
    fp = len(best) - tp
    prec = tp / (tp + fp) if tp + fp else 0.0
    rec = tp / n_true
    return {"arm": label, "merged": len(best), "true": tp, "false": fp,
            "precision": round(prec, 4), "recall": round(rec, 4),
            "f1": round(2 * prec * rec / (prec + rec), 4) if prec + rec else 0.0}

def show(rows):
    print(f"{'arm':<26}{'merged':>8}{'true':>7}{'false':>7}"
          f"{'precision':>11}{'recall':>9}{'F1':>8}")
    for r in rows:
        print(f"{r['arm']:<26}{r['merged']:>8}{r['true']:>7}{r['false']:>7}"
              f"{r['precision']:>11.4f}{r['recall']:>9.4f}{r['f1']:>8.4f}")

results = []
''')

md("""
### Arm 1: arche's own engine
""")

code('''
res_arche = crosswalk(arche_a, arche_b, entity="person", id_field="id")
results.append(score(
    ((e["a_id"], e["b_id"], e["score"]) for e in res_arche["matches"]
     if e["decision"] == "match"),
    "arche"))
show(results)
print()
print("pins:", {k: v for k, v in res_arche["pins"].items()
                if k in ("engine", "block", "threshold", "distinctive_floor")})
''')

md("""
### Arm 2: Splink on its own

The same settings and training the adapter will be handed in arm 3, called directly here so there is something to compare against.
""")

code('''
import pandas as pd
from splink import DuckDBAPI, Linker

def frame(records):
    return pd.DataFrame([{"unique_id": r["id"],
                          **{k: v for k, v in r.items() if k != "id"}}
                         for r in records])

linker = Linker([frame(splink_a), frame(splink_b)],
                splink_settings(with_ssn=False),
                db_api=DuckDBAPI(), input_table_aliases=["a", "b"])
splink_train(linker, with_ssn=False)
predicted = linker.inference.predict(
    threshold_match_probability=0.5).as_pandas_dataframe()

at99 = predicted[predicted["match_probability"] >= 0.99]
results.append(score(zip(at99["unique_id_l"], at99["unique_id_r"],
                         at99["match_probability"], strict=False),
                     "splink, p >= 0.99"))
show(results)
''')

md("""
### Arm 3: arche with Splink as its backend

`splink_settings=` and `threshold=` are both required and neither has a default. arche will not invent a Splink configuration, because a configuration inferred from a comparator pack orders pairs about as well as a hand-written one and cannot calibrate them. And a Splink probability has no portable scale: `p >= 0.99` merges thousands of pairs here and nothing at all on the Nigerian school benchmark.
""")

code('''
res_backend = crosswalk(
    splink_a, splink_b,
    id_field="id",
    backend="splink",
    splink_settings=splink_settings(with_ssn=False),
    splink_train=lambda lk: splink_train(lk, with_ssn=False),
    threshold=0.99,
)
results.append(score(
    ((e["a_id"], e["b_id"], e["score"]) for e in res_backend["matches"]
     if e["decision"] == "match"),
    "arche + splink"))
show(results)
''')

md("""
## The two questions, answered separately

**Is arche's matcher as good as Splink's?** No. Compare rows 1 and 2 and the gap is large, on recall rather than precision: arche declines to merge pairs Splink is willing to merge. That is the distinctive-signal gate doing its job, and on this dataset it costs more than it saves.

**Does the adapter change what Splink says?** Compare rows 2 and 3. They should agree to within the noise of an unseeded training run, and if they do not, the adapter is doing something to the scores it has no business doing.
""")

code('''
splink_only = next(r for r in results if r["arm"].startswith("splink"))
backend = next(r for r in results if r["arm"] == "arche + splink")
gap = backend["recall"] - splink_only["recall"]

print(f"splink alone      recall {splink_only['recall']:.4f}  "
      f"true {splink_only['true']}  false {splink_only['false']}")
print(f"arche + splink    recall {backend['recall']:.4f}  "
      f"true {backend['true']}  false {backend['false']}")
print(f"difference        {gap:+.4f}")
print()
if abs(gap) < 0.01:
    print("The adapter is faithful. It is the same scorer with a decision")
    print("layer attached, which is the only honest claim to make for it.")
else:
    print("The adapter has MOVED the numbers. That is a defect, not a feature.")

print()
print("Splink's own recipe calls estimate_u_using_random_sampling without a")
print("seed, so both Splink arms wobble by a few pairs between runs. Read a")
print("small difference as noise and a large one as a bug.")
''')

md("""
## What arche adds, which is the reason for the adapter

The backend gives up arche's scoring and keeps everything arche puts around a score. That is visible in the result rather than asserted.
""")

code('''
edge = res_backend["matches"][0]
print("one edge from the Splink-backed run:")
for k in ("a_id", "b_id", "score", "decision", "evidence"):
    print(f"  {k:<14} {edge[k]}")
print(f"  {'decision_id':<14} {edge['decision_id'][:52]}...")
print()
print("pins, which name the scorer rather than a comparator set:")
for k, v in res_backend["pins"].items():
    print(f"  {k:<20} {str(v)[:56]}")
''')

md("""
Three things in that output are the argument for doing this at all.

**`decision_id`** is a content hash over the edge and the pins, so the decision has a reproducible address. Splink alone gives you a probability in a dataframe.

**`model_sha256` and `corpus_sha256`** name the trained model and the data it saw. A trained scorer is a function of its corpus, so a decision that depends on the model depends on both, and two decisions carrying different pins were never expected to agree.

**`evidence`** carries Splink's per-comparison levels rather than only the final probability, so a reviewer can see which fields agreed.

There is no `tf` pin, because Splink applies term frequency inside its own comparisons. Naming one would claim an input this decision never used.
""")

md("""
## Reproducing this

```sh
python examples/notebooks/build_16.py
jupyter nbconvert --to notebook --execute --inplace \\
    examples/notebooks/16_three_matchers.ipynb
```

Needs `arche-core[resolve]` for Splink and DuckDB. Febrl 4 downloads on first run and is cached under `data/_cache/febrl/`.

The same three arms run headless over Febrl 4 and the Nigerian school register in `datasets/names_dataops/bench_backend_compare.py`, which is where the numbers on the [benchmarks page](../../docs-site/docs/reference/benchmarks.md) come from.
""")


nb = {
    "cells": [
        {"cell_type": t, "metadata": {},
         **({"source": s.splitlines(keepends=True)} if t == MD else
            {"source": s.splitlines(keepends=True), "outputs": [],
             "execution_count": None})}
        for t, s in cells
    ],
    "metadata": {
        "kernelspec": {"display_name": "Python 3", "language": "python",
                       "name": "python3"},
        "language_info": {"name": "python"},
    },
    "nbformat": 4, "nbformat_minor": 5,
}

out = Path(__file__).parent / "16_three_matchers.ipynb"
out.write_text(json.dumps(nb, indent=1), encoding="utf-8")
print(f"wrote {out}  ({len(cells)} cells)")
