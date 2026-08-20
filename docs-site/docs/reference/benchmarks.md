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
| arche, shipped person pack | 233 | 219 | **14** | 0.9399 | 0.7449 | 0.8311 |
| arche, name + date of birth | 274 | 274 | 0 | 1.0000 | 0.9320 | 0.9648 |
| arche, name + DOB, review included | 288 | 286 | 2 | 0.9931 | 0.9728 | 0.9828 |

Given a date of birth, arche finds 69 more true pairs than the exact key and
makes no false matches doing it. The 69 are dropped middle names and keying
errors: `SARI` for `SORRY`, `HANA` for `HANNA`, `LEE` for `LEELEA`.

**Read the middle row before the third one.** Out of the box, arche was less
precise than the R tutorial. The shipped person pack has no date comparator, so
it never looked at the birthday it was given, and all 14 of its false positives
are two different children with the same name. See
[the gap in the person pack](#the-person-pack-has-no-date-comparator) below.

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

## Known gaps

### The person pack has no date comparator

`ENTITY_PACKS["person"]` declares name, a token-frequency view of the name,
`national_id`, `phone`, `email` and `address`. It does not declare a date of
birth, which is close to the most common identifier in person linkage.

On the Parrish files, which carry no id, phone, email or address, this makes
the pack a name-only matcher. It produced 14 false positives, every one of them
a different child with the same name and a different birthday, and every one
refutable by comparing the two dates.

A `date` comparator kind is registered and reachable through `comparators=`,
which is how the notebook gets the third row of the table above. It is not in
the pack. Before it goes in, `compare_dates` needs three things it does not
currently have:

| input | returns | problem |
| --- | ---: | --- |
| `6/28/2016` vs `2016-06-28` | 0.0 | same day, different format |
| missing vs `2016-06-28` | 0.0 | absence scores as disagreement |
| `2016-06-28` vs `2016-06-29` | 0.0 | one day apart scores like a year apart |

The second is the dangerous one. Paired with `refutes_below`, a missing date
becomes a refusal, so a record is punished for a field it never had. On the
Parrish register 8 rows carry no date, and one of them is a true pair.

The third matters more than it looks. Of the 12 true pairs whose dates
disagree, several are the near misses you would predict: `2017-01-01` against
`2016-12-31`, `2018-11-18` against `2018-10-18`.

Adding the comparator changes decisions, so it moves decision ids. It belongs
in a release with a changelog entry, not a patch.

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
