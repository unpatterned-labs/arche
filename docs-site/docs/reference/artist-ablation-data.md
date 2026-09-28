# The artist variant-list data, and which file carries which claim

Every number in [what a name list is worth](../writing/what-a-name-list-is-worth.md) and [part two](../writing/what-a-name-list-is-worth-part-two.md) comes from a committed artifact or a pinned source. This page maps claim to file so a reviewer can check one without reading all of it, and it is honest about the two claims whose artifacts are not yet public.

The first study's data and scripts left this repository in 0.10.0 with the rest of the generator. The tree before that commit still has all of it:

```sh
git checkout c92c3f7^ -- datasets/artists_dataops data/synthetic
```

That gives you the `artists_v0` world, the variant lists, the coverage script and the six-arm benchmark. Start there; the table below says which file carries which claim.

## The sources, and why the licences matter

| asset | what it is | licence |
|---|---|---|
| MusicBrainz artist dump | `musicbrainz-artist-20260923-001002`, sha256 `ce3be9e9...`, one pinned file | CC0 |
| Wikidata snapshot | frozen alias/altLabel pull, artists with a P434 MusicBrainz id | CC0 |
| MusicBrainz-derived variant list | `artist_variants_musicbrainz_africa_v1.yaml`, 5,982 lines | CC0 |
| Wikidata-derived variant list | `artist_variants_wikidata_africa_v1.yaml` | CC0 |
| curated equivalence groups | `datasets/artist_equivalences/{afrobeats,hiphop,pop}.yaml` | CC-BY-4.0 |

Both primary sources are CC0, which is the whole reason this line of work exists. The comparable named sets in this field are closed: ai4privacy is academic-only and forbids derivatives, i2b2 needs a data-use agreement, OpenSanctions Pairs is a purchase. **Nobody's permission is needed to publish either this data or this result**, and that was a selection criterion, not a convenience.

One asset is deliberately *not* used here: `datasets/name_equivalences/` is CC-BY-NC-SA, so a published benchmark shipping it would be a separate decision. The artist lists avoid it.

## The separation that makes the result meaningful

The answer key and the list given to the matcher must not come from the same place, or "with list" wins by construction.

They are joined **only by identifier**: Wikidata P434 against the MusicBrainz id. Never by name. In part two each source takes a turn on each side, which is a stronger check than picking one arrangement and asserting it was fair.

Train, tune and test are entity-disjoint: each artist id hashes to exactly one split, so no artist can appear on both sides. Thresholds are picked on tune and test is scored once.

## Claim to artifact

| claim | where it is measured | artifact |
|---|---|---|
| EM prices a variant intersection at +10.7 bits, against +10.75 for an exact name match | first study | `bench_splink_variants_result.json` |
| Raw Splink finds 0 of 2,016 pairs below Jaro-Winkler 0.7, at every threshold 0.1 to 0.9 | first study | same |
| The public list covers 10.5% of truth pairs | first study | `coverage_result.json` |
| Collision cost: 125 false merges raw, 264 with the native variant level | first study | `bench_splink_variants_result.json` |
| List as a scoring signal only: +0.003 F1 in one direction, **−0.007 and −4.4 points of precision** in the other | part two, preregistered | `results/artist_ablation_A_*.json`, `..._B_*.json` |
| List also choosing candidates: +0.41 and +0.35 covered recall, precision does not fall | part two, **exploratory** | same, `preregistered: false` |
| Coverage caps the gain: 31% and 12% of test pairs, F1 +0.12 and +0.04 | part two | same |
| Term frequency changes nothing to four decimals | part two | same, and see the gap below |
| Removing lexicographic label residue: Jaro-Winkler precision 0.6669 to 0.9467 | supplier world, generator 0.0.2 against 0.0.5 | `docs/benchmarks/ng-supplier-v002-400-report.md` |
| Diacritic-loss recall 0.72 against 0.30, paired in 5 of 5 seeds | supplier world, five seeds | `results/nigeria_supplier_v1_s400_sweep.json` |

## Two gaps, stated rather than left to be discovered

**The frequency half of the claim is not tested.** "The frequency table buys precision" needs a world where two *different* artists share a name. The part-two cohorts contain 0 and 5 such collisions among test pairs, so the measurement could not happen. The world that had 327 collision pairs is the earlier `artists_v0`, whose generator now lives only in this repository's history: `git show c92c3f7^:data/synthetic/arche_synthetic/artists.py`. Until that is rebuilt, the sentence at the top of `afrobeats.yaml` is half measured.

**The generator and the part-two artifacts are not in a public repository yet.** The generator moved out of this repository in 0.10.0 and is developed privately while the file contract stabilises. What that means concretely: the *claims* above are checkable against files, and a reviewer outside the project cannot yet fetch all of those files. The first study's artifacts are recoverable from this repository's history; the part-two artifacts are not here at all.

That is a real limitation and it bounds what the result can be called. **Two independent sources agreeing across directions is evidence about the mechanism. It is not yet an independently reproducible published benchmark**, and it should not be described as one until the artifacts can be fetched by someone with no access to this project.

## Recovering the first study

It was removed from this repository in 0.10.0 along with the rest of the generator. The tree before that commit has all of it:

```sh
git ls-tree -r --name-only 'c92c3f7^' -- datasets/artists_dataops   # 9 files: scripts and results
git checkout 'c92c3f7^' -- datasets/artists_dataops                # the scripts and result files
git checkout 'c92c3f7^' -- data/synthetic                          # the generator and artists_v0
```

`git show --stat` will look empty against these paths and that is not a problem with the commit: it reports what a commit *changed*, and that one changed nothing under `datasets/`. `ls-tree` reports what it *contains*, which is the question.

The four commands the first essay quoted run from that tree, not from the current one.

## What would close the gap

In order, and none of it is hard:

1. **Publish the two part-two result JSONs and the two cohort worlds.** They are a few megabytes and they carry every condition, interval and content fingerprint. This alone makes every part-two number checkable.
2. **Publish the generator**, or a release artifact of the worlds it produces. The file contract is already matcher-neutral; what is missing is a fetchable copy.
3. **Rebuild a collision-bearing artist world** and measure the frequency half of the claim.
4. **Preregister variant retrieval** and run it on artists this study has not seen. The next MusicBrainz dump's new African artists are the natural set.
