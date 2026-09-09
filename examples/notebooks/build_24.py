# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0
"""Generate 24_is_the_synthetic_world_realistic.ipynb.

    python examples/notebooks/build_24.py

Holds the generated supplier world up against 51,023 real Nigerian facility
names and asks whether it is realistic enough for the numbers measured on it
to mean anything. Written to falsify: each hypothesis states in advance what
result would refute it.
"""
from __future__ import annotations

import json
from pathlib import Path

MD, CODE = "markdown", "code"
cells: list[tuple[str, str]] = []
md = lambda t: cells.append((MD, t.strip("\n")))      # noqa: E731
code = lambda t: cells.append((CODE, t.strip("\n")))  # noqa: E731


# 1
md("""
# Is the synthetic world realistic enough to measure on?

**51,023 real Nigerian facility names against a generated supplier world.**

`data/synthetic` generates suppliers, ages them, observes them through three
source systems, and labels every disagreement by *why* it happened. Numbers
measured on it are published in `data/synthetic/RESULTS.md`. This notebook asks
the question that comes before any of those numbers: **is the generated world
enough like a real one that a matcher's score on it tells you anything?**

It is written to **falsify**. Each hypothesis below states what result would
refute it, before the result is computed. That matters here more than usual:
the same benchmark has already had three claims withdrawn after a seed sweep
showed they sat inside the noise, and a notebook built to confirm a hypothesis
will confirm it.

| | hypothesis | refuted if |
|---|---|---|
| **H1** | Generated company names have a token vocabulary as rich as real ones | generated type/token ratio is close to real |
| **H2** | Name collisions in the generated world are as common as in real data | collision rates are within a factor of two |
| **H3** | Generated names carry regional signal, the way real names do | generated tokens are as regionally marked as real ones |

H1 and H2 are stated in the direction we *expect to fail*, so that confirming
them would be the surprise. H3 tests the defect Robin Linacre identified — that
our names are drawn without correlation — against real data rather than by
assertion.
""")

# 2
code("""
from __future__ import annotations

import collections
import csv
import math
import random
import sys
from pathlib import Path

REPO = Path.cwd()
while not (REPO / "data" / "synthetic").exists() and REPO != REPO.parent:
    REPO = REPO.parent
sys.path.insert(0, str(REPO / "data" / "synthetic"))
sys.path.insert(0, str(REPO / "packages" / "arche-core" / "src"))

GRID3 = REPO / "data" / "GRID3_NGA_health_facilities_v2.csv"
print("repo:", REPO)
print("real data present:", GRID3.exists())
""")

# 3
md("""
## The real data

GRID3's Nigerian health facility register. Not suppliers — but real Nigerian
**organisation names**, recorded by many hands over many years, with the state
and local government area attached. That last column is what makes the
correlation test possible: it lets us ask whether a name predicts where it is.
""")

# 4
code("""
with open(GRID3, encoding="utf-8-sig") as fh:
    real = [
        {"name": r["facility_name"].strip(), "state": r["state"].strip(),
         "lga": r["lga"].strip()}
        for r in csv.DictReader(fh)
        if r.get("facility_name", "").strip()
    ]

print(f"{len(real):,} real facility names, {len({r['state'] for r in real})} states")
for r in real[:6]:
    print(f"   {r['name']:<48} {r['state']}")
""")

# 5
md("""
## The generated data

The same generator that produced the worlds in `data/synthetic/worlds/`. We
take the **true** company names rather than the observed ones: the observations
carry deliberate typos and OCR damage, and comparing those against a clean
register would measure the corruption engine rather than the naming model.
""")

# 6
code("""
from arche_synthetic import build

world, _ = build("ng_supplier_v0", seed=42,
                 scale={"organisations": 2000, "people": 3000, "places": 1500})

generated = [
    {"name": world.current(e.entity_id).attributes["legal_name"],
     "city": world.current(
         world.current(e.entity_id).attributes["place_id"]).attributes["city"]}
    for e in world.of_type("organisation")
]

print(f"{len(generated):,} generated company names")
for g in generated[:6]:
    print(f"   {g['name']:<48} {g['city']}")
""")

# 7
md("""
## H1 — how rich is the naming vocabulary?

A real register accumulates names from thousands of independent naming
decisions. Ours composes them from `<Surname> <Trade> <Form>` over 18 trades
and 10 legal forms. The **type/token ratio** — distinct words divided by total
words — measures that directly.

*Refuted if the generated ratio is close to the real one.*
""")

