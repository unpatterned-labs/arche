# What a name list is worth, part two: we designed the experiment better and the answer changed

Three weeks ago we published [what a name list is worth](what-a-name-list-is-worth.md). It measured what happens when you give Splink a list of known name variants for African artists, and it found that a trained Fellegi-Sunter model prices such a list as highly as an identical name: **+10.7 bits**, against +10.75 for an exact match.

That number still holds. The conclusion built on it does not.

We have since run the same question twice more, with two independent sources taking turns as the answer key, entity-disjoint splits, a preregistered protocol and bootstrap intervals. The headline is narrower and more useful than what we published:

> **A variant list buys almost nothing if it is only allowed to score pairs. It buys 35 to 41 points of recall if it is allowed to choose which pairs get scored.**

That distinction was invisible in the first study, and it is the difference between an asset that pays and one that does not.

## The question, as it was actually asked

This matters because the question is easy to misremember, including by us.

Robin Linacre, who wrote Splink, looked at this work in September and raised two things. The second was an experiment, and it was not "is arche better than Splink". Our own repository contains this sentence, at the top of a curated equivalence file:

> *equivalence data buys recall, the frequency table buys precision, the gate keeps merges safe*

We wrote that. We had never measured it. His proposal was the ablation that tests it: **run the same matcher over the same records twice, once with the name-variant list and once without, and report the difference.** One engine, one variable.

So every arm in every run below is Splink. There is no cross-engine comparison here, deliberately. Splink wins the [four head-to-heads that matter](../reference/benchmarks.md) on real labels and nothing in this post changes that. An ablation has no fairness problem to argue about, which is exactly why it was the right experiment.

## Why the pairs are unreachable, in Splink's own numbers

`Wizkid` and `Ayodeji Ibrahim Balogun` are one artist. No edit distance joins them, no phonetic key joins them, and term frequency has nothing to say: term frequency discounts a name that is *common*, and neither of these is. On the first world, Splink's learned weights for the name comparison put that pair in "all other comparisons" at minus 6.7 bits against a prior near minus 11.

A list moves it to the exact-match level. That is a swing of roughly 17 bits, and it is the entire mechanism under test.

The prediction we wrote down before running anything was specific: **the gain concentrates where string similarity is near zero and is near zero where string similarity is high.** That prediction was right, and it was also not the whole story.

## The trap, and the design that avoids it

If the list and the answer key come from the same source, "with list" wins by construction and the result is worthless. So the two are separated by construction, and in the second study each source takes a turn on both sides:

| | Direction A | Direction B |
|---|---|---|
| Answer key | Wikidata alias groups | MusicBrainz aliases |
| List given to the matcher | MusicBrainz names and aliases | Wikidata snapshot |
| Cohort | 1,197 artists | 2,858 artists |
| Held-out test artists / true pairs | 227 / 681 | 458 / 1,374 |
| Test pairs the list covers | 212 (31%) | 170 (12%) |

The two are linked **only by identifier**, Wikidata P434 against the MusicBrainz id, never by name. Both come from one pinned dump and one frozen snapshot. Train, tune and test are entity-disjoint: every artist id hashes to exactly one split, so no artist appears on both sides of the line. Each condition fits on train, picks its threshold on tune, and scores test once.

Intervals are a paired entity-level bootstrap, 2,000 resamples, every condition scored on the same draws. They are not seed intervals, because the artist world is determined by its MusicBrainz ids and a world seed cannot vary it. That is worth saying out loud: a seed interval here would have been theatre.

## The result

| | A: F1 | A: covered recall | B: F1 | B: covered recall |
|---|---|---|---|---|
| surface, no list | 0.564 | 0.443 | 0.617 | 0.429 |
| surface + frequency | 0.564 | 0.443 | 0.617 | 0.429 |
| surface + variants, list scores only | 0.567 | 0.443 | 0.609 | 0.465 |
| variants + variant retrieval (*exploratory*) | **0.686** | **0.849** | **0.656** | **0.782** |

Paired differences from the no-list baseline, median with 95% interval:

| | A | B |
|---|---|---|
| list scores only: F1 | +0.003 [0.000, +0.006] | **−0.007 [−0.014, −0.001]** |
| list scores only: precision | +0.001 | **−0.044 [−0.067, −0.026]** |
| list also picks candidates: F1 | **+0.122 [+0.093, +0.155]** | **+0.039 [+0.027, +0.054]** |
| list also picks candidates: covered recall | +0.406 [+0.324, +0.485] | +0.353 [+0.258, +0.445] |

Read the third row first. **Given the list only as a scoring signal, it does nothing in one direction and costs four points of precision in the other.** That is the preregistered answer, and it is negative.

The reason is blocking. The protocol held the blocker fixed at a three-character prefix of the plain name, which is a reasonable default and the wrong one for this problem: it discards 51% of the pairs the list covers in direction A and 53% in direction B **before any scoring happens**. A stage name and a legal name rarely share a prefix. The list was being handed a question the candidate generator had already answered wrongly.

Let the list choose candidates as well, and covered recall rises by 35 to 41 points in both directions, precision does not fall, and false-merge clusters move by one or two (A 27 to 22, B 25 to 26).

## What we are and are not claiming

The retrieval condition is **exploratory, not confirmatory.** It was added after the preregistered conditions had been run and their blocking ceiling was visible, and it is marked `preregistered: false` in the artifacts. The honest summary of this study is: *the registered answer was null, and the follow-up suggests the mechanism is retrieval rather than scoring.* Confirming it means registering "variant retrieval" in advance and running it on artists the study has not seen, which the next dump's new African artists will provide.

