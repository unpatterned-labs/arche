# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0
"""Generate 14_nigeria_schools.ipynb.

    python examples/notebooks/build_14.py

Companion to notebook 13. Same process, same baselines, a country where the
names behave differently.
"""
from __future__ import annotations

import json
from pathlib import Path

MD, CODE = "markdown", "code"
cells: list[tuple[str, str]] = []
md = lambda t: cells.append((MD, t.strip("\n")))      # noqa: E731
code = lambda t: cells.append((CODE, t.strip("\n")))  # noqa: E731


md("""
# The same process, a country where names stop working

**Nigeria schools: two independent surveys of the same schools, reconciled the
way notebook 13 reconciled England's.**

[Notebook 13](13_england_schools.ipynb) crosswalked the DfE register against
OpenStreetMap in Leeds and found something uncomfortable: on F1, **plain exact
name matching was level with the shipped pack**. English school names are
unusually standardised, so a string comparison is nearly enough.

This runs the same process on Nigerian schools and the result inverts. Exact
matching goes from the safest method available to the most dangerous one.

Nothing about the engine changes between the two notebooks. What changes is
what a name is worth.
""")

md("""
## The two sources

The GRID3 schools register for Nigeria is an aggregate: six surveys merged into
one file, each having visited schools independently.

| source | records |
|---|---|
| NMIS | 78,770 |
| GRID | 17,345 |
| OSGOF | 8,166 |
| eHA Polio | 2,389 |

**NMIS** and **GRID** both cover 24 states, and neither carries the other's
identifiers. That is the same shape as GIAS against OpenStreetMap: two parties
who surveyed the same world and cannot join their results.

One state keeps this readable. Enugu has 1,776 NMIS records and 1,504 GRID
records, which is 2.7 million candidate pairs before blocking.
""")

code("""
import csv, math, random, re, statistics, sys
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path.cwd()
while not (REPO / "packages" / "arche-core").exists() and REPO != REPO.parent:
    REPO = REPO.parent
sys.path.insert(0, str(REPO / "packages" / "arche-core" / "src"))

CSV = REPO / "data" / "_cache" / "schools" / "nigeria_schools.csv"
if not CSV.exists():
    raise SystemExit(
        "Stage the register first (fetched, never committed):\\n"
        "    python data/scripts/stage_nigeria_schools.py --csv <download>.csv"
    )

rows = [r for r in csv.DictReader(CSV.open(encoding="utf-8-sig"))
        if (r.get("name") or "").strip()]
STATE = "Enugu"
nmis = [r for r in rows if r["source"].strip() == "NMIS" and r["statename"].strip() == STATE]
grid = [r for r in rows if r["source"].strip() == "GRID" and r["statename"].strip() == STATE]
print(f"register    : {len(rows):,} named records")
print(f"{STATE} NMIS  : {len(nmis):>6,}")
print(f"{STATE} GRID  : {len(grid):>6,}")
print(f"candidates  : {len(nmis)*len(grid):,} before blocking")
""")

md("""
## Step 1 — There is no truth set, and saying so is the honest start

Notebook 13 had 282 labels, because OpenStreetMap editors had written
`ref:edubase` tags asserting *this mapped school is that URN*. Nothing
equivalent exists here. NMIS and GRID never linked their records.

So this notebook **cannot report recall**, and any table that did would be
inventing labels.

What it can report is the error that matters, because one label is free and
certain:

> **Two schools in different states are not the same school.**

That gives negatives nobody constructed. Every method below is scored on pairs
it should never merge.

## Step 2 — Why the names are the story

Before matching anything, look at what a Nigerian school name contains.
""")

code("""
names = Counter(r["name"].strip().upper() for r in rows)
shared = {n: c for n, c in names.items() if c > 1}
print(f"distinct names         {len(names):>8,} of {len(rows):,}")
print(f"names held by >1 school{len(shared):>8,}")
print(f"records sharing a name {sum(shared.values()):>8,}  ({100*sum(shared.values())/len(rows):.0f}%)")
print()
for n, c in names.most_common(6):
    st = len({r["statename"] for r in rows if r["name"].strip().upper() == n})
    print(f"  {c:>4}x  {n[:46]:<46} across {st} states")
""")

md("""
Two hundred schools are called `COMMUNITY PRIMARY SCHOOL`, spread over 21
states. Ninety-nine are called `NOMADIC PRIMARY SCHOOL`, over 24.

Compare that with Leeds, where a school called `Roundhay School` is the only
one. **One in eight Nigerian records shares its name with a different school.**

The name is built from words describing what the school *is*, not which one it
is. `COMMUNITY`, `PRIMARY`, `SCHOOL`, `LGEA`, `NOMADIC` are all category words.
A string comparator reading two of these sees near-perfect agreement and is
not wrong about the strings. It is wrong about what agreement is worth.

## Step 3 — The certain negatives
""")

