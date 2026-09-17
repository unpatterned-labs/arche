# The artist world: Splink with and without a name-variant list

Robin Linacre asked one question: *run Splink over the same records with the variant list and without it, and say what the difference is.* This directory is that experiment, and this page is how to run it.

## What is here

| file | what it is |
|---|---|
| `data/synthetic/worlds/artists_v0/` | **the world.** 9,944 records of 2,941 real African artists, every disagreement labelled by cause. Parquet + JSON schema + manifest. No truth column in the file a matcher is given |
| `datasets/data/artist_variants.jsonl` | **the list.** 449 groups: MusicBrainz alias sets (joined to the truth by Wikidata P434, never by name) plus 38 curated groups |
| `example_splink_with_variants.py` | the experiment in one file, ~90 lines, imports nothing from arche |
| `bench_splink_variants.py` | the full version: six arms, strata, collisions, threshold sweeps, an oracle arm |
| `coverage.py` | how much of the truth the list knows, measured before any matcher runs |
| `pull_musicbrainz.py` | how the list was built |
| `RESULTS.md` | what we found |

**Where the truth comes from.** Every alias group is a real artist with the alternate names Wikidata records for them (CC0). The generator decides which alias each of four catalogues writes and what it does to it — lost diacritics, a typo, capitals — and never decides what an artist is called. The list Splink is given comes from MusicBrainz, a different editorial community, so the list and the truth can disagree. A list derived from the truth would win by construction.

**What the list covers.** 10.5% of the truth's alias pairs. That number bounds the gain before anything runs; `coverage.py` prints it.

## Run it

From the repository root, with Splink installed (`uv sync --extra splink`, or `pip install splink pyarrow pandas`):

```sh
uv run python datasets/artists_dataops/example_splink_with_variants.py
```

```text
arm                    precision  recall  alias recall  false
splink, raw                0.835   0.389         0.004  1,169
splink + variants          0.840   0.401         0.068  1,158
```

Both arms at p ≥ 0.5. **`alias recall`** is the column the experiment is about: the 3,002 pairs where two records name the artist differently and the names are not string-similar — `Wizkid` against `Ayodeji Ibrahim Balogun`. Raw Splink finds four in a thousand of them. With the list it finds one in fifteen, at the same precision — which is what a list that covers one alias in ten should buy, and no more.

The example does three things, and they are the whole method:

1. reads `observations.parquet` and maps each name to its list group (`name_variants`, and a `canonical` key for blocking);
2. builds two Splink models that differ by one comparison level — `ArrayIntersectLevel("name_variants")` between exact match and Jaro-Winkler — and one blocking rule on the canonical key, so pairs that share no prefix can be proposed at all;
3. scores both against `truth.parquet`, and against `differences.parquet` for the alias stratum.

## The full result

```sh
uv run python datasets/artists_dataops/bench_splink_variants.py
```

Six arms — raw, canonicalised, the native level, both, and each list arm again with the truth's own aliases as an **oracle** (100% coverage, leakage by construction, labelled as such) — at five thresholds, with recall by stratum and false merges on the 327 record pairs where two *different* artists genuinely share a name. Two minutes. `RESULTS.md` walks through it; the two numbers to know:

- **Splink priced the list itself at +10.7 bits** — the same as an exact name match. EM was not told to trust the list; it looked at how list-asserted pairs behaved and concluded that.
- **A complete list is worth 0.2 of F1** (0.743 → 0.944). The independent list, at 10.5% coverage, buys 2.8 recall points. The gap is the value of building the list.

## Regenerate everything

```sh
python -m arche_synthetic --world-pack artists_v0 --scale 10000 --out data/synthetic/worlds/artists_v0
uv run python datasets/artists_dataops/pull_musicbrainz.py     # ~15 min at MusicBrainz's 1 req/s, cached
uv run python datasets/artists_dataops/coverage.py              # the 10.5%; writes artist_variants.jsonl
uv run python datasets/artists_dataops/bench_splink_variants.py
```

The world is seeded and fingerprinted: the same seed produces the same content, checked by hash rather than by file bytes.

## Two things to know before quoting a number

**Train the name on a rule that does not mention it.** Splink treats any comparison whose column appears in the EM blocking rule as untrainable in that session. Block on `substr(name,1,2)` to train the name and every name level stays at its default; the first version of the example did exactly that and reported a model that had never learned what a name is worth. Both scripts train the name while blocking on `country`.

**The world has two fields, and it shows.** Best operating points sit at 0.1–0.3, not 0.9, and unseeded u-sampling moved one arm's false-merge count from 1,180 to 4,258 between runs while recall by stratum did not move at all. Comparisons *between arms* at a matched threshold are what the tables support; the absolute probabilities are a property of a thin world. `bench_splink_variants.py` seeds the sampling so a run is reproducible, and says so rather than pretending that makes the number stable.

## What Robin asked for, and what is and is not here

| asked | status |
|---|---|
| artist / stage-name matching, Splink with and without variants | **done** — this directory |
| MusicBrainz as the source of variants | **done** — `pull_musicbrainz.py`, joined by identifier |
| names with correlation (a *Mary* is not an *Ahmed*) | **done** in the supplier worlds — `ng_supplier_v1` and `africa_supplier_v1` draw both halves of a name from one country's real pairs |
| 10k, then 100k | **10k done**; `--scale 100000` runs, but the alias groups are fixed at 1,468 so a bigger world is thinner in aliases, not richer |
| African *person* names with lexicon-driven spelling variants, Splink with and without | **not done, and not honestly doable yet.** The name-equivalence lists we hold are CC-BY-NC-SA and there is no second public source of "Mohammed is Muhammad for this person" to keep the list and the truth apart. Corrupting with a lexicon and testing with the same lexicon measures an upper bound at 100% coverage, which is the oracle arm here without the honest arm beside it |
