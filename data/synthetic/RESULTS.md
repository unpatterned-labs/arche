# Stratified results — `ng_supplier_v0`, seven arms

**Measured 2026-09-08** by `run_benchmark.py`. Every number here was produced on the machine that printed it; nothing is carried over from a previous run or another benchmark.

Two tables, each internally consistent, each labelled with its scale. The seven-arm table is the main one — it is the only place every arm is comparable — and it runs at 150 suppliers because the ledger arms are O(n²) and the whole set has to fit in one sitting.

```bash
python data/synthetic/build_ng_supplier_v0.py --scale 150 --out data/synthetic/worlds/ng_supplier_v0_s150
python data/synthetic/run_benchmark.py --world data/synthetic/worlds/ng_supplier_v0_s150
```

## The table — 150 suppliers, 455 records, 567 true pairs

```
arm                        P      R     F1  cover     change  represent    error  falseMrg  blockR    secs
exact                  0.908  0.416  0.571  0.416      0.198      0.397    0.292     0.010   0.416     0.0
jaro_winkler           0.772  0.906  0.834  0.906      0.942      0.898    0.876     0.054   0.989     0.0
splink                 0.984  0.739  0.844  0.739      0.512      0.745    0.722     0.021   0.995     4.4
arche/pack             0.986  0.732  0.840  0.970      0.395      0.727    0.661     0.005   0.991   238.8
arche/custom           0.992  0.674  0.802  0.910      0.314      0.664    0.584     0.005   0.991   235.9
arche/ledger           0.906  0.769  0.832  0.769      0.477      0.762    0.715     0.009     n/a   519.1
arche/ledger+observe   0.860  0.788  0.822  0.788      0.523      0.784    0.734     0.008     n/a   532.3
```

`cover` counts pairs an engine *surfaced for review* as well as merged — without it an engine with three answers is scored as though it had two. The stratum columns are **recall only**: a false merge joins two different entities, has no difference row, and belongs to no stratum. `blockR` is `n/a` for the ledger arms because they do not enumerate a candidate set, and filling it in with their own recall would be a lie in the flattering direction.

## 1. Relocation defeats every engine that reads the address

Recall on the 45 relocated pairs, which is the stratum this whole dataset exists to expose:

```
exact                 0.022        arche/pack            0.111
splink                0.222        arche/custom          0.111
arche/ledger          0.178        arche/ledger+observe  0.267
jaro_winkler          0.956  ← reads names only
```

**Every engine that uses the address fails.** A rule join finds 2%, arche finds 11%, Splink — an independent Fellegi-Sunter implementation with parameters estimated from the data — finds 22%. The only arm that succeeds is the one that never looks at the field that changed.

That is the finding. Not "arche is bad at relocation" but **"the address is treated as refuting evidence by every engine that reads it, and a supplier moving is therefore indistinguishable from a supplier being a different company."** No published entity-resolution benchmark can show this, because none of them label *why* two records disagree.

Jaro-Winkler's 0.956 must not be read as competence. It compares names and nothing else, so a changed address cannot hurt it — and the bill arrives in the next column: precision 0.772 against arche's 0.986, with the false merges concentrated on shared surname heads, which is exactly what the Zipf name draw was put there to produce. **An arm can top the change stratum by ignoring evidence.**

## 2. The ledger is the only thing that moves the number

This is what S5 was built to test, and it works.

```
arche/pack             0.111   one-shot batch comparison
arche/ledger           0.178   the same engine, records ingested in observed_at order   +60%
arche/ledger+observe   0.267   ... then the operator's registry lookup                 +140%
```

`arche/pack` at 0.111 with `cover` 0.970 was never *missing* the relocated pairs — it was refusing them. The `organisation` pack compares `address` with a `premises` comparator declared `refutes_below: 0.5`, so a wholly changed address demotes the pair to `review` however well the name and RC number agree. Feeding records in arrival order and letting later evidence supersede earlier decisions recovers 60% more of them; adding the operator's move — an open case sends somebody to the companies register — recovers 140% more.

Overall recall improves too, 0.732 → 0.769 → 0.788, the best of any arm that is not blind.

**The trade is visible and should be stated: precision falls, 0.986 → 0.906 → 0.860.** The ledger links transitively, so a wrong link propagates through an entity in a way a pairwise merge does not. Which end of that trade is right is a policy question and depends on whether a false merge or a false split costs more in the workflow — but the benchmark can now price both.

