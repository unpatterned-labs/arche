# Stratified results — `ng_supplier_v0`, seven arms

**Measured 2026-09-08** by `run_benchmark.py`, on the world files currently in `worlds/`. Every number was produced on the machine that printed it.

```bash
python data/synthetic/build_ng_supplier_v0.py --scale 150 --out data/synthetic/worlds/ng_supplier_v0_s150
python data/synthetic/run_benchmark.py --world data/synthetic/worlds/ng_supplier_v0_s150
```

## 0. Read this first: how much a single number here can carry

A previous version of this file quoted numbers measured on worlds that were then regenerated after a name-pool fix. Re-measuring, I predicted the figures would "move only slightly." **That was wrong**, and finding out how wrong is the most useful thing in this document.

Five seeds at 150 suppliers, the three fast arms (the arche arms are too slow to sweep):

```
arm           metric          min     max  spread   stdev
exact         recall        0.367   0.466   0.099   0.044
exact         change        0.167   0.272   0.105   0.046
exact         reloc         0.018   0.079   0.061   0.024
jaro_winkler  recall        0.861   0.934   0.074   0.028
jaro_winkler  precision     0.669   0.887   0.218   0.091
jaro_winkler  change        0.837   0.965   0.128   0.050
jaro_winkler  reloc         0.818   0.980   0.162   0.066
splink        recall        0.706   0.783   0.077   0.033
splink        precision     0.925   0.988   0.063   0.024
splink        reloc         0.163   0.309   0.146   0.066
```

The worlds themselves vary: 439–473 records, 521–625 true pairs, **38–55 relocated pairs** for the same nominal 150 suppliers.

**The rule this sets.** For an *unpaired* comparison between two arms at this scale, a difference below **~0.10 on overall recall** or **~0.15 on relocation recall** cannot be distinguished from which world you happened to draw. Several comparisons in earlier drafts of this file sat inside that band and have been withdrawn below.

**Paired comparisons are a different matter** and are much more sensitive: two arms run on the *same* world see identical records, so world-to-world variation largely cancels. Section 3 is a paired result and is treated accordingly.

This is a property of the benchmark at 150 suppliers, not of the engines. The fix is more suppliers or more seeds, and both cost arche-runtime — which is the binding constraint recorded in the caveats.

## 1. The table — 150 suppliers, 444 records, 545 true pairs, seed 42

```
arm                        P      R     F1  cover     change  represent    error  falseMrg  blockR    secs
exact                  1.000  0.466  0.636  0.466      0.261      0.440    0.329     0.000   0.466     0.0
jaro_winkler           0.882  0.861  0.871  0.861      0.837      0.854    0.805     0.042   0.947     0.0
splink                 0.988  0.783  0.874  0.783      0.533      0.792    0.761     0.024   0.974     7.5
arche/pack             0.995  0.745  0.852  0.969      0.391      0.725    0.663     0.005   0.980   343.4
arche/custom           1.000  0.694  0.819  0.921      0.370      0.669    0.591     0.000   0.985   260.4
arche/ledger           1.000  0.778  0.875  0.778      0.522      0.773    0.717     0.000     n/a   547.1
arche/ledger+observe   0.944  0.796  0.864  0.796      0.576      0.792    0.738     0.000     n/a   436.7
```

`cover` counts pairs an engine *surfaced for review* as well as merged — without it an engine with three answers is scored as though it had two. The stratum columns are **recall only**: a false merge joins two different entities, has no difference row, and belongs to no stratum. `blockR` is `n/a` for the ledger arms because they do not enumerate a candidate set, and filling it in with their own recall would be a lie in the flattering direction.

## 2. Relocation defeats every engine that reads the address

Recall on the 55 relocated pairs — the stratum this dataset exists to expose:

```
exact                 0.018        arche/pack            0.145
arche/custom          0.164        splink                0.309
arche/ledger          0.309        arche/ledger+observe  0.400
jaro_winkler          0.818  ← reads names only
```

**This is the finding, and it is the one comfortably outside the noise.** Jaro-Winkler sits at 0.818–0.980 across five seeds; every engine that reads the address sits below 0.41. That gap is five times the measured spread. A rule join finds 2% of relocated suppliers; arche finds 15%; Splink — an independent Fellegi-Sunter implementation — finds 31%.

Not "arche is bad at relocation" but **"a changed address is treated as refuting evidence by every engine that reads it, so a supplier moving is indistinguishable from a supplier being a different company."** No published entity-resolution benchmark can show this, because none label *why* two records disagree.

Jaro-Winkler's 0.818 is not competence. It compares names and nothing else, so a changed address cannot hurt it — and the bill arrives in the precision column: 0.882 here, and 0.669 on the worst of five seeds, against Splink's 0.925–0.988. **An arm can top the change stratum by ignoring evidence.**

The middle of that list — arche 0.145 vs Splink 0.309 vs ledger 0.309 — spans less than the 0.146 seed spread measured for Splink alone. **Do not read an ordering into it.**

## 3. The ledger does beat batch — paired across three worlds

`arche/pack` reaches 0.145 on relocation while its `cover` is 0.969: it is not *missing* those pairs, it is **refusing** them. The `organisation` pack compares `address` with a `premises` comparator declared `refutes_below: 0.5`, so a wholly changed address demotes the pair to `review` however well the name and RC number agree.

The single-seed gap could not carry that claim — 0.16 on relocation is inside the unpaired noise band. But both arms run on the *same* records, so the honest test is paired: does the difference keep its sign across worlds? Three worlds, 90 suppliers, `arche/pack` against `arche/ledger`:

```
seed  arm             recall    prec   reloc  change
42    arche/pack       0.739   0.978   0.121   0.346
42    arche/ledger     0.797   0.944   0.151   0.462
        delta         +0.058  -0.034  +0.030  +0.115
43    arche/pack       0.735   0.975   0.053   0.378
43    arche/ledger     0.812   0.895   0.158   0.540
        delta         +0.077  -0.081  +0.105  +0.162
44    arche/pack       0.757   1.000   0.115   0.460
44    arche/ledger     0.800   1.000   0.308   0.580
        delta         +0.043  +0.000  +0.192  +0.120
```

**Overall recall, the `change` stratum and relocation are positive in all three worlds.** The most consistent of them is the whole `change` stratum: **+0.115, +0.162, +0.120** — the ledger recovers twelve to sixteen points of legitimate change that one-shot batch comparison declines. Relocation moves in the same direction every time but with a much wider range (+0.03 to +0.19), so the *direction* is the claim and the magnitude is not.

**What this is and is not.** Three worlds agreeing on sign is p = 0.125 under a sign test — suggestive, not significant, and it should not be described as significant. What lifts it above a coincidence is that there is a mechanism: the pack refuses on a changed address, and the ledger's later-evidence-supersedes-earlier-decision path is precisely the thing that can revisit a refusal. A consistent sign plus a mechanism that predicts that sign is a reasonable claim; either alone would not be.

**Precision is the honest other half, and it flips.** −0.034, −0.081, 0.000: the ledger is never *more* precise than batch and is sometimes less, because it links transitively and a wrong link propagates through an entity in a way a pairwise merge does not. That is a smaller and less consistent cost than the single-seed table implied, and it is a real trade: which end of it is right depends on whether a false merge or a false split costs more in the workflow. The benchmark can now price both.

`arche/ledger+observe` is an **assisted** number wherever it appears, and was not part of this paired test. The lookup key is the RC number, an identifier the records carry, never the truth mapping — but two records sharing an RC number are already strong evidence, so it measures whether `observe()` propagates and re-decides correctly, not whether arche finds the link unaided.

## 4. Splink and arche are close — how close is not measurable here

```
splink       P 0.988   R 0.783   F1 0.874     7.5 s
arche/pack   P 0.995   R 0.745   F1 0.852   343.4 s
```

Two independently written engines, one of them not ours, landing within 0.04 recall and 0.007 precision. **The gap is inside the noise band, so the correct statement is that they are indistinguishable at this scale — not that either leads.** An earlier draft of this file claimed they agreed "to three decimal places," which was one draw dressed up as a measurement.

What the row does support is the thing that matters: an engine we did not write, on our data, lands in the same region as ours. That is evidence the benchmark measures the problem rather than a quirk of our implementation, and it **completes the trigger for cutting the separate repository**. Splink is also ~46× faster.

Getting this arm to be fair took two corrections, both recorded because both would have flattered arche:

- **The first version scored 0.000 on relocations.** Not a Splink limitation — `block_on` is case-sensitive, 57% of this world's representation differences are a source that stores records IN CAPITALS, and every blocking key broke on case alone. Blocking recall was 0.404. Normalising before loading, which every Splink user does, took it to 0.974.
- **The threshold was borrowed and wrong.** 0.99, taken from the existing Febrl benchmark, cost about 0.5 recall: at 0.99 Splink scores R 0.207/P 1.000; at its own 0.5 decision boundary R 0.731/P 0.940. Imposing an arche-flavoured caution on an engine that has no third answer is the same error as scoring arche on a probability cut, which this project already knows not to make.

A badly configured competitor is worse than no competitor.

## 5. Reading more fields made matching worse

`arche/custom` maps in the four fields the shipped pack ignores — phone, TIN, account number, director. Recall falls 0.745 → 0.694, and `ACCOUNT_CHANGED` recall falls 0.889 → 0.333.

The reason is structural. Those fields are disproportionately the ones that *legitimately change* or are *absent*, so they disagree on exactly the pairs that most need linking, and each disagreement pulls the weighted mean down. `error/digit_mutation` shows the same shape, 0.407 → 0.185, because a mutated digit in an identifier now actively argues against a match. Precision rises to 1.000, which is the honest other half.

**A comparator that helps on the stable case can hurt on the changing one**, and no benchmark without a `change` column would have shown it. The overall recall gap (0.051) is inside the noise band; the `ACCOUNT_CHANGED` and `digit_mutation` drops are large and mechanistically explained, which is why they are reported and the headline recall difference is not.

## Caveats that belong with any use of these numbers

- **Read section 0 before quoting anything.** At 150 suppliers, unpaired differences below ~0.10 recall are not measurable.
- **The names have no correlation.** Given name and surname are drawn independently, so this world contains `Zübeyde Saliou` and `Fabiano Anaehobi`. That corrupts the `common_names` stratum specifically — real collisions are structured by region and these are random. See `DATACARD.md` and plan §7b (N1).
- **`ORG_RENAMED` is easier here than it should be.** The rename mostly swaps the legal form, which every arm normalises away. Until N2 lands, the rename numbers flatter every arm.
- **`DIRECTOR_CHANGED` has n=7** at this scale, `ACCOUNT_CHANGED` n=9. Reported, not scoreable. `diacritic_loss` did not populate at all.
- **arche's runtime is the binding constraint.** ~160 pairs/second, measured as *not* the frequency table (75 s vs 81 s with `tf` off on a fixed subset). It caps the scale, which is what makes the noise band as wide as it is.
- **Company names are `<Surname> <Trade> <Form>` over 18 trades and 10 forms**, which makes token blocking collapse harder than on a real register.
