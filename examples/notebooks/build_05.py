# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0
"""Generate 05_does_the_engine_generalise.ipynb.

The notebook is the artefact; this script exists so it can be regenerated
rather than hand-edited as JSON. Run from the repo root:

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

**London hospitals, Wikidata against OpenStreetMap, measured rather than
asserted.**

arche's place matcher was tuned on Nigerian health facilities. That raises an
obvious and uncomfortable question: does it work anywhere else, or has it
learned Kano?

The answer, in three parts.

1. **The engine generalises.** On London hospitals, with the shipped pack and no
   retuning, it auto-matches 95.3% of labelled true pairs and surfaces 98.8%.
2. **One assumption had to change.** The distinctiveness gate assumed the
   identifying part of a name is a *rare token*. In Nigeria that is a village
   name. In London it is a saint, a monarch or a bridge — ordinary words in an
   uncommon combination, and the earlier engine scored 73 of 86 for that reason.
3. **The fix ships.** Phrase-level rarity and a possessive-aware tokenisation
   are both in `arche-core`. Nothing in this notebook patches the library.

Everything below is executable, and every number is this run's own output.
""")

md("""
## Why these two sources

The Kano benchmark could not settle the question, because its two sources shared
lineage: OpenStreetMap's Kano health facilities descend from the same registry as
GRID3. Comparing them measured consistency, not accuracy — which
[the place benchmark](https://unpatterned-labs.github.io/arche/concepts/place-benchmark/)
says at length.

This pair changes **exactly one variable** against Kano — the country — while
holding the entity type and the shape of the name constant. `Bethlem Royal
Hospital` has the same structure as `Karfi Health Post`: a distinctive part plus
a generic type word.

| | collection method | licence | role here |
|---|---|---|---|
| **Wikidata** | curated per item by editors from published references | CC0 | may enter a pack |
| **OpenStreetMap** | surveyed and crowd-mapped | ODbL | **benchmark evidence only, never a shipped asset** |

That licence split is not a footnote. arche's provenance firewall bars ODbL data
from entering any shipped pack, because share-alike would propagate into every
derived artefact.
""")

code("""
import copy, csv, sys, statistics
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

The labels are incomplete: an untagged OSM hospital may still have a Wikidata
counterpart. So this measures auto-match rate against *known-true* pairs, and
cannot measure recall. That limit is restated at the end rather than buried.
""")

code("""
truth = {(r["osm_id"], r["wd_id"])
         for r in csv.DictReader(open(DATA / "truth_pairs_london.csv", encoding="utf-8"))}
tagged = sum(1 for r in osm if r.get("wikidata"))
print(f"OSM rows carrying a wikidata= tag : {tagged} / {len(osm)}  ({100*tagged/len(osm):.1f}%)")
print(f"labels resolving into our pull    : {len(truth)}")
""")

md("""
## Step 2 — The independence gate, run before any matching

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
print()
print("pins.tf =", result["pins"]["tf"])
""")

md("""
The pin names both frequency tables the decision used. They are scoring inputs,
so rebuilding either changes every `decision_id` it touched rather than changing
results silently.

## Step 3 — The result

Shipped place pack. No retuning, no patching, different country.
""")

code("""
def score(label, predictions):
    m = {k for k, e in predictions.items() if k in truth and e["decision"] == "match"}
    r = {k for k, e in predictions.items() if k in truth and e["decision"] == "review"}
    missed = truth - set(predictions)
    extra = [k for k, e in predictions.items()
             if e["decision"] == "match" and k not in truth]
    print(f"{label}")
    print(f"  auto-matched     {len(m):>3} / {len(truth)}   ({100*len(m)/len(truth):.1f}%)")
    print(f"  routed to review {len(r):>3}")
    print(f"  never proposed   {len(missed):>3}   <- blocking loss, unrecoverable")
    print(f"  surfaced         {len(m)+len(r):>3} / {len(truth)}   ({100*(len(m)+len(r))/len(truth):.1f}%)")
    print(f"  matches outside the label set: {len(extra)}  (unlabelled, not necessarily wrong)")
    return m

shipped = score("shipped", pred)
print()
print("still abstaining:")
for k, e in pred.items():
    if k in truth and e["decision"] == "review":
        o = next(x for x in osm if x["osm_id"] == k[0])
        w = next(x for x in wd if x["wd_id"] == k[1])
        print(f"  {o['name'][:36]:36} <-> {w['name'][:34]}")
""")

