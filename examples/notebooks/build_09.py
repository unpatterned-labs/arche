# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0
"""Generate 09_matching_products.ipynb.

Run from the repo root:  python examples/notebooks/build_09.py
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
# Matching products

**Abt-Buy and Amazon-Google: two public benchmarks, complete ground truth, and one finding that reorders the whole lane.**

Two retailers list the same camera case. One calls it `Canon Deluxe Black Digital Camera Case - 2595B002`, the other `Canon PSC-85 Soft Camera Case - 2595B002`. Nothing about those titles matches except eight characters in the middle.

This notebook runs arche's experimental electronics lane against the [Leipzig product benchmarks](https://dbs.uni-leipzig.de/research/projects/benchmark-datasets-for-entity-resolution) — CC-BY-4.0, and their mappings are *complete*, so false merges are visible rather than assumed.

**Three things it establishes.**

1. A plain name matcher gets **F1 0.3443** here. Product titles are marketing copy.
2. The identity is a rare code, and **rarity — not the code's shape — is the signal.**
3. The lane barely helps on general merchandise, which is why it ships named `product_electronics` rather than `product`.
""")

md("""
## Setup
""")

code("""
import csv, sys
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path.cwd()
while not (REPO / "packages" / "arche-core").exists() and REPO != REPO.parent:
    REPO = REPO.parent
sys.path.insert(0, str(REPO / "packages" / "arche-core" / "src"))

from arche.resolve import crosswalk, ENTITY_PACKS
from arche.resolve._productcode import (
    build_code_table, code_rarity, extract_product_code_candidates,
)

DATA = REPO / "data" / "er_bench" / "products"


def read(name):
    with open(DATA / name, encoding="utf-8-sig", errors="replace", newline="") as fh:
        return list(csv.DictReader(fh))


abt, buy = read("Abt.csv"), read("Buy.csv")
truth = {(r["idAbt"], r["idBuy"]) for r in read("abt_buy_perfectMapping.csv")}
print(f"Abt {len(abt)} x Buy {len(buy)}  ->  {len(truth)} true pairs")
print(f"possible pairs: {len(abt) * len(buy):,}   positive rate: "
      f"{100 * len(truth) / (len(abt) * len(buy)):.4f}%")
""")

md("""
## 1. What a product title actually looks like

Read five true pairs before writing any matcher.
""")

code("""
ia = {r["id"]: r for r in abt}
ib = {r["id"]: r for r in buy}
for a, b in list(truth)[:5]:
    if a in ia and b in ib:
        print(f"  ABT  {ia[a]['name'][:74]}")
        print(f"  BUY  {ib[b]['name'][:74]}")
        print()
""")

md("""
The pattern is the same every time: a manufacturer code, wrapped in whatever copy each retailer felt like writing. `Deluxe Black` against `PSC-85 Soft`. `Super Capacity Drum` against nothing at all.

The code is the identity. Everything else is noise that happens to be longer.

## 2. The baseline, so the improvement is measurable
""")

code("""
A = [{"id": r["id"], "name": r["name"]} for r in abt]
B = [{"id": r["id"], "name": r["name"]} for r in buy]


def score(comparators=None, entity=None, label=""):
    kw = {"comparators": comparators} if comparators else {"entity": entity}
    res = crosswalk(A, B, id_field="id", **kw)
    pred = {(e["a_id"], e["b_id"]): e for e in res["matches"]}
    tp = sum(1 for k, e in pred.items() if e["decision"] == "match" and k in truth)
    fp = sum(1 for k, e in pred.items() if e["decision"] == "match" and k not in truth)
    rv = sum(1 for k, e in pred.items() if e["decision"] == "review" and k in truth)
    p = tp / (tp + fp) if tp + fp else 0.0
    r = tp / len(truth)
    print(f"  {label:<26} P={p:.4f}  R={r:.4f}  F1={2*p*r/(p+r) if p+r else 0:.4f}  "
          f"surfaced={(tp+rv)/len(truth):.4f}  (TP {tp}, FP {fp})")
    return p, r


score(comparators=[{"field": "name", "kind": "name", "weight": 2.0},
                   {"field": "name", "kind": "tftoken", "weight": 2.0}],
      label="name only (baseline)")
""")

