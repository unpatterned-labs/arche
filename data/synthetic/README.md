# arche-synthetic

Known entity worlds, imperfect observations, exact ground truth — and every disagreement labelled with **why it happened**.

```bash
pip install arche-synthetic          # pyarrow and pyyaml. Nothing else.
python -m arche_synthetic --scale 400 --out ./worlds/ng
```

```python
from arche_synthetic import Benchmark, Predictions, build

world, manifest = build("ng_supplier_v0", seed=42, out=Path("worlds/ng"))

bench = Benchmark.load(Path("worlds/ng"))
report = bench.score(Predictions(arm="mine", pairs=my_predicted_pairs))
report["recall_by_stratum"]["change/ORG_RELOCATED"]   # the column nobody else has
```

From a checkout of this repository, run the scripts **from the repo root**. `data/synthetic` has its own `pyproject.toml`, so `uv run` with the working directory inside it resolves to the standalone project and will not find arche:

```bash
python data/synthetic/build_ng_supplier_v0.py          # ~7s, writes worlds/ng_supplier_v0/
python data/synthetic/run_benchmark.py --world data/synthetic/worlds/ng_supplier_v0_s150
```

## Why this exists

arche keeps being blocked by data licensing. ai4privacy's 300k is academic-only and forbids derivatives; i2b2 needs a data-use agreement; OpenSanctions Pairs is a purchase. Every one of those is somebody else's permission. This is the path that needs nobody's.

And one thing arche can do had never been measured: `ledger.observe()` — add evidence about a record, re-decide its open pairs, supersede rather than overwrite — had no benchmark, because measuring it needs data where an entity *legitimately changed* and the truth says so. No public entity-resolution benchmark has that column. This generates it, and [RESULTS.md](RESULTS.md) is what it found.

## The idea in one table

| kind | example | are both records true? |
|---|---|---|
| `change` | the supplier moved; the director resigned; the account was replaced | **yes**, at their respective times |
| `representation` | `Établissements Koné & Fils SARL` → `ETS Kone & Fils` | yes — same fact, different encoding |
| `error` | typo, OCR misread, truncation, mutated digit | no — one is a distortion |

Existing synthetic ER benchmarks produce only the third row: take a record, corrupt it, call the result a duplicate. A matcher tuned on that learns that all disagreement means "different entity", and then splits entities in production the first time a supplier moves.

The labels are computed **by construction**. Every observed value carries a note of which state it came from and which transforms were applied, so a difference is explained by comparing provenance rather than by guessing from the strings.

## The modules

```
arche_synthetic/
├── ids.py         opaque record ids — the invariant that keeps truth out of the input
├── world.py       entities, states, relationships; the frequency-weighted name draw
├── lifecycle.py   events: relocation, rename, director change, account change
├── observe.py     sources, representation rules, corruption rules, difference labelling
├── export.py      Parquet + JSON Schema + manifest, and the write-time leak check
├── evaluate.py    the stratified scorer — recall stratifies, precision does not
└── data/          the vendored name lexicon (CC-BY-4.0)
```

**Nothing imports `arche` at all.** The name lexicon is vendored (from arche's `african_names_v1`, itself built from Wikidata/ParaNames), and the RC/TIN format checks are local — with `test_synthetic_world.py::test_the_local_validators_agree_with_arches` asserting they still agree with arche's, which is stronger than importing either, because a one-sided import would hide a drift.

Verified rather than asserted: installed into an empty virtualenv with only `pyarrow` and `pyyaml` beside it, the package generates a world whose content fingerprints are **identical** to one built inside this repo.

## Output

See [DATACARD.md](DATACARD.md) for what the shipped world contains, every measured number, and — as importantly — what it is not.

**The contract is the files, not a Python class.** Parquet with documented columns, a JSON Schema beside each one, a manifest with provenance. A Splink, Zingg, R or SQL user consumes it without installing anything of ours. The moment the truth is only readable through our own types, matcher-neutrality is gone.

## Running the benchmark

```bash
python data/synthetic/run_benchmark.py --world data/synthetic/worlds/ng_supplier_v0_s150
python data/synthetic/run_benchmark.py --arms exact,jaro_winkler     # the fast ones
```

Seven arms: `exact` (normalised name + city join), `jaro_winkler`, `splink` (Fellegi-Sunter, its own decision boundary), `arche/pack`, `arche/custom`, and the two ledger arms — `arche/ledger` (records ingested in arrival order) and `arche/ledger+observe` (plus the operator's registry lookup). **Measured results and their caveats: [RESULTS.md](RESULTS.md).** The short version — every engine that reads the address fails on relocated suppliers, and the ledger path is the only thing that moves the number.

The arms are extras, so the base install stays two dependencies: `pip install "arche-synthetic[bench]"` for the baselines, `[splink]` for the Splink arm, `[arche]` for the arche and ledger arms, `[all]` for everything.

### Cutting the repository

The trigger the plan set was *a stratified result **and** arche not being the only arm*. Both hold: Splink runs on this data and lands within 0.007 recall of `arche/pack`.

This directory is now a complete standalone project — `pyproject.toml`, `LICENSE`, `.gitignore`, a vendored lexicon, no arche import anywhere, installable and verified in a clean environment. What remains is one command to extract its history and one to publish it:

```bash
git subtree split -P data/synthetic -b arche-synthetic
```

then push that branch to a newly created `unpatterned-labs/arche-synthetic` and set `main` to it.

**Publishing is the owner's to do.** Nothing in this branch creates a remote, pushes, or uploads anything; the repository's guards block an agent from doing so, and that is the correct arrangement.

Afterwards, in this repository: drop the directory, add `arche-synthetic` as a dev dependency, and keep a thin consumer that runs the arche arms against the published package. The three test files in `packages/arche-core/tests/` move last — they become the new repo's `tests/`, and until the cut they are what keeps the generator honest inside arche's CI.