md("""
### What you would get without any of this

A number on its own says nothing. Here is the same truth set scored by the
things people actually reach for first, over every one of the 86,487 possible
pairs.

One arm needs explaining. arche sees coordinates and the string baselines do
not, so a straight comparison would flatter it for reasons that have nothing to
do with matching. The **arche, names only** arm removes the coordinates and
runs the same pack on names alone, which separates "the representation is
better" from "it had more inputs".
""")

code("""
import re
from rapidfuzz import fuzz

def toks(s):
    return {t for t in re.split(r"[^a-z0-9]+", s.casefold()) if t}

# Count distinct pairs, not hits. The Wikidata pull carries the same wd_id on
# more than one row (380 rows, 273 entities), so a counter scores one truth pair
# several times and can push recall above 1.0. Sets are the only safe shape here.
def sweep(label, decide):
    hit, miss = set(), set()
    for a in osm:
        for b in wd:
            k = (a["osm_id"], b["wd_id"])
            if decide(a["name"], b["name"]):
                (hit if k in truth else miss).add(k)
    return label, len(hit), len(miss)

def jaccard(x, y):
    tx, ty = toks(x), toks(y)
    return len(tx & ty) / len(tx | ty) if tx and ty else 0.0

rows = [
    sweep("exact name (casefold)", lambda x, y: x.casefold().strip() == y.casefold().strip()),
    sweep("token Jaccard >= 0.5",  lambda x, y: jaccard(x, y) >= 0.5),
    sweep("token_set_ratio >= 90", lambda x, y: fuzz.token_set_ratio(x, y) >= 90),
]

# arche, names only: same pack, coordinates withheld
An = [{"name": r["name"]} for r in osm]
Bn = [{"name": r["name"]} for r in wd]
pn = {(osm[e["a_id"]]["osm_id"], wd[e["b_id"]]["wd_id"]): e
      for e in crosswalk(An, Bn, entity="place")["matches"]}
def arche_arm(label, predictions):
    hit = {k for k, e in predictions.items() if e["decision"] == "match" and k in truth}
    miss = {k for k, e in predictions.items() if e["decision"] == "match" and k not in truth}
    return label, len(hit), len(miss)

rows.append(arche_arm("arche, names only", pn))
rows.append(arche_arm("arche, name + coords", pred))

print(f"{'approach':<24}{'precision':>10}{'recall':>9}{'F1':>8}{'false merges':>14}")
for label, tp, fp in rows:
    prec = tp / (tp + fp) if tp + fp else 0.0
    rec = tp / len(truth)
    f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
    print(f"{label:<24}{prec:>10.3f}{rec:>9.3f}{f1:>8.3f}{fp:>14,}")
print()
print("False merges here are matches outside the 87 labelled pairs. The label")
print("set is not complete, so some are real hospitals nobody labelled. That")
print("cuts the same way for every row, which is what makes the column")
print("comparable even though it is not a clean error count.")
""")

md("""
The fuzzy baselines behave exactly as the argument predicts. Loosening from
exact to token overlap takes recall from 0.709 to 0.965 and drops precision
from 0.859 to 0.182, turning 10 false merges into 372. **One threshold cannot
fix both directions at once.**

Now the part that does not flatter us. On F1, **arche with names only does not
beat exact matching** (0.769 against 0.777). It is a different trade, not a
better one: recall 0.930 against 0.709, precision 0.656 against 0.859. It finds
a third more of the true pairs and pays for them.

If your sources spell things identically, exact matching is a perfectly good
answer and you do not need any of this. That is worth saying plainly, because
the case for representation is not that it wins everywhere.

What moves it clearly ahead here is the coordinates: 0.854, the best of the
five, at the highest recall of any arm that keeps precision above 0.7. The
lesson is not "arche beats string matching". It is that **a single signal, of
any kind, runs out** — and the engine's job is combining several without
letting any one of them decide alone.

Both remaining abstentions are the right answer rather than a gap.
`Memorial Hospital` is a generic stem — it appears four times in *each* source.
`Nuffield Health Highgate Hospital` against `Highgate Private Hospital` is brand
substitution, which belongs in an alias field on the record, not in a string
comparator.

Note **where the residual failure sits**: pairs go to `review`, never to a wrong
merge. A reviewer's glance is cheap; fusing two hospitals' records is not.

## Step 4 — Why this used to fail

The earlier engine scored **73** of 86 here. The gap was one assumption: that
the identifying part of a name is a **rare token**.
""")

