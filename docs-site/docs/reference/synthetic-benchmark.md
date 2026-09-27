# The synthetic benchmark

Three worlds of known entities, imperfect observations, exact truth, and **every disagreement labelled with why it happened**. That last part is the reason this exists: no public entity-resolution benchmark says whether two records disagree because something changed, because the same fact was written differently, or because one of them is wrong. A matcher tuned without that distinction learns that all disagreement means "different entity", and then splits a supplier in half the first time it moves.

```python
from arche_synthetic import available, load

print(available())

w = load("ng_supplier_v0")
w.describe()

print(f"\n{len(w.observations):,} observations, {len(w.truth):,} in the answer key")
print("disagreements by kind:", w.difference_counts())
```

Everything below is reproducible from the shipped files. The scripts write their own result files and nothing on this page carries a constant from a run that is not committed beside it.

## The three kinds, and why the first one matters

| kind | example | are both records true? |
|---|---|---|
| `change` | the supplier moved; the director resigned; the account was replaced | **yes**, at their respective times |
| `representation` | `Établissements Koné & Fils SARL` written as `ETS Kone & Fils`; a source that stores names IN CAPITALS | yes, the same fact encoded differently |
| `error` | a typo, a truncation, a mutated digit | no, one of them is a distortion |

Existing synthetic benchmarks produce the third row only: take a record, corrupt it, call the result a duplicate. The first row is the one that costs money in production and the one nobody publishes, because producing it means modelling an entity's life rather than adding noise to a string.

```python
w = load("ng_supplier_v0")
change = {d["cause"] for d in w.differences if d["difference_kind"] == "change"}
print(sorted(change))
```

## The three worlds

| world | what it is | the question it answers |
|---|---|---|
| `ng_supplier_v0` | 6,144 observations of 2,000 Nigerian organisations, seen by four sources over six years | does a matcher survive an entity legitimately changing |
| `artists_v0` | 9,944 observations of 2,905 real African musicians under their real Wikidata aliases | what is a name-variant list worth to a matcher |
| `places_v1` | a 665-row master address sheet and 1,000 delivery requests in seven renderings | does a delivery endpoint verify, ask one question, or refuse, and how often does it verify the wrong door |

Smaller and larger cuts of the supplier world ship beside it (`_s150`, `_s400`, `_s1000`) because the noise band at 150 suppliers is wide enough to matter, and a claim measured on one cut should be checked on another.

## The file contract

Matcher-neutral on purpose. The contract is Parquet plus JSON Schema plus a manifest, not a Python class, so using this benchmark does not require installing arche.

| file | what it is |
|---|---|
| `observations.parquet` | **all a matcher sees.** One row per observation of an entity by a source |
| `truth.parquet` | `record_id` to `entity_id`. The answer key |
| `differences.parquet` | one row per (pair, attribute): the two records, the field they disagree on, and the labelled reason |
| `events.parquet` | what actually happened to the entity, and when |
| `collisions.parquet` | pairs of genuinely *different* entities that share a name, found in the data rather than made |
| `manifest.yaml` | the seed, the generator version, a content fingerprint per table, and a provenance entry per asset |

Two rules the generator enforces rather than documents. **No truth column can reach the file a matcher is given**: `export.check_no_leak` compares the observation columns against a forbidden list at write time, so a leak fails the write instead of a test. And **`record_id` is a content hash**, because an id that encoded the entity would make the answer key derivable from the input by string manipulation.

```python
w = load("ng_supplier_v0")
print("given to a matcher:", w.given_to_a_matcher)
print("tables:", sorted(w.tables))
print("fingerprints:", sorted(w.manifest["content_fingerprints"]))
```

## Running your own matcher against it

Read the observations, produce pairs, and hand them back with a name. `Benchmark.score` returns overall precision and recall, the per-cause recall, entity-level B-cubed, and a breakdown of what your false merges were holding together.

<!-- docs-test: fragment -->
```python
from arche_synthetic import Benchmark, Predictions, load

bench = Benchmark.load(load("ng_supplier_v0_s150").path)
pairs = my_matcher(bench.observations)          # [(record_id, record_id), ...]
report = bench.score(Predictions(arm="mine", pairs=pairs))

print(report["overall"])
print(report["recall_by_stratum"]["change/ORG_RELOCATED"])
```

`Predictions` also takes pairs you surfaced for *review* rather than merged, because an engine with three answers scored as though it had two is scored wrongly. The `cover` column in the results counts both.

## What it has found so far

Seven arms over 444 records of the supplier world, five seeds for the noise band:

```sh
uv run python data/synthetic/run_benchmark.py --world data/synthetic/worlds/ng_supplier_v0_s150
uv run python data/synthetic/run_benchmark.py --world ... --fast   # five arms, about 20 s
```

**A changed address defeats every engine that reads the address.** Recall on the 55 relocated pairs: a rule join finds 1.8%, arche 14.5%, Splink 30.9%, the incremental ledger 30.9%. Jaro-Winkler, which compares names and nothing else, finds 81.8%, and pays for it in precision. That gap is five times the seed-to-seed spread, which is why it is the one comparison worth quoting from a single run. Nothing about it flatters arche, and no benchmark without a labelled `change` column can show it.

**A name-variant list is worth about fifteen times its cost on the stratum it exists for.** On `artists_v0`, one Splink model with an array-intersection level over a MusicBrainz-derived variant list against the same model without it: alias-pair recall 0.004 to 0.068 at the same precision, from a list covering 10.6% of the alias pairs. EM priced the variant level at +10.70 bits against +10.74 for an exact name match, which is to say it learned to trust the list about as much as it trusts the name itself.

**Reading more fields made matching worse.** Adding phone, TIN, account number and director to the comparator set took recall from 0.745 to 0.694 and `ACCOUNT_CHANGED` recall from 0.889 to 0.333, because those fields are disproportionately the ones that legitimately change, so they disagree on exactly the pairs that most need linking.

**Splink and arche are indistinguishable at this scale**, within 0.04 recall and 0.007 precision. An engine we did not write, on our data, landing in the same region as ours is evidence the benchmark measures the problem rather than a quirk of our implementation.

The full table with every caveat is in `data/synthetic/RESULTS.md`, and its section 0 should be read before quoting any single number: at 150 suppliers an unpaired difference below about 0.10 recall cannot be distinguished from which world you happened to draw.

## The notebooks

Three, each answering one question, with outputs committed so they read without running.

- `examples/notebooks/26_what_is_in_a_world.ipynb`: the three families, and how to read them.
- `examples/notebooks/27_what_a_variant_list_is_worth.ipynb`: the variant-list experiment end to end, coverage first and the collision cost last.
- `examples/notebooks/28_does_the_ledger_beat_batch.ipynb`: the seven arms, and the refusal behind the relocation finding, run live.

## Generating a world

Every world is a seed and a command, and two runs at one seed agree by fingerprint. Fingerprints rather than file comparison, because Parquet embeds a writer version: byte-identical data can produce byte-different files.

```sh
cd data/synthetic
python -m arche_synthetic --scale 2000 --out worlds/mine
python -m arche_synthetic --world-pack artists_v0 --scale 10000 --out worlds/artists
python -m arche_synthetic --world-pack places_v1 --scale 1000 --out worlds/places
```

`--scale` means organisations for the supplier world, records for artists, requests for places. Each takes under ten seconds at full size. The generator commands run from `data/synthetic`; the benchmark and the notebooks run from the repository root.

## Licence and provenance

Code Apache-2.0, data CC-BY-4.0. The artist world's truth is derived from Wikidata (CC0) and its variant list from MusicBrainz alias sets (CC0), joined by Wikidata P434 and never by name, so the two editorial communities can disagree and a list that is wrong about an artist shows up as a list that is wrong.

Every manifest carries a provenance entry per asset saying what class of claim it is: `public-data-derived` where real data decides, `synthetic-assumption` where a distribution was chosen. The supplier world's name pool is a worked example of the distinction. Which names exist and go together comes from real people; how concentrated the distribution is does not, because Wikidata holds notable people where almost every name occurs once. So the real counts decide which names are commoner and a Zipf curve supplies the shape, and the manifest says so on its own line rather than presenting the whole thing as evidence.

**Why this exists at all**: the alternatives are closed. ai4privacy is academic-only and forbids derivatives, i2b2 needs a data-use agreement, OpenSanctions is a purchase. This is the path that needs nobody's permission, and `DATACARD.md` records what it is not, including the known defects.

**The claim this supports, and no more**: this is the only public entity-resolution benchmark that labels why two records disagree, and its African name and place distributions are not a re-skin of a US voter roll. Not "the benchmark for Africa", because nobody outside this project has run it yet.

## Where to read next

- [Benchmarks](benchmarks.md) for the other direction: arche measured against published results on public datasets.
- [What a name list is worth](../writing/what-a-name-list-is-worth.md) for the variant-list result written out in full.
- `data/synthetic/DATACARD.md` for every cause with its count, and the limitations.
