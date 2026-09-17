# What a name-variant list is worth to Splink

*Measured 2026-09-13 on `artists_v0` (seed 42): 9,944 records of 2,941 real African artists, 15,171 true pairs, every disagreement labelled by cause. Every arm is Splink 4.0.16. Script: `bench_splink_variants.py`. Reproducible: u-sampling is seeded and two consecutive runs agree to the last digit.*

---

## The question

`Wizkid` and `Ayodeji Ibrahim Balogun` are one person. No edit distance, term-frequency weight or phonetic key will ever pair them; only a list that says they are the same can. Splink's author asked what such a list actually buys. This is the answer on real alias data, with the cost printed beside the gain.

## The lists, and why there are two

| list | source | coverage of the truth's alias pairs |
|---|---|---:|
| **independent** | MusicBrainz alias sets joined by Wikidata P434, plus 38 curated groups | **10.5%** of name pairs, 13.4% of record pairs |
| **oracle** | the truth's own alias groups — **leakage, labelled** | 100% |

The truth is Wikidata; the independent list is a different editorial community, joined by identifier and never by name, so the two can disagree and a list derived from the truth cannot win by construction. `coverage.py` measured the 10.5% before any matcher ran. The oracle exists to say what a *complete* list would be worth; the gap between the two arms is the value of building one.

## The arms

| arm | what Splink sees |
|---|---|
| **raw** | name and country, term frequency on. What a Splink user runs today |
| **canon** | each name replaced by its list group's canonical form before Splink sees it |
| **level** | raw name kept; a `name_variants` array added and an `ArrayIntersect` comparison level placed between exact and Jaro-Winkler, **with its m and u estimated by EM like any other level** |
| **both** | canonical name and the variant level |

Blocking is part of the treatment: the list arms also block on the list key, because a pair that shares no prefix is otherwise never proposed. That is what a list is for, and the `block` column says how much of each arm's recall was reachable at all.

## The result

Recall by stratum. `alias` is two records naming the artist differently with Jaro-Winkler < 0.88 on the intended names; **`<0.7`** is the sub-stratum below 0.7 on the observed names — 2,016 pairs no string method can see. `spell` is `Wiz Kid` / `Wizkid`. `coll.` is false merges on the 327 record pairs where two *different* artists genuinely share a name.

Each arm at its own best-F1 threshold, and at a matched 0.5:

| arm | p ≥ | prec | recall | F1 | false | coll. | alias | **<0.7** | spell | typo | block |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| raw | 0.15 | 0.712 | 0.777 | 0.743 | 4,759 | 125 | 0.059 | **0.000** | 0.657 | 0.530 | 0.807 |
| canon / indep | 0.15 | 0.710 | 0.805 | 0.755 | 4,981 | 126 | 0.200 | **0.161** | 0.677 | 0.533 | 0.832 |
| level / indep | 0.15 | 0.719 | 0.805 | 0.759 | 4,769 | 131 | 0.184 | **0.141** | 0.710 | 0.530 | 0.831 |
| canon / oracle | 0.30 | 0.925 | 0.963 | 0.944 | 1,180 | 159 | 0.943 | **0.944** | 0.963 | 0.953 | 1.000 |
| level / oracle | 0.10 | 0.756 | 1.000 | 0.861 | 4,902 | 264 | 1.000 | **1.000** | 1.000 | 1.000 | 1.000 |
| | | | | | | | | | | | |
| raw | 0.5 | 0.835 | 0.389 | 0.531 | 1,169 | 90 | 0.004 | **0.000** | 0.435 | 0.253 | 0.807 |
| canon / indep | 0.5 | 0.835 | 0.403 | 0.543 | 1,208 | 95 | 0.079 | **0.078** | 0.415 | 0.256 | 0.832 |
| level / indep | 0.5 | 0.840 | 0.401 | 0.543 | 1,158 | 79 | 0.068 | **0.067** | 0.441 | 0.253 | 0.831 |
| canon / oracle | 0.5 | 0.869 | 0.510 | 0.643 | 1,163 | 142 | 0.494 | **0.481** | 0.506 | 0.473 | 1.000 |
| level / oracle | 0.5 | 0.957 | 0.492 | 0.650 | 338 | 126 | 0.481 | **0.465** | 0.492 | 0.464 | 1.000 |

`both` is omitted: with a consistent list it is identical to `canon`, because two records with intersecting variants always share a canonical form, so the exact level fires first and the variant level is never observed (Splink reports it untrained). The full sweep at 0.1 / 0.2 / 0.3 / 0.5 / 0.9 is in `bench_splink_variants_result.json`.

## What it says

**1. On the pairs no string method can see, raw Splink finds none — at any threshold.** The `<0.7` column is 0.000 for the raw arm at 0.1, 0.15, 0.2, 0.3, 0.5 and 0.9. Its blocking never proposes them (`block` 0.807: nineteen percent of all true pairs are unreachable) and if it did, "all other comparisons" is priced at −6.7 bits. This is the stratum the list exists for, and it is exactly as unreachable as the argument said.