code("""
from arche.resolve._tokenfreq import TokenFrequencyTable
from arche.resolve._gate import DISTINCTIVE_FLOOR

tf = TokenFrequencyTable.default(domain="place")
print(f"gate floor = {DISTINCTIVE_FLOOR}\\n")

for name in ("London Bridge Hospital", "King's College Hospital", "St Mary's Hospital"):
    per_token = {t: round(tf.distinctiveness(t), 2)
                 for t in name.lower().replace("'s", "").split()}
    print(f"  {name:28} {per_token}")
print()
for name in ("Karfi Health Post", "Gyaranya Health Post"):
    per_token = {t: round(tf.distinctiveness(t), 2) for t in name.lower().split()}
    print(f"  {name:28} {per_token}")
""")

md("""
`Karfi` clears the floor on its own. **No single token of a London hospital name
comes close**, even when the two names are byte-identical.

Two changes closed that, and both ship in `arche-core`.

**Possessive-aware tokenisation.** `Queen's` now emits `queen`, `s` *and*
`queens` — alongside, never instead. `Queens Hospital` and `Queen's Hospital`
previously shared nothing but `hospital`.

**Phrase distinctiveness.** A bigram frequency table ships beside the unigram
one, and the corpus separates generic phrases from identifying ones with no
curation at all:
""")

code("""
print("generic type phrases stay common:")
for g in ("general hospital", "primary health", "health post", "medical centre"):
    print(f"  {g:20} {tf.phrases.distinctiveness(g):.3f}")

print("\\nidentifying phrases are rare:")
for g in ("london bridge", "kings college", "king george", "royal london"):
    print(f"  {g:20} {tf.phrases.distinctiveness(g):.3f}")

print(f"\\nphrase table rule {tf.phrases.token_rule!r} must equal unigram rule {tf.token_rule!r}")
""")

md("""
The two measures combine with **`max`**, never replacement, so phrase evidence
can only recover a pair that was abstaining and can never demote one that
already matched. That discipline is not stylistic: an earlier orthography
experiment on this engine recovered 13 pairs and demoted 79, and only became
shippable once it was made structurally additive.

## Step 5 — Ablation: what the phrase table is actually worth

Rather than trust the claim, switch it off. `tf.phrases` is the companion table;
setting it to `None` reverts to token-only rarity with nothing else changed.
""")

code("""
ablated = copy.copy(TokenFrequencyTable.default(domain="place"))
ablated.phrases = None          # token-only rarity; everything else identical

pred_ablated = {
    (osm[e["a_id"]]["osm_id"], wd[e["b_id"]]["wd_id"]): e
    for e in crosswalk(A, B, entity="place", tf=ablated)["matches"]
}
without = score("without the phrase table", pred_ablated)
print()
print(f"phrase table is worth: {len(shipped - without)} recovered, "
      f"{len(without - shipped)} lost")
print()
for k in sorted(shipped - without):
    o = next(x for x in osm if x["osm_id"] == k[0])
    w = next(x for x in wd if x["wd_id"] == k[1])
    print(f"  {o['name'][:34]:34} <-> {w['name'][:32]:32} "
          f"phrase={tf.phrase_distinctiveness(o['name'], w['name']):.3f}")
""")

md("""
## Step 6 — The regression check that decides whether this could ship

A change that helps London and quietly damages Kano is not an improvement. The
same comparison, on the benchmark the place pack was originally tuned against.
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
    KB = [{"name": r["facility_name"], "lat": r["latitude"], "lon": r["longitude"]}
          for r in grid3]
    lga_a = {i: (r.get("lga") or "").strip().lower() for i, r in enumerate(okano)}
    lga_b = {i: (r.get("lga") or "").strip().lower() for i, r in enumerate(grid3)}

    def kano(label, table=None):
        res = crosswalk(KA, KB, entity="place", **({"tf": table} if table else {}))
        dec = Counter(e["decision"] for e in res["matches"])
        same = diff = 0
        for e in res["matches"]:
            if e["decision"] != "match":
                continue
            x, y = lga_a.get(e["a_id"], ""), lga_b.get(e["b_id"], "")
            if x and y:
                same += (x == y); diff += (x != y)
        print(f"  {label:26} match={dec['match']:>4}  review={dec['review']:>4}  "
              f"LGA agreement {100*same/(same+diff):.1f}%")

    kano("without the phrase table", ablated)
    kano("shipped")
else:
    print("Kano data not present; skipping the regression check.")
""")

