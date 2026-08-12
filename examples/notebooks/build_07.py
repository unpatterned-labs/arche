# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0
"""Generate 07_places_on_a_public_benchmark.ipynb.

The notebook is the artefact; this script exists so it can be regenerated
rather than hand-edited as JSON. Run from the repo root:

    python examples/notebooks/build_07.py
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
# How does the place lane hold up on someone else's benchmark?

**Leipzig Geographic Settlements: 3,054 records, 4 sources, 820 clusters,
complete ground truth.**

Every place number arche has published came from a corpus we assembled: Kano
health facilities, London hospitals. Both measure recall, neither can measure a
false merge, and we labelled both. A benchmark you built and tuned against
cannot falsify you.

This one can. It is [published by the Database Group at
Leipzig](https://dbs.uni-leipzig.de/research/projects/benchmark-datasets-for-entity-resolution),
CC-BY-4.0, and its ground truth is **complete** — 820 clusters covering every
record, so any pair not in a cluster is a known non-match and precision becomes
measurable.

**The headline, stated the way it should be read.**

| | baseline | after one representation change |
|---|---|---|
| precision (pooled micro) | 0.9862 | 0.9733 |
| macro-precision by source pair, worst case | 0.9869 / 0.9702 | 0.9740 / 0.9464 |
| recall at auto-match | 0.7135 | 0.9205 |
| **surfaced recall** | 0.9654 | 0.9806 |
| **review queue** | 1,732 edges | 676 edges |

Read the last two rows before the third. Auto-match recall moves 20 points, but
**surfaced recall moves 1.5** — almost everything the change "found" was already
in the review queue. It is an automation result, not a discovery result, and
saying otherwise would be the most flattering available reading of our own data.

This notebook was pressure-tested by an adversarial reviewer before publication.
Several of the corrections below came from that review, including an arithmetic
impossibility in the published ground truth that we had not noticed.
""")

md("""
## Setup
""")

code("""
import json, re, sys, copy, hashlib
from collections import Counter
from itertools import combinations
from pathlib import Path
from statistics import median

REPO = Path.cwd()
while not (REPO / "packages" / "arche-core").exists() and REPO != REPO.parent:
    REPO = REPO.parent
sys.path.insert(0, str(REPO / "packages" / "arche-core" / "src"))

from arche.resolve import crosswalk, ENTITY_PACKS
from arche.resolve._matcher import haversine_km, split_place_name

DATA = REPO / "data" / "er_bench" / "places"

recs = {}
for line in open(DATA / "settlements.json", encoding="utf-8"):
    if not line.strip():
        continue
    o = json.loads(line); d = o["data"]
    recs[o["id"]] = {"id": o["id"], "name": d.get("label", ""),
                     "src": d.get("ontology", "").split("//")[-1].strip("/"),
                     "lat": d.get("lat"), "lon": d.get("lon")}

clusters = [json.loads(l)["data"]["clusteredVertices"]
            for l in open(DATA / "combinedSettlements_perfectMatch.json", encoding="utf-8")
            if l.strip()]

print(f"records  {len(recs):,}")
print(f"clusters {len(clusters):,}")
for s, n in Counter(r["src"] for r in recs.values()).most_common():
    print(f"  {n:>4}  {s}")
""")

md("""
## First: the ground truth has a defect

Before trusting a benchmark, check that it is internally consistent. The cluster
size histogram should account for exactly as many memberships as there are
records.
""")

code("""
sizes = Counter(len(c) for c in clusters)
slots = sum(len(c) for c in clusters)
print(f"cluster sizes: {dict(sorted(sizes.items()))}")
print(f"membership slots {slots}  vs  records {len(recs)}   <- these must match")

memb = Counter(v for c in clusters for v in c)
dupes = [v for v, n in memb.items() if n > 1]
print(f"\\nvertices appearing in more than one cluster: {dupes}")
for v in dupes:
    print(f"  vertex {v} = {recs[v]['name']!r}")
    for i, c in enumerate(clusters):
        if v in c:
            print(f"    in cluster #{i}: {c}")
""")

md("""
One record is filed in two clusters — once inside a genuine four-source cluster,
and once as a singleton cluster containing only itself. That is a defect in the
**published dataset**, not in our loader.

It is worth stating plainly because it is small, real, and easy to miss: a naive
reading gives 820 clusters when there are 819 real ones. It does **not** move
the pair denominator, because a singleton cluster contributes no pairs. We
carried on with 4,391 true pairs and recorded the defect rather than silently
de-duplicating it.
""")

