# Entity-resolution benchmark data — sources & attribution

Public benchmark sets from the Database Group at the University of Leipzig,
used by `data/scripts/benchmark_leipzig.py`. They are here for one reason no
other data in this repo can supply: **their match mappings are complete**.

Every accuracy figure arche published before these landed — Kano, London — came
from a labelled set we built ourselves, and each measured recall: how many true
pairs we find. None could measure a **false merge**, because none knew every
pair that is *not* a match. Eighty-six labelled London pairs say nothing about
what the engine does to the other few thousand. Here, every pair absent from the
mapping is a known non-match, so precision is measurable — and the first time we
measured it, it was 0.85, not the ~0.95 the recall figures implied.

Using someone else's benchmark is also the point. A set we built, labelled and
tuned against cannot falsify us. This one can, it is used widely enough that our
numbers can be read against other people's, and it is published whichever way it
falls.

- **Source:** Benchmark datasets for entity resolution, Database Group Leipzig.
- **URL:** https://dbs.uni-leipzig.de/research/projects/benchmark-datasets-for-entity-resolution
- **License:** Creative Commons Attribution 4.0 (CC BY 4.0). Redistribution is
  permitted with attribution, which is what this file provides.
- **Citation:** Köpcke, H., Thor, A., Rahm, E. *Evaluation of entity resolution
  approaches on real-world match problems.* PVLDB 3(1), 2010.
- **Modifications:** none. The files are byte-identical to the published
  archive; all normalisation happens in the benchmark script at read time.

## DBLP–ACM

Bibliographic records for the same publications from two digital libraries.
Chosen first because it is the smallest set with a complete mapping and because
its entity type — a publication — has the discriminator structure that turned
out to matter: a title that carries most of the identity, and a year that
carries almost none of it but refutes decisively.

| File | Rows | Columns |
|---|---|---|
| `DBLP2.csv` | 2,616 | `id, title, authors, venue, year` |
| `ACM.csv` | 2,294 | `id, title, authors, venue, year` |
| `DBLP-ACM_perfectMapping.csv` | 2,224 | `idDBLP, idACM` |

What it found, and what it changed, is written up in
[the roadmap](../../docs-site/docs/concepts/roadmap.md#the-refutation-gap-and-the-first-precision-number).

## Scope and handling

**Benchmark evidence only, never a shipped asset.** These files are not a data
pack, are not licence-classed for pack inclusion, and cannot reach the wheel:
`packages/arche-core/pyproject.toml` sets `packages = ["src/arche"]`, so nothing
under `data/` is packaged. This is the same rule the ODbL OpenStreetMap extracts
follow, applied to a licence that would in fact permit more.

**Not a tuning set.** The declaration in the benchmark script is the one an
ordinary user would write on day one — hand-declared comparators, no
bibliographic pack, no per-dataset fitting. Tuning comparators against a public
benchmark until the number looks good is how published ER results stop meaning
anything, and a benchmark we have overfitted is worth less to us than no
benchmark at all.

Re-run: `uv run python data/scripts/benchmark_leipzig.py`
