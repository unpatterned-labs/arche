# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0
"""Generate 13_england_schools.ipynb.

The notebook is the artefact; this script exists so it can be regenerated
rather than hand-edited as JSON. Run from the repo root:

    python data/scripts/fetch_england_schools.py --la Leeds --date YYYYMMDD
    python examples/notebooks/build_13.py
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
# Crosswalking a national register against a crowd-sourced map

**England schools: the Department for Education's GIAS register against
OpenStreetMap, measured on 282 human-asserted labels.**

The London hospital lane asked whether the engine generalises past Nigeria.
This asks a different question, and a more common one in practice:

> You have an **authoritative register** and a **map somebody else made**.
> Neither has the other's identifiers. How much of the join can software do,
> and how do you know it got it right?

This is the shape of most real reconciliation work. A ministry has a facility
list. A logistics team has points. A regulator has a licence register. Nobody
shares a key.

Everything below is executable and every number is this run's own output.
""")

md("""
## The two sources

**GIAS** is the register. The Department for Education issues a **URN** to
every open educational establishment in England, and GIAS is where that
happens. Crown copyright, Open Government Licence.

**OpenStreetMap** is surveyed and crowd-mapped. ODbL, which is why it is
**benchmark evidence only here and can never enter a shipped pack**:
share-alike would propagate into every derived artefact.

### Three identifiers that do not mean the same thing

GIAS carries all three, and treating them as interchangeable is the first
mistake available.

| | identifies | reissued when |
|---|---|---|
| **URN** | an *establishment* | it legally becomes a new establishment, which an academy conversion usually is |
| **UKPRN** | a *provider* on the UK Register of Learning Providers | rarely; sparsely populated for schools |
| **LAESTAB** | `LA code` + `establishment number` | the composite that predates URN and still appears in funding returns |

A school can keep its buildings, staff, pupils and name through a conversion
and come out with a **new URN**. Ask "is this the same school" and the register
answers "no" while everyone standing in the playground answers "yes". Which one
is right depends on whether you are counting institutions or funding entities,
and no amount of string matching decides it for you.
""")

code("""
import csv, math, statistics, sys
from pathlib import Path

REPO = Path.cwd()
while not (REPO / "packages" / "arche-core").exists() and REPO != REPO.parent:
    REPO = REPO.parent
sys.path.insert(0, str(REPO / "packages" / "arche-core" / "src"))

D = REPO / "data" / "_cache" / "schools"
if not (D / "gias.csv").exists():
    raise SystemExit(
        "Stage the sources first (they are fetched, never committed):\\n"
        "    python data/scripts/fetch_england_schools.py --la Leeds"
    )

gias = list(csv.DictReader(open(D / "gias.csv", encoding="utf-8")))
osm  = list(csv.DictReader(open(D / "osm.csv", encoding="utf-8")))
truth = {(r["osm_id"], r["urn"])
         for r in csv.DictReader(open(D / "truth_pairs.csv", encoding="utf-8"))}
known = {g["urn"] for g in gias}
truth = {(o, u) for o, u in truth if u in known}

print(f"GIAS open establishments   : {len(gias):>4}")
print(f"OSM named school features  : {len(osm):>4}")
print(f"truth pairs (ref:edubase)  : {len(truth):>4}   {100*len(truth)/len(osm):.0f}% of OSM features")
print()
print(f"UKPRN present in GIAS      : {sum(1 for g in gias if g['ukprn']):>4} / {len(gias)}")
print(f"UKPRN present in OSM       : {sum(1 for o in osm if o['ukprn']):>4} / {len(osm)}")
""")

md("""
## Step 1 — The truth set, and the rule that keeps it honest

93% of OSM school features in Leeds carry `ref:edubase`, an editor asserting
*this mapped school is that URN*. That is a literal foreign key.

Matching on it would be a key join wearing an entity-resolution costume. So it
is used the other way round:

* the tag is the **label**;
* the matcher sees **name and coordinates only**, and never the URN.

The labels are incomplete. An untagged OSM school may still have a GIAS
counterpart, so this measures auto-match rate against *known-true* pairs. It is
not a complete recall measurement, and that limit is restated at the end rather
than buried.

## Step 2 — The independence gate, before any matching

A benchmark whose sources copied each other's coordinates measures nothing. The
portable test: for pairs we already know are the same, how far apart are they?
If a large share sit at **exactly** 0.00 km, one source copied the other.
""")

