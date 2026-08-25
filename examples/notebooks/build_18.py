# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0
"""Generate 18_matching_retail_products.ipynb.

    python examples/notebooks/build_18.py

What was actually done to make arche match retail products across two
retailers, including the sampling mistake that made the first round of numbers
wrong.

The notebook reads a data directory the reader supplies. The corpus is client
data and is not in this repository, so every cell degrades to an explanation
when it is absent -- the narrative and the code stay readable either way.
"""
from __future__ import annotations

import json
from pathlib import Path

MD, CODE = "markdown", "code"
cells: list[tuple[str, str]] = []
md = lambda t: cells.append((MD, t.strip("\n")))      # noqa: E731
code = lambda t: cells.append((CODE, t.strip("\n")))  # noqa: E731


md("""
# Matching retail products across two retailers

**What was done, what it measured, and the mistake in the middle that made the first answer wrong.**

The question: two retailers list the same product under different titles. Can arche tell which of Walmart's listings is which of Amazon's — and, more importantly, can it *avoid* merging two listings that are near-identical but different?

That second half is the one that costs money. A wrong merge makes a repricer act on a comparison between two different products.

## The data, and why it has real truth

Two feeds, both client data and neither in this repository:

| feed | truth | why it is trustworthy |
| --- | --- | --- |
| Cross-retailer offers | `ITEM_ID` shared across retailers | A vendor's internal key, assigned before anyone asked it to be a benchmark |
| UK grocery, five supermarkets | `gtin` (barcode) | An **external standard**. Nobody assigned it with an interest in how matching turns out |

Both give **complete truth over the sampled block** — every pair not sharing the key is a known negative — which is what makes a false-merge rate countable rather than estimated.

The barcode is the better of the two. It is the only truth in this project not produced by a party with a stake in the answer.
""")

code('''
import os, warnings, collections, csv, pathlib
warnings.filterwarnings("ignore")
csv.field_size_limit(10_000_000)

# Point this at your own copy:
#     ARCHE_RETAIL_DATA=/path/to/corpus jupyter lab
# Every cell below degrades to an explanation when it is absent, so the
# notebook stays readable without the data -- which is the normal case,
# because the corpus is a commercial feed and is not distributed here.
DATA = pathlib.Path(os.environ.get("ARCHE_RETAIL_DATA", "./retail-corpus"))

HAVE_DATA = DATA.exists()
print("data directory:", "found" if HAVE_DATA else f"not present at {DATA}")
if HAVE_DATA:
    for f in sorted(DATA.glob("*.csv")):
        print(f"   {f.name:<46}{f.stat().st_size/1e6:>8.0f} MB")
''')

md("""
## The mistake worth reading first

The first benchmark took the first 600 pairs in file order. That is not a sample. It turned out to be **83% one vendor's rug catalogue**, and every number measured from it described SAFAVIEH rather than retail matching.

The consequences were not subtle. Precision read 0.13 lower than it really is, the pack built in response looked like a *regression* when it is a large improvement, and a whole round of conclusions had to be withdrawn.

File order is never random. Sample across a grouping key.
""")

code('''
# The two sampling strategies, on the same source.
def load_items(limit_rows=250_000):
    """Cross-retailer offers grouped by the shared product id."""
    if not HAVE_DATA:
        return {}
    by_item = collections.defaultdict(dict)
    # Found by columns, not by filename: any CSV carrying these headers is an
    # offer feed, whatever the supplier called their export.
    wanted = {"ITEM_ID", "PRODUCT_TITLE", "COMPANY_NAME"}
    for path in sorted(DATA.glob("*.csv")):
        with path.open(encoding="utf-8-sig", newline="") as fh:
            if not wanted <= set(next(csv.reader(fh), [])):
                continue
        with path.open(encoding="utf-8-sig", newline="") as fh:
            for i, row in enumerate(csv.DictReader(fh)):
                if i >= limit_rows:
                    break
                item = (row.get("ITEM_ID") or "").strip()
                title = (row.get("PRODUCT_TITLE") or "").strip()
                company = (row.get("COMPANY_NAME") or "").strip()
                if item and title and company:
                    by_item[item].setdefault(company, {
                        "title": title, "brand": (row.get("BRAND") or "").strip()})
    return {i: v for i, v in by_item.items() if "Amazon" in v and "Walmart" in v}

items = load_items()
if items:
    def brand(v): return (v["Amazon"]["brand"] or "?").upper()

    prefix = list(items)[:600]                       # what the first run did
    by_brand = collections.defaultdict(list)
    for key, v in items.items():
        by_brand[brand(v)].append(key)
    spread = []                                      # what it should do
    for _, keys in sorted(by_brand.items()):
        spread.extend(keys[::max(1, len(keys)//40)][:40])
    spread = spread[:600]

    for label, block in (("first 600 in file order", prefix),
                         ("600 spread across brands", spread)):
        counts = collections.Counter(brand(items[k]) for k in block)
        top, n = counts.most_common(1)[0]
        print(f"  {label:<28}{len(counts):>4} brands   top: {top} at {n/len(block):.0%}")
else:
    print("  (no data) first 600 in file order was 83% SAFAVIEH; spread was 67 brands, top 12%")
''')