**2. Splink's own estimate of the list: +10.7 bits.** With the variant level in the model, EM priced "the two records' variant sets intersect" at **+10.7 bits — the same as an exact match on the name (+10.75)**, for both the independent list and the oracle. That is Splink saying, from the data and without being told, that a list-asserted alias is worth as much as the names being identical. It is the number to quote.

**3. The independent list delivers about what its coverage promised, and no more.** It can reach 13.4% of alias record pairs; it recovers 14–16% of the `<0.7` stratum and lifts overall recall by 2.8 points (0.777 → 0.805) at the same precision. A list that covers one alias in ten buys one alias in ten. There is no free lunch in the inference; the value is in the list.

**4. A complete list is worth 19 F1 points.** canon/oracle at its best operating point: precision 0.925, recall 0.963, F1 0.944 against raw's 0.743, and the `<0.7` stratum goes from 0.000 to 0.944. That gap — 0.201 F1 — is the value of the curation work that turns a 10% list into a complete one. It is the data-flywheel argument as one measured number.

**5. The cost is real and it is in the collision column.** Raw merges 125 of the 327 collision pairs at its best operating point; the independent list adds one to six; the complete list adds 34 (canon) or 139 (level). A list that says two `Tyla`s are one artist will merge two Tylas, and a complete list does that more often than a thin one. Report the gain without this column and the result is not worth reading.

**6. Canonicalise, or let Splink weigh the list?** At independent scale it barely matters (F1 0.755 vs 0.759). At oracle scale canonicalisation wins clearly (0.944 vs 0.861) — and the reason is a modelling detail worth knowing: the `ArrayIntersect` level carries **no term-frequency adjustment**, so an alias hit on a common name is priced at the full +10.7 while an exact hit on the same common name is discounted. That makes the level arm more generous on exactly the pairs that collide (264 collision merges against 159). A TF-adjusted variant level would close that; canonicalising first gets it for free because the exact level already has one.

## For the record: the arche arm

Run once with `--arche`, shipped `artist` pack, default thresholds, its curated 38-group list and nothing else. 109 seconds.

| arm | prec | recall | F1 | false | coll. | `<0.7` | spell | typo | review queue |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| arche artist pack | 0.978 | 0.723 | 0.832 | 242 | 142 | 0.013 | 0.567 | 0.021 | **13,883** |

Read it carefully, because the F1 is higher than any Splink arm short of the oracle and that is not the finding it looks like.

- **The precision comes from refusal.** arche sends 13,883 pairs to `review` — 3.8 times the number of true pairs in the world. Counting those as found lifts recall to 0.822; counting them as a queue someone has to work is the honest reading. Its typo recall is 0.021: a misspelled name is not a match, it is a question. Splink has no queue and pays for that in the `false` column.
- **The Splink arms were configured for the ablation, not tuned to win.** Two fields, a hand-written prior, a Jaro-Winkler 0.7 level that EM priced at +7 bits and that produces most of the false merges at the operating points that matter. A Splink user tuning for this world would drop that level or raise the prior's `recall`, and the `false` column would move. And each Splink arm's best-F1 threshold was chosen *on the labels*; arche's is the shipped default.
- **On the pairs this experiment is about, arche has nothing either.** `<0.7` recall 0.013 -- the 38 curated groups reach about one alias pair in a hundred. A list is a list, whoever consumes it.
- **It is not a head-to-head.** The four benchmarks on `docs-site/docs/reference/benchmarks.md` are, and Splink wins all four on real labels. This is a thin two-field world where a Fellegi-Sunter model cannot separate well and a gate that refuses looks good by refusing. That says something about worlds, not engines.

## What it does not say

- **Nothing about arche beyond the paragraph above.** Every arm that matters is Splink.
- **Nothing about names in general.** These are musicians, whose aliases are the extreme case; the world's records carry two fields, and a two-field Fellegi-Sunter model is steep — the best operating points sit at 0.10–0.30, not 0.9, and an exact-name pair with no country on either side lands near p = 0.4. Comparisons *between arms at a matched threshold* are what this table supports; the absolute probabilities are a property of a thin world.
- **Nothing about collisions beyond the 28 this data contains.** They were found, not made. A catalogue with more homonyms pays more for a list.
- **The independent arm's ceiling is the list's, not Splink's.** For African artists, the two largest public alias sources between them know about one alternate name in ten.

## Reproduce

```sh
python -m arche_synthetic --world-pack artists_v0 --scale 10000 --out data/synthetic/worlds/artists_v0
uv run python datasets/artists_dataops/pull_musicbrainz.py      # ~15 min, cached
uv run python datasets/artists_dataops/coverage.py               # the 10.5%, and the list
uv run python datasets/artists_dataops/bench_splink_variants.py  # ~2 min
```
