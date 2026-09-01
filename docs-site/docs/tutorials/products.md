# Matching products

Two retailers list the same camera case. One calls it `Canon Deluxe Black Digital Camera Case - 2595B002`; the other calls it `Canon PSC-85 Soft Camera Case - 2595B002`. Nothing about those titles matches except eight characters in the middle.

This tutorial is the product lane end to end: what makes product titles hard, why the obvious fix is the wrong one, and exactly where the shipped pack stops working. Everything here is measured on the [Leipzig product benchmarks](https://dbs.uni-leipzig.de/research/projects/benchmark-datasets-for-entity-resolution) (CC-BY-4.0), whose mappings are *complete*, so false merges are visible rather than assumed.

The runnable version is [notebook 09](https://github.com/unpatterned-labs/arche/blob/main/examples/notebooks/09_matching_products.ipynb).

---

## The short version

```python
from arche.resolve import reconcile

result = reconcile(abt, buy, entity="product_electronics", id_field="id")
```

| | name matcher | `product_electronics` |
|---|---|---|
| precision | 0.7954 | **0.9707** |
| recall | 0.2197 | **0.6636** |
| F1 | 0.3443 | **0.7883** |
| false merges | 62 | **22** |

---

## Why product titles defeat a name matcher

Read five true pairs before writing anything:

```text
ABT  Frigidaire Electric White Dryer - FEQ332WH
BUY  Frigidaire Electric Dryer - FEQ332WH 5.7 Cu.Ft. Super Capacity Drum

ABT  Canon Deluxe Black Digital Camera Case - 2595B002
BUY  Canon PSC-85 Soft Camera Case - 2595B002

ABT  Sony 19' BRAVIA M-Series Silver LCD Flat Panel HDTV - KDL19M4000S
BUY  Sony BRAVIA M Series KDL-19M4000 19' LCD TV - kdl19m4000s
```

The pattern never varies: a manufacturer code, wrapped in whatever copy each retailer felt like writing. `Deluxe Black` against `PSC-85 Soft`. The code is the identity; the rest is noise that happens to be longer than the signal.

A plain name matcher scores **F1 0.3443** on this. That is not a comparator bug, the strings genuinely differ.

Normalisation is most of what remains. Matching raw strings finds a shared code on 44.9% of true pairs; matching normalised ones finds it on **71.2%**, because one source writes `SB97CS` and the other `SB-97Cs`.

---

## The finding: rarity, not shape

The obvious move is a regex for model numbers. It is not enough, and the reason matters.

`extract_product_code_candidates` deliberately returns *candidates*, anything that could be a manufacturer code, a retailer SKU, a specification or a quantity:

```python
from arche.resolve._productcode import extract_product_code_candidates

extract_product_code_candidates("Fellowes Powershred SB-97Cs Shredder - 3219701")
# {'sb97cs', '3219701'}          <- one model code, one retailer SKU
extract_product_code_candidates("Sony 1080p 16GB Handycam HDRCX150")
# {'16gb', 'hdrcx150'}           <- one model code, one specification
```

A regex cannot tell those apart. Document frequency can:

| rarest shared code, doc freq | pairs | true | precision |
|---|---|---|---|
| **1–2** | 754 | 752 | **0.9973** |
| 3–4 | 47 | 23 | 0.4894 |
| 5–9 | 55 | 6 | 0.1091 |
| **20+** | 503 | 0 | **0.0000** |

A code seen once or twice identifies almost perfectly. A code seen twenty or more times, `1080p`, `16gb`, `720p`, identifies **nothing at all**. Five hundred candidate pairs, not one true match among them.

So the signal was never "looks like a model number". It is "is rare", which is the same machinery arche already uses for places and people. `1080p` is the `General Hospital` of consumer electronics.

```python
from arche.resolve._productcode import build_code_table, code_rarity

tf = build_code_table(titles)
code_rarity("2595b002", tf)   # 1.000  - appears twice in the catalogue
code_rarity("16gb", tf)       # 0.182  - appears eleven times
```

Only the first clears `DISTINCTIVE_FLOOR` (0.75) unaided.

### A calibration bug worth knowing about

The first version of this lane made things *worse*, recall fell from 0.2197 to 0.0948. `TokenFrequencyTable.distinctiveness` is `min(1, -log10(rel_freq)/5)`, calibrated for the million-token word corpora behind the place and person tables. A code vocabulary is about two thousand documents, so the rarest possible shared code scored **0.6205** through it, below the gate floor, and the gate demoted every true product match.

The formula was not wrong; it was being asked a question about a different distribution. `code_rarity` scores document frequency relative to what a unique code looks like *in that corpus*, which also survives a catalogue where every product is listed several times.

---

## The pack, and two decisions inside it

```python
ENTITY_PACKS["product_electronics"] = [
    {"field": "name", "kind": "name",    "weight": 1.5},
    {"field": "name", "kind": "code",    "weight": 3.0, "category": "electronics"},
    {"field": "name", "kind": "tftoken", "weight": 1.5},
    {"field": "name", "kind": "spec",    "weight": 0.5, "category": "electronics",
     "refutes_below": 0.5},
]
```

**A conflicting code does not refute.** `code` returns `0.0` rather than a veto when both sides carry codes and share none, because 18.6% of true pairs are in exactly that position, accessories, bundles, replacement parts and retailer SKUs legitimately disagree. A hard conflict rule would refute all of them.

**A conflicting specification does.** `spec` uses `refutes_below` under a **purchasable-variant identity contract**: a 16GB and a 32GB player are different products however alike their titles. Be aware this is unvalidated, on Abt-Buy it is exactly neutral, and on Amazon-Google entirely inert. It earns its place from the contract, not from either benchmark.

---

## Where it stops working

On Amazon-GoogleProducts, general merchandise rather than consumer electronics:

| Amazon-Google | baseline | `product_electronics` |
|---|---|---|
| precision | 0.4898 | **0.4863** |
| F1 | 0.3971 | 0.4007 |
| false merges | 452 | **468** |

The F1 goes up and the **precision goes down**. That is +9 true matches bought with +16 false ones, a marginal precision of 0.36 on the pairs it changes. The gain is real and it is not worth having, and reporting only F1 would have hidden it.

This is why the pack is named `product_electronics` rather than `product`, is flagged `experimental=True`, and why a test asserts no generic `product` pack exists. The rules that work here fail elsewhere by construction:

- Levi's **`501`** is a real model that gets rejected twice, once for being under four characters, once for being a bare number under five digits. Those thresholds exist to filter prices and years out of electronics titles.
- **`32x32`** looks exactly like a model code and is a waist and inseam.
- **`600mg`** would be read as a drug's model code, which is dangerous rather than merely wrong.

---

## Adding a category

New verticals are a **registration plus a benchmark**, not a change to any comparator:

```python
from arche.resolve._productcode import ProductCategory, register_category

register_category(ProductCategory(
    name="apparel",
    min_code_len=3,            # so `501` survives
    min_bare_number_len=3,
    identity_units=("inch",),  # waist/inseam distinguish variants
    stop_codes=frozenset({"32x32"}),
))
```

`identity_units` is where the **identity contract** lives: which specifications make two listings different purchasable things. Under a SKU reading, capacity and pack size are identity-bearing and a disagreement refutes. Under a product-family reading they are attributes and it does not. Changing that tuple changes what the lane means, which is why it is data on a category rather than a constant in a comparator.

The benchmark half is not optional. Everything on this page is one vertical, and the Amazon-Google result is the evidence for what happens when you assume it generalises.

---

## Reproduce it

```bash
python examples/notebooks/build_09.py
jupyter nbconvert --to notebook --execute --inplace \
  --ExecutePreprocessor.kernel_name=arche-venv \
  examples/notebooks/09_matching_products.ipynb
```

Data provenance and licence are in `data/er_bench/SOURCES.md`. If a number here does not reproduce, that is a bug and we want the issue.