md("""
## Step 7 — Safety: the defect the gate exists to prevent

Two unrelated facilities sharing a common name must not merge, however much
other evidence agrees. If the phrase table broke that, it would be worthless
whatever it recovered.
""")

code("""
for name, expected in (("General Hospital", "review"), ("Gyaranya Health Post", "match")):
    a = [{"name": name, "lat": "12.00", "lon": "8.50"}]
    b = [{"name": name, "lat": "12.04", "lon": "8.50"}]
    got = crosswalk(a, b, entity="place")["matches"][0]["decision"]
    print(f"  {name:24} -> {got:<7} (expected {expected})  "
          f"{'OK' if got == expected else '<-- REGRESSION'}")

print()
print("phrase evidence is refused where it cannot be trusted:")
unseen = tf.phrase_distinctiveness("Zzqq Wwxx Hospital", "Zzqq Wwxx Hospital")
local = TokenFrequencyTable.from_corpus(["London Bridge Hospital"] * 5)
print(f"  unseen phrase        {unseen:.3f}")
print(f"  runtime-built table  "
      f"{local.phrase_distinctiveness('London Bridge Hospital', 'London Bridge Hospital'):.3f}")
""")

md("""
Both zeros matter. An **unseen** phrase scores 0.0 rather than defaulting to
"rare" — that is the failure where a key absent from every table reads as
maximally distinctive. And a table built at runtime over the two lists in hand
is silent, because rarity is a claim about a *population* and a small corpus
cannot make one.

## Step 8 — A known risk, shown rather than buried

Phrase rarity makes **containment** errors easier to trip: a shared phrase is
distinctive even when the two records sit at different granularities.
""")

code("""
containment = []
for e in result["matches"]:
    if e["decision"] != "match":
        continue
    a_name, b_name = osm[e["a_id"]]["name"], wd[e["b_id"]]["name"]
    ta, tb = set(a_name.lower().split()), set(b_name.lower().split())
    if ta and tb and ta != tb and (ta < tb or tb < ta):
        extra = sorted((tb - ta) if ta < tb else (ta - tb))
        if extra != ["the"]:                      # a leading article is noise
            k = (osm[e["a_id"]]["osm_id"], wd[e["b_id"]]["wd_id"])
            containment.append((k in truth, a_name, b_name, extra))

for labelled, a_name, b_name, extra in sorted(containment):
    tag = "labelled true" if labelled else "UNLABELLED  "
    print(f"  [{tag}] {a_name[:33]:33} <-> {b_name[:29]:29} +{extra}")
""")

md("""
`King's College Hospital Emergency Department` matched to `King's College
Hospital`; `Charing Cross Hospital` matched to `Charing Cross Hospital Medical
School`. A department and a medical school — neither is the hospital.

They are **not** suppressed, and the reason is visible in the output above.
`Caterham Dene Hospital & Minor Injuries Unit` and `Moorfields Eye Hospital
(City Road campus)` are labelled *true* while those two are unlabelled. A
subunit is a true match in one row and unknown in another, so a token-subset
rule learned on this corpus would fit label noise — and would also route three
known-true pairs to `review`.

Containment needs its own relation labels and its own verdict. Until then it is
a documented limit of auto-match in this domain, not a solved problem.

## What this measured, and what it did not

**Measured.** On 86 labelled London pairs the shipped pack auto-matches 95.3%
and surfaces 98.8%, with blocking recall 0.988. The phrase table accounts for
most of the gain over the earlier 73/86 — 7 recovered, 0 lost — and Kano's LGA
agreement is unchanged at 88.1%.

**Not measured, and worth being blunt about.**

* **This is not recall.** The truth set comes from OpenStreetMap `wikidata=`
  tags. Only 91 of 226 OSM records carry one, and an absent tag means
  *unlabelled*, not *no match exists*. It is an auto-match rate over a
  tag-bearing positive subset.
* **There is no precision instrument here at all.** Nothing in this corpus can
  say whether an unlabelled match is right. Kano's LGA agreement is the only
  precision signal in the exercise, and it is a weak label.
* **These 86 pairs have been optimised against repeatedly.** Treat the figure as
  a conditional statistic with real overfit risk, not a headline.
* **One city, one entity type.** London hospitals establish nothing about UK
  addresses, retail, or any other domain.

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
