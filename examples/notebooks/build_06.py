# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0
"""Generate 06_what_is_the_false_merge_rate.ipynb.

The notebook is the artefact; this script exists so it can be regenerated
rather than hand-edited as JSON. Run from the repo root:

    python examples/notebooks/build_06.py
"""
from __future__ import annotations

import json
from pathlib import Path

MD, CODE = "markdown", "code"
cells: list[tuple[str, str]] = []


def md(text: str) -> None:
    cells.append((MD, text.strip("\n")))


def code(text: str) -> None:
    cells.append((CODE, text.strip("\n")))


md("""
# What is the false-merge rate?

**DBLP against ACM, on a benchmark whose ground truth is complete.**

Notebook 05 measured whether the engine generalises past Nigeria, and ended on
a caveat it could not resolve:

> *There is no precision instrument here at all. Nothing in this corpus can say
> whether an unlabelled match is right.*

This notebook is that instrument, and it exists because of a specific gap. Every
accuracy figure arche has published — Kano, London — measures **recall**: how
many true pairs we find. None of them can measure a **false merge**, because
none of them knows every pair that is *not* a match. Eighty-six labelled London
pairs say nothing about what the engine does to the other few thousand.

The [Leipzig benchmark sets](https://dbs.uni-leipzig.de/research/projects/benchmark-datasets-for-entity-resolution)
close that hole. Their mappings are **complete**: every pair absent from the
mapping is a known non-match, so precision becomes measurable. They are
CC-BY-4.0 and used widely enough that our numbers can be read against other
people's rather than only against ourselves.

Using someone else's benchmark is the point. A set we built, labelled and tuned
against cannot falsify us. This one can — and it did.

**What it found, in three parts.**

1. **Recall was never the problem.** 0.996 auto, 0.9996 surfaced, 0.9996 blocking.
2. **Precision was 0.85.** 391 false merges, hiding behind recall figures that
   implied ~0.95.
3. **The obvious fix makes it worse**, and the reason turns out to be structural
   rather than a tuning miss.
""")

md("""
## Setup

Nothing is monkeypatched here. This runs the shipped engine on shipped
behaviour — the point of the exercise is what an ordinary user gets.
""")

code("""
import csv
import sys
from collections import Counter
from pathlib import Path

REPO = Path.cwd()
while not (REPO / "packages" / "arche-core").exists() and REPO != REPO.parent:
    REPO = REPO.parent
sys.path.insert(0, str(REPO / "packages" / "arche-core" / "src"))

from arche.resolve import crosswalk

DATA = REPO / "data" / "er_bench"


def read(name):
    with open(DATA / name, encoding="utf-8-sig", errors="replace", newline="") as fh:
        return list(csv.DictReader(fh))


dblp, acm = read("DBLP2.csv"), read("ACM.csv")
truth = {(r["idDBLP"], r["idACM"]) for r in read("DBLP-ACM_perfectMapping.csv")}

print(f"DBLP  {len(dblp):>5} records")
print(f"ACM   {len(acm):>5} records")
print(f"truth {len(truth):>5} pairs  <- complete, so non-matches are known")
""")

md("""
The completeness of that third file is the whole reason this notebook can say
anything the others could not. `2,224` labelled pairs out of `2,616 x 2,294 =
6,001,104` possible ones — and every one of the remaining six million is a
labelled *non*-match, not an unknown.
""")

code("""
print(dblp[0])
print(acm[0])
""")

md("""
## The declaration

Hand-written, because **no bibliographic pack ships**. This is what an ordinary
user would write on day one: a title that carries most of the identity, authors,
and a year.

That matters for how you read the result. Tuning comparators against a public
benchmark until the number looks good is how published ER results stop meaning
anything, so nothing here is fitted to this dataset.
""")

code("""
FIELDS = ("title", "authors", "year")

BASE = [
    {"field": "title",   "kind": "name",    "weight": 3.0},
    {"field": "title",   "kind": "tftoken", "weight": 2.0},
    {"field": "authors", "kind": "name",    "weight": 2.0},
    {"field": "year",    "kind": "date",    "weight": 0.5},
]

A = [{"id": r["id"], **{f: r[f] for f in FIELDS}} for r in dblp]
B = [{"id": r["id"], **{f: r[f] for f in FIELDS}} for r in acm]
""")

md("""
## Scoring

Four numbers, not one. Reporting recall alone is exactly the habit this notebook
exists to correct.

* **blocking recall** — the ceiling. A pair never proposed cannot be recovered
  by any amount of scoring.
* **recall** — true pairs auto-matched.
* **surfaced recall** — true pairs auto-matched *or* queued for review. A pair a
  human is asked to look at is found, just not decided; reporting only
  auto-recall understates a system that deliberately abstains.
* **precision** — of everything auto-matched, how much was right. This is the
  one no other notebook in this repo can compute.
""")

