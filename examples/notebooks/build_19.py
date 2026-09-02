# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0
"""Generate 19_how_distinctive_is_a_mark.ipynb.

    python examples/notebooks/build_19.py

Distinctiveness as trademark law means it: the generic -> descriptive ->
suggestive -> arbitrary -> fanciful spectrum, computed from corpora rather than
asserted, and computed PER CLASS because a word's strength depends entirely on
the goods it is registered against.

Names no client and no data supplier. The corpora are read from a directory the
reader supplies and every cell degrades to an explanation when it is absent.
"""
from __future__ import annotations

import json
from pathlib import Path

MD, CODE = "markdown", "code"
cells: list[tuple[str, str]] = []
md = lambda t: cells.append((MD, t.strip("\n")))      # noqa: E731
code = lambda t: cells.append((CODE, t.strip("\n")))  # noqa: E731


md("""
# How distinctive is a mark?

**The legal spectrum, computed from data instead of argued from opinion.**

Trademark strength runs generic → descriptive → suggestive → arbitrary → fanciful. A generic term is unprotectable; a coined one gets the broadest protection; and likelihood-of-confusion analysis weights the strength of the senior mark throughout.

That is the same question arche's engine asks on every comparison:

> Agreement on an ordinary word is not evidence. Agreement on a rare one is.

A mark that is an ordinary word is weak for exactly the reason that two records agreeing on `hospital` are not the same hospital — the agreement carries almost no information. So mark strength and record linkage are the same computation pointed at different problems, and the measure is the same: **how often does this token occur in the relevant population?**

Two things follow, and the second is the one worth the meeting:

1. Strength is computable, not a matter of taste.
2. **It is meaningless without a class.** `Apple` is generic for fruit and arbitrary for computers. One global answer is wrong for both.
""")

code('''
import warnings, collections, csv, re, os, pathlib
warnings.filterwarnings("ignore")
csv.field_size_limit(10_000_000)

# Optional: two real product corpora, for the per-class demonstration below.
#     ARCHE_RETAIL_DATA=/path/to/corpora jupyter lab
CORPORA = pathlib.Path(os.environ.get("ARCHE_RETAIL_DATA", "./retail-corpora"))
HAVE_CORPORA = CORPORA.exists()

from arche.resolve._gate import _english_counts
ENGLISH, ENGLISH_TOTAL = _english_counts()
print(f"general-English table: {len(ENGLISH):,} words, "
      f"{ENGLISH_TOTAL:,} tokens")
print("product corpora:", "found" if HAVE_CORPORA else f"not present at {CORPORA}")
''')

md("""
## Part 1 — the spectrum, on a general-English corpus

A mark is only as strong as its **strongest element**. `Best Buy` is weak because both words are ordinary; `Häagen-Dazs` is strong because neither is a word at all. So the measure is the rarest token in the mark.
""")

code('''
def strength(mark, counts=ENGLISH, total=ENGLISH_TOTAL):
    """The mark's rarest element and its rate, per million words."""
    tokens = [t for t in re.split(r"[^a-z]+", mark.lower()) if len(t) > 2]
    if not tokens:
        return None, 0.0
    rates = [(t, counts.get(t, 0) / total * 1e6) for t in tokens]
    return min(rates, key=lambda kv: kv[1])

def band(ppm):
    return ("generic"     if ppm > 500 else
            "descriptive" if ppm >  50 else
            "suggestive"  if ppm >   1 else
            "arbitrary / fanciful")

SPECTRUM = {
  "generic / descriptive": ["Best Buy", "Whole Foods", "Sports Direct",
                            "General Motors", "American Airlines"],
  "suggestive":            ["Netflix", "Greyhound", "Coppertone"],
  "arbitrary":             ["Apple", "Amazon", "Shell", "Dove", "Orange"],
  "fanciful (coined)":     ["Kodak", "Xerox", "Exxon", "Verizon", "Zalando"],
}
print(f"  {'mark':<20}{'weakest link':>16}{'per million':>14}   computed band")
print("  " + "-" * 72)
for label, marks in SPECTRUM.items():
    print(f"  {label}")
    for m in marks:
        tok, ppm = strength(m)
        print(f"    {m:<18}{tok:>16}{ppm:>14.1f}   {band(ppm)}")
    print()
''')