# 8
code("""
def tokens(name: str) -> list[str]:
    return [t for t in "".join(c if c.isalnum() else " " for c in name).lower().split()
            if len(t) > 1]


def vocabulary(names: list[str]) -> dict:
    counted = collections.Counter(t for n in names for t in tokens(n))
    total = sum(counted.values())
    return {"names": len(names), "tokens": total, "distinct": len(counted),
            "ratio": len(counted) / total, "top": counted.most_common(8)}


real_v = vocabulary([r["name"] for r in real])
gen_v = vocabulary([g["name"] for g in generated])

print(f"{'':<12}{'names':>8}{'tokens':>9}{'distinct':>10}{'type/token':>12}")
for label, v in (("real", real_v), ("generated", gen_v)):
    print(f"{label:<12}{v['names']:>8,}{v['tokens']:>9,}{v['distinct']:>10,}"
          f"{v['ratio']:>12.4f}")
print()
print("most common tokens")
for label, v in (("real", real_v), ("generated", gen_v)):
    print(f"  {label:<10}", ", ".join(f"{t}({c:,})" for t, c in v["top"]))
""")

# 9
md("""
### Reading H1 — not refuted, but not for the reason first assumed

Type/token is 0.164 real against 0.113 generated, and the top tokens show what
kind of difference it is. Real names are built from a **descriptive**
vocabulary — `health`, `center`, `primary`, `clinic`, `post`, `hospital`,
`maternity`. Ours are built from a **legal-form** vocabulary — `limited`,
`nigeria`, `enterprises`, `sons`. A real register names the thing; ours names
the company wrapper.

**A first attempt at a fairer measure got this backwards and is worth
recording.** Counting how many tokens are *common* — appearing in at least
0.1%, 0.5%, 2% of names — says generated has **more** of them (243 against 130
at the 0.1% mark). That is true and it is not richness: with eighteen trade
words and ten legal forms, every one of ours appears constantly, while real
vocabulary is spread thin across tens of thousands of settlement names and
one-off descriptors. Concentration read as richness because the statistic was
chosen before the shape of the data was understood.

The cell below fixes it by comparing at **matched sample size**, which is what
vocabulary comparisons require: vocabulary grows with the number of documents
(Heaps' law), so 51,022 names will always out-vocabulary 2,000.

At 2,000 names each, real draws **2,429 distinct tokens** (2,402-2,446 over five
samples) against the generator's **877** — 2.8x. And the shape says where the
difference lives:

| token appears in | real | generated |
|---|---:|---:|
| 1 name | 2,102 | 634 |
| 2-9 names | 285 | 190 |
| 10+ names | 29 | **53** |

Real vocabulary is **dispersed** — a long tail of settlement names and one-off
descriptors, three times larger than ours. Ours is **concentrated** — fewer
distinct words, each repeating far more often, which is why the naive
common-token count flattered it. H1 stands.

The consequence for the benchmark is specific. A blocker keyed on name tokens
sees far fewer distinct keys in our world than in a real one, so blocks are
larger and blocking looks worse than it would on a real register. `RESULTS.md`
carries that as a caveat; this is the measurement behind it.
""")

# 10
code("""
# Matched sample size. The real set is 26x larger, and vocabulary grows with
# sample size (Heaps' law), so comparing 51,022 names against 2,000 measures
# the sample, not the naming model. Draw the same number from each.
rng = random.Random(0)
real_names = [r["name"] for r in real]
gen_names = [g["name"] for g in generated]
n = len(gen_names)

trials = [len({t for name in rng.sample(real_names, n) for t in tokens(name)})
          for _ in range(5)]
gen_distinct = len({t for name in gen_names for t in tokens(name)})

print(f"at n = {n:,} names each:")
print(f"   real       {sum(trials) / len(trials):>8,.0f} distinct tokens "
      f"(5 draws: {min(trials):,}-{max(trials):,})")
print(f"   generated  {gen_distinct:>8,} distinct tokens")
print(f"   ratio      {sum(trials) / len(trials) / gen_distinct:>8.1f}x")

# Where the difference sits: the tail, or the common words?
def band(names, lo, hi):
    c = collections.Counter(t for name in names for t in set(tokens(name)))
    return sum(1 for _, v in c.items() if lo <= v < hi)


sample = rng.sample(real_names, n)
print()
print(f"{'token appears in':<22}{'real':>8}{'generated':>12}")
for lo, hi in ((1, 2), (2, 10), (10, 10**9)):
    label = "1 name" if hi == 2 else (f"{lo}-{hi - 1} names" if hi < 10**9
                                      else f"{lo}+ names")
    print(f"{label:<22}{band(sample, lo, hi):>8,}{band(gen_names, lo, hi):>12,}")
""")