md("""
## What the errors looked like

Three shapes, and none of them is a string-similarity failure. Every wrong merge was two listings that really are nearly the same words — and really are different products.
""")

code('''
EXAMPLES = [
  ("asymmetry: a variant page against a family page",
   "LCM Home Fashions Microfiber Down Alternative Blanket, King, Blue",
   "LCM Home Fashions Microfiber Plush Down Alternative Blanket"),
  ("a measurement that was extracted and never consulted",
   "Oriental Furniture 7 ft. Tall Double Cross Shoji Screen Honey 3 Panels",
   "Oriental Furniture 6 ft. Tall Double Cross Shoji Screen Natural 3 Panels"),
  ("rival identifiers: a product code against a design name",
   "SAFAVIEH Antiquity Collection 4'6\\" x 6'6\\" Oval Blue AT21E Handmade "
   "Traditional Oriental Premium Wool Area Rug",
   "SAFAVIEH Antiquity Bethanie Traditional Wool Area Rug, Blue/Beige, "
   "4'6\\" x 6'6\\" Oval"),
]
for why, a, b in EXAMPLES:
    print(f"  {why}")
    print(f"    A: {a[:96]}")
    print(f"    B: {b[:96]}")
    print()
''')

md("""
`product_electronics` called all three a **match**. Its two safety mechanisms are inert on home goods: `code` finds no model numbers in a furniture title, and `spec` is `category="electronics"` — it knows GB and GHz, and `King`, `Blue` and `3 Panels` mean nothing to it. What survives is title similarity with a rarity gate, which merges variants of one family.

## What was built in response

Three mechanisms, each aimed at one shape above.
""")

code('''
from arche.resolve import ENTITY_PACKS, describe_pack

for pack in ("product_electronics", "product_home_goods", "product_grocery"):
    d = describe_pack(pack)
    kinds = [c["kind"] for c in ENTITY_PACKS[pack]]
    print(f"  {pack}")
    print(f"    {d['purpose'][:88]}")
    print(f"    comparators: {kinds}")
    print()
''')

md("""
**`home_goods` category** — lengths in feet and inches become identity-bearing (a 6 ft room divider is not the 7 ft one; the electronics rules already *extracted* `ft` and simply never asked about it), plus categorical vocabularies for size, colour, material and shape, because what distinguishes home goods are words rather than measurements.

**The variant-versus-family asymmetry** — one listing declares `King, Blue`, the other declares nothing about size or colour because it is the family page. Everywhere else in arche an absent field is missing evidence rather than a disagreement; here it is the commonest way a catalogue misleads, so it is an opt-in flag on the category.

**The rival-token rule** — each side carries a distinctive token the other lacks. `at21e` against `bethanie`: a product code and a design name, neither shared, two different rugs. No word list enumerates design names, so this is a rule rather than a vocabulary.
""")

code('''
from arche.resolve._gate import rival_distinctive_tokens, tokenset_similarity
from arche.resolve._productcode import compare_specs, extract_attributes

pairs = {
  "size + colour, one side only": (
      "LCM Microfiber Down Alternative Blanket, King, Blue",
      "LCM Microfiber Plush Down Alternative Blanket"),
  "6 ft against 7 ft": (
      "Oriental Furniture 7 ft. Tall Shoji Screen Honey 3 Panels",
      "Oriental Furniture 6 ft. Tall Shoji Screen Natural 3 Panels"),
}
for label, (a, b) in pairs.items():
    print(f"  {label}")
    print(f"    attributes A : {extract_attributes(a, 'home_goods')}")
    print(f"    attributes B : {extract_attributes(b, 'home_goods')}")
    print(f"    spec verdict : {compare_specs(a, b, 'home_goods')}   (0.0 refutes)")
    print()
''')