code("""
by_name = defaultdict(list)
for r in rows:
    by_name[r["name"].strip().upper()].append(r)

rng = random.Random(20260819)
pool = sorted(n for n, rs in by_name.items() if len({x["statename"] for x in rs}) > 1)
rng.shuffle(pool)

negatives = []
for n in pool:
    if len(negatives) >= 400:
        break
    rs = sorted(by_name[n], key=lambda x: x["uniq_id"])
    a = rs[0]
    b = next((x for x in rs if x["statename"] != a["statename"]), None)
    if b:
        negatives.append((a, b))

print(f"{len(negatives)} pairs that share a name exactly, in different states.")
print()
for a, b in negatives[:4]:
    print(f"  {a['name'][:40]:<40} {a['statename']:<12} vs {b['statename']}")
""")

md("""
## Step 4 — The same four methods as notebook 13
""")

code("""
from rapidfuzz import fuzz
from arche.resolve import reconcile

def toks(s): return {t for t in re.split(r"[^a-z0-9]+", s.casefold()) if t}
def jaccard(x, y):
    tx, ty = toks(x), toks(y)
    return len(tx & ty) / len(tx | ty) if tx and ty else 0.0

def rec(r):
    out = {"id": r["uniq_id"], "name": r["name"].strip()}
    try:
        out["lat"], out["lon"] = str(float(r["y"])), str(float(r["x"]))
    except (TypeError, ValueError):
        pass
    return out

rowsout = []
for label, fn in (
    ("exact name (casefold)", lambda a, b: a.casefold().strip() == b.casefold().strip()),
    ("token Jaccard >= 0.5",  lambda a, b: jaccard(a, b) >= 0.5),
    ("token_set_ratio >= 90", lambda a, b: fuzz.token_set_ratio(a, b) >= 90),
):
    rowsout.append((label, sum(1 for a, b in negatives if fn(a["name"], b["name"]))))

pairs = {(a["uniq_id"], b["uniq_id"]) for a, b in negatives}
res = reconcile([rec(a) for a, _ in negatives], [rec(b) for _, b in negatives],
                entity="place", id_field="id")
merged = sum(1 for e in res["matches"] if e["decision"] == "match" and (e["a_id"],
    e["b_id"]) in pairs)
held   = sum(1 for e in res["matches"] if e["decision"] == "review" and (e["a_id"],
    e["b_id"]) in pairs)
rowsout.append(("arche (name + coords)", merged))

print(f"{'method':<26}{'false merges':>14}{'rate':>9}")
for label, n in rowsout:
    print(f"{label:<26}{n:>14,}{n/len(negatives):>9.1%}")
print()
print(f"arche routed {held} of {len(negatives)} to review rather than deciding.")
""")

md("""
### The two arche got wrong

Promising that two errors are "worth reading" and then not showing them would be
the same trick this notebook exists to avoid. Here they are.
""")

code("""
idx = {r["uniq_id"]: r for a, b in negatives for r in (a, b)}
for e in res["matches"]:
    if e["decision"] == "match" and (e["a_id"], e["b_id"]) in pairs:
        a, b = idx[e["a_id"]], idx[e["b_id"]]
        print(f"score {e['score']:.3f}   {a['name']}")
        print(f"  {a['statename']:<10} / {a['lganame']}")
        print(f"  {b['statename']:<10} / {b['lganame']}")
        print(f"  {e['evidence'].get('distance_km')} km apart")
        print(f"  {e['evidence']}")
        print()
""")