code("""
def score(comparators, label):
    res = crosswalk(A, B, comparators=comparators, id_field="id")
    pred = {(e["a_id"], e["b_id"]): e for e in res["matches"]}
    tp = {k for k, e in pred.items() if e["decision"] == "match" and k in truth}
    fp = {k for k, e in pred.items() if e["decision"] == "match" and k not in truth}
    review = {k for k, e in pred.items() if e["decision"] == "review"}
    p = len(tp) / (len(tp) + len(fp)) if (tp or fp) else 0.0
    r = len(tp) / len(truth)
    out = {
        "label": label,
        "precision": p,
        "recall": r,
        "f1": 2 * p * r / (p + r) if (p + r) else 0.0,
        "surfaced": (len(tp) + len(review & truth)) / len(truth),
        "blocking": 1 - len(truth - set(pred)) / len(truth),
        "tp": len(tp), "fp": len(fp), "review": len(review),
        "_fp": fp,
    }
    print(f"{label:26}  P={p:.4f}  R={r:.4f}  F1={out['f1']:.4f}  "
          f"surfaced={out['surfaced']:.4f}  blocking={out['blocking']:.4f}")
    print(f"{'':26}  {len(tp)} true, {len(fp)} FALSE MERGES, {len(review)} queued")
    return out


baseline = score(BASE, "baseline")
""")

md("""
## Read that carefully

**Blocking recall 0.9996.** One true pair out of 2,224 was never proposed. The
union blocker is not the constraint.

**Recall 0.996.** On the numbers this repo usually publishes, this is an
excellent result and the notebook would end here.

**Precision 0.850.** 391 false merges. Nothing in Kano or London could have told
us this, and the recall figures pointed the other way.

Where do they come from?
""")

code("""
repeated = Counter(r["title"].strip().lower() for r in acm)
print("most repeated ACM titles:")
for title, n in sorted(repeated.items(), key=lambda kv: -kv[1])[:8]:
    print(f"  {n:>3}x  {title[:58]}")
""")

md("""
There it is. `Guest editorial`, `Book reviews`, `Reminiscences on Influential
Papers` — recurring editorial columns, published in different years by different
people, sharing a byte-identical title.

This is the **"General Hospital" defect**, which arche already fixed once for
places: agreement on a string that is identical everywhere read as evidence of
identity. It has reproduced here in a third domain, on data we neither chose nor
labelled, because no bibliographic frequency table ships to tell the engine that
`guest editorial` is a generic phrase.
""")

code("""
for a_id, b_id in list(baseline["_fp"])[:5]:
    x = next(r for r in dblp if r["id"] == a_id)
    y = next(r for r in acm if r["id"] == b_id)
    print(f"  {x['title'][:56]:58} {x['year']}")
    print(f"  {y['title'][:56]:58} {y['year']}")
    print()
""")

md("""
The false-merge set is more varied than the repeated-title count suggests. Some
are the recurring columns above. Others are genuinely different papers with
genuinely similar titles — an extended journal version of a conference paper a
year later, or two distinct papers on the same technique. Those are hard cases,
and no frequency table makes them easy.

But look at the years. Several of these pairs are separated by a field the
engine already has in front of it.

## A discriminator hiding in plain sight

Do the true pairs ever disagree on year?
""")

code("""
idx_a = {r["id"]: r for r in dblp}
idx_b = {r["id"]: r for r in acm}

agree = sum(1 for a, b in truth
            if idx_a[a]["year"].strip() == idx_b[b]["year"].strip())
print(f"year agrees on {agree}/{len(truth)} true pairs "
      f"({100 * agree / len(truth):.2f}%)")

by_title = {}
for r in acm:
    by_title.setdefault(r["title"].strip().lower(), []).append(r)
collisions = non_pair = separable = 0
for r in dblp:
    for s in by_title.get(r["title"].strip().lower(), []):
        collisions += 1
        if (r["id"], s["id"]) not in truth:
            non_pair += 1
            separable += r["year"].strip() != s["year"].strip()

print(f"exact title collisions: {collisions}")
print(f"  not a true pair:      {non_pair}")
print(f"  separable by year:    {separable}")
""")

md("""
**100.00%.** Year never disagrees on a true pair, and separates 213 of the false
ones. A discriminator this clean should be trivial to exploit.

So let us do the obvious thing and turn its weight up.
""")

code("""
def with_year_weight(w):
    comps = [dict(c) for c in BASE]
    comps[-1]["weight"] = w
    return comps


sweep = [score(with_year_weight(w), f"year weight {w}") for w in (2.0, 7.0)]
""")

