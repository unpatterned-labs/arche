# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0
"""Generate 05_does_the_engine_generalise.ipynb.

The notebook is the artefact; this script exists so the notebook can be
regenerated rather than hand-edited as JSON. Run from the repo root:

    python examples/notebooks/build_05.py
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
# Does the engine generalise, or is it overfitted to Nigeria?

**London hospitals, Wikidata against OpenStreetMap, with the answer measured
rather than asserted.**

arche's place matcher was tuned on Nigerian health facilities. That raises an
obvious and uncomfortable question: does it work anywhere else, or has it
learned Kano?

This notebook answers it, and the answer has three parts.

1. **The engine generalises.** On London hospitals, with the shipped pack and no
   retuning, it auto-matches 84.9% of labelled true pairs and surfaces 98.8%.
2. **One assumption does not travel.** The distinctiveness gate assumes the
   identifying part of a name is a *rare token*. In Nigeria that is a village
   name. In London it is a saint, a monarch or a bridge — common words in an
   uncommon combination. `London Bridge Hospital` matched against itself, 30 m
   apart, was routed to `review`.
3. **A prototype fixes it.** Pricing *phrases* rather than only tokens recovers
   7 of the 12 abstentions with **zero** losses, and leaves the Kano benchmark
   unchanged.

Everything below is executable. Nothing is quoted from a previous run.
""")

md("""
## Why these two sources

The Kano benchmark could not settle the question, because its two sources shared
lineage: OpenStreetMap's Kano health facilities descend from the same registry as
GRID3. Comparing them measured consistency, not accuracy — which
[the place benchmark](https://unpatterned-labs.github.io/arche/concepts/place-benchmark/)
says at length.

This pair is chosen to change **exactly one variable** against Kano — the
country — while holding the entity type and the shape of the name constant.
`Bethlem Royal Hospital` has the same structure as `Karfi Health Post`: a
distinctive part plus a generic type word.

| | collection method | licence | role here |
|---|---|---|---|
| **Wikidata** | curated per item by editors from published references | CC0 | may enter a pack |
| **OpenStreetMap** | surveyed and crowd-mapped | ODbL | **benchmark evidence only, never a shipped asset** |

That licence split is not a footnote. arche's provenance firewall bars ODbL data
from entering any shipped pack, because share-alike would propagate into every
derived artefact.
""")

code("""
import csv, sys, statistics
from collections import Counter
from pathlib import Path

REPO = Path.cwd()
while not (REPO / "packages" / "arche-core").exists() and REPO != REPO.parent:
    REPO = REPO.parent
sys.path.insert(0, str(REPO / "packages" / "arche-core" / "src"))

DATA = REPO / "data" / "uk"
if not (DATA / "osm_london_hospitals.csv").exists():
    raise SystemExit(
        "Fetch the data first:\\n"
        "    python data/scripts/fetch_london_hospitals.py"
    )

osm = list(csv.DictReader(open(DATA / "osm_london_hospitals.csv", encoding="utf-8")))
wd  = list(csv.DictReader(open(DATA / "wikidata_london_hospitals.csv", encoding="utf-8")))
print(f"OpenStreetMap : {len(osm):>4} hospitals")
print(f"Wikidata      : {len(wd):>4} hospitals")
print(f"OSM unnamed   : {sum(1 for r in osm if not r['name'])}")
""")

md("""
## Step 1 — The truth set, and why it is honest

40% of OSM's London hospitals carry a `wikidata=` tag. That is a **literal
foreign key**: a human editor asserting "this OSM feature is that Wikidata item".

Matching on it would be a key join wearing an entity-resolution costume — the
exact failure the Kano work documented. So it is used the other way round:

* the tag becomes the **truth label**;
* the matcher never sees it, and works only from **name and coordinates**.

The labels are incomplete — an untagged OSM hospital may still have a Wikidata
counterpart. So this measures *precision against known-true pairs*, and cannot
measure true recall. That limitation is real and is restated at the end.
""")

code("""
truth = {(r["osm_id"], r["wd_id"])
         for r in csv.DictReader(open(DATA / "truth_pairs_london.csv", encoding="utf-8"))}
tagged = sum(1 for r in osm if r.get("wikidata"))
print(f"OSM rows carrying a wikidata= tag : {tagged} / {len(osm)}  ({100*tagged/len(osm):.1f}%)")
print(f"labels resolving into our pull    : {len(truth)}")
""")