`arche/ledger+observe` is an **assisted** number and is labelled as one everywhere it appears. The lookup key is the RC number, an identifier the records carry, never the truth mapping — but two records sharing an RC number are already strong evidence, so this measures whether `observe()` propagates and re-decides correctly, not whether arche finds the link unaided.

## 3. Splink and arche land in nearly the same place

```
splink       P 0.984   R 0.739   F1 0.844   4.4 s
arche/pack   P 0.986   R 0.732   F1 0.840   238.8 s
```

Two independently written engines, one of them not ours, agreeing to three decimal places on precision and within 0.007 on recall. That is the most reassuring row in the table: it says the benchmark is measuring the problem rather than a quirk of one implementation. It also **completes the trigger for cutting the separate repository** — a stratified result exists and arche is not the only arm.

Splink beats arche on relocation (0.222 vs 0.111) and loses on coverage, having no third answer to give. It is also **54× faster**.

Getting this arm to be fair took two corrections, both recorded because both would have flattered arche:

- **The first version scored 0.000 on relocations.** Not a Splink limitation — `block_on` is case-sensitive, 57% of this world's representation differences are a source that stores records IN CAPITALS, and every blocking key broke on case alone. Blocking recall was 0.404. Normalising before loading, which is what every Splink user does, took it to 0.995.
- **The threshold was borrowed and wrong.** 0.99, taken from the existing Febrl benchmark, cost 0.53 recall: at 0.99 Splink scores R 0.207/P 1.000, at its own 0.5 decision boundary R 0.731/P 0.940. Imposing an arche-flavoured caution on an engine that has no third answer is the same error as scoring arche on a probability cut, which this project already knows not to do.

A badly configured competitor is worse than no competitor.

## 4. Reading more fields made matching worse

`arche/custom` maps in the four fields the shipped pack ignores — phone, TIN, account number, director. Recall falls 0.732 → 0.674 and `ACCOUNT_CHANGED` recall falls 0.750 → 0.188.

The reason is structural. Those fields are disproportionately the ones that *legitimately change* or are *absent*, so they disagree on exactly the pairs that most need linking, and each disagreement pulls the weighted mean down. `error/digit_mutation` shows the same shape, 0.400 → 0.233, because a mutated digit in an identifier now actively argues against a match. Precision rises 0.986 → 0.992, which is the honest other half.

**A comparator that helps on the stable case can hurt on the changing one**, and no benchmark without a `change` column would have shown it.

## 5. The batch arms at 400 suppliers

The same five batch arms on the larger world (1,198 records, 1,485 true pairs), for scale sensitivity. The ledger arms are absent because they would take about two hours here.

```
arm                   P      R     F1  cover     change  represent    error  falseMrg  blockR    secs
exact             0.858  0.415  0.559  0.415      0.261      0.396    0.287     0.025   0.415     0.0
jaro_winkler      0.428  0.910  0.582  0.910      0.924      0.903    0.880     0.089   0.968     0.1
arche/pack        0.883  0.748  0.810  0.978      0.406      0.739    0.682     0.032   0.995   721.0
arche/custom      0.948  0.685  0.795  0.936      0.341      0.673    0.597     0.028   0.997   652.4
```

The ordering is stable across scales; the absolute numbers are not. Jaro-Winkler's precision collapses from 0.772 to 0.428 as the world grows, which is what a name-only matcher does when there are more names to collide with — the clearest single argument in the set for frequency-aware comparison.

## Caveats that belong with any use of these numbers

- **One seed, one world, 150 (or 400) suppliers.** No confidence intervals. The gap between 0.111 and 0.267 is meaningful; the gap between 0.111 and 0.178 is suggestive; anything closer is not.
- **`ORG_RENAMED` is easier here than it should be.** The rename event mostly swaps the legal form (`X Limited` → `X Group Limited`), and every arm normalises legal forms away, so the distinctive head survives. A real rebrand changes the head. Until that generator fix lands, the rename numbers flatter every arm.
- **`DIRECTOR_CHANGED` has n=6** at this scale. Reported, not scoreable. `diacritic_loss` did not populate at all.
- **arche's runtime is the binding constraint.** ~160 pairs/second, measured as *not* the frequency table (75 s vs 81 s with `tf` off on a fixed subset). It is what caps the benchmark's scale and it is why the seven-arm table is at 150.
- **The world's company names are `<Surname> <Trade> <Form>` over 18 trades and 10 forms**, which makes token blocking collapse harder than it would on a real register. Read the blocking numbers as a property of this world.