md("""
### Read the failures, they are the point

The coined marks land perfectly — `Kodak`, `Xerox`, `Exxon`, `Zalando` all at **0.0 per million**, because they are not words. The arbitrary ones land in a clean middle band: `Apple` 32, `Shell` 27, `Orange` 16, `Dove` 11.

Then three of them are **wrong**, and wrong in the same direction:

```
General Motors    -> "motors"    0.0 ppm -> reads FANCIFUL
American Airlines -> "airlines"  0.0 ppm -> reads FANCIFUL
Burger King       -> "burger"    0.0 ppm -> reads FANCIFUL
```

Those are descriptive marks reading as coined. The cause is not the method — it is the corpus. This table is built from **public-domain Project Gutenberg text, which is overwhelmingly pre-1930**. There were no airlines, no motors industry and no burgers in it. Modern commercial vocabulary is simply absent, and absent reads as rare.

**That is a corpus problem with an obvious owner.** The right corpus for scoring trademarks is a corpus of trademarks and commerce — a register, a marketplace, a catalogue. Anyone holding one gets the whole spectrum correct; the arithmetic is already here.

## Part 2 — why one number per mark is the wrong shape

`Apple` is generic for fruit and arbitrary for computers. Nice classification exists precisely because a word's strength is a property of the **word and the class together**, and no single figure can carry both.

Below, two real product corpora stand in for two classes.
""")

code('''
def corpus_counts(path, field, required, limit=90_000):
    """Token counts over one product corpus, found by its columns."""
    if not path.exists():
        return None
    counts, seen = collections.Counter(), 0
    with path.open(encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        if not required <= set(reader.fieldnames or []):
            return None
        for row in reader:
            text = (row.get(field) or "").strip()
            if not text or text == "NA":
                continue
            seen += 1
            counts.update(re.findall(r"[a-z]{3,}", text.lower()))
            if seen >= limit:
                break
    return counts

CLASSES = {}
if HAVE_CORPORA:
    for path in sorted(CORPORA.glob("*.csv")):
        with path.open(encoding="utf-8-sig", newline="") as fh:
            header = set(next(csv.reader(fh), []))
        if {"gtin", "seller", "name"} <= header and "groceries" not in CLASSES:
            CLASSES["groceries"] = corpus_counts(
                path, "name", {"gtin", "seller", "name"})
        elif {"ITEM_ID", "PRODUCT_TITLE"} <= header and "home goods" not in CLASSES:
            CLASSES["home goods"] = corpus_counts(
                path, "PRODUCT_TITLE", {"ITEM_ID", "PRODUCT_TITLE"})

CLASSES = {k: v for k, v in CLASSES.items() if v}
for name, counts in CLASSES.items():
    print(f"  class '{name}': {sum(counts.values()):,} tokens")
if not CLASSES:
    print("  (no corpora) the measured figures are quoted in the next cell")
''')

code('''
WORDS = ["apple", "orange", "organic", "dove", "shell",
         "wool", "rug", "oval", "king", "blue"]

# Measured on the two corpora, quoted so the narrative holds without them.
FALLBACK = {"apple": (2123.3, 10.6), "orange": (2207.4, 826.2),
            "organic": (3022.7, 32.7), "dove": (366.6, 23.1),
            "shell": (88.1, 45.2), "wool": (38.1, 15882.8),
            "rug": (16.0, 58096.0), "oval": (64.1, 766.5),
            "king": (853.3, 1068.5), "blue": (1894.9, 9312.9)}

def ppm(word, counts):
    total = sum(counts.values())
    return counts.get(word, 0) / total * 1e6

print(f"  {'word':<10}{'groceries':>12}{'home goods':>13}{'ratio':>10}   "
      f"strength as a mark")
print("  " + "-" * 78)
for w in WORDS:
    if CLASSES.get("groceries") and CLASSES.get("home goods"):
        g, h = ppm(w, CLASSES["groceries"]), ppm(w, CLASSES["home goods"])
    else:
        g, h = FALLBACK[w]
    lo, hi = min(g, h), max(g, h)
    ratio = hi / lo if lo else float("inf")
    if ratio < 4:
        verdict = "similar in both classes"
    elif g > h:
        verdict = "WEAK for groceries, strong for home goods"
    else:
        verdict = "strong for groceries, WEAK for home goods"
    print(f"  {w:<10}{g:>12.1f}{h:>13.1f}{ratio:>9.0f}x   {verdict}")
''')