# 11
md("""
## H2 — are name collisions as common as in real data?

The `common_names` stratum exists because a name that many entities share is
weak evidence. If our collision rate is far from the real one, that stratum is
measuring a difficulty that does not exist.

*Refuted if the two rates land within a factor of two.*
""")

# 12
code("""
def collision_rate(names: list[str]) -> tuple[float, list]:
    norm = [" ".join(tokens(n)) for n in names]
    counted = collections.Counter(norm)
    shared = sum(c for c in counted.values() if c > 1)
    return shared / len(norm), counted.most_common(5)


real_rate, real_top = collision_rate([r["name"] for r in real])
gen_rate, gen_top = collision_rate([g["name"] for g in generated])

print(f"real      exact-name collisions: {real_rate:6.1%}")
print(f"generated exact-name collisions: {gen_rate:6.1%}")
print()
print("real, most repeated:     ", ", ".join(f"{n!r}x{c}" for n, c in real_top[:3]))
print("generated, most repeated:", ", ".join(f"{n!r}x{c}" for n, c in gen_top[:3]))
""")

# 13
code("""
# Head-token collisions: how often two organisations share their first word.
def head_rate(names: list[str]) -> float:
    heads = collections.Counter(tokens(n)[0] for n in names if tokens(n))
    return sum(c for c in heads.values() if c > 1) / sum(heads.values())


print(f"real      share a head token: {head_rate([r['name'] for r in real]):6.1%}")
print(f"generated share a head token: {head_rate([g['name'] for g in generated]):6.1%}")
""")

# 14
md("""
### Reading H2 — refuted, which is the good outcome

12.0% real against 13.5% generated on exact name collisions, and 61.4% against
68.7% on the head token. Both well inside the factor of two that was set in
advance as the refutation condition, so **H2 is refuted: the collision *rate*
is realistic.** The Zipf surname draw is doing its job.

That is necessary for the `common_names` stratum to mean anything, and it is
not sufficient. A rate can be right while the collisions are the wrong *kind*.
H3 is the sufficiency test.
""")

# 15
md("""
## H3 — do names carry regional signal?

This is the important one. In real data a name predicts where it is: Hausa
naming in Kano, Yoruba in Oyo, and facility words that travel with them. Our
generator draws a surname from a global pool and a city independently, so a
generated name should predict its city no better than chance.

The measure: for each frequent token, how concentrated is its distribution over
regions, compared with the baseline distribution of regions? A token that
appears three times more often in one region than the baseline is
**regionally marked**.

*Refuted if generated tokens are as regionally marked as real ones.*
""")

# 16
code("""
def regional_marking(rows: list[dict], key: str, min_count: int = 20) -> dict:
    baseline = collections.Counter(r[key] for r in rows)
    total = sum(baseline.values())
    per_token: dict[str, collections.Counter] = collections.defaultdict(
        collections.Counter)
    for r in rows:
        for t in set(tokens(r["name"])):
            per_token[t][r[key]] += 1

    marked, examined, best = 0, 0, []
    for token, dist in per_token.items():
        n = sum(dist.values())
        if n < min_count:
            continue
        examined += 1
        region, count = dist.most_common(1)[0]
        lift = (count / n) / (baseline[region] / total)
        if lift >= 3.0:
            marked += 1
            best.append((token, region, round(lift, 1), n))
    best.sort(key=lambda x: -x[2])
    return {"examined": examined, "marked": marked,
            "share": marked / examined if examined else 0.0, "top": best[:6]}


real_m = regional_marking(real, "state")
gen_m = regional_marking(generated, "city")

print(f"{'':<12}{'tokens examined':>17}{'regionally marked':>20}{'share':>9}")
for label, m in (("real", real_m), ("generated", gen_m)):
    print(f"{label:<12}{m['examined']:>17,}{m['marked']:>20,}{m['share']:>9.1%}")
print()
for label, m in (("real", real_m), ("generated", gen_m)):
    print(f"{label} — most regionally marked tokens:")
    print("   ", m["top"] if m["top"] else "(none)")
""")