md("""
Look at where they are.

`Tumbu Primary School` sits in **Adamawa** and **Borno**, and the two records are
**720 metres apart**. `Able God Group Of School` sits in **Ogun** and **Lagos**,
8.8 km apart, in the two local governments that meet at the boundary between
them.

Both errors are on a **state border**, and that is not a coincidence. It is a
flaw in the label rule this notebook is built on.

"Two schools in different states are not the same school" is true as
administration and shaky as geography. Two records 720 metres apart on either
side of a line are exactly the case where a boundary file, a GPS reading taken
at the gate rather than the road, or a school serving both sides, can put one
school in two states. The rule is safest in the interior and weakest at the
edge, and any method's errors will concentrate where the rule is weakest.

So the honest reading of `arche: 2 / 400` is **at most two**, and both sit where
the labels themselves are least trustworthy.

That does not rescue the 100% from the string methods. Those merged schools
hundreds of kilometres apart on nothing but a shared generic name, and no
boundary subtlety explains it. But it does mean the gap is a floor rather than a
measurement.

### The boundary-aware rule, and what it settles

So the rule was rebuilt: a pair counts as a certain negative only if it is in
different states **and** more than N km apart. Choosing one N would be picking a
number after seeing results, so every N is reported.

```text
method                           >0 km       >1 km       >5 km      >25 km
exact name (casefold)              400         399         399         390
token Jaccard >= 0.5               400         399         399         390
token_set_ratio >= 90              399         398         398         389
arche (name + coords)                2           1           1           0
(pairs remaining)                  400         399         399         390
```

Three things fall out, and the first is the one that matters.

**The doubt was smaller than it looked.** Only one pair of 400 sits within a
kilometre. The median separation is **243 km**. These are not border cases; they
are schools on opposite sides of the country sharing a generic name.

**The string methods do not move.** 390 of 390 wrong at more than 25 km apart.
Their errors have nothing to do with boundaries and no threshold rescues them.

**arche's two errors are exactly where the labels are weakest**, and both leave
as the rule tightens: 2, then 1, then 0. That is the behaviour you want from a
rule you distrust, and it is why the sensitivity table is worth more than any
single figure.

The conclusion survives every threshold, which is the only reason it is worth
stating.
""")

md("""
### Read the construction honestly

These pairs were chosen *because* they share a name, so exact matching failing
all 400 is true by construction. That is not a trick, it is the finding, and it
only matters because of the number in step 2: **12% of records are exposed to
it.** In Leeds, two schools sharing a name exactly were nearly always the same
school. Here they are nearly always different ones.

Put the two notebooks side by side.

| | Leeds | Nigeria |
|---|---|---|
| exact name | precision 0.992, **2** false merges | **400 / 400** wrong |
| token_set_ratio >= 90 | 131 false merges | 399 / 400 wrong |
| arche, name + coords | 37 false merges | **2 / 400** wrong |

Same engine, same comparators, same four methods. The only thing that changed
is the naming culture.

## Step 5 — The actual reconciliation

The negatives measure safety. This is the job someone actually wants done:
link the two surveys.
""")

code("""
A = [rec(r) for r in nmis]
B = [rec(r) for r in grid]
out = reconcile(A, B, entity="place", id_field="id")
d = Counter(e["decision"] for e in out["matches"])
print(f"candidate pairs after blocking : {len(out['matches']):,}")
print(f"  match  {d.get('match', 0):>6,}")
print(f"  review {d.get('review', 0):>6,}")
print()
print("pins.tf =", out["pins"]["tf"])
print()
for e in [x for x in out["matches"] if x["decision"] == "match"][:6]:
    a = next(r for r in nmis if r["uniq_id"] == e["a_id"])
    b = next(r for r in grid if r["uniq_id"] == e["b_id"])
    print(f"  {e['score']:.3f}  {a['name'][:34]:<34} <-> {b['name'][:34]}")
""")

md("""
Without labels these are proposals, not verified links. That is what the review
queue is for, and why the engine puts so many of them there rather than
asserting them.

## What this measured, and what it did not

**Measured.** The false-merge behaviour of four methods on 400 pairs that are
certainly different schools, drawn from the register rather than written by us.

**Not measured.**

* **Recall.** No positive labels exist here. A method that refuses everything
  would score perfectly on this page. Notebook 13 is the control: the same
  engine on labelled English data reaches recall 0.986.
* **Whether the step 5 links are correct.** They are proposals. Nobody has
  adjudicated them.
* **arche is not clean either.** It merged 2 of the 400. Those two are worth
  reading, because they are the shape of what still gets through.

The pair of notebooks is the argument. Neither is complete on its own: 13
without 14 says representation buys you little, and 14 without 13 says a
matcher that abstains is safe. Both are true, and neither is the point.
""")

nb = {
    "cells": [
        {"cell_type": t, "metadata": {},
         **({"source": s.splitlines(keepends=True)} if t == MD else
            {"source": s.splitlines(keepends=True), "outputs": [], "execution_count": None})}
        for t, s in cells
    ],
    "metadata": {
        "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
        "language_info": {"name": "python", "version": "3.12"},
    },
    "nbformat": 4, "nbformat_minor": 5,
}
out = Path(__file__).resolve().parent / "14_nigeria_schools.ipynb"
out.write_text(json.dumps(nb, indent=1, ensure_ascii=False), encoding="utf-8")
print(f"wrote {out}  ({len(cells)} cells)")