md("""
**F1 0.3443.** A name matcher is close to useless here, and that is not a bug in the comparator — it is a fact about product titles. The strings genuinely differ.

## 3. The signal is rarity, not shape

The obvious move is a regex for model numbers. Here is why that alone is not enough.

`extract_product_code_candidates` deliberately returns *candidates* — anything that could be a manufacturer code, a retailer SKU, a spec or a quantity. A regex cannot tell those apart. Rarity can.
""")

code("""
for title in ("Fellowes Powershred Personal SB-97Cs Confetti Cut Shredder - 3219701",
              "Sony 1080p 16GB Handycam HDRCX150"):
    print(f"  {title[:62]:64} -> {sorted(extract_product_code_candidates(title))}")
""")

md("""
Note `3219701` — a retailer SKU, not a manufacturer code — and `16gb`, which is a specification. Both look exactly like model numbers to a regex.

Now block on a shared code and condition on how rare that code is.
""")

code("""
MA = {r["id"]: extract_product_code_candidates(r["name"]) for r in abt}
MB = {r["id"]: extract_product_code_candidates(r["name"]) for r in buy}
tf = build_code_table([r["name"] for r in abt] + [r["name"] for r in buy])

index = defaultdict(list)
for r in buy:
    for code_ in MB[r["id"]]:
        index[code_].append(r["id"])

candidates = defaultdict(set)
for r in abt:
    for code_ in MA[r["id"]]:
        for other in index[code_]:
            candidates[(r["id"], other)].add(code_)

hit = sum(1 for k in candidates if k in truth)
print(f"pairs sharing any code: {len(candidates)}   true: {hit}   "
      f"precision {hit/len(candidates):.4f}")
print()
print(f"{'rarest shared code, doc freq':<30} {'pairs':>7} {'true':>6} {'precision':>10}")
for lo, hi in ((1, 2), (3, 4), (5, 9), (10, 19), (20, 10**6)):
    sel = [k for k, cs in candidates.items()
           if lo <= min(tf._as_counts().get(c, 0) for c in cs) <= hi]
    if not sel:
        continue
    t = sum(1 for k in sel if k in truth)
    label = f"{lo}-{hi if hi < 10**6 else '+'}"
    print(f"{label:<30} {len(sel):>7} {t:>6} {t/len(sel):>10.4f}")
""")

md("""
**That table is the whole lane.**

A code seen once or twice identifies almost perfectly. A code seen twenty or more times — `1080p`, `16gb`, `720p` — identifies **nothing at all**: hundreds of candidate pairs, not one true match among them.

So the signal was never "looks like a model number". It is "is rare". `1080p` is the `General Hospital` of consumer electronics, and the fix is the frequency table arche already uses for places and people, not a cleverer regex.
""")

code("""
print(f"{'code':<12} {'doc freq':>9} {'rarity':>8}")
for c in ("2595b002", "feq332wh", "sb97cs", "16gb"):
    print(f"  {c:<12} {tf._as_counts().get(c, 0):>7.0f} {code_rarity(c, tf):>8.3f}")
print()
print("DISTINCTIVE_FLOOR = 0.75 — only the first three can clear the gate unaided.")
""")

md("""
## 4. The shipped lane
""")

code("""
score(entity="product_electronics", label="product_electronics")
print()
for spec in ENTITY_PACKS["product_electronics"]:
    print(" ", {k: v for k, v in spec.items() if k != "category"})
""")

md("""
**F1 0.3443 → 0.7883**, precision 0.9707, 22 false merges.

Two details in that pack worth reading.

`code` carries the highest weight because a shared *rare* code is the identity, but it returns **0.0 rather than a veto** when both sides have codes and share none — 18.6% of true pairs are in that position, because accessories, bundles and retailer SKUs legitimately disagree. A hard conflict rule would refute all of them.

`spec` uses `refutes_below` under a **purchasable-variant identity contract**: a 16GB and a 32GB player are different products however alike their titles. On this corpus it is exactly neutral — it earns its place from the contract, not from the benchmark, and the changelog says so.

## 5. Where it stops working
""")

