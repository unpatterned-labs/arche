# The number we could not reproduce

*We went looking for the evidence behind our own headline result. It was not there. What we built instead disagreed with us three times. By Dennis Irorere, August 2026.*

---

This row sat in the arche README for four months. It was the most quotable thing on the page.

```text
Name frequency | frequency-blind matching, 40% false merges | 0% | recall held at 1.00
```

Someone asked what was behind it. That is the whole reason this post exists.

The honest answer was: nothing we could show them. The 60 positives and 60 negatives were never committed. No script computed the number. The document the page cited for it, `ARCHE_NAME_FREQUENCY_BENCHMARK.md`, did not exist in the repository or anywhere in its git history. The claim was probably measured at some point. It had simply stopped being checkable, and neither we nor anyone else could tell the difference.

So we built the benchmark. Then we ran it, and it disagreed with us in both directions at once.

## What we were actually claiming

The idea underneath the number is not controversial. If two records both say the surname *Smith*, that agreement is weak evidence they are the same person, because a great many people are called Smith. If they both say *Zabielski*, the same agreement is strong evidence. A matcher that treats those two agreements identically will over-merge on common names and it will do so confidently.

This is old. Winkler wrote the value-specific frequency adjustment into record linkage in 1989. What arche adds is not the mathematics, it is shipping the population data the adjustment needs, which is a data problem rather than a modelling one.

The question is whether that helps as much as we said, and what it costs. Our old test could not answer either, because we had written both the problem and the solution. The 60 negatives were pairs we picked to exhibit exactly the failure the signal was designed to fix. A test built that way passes almost by construction.

## Using people we did not choose

The replacement uses the North Carolina voter register, which is a public record: 141,163 real registrations from one county. Real names, real distribution, and nobody involved was selecting for a result.

The negatives are now **observed rather than written**. We take pairs of real people who share a surname exactly, have different first names, and have different birth years. That last condition matters more than it looks. Voter rolls really do contain duplicate registrations of the same person, and without the birth-year test some of those would quietly enter the benchmark labelled as different people when they are not.

The positives are still constructed, and the script says so on every line that reports them. We take one real record and render it two ways, with the middle name and without it. That is an ordinary recording difference, and it is the case we keep citing in talks: *John Smith* and *John Evelyn Smith*, same person, one form shorter. But we generated the second form, so recall here describes a distribution we made.

That asymmetry is the important part. **The false-merge column is evidence. The recall column is a sanity check.** They should not be read with the same confidence.

## The result, including the part that embarrasses us

Three arms over the same two lists. One with the frequency signal removed, one exactly as a user gets it, one with the population table loaded explicitly.

| arm | false merges | precision | recall | F1 |
|---|---|---|---|---|
| frequency-blind | 7,705 | 0.162 | 0.990 | 0.278 |
| shipped default | 41 | 0.946 | 0.480 | 0.637 |
| population table | 24 | 0.963 | 0.412 | 0.577 |

The old claim was wrong twice.

**The benefit is much larger than we said.** Not 40% of pairs confused, but 7,705 wrong edges against 1,114 negative pairs. Run across two lists rather than pair by pair, a frequency-blind matcher does not occasionally slip. It links nearly everything to nearly everything, because without any sense of what a name is worth, sharing a surname looks like evidence every time.

**And it costs recall, which we had explicitly denied.** "Recall held at 1.00" was not a rounding problem, it was false. On same-person pairs differing only by a dropped middle name, the frequency-aware engine matches 48%. The rest go to `review` rather than being merged. We think that is the right behaviour, since abstaining is the whole design. Reporting the safety gain while stating the cost was zero was not.

The benchmark also **fails one of its own pre-declared criteria**, and we published it failing. The criterion asked the frequency-aware arm to stay within ten points of the blind arm's recall. That was a badly chosen criterion, because the blind arm reaches 0.990 recall at 0.162 precision by merging almost everything, so meeting it would have required merging almost everything too. We left it failing rather than rewriting it into a pass after seeing the result, which is the specific temptation this exercise exists to resist.

## Then we checked the others, and found a pattern

Having done it once, leaving the rest unexamined was not defensible.

**Febrl 4.** We have claimed precision 1.0, 87.7% auto-resolved, 96.2% surfaced since v0.1. It reproduces exactly. All three figures land on the published values, which was a relief for about a minute. Febrl ships `soc_sec_id`, a near-unique synthetic identifier, and with that field in play the engine is substantially joining on a key rather than resolving anything. Withhold it and the same pipeline scores precision 0.921 with 282 false merges, auto-resolving 65.7%.

**Leipzig DBLP-ACM.** We quoted precision 0.9506 with an em dash in the baseline column, implying there was nothing to compare against. There was. Out of the box the same pipeline scores 0.8500 with 391 false merges. The 0.9506 requires the caller to declare a discriminator on the `year` field. Both numbers are real. Only the flattering one travelled.

**Multilingual detection, 47/48 against Presidio's 37/48.** We cannot re-run this at all. The 48-case set is not in the repository and nothing computes the number. It is now labelled unverified rather than sitting beside four figures that can be checked.

None of these was fabricated. Every one was a real run. The failure is quieter and more ordinary than fraud: **the configuration stopped travelling with the number.** A result gets measured under specific conditions, the conditions live in someone's head or in a notebook, the number goes into a README, and six months later the sentence around it has drifted into describing something the run never tested.

## Something we found and decided not to fix

The benchmark turned up a thing we were not looking for. `crosswalk(entity="person")` never loads the shipped name-frequency table. The `person` pack is missing from the internal map that connects a pack to its population data, so it self-calibrates over whatever two lists you hand it. The `organisation` pack has an entry, added to fix precisely this, with a code comment explaining why. Nobody added one for `person`.

We expected that to be a bug. On this benchmark it is not: the self-calibrated default scores F1 0.637 against the population table's 0.577, buying seven points of recall for under two points of precision. Changing it would also change the `decision_id` of every person-pack decision ever issued.

So we wrote it down and left it. It is in the changelog as a known gap rather than quietly patched, because we do not yet have the evidence to say which way it should go.

## What this does not prove

The whole benchmark is one county in North Carolina. US naming, US population structure. arche's clearest claim is about names that Western defaults handle badly, *Diallo* and *Jallow*, *Mohammed* and *Muhammad*, and this measures none of that. Building an African name benchmark with the same standard is now the largest open item we have, and it is unbuilt.

We also still cannot re-run the multilingual result or the 58-pair name-equivalence set.

## Where this leaves us

arche is a research project that happens to have working software, and we would rather it be read that way than as a product with a position to defend. The thesis we are exploring is narrow: most of the effort in entity resolution goes into better mathematics for combining evidence, that half is genuinely solved and has better free software than ours in [Splink](https://moj-analytical-services.github.io/splink/), and the remaining gains may sit somewhere less glamorous, in what the records look like before anything is compared. Which spellings count as the same name. How common that name is where the data came from. What agreement is actually worth.

We think that is one reasonable way to approach the problem. We do not know that it is right, and this week it got less certain rather than more, which seems like the correct direction for it to move while we are still finding out.

Both benchmarks ship, with their result files, and both are one command:

```bash
python datasets/names_dataops/bench_name_frequency.py
python datasets/names_dataops/bench_febrl.py
```

If you run them and get something different from us, that is the most useful thing you could do with this post.

---

*The full ledger, including what is measured, what failed its own criteria, and what remains unverified, is in [the whole picture](../concepts/the-whole-picture.md).*