code("""
truth = {}
for ci, c in enumerate(clusters):
    for a, b in combinations(sorted(set(c)), 2):
        truth[(a, b)] = ci

n = len(recs)
print(f"true pairs        {len(truth):,}")
print(f"all possible pairs{n*(n-1)//2:>12,}")
print(f"positive rate     {100*len(truth)/(n*(n-1)/2):.3f}%")

same_src = sum(1 for a, b in truth if recs[a]["src"] == recs[b]["src"])
print(f"\\nwithin-source true pairs: {same_src}  <- every cluster holds at most one record per source")

full4 = sum(1 for c in clusters if len(set(c)) == 4)
print(f"complete four-source clusters: {full4}, contributing {full4*6:,} pairs "
      f"({100*full4*6/len(truth):.1f}% of all true pairs)")
""")

md("""
**That last number is the most important caveat in this notebook.** 96.6% of the
true pairs come from 707 fully-overlapping four-source entities. Pooled
edge-level precision therefore weights those 707 entities six times each, and a
single hard entity can contribute six correlated successes or six correlated
failures. Read every pooled figure below as *pooled micro edge precision*, not
as "98.6% of settlements were resolved correctly".
""")

md("""
## The provenance gate, which runs before any matching

Kano taught us this the hard way: GRID3 and OpenStreetMap looked like two
independent sources and were not, because one had ingested the other. A matcher
scoring well on a pair like that is partly reading a copied key.

The check is median separation between true pairs plus the fraction sitting at
**exactly** 0.00 km. Two sources that independently observed the same town do
not agree to the last decimal.

A caveat the adversarial review insisted on, and it is correct: this conditions
on positives only and its threshold is not pre-registered, so it is **not** a
statistical test of independence. It identifies a provenance *risk* stratum. We
report all six pairs and flag rather than delete.
""")

code("""
srcs = sorted({r["src"] for r in recs.values()})
print(f"{'source pair':<42} {'pairs':>6} {'median km':>10} {'at exactly 0.00':>17}")
print("-" * 78)
for s1, s2 in combinations(srcs, 2):
    ds = []
    for a, b in truth:
        ra, rb = recs[a], recs[b]
        if {ra["src"], rb["src"]} != {s1, s2}:
            continue
        if None in (ra["lat"], ra["lon"], rb["lat"], rb["lon"]):
            continue
        ds.append(haversine_km(float(ra["lat"]), float(ra["lon"]),
                               float(rb["lat"]), float(rb["lon"])))
    z = sum(1 for d in ds if d < 1e-9)
    flag = "  <- PROVENANCE RISK" if z / len(ds) > 0.5 else ""
    print(f"{s1[:19]+' x '+s2[:19]:<42} {len(ds):>6} {median(ds):>10.3f} "
          f"{z:>6} ({100*z/len(ds):>5.1f}%){flag}")
print("\\nKano GRID3 x OpenStreetMap, for contrast: median 0.000 km, 59% at exactly 0.00")
""")

md("""
NYTimes × GeoNames sits at **91% exact coordinate agreement** — worse than the
Kano pair we disqualified. Those coordinates were copied, not independently
observed. DBpedia × Freebase at 25% is a milder version of the same thing, and
unsurprising: both ingest Wikipedia.

We keep all six pairs in the headline and report the flagged stratum separately.
Deleting it would be special pleading; ignoring it would be worse.
""")

md("""
## Running arche

`crosswalk` links two lists, so four sources become six pairwise runs. Those
runs are disjoint in edge space — a DBpedia–Freebase pair cannot also appear in
a NYTimes–GeoNames run — so summing counts across them double-counts no edge.
It does re-weight *entities*, which is the caveat recorded above.

**This is a pairwise evaluation of a clustering benchmark, and that is a
deliberate choice.** arche emits pairwise edges; it does not do transitive
clustering, which is gated on the roadmap precisely because of what the last
section of this notebook demonstrates.
""")