code("""
amz, goo = read("Amazon.csv"), read("GoogleProducts.csv")
t2 = {(r["idAmazon"], r["idGoogleBase"]) for r in read("Amzon_GoogleProducts_perfectMapping.csv")}
A2 = [{"id": r["id"], "name": r["title"]} for r in amz]
B2 = [{"id": r["id"], "name": r["name"]} for r in goo]


def score2(kw, label):
    res = crosswalk(A2, B2, id_field="id", **kw)
    pred = {(e["a_id"], e["b_id"]): e for e in res["matches"]}
    tp = sum(1 for k, e in pred.items() if e["decision"] == "match" and k in t2)
    fp = sum(1 for k, e in pred.items() if e["decision"] == "match" and k not in t2)
    p, r = tp / (tp + fp), tp / len(t2)
    print(f"  {label:<26} P={p:.4f}  R={r:.4f}  F1={2*p*r/(p+r):.4f}  (TP {tp}, FP {fp})")


score2({"comparators": [{"field": "name", "kind": "name", "weight": 2.0},
                        {"field": "name", "kind": "tftoken", "weight": 2.0}]},
       "name only (baseline)")
score2({"entity": "product_electronics"}, "product_electronics")
""")

md("""
On Amazon-GoogleProducts — general merchandise rather than consumer electronics — the lane moves F1 from 0.3971 to 0.4007 and **precision falls**, 0.4898 to 0.4863. That is +9 true matches bought with +16 false ones: a marginal precision of **0.36** on the pairs it changes.

The F1 gain is real and it is not worth having. Reporting only F1 would have hidden that.

This is why the pack is named `product_electronics`, is flagged `experimental=True`, and why a test asserts no generic `product` pack exists. The rules that work here fail elsewhere by construction: Levi's `501` is rejected twice by thresholds that exist to filter prices and years, `32x32` looks like a model and is not, and reading `600mg` as a drug's model code would be dangerous.

Adding food, books or apparel is a **category registration plus a benchmark**, not a change to any comparator:

```python
from arche.resolve._productcode import ProductCategory, register_category

register_category(ProductCategory(
    name="apparel",
    min_code_len=3, min_bare_number_len=3,   # Levi's 501 is a real model
    identity_units=("inch",),
    stop_codes=frozenset({"32x32"}),
))
```

""")

md("""
## 6. Making Amazon-Google better

The obvious move is to feed the matcher more fields — both catalogues carry `description`, and Amazon carries `manufacturer` on every row. Measured, that is wrong, in a way worth understanding.
""")

code("""
def rows3(src, namefield):
    return [{"id": r["id"], "name": r[namefield],
             "description": (r.get("description") or "")[:400],
             "manufacturer": r.get("manufacturer") or ""} for r in src]


NAME = [{"field": "name", "kind": "name", "weight": 2.0},
        {"field": "name", "kind": "tftoken", "weight": 2.0}]
A3, B3 = rows3(amz, "title"), rows3(goo, "name")


def bench(label, comps, b=None):
    res = crosswalk(A3, b or B3, comparators=comps, id_field="id")
    pred = {(e["a_id"], e["b_id"]): e for e in res["matches"]}
    tp = sum(1 for k, e in pred.items() if e["decision"] == "match" and k in t2)
    fp = sum(1 for k, e in pred.items() if e["decision"] == "match" and k not in t2)
    p, r = tp / (tp + fp), tp / len(t2)
    print(f"  {label:<28} P={p:.4f}  R={r:.4f}  F1={2*p*r/(p+r):.4f}  (TP {tp}, FP {fp})")


""")

code("""
bench("name only (baseline)", NAME)
""")

code("""
bench("+ description", NAME + [{"field": "description", "kind": "tftoken", "weight": 1.0}])
""")

code("""
bench("+ manufacturer", NAME + [{"field": "manufacturer", "kind": "name", "weight": 1.0}])
""")

