# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0
"""Generate 17_when_agreement_is_not_evidence.ipynb.

    python examples/notebooks/build_17.py

Two records can agree perfectly and still not be a match. This notebook shows
the gate that decides that, why no better string model can replace it, and what
`would_resolve` does with the refusal.
"""
from __future__ import annotations

import json
from pathlib import Path

MD, CODE = "markdown", "code"
cells: list[tuple[str, str]] = []
md = lambda t: cells.append((MD, t.strip("\n")))      # noqa: E731
code = lambda t: cells.append((CODE, t.strip("\n")))  # noqa: E731


md("""
# When agreement is not evidence

**Two records can be identical and still not be a match.** This is the part of arche most likely to surprise you, and the surprise is usually arche being right.

Everything below runs on the shipped wheel. No API key, no data download, no network.

There are two gates and a pair must clear both:

| Gate | Question | Field |
| --- | --- | --- |
| Agreement | Do these records say the same things? | `score` |
| Distinctiveness | Is what they agree on rare enough to identify anything? | `distinctive_max` |

The first is a similarity measure. The second is not — it asks how much information the agreement carries. A pair that clears the score threshold and falls below the distinctiveness floor is demoted from `match` to `review`.
""")

code('''
import warnings
warnings.filterwarnings("ignore")

from arche.resolve import reconcile, would_resolve
from arche.resolve._gate import DISTINCTIVE_FLOOR

print("distinctiveness floor:", DISTINCTIVE_FLOOR)


def probe(name_a, name_b, entity="place", **extra):
    """Score one pair and return the two gates plus the verdict."""
    a = {"id": "a", "name": name_a, **extra}
    b = {"id": "b", "name": name_b, **extra}
    edges = reconcile([a], [b], entity=entity, id_field="id")["matches"]
    if not edges:
        return None
    e = edges[0]
    return e["score"], e["distinctive_max"], e["decision"]
''')

md("""
## Identical strings, three different answers

Each row below compares a name **against itself**. The strings are the same in every case, so any similarity function returns its maximum — and arche's does, three times over. The verdicts differ anyway.
""")

code('''
print(f"{'name':<24}{'score':>7}{'distinctive':>13}   decision")
print("-" * 58)
for name in ["General Hospital", "Gyaranya Health Post", "Karfi Health Post"]:
    score, distinctive, decision = probe(name, name)
    print(f"{name:<24}{score:>7}{distinctive:>13}   {decision}")
''')

md("""
`score` is constant at 1.0. `distinctive_max` moves from 0.564 to 0.927, and the verdict flips.

**The separating information is not in the pair.** It is a fact about the world: a great many facilities are called *General Hospital*, and very few are called *Karfi Health Post*. No comparison of two strings can recover a fact that is in neither string.

This is worth stating carefully, because it is not the usual complaint about model quality. It is that `sim(a, b)` has the wrong signature. When `a == b`, every metric — cosine, edit distance, Jaccard, a fine-tuned bi-encoder — returns its ceiling. A better model moves nothing, because the deficiency is in what the function is allowed to read.

## The rarity is computed, not asserted

`distinctiveness(token) = -log10(relative frequency) / 5`, clamped to [0, 1]. Read straight from the shipped table:
""")

code('''
import gzip, json, math, pathlib
import arche.resolve as _r

data = pathlib.Path(_r.__file__).parent / "_data"

def counts_for(domain):
    raw = json.loads(gzip.open(data / f"{domain}_frequencies.json.gz",
                               "rt", encoding="utf-8").read())
    return raw["counts"], raw["total"]

def distinctiveness(token, domain):
    counts, total = counts_for(domain)
    freq = max(counts.get(token, 0.0) / total, 1e-12)
    return min(1.0, max(0.0, -math.log10(freq) / 5.0))

counts, total = counts_for("place")
print(f"place table: {len(counts):,} tokens, {total:,.0f} total\\n")
print(f"{'token':<12}{'count':>12}{'1 in':>10}{'distinctiveness':>17}")
print("-" * 51)
for token in ["hospital", "general", "clinic", "karfi", "gyaranya"]:
    n = counts.get(token, 0.0)
    rate = total / n if n else float("inf")
    print(f"{token:<12}{n:>12,.0f}{rate:>10,.0f}{distinctiveness(token, 'place'):>17.3f}")
''')

