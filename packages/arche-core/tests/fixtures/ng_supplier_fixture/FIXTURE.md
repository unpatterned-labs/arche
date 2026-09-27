# `ng_supplier_fixture`, a synthetic test fixture

Generated, not collected. **Do not edit these files by hand**, and do not treat
a number measured on them as a benchmark result.

| | |
| --- | --- |
| world pack | `nigeria_supplier_v1` |
| seed | 42 |
| scale | 60 canonical organisations |
| tables | differences 792, events 60, observations 168, truth 168 |
| generator | arche-synthetic 0.0.5 |
| source commit | `1ed410b-dirty` |
| exported | 2026-09-27 |

## What it is for

Catching a regression in a matcher, on data where every disagreement between two
observations carries **why it happened**: `change` (the supplier moved, both
records were true), `representation` (the same fact written differently), or
`error` (one record is a distortion). A matcher tuned only against the third
kind learns that all disagreement means "different entity" and then splits an
entity the first time it legitimately changes.

It is far too small to measure how good a matcher is. Recall on 60 organisations
moves by tenths on a single seed. Use it to answer "did this change break
something", and a full world in the generator's own repository to answer
"is this good".

## The contract

`observations.parquet` is the only table a matcher may see. Everything else is
evaluator-only: `truth.parquet` maps an observation to its canonical entity,
`differences.parquet` labels every disagreement with its cause, and
`events.parquet` records what happened to the entity and when. `record_id` is a
content hash, so the answer key is not derivable from the input.

Reading it needs `pyarrow` and nothing else:

```python
import pyarrow.parquet as pq

observations = pq.read_table("observations.parquet").to_pylist()
truth = {r["record_id"]: r["truth_entity_id"]
         for r in pq.read_table("truth.parquet").to_pylist()}
```

## Refreshing it

From a checkout of the generator's repository:

```sh
python export_fixture.py --into <this directory's parent>
```

The generator version and commit above are what make a changed number
attributable. If they move in the same commit as a matcher change, nobody can
tell which one moved the number.