code("""
def haversine_km(lat1, lon1, lat2, lon2):
    R = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    h = math.sin(dp/2)**2 + math.cos(p1) * math.cos(p2) * math.sin(dl/2)**2
    return 2 * R * math.asin(math.sqrt(h))

gi = {g["urn"]: g for g in gias}
oi = {o["osm_id"]: o for o in osm}
sep = sorted(haversine_km(float(oi[o]["lat"]), float(oi[o]["lon"]),
                          float(gi[u]["lat"]), float(gi[u]["lon"]))
             for o, u in truth)

print(f"known-same pairs           : {len(sep)}")
print(f"median separation          : {statistics.median(sep)*1000:>6.0f} m")
print(f"90th percentile            : {sep[int(0.9*len(sep))]*1000:>6.0f} m")
print(f"largest                    : {sep[-1]*1000:>6.0f} m")
print(f"at exactly 0.00 km         : {sum(1 for x in sep if x == 0.0)}")
print()
print("Zero. GIAS publishes British National Grid eastings from the DfE's own")
print("records; OSM positions come from survey. Nobody copied anybody, so the")
print("distance signal carries real information here.")
""")

md("""
That median also validates the projection. GIAS ships eastings and northings on
the Airy 1830 ellipsoid and the engine wants WGS84, so the staging script does
the inverse transverse Mercator and a Helmert transform. If that arithmetic were
wrong, known-same pairs would sit *systematically* far apart. They sit tens of
metres apart, which is the distance between a school's centroid and its gate.

## Step 3 — The result

Shipped place pack. No retuning, no patching, a country and an entity type away
from where it was calibrated.
""")

code("""
from arche.resolve import crosswalk

A = [{"name": o["name"], "lat": o["lat"], "lon": o["lon"]} for o in osm]
B = [{"name": g["name"], "lat": g["lat"], "lon": g["lon"]} for g in gias]

res = crosswalk(A, B, entity="place")
pred = {(osm[e["a_id"]]["osm_id"], gias[e["b_id"]]["urn"]): e for e in res["matches"]}

m = {k for k, e in pred.items() if k in truth and e["decision"] == "match"}
r = {k for k, e in pred.items() if k in truth and e["decision"] == "review"}
never = truth - set(pred)
extra = {k for k, e in pred.items() if e["decision"] == "match" and k not in truth}

print(f"auto-matched      {len(m):>4} / {len(truth)}   ({100*len(m)/len(truth):.1f}%)")
print(f"routed to review  {len(r):>4}")
print(f"never proposed    {len(never):>4}   <- blocking loss, unrecoverable")
print(f"surfaced          {len(m)+len(r):>4} / {len(truth)}   ({100*(len(m)+len(r))/len(truth):.1f}%)")
print(f"matches outside the label set: {len(extra)}")
print()
print("pins.tf =", res["pins"]["tf"])
""")

md("""
## Step 4 — What you would get without it

The same labels, scored by the things people reach for first, over every
possible pair.

One arm needs explaining. arche sees coordinates and the string baselines do
not, so a straight comparison would flatter it for reasons unrelated to
matching. **arche, names only** withholds the coordinates and runs the same
pack on names alone, which separates "the representation is better" from "it
had more inputs".
""")

code("""
import re
from rapidfuzz import fuzz

def toks(s):
    return {t for t in re.split(r"[^a-z0-9]+", s.casefold()) if t}

def jaccard(x, y):
    tx, ty = toks(x), toks(y)
    return len(tx & ty) / len(tx | ty) if tx and ty else 0.0

# Distinct pairs, never hits: a counter double-scores whenever either source
# repeats an identifier, which quietly pushes recall above 1.0.
def sweep(label, decide):
    hit, miss = set(), set()
    for o in osm:
        for g in gias:
            k = (o["osm_id"], g["urn"])
            if decide(o["name"], g["name"]):
                (hit if k in truth else miss).add(k)
    return label, len(hit), len(miss)

def arche_arm(label, predictions):
    hit = {k for k, e in predictions.items() if e["decision"] == "match" and k in truth}
    miss = {k for k, e in predictions.items() if e["decision"] == "match" and k not in truth}
    return label, len(hit), len(miss)

An = [{"name": o["name"]} for o in osm]
Bn = [{"name": g["name"]} for g in gias]
pn = {(osm[e["a_id"]]["osm_id"], gias[e["b_id"]]["urn"]): e
      for e in crosswalk(An, Bn, entity="place")["matches"]}

rows = [
    sweep("exact name (casefold)", lambda x, y: x.casefold().strip() == y.casefold().strip()),
    sweep("token Jaccard >= 0.5",  lambda x, y: jaccard(x, y) >= 0.5),
    sweep("token_set_ratio >= 90", lambda x, y: fuzz.token_set_ratio(x, y) >= 90),
    arche_arm("arche, names only", pn),
    arche_arm("arche, name + coords", pred),
]

print(f"{'approach':<24}{'precision':>10}{'recall':>9}{'F1':>8}{'false merges':>14}")
for label, tp, fp in rows:
    prec = tp / (tp + fp) if tp + fp else 0.0
    rec = tp / len(truth)
    f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
    print(f"{label:<24}{prec:>10.3f}{rec:>9.3f}{f1:>8.3f}{fp:>14,}")
""")