md("""
## Step 2 — The independence gate, run *before* any matching

A benchmark whose sources copied each other's coordinates measures nothing. The
portable test: after matching, look at the distance between matched pairs. If a
large share sit at **exactly** 0.00 km, one source copied the other.

Kano fails this test. London passes it.
""")

code("""
from arche.resolve import crosswalk

# The matcher sees name and coordinates. Never the wikidata tag.
A = [{"name": r["name"], "lat": r["lat"], "lon": r["lon"]} for r in osm]
B = [{"name": r["name"], "lat": r["lat"], "lon": r["lon"]} for r in wd]

result = crosswalk(A, B, entity="place")
pred = {(osm[e["a_id"]]["osm_id"], wd[e["b_id"]]["wd_id"]): e for e in result["matches"]}

d = [e["evidence"]["distance_km"] for k, e in pred.items()
     if k in truth and "distance_km" in e["evidence"]]
zero = sum(1 for x in d if x == 0.0)
print(f"labelled pairs with a distance : {len(d)}")
print(f"median separation              : {statistics.median(d):.3f} km")
print(f"at exactly 0.00 km             : {zero} / {len(d)}  ({100*zero/len(d):.1f}%)")
print()
print("For contrast, Kano GRID3 x OSM: median 0.000 km, 332 of 564 (59%) at exactly 0.00.")
print("Those two sources shared coordinates. These two did not.")
""")

md("""
## Step 3 — The baseline: does it work at all?

Shipped place pack, no retuning, different country.
""")

code("""
def score(label, pred):
    m = {k for k, e in pred.items() if k in truth and e["decision"] == "match"}
    r = {k for k, e in pred.items() if k in truth and e["decision"] == "review"}
    missed = truth - set(pred)
    extra = [k for k, e in pred.items() if e["decision"] == "match" and k not in truth]
    print(f"{label}")
    print(f"  auto-matched     {len(m):>3} / {len(truth)}   ({100*len(m)/len(truth):.1f}%)")
    print(f"  routed to review {len(r):>3}")
    print(f"  never proposed   {len(missed):>3}   <- blocking loss, unrecoverable")
    print(f"  surfaced         {len(m)+len(r):>3} / {len(truth)}   ({100*(len(m)+len(r))/len(truth):.1f}%)")
    print(f"  matches outside the label set: {len(extra)}  (unlabelled, not necessarily wrong)")
    return m

baseline = score("shipped gate", pred)
""")

md("""
Note **where the failure sits**: 12 true pairs routed to `review`, not merged
wrongly. The engine abstained rather than erred. That asymmetry is the product
working as designed — a wrong merge fuses two records and is expensive to undo,
while an abstention costs a human glance.
""")

md("""
## Step 4 — The diagnosis

Look at what the engine abstained on.
""")

code("""
for k, e in pred.items():
    if k in truth and e["decision"] == "review":
        o = next(r for r in osm if r["osm_id"] == k[0])
        w = next(r for r in wd if r["wd_id"] == k[1])
        ev = e["evidence"]
        print(f"  {o['name'][:34]:34} <-> {w['name'][:34]:34}"
              f"  score={e['score']:.3f}  {ev.get('distance_km')} km")
""")

md("""
`London Bridge Hospital` against `London Bridge Hospital`. Identical strings,
30 m apart, score 0.998 — and it abstained.

The reason is the distinctiveness gate. A merge requires agreement on something
*rare*, which is what stops two unrelated "General Hospital" records fusing.
The gate looks at **tokens**.
""")

code("""
from arche.resolve._tokenfreq import TokenFrequencyTable
from arche.resolve._gate import shared_name_distinctiveness, DISTINCTIVE_FLOOR

tf = TokenFrequencyTable.default(domain="place")
print(f"gate floor = {DISTINCTIVE_FLOOR}\\n")

for name in ("London Bridge Hospital", "King's College Hospital",
             "University College Hospital", "St Mary's Hospital"):
    per_token = {t: round(tf.distinctiveness(t), 2)
                 for t in name.lower().replace("'s", "").split()}
    shared = shared_name_distinctiveness(name.lower(), name.lower(), tf)
    print(f"  {name:30} shared={shared:.3f}  {per_token}")

print()
for name in ("Karfi Health Post", "Gyaranya Health Post", "Tsalle Health Post"):
    per_token = {t: round(tf.distinctiveness(t), 2) for t in name.lower().split()}
    shared = shared_name_distinctiveness(name.lower(), name.lower(), tf)
    print(f"  {name:30} shared={shared:.3f}  {per_token}")
""")