# 17
md("""
### Reading H3 — not refuted, and the gap is total

**90.4% of real tokens are regionally marked (367 of 406). 0.0% of generated
tokens are (0 of 40).** Not a difference of degree. The generator has no
regional structure whatsoever, which is what independent draws produce and
what Robin Linacre predicted from reading the design.

Two honest qualifications, neither of which rescues the generator:

- **Some real marks are circular.** `ekiti` is marked 64x for Ekiti because
  facilities are often named after where they are. Discount those and the
  signal survives in the ones that are not place names: `akpan` at 49x for Akwa
  Ibom is an Ibibio surname, `afaha` at 55x is an Ibibio settlement prefix.
  Real names carry linguistic origin, not just an address.
- **Only 40 generated tokens cleared the 20-occurrence floor**, against 406
  real ones — itself the H1 finding. But the share is 0 of 40, not 1 or 2 of
  40, so thinness is not hiding a weak signal.

This is the defect measured rather than asserted, and it is the number to watch
after N1 lands.
""")

# 18
md("""
## The same thing, by eye

Real African person names, from the artist equivalence data — these are actual
people, so the two halves of each name belong together. Next to them, names
this generator produces.
""")

# 19
code("""
import yaml

from arche_synthetic.world import Names

real_people = []
for f in sorted((REPO / "datasets" / "artist_equivalences").glob("*.yaml")):
    doc = yaml.safe_load(f.read_text(encoding="utf-8"))
    for group in doc.get("groups", []):
        for value in [group["canonical"], *group.get("variants", [])]:
            if value.count(" ") == 2 and all(w[:1].isupper() for w in value.split()):
                real_people.append(value)

names = Names(random.Random(42))
generated_people = [names.person() for _ in range(10)]

print(f"{'real (artist legal names)':<34}generated")
for a, b in zip(real_people[:10], generated_people, strict=False):
    print(f"{a:<34}{b}")
""")

# 20
md("""
## What this means for the published numbers

Nothing here changes a measured result. What it changes is which results can be
**generalised**, and that distinction is the whole point of running it.

Safe to generalise — these depend on the *labels*, which are correct by
construction, not on the naming model:

- **Every engine that reads the address fails on relocated suppliers**, while
  the one that ignores the address does not. The mechanism is the address
  comparator, and no amount of naming realism changes it.
- **The ledger recovers legitimate change that batch comparison refuses**
  (`change` stratum +0.115 / +0.162 / +0.120 across three paired worlds).

Not safe to generalise — these depend on the naming model this notebook has
just measured:

- **Anything from the `common_names` stratum.** The *rate* is realistic (H2
  refuted, 13.5% against 12.0%) but the *structure* is not (H3, 0.0% against
  90.4% regionally marked). A matcher that exploits regional coherence — and a
  human reviewer certainly does — has nothing to exploit here.
- **Blocking numbers.** H1: a descriptive vocabulary of eighteen trade words
  against a real register's hundreds makes token blocks much larger than they
  would be in the field.
- **Absolute recall on any arm.** Ordering survives; the level does not.

The fixes are already named in the plan: **N1** correlated names
(`P(given | region, era)` derived from ParaNames/Wikidata language and script
tags) and **N2** a rename that changes the distinctive head rather than the
legal form. This notebook is the before; re-running it after N1 is how we will
know the fix worked, and the `regionally marked` share is the number to watch.

Re-run with `python examples/notebooks/build_24.py` after any generator change.
""")


def build() -> Path:
    nb = {
        "cells": [
            {
                "cell_type": kind,
                "metadata": {},
                "source": text.splitlines(keepends=True),
                **({"outputs": [], "execution_count": None} if kind == CODE else {}),
            }
            for kind, text in cells
        ],
        "metadata": {
            "kernelspec": {"display_name": "Python 3", "language": "python",
                           "name": "python3"},
            "language_info": {"name": "python"},
        },
        "nbformat": 4,
        "nbformat_minor": 5,
    }
    out = Path(__file__).with_name("24_is_the_synthetic_world_realistic.ipynb")
    out.write_text(json.dumps(nb, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return out


if __name__ == "__main__":
    print(build())
