# Benchmarks

Every number here is produced by a script in this repository, against data you
can fetch yourself. Where a published result exists, we reproduce it first and
show the reproduction, because a comparison you cannot check is not a
comparison.

Results that make arche look bad are on this page too. That is the point of
keeping it.

## How to read this

There are three kinds of entry, and they support different claims.

**Against another package.** Someone else published a method and a number on a
public dataset. We reproduce their number exactly, then run arche on the same
records against the same truth. This is the only kind that supports a sentence
of the form "arche did better than X".

**Against string baselines.** Exact match, token Jaccard, `token_set_ratio`.
These are not competing libraries, they are the thing most people actually do.
Useful for showing when a matcher is worth having and when it is not.

**Internal ablation.** One part of arche switched off, everything else held
still. Says nothing about other tools.

## Against another package

### R `RecordLinkage`, Parrish tutorial

Jared Parrish's [record linkage
tutorial](https://rstudio-pubs-static.s3.amazonaws.com/1203076_6c678b417f564183a8708e3b4720c6c0.html)
links two files of child records, 1,183 and 302 rows. Both files carry the
identifiers needed to score: 294 of the 302 sampled records have a true match,
and 8 have none.

Reproduction first. The tutorial's deterministic step reports 205 linked, 97
not, 67.9%, on a register deduplicated from 1,183 to 986:

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

Given a date of birth, arche finds 60 more true pairs than the exact key. They
are dropped middle names and keying errors: `SARI` for `SORRY`, `HANA` for
`HANNA`, `LEE` for `LEELEA`.

**Read the second row.** Until 0.4.0a4 the shipped pack was *less precise than
the R tutorial*, because it declared no date comparator and never looked at the
birthday it was handed. All 14 of its false positives were two different
children with the same name. That benchmark is what put a date in the pack, and
the row is kept here because a page that quietly drops its own bad results is
not worth reading.

The fourth row adds `refutes_below`, which the shipped pack deliberately does
not declare. See [refutation is not on by
default](#refutation-is-not-on-by-default).

One trap for anyone reproducing this: the tutorial's prose names five
comparison fields, but its own uniqueness table uses four, without middle name.
The five-field key gives 174, not 205.

Notebook: `examples/notebooks/15_parrish_record_linkage.ipynb`.

### Python `recordlinkage`, Febrl 4

Febrl 4 is synthetic, 5,000 by 5,000, with complete truth, distributed with the
[`recordlinkage`](https://github.com/J535D165/recordlinkage) package. arche
claimed precision 1.0000 with 87.7% auto-resolved from v0.1 onwards. The
benchmark reproduces that claim exactly, and shows what it depends on:

| configuration | true merges | false merges | precision | auto-resolved |
| --- | ---: | ---: | ---: | ---: |
| name + address + `soc_sec_id` | 4,384 | 0 | 1.0000 | 87.7% |
| name + address | 3,285 | **282** | 0.9209 | 65.7% |

The published claim holds only with the social security number in the record.
Without it, precision falls to 0.9209. Both configurations are legitimate; only
one of them was ever quoted, and that was a fault in how we described it.

Script: `datasets/names_dataops/bench_febrl.py`.

## Against string baselines

Two school registers, same process both times, opposite conclusions.

**England, Leeds, 282 labelled pairs.** School names are standardised enough
that plain exact matching is level with arche on F1 (0.930 against 0.931).
Where names are administered, a string comparison is close to sufficient, and a
matcher earns very little.

**Nigeria, 400 same-name pairs in different states.** The same baselines
collapse. These are certain negatives: two schools in different states are not
the same school, subject to a boundary allowance.

| method | false merges | rate |
| --- | ---: | ---: |
| exact name, casefolded | 400 | 100.0% |
| token Jaccard >= 0.5 | 400 | 100.0% |
| `token_set_ratio` >= 90 | 399 | 99.8% |
| arche, name + coordinates | 2 | 0.5% |

`COMMUNITY PRIMARY SCHOOL` occurs 200 times across 21 states. Exact matching
goes from the safest method available in Leeds to the most dangerous one here.

Notebooks: `13_england_schools.ipynb`, `14_nigeria_schools.ipynb`.

## Internal ablation

**Name frequency, NCVR Alamance County.** Three arms of the person pack's
`tftoken` comparator on 1,114 observed negatives and 1,500 constructed
positives:

| arm | false merges | precision | recall | F1 |
| --- | ---: | ---: | ---: | ---: |
| frequency-blind | 7,705 | 0.162 | 0.990 | 0.278 |
| shipped default, self-calibrated | 41 | 0.946 | 0.480 | 0.637 |
| shipped population table | 24 | 0.963 | 0.412 | 0.577 |

The frequency signal is doing real work. It also costs half the recall, and the
benchmark fails its own precision criterion. Published failing.

Script: `datasets/names_dataops/bench_name_frequency.py`.

## Notes on the person pack

### Refutation is not on by default

A date is the clearest case of a signal that refutes better than it confirms:
two people with the same name and different birthdays are two people, however
alike the names. `refutes_below` exists for exactly that shape, and on the
Parrish set it takes precision from 0.9962 to 1.0000.

The shipped pack still does not declare it. `test_discriminator_veto.py` guards
`place`, `person` and `artist` against acquiring refutation as a side effect of
an unrelated change, on the grounds that each has published numbers a
refutation would move. Adding a comparator was that unrelated change. Turning
refutation on is a separate decision with its own measurement, and it is one
line for a caller who wants it:

```python
crosswalk(a, b, entity="person", comparators=[
    {"field": "name", "kind": "name", "weight": 2.0},
    {"field": "name", "kind": "tftoken", "weight": 2.0},
    {"field": "birth_date", "kind": "date", "weight": 2.0,
     "refutes_below": 0.5},
])
```

It also cost recall on the only set we have (0.8810 against 0.9014), which is
not an argument either way at one data point.

### What the date comparator will not do

Reading is anchored on a four-digit year, so a date without one is unreadable
by design. `03/04/05` has six meanings and the comparator declines rather than
guessing:

| input | result |
| --- | --- |
| `6/28/2016` vs `2016-06-28` | 1.0, same day |
| `6/7/2016` vs `7/6/2016` | 1.0, both ambiguous and could agree |
| `2017-01-01` vs `2016-12-31` | 0.35, one keying slip |
| `03/04/05` vs anything | abstains, no four-digit year |
| missing or unreadable | abstains, never refutes |

Ambiguous dates resolving to agreement is a deliberate asymmetry. It withholds
refutation where the data does not say what it means, which is the same rule
`boundary_doubt` applies at administrative edges. It will merge two records that
a locale-aware reader would separate.

Near-miss grading is a fixed 0.35 for "within a day, or one component out". It
is not a model of how people mistype dates, and the value was chosen to sit
below agreement and above the candidate threshold, not fitted to anything.

It also costs something, visible in the single false merge that survives above.
`JORGE TORRES 2016-02-23` matched a different `JORGE TORRES 2016-10-23`: one
component out, graded 0.35, so the pair stayed above the threshold rather than
vanishing as it would have under a flat 0.0. Some near misses are near misses
between two different people. That is the trade, not a defect.

## Running these

```sh
python examples/notebooks/build_15.py     # Parrish, R RecordLinkage
python datasets/names_dataops/bench_febrl.py
python datasets/names_dataops/bench_name_frequency.py
python data/scripts/nigeria_school_false_merges.py
```

Each writes a JSON result next to itself, holding the numbers above and a
statement of what the run does not measure.

## What none of this measures

Febrl and the Parrish files are synthetic. Their errors were generated, so they
are tidier than the errors a real register makes, and a benchmark that only
looks clean on synthetic data has told you very little.

The Nigeria and NCVR negatives are certain, but the positives are constructed,
so recall on those two is a statement about the constructions.

No benchmark here measures a population arche has not been shown. Nothing on
this page is evidence about your data.