md("""
`hospital` is one token in 57 across a facility gazetteer — the most ordinary word a facility name can contain. `karfi` is one in tens of thousands. `distinctive_max` takes the strongest of the agreeing tokens, which is why *Karfi Health Post* clears the floor on the strength of one word.

**`gyaranya` has a count of zero, and scores 1.000 anyway.** It is not in the table at all, so it falls to the unknown-token floor and is treated as maximally rare. That is the right default — a name the gazetteer has never seen is usually genuinely unusual — but it is an assumption, not a measurement.

### Where that assumption bites

A misspelling is also an unseen token, and it scores exactly like a rare one:""")

code('''
for name in ["General Hospital", "Genrel Hopsital"]:
    score, distinctive, decision = probe(name, name)
    print(f"{name:<20} distinctive_max={distinctive:<7} -> {decision}")
''')

md("""
**The same pair of records auto-merges once both sides carry the same OCR error.** Correctly spelled, arche refuses; misspelled identically, it matches — because nothing in the gazetteer says `hopsital` is ordinary.

This is the sharpest limitation of a frequency gate and it matters most in exactly the setting the gate is for: scanned invoices, packing lists and certificates, where a systematic OCR error appears on both documents. Normalise before you resolve, and treat a high `distinctive_max` driven by an *unseen* token differently from one driven by a *measured*-rare token. The table knows which it was; the score alone does not.

## The same name, two packs, two answers

Rarity is measured against **the population the pack ships**, and the packs ship different ones. This is the single most common source of surprise:
""")

code('''
for entity in ["place", "organisation"]:
    score, distinctive, decision = probe("General Hospital", "General Hospital",
                                         entity=entity)
    print(f"{entity:<14} score={score}  distinctive_max={distinctive}  -> {decision}")

print()
print(f"{'token':<12}{'place table':>14}{'organisation table':>22}")
print("-" * 48)
for token in ["hospital", "general", "limited"]:
    p_counts, p_total = counts_for("place")
    o_counts, o_total = counts_for("organisation")
    p = p_counts.get(token, 0.0)
    o = o_counts.get(token, 0.0)
    print(f"{token:<12}{f'1 in {p_total/p:,.0f}' if p else 'absent':>14}"
          f"{f'1 in {o_total/o:,.0f}' if o else 'absent':>22}")
''')

md("""
**Read the organisation column carefully, because it is the honest limitation.**

`hospital` is not rare in the world. It is rare *in GLEIF* — a registry of entities that participate in financial markets — because hospitals do not generally register Legal Entity Identifiers. The organisation table's answer is a true statement about GLEIF and a misleading one about hospitals.

A frequency table cannot distinguish **rare** from **absent from my sampling frame**, and no gate downstream recovers the difference. The practical rule follows: choosing a pack is choosing which population rarity is measured against. If picking a different pack turns a `review` into a `match`, you have routed around the refusal rather than resolved it.

## The second gate: a hard constraint

Distinctiveness is not the only thing that can hold a pair. The `place` pack declares `veto_km: 10.0` on its geo comparator. Both gates, in one table:
""")

code('''
LAGOS      = (6.5244, 3.3792)
NEXT_DOOR  = (6.5250, 3.3800)   # about 90 m
ABUJA      = (9.0765, 7.3986)   # about 530 km

def pair(name, here, there):
    a = {"id": "a", "name": name, "lat": here[0], "lon": here[1]}
    b = {"id": "b", "name": name, "lat": there[0], "lon": there[1]}
    edges = reconcile([a], [b], entity="place", id_field="id")["matches"]
    return edges[0]["decision"] if edges else "not surfaced"

print(f"{'name':<24}{'90 m apart':>14}{'530 km apart':>16}")
print("-" * 54)
for name in ["Karfi Health Post", "General Hospital"]:
    print(f"{name:<24}{pair(name, LAGOS, NEXT_DOOR):>14}{pair(name, LAGOS, ABUJA):>16}")
''')

md("""
Only the top-left corner is a match. Distinctiveness moves you down the rows; geography moves you across the columns.

**Note what the veto did not do.** At 530 km the pair is still returned, and it is `review`, not `no_match`. arche declines to assert sameness; it never asserts difference. A hard constraint caps the decision — it does not delete the pair or claim the records are different things.

## Turning the refusal into a next action

A `review` edge says the evidence was insufficient. It does not say what *would* be sufficient — and a human reviewer fills that gap from domain knowledge an agent does not have. `would_resolve` closes it, mechanically, from the pack spec and the fields that arrived.
""")