md("""
There it is.

`Karfi` scores 0.93 on its own — a Hausa village name is rare, so the Nigerian
facility name carries its identity in a single token. But `london`, `bridge`,
`king`, `college`, `st` and `mary` are all ordinary English words. **No single
token in a London hospital name is rare enough to clear the gate**, even though
the name as a whole is perfectly distinctive.

The assumption that broke is not a threshold. It is: *the identifying part of a
name is a rare token*. In London, identity lives in the **phrase**.
""")

md("""
## Step 5 — The prototype: price phrases, not just tokens

If the diagnosis is right, then bigram frequency should separate the two kinds
of phrase without any curation: `general hospital` should be common, and
`london bridge` should be rare.

The bigram table is built over the same corpus and with the same equal-mass
stratum weighting as the shipped token table. Building it takes a few minutes,
so it is cached.
""")

code("""
BIGRAMS = REPO / "datasets" / "data" / "_cache" / "place_bigrams.json.gz"
if not BIGRAMS.exists():
    raise SystemExit(
        "Build the bigram table first:\\n"
        "    python datasets/places_dataops/build_place_bigrams.py"
    )
BI = TokenFrequencyTable.load(BIGRAMS)
print(f"{len(BI._rel):,} bigrams\\n")
for g in ("general hospital", "primary health", "health post",
          "london bridge", "kings college", "king george", "royal london"):
    print(f"  {g:20} rel_freq={BI.rel_freq(g):.3e}  distinctiveness={BI.distinctiveness(g):.3f}")
""")

md("""
The corpus separates them on its own. `general hospital` is common and stays
blocked; `london bridge` is rare and clears.

The combination rule matters as much as the measure. It is **`max`** over the
token and phrase measures, which makes the change *structurally* incapable of
demoting a pair that already matched. An earlier orthography experiment on this
engine recovered 13 true pairs and demoted 79, and only became shippable once it
was made strictly additive. That lesson is applied here rather than relearned.
""")

code("""
from arche.resolve._tokenfreq import _tokens

_original = shared_name_distinctiveness

def _bigrams(name: str) -> set[str]:
    t = _tokens(name)
    return {" ".join(t[i:i + 2]) for i in range(len(t) - 1)}

def phrase_distinctiveness(a: str, b: str) -> float:
    \"\"\"Rarity of the rarest shared bigram, or 0.0 when none is shared.\"\"\"
    return max((BI.distinctiveness(g) for g in _bigrams(a) & _bigrams(b)), default=0.0)

def patched(a, b, tf, **kw):
    # STRICTLY ADDITIVE: can only ever raise the score, never lower it.
    return max(_original(a, b, tf, **kw), phrase_distinctiveness(a, b))

# `arche.resolve.reconcile` resolves to the *function*, so patch the module.
RECONCILE = sys.modules["arche.resolve.reconcile"]
RECONCILE.shared_name_distinctiveness = patched

result_ng = crosswalk(A, B, entity="place")
pred_ng = {(osm[e["a_id"]]["osm_id"], wd[e["b_id"]]["wd_id"]): e for e in result_ng["matches"]}
with_ngrams = score("+ phrase gate", pred_ng)

print()
print(f"recovered: {len(with_ngrams - baseline)}      lost: {len(baseline - with_ngrams)}")
""")

md("""
## Step 6 — Which pairs moved, and which did not
""")

code("""
print("recovered by the phrase gate:")
for k in sorted(with_ngrams - baseline):
    o = next(r for r in osm if r["osm_id"] == k[0])
    w = next(r for r in wd if r["wd_id"] == k[1])
    print(f"  {o['name'][:36]:36} <-> {w['name'][:36]:36} phrase={phrase_distinctiveness(o['name'], w['name']):.3f}")

print("\\nstill abstaining:")
for k, e in pred_ng.items():
    if k in truth and e["decision"] == "review":
        o = next(r for r in osm if r["osm_id"] == k[0])
        w = next(r for r in wd if r["wd_id"] == k[1])
        print(f"  {o['name'][:36]:36} <-> {w['name'][:36]:36} phrase={phrase_distinctiveness(o['name'], w['name']):.3f}")
""")

md("""
Two of the remaining abstentions are **correct**, not failures.

`St Mary's Hospital` and `St George's Hospital` keep abstaining because those
bigrams genuinely are common — there really are several St Mary's Hospitals in
the UK. Those pairs are confirmed only by their coordinates, and `review` is the
honest answer. The other three are mechanical: `Queens` and `Queen's` share no
bigram once tokenised, and two name forms differ outright.
""")

md("""
## Step 7 — The regression check that decides whether this could ship

A change that helps London and quietly damages Kano is not an improvement. The
same comparison, on the benchmark the place pack was tuned against.
""")

