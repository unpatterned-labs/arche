# What a name list is worth

*Splink's author asked us a question we had been answering by assertion. We built a world of real artists to measure it, found the two biggest public alias sources know one alternate name in ten, and let Splink price the list itself. By Dennis Irorere, September 2026.*

---

`Wizkid` and `Ayodeji Ibrahim Balogun` are one person. So are `Burna Boy` and `Damini Ogulu`, `Tyla` and `Tyla Laura Seethal`. If you run a catalogue, a rights registry or a press archive, these pairs are in your data, and no edit distance, term-frequency weight or phonetic key will ever put them together. The strings share nothing that matters. The only thing that can pair them is a list that says they are the same.

We have such lists. `datasets/artist_equivalences/` opens with the sentence *equivalence data buys recall, the frequency table buys precision, the gate keeps merges safe.* When Robin Linacre, who wrote [Splink](https://moj-analytical-services.github.io/splink/), saw that, he asked the obvious thing: run Splink over the same records with the list and without it, and say what the difference is.

That claim had been in our repository for months and had never been measured. This post is the measurement.

## Why the pair is unreachable, in Splink's own numbers

It is worth being precise about *why* a stage name and a legal name cannot be linked by a string method, because "obviously" is not a number.

Splink is a Fellegi-Sunter model. Every comparison level gets a weight, in bits, learned from the data by expectation-maximisation. On the world described below, the raw model learned these for the name:

```text
exact match                      +10.8 bits
Jaro-Winkler >= 0.92             +10.3
Jaro-Winkler >= 0.88              +8.7
Jaro-Winkler >= 0.70              +7.1
all other comparisons             -6.7
```

`Wizkid` against `Ayodeji Ibrahim Balogun` is "all other comparisons": minus 6.7 bits, against a prior of about minus 11. No threshold recovers that. And it never gets that far, because the pair is never proposed: blocking on the name and its prefix reaches 80.7% of the world's true pairs, and the missing fifth is almost entirely this kind. **Raw Splink finds 0 of the 2,016 pairs in the world whose names are below Jaro-Winkler 0.7, at every threshold from 0.1 to 0.9.**

That is the stratum a list exists for. The question is what a list does to it, and what it costs elsewhere.

## The rule that makes the experiment honest

If the list Splink is given comes from the same place as the answer key, "with list" wins by construction and the number means nothing. So the two are different sources, joined by identifier and never by name.

The **truth** is Wikidata: 1,464 African musicians with the alternate names Wikidata records for them, CC0. The **list** is MusicBrainz: alias sets for the same artists, reached through Wikidata's `P434` property (the MusicBrainz id), plus our 38 curated groups. Two editorial communities, two opinions about what an artist is called. Where they disagree is where the experiment lives.

Before any matcher ran, we measured how much of the truth the list knows:

```text
truth: 1,464 alias groups, 3,503 name pairs
list :   449 groups (411 MusicBrainz, 38 curated)

coverage of truth pairs          10.5%   (367 / 3,503)
  alias  (not string-similar)    10.6%
  spelling                       10.0%
  artist has a MusicBrainz id    18.2%
  artist does not                 0.2%
```

The chain of loss is short. 1,468 Wikidata artists; 727 carry a MusicBrainz id at all; 311 of those have no MusicBrainz aliases; 411 usable groups; one alias pair in ten. Alias and spelling coverage are the same, so the list is not preferentially missing the hard pairs. It is just thin.

That number is a finding on its own, before Splink runs. **For African artists, the two largest public alias sources between them know about one alternate name in ten.** Anyone who says "just use MusicBrainz" has not counted.

It also fixes the experiment's shape. A list that covers 10% of pairs can lift recall on them by at most about 10 points, whatever the matcher does. So there are two lists in the table, not one: the **independent** list you can actually get, and an **oracle**: the truth's own aliases, 100% coverage, leakage by construction and labelled as such. The oracle says what a *complete* list would be worth. The gap between the two arms is the value of building one.

## The world

Real names, invented catalogues. Every alias group is a real artist with Wikidata's alternate names for them; the crowd around them are real people's names from the same pull, one each. The generator decides which alias each of four sources writes (a streaming catalogue that prefers the stage name, a press archive that writes whatever the journalist used, a festival line-up in capitals, a rights registry that writes the legal name) and what it does to it: lost diacritics, a typo, a truncated field. It never decides what an artist is called.

9,944 records of 2,941 artists, 15,171 true pairs, and every disagreement between two records of one artist labelled with why: `alias`, `spelling`, `case_upper`, `typo`. Twenty-eight pairs of *different* artists who genuinely share a name, found in the data and not made, are written to their own file, because that is where a list's cost will show.

Source coverage and error rates are declared assumptions. Names, aliases and countries are public data. The manifest says which is which.

## Six ways to give Splink a list

Every arm is Splink 4.0.16. What changes is the list and how it is handed over.

| arm | what Splink sees |
|---|---|
| **raw** | name and country, term frequency on. What a user runs today |
| **canon** | each name replaced by its list group's canonical form before Splink sees it |
| **level** | raw name kept; a `name_variants` array added and an `ArrayIntersect` comparison level placed between exact match and Jaro-Winkler, with its m and u estimated by EM like any other level |
| **both** | canonical name and the variant level |

Each of `canon` and `level` runs with the independent list and with the oracle. The `level` arm is the one Robin would want, and the reason is in the table below: it lets Splink put its own price on the list rather than being made to trust it.

The `level` configuration, in full:

<!-- docs-test: skip -->
```python
import splink.comparison_level_library as cll
import splink.comparison_library as cl
from splink import SettingsCreator, block_on

name = cl.CustomComparison(
    output_column_name="name",
    comparison_levels=[
        cll.NullLevel("name"),
        cll.ExactMatchLevel("name").configure(tf_adjustment_column="name"),
        cll.ArrayIntersectLevel("name_variants", min_intersection=1),   # the list
        cll.JaroWinklerLevel("name", 0.92),
        cll.JaroWinklerLevel("name", 0.88),
        cll.JaroWinklerLevel("name", 0.7),
        cll.ElseLevel(),
    ],
)
settings = SettingsCreator(
    link_type="dedupe_only",
    comparisons=[name, cl.ExactMatch("country")],
    blocking_rules_to_generate_predictions=[
        block_on("name"), block_on("substr(name,1,4)"),
        block_on("canonical"),          # reach the pairs that share no prefix
    ],
)
```

Blocking is part of the treatment. A pair that shares no prefix is never proposed unless something proposes it, and the list key is that something. That is not the harness helping the list; it is what a list is for, and the `block` column below says how much of each arm's recall was reachable at all.

## The result

Recall by stratum, each arm at its own best-F1 operating point. **`<0.7`** is the sub-stratum the post is about: 2,016 alias pairs below Jaro-Winkler 0.7 on the observed names. `coll.` is false merges on the 327 record pairs where two different artists share a name.

| arm | p ≥ | prec | recall | F1 | false | coll. | **<0.7** | spelling | typo | block |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| raw | 0.15 | 0.712 | 0.777 | 0.743 | 4,759 | 125 | **0.000** | 0.657 | 0.530 | 0.807 |
| canon / independent | 0.15 | 0.710 | 0.805 | 0.755 | 4,981 | 126 | **0.161** | 0.677 | 0.533 | 0.832 |
| level / independent | 0.15 | 0.719 | 0.805 | 0.759 | 4,769 | 131 | **0.141** | 0.710 | 0.530 | 0.831 |
| canon / oracle | 0.30 | 0.925 | 0.963 | **0.944** | 1,180 | 159 | **0.944** | 0.963 | 0.953 | 1.000 |
| level / oracle | 0.10 | 0.756 | 1.000 | 0.861 | 4,902 | 264 | **1.000** | 1.000 | 1.000 | 1.000 |

`both` is not shown because it is `canon`: two records with intersecting variants always share a canonical form, so the exact level fires first and Splink reports the variant level as never observed. The full sweep at 0.1, 0.2, 0.3, 0.5 and 0.9 is in the result file beside the script.

## What Splink thinks the list is worth

This is the number we would quote if we could only quote one.

With the variant level in the model, EM estimated the weight of "these two records' variant sets intersect" at **+10.7 bits**. An exact match on the name, in the same model, is +10.75. The same held for the independent list and the oracle.

Nobody told Splink to trust the list. It looked at the data, saw which pairs the list asserted and how those pairs behaved on every other comparison, and concluded that a list-asserted alias is worth as much as the names being identical. That is a stronger endorsement of equivalence data than anything we have written, and it came from the model we were supposedly competing with.

## What a list you can actually get is worth

Less than that endorsement suggests, and for a reason that has nothing to do with the model.

The independent list can reach 13.4% of the alias record pairs in the world. It recovers 14–16% of the `<0.7` stratum and lifts overall recall by 2.8 points at the same precision. One alias in ten in the list; one alias in ten recovered. There is no leverage in the inference. **The value is in the list**, and the list is thin.

The oracle shows what the list would be worth if someone finished it: canon/oracle reaches F1 0.944 against raw's 0.743, and the `<0.7` stratum goes from nothing to 0.944. That 0.2 of F1 is the value of the curation work that turns a 10% list into a complete one, as one measured number. We think of it as the price of the asset.

## What it costs

The collision column. Raw Splink merges 125 of the 327 pairs where two different artists share a name. The independent list adds one to six. The complete list adds 34 with canonicalisation and 139 with the native level.

A list that says the two `Tyla`s are one artist will merge two Tylas, and a complete list does that more often than a thin one, because it has more to say. The gain is real; so is this. Reporting one without the other is the failure mode we were trying to avoid.

## Canonicalise first, or let Splink weigh it?

At independent scale it hardly matters: F1 0.755 against 0.759. At oracle scale canonicalisation wins clearly, 0.944 against 0.861, and the reason is a detail worth knowing if you build one of these.

The `ArrayIntersect` level carries no term-frequency adjustment. An alias hit on a *common* name is priced at the full +10.7 bits, while an exact hit on the same common name is discounted by how common it is. That makes the level arm more generous on exactly the names that collide: 264 collision merges against 159. Canonicalising first gets the adjustment for free, because the exact-match level already has one. A TF-adjusted variant level would close the gap; until Splink has one, canonicalise.

## What this does not say

**It is not a comparison of arche with Splink.** Every arm above is Splink. We ran our own artist pack once, for the record, and its F1 came out at 0.832, above every non-oracle Splink arm, which is not the finding it looks like. The precision is refusal: it sent 13,883 pairs to review, nearly four times the number of true pairs in the world. The Splink arms were configured for this ablation, not tuned to win; a Jaro-Winkler 0.7 level that EM priced at +7 bits makes most of their false merges, and a Splink user would drop it. And each Splink arm's threshold was chosen on the labels where ours is the default. Splink wins [the four head-to-heads that matter](../reference/benchmarks.md), on real labels, and nothing here changes that.

**The world is thin, and it shows.** Two fields make a steep model: the best operating points sit at 0.10–0.30, not 0.9, and an exact-name pair with no country on either side lands near p = 0.4. Comparisons between arms at a matched threshold are what the table supports. The absolute probabilities are a property of a world with two columns, and the first thing to do if this draws fire is a `v1` with a third column a real catalogue has.

**These are musicians.** Stage names are the extreme case of the alias problem, which is why they were the right place to measure it and the wrong place to generalise from. Whether a variant list is worth +10.7 bits on Yoruba given names is a different experiment, and one we cannot run honestly yet: the African name-equivalence lists we hold are CC-BY-NC-SA, and there is no second public source of *Mohammed is Muhammad for this person* to keep the list and the truth apart.

## Where this leaves us

Three things we did not know in August.

The public alias data for African artists is one-tenth complete, and where MusicBrainz knows more than Wikidata it is usually a legal name the other never recorded: 1,388 of the list's 1,755 pairs are outside the truth. That is the gap, and it is a data gap, not a modelling one.

A trained Fellegi-Sunter model, given a list, prices it as highly as identical names. The argument for equivalence data does not need us to make it; Splink makes it from the data.

And the value of a list is bounded by its coverage and paid for in collisions, both measurable, both measured, neither the number we would have guessed.

The world that produced these numbers is a file contract, not a Python class: Parquet, a schema beside each table, a manifest with content fingerprints and provenance, no truth column in the file a matcher is given. Anyone with Splink, or Zingg, or a SQL prompt, can regenerate it and run their own recipe over it. That is what it is for.

```sh
python -m arche_synthetic --world-pack artists_v0 --scale 10000 --out worlds/artists_v0
uv run python datasets/artists_dataops/pull_musicbrainz.py      # ~15 min, cached
uv run python datasets/artists_dataops/coverage.py               # the 10.5%
uv run python datasets/artists_dataops/bench_splink_variants.py  # ~2 min
```

Every number above comes out of those four commands. If one of them does not, that is the bug report we want.
