# Benchmarks

Every number here is produced by a script in this repository, against data you can fetch yourself. Where a published result exists, we reproduce it first and show the reproduction, because a comparison you cannot check is not a comparison.

Results that make arche look bad are on this page too. That is the point of keeping it.

## How to read this

There are three kinds of entry, and they support different claims.

**Against another package.** Someone else published a method and a number on a public dataset. We reproduce their number exactly, then run arche on the same records against the same truth. This is the only kind that supports a sentence of the form "arche did better than X".

**Against string baselines.** Exact match, token Jaccard, `token_set_ratio`. These are not competing libraries, they are the thing most people actually do. Useful for showing when a matcher is worth having and when it is not.

**Internal ablation.** One part of arche switched off, everything else held still. Says nothing about other tools.

## Against another package

### R `RecordLinkage`, Parrish tutorial

Jared Parrish's [record linkage tutorial](https://rstudio-pubs-static.s3.amazonaws.com/1203076_6c678b417f564183a8708e3b4720c6c0.html) links two files of child records, 1,183 and 302 rows. Both files carry the identifiers needed to score: 294 of the 302 sampled records have a true match, and 8 have none.

Reproduction first. The tutorial's deterministic step reports 205 linked, 97 not, 67.9%, on a register deduplicated from 1,183 to 986:

| step | tutorial | reproduced |
| --- | --- | --- |
| register after dedup | 986 | 986 |
| duplicates removed | 197 | 197 |
| linked | 205 | 205 |
| linkage rate | 67.9% | 67.9% |

Scored against the truth the tutorial sets aside:

| method | linked | TP | FP | precision | recall | F1 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Parrish deterministic | 205 | 205 | 0 | 1.0000 | 0.6973 | 0.8216 |
| arche, person pack *before* 0.4.0a4 | 233 | 219 | **14** | 0.9399 | 0.7449 | 0.8311 |
| arche, shipped person pack | 266 | 265 | 1 | 0.9962 | 0.9014 | 0.9464 |
| arche, plus date refutation | 259 | 259 | 0 | 1.0000 | 0.8810 | 0.9367 |

Given a date of birth, arche finds 60 more true pairs than the exact key. They are dropped middle names and keying errors: `SARI` for `SORRY`, `HANA` for `HANNA`, `LEE` for `LEELEA`.

**Read the second row.** Until 0.4.0a4 the shipped pack was *less precise than the R tutorial*, because it declared no date comparator and never looked at the birthday it was handed. All 14 of its false positives were two different children with the same name. That benchmark is what put a date in the pack, and the row is kept here because a page that quietly drops its own bad results is not worth reading.