md("""
## The mutual requirement, which is the safety property

The rival rule fires **only when both sides** carry their own unshared rare token. One side being more verbose means almost nothing — retailers write titles at different lengths, and the terser listing of a true pair is missing tokens constantly.

Three refinements were forced by measured regressions, each of which looked correct before it was run:

1. **Rarity has to be corpus-relative.** A hardcoded 0.75 floor is unreachable for a table calibrated over two catalogues — the rarest token scores 0.861 and the two identifiers score 0.721 and 0.706.
2. **Spelling variants are not rivals.** `panels` against `panel` was refuting true pairs that agreed on everything.
3. **A shared distinctive token wins.** Two listings sharing a product code are one item described twice, whatever else differs.
""")

code('''
from arche.resolve import TokenFrequencyTable
from arche.resolve._gate import _distinctiveness_ceiling as _ceiling

# The corpus has to look like a catalogue. A four-line one has a
# distinctiveness ceiling of 0.316, which drags the rule's own threshold to
# 0.237 -- low enough that any shared ordinary word suppresses it, so the rule
# never fires and the demonstration shows nothing. That is a real fragility
# worth knowing about: this rule needs vocabulary spread to mean anything.
if HAVE_DATA:
    corpus = [v["Amazon"]["title"] for v in list(items.values())[:1500]]
    corpus += [v["Walmart"]["title"] for v in list(items.values())[:1500]]
else:
    corpus = ([f"SAFAVIEH {c} Traditional Wool Area Rug, {col}, Oval"
               for c in ("Antiquity", "Heritage", "Anatolia", "Lyndhurst",
                         "Adirondack", "Madison", "Evoke", "Amherst")
               for col in ("Blue/Beige", "Red/Black", "Ivory/Grey")]
              + [f"Kingston Brass Tub and Shower Faucet, {f}"
                 for f in ("Polished Chrome", "Brushed Nickel", "Oil Rubbed Bronze",
                           "Satin Brass", "Matte Black")]
              + [f"Oriental Furniture {n} ft. Tall Shoji Screen {c} 3 Panels"
                 for n in (4, 5, 6, 7) for c in ("Black", "Natural", "Honey")])
tf = TokenFrequencyTable.from_corpus(corpus)
print(f"  corpus of {len(corpus)} titles, "
      f"distinctiveness ceiling {_ceiling(tf):.3f}")
print()

checks = [
  ("two different rugs, code vs design name",
   "SAFAVIEH Antiquity Collection Oval Blue AT21E Handmade Wool Area Rug",
   "SAFAVIEH Antiquity Bethanie Traditional Wool Area Rug, Blue/Beige, Oval"),
  ("one faucet, two descriptions (shares KB241KL)",
   "Kingston Brass KB241KL Tub and Shower Faucet, Polished Chrome 5-Inch Spout Reach",
   "Kingston Brass KB241KL Knight Tub and Shower Faucet, Polished Chrome"),
  ("a terser listing is not a contradiction",
   "SAFAVIEH Antiquity Collection Oval Blue AT21E Handmade Wool Area Rug",
   "SAFAVIEH Antiquity Wool Area Rug"),
]
for label, a, b in checks:
    verdict = rival_distinctive_tokens(a, b, tf)
    print(f"  {str(verdict):<6} {'refutes' if verdict == 0.0 else 'stays quiet':<12} {label}")
''')

md("""
## Running the benchmark

`datasets/bench_product_matching.py` takes a data directory, so the harness ships and the corpus does not.
""")

code('''
import subprocess, sys, pathlib
repo = pathlib.Path.cwd().parents[1] if (pathlib.Path.cwd()/"build_18.py").exists() else pathlib.Path.cwd()
script = repo / "datasets" / "bench_product_matching.py"
print(f"  python {script.relative_to(repo) if script.exists() else script} <data-dir> --limit 4000")
print()
if HAVE_DATA and script.exists():
    out = subprocess.run([sys.executable, str(script), str(DATA),
                          "--limit", "400", "--suite", "grocery"],
                         capture_output=True, text=True, timeout=1800)
    print("\\n".join(l for l in out.stdout.splitlines()
                     if l.strip() and "INFO" not in l))
else:
    print("  (no data) run the line above against your own copy")
''')