code('''
a = {"id": "a", "name": "General Hospital"}
b = {"id": "b", "name": "General Hospital"}
edge = reconcile([a], [b], entity="place", id_field="id")["matches"][0]

advice = would_resolve(edge, a, b, entity="place")

print("why:", advice["why"])
print()
print("supplied:", advice["fields_present"])
print()
print("would resolve it:")
for entry in advice["would_resolve"]:
    print(f"  {entry['effect']:<20} {entry['field']}")
    print(f"  {'':<20} {entry['why']}")
print()
print("will NOT help:")
for entry in advice["will_not_help"]:
    print(f"  {entry['field']}: {entry['why']}")
''')

md("""
`will_not_help` is the half that matters most and the half a scoring API never gives you. Faced with `review` on two identical names, the obvious move is to fetch a longer or cleaner name and retry. That cannot work — rarity is a property of the population, so a better rendering of *General Hospital* is still *General Hospital*. Go and get a different field.

## Taking the advice

Guidance that sounds authoritative and is wrong is worse than none, because an agent acts on it. So: apply it and watch the decision move.
""")

code('''
# `decisive_for` on the organisation pack: an identifier settles a generic name.
a = {"id": "a", "name": "Central Cooperative Society"}
b = {"id": "b", "name": "Central Cooperative Society"}
before = reconcile([a], [b], entity="organisation", id_field="id")["matches"][0]

a_id = {**a, "registration_id": "RC-889112"}
b_id = {**b, "registration_id": "RC-889112"}
after = reconcile([a_id], [b_id], entity="organisation", id_field="id")["matches"][0]

print(f"name only            -> {before['decision']}  (score {before['score']})")
print(f"+ registration_id    -> {after['decision']}  (score {after['score']})")
print()

# `hard_constraint` on the place pack, on a name distinctive enough to match.
print(f"Karfi, 90 m apart    -> {pair('Karfi Health Post', LAGOS, NEXT_DOOR)}")
print(f"Karfi, 530 km apart  -> {pair('Karfi Health Post', LAGOS, ABUJA)}")
''')

md("""
Both promises hold. The identifier lifted a pair the name alone could not carry; the distance capped one the name alone would have merged.

## What this is, in one line

The distinctiveness gate is not a new idea and it helps to name it properly.

In Fellegi–Sunter an agreeing field contributes `log(m / u)`, where `u` is the probability two **non-matching** records agree on that value. With value-specific frequency adjustment — Winkler's refinement, standard practice — `u` for a token is approximately that token's frequency in the population. So when `m ≈ 1`, the agreement weight reduces to `≈ -log f(token)`.

arche computes `-log10(f(token)) / 5`.

**That is a Fellegi–Sunter u-probability with `m` pinned at 1 and the log-odds rescaled to [0, 1].** arche is not outside probabilistic record linkage; it implements the u-side of it. Two things genuinely differ:

1. **Population, not batch.** Splink estimates `u` from the data you hand it. That cannot learn `hospital` is common if neither list contains many hospitals, and in a two-record comparison it cannot learn anything at all. arche ships the frequencies — 1,248,172 records across 40 strata for the place table.
2. **Gate, not summand.** In Fellegi–Sunter the term-frequency weight is added to a total and can be outvoted by other agreeing fields. Here it is a floor: below 0.75 no amount of other agreement promotes the pair.

## Reproducing this

```sh
python examples/notebooks/build_17.py
jupyter nbconvert --to notebook --execute --inplace \\
    examples/notebooks/17_when_agreement_is_not_evidence.ipynb
```

Needs only `arche-core`. Nothing here downloads or calls out.

The numbers are pinned in `packages/arche-core/tests/test_similarity_vs_distinctiveness.py` and `test_would_resolve.py`, so a frequency-table rebuild that moves them fails the suite rather than leaving this page quietly wrong.

Related: [Distinctiveness](../../docs-site/docs/reference/distinctiveness.md) for the reference version, and [notebook 03](03_llm_vs_arche.ipynb) for the same question put to a frontier model on 30 real facility pairs.
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

out = Path(__file__).parent / "17_when_agreement_is_not_evidence.ipynb"
out.write_text(json.dumps(nb, indent=1), encoding="utf-8")
print(f"wrote {out}  ({len(cells)} cells)")