The fourth row adds `refutes_below`, which the shipped pack deliberately does not declare. See [refutation is not on by default](#refutation-is-not-on-by-default).

One trap for anyone reproducing this: the tutorial's prose names five comparison fields, but its own uniqueness table uses four, without middle name. The five-field key gives 174, not 205.

Notebook: `examples/notebooks/15_parrish_record_linkage.ipynb`.

### Splink, on Febrl 4

[Splink](https://moj-analytical-services.github.io/splink/) is the closest thing to a standard in probabilistic record linkage, and it does inference better than arche does: Fellegi-Sunter with EM-trained m and u parameters, term frequency adjustments, the full apparatus. arche's claim is not that it estimates better, it is that most of the available gain sits in what the records look like before any estimator sees them. Handing a better estimator the same records is the way to test that.

Reproduction first. Splink's published Febrl 4 example reports **4,959 clusters of size 2** at a 0.99 match probability, and no accuracy figures. Running its recipe here gives **4,952**, 0.14% apart. The precision and recall below are computed here, identically for both engines, against the same complete truth.

Both engines are run twice, because Splink's example blocks on and compares `soc_sec_id`, a near-unique synthetic identifier. A linkage that has one is a much easier problem than one that does not.

| engine | true | false | precision | recall | F1 |
| --- | ---: | ---: | ---: | ---: | ---: |
| Splink, with `soc_sec_id` | 4,952 | 0 | 1.0000 | 0.9904 | 0.9952 |
| arche, with `soc_sec_id` | 4,473 | 0 | 1.0000 | 0.8946 | 0.9444 |
| Splink, without | 4,768 | 0 | 1.0000 | 0.9536 | 0.9762 |
| arche, without | 4,190 | 24 | 0.9943 | 0.8380 | 0.9095 |

**Splink wins both arms, and it is not close.** Same precision or better, and roughly ten points more recall. On the harder arm arche also makes 24 false merges where Splink makes none.

The Splink rows wobble slightly between runs. That recipe calls `estimate_u_using_random_sampling` without a seed, so the "without" arm has been measured at 0.9528, 0.9534 and 0.9536 on different days. Read it as "about 0.953", not as a fixed constant, and do not quote a single draw as a reference value the way an earlier version of this page did.

One thing is worth adding, not as mitigation but because the two engines are answering slightly different questions. arche's `match` is an auto-merge and everything ambiguous goes to `review` for a human. Counting what it surfaces rather than what it merges outright:

| | auto-merged | surfaced (match + review) |
| --- | ---: | ---: |
| arche, with `soc_sec_id` | 0.8946 | 0.9692 |
| arche, without | 0.8380 | 0.9724 |

So most of the recall gap is pairs arche declined to decide rather than pairs it missed. That is the behaviour the distinctive-signal gate is for, and on this dataset it is costing more than it saves: Splink reaches 0.9904 with perfect precision and no queue at all.

**What this does not show.** Febrl is synthetic, its errors came from a generator with a model of how people mistype, and Splink was run close to its published example rather than tuned by someone who knows it well. A tuned Splink would likely do better still. This is not a claim that one tool beats another in general; it is the same task run both ways with the code to check it.

Script: `datasets/names_dataops/bench_splink_febrl.py`.

### Splink, on Nigerian school names

The two runs below are on data where a name is a reasonably distinctive thing. This is the one where it is not, and it was chosen because it is the case arche is designed for: `COMMUNITY PRIMARY SCHOOL` occurs 200 times across 21 states. If the representation argument holds anywhere against a strong baseline, it holds here.

13,200 records. Negatives are **observed**: 400 pairs sharing a name exactly across a state line, and two schools in different states are not one school. Positives are **constructed**: one record recorded twice with an ordinary recording difference and a jittered coordinate, so the true-merge column is a statement about that construction. Both engines face the same construction, and both are given name and coordinates.

| engine | true merges of 200 | false merges of 400 |
| --- | ---: | ---: |
| Splink, p ≥ 0.99 | 0 | 0 |
| Splink, p ≥ 0.95 | 1 | 0 |
| **Splink, p ≥ 0.9** | **190** | **0** |
| Splink, p ≥ 0.5 | 190 | 12 |
| **arche, match** | **146** | **2** |
| arche, match + review | 199 | 393 (queued, not merged) |

The two denominators differ and an earlier version of this page printed both as
400. There are 400 observed negatives and 200 constructed positives: 800 negative records plus 400 positive records plus 12,000 filler is the 13,200 above.

**Splink wins on both axes.** At its best operating point it finds 190 true merges and makes none of the 400 false ones. arche finds 146 and makes 2.

This is the result that matters most on this page, because this dataset was picked to favour arche and did not. The prediction behind the representation argument, that a name-frequency-weighted score would over-merge here where a distinctive-signal gate would not, is **not** what happened: Splink's term frequency adjustments handled the collisions, and it kept more recall doing it.

Two things about arche's last row. `review` is a queue, not a merge, so 393 is not a false-merge count; it is the gate surfacing nearly every same-name pair for a human. That is the designed behaviour and it is also an operational cost nobody should discover later.

**Caveats.** Splink reported one comparison level it could not train ("Distance less than 2km ... not observed"), which if anything understates it. Its probabilities cliff sharply between 0.95 and 0.9, so the operating point matters more here than on the other two datasets. And the positives are constructed, so read the true-merge column as a control that both engines can still find things, not as recall.

Script: `datasets/names_dataops/bench_splink_nigeria.py`.

### A shipped population table against batch-estimated frequency

The Nigerian register above shows Splink ahead: 190 true of 200 at 0 false of 400, against arche's 146 and 2. That comparison is fair and it is not the whole claim.

arche's frequency tables rest on a specific assertion — that estimating `u` from the batch fails when the batch is small, because a handful of records cannot know which words are ordinary. **A 13,200-record register cannot test that.** Splink's term-frequency adjustment has an excellent sample of Nigerian school names there and uses it well.

So this run holds the labels fixed — the same 400 observed negatives and 200 constructed positives, imported from `bench_splink_nigeria.py` so they cannot drift — and varies only the **filler**, which is the population Splink learns frequencies from. arche reads the same shipped 1.25M-record place table at every size.

| filler | records | `splink@0.5` true | false | arche match true | false |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 0 | 1,200 | 190 | **368** | 146 | **2** |
| 500 | 1,700 | 190 | 2 | 146 | 2 |
| 2,000 | 3,200 | 190 | 2 | 146 | 2 |
| 12,000 | 13,200 | 190 | 12 | 146 | 2 |

**With nothing to learn from, Splink merges 368 of 400 known negatives.** Every name in the labelled block appears exactly twice, so nothing in the batch says `COMMUNITY PRIMARY SCHOOL` is common — and two schools of that name in different states duly merge. Add 500 filler records and it collapses to 2.

arche is **2 at every size**, because the table it reads does not change.

Reproduced three times at filler 0 and three at filler 2,000: 368/368/368 and 2/2/2, exactly. The effect is not a sampling artefact.

**What this does and does not establish.**

It does not say arche is more accurate. Splink finds 190 true pairs at every size against arche's 146, and on the full register it does so with zero false merges. On accuracy, Splink wins.

What it establishes is narrower and, for a shipped library, more useful: **arche's false-merge rate does not depend on how much data you happened to bring.** That is what a population table buys, and it is the only property in this comparison that a caller gets without labels.

Because the alternative reading is available and should be stated: at `p >= 0.9` Splink also holds 0-2 false merges at every filler size. A higher threshold compensates for a thinner batch. But **choosing that threshold requires labels**, and a caller with 400 records to reconcile and no ground truth has no way to know that 0.5 is wrong for their data and 0.9 is right. The shipped prior removes that choice rather than winning an argument about it.

Run it with:

```sh
uv run python datasets/names_dataops/bench_population_vs_batch.py
```

**One caveat on the harness.** It builds four Splink models in one process. At filler 12,000 the `p >= 0.9` arm returned 1 true where the standalone `bench_splink_nigeria.py` reproduces 190 exactly, byte for byte. The `p >= 0.5` arm is stable across repeated runs at every size, so the ranking is reproducible and the absolute probability calibration at that size is not. The figures quoted above are from `p >= 0.5` for that reason, and the discrepancy is unexplained rather than diagnosed.

### Splink, on `historical_50k`

Febrl's records were invented by a generator and then corrupted by it. This is the harder test: 50,578 records describing 5,156 real UK historical figures from Wikidata, with errors introduced afterwards. The names, places and occupations are real and distributed the way real ones are, which is the part a generator cannot fake and the part arche's thesis is about.

**Not ONS, and why.** ONS runs Splink in production on the 2021 Census, the Business Index and the Demographic Index. None of that data is public and no accuracy figures on it are published, so there is nothing there to reproduce. This is the closest public substitute.

Splink publishes no accuracy number here either; its `deduplicate_50k_synthetic` example shows charts only. So what is reproduced is the recipe, its ten blocking rules and its comparisons, and the figures below are computed here for both engines against the `cluster` column both are blind to. Scored on **pairs**, not clusters, so the transitive closure each tool applies afterwards is not what is being measured. 303,961 true pairs.

| engine | pairs | precision | recall | F1 | time |
| --- | ---: | ---: | ---: | ---: | ---: |
| Splink, its own recipe | 153,561 | 0.9992 | 0.5048 | 0.6707 | 20s |
| arche, shipped `person` pack | 89,035 | 0.9803 | 0.2872 | 0.4442 | 111s |
| arche, same five fields | 68,031 | 0.9977 | 0.2233 | 0.3649 | 109s |

**Splink wins again, by more than on Febrl, and it is five times faster.**

Two arche arms because Splink is given name, date of birth, postcode, birth place and occupation, and the shipped pack has comparators for the first two only. Handing arche the same five columns raises its precision to 0.9977 and *lowers* its recall to 0.2233. The extra fields tighten it rather than help it, which is worth sitting with: more evidence made the engine more conservative, not more accurate.

Counting what arche surfaces rather than what it merges:

| | auto recall | surfaced recall | surfaced precision |
| --- | ---: | ---: | ---: |
| shipped pack | 0.2872 | 0.4418 | 0.8158 |
| same five fields | 0.2233 | 0.3725 | 0.9678 |

Even surfacing everything it is unsure about, arche reaches 0.4418 against Splink's 0.5048 at near-perfect precision and with no queue for anyone to work.

Script: `datasets/names_dataops/bench_splink_historical.py`.

#### The same comparison at matched precision

One operating point each measures two default settings, not two engines. Sweeping both and reading recall off at the same precision:

| precision | Splink recall | arche recall | gap |
| ---: | ---: | ---: | ---: |
| 0.999 | 0.5131 | 0.1472 | −0.3660 |
| 0.990 | 0.6060 | 0.2971 | −0.3089 |
| 0.980 | 0.6265 | 0.3339 | −0.2926 |
| 0.950 | 0.6481 | 0.4257 | −0.2225 |
| 0.900 | 0.6565 | 0.4598 | −0.1967 |

Splink is ahead at every precision, by 20 to 37 points of recall. The sweep does not rescue arche; it makes the size of the gap legible.

**Where the gap comes from matters more than its size.** A matcher can only decide pairs it was shown, so the candidate set bounds everything:

| | candidate pairs | recall ceiling | converted at p=0.99 |
| --- | ---: | ---: | ---: |
| Splink | 241,899 | 0.6593 | 91.9% |
| arche | 246,903 | 0.4878 | 60.9% |

arche generates **more** candidate pairs than Splink and covers **fewer** true ones. Its blocking is not too small, it is aimed badly: the same budget spent on the wrong pairs. 0.4878 is a hard ceiling no threshold can lift, and it sits below Splink's *operating* recall of 0.6060.

The second column is the other half. Splink converts 91.9% of the recall its candidates make available; arche converts 60.9%. So arche is behind on both axes, and roughly half the gap is candidate generation rather than scoring.

That split is worth stating plainly because the two have different meanings. Blocking is machinery, and machinery is fixable. Scoring is where the representation argument lives, and 60.9% against 91.9% is not a small deficit there either.

Script: `datasets/names_dataops/bench_sweep_historical.py`. arche is run with `threshold=0.0, review_margin=0.0` so the curve is limited by blocking rather than by the default decision point. That is not a production setting; it exists to separate "scored badly" from "never seen".

### arche using Splink, rather than against it

The three sections above measure arche's own matcher against Splink and it loses all three. `reconcile(backend="splink")` is the response: hand the scoring to Splink and keep the decision layer arche puts around a score.

The question a benchmark can answer about an adapter is not "is it better" but "is it faithful". Does wrapping the scorer change what the scorer says?

| Febrl 4, no `soc_sec_id` | true | false | precision | recall |
| --- | ---: | ---: | ---: | ---: |
| arche's own engine | 4,191 | 42 | 0.9901 | 0.8382 |
| adapter, `p >= 0.99` | 4,765 | 0 | 1.0000 | 0.9530 |
| the same recipe run directly | 4,767 / 4,764 | 0 | 1.0000 | 0.9534 / 0.9528 |

On the Nigerian register the adapter and the hand-written recipe both reach 190 true of 200 at 0 false of 400, where arche's own engine reaches 146 and 2.

**The adapter costs nothing and gains nothing.** It is the same scorer, inside arche's decision ids, pins, evidence, refusal and review pack. That is the claim, and a fidelity result is the only honest way to state it.

#### Why arche will not configure Splink for you

An earlier version inferred the Splink configuration from an arche comparator pack. Measured across three datasets it was wrong in a different way on each:

| dataset | defect |
| --- | --- |
| Febrl 4 | no `datetime_format`, so the date comparison trained nothing |
| `historical_50k` | blocking rules added without costing them; `occupation` alone puts 639M pairs in one block and the run was killed by the operating system |
| Nigerian schools | coordinates coerced to strings, so DuckDB refused `radians(VARCHAR)` |

Fixing all three left the part that cannot be fixed by inference. A derived configuration **orders pairs about as well as a hand-written one and cannot calibrate them.** Calibration comes from `probability_two_random_records_match`, a prior about how many true matches the corpus holds, and nothing in a list of records states it. The same derived run on Febrl 4:

| threshold | recall | precision |
| --- | ---: | ---: |
| `p >= 0.5` | 0.8952 | 1.0000 |
| `p >= 0.9` | 0.7026 | 1.0000 |
| `p >= 0.99` | 0.5448 | 1.0000 |

Same edges, same order, three different answers, straddling arche's own engine at 0.8382. Without labels you cannot know which one you are on. So `splink_settings=` is required, `splink_settings="derive"` warns, and `threshold=` is required too: at `p >= 0.99` the Nigerian recipe merges nothing while Febrl merges 4,765.

Scripts: `datasets/names_dataops/bench_backend_compare.py`.

### Python `recordlinkage`, Febrl 4

Febrl 4 is synthetic, 5,000 by 5,000, with complete truth, distributed with the [`recordlinkage`](https://github.com/J535D165/recordlinkage) package. arche claimed precision 1.0000 with 87.7% auto-resolved from v0.1 onwards. The benchmark reproduces that claim exactly, and shows what it depends on:

| configuration | true merges | false merges | precision | auto-resolved |
| --- | ---: | ---: | ---: | ---: |
| name + address + `soc_sec_id` | 4,384 | 0 | 1.0000 | 87.7% |
| name + address | 3,285 | **282** | 0.9209 | 65.7% |

The published claim holds only with the social security number in the record. Without it, precision falls to 0.9209. Both configurations are legitimate; only one of them was ever quoted, and that was a fault in how we described it.

Script: `datasets/names_dataops/bench_febrl.py`.

## Entity formation

Every entry above scores *pairs*. The [ledger](../guides/keep-and-replay.md) does something no pairwise score measures: it unions `match` edges into entities, so A~B and B~C put A, B and C together whether or not A and C were ever compared. That is how a resolution system quietly merges two different things, and until this section nothing in the repository counted it.

Two complete-truth sets, run through `reconcile(store=ledger)` with exactly the configuration reported for each above, then every entity's records mapped back to the truth clusters they belong to. An entity whose records come from more than one truth cluster is a **cross-cluster merge** — the entity-level false merge, worse than a pairwise one because it propagates. `held` says whether the entity is a clique (`direct`, every pair itself decided `match`) or depends on a chain (`transitive`).

| | DBLP-ACM, year refutes | Febrl 4, name + address |
| --- | ---: | ---: |
| records / true clusters | 4,910 / 2,224 | 10,000 / 5,000 |
| pairwise: true merges / false merges | 2,215 / 115 | 3,285 / 484 |
| entities built | 2,179 | 3,155 |
| true clusters recovered whole | 2,135 (96.0%) | 2,960 (59.2%) |
| **cross-cluster entities** | **44 (2.0%)** | **195 (6.2%)** |
| records inside them | 187 | 848 |
| of which `transitive` / `direct` | 44 / 0 | 184 / 11 |
| largest cross-cluster entity | 12 records, 8 clusters | 17 records, 10 clusters |

The hypothesis the run was designed to test held on both sets: **cross-cluster merges are a transitive phenomenon.** On DBLP-ACM every one of the 44 is transitive and every direct entity is pure. On Febrl 184 of 195 are transitive; the 11 direct ones are two-record entities, which is to say ordinary pairwise false merges wearing an entity id. So `held == "direct"` is a usable guarantee — such an entity is exactly as trustworthy as its pairwise decisions — and `held == "transitive"` is where review effort belongs.

The compounding is visible in the sizes. DBLP-ACM's 115 pairwise false merges become 44 bad entities holding 187 records; the worst is a 12-record entity built from eight different SIGMOD editorials that share a generic title. Febrl's 484 become 195 entities holding 848 records; the worst chains ten different people through seventeen records. A pairwise precision of 0.95 does not translate into 95% of entities being right when the errors cluster, and on DBLP-ACM they do: recurring generic titles pull many records toward one another.

Two caveats. The Febrl pairwise line here (484 false merges) is not the 282 recorded in `bench_febrl_result.json` on 2026-08-17; true merges are identical; the shipped name lexicon and the equivalence groups are ruled out (the count is 484 with either switched off), and the branch's parent commit reproduces 484 untouched, so the drift is in the matcher somewhere between v0.4.0a3 and the current head and is being run down separately. A benchmark that is not gated in CI is a benchmark that drifts. And whole-cluster recovery (59% on Febrl) is bounded by pairwise recall (65.7% auto-resolved): a cluster is whole only if its one true pair matched, so this column restates recall at the entity level rather than adding to it.

Script: `data/scripts/benchmark_entity_formation.py`, result in `data/er_bench/benchmark_entity_formation_result.json`. Run with a results file already present and it adds to it rather than replacing it.

## Against string baselines

Two school registers, same process both times, opposite conclusions.

**England, Leeds, 282 labelled pairs.** School names are standardised enough that plain exact matching is level with arche on F1 (0.930 against 0.931). Where names are administered, a string comparison is close to sufficient, and a matcher earns very little.

**Nigeria, 400 same-name pairs in different states.** The same baselines collapse. These are certain negatives: two schools in different states are not the same school, subject to a boundary allowance.

| method | false merges | rate |
| --- | ---: | ---: |
| exact name, casefolded | 400 | 100.0% |
| token Jaccard >= 0.5 | 400 | 100.0% |
| `token_set_ratio` >= 90 | 399 | 99.8% |
| arche, name + coordinates | 2 | 0.5% |

`COMMUNITY PRIMARY SCHOOL` occurs 200 times across 21 states. Exact matching goes from the safest method available in Leeds to the most dangerous one here.

Notebooks: `13_england_schools.ipynb`, `14_nigeria_schools.ipynb`.

## Internal ablation

**Name frequency, NCVR Alamance County.** Three arms of the person pack's `tftoken` comparator on 1,114 observed negatives and 1,500 constructed positives:

| arm | false merges | precision | recall | F1 |
| --- | ---: | ---: | ---: | ---: |
| frequency-blind | 7,705 | 0.162 | 0.990 | 0.278 |
| shipped default, self-calibrated | 41 | 0.946 | 0.480 | 0.637 |
| shipped population table | 24 | 0.963 | 0.412 | 0.577 |

The frequency signal is doing real work. It also costs half the recall, and the benchmark fails its own precision criterion. Published failing.

Script: `datasets/names_dataops/bench_name_frequency.py`.

## The boundary discount does nothing at its default, on this data

`compare_containment` discounts a state-level disagreement by distance, so two records either side of a line are not refuted on the strength of a boundary file's positional error. The ramp behaves as specified, checked directly:

| separation | score |
| ---: | ---: |
| 0.00 km | 0.2000 |
| 0.50 km | 0.1000 |
| 0.99 km | 0.0020 |
| 1.00 km | 0.0000 |
| 5.00 km | 0.0000 |

The part worth publishing is what happens when it meets real records. On a 400-pair sample of same-name schools in different Nigerian states, **no pair falls inside the 1.0 km band**, so at the shipped default the discount changes no decision at all. Widening the band to 5 km lets one pair in, and that pair becomes a false merge.

So the feature is currently inert rather than beneficial. That is not an argument for widening the band: the one pair a wider band admits is one the labels say is wrong. It is an argument that the case the discount was built for, a genuine sub-kilometre cross-boundary pair, is rare enough that this dataset does not contain a clean example, and the comparator remains unproven on real data in the direction it was meant to help.

The counts above come from an ad-hoc sample rather than the committed benchmark, which groups names slightly differently and does contain one sub-kilometre pair. Treat the direction as the finding, not the exact number.

## Notes on the person pack

### Refutation is not on by default

A date is the clearest case of a signal that refutes better than it confirms: two people with the same name and different birthdays are two people, however alike the names. `refutes_below` exists for exactly that shape, and on the Parrish set it takes precision from 0.9962 to 1.0000.

The shipped pack still does not declare it. `test_discriminator_veto.py` guards `place`, `person` and `artist` against acquiring refutation as a side effect of an unrelated change, on the grounds that each has published numbers a refutation would move. Adding a comparator was that unrelated change. Turning refutation on is a separate decision with its own measurement, and it is one line for a caller who wants it:

```python
from arche.resolve import reconcile

REFUTING = [
    {"field": "name", "kind": "name", "weight": 2.0},
    {"field": "name", "kind": "tftoken", "weight": 2.0},
    {"field": "birth_date", "kind": "date", "weight": 2.0,
     "refutes_below": 0.5},
]

# Same name, different birthday: two people, however alike the names.
res = reconcile(
    [{"id": "1", "name": "Angel Gonzalez", "birth_date": "2018-08-16"}],
    [{"id": "2", "name": "Angel Gonzalez", "birth_date": "2017-08-30"}],
    entity="person", id_field="id", comparators=REFUTING,
)
assert [e["decision"] for e in res["matches"]] != ["match"]
```

It also cost recall on that set (0.8810 against 0.9014), which is not an argument either way at one data point.

**A second opinion, on NCVR.** The North Carolina voter register was the obvious second dataset, and the result is that refutation does nothing there:

| arm | merged | true | false | precision | recall | refuted |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| name only | 741 | 705 | 36 | 0.9514 | 0.4700 | 0 |
| + year, weighted | 1502 | 1458 | 44 | 0.9707 | 0.9720 | 0 |
| + year, refuting | 1502 | 1458 | 44 | 0.9707 | 0.9720 | **0** |

The two date arms are identical to the digit, at every assumed error rate. The last column says why: **not one pair was ever refuted.** A weight of 2.0 already drops a year-disagreeing pair below the candidate threshold, so refutation never gets a pair to act on, and declaring it is a no-op.

Contrast Parrish, where 46 pairs were refuted, **14 of them scoring 0.35**. That is the near-miss band, and it is where refutation earns its keep: a pair whose names match exactly and whose dates are one keying slip apart stays alive on the strength of the names, and only refutation demotes it. A bare year has no such band. It scores 1.0 or 0.0 and nothing in between, so the case refutation is best at cannot arise.

Two cautions about reading NCVR here at all. Its negatives had to be rebuilt: `bench_name_frequency.py` selects them for *disagreeing on birth year*, so measuring a date comparator against them would have been circular, and this script drops that condition. And NCVR carries no date of birth, only a year, so it tests refutation on a field roughly a hundred times less selective than the one the pack declares.

**The third opinion, on Febrl 4, settles it.** Febrl is the dataset NCVR could not be: full dates, corruption introduced by the generator rather than assumed by the script, and complete truth. Of its 5,000 true pairs the comparator scores 4,469 at 1.0, **52 at 0.35**, and 479 at 0.0. The 0.35 row is the near-miss band refutation exists to act on, and here it is populated.

| arm | true | false | precision | auto-resolved | refuted |
| --- | ---: | ---: | ---: | ---: | ---: |
| name + address | 3,285 | 282 | 0.9209 | 0.6570 | 0 |
| + date, weighted | 4,190 | 24 | 0.9943 | 0.8380 | 0 |
| + date, refuting | 4,066 | 24 | 0.9941 | 0.8132 | **307** |

Refutation fires 307 times here, so this is a real test rather than a no-op. It costs **124 true merges and prevents not one false merge**: the false count is 24 either way and precision is unchanged to three decimals. The weight has already excluded everything refutation would have caught, and all refutation adds is demoting correct matches to a queue.

Note also what the date comparator itself is worth on this arm: **282 false merges down to 24**, precision 0.9209 to 0.9943. Adding it to the pack was the right call. Adding refutation on top of it is not.

**Conclusion: no change.** The shipped pack declares a date comparator and no refutation. Three datasets: a small precision gain on Parrish, nothing at all on NCVR, and a clear loss on Febrl. Scripts: `bench_date_refutation.py` (NCVR) and `bench_febrl_dates.py` (Febrl).

### What the date comparator will not do

Reading is anchored on a four-digit year, so a date without one is unreadable by design. `03/04/05` has six meanings and the comparator declines rather than guessing:

| input | result |
| --- | --- |
| `6/28/2016` vs `2016-06-28` | 1.0, same day |
| `6/7/2016` vs `7/6/2016` | 1.0, both ambiguous and could agree |
| `2017-01-01` vs `2016-12-31` | 0.35, one keying slip |
| `03/04/05` vs anything | abstains, no four-digit year |
| missing or unreadable | abstains, never refutes |

Ambiguous dates resolving to agreement is a deliberate asymmetry. It withholds refutation where the data does not say what it means, which is the same rule `boundary_doubt` applies at administrative edges. It will merge two records that a locale-aware reader would separate.

Near-miss grading is a fixed 0.35 for "within a day, or one component out". It is not a model of how people mistype dates, and the value was chosen to sit below agreement and above the candidate threshold, not fitted to anything.

It also costs something, visible in the single false merge that survives above. `JORGE TORRES 2016-02-23` matched a different `JORGE TORRES 2016-10-23`: one component out, graded 0.35, so the pair stayed above the threshold rather than vanishing as it would have under a flat 0.0. Some near misses are near misses between two different people. That is the trade, not a defect.

## Running these

```sh
python examples/notebooks/build_15.py     # Parrish, R RecordLinkage
python datasets/names_dataops/bench_febrl.py
python datasets/names_dataops/bench_name_frequency.py
python data/scripts/nigeria_school_false_merges.py
```

Each writes a JSON result next to itself, holding the numbers above and a statement of what the run does not measure.

## What none of this measures

Febrl and the Parrish files are synthetic. Their errors were generated, so they are tidier than the errors a real register makes, and a benchmark that only looks clean on synthetic data has told you very little.

The Nigeria and NCVR negatives are certain, but the positives are constructed, so recall on those two is a statement about the constructions.

No benchmark here measures a population arche has not been shown. Nothing on this page is evidence about your data.