md("""
**Adding descriptions is catastrophic** — recall falls from 0.334 to 0.129. Manufacturer is break-even.

The reason is visible in the data. Descriptions are marketing copy each retailer wrote independently:

```text
AMZ  swat 4: special weapons and tactics
     'looking for a tactical shooter that asks you to do more than charg...'
GOO  vivendi-universal games inc swat 4
     'it is not just about the badge it is about the rush! the adrenaline...'
```

Mean Jaccard on true pairs is **0.448 for titles and 0.119 for descriptions**. Adding description as a weighted comparator dilutes real agreement with near-noise. More fields is not more signal.

But look again at those two titles. **Google prefixes the publisher and Amazon does not** — and Amazon states that publisher in its own `manufacturer` column, on 100% of rows. That is the same representation mismatch the place lane hit with trailing region qualifiers, arriving at the front of the string instead of the back.
""")

code("""
from arche.resolve._productcode import build_brand_prefixes, strip_brand_prefix

brands = build_brand_prefixes(r.get("manufacturer") for r in amz)
prefixed = sum(1 for r in goo if strip_brand_prefix(r["name"], brands)[1])
print(f"brands learned from Amazon's manufacturer column: {len(brands)}")
print(f"Google titles carrying one as a prefix: {prefixed}/{len(goo)} "
      f"({100*prefixed/len(goo):.0f}%)")
print()

B4 = [{"id": r["id"], "name": strip_brand_prefix(r["name"], brands)[0],
       "description": "", "manufacturer": ""} for r in goo]
bench("publisher prefix stripped", NAME, b=B4)
""")

md("""
**Both precision and recall improve** — F1 0.3971 to 0.4275, with 30 more true matches and 45 fewer false ones.

That is unusual. The prefix was doing two bad things at once: diluting agreement between two listings of the same product, and manufacturing agreement between unrelated products from the same publisher. Removing it fixes both, which is why this is not the usual precision-for-recall trade.

The brand list is **self-calibrated from the corpus**, exactly like the code frequency table. No shippable list of publishers would cover an arbitrary catalogue, and the vocabulary that matters is the one in the data being matched.

## What this establishes, and what it does not

**Establishes.** On a public benchmark with complete ground truth, neither built nor labelled by us, the lane takes F1 from 0.3443 to 0.7883 at precision 0.9707. The mechanism is rarity, measured, not asserted.

**Does not establish.**

* **One vertical.** Consumer electronics. The Amazon-Google result above is the evidence that it does not generalise as-is.
* **The stop list does nothing here.** With `stop_codes` emptied the end-to-end result is byte-identical — the frequency table already suppresses `1080p`. The list earns its place on catalogues too small to estimate frequency from, which this benchmark cannot show.
* **The `spec` refutation is unvalidated.** Exactly neutral on Abt-Buy, entirely inert on Amazon-Google, where no true pair carries a comparable unit. 47 of 1,097 pairs is not an evidence base.
* **Titles only.** The pack reads `name`. `description`, `manufacturer` and `price` are all present in the data and all unused.

*Related: [the product tutorial](../../docs-site/docs/tutorials/products.md) · [what is the false-merge rate?](06_what_is_the_false_merge_rate.ipynb) · provenance in `data/er_bench/SOURCES.md`*
""")

nb = {
    "cells": [
        {"cell_type": kind, "metadata": {},
         "source": (src + "\n").splitlines(keepends=True),
         **({"execution_count": None, "outputs": []} if kind == CODE else {})}
        for kind, src in cells
    ],
    "metadata": {
        "kernelspec": {"display_name": "Python 3", "language": "python",
                       "name": "python3"},
        "language_info": {"name": "python", "version": "3.12"},
    },
    "nbformat": 4, "nbformat_minor": 5,
}
out = Path(__file__).resolve().parent / "09_matching_products.ipynb"
out.write_text(json.dumps(nb, indent=1, ensure_ascii=False), encoding="utf-8")
n_code = sum(1 for k, _ in cells if k == CODE)
print(f"wrote {out}  ({len(cells)} cells, {n_code} code)")