code("""
def rows(src):
    \"\"\"Records exactly as published — no preprocessing of any kind.\"\"\"
    out = []
    for r in recs.values():
        if r["src"] != src:
            continue
        d = {"id": r["id"], "name": r["name"]}
        if r["lat"] is not None:
            d["lat"], d["lon"] = r["lat"], r["lon"]
        out.append(d)
    return out


PACK = ENTITY_PACKS["place"]

# The shipped capability, declared rather than hand-rolled. `strip_qualifier`
# makes a text comparator judge the core name; `kind: "qualifier"` weighs the
# appended region separately. Both read the same `name` field, so the records
# above stay untouched.
QUAL = copy.deepcopy(PACK)
for _spec in QUAL:
    if _spec.get("kind") in ("placename", "tftoken"):
        _spec["strip_qualifier"] = True
QUAL = QUAL + [{"field": "name", "kind": "qualifier", "weight": 1.0}]

print("split_place_name demonstrates what the flag does:")
for _n in ("Petra (Jordan)", "Cordoba, Spain", "Split", "(Jordan)"):
    print(f"  {_n!r:24} -> {split_place_name(_n)}")


def evaluate(_unused, comparators):
    per = {}
    for s1, s2 in combinations(srcs, 2):
        gt = {k for k in truth if {recs[k[0]]["src"], recs[k[1]]["src"]} == {s1, s2}}
        res = crosswalk(rows(s1), rows(s2),
                        comparators=comparators, tf="place", id_field="id")
        pred = {(min(e["a_id"], e["b_id"]), max(e["a_id"], e["b_id"])): e
                for e in res["matches"]}
        per[(s1, s2)] = {"gt": gt, "pred": pred}
    return per


def report(label, per):
    T = F = GT = RVt = RVf = MISS = 0
    macro = []
    for d in per.values():
        gt, pred = d["gt"], d["pred"]
        tp = sum(1 for k, e in pred.items() if e["decision"] == "match" and k in gt)
        fp = sum(1 for k, e in pred.items() if e["decision"] == "match" and k not in gt)
        RVt += sum(1 for k, e in pred.items() if e["decision"] == "review" and k in gt)
        RVf += sum(1 for k, e in pred.items() if e["decision"] == "review" and k not in gt)
        MISS += len(gt - set(pred))
        T += tp; F += fp; GT += len(gt)
        macro.append(tp / (tp + fp) if tp + fp else 0)
    P, R = T / (T + F), T / GT
    print(f"{label}")
    print(f"  precision (pooled micro) {P:.4f}      recall {R:.4f}")
    print(f"  macro-P by source pair   {sum(macro)/len(macro):.4f}      worst pair {min(macro):.4f}")
    print(f"  surfaced recall          {(T+RVt)/GT:.4f}      blocking recall {1-MISS/GT:.4f}")
    print(f"  auto {T} true / {F} FALSE MERGES   review queue {RVt+RVf} ({RVt} true, {RVf} false)")
    return {"T": T, "F": F, "S": (T + RVt) / GT, "RV": RVt + RVf}


baseline = report("BASELINE - shipped place pack, names as published", evaluate(False, PACK))
""")

md("""
Precision 0.986, and only 44 false merges. That is a strong result and it is the
opposite profile from arche's bibliographic run, where precision was the weak
axis.

Recall 0.714 is the problem. But surfaced recall is **0.965** — the missing
pairs are overwhelmingly sitting in the review queue, not lost. arche is
abstaining, not failing. So the question is *why*.
""")

code("""
worst = ("data.nytimes.com", "dbpedia.org")
d = evaluate(False, PACK)[worst]
review_true = [(k, e) for k, e in d["pred"].items()
               if e["decision"] == "review" and k in d["gt"]][:10]
print(f"TRUE pairs sitting in review, {worst[0]} x {worst[1]}\\n")
print(f"{'':36}{'':34} {'score':>6} {'distinct':>9}")
for k, e in review_true:
    a, b = recs[k[0]], recs[k[1]]
    geo = "geo" if "distance_km" in e["evidence"] else "NO-GEO"
    print(f"  {a['name'][:32]:34} <-> {b['name'][:30]:32} {e['score']:>6.3f} "
          f"{e['distinctive_max']:>9.3f}  {geo}")
""")

md("""
## The diagnosis: it is not the gate

Look at the `distinct` column — `distinctive_max` is 0.79 to 0.93, comfortably
above the 0.75 floor. **The distinctiveness gate is clearing.** What fails is
the score, which sits at 0.55–0.69 against a 0.70 threshold.

The cause is visible in the names. The four sources use three incompatible
conventions for the same place:
""")

code("""
qualified = lambda s: "(" in s or "," in s
for s in srcs:
    rs = [r for r in recs.values() if r["src"] == s]
    ex = [r["name"] for r in rs[:3]]
    withxy = sum(1 for r in rs if r["lat"] is not None)
    print(f"{s:<24} qualified {100*sum(1 for r in rs if qualified(r['name']))/len(rs):>5.1f}%   "
          f"coords {100*withxy/len(rs):>5.1f}%   e.g. {ex}")
""")