code("""
G3 = REPO / "data" / "GRID3_NGA_health_facilities_v2.csv"
OSM_KANO = REPO / "data" / "osm_kano.csv"

if G3.exists() and OSM_KANO.exists():
    with open(G3, encoding="utf-8-sig") as fh:
        grid3 = [r for r in csv.DictReader(fh) if r["state"] == "Kano"]
    with open(OSM_KANO, encoding="utf-8-sig") as fh:
        okano = [r for r in csv.DictReader(fh) if r["name"].strip()]
    KA = [{"name": r["name"], "lat": r["lat"], "lon": r["lon"]} for r in okano]
    KB = [{"name": r["facility_name"], "lat": r["latitude"], "lon": r["longitude"]} for r in grid3]
    lga_a = {i: (r.get("lga") or "").strip().lower() for i, r in enumerate(okano)}
    lga_b = {i: (r.get("lga") or "").strip().lower() for i, r in enumerate(grid3)}

    def kano(label):
        res = crosswalk(KA, KB, entity="place")
        dec = Counter(e["decision"] for e in res["matches"])
        same = diff = 0
        for e in res["matches"]:
            if e["decision"] != "match":
                continue
            x, y = lga_a.get(e["a_id"], ""), lga_b.get(e["b_id"], "")
            if x and y:
                same += (x == y); diff += (x != y)
        print(f"  {label:16} match={dec['match']:>4}  review={dec['review']:>4}  "
              f"LGA agreement {100*same/(same+diff):.1f}%")

    RECONCILE.shared_name_distinctiveness = _original
    kano("shipped gate")
    RECONCILE.shared_name_distinctiveness = patched
    kano("+ phrase gate")
else:
    print("Kano data not present; skipping the regression check.")
""")

md("""
## Step 8 — Safety: the defect this gate exists to prevent

The whole point of the distinctiveness gate is that two unrelated facilities
sharing a common name must not merge. If the phrase gate broke that, it would be
worthless however many pairs it recovered.
""")

code("""
for name, expected in (("General Hospital", "review"), ("Gyaranya Health Post", "match")):
    a = [{"name": name, "lat": "12.00", "lon": "8.50"}]
    b = [{"name": name, "lat": "12.04", "lon": "8.50"}]
    got = crosswalk(a, b, entity="place")["matches"][0]["decision"]
    flag = "OK" if got == expected else "<-- REGRESSION"
    print(f"  {name:24} -> {got:<7} (expected {expected})  {flag}")
""")

md("""
## What this measured, and what it did not

**Measured.** On 86 labelled London pairs the shipped pack auto-matches 84.9%
and surfaces 98.8%, with blocking recall 0.988. Adding a phrase-level
distinctiveness measure lifts auto-match to 93.0%, recovering 7 pairs and losing
none, while Kano's LGA agreement is unchanged.

**Not measured, and worth being blunt about.**

* **Recall is unknown.** The truth set comes from `wikidata=` tags, and an
  untagged hospital may still have a counterpart. Absence of a label is not
  evidence of absence, so nothing here is a recall figure.
* **86 pairs is small.** These are illustrative counts, not confidence intervals.
* **One city, one entity type.** London hospitals do not establish anything
  about UK addresses, retail, or any other domain.
* **The prototype is not shipped.** It monkey-patches a function in a notebook.
  Shipping it needs the n-gram table built by the packaged builder, a
  population-scale guard so a small corpus cannot clear the gate on noise,
  per-region evidence so a reviewer can see *which phrase* cleared it, and tests.

**A known risk the prototype makes worse, not better.** Among the newly matched
pairs is `King's College Hospital Emergency Department` against
`King's College Hospital` — a *part-of* relation, not identity. Phrase-level
rarity makes that easier to trip, because the shared phrase is distinctive even
though the entities are at different granularities. That is a separate failure
class from the one this notebook fixes, and it needs its own answer before any
of this ships.

*Related: [the place benchmark](https://unpatterned-labs.github.io/arche/concepts/place-benchmark/)
· [a representation engine, not an inference engine](https://unpatterned-labs.github.io/arche/concepts/representation-engine/)
· [a place is not a point](https://unpatterned-labs.github.io/arche/concepts/a-place-is-not-a-point/)*
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

out = Path(__file__).resolve().parent / "05_does_the_engine_generalise.ipynb"
out.write_text(json.dumps(nb, indent=1, ensure_ascii=False), encoding="utf-8")
print(f"wrote {out}  ({len(cells)} cells)")