md("""
## Precision *collapses*

0.850 at weight 0.5, 0.876 at 2.0, then 0.653 at 7.0. Turning up the field that
knows the answer made the system worse.

The reason is structural, not a tuning miss. **A weight is symmetric.** It
punishes disagreement, but it rewards agreement by exactly as much — and
*agreement on a year is not evidence*, because thousands of unrelated papers
share one. Turning up a discriminator turns up the noise it sits in.

It fails in the other direction too. A heavy weight drags genuinely-disagreeing
pairs *below the review floor*, so the edge is dropped entirely and a reviewer
never sees the conflict. Overcorrecting on true pairs, undercorrecting on false
ones, at the same time.

There is no weight that recovers what this field plainly knows. The instrument
is wrong, not the setting.

## Some attributes refute without confirming

This is the same argument the geographic veto already makes in arche — *two
buildings 143 km apart are not one building however alike their names* — but on
an attribute with no coordinates, in a domain with no pack.

`refutes_below` is the asymmetric form. Disagreement demotes to `review`;
agreement adds nothing beyond whatever `weight` already grants. It never demotes
to `no_match` — a refutation says a human must look, not that the answer is no —
and a missing value never refutes, because you cannot refute on absent evidence.
""")

code("""
REFUTING = [dict(c) for c in BASE]
REFUTING[-1]["refutes_below"] = 0.99

veto = score(REFUTING, "year refutes_below 0.99")

print()
print(f"precision {baseline['precision']:.4f} -> {veto['precision']:.4f}")
print(f"recall    {baseline['recall']:.4f} -> {veto['recall']:.4f}")
print(f"{baseline['fp'] - veto['fp']} false merges removed, "
      f"{baseline['tp'] - veto['tp']} true matches lost")
""")

md("""
**276 false merges removed. Zero true matches lost.**

Recall is unchanged to four decimal places. Surfaced recall is unchanged — the
demoted pairs went to the review queue, not into the dark.

**115 false merges survive**, and that number is the honest part of the result.
They are the same-year near-duplicates from the sample above — an extended
version of a paper, two papers on one technique. Year cannot refute those
because year does not disagree, and a bibliographic frequency table is the tool
for the ones that are merely generic. This fixed one failure mode, not matching.

One line in a declaration:

```python
{"field": "year", "kind": "date", "weight": 0.5, "refutes_below": 0.99}
```
""")

code("""
rows = [baseline, *sweep, veto]
print(f"{'configuration':26} {'P':>7} {'R':>7} {'F1':>7} {'TP':>6} {'FP':>6}")
print("-" * 64)
for m in rows:
    print(f"{m['label']:26} {m['precision']:>7.4f} {m['recall']:>7.4f} "
          f"{m['f1']:>7.4f} {m['tp']:>6} {m['fp']:>6}")
""")

md("""
## What this establishes, and what it does not

**Establishes.**

* arche's blocking and recall hold up on a third domain, on someone else's data,
  with no pack and no tuning.
* Its precision, measured for the first time, was **0.85** — materially below
  what the recall-only figures implied.
* A declarable refutation lifts that to **0.95** at zero recall cost, and no
  weight can do the same job.

**Does not establish.**

* **One benchmark, one entity type.** Bibliographic records are not products,
  people, or places. Abt-Buy and Amazon-Google are the obvious next runs and are
  deliberately not folded in here.
* **The 0.85 is not arche's precision.** It is this declaration's precision on
  this corpus. A bibliographic frequency table would very likely close much of
  the same gap by making `guest editorial` cheap, and that is untested.
* **`refutes_below` is not free in general.** Year is an unusually clean
  discriminator — 100.00% agreement on true pairs. An attribute that disagrees
  on even 2% of true pairs would trade recall for precision, and the trade has
  to be measured per attribute rather than assumed.
* **No shipped pack declares it.** Turning it on for `place` would move Kano's
  and London's published numbers, so that is a separate measured decision.
* **This corpus is clean.** Both sides are curated digital libraries. Real
  registries are messier than DBLP.

*Related: [does the engine generalise?](05_does_the_engine_generalise.ipynb)
· [the roadmap's refutation gap](https://unpatterned-labs.github.io/arche/concepts/roadmap/)
· data provenance in `data/er_bench/SOURCES.md`*
""")

nb = {
    "cells": [
        {
            "cell_type": kind,
            "metadata": {},
            "source": (src + "\n").splitlines(keepends=True),
            **({"execution_count": None, "outputs": []} if kind == CODE else {}),
        }
        for kind, src in cells
    ],
    "metadata": {
        "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
        "language_info": {"name": "python", "version": "3.12"},
    },
    "nbformat": 4,
    "nbformat_minor": 5,
}

out = Path(__file__).resolve().parent / "06_what_is_the_false_merge_rate.ipynb"
out.write_text(json.dumps(nb, indent=1, ensure_ascii=False), encoding="utf-8")
print(f"wrote {out}  ({len(cells)} cells)")