md("""
`Marseille (France)` against `Marseille` is one settlement written two ways. The
name comparator sees the country qualifier as part of the identifying string and
dilutes the similarity with it. DBpedia also carries coordinates on only 57.5%
of its records, so geography frequently cannot rescue the pair.

This is a **representation** problem, not a threshold problem — and arche
already has the machinery. Move the qualifier into its own field so the name
comparator compares names and the qualifier is scored separately.
""")

code("""
split = report("QUALIFIER SPLIT - qualifier moved to its own field", evaluate(True, QUAL))

print()
print("Is that a discovery gain or an automation gain?")
print(f"  auto-matched true pairs   {baseline['T']} -> {split['T']}  (+{split['T']-baseline['T']})")
print(f"  surfaced recall           {baseline['S']:.4f} -> {split['S']:.4f}  "
      f"(+{round((split['S']-baseline['S'])*len(truth))} pairs newly surfaced)")
already = (split["T"] - baseline["T"]) - round((split["S"] - baseline["S"]) * len(truth))
print(f"  => {already} of the {split['T']-baseline['T']} were ALREADY surfaced in review at baseline")
print(f"  review queue              {baseline['RV']} -> {split['RV']} edges "
      f"({100*(baseline['RV']-split['RV'])/baseline['RV']:.0f}% less human work)")
""")

md("""
## State that honestly

Recall moves 0.713 → 0.919, which looks like a twenty-point discovery. It is
not. Surfaced recall moves 0.965 → 0.981 — about 67 genuinely new pairs. The
other ~837 were already in the review queue and simply crossed the auto-match
threshold.

That is still a real and valuable result: **the review queue shrinks by 61%**,
which is 61% less human adjudication for the same evidence. But it is a
calibration and automation win, and a system can inflate F1 simply by becoming
more willing to auto-accept what it had already found. Precision pays for it —
pooled 0.986 → 0.973, and the worst source pair 0.970 → 0.946.

## Does the qualifier split survive held-out data?

The splitter was written after looking at these names, which makes it model
selection on the test set even though it now ships in the library. The weakest honest check is a split **by cluster**,
so no entity appears on both sides.
""")

code("""
half = {ci: int(hashlib.md5(str(ci).encode()).hexdigest(), 16) % 2
        for ci in range(len(clusters))}
base_per, qual_per = evaluate(False, PACK), evaluate(True, QUAL)
for h in (0, 1):
    line = f"  half {h}: "
    for nm, per in (("baseline", base_per), ("split", qual_per)):
        T = GT = 0
        for d in per.values():
            gt = {k for k in d["gt"] if half[truth[k]] == h}
            T += sum(1 for k, e in d["pred"].items() if e["decision"] == "match" and k in gt)
            GT += len(gt)
        line += f"{nm} R={T/GT:.4f} (n={GT})   "
    print(line)
""")

md("""
Recall replicates on both halves — 0.700 → 0.919 and 0.727 → 0.920. The effect
is not an artefact of one subset.

Two things this does **not** prove, and they matter. Precision is not cleanly
splittable, because a false edge belongs to no cluster and so cannot be assigned
to a half; only recall is reported above. And both halves share the same four
sources, so this tests entity generalisation, not *format* generalisation — and
the qualifier convention is a property of the source, not the entity. A real
test needs a corpus with different naming conventions.

## The review queue, and how it is treated

A review edge is not a failure. It is the engine declining to spend a merge it
cannot justify. What matters is whether the queue is small enough to work and
whether the true pairs in it are findable.
""")

code("""
per = evaluate(True, QUAL)
rows_out = []
for (s1, s2), d in per.items():
    rv = [(k, e) for k, e in d["pred"].items() if e["decision"] == "review"]
    t = sum(1 for k, _ in rv if k in d["gt"])
    rows_out.append((f"{s1[:14]} x {s2[:14]}", len(rv), t, len(rv) - t))
print(f"{'source pair':<34} {'queue':>6} {'true':>6} {'false':>6}  yield")
for nm, n, t, f in sorted(rows_out, key=lambda r: -r[1]):
    print(f"{nm:<34} {n:>6} {t:>6} {f:>6}  {100*t/n if n else 0:>5.1f}%")
print(f"\\nA reviewer working the whole queue sees {sum(r[1] for r in rows_out)} edges "
      f"to recover {sum(r[2] for r in rows_out)} true pairs.")
""")

md("""
## What happens if you close the loop naively

The benchmark is a *clustering* benchmark. arche stops at pairwise edges, and
the roadmap gates transitive clustering deliberately. This is what that gate is
protecting against.

Take the auto-match edges and run union-find, the obvious thing to do next.
""")