**The gain is capped by coverage, and the cap is the real finding.** The list covers 31% of test pairs in one direction and 12% in the other, and the F1 gain tracks it: +0.12 and +0.04. The 12% agrees with the 10.5% measured in the opposite direction three weeks earlier. A public alias list covers roughly one pair in nine in the domain it was built for. Outside that domain it is irrelevant: on a worldwide MusicBrainz sample it covers 12 held-out pairs, below our reporting gate, so we report it as not measured rather than as zero.

**Half of the original claim is still untested.** "The frequency table buys precision" did not move a single figure to four decimal places in either direction. That is not a null result, it is a measurement that could not happen: frequency only lowers a common name's weight when two *different* artists share it, and these cohorts contain 0 and 5 such collisions among test pairs. Testing it needs a world with deliberate name collisions. Our earlier artist world had 327 of them, and measuring that half properly is the next job rather than a footnote.

## The other half of what Robin said, and what looking for it found

The first thing he raised was not an experiment. It was a defect.

Our generator drew given names and surnames independently, so it produced `Zübeyde Saliou` and `Fabiano Anaehobi`: a Turkish given name on a West African surname, an Italian one on an Igbo surname. He put it as a rule, that a *Mary* should not be an *Ahmed*.

The reason this matters more than realism is that it corrupts the stratum it was built to exercise. Real name collisions are structured: a common Yoruba surname collides with other Yoruba records in Lagos. Ours collided at random. A matcher that learned "this given name with that surname is implausible, so these records were probably merged in error" would have been **right on our data and wrong on real data.** We would have been measuring on a distribution that does not exist.

That fix is in. Looking for its effects turned up a second defect in the same place, and this one had been quietly changing our published numbers.

The name pool is built from a public lexicon, and a public lexicon of names is not a list of names. It is a list of *labels*. Two classes of label were getting through a filter that had been copied into two modules with two sets of thresholds, so a fix had to be made twice and had been made once:

- **Lexicographic qualifiers survived.** `Barber surname`, `Clement surname`, `Given name`. Two tokens, a capital letter, no digits: every structural check passed them. Fifteen reached the pool, and because the pool is shuffled and drawn Zipf-weighted, one landing near the head of the distribution is drawn constantly. The result was **34 observations of 15 different organisations all named `Harding surname ...`**.
- **Tone-marked names were being deleted.** A Unicode combining mark falls outside the character class the filter used, so `Adébánkẹ́`, `Adélọ́lá` and `Àgbẹ́bí` were thrown away while `Barber` was kept. Ninety-six entries, concentrated in Yoruba and Igbo orthography, in a generator whose entire subject is African name realism.

The first defect was not cosmetic. Fifteen distinct companies sharing a distinctive leading token is not a hard matching problem, it is a wrong one: a name-similarity matcher merges them and is then scored as imprecise for doing exactly the right thing. Fixing it, same pack, same seed, same scale:

| 400 organisations | precision before | after |
|---|---|---|
| Jaro-Winkler (names only) | 0.6669 | **0.9467** |
| exact | 0.9149 | **0.9849** |

**Twenty-eight points of precision, on the arm that reads the polluted field.** Recall barely moved, 0.8441 to 0.8394, which is the reassuring half: the world did not become easier, it became correctly labelled. Every conclusion the old table supported about the cost of name-only fuzzy matching was wrong, and wrong in the direction that flattered the more elaborate arms.

The general lesson is the one we did not have three weeks ago. **A defect in generated data does not merely add noise. It can systematically penalise whichever matcher reads the polluted field**, and it will do so silently, because the numbers stay plausible.

Recovering the tone-marked names had a second effect worth recording: it created a stratum that could not previously be measured. Lost diacritics went from too thin to score to 112 pooled pairs across five seeds, and it is now the cleanest separation we have between a mark-folding comparator and a character-similarity one: **0.72 against 0.30**, paired in five of five seeds. It exists only because the generator stopped throwing those names away.

## What we would tell someone starting this

Four things, in the order we learned them.

**Ask for the ablation, not the contest.** One engine, one variable. We had four head-to-head losses against Splink before this, and a fifth would have taught us nothing. The ablation was publishable whichever way it came out.

**Preregister, then report the registered answer first.** Ours was null. The interesting result came second and is labelled exploratory, and that label is the only reason the interesting result is worth anything.

**Check what the candidate generator threw away before crediting or blaming the scorer.** Half the pairs our list covered never reached scoring. We had been measuring a question that had already been decided upstream.

**A benchmark's data is a claim, and it needs the same scepticism as a result.** Two realism defects, one pointed out by a reviewer and one found by measuring the first, and the second was worth 28 points of precision on one arm. The numbers never looked wrong.

## Reproducing this

Every number above comes from committed artifacts and pinned sources: one MusicBrainz dump identified by sha256, one frozen CC0 Wikidata snapshot, two cohort worlds rebuilt by a script, and two result files carrying every condition, every interval and the content fingerprint of every table. The world contract is Parquet plus a schema per table plus a manifest, deliberately not a Python class, so running your own recipe over it requires nothing of ours installed.

Licences are the reason this programme exists at all: MusicBrainz core data is CC0 and Wikidata is CC0, so unlike the academic-only and purchase-only sets in this field, nobody's permission is needed to publish either the data or the result.

One command re-derives both directions and diffs them against the committed results:

```sh
python verify_artist_ablation.py
```

Run on 2026-09-28, both directions reproduced with only the wall-clock fields moving. The bundle is nine files and 1.8 MB.

See [the reviewer's guide](../reference/artist-ablation-data.md) for every path, size and content fingerprint, the command that rebuilds the cohorts from the pinned dump, and an honest account of which claims are not yet in a publicly fetchable artifact.