md("""
## What the numbers mean, and the metric to distrust

**Precision is the number that matters here and F1 is not.** F1 weights a missed match and a wrong merge equally. A pricing pipeline does not: a wrong merge acts on the world, a held pair costs a human glance.

Measured across four comparator sets, five distinctiveness floors and several thresholds, F1 on this data sits between 0.55 and 0.59 in every configuration. What moves is the trade:

* At the shipped default the engine is at **precision ~0.97 with two false merges in 150 pairs**.
* Every configuration that beats it on F1 buys recall with **four to eighteen times** the false merges.

A held pair is not a loss. It comes back with its evidence and a reason, and `would_resolve` names the field that would settle it.

## Two defects the grocery pack surfaced

Writing a pack for supermarket data found both, and both were real.

**A refutation was deleting edges instead of demoting them.** `Tesco Almonds 200G` against `Tesco Almonds 500G` scored 0.505 — under the return floor — so the edge vanished entirely and a reviewer never saw the size conflict. Fixed by making the refuting comparator a pure discriminator at weight 0.0, so it refutes without dragging the score down.

**Own-label products were merging.** `Tesco Chopped Tomatoes 400g` and `Sainsbury's Chopped Tomatoes 400g` matched at 0.735 — different products, identical net contents, the same category words. The retailer name is the only separator, and it is exactly what the rival rule reads.
""")

code('''
from arche.resolve import reconcile

SHELF = ["Tesco Almonds 200G", "Tesco Almonds 500G", "Tesco Cashews 200G",
         "Sainsbury's Almonds 200g", "Tesco Chopped Tomatoes 400g",
         "Sainsbury's Chopped Tomatoes 400g", "Heinz Baked Beans 415g"] * 12

def grocery(a, b):
    table = TokenFrequencyTable.from_corpus([*SHELF, a, b])
    edges = reconcile([{"id": "a", "name": a}], [{"id": "b", "name": b}],
                      ENTITY_PACKS["product_grocery"], tf=table,
                      id_field="id", block=None)["matches"]
    return edges[0]["decision"] if edges else "not surfaced"

for a, b, note in [
    ("Tesco Almonds 200G", "Tesco Almonds 500G",
     "two sizes -> two products; before the fix this edge was DROPPED, not held"),
    ("Tesco Chopped Tomatoes 400g", "Sainsbury's Chopped Tomatoes 400g",
     "two own-labels -> not one product; before the rival rule this MATCHED"),
    ("Heinz Baked Beans 415g", "Heinz Baked Beanz 415G",
     "one branded item spelled two ways -> held on this toy shelf"),
]:
    print(f"  {grocery(a, b):<8} {note}")

print()
print("  The third is neither a defect nor a success. On a seven-line shelf the")
print("  score is 0.68 against a 0.70 threshold and `rival` stayed quiet, so the")
print("  pair is held. Abstaining on thin evidence is the designed behaviour,")
print("  and a real catalogue behind the table moves it -- which is what the")
print("  benchmark above measures: 0.926 precision over 400 barcode pairs.")
''')

md("""
## Honest limits

**One vendor can dominate a result.** 41 of 43 false merges in one run were a single rug catalogue where Amazon lists by product code and Walmart by design name. Set that cluster aside and precision on the same run goes from 0.736 to 0.954. Always segment before concluding.

**Rarity cannot separate a product code from an ordinary word.** In a catalogue-sized self-calibrated corpus `spout` scores 0.766 and `at21e` scores 0.721 — an English word rarer than an identifier. A general-English table was built from public-domain text to fix this; it separates every motivating case correctly and **moved the benchmark not at all**, because the wrongly-refuted pairs turned out to come from a different comparator entirely. It is insurance, not a lever.

**Own-label equivalence is out of scope.** A Tesco value tin and an Aldi value tin are a comparable basket item, not the same product, and no barcode links them.

**The grocery accuracy number cannot be reproduced from a clean checkout**, because the corpus is client data. That is stated wherever the number appears.

## Reproducing this

```sh
python examples/notebooks/build_18.py
jupyter nbconvert --to notebook --execute --inplace \\
    examples/notebooks/18_matching_retail_products.ipynb
```

Cells that need the corpus explain themselves when it is absent; the rest run on the shipped wheel.

The mechanisms are pinned in `packages/arche-core/tests/test_home_goods_lane.py`, `test_rival_tokens.py` and `test_grocery_lane.py` — each with a class recording what it still gets wrong, so the limits above stay visible rather than becoming folklore.
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

out = Path(__file__).parent / "18_matching_retail_products.ipynb"
out.write_text(json.dumps(nb, indent=1), encoding="utf-8")
print(f"wrote {out}  ({len(cells)} cells)")