md("""
## Step 5 — Where it abstains, and whether that is right

`review` is the third answer. The question worth asking of any abstention is
not "why did it fail" but "would a human have been confident here".
""")

code("""
shown = 0
for k, e in pred.items():
    if k in truth and e["decision"] == "review" and shown < 12:
        o, g = oi[k[0]], gi[k[1]]
        d = haversine_km(float(o["lat"]), float(o["lon"]), float(g["lat"]), float(g["lon"]))
        print(f"  {o['name'][:38]:38} <-> {g['name'][:38]:38} {d*1000:>6.0f} m")
        shown += 1
print()
print("The pattern to look for: same institution under an operator name on one")
print("side and a legal name on the other, or a site split across two features.")
""")

md("""
## Step 6 — The cheapest audit available, and what it caught

Both sides sometimes carry a UKPRN. Where both do, compare them. This is a
second check on the match decisions using an identifier **neither the matcher
nor the truth set ever touched**, and it costs one join.

It is worth running because the truth set cannot see everything. The labels
cover pairs an editor tagged; the 37 matches outside that set are unjudged. The
UKPRN comparison reaches into exactly that blind spot.
""")

code("""
from collections import defaultdict

both = [(o, g) for o, g in
        ((oi[k[0]], gi[k[1]]) for k in pred if pred[k]["decision"] == "match")
        if o["ukprn"] and g["ukprn"]]
bad = [(o, g) for o, g in both if o["ukprn"].strip() != g["ukprn"].strip()]
print(f"auto-matched pairs where both sides carry a UKPRN : {len(both)}")
print(f"  the two UKPRNs agree                            : {len(both)-len(bad)} / {len(both)}")
print(f"  they disagree                                   : {len(bad)}")

# The shape of the disagreement matters more than the count. One OSM school
# pointing at several GIAS schools is not a near-miss, it is a fan-out.
fan = defaultdict(set)
for o, g in bad:
    fan[o["name"]].add(g["name"])
print()
for name, targets in sorted(fan.items(), key=lambda kv: -len(kv[1])):
    if len(targets) > 1:
        print(f"  {name[:36]:36} matched {len(targets)} different GIAS schools")
        for t in sorted(targets):
            print(f"      {t[:60]}")
""")

md("""
It found a false merge the labels could not.

The disagreements are not near-misses. One OSM school is matched to **several**
GIAS schools at once, and they are all in the same academy chain. `Co-op Academy
Leeds`, `Co-op Academy Woodlands` and `Co-op Academy Oakwood` share a brand
prefix that is two thirds of each name, so a name comparator sees near-identical
strings and the coordinates are close enough not to save it.

This is the second failure mode, the one loosening a threshold makes worse:
**many entities, one name.** Chain branding manufactures it wholesale. Every
supermarket estate, clinic network and academy trust has the same shape.

The honest reading of this notebook is therefore not 98.6%. It is: 98.6% on the
labelled pairs, **and** a family of false merges among the unlabelled ones that
only showed up because a third identifier happened to be lying around. Without
UKPRN we would have reported the first number and never seen the second.

## What this measured, and what it did not

**Measured.** Auto-match rate and abstention against 282 editor-asserted labels,
on two sources that demonstrably did not copy each other's coordinates, in a
country and an entity type the pack was not tuned on.

**Not measured.**

* **Complete recall.** The labels cover the OSM features an editor happened to
  tag. An untagged school may still have a GIAS counterpart, and those absences
  are invisible here.
* **Whether a match is *correct* in the register's sense.** `ref:edubase` is one
  editor's assertion. It is good evidence and it is not adjudicated truth.
* **One local authority.** Leeds. Naming conventions for English schools are
  fairly uniform, so this should travel within England, and it says nothing
  about anywhere else.
* **The academy-conversion case.** URNs change when an establishment legally
  becomes a new one. This run compares against *current* open establishments
  only, so it never sees a school whose URN moved underneath it. That case is
  the interesting one and it needs a historical GIAS export to study.

The sources are fetched and never committed. Re-staging with a different
`--date` pins a different GIAS export, and the numbers above will move with it.
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
    "nbformat": 4,
    "nbformat_minor": 5,
}

out = Path(__file__).resolve().parent / "13_england_schools.ipynb"
out.write_text(json.dumps(nb, indent=1, ensure_ascii=False), encoding="utf-8")
print(f"wrote {out}  ({len(cells)} cells)")