md("""
### What that table says

`apple` occurs **200 times more often** in grocery listings than in home-goods listings. `organic` 92 times more. `wool` 417 times more the other way, `rug` 3,600 times.

So a single "how strong is APPLE" has no answer. For fruit it is generic and unprotectable; for furniture it is arbitrary and strong. **The class is not metadata on the question — it is half of the question.**

This is the same result arche found in its own place data. A frequency table merged across twenty countries called `gidan` — Hausa for *house of*, one of the commonest elements in northern Nigerian place names — distinctive enough to carry a match, because the merged table's common ranks are owned by vocabulary shared across many strata. Scored against Nigerian place names alone it comes out correctly ordinary:

```
gidan   merged 0.678  ->  country-scoped 0.371
tungan  merged 0.782  ->  country-scoped 0.462
```

One population, one table. Twenty populations merged into one table is wrong for all twenty. **Nice classes are the same problem with a legal name attached.**

## Part 3 — strength is one input to a decision, not the decision

Knowing a mark is weak does not tell you whether a listing infringes it. arche returns a verdict, the evidence, and — when the evidence is insufficient — what would settle it, rather than a score somebody downstream has to interpret.
""")

code('''
from arche.resolve import reconcile, would_resolve

def adjudicate(a, b, entity="product_home_goods"):
    ra, rb = {"id": "a", "name": a}, {"id": "b", "name": b}
    edges = reconcile([ra], [rb], entity=entity, id_field="id")["matches"]
    if not edges:
        return None, None
    return edges[0], would_resolve(edges[0], ra, rb, entity=entity)

PAIRS = [
    ("a genuine listing against the same product elsewhere",
     "SAFAVIEH Heritage Wool Area Rug Red Black 3 ft Round",
     "SAFAVIEH Heritage Traditional Wool Area Rug, Red/Black, 3 ft Round"),
    ("two products of one family -- NOT interchangeable",
     "LCM Microfiber Down Alternative Blanket, King, Blue",
     "LCM Microfiber Down Alternative Blanket, Full/Queen, Blue"),
]
for why, a, b in PAIRS:
    edge, advice = adjudicate(a, b)
    print(f"  {why}")
    print(f"    A: {a[:72]}")
    print(f"    B: {b[:72]}")
    if edge is None:
        print("    -> not surfaced as a candidate\\n")
        continue
    print(f"    -> {edge['decision']}   score {edge['score']}  "
          f"distinctive_max {edge['distinctive_max']}")
    print(f"       evidence {dict(list(edge['evidence'].items())[:4])}")
    print(f"       decision id {edge['decision_id'][:38]}...")
    if advice and advice["would_resolve"]:
        top = advice["would_resolve"][0]
        print(f"       to settle it: {top['field']} ({top['effect']})")
    print()
''')

md("""
The `decision_id` is a content hash over the edge and the run's pinned inputs — the frequency table's digest included. Recompute it next year and it either matches or it does not, and if it does not, the pins say which input moved.

For an enforcement workflow that matters more than the score. **A takedown is a legal act, and "why did you flag this listing" has to have an answer that survives a challenge months later.** A similarity number does not survive that. A pinned decision with its evidence does.

## What this is and is not

**It is** a demonstration that trademark strength is computable, that it is class-dependent, and that the same machinery produces an auditable verdict rather than a score.

**It is not** a legal opinion, a substitute for clearance search, or a claim to beat a purpose-built matcher. arche's own engine loses to Splink on batch record linkage — that is measured and published in `docs-site/docs/reference/benchmarks.md`. The differentiated part is the strength model and the decision record, and the scorer underneath is pluggable.

**And the corpus is the whole game.** Part 1 gets coined and arbitrary marks right and descriptive ones wrong, because it is reading Victorian novels. Anyone holding a trademark register or a marketplace catalogue can build the right table in an afternoon — the code is `datasets/english_dataops/build_english_frequencies.py` with a different input, and the per-class version is the same builder run once per class.

## Reproducing this

```sh
python examples/notebooks/build_19.py
ARCHE_RETAIL_DATA=/path/to/corpora jupyter nbconvert --to notebook --execute \\
    --inplace examples/notebooks/19_how_distinctive_is_a_mark.ipynb
```

Part 1 needs only the shipped wheel. Parts 2 and 3 fall back to quoted measurements when no corpora are present.
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

out = Path(__file__).parent / "19_how_distinctive_is_a_mark.ipynb"
out.write_text(json.dumps(nb, indent=1), encoding="utf-8")
print(f"wrote {out}  ({len(cells)} cells)")