code("""
edges = {k: e for d in per.values() for k, e in d["pred"].items()
         if e["decision"] == "match"}
parent = {i: i for i in recs}
def find(x):
    while parent[x] != x:
        parent[x] = parent[parent[x]]; x = parent[x]
    return x
for a, b in edges:
    ra, rb = find(a), find(b)
    if ra != rb:
        parent[ra] = rb
comp = {}
for i in recs:
    comp.setdefault(find(i), []).append(i)

induced = set()
for c in comp.values():
    for a, b in combinations(sorted(c), 2):
        induced.add((a, b))
edge_fp = sum(1 for k in edges if k not in truth)
clust_fp = len(induced - set(truth))
print(f"components {len(comp)}   (truth: {len(clusters)} clusters)")
print(f"size histogram {dict(sorted(Counter(len(c) for c in comp.values()).items()))}")
print(f"\\nfalse pairs, edge level     {edge_fp}")
print(f"false pairs, after closure  {clust_fp}   <- {clust_fp/edge_fp:.1f}x amplification")

over = [c for c in comp.values() if len(c) > 4]
print(f"\\ncomponents larger than 4 (IMPOSSIBLE - only 4 sources, <=1 record each): {len(over)}")
for c in sorted(over, key=len, reverse=True)[:3]:
    print(f"  size {len(c)}: {[recs[i]['name'][:24] for i in c[:7]]}")
""")

md("""
**111 false edges become 365 false pairs.** One bad edge bridges two correct
components and every record on one side becomes wrongly linked to every record
on the other.

The examples are the whole argument. Three different Oxfords — Connecticut,
Mississippi, England — fused into a single entity. Manchester in Vermont, New
Hampshire and England, likewise. Each bridge is individually plausible at the
edge level and catastrophic at the entity level.

This dataset also hands us a **provable invariant**: four sources, at most one
record per source per cluster, so no true cluster can exceed four members. Every
oversized component is wrong *by construction*, with no labels required. That is
a bridge detector you can run on unlabelled production data whenever you know
your source cardinality — and it is the shape the roadmap's gated clustering
work should take: drop non-distinctive edges before components form, and flag
bridge records to review rather than merging through them.

## What this establishes, and what it does not

**Establishes.**

* On a public, complete-ground-truth place benchmark that we neither built nor
  labelled, the shipped place pack reaches pooled edge precision **0.986** with
  44 false merges, and surfaced recall **0.965**.
* The recall gap is a naming-convention mismatch, not a gate failure —
  `distinctive_max` clears the floor on the abstaining pairs.
* Moving the qualifier into its own field cuts the review queue by **61%** at a
  cost of 1.3 points of pooled precision, and the recall effect replicates on
  held-out clusters.
* Naive transitive closure amplifies false merges **3.3x** and creates 19
  structurally impossible components. Gating clustering is justified by
  measurement, not caution.

**Does not establish.**

* **Not a clustering result.** These are pairwise metrics. Cluster-level claims
  need B-cubed or LEA and an explicit conflict policy, and arche has neither yet.
* **96.6% of true pairs come from 707 four-source entities.** Pooled precision
  weights those entities six times each; edges are not independent observations,
  so an edge-level confidence interval would be wrong. Use a cluster-level
  bootstrap.
* **The qualifier split is model selection on this corpus.** The splitter, the
  weight, and the field layout were all chosen after seeing these names, and the
  convention is source-specific. It needs a differently-formatted corpus. It is
  shipped **off by default** for exactly this reason: it changes Kano not at all
  and recovers nothing on London.
* **The provenance gate is not an independence test.** It conditions on
  positives and its threshold is not pre-registered. It flags risk; it proves
  nothing.
* **Settlements are not facilities.** These are towns and cities with one name
  and a qualifier. Hospitals, clinics and charge points have operators, brands
  and departments, and the containment problem that dominates London does not
  appear here at all.
* **The published ground truth contains a defect** (one record in two clusters).
  We found one. There may be others we did not.

*Related: [what is the false-merge rate?](06_what_is_the_false_merge_rate.ipynb)
· [does the engine generalise?](05_does_the_engine_generalise.ipynb)
· provenance in `data/er_bench/places/SOURCES.md`*
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

out = Path(__file__).resolve().parent / "07_places_on_a_public_benchmark.ipynb"
out.write_text(json.dumps(nb, indent=1, ensure_ascii=False), encoding="utf-8")
print(f"wrote {out}  ({len(cells)} cells)")
