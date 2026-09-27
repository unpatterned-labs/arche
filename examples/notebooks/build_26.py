# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0
"""Generate 26_what_is_in_a_world.ipynb.

    python examples/notebooks/build_26.py

The first of three synthetic-data notebooks. This one answers "what are these
files and how do I read them"; 27 answers the variant-list question; 28 runs
the arms. Nothing here needs Splink or arche: it is pyarrow, pandas and the
`load()` reader.
"""
from __future__ import annotations

import json
from pathlib import Path

MD, CODE = "markdown", "code"
cells: list[tuple[str, str]] = []
md = lambda t: cells.append((MD, t.strip("\n")))      # noqa: E731
code = lambda t: cells.append((CODE, t.strip("\n")))  # noqa: E731


md("""
# What is in a synthetic world

Three world families ship in `data/synthetic/worlds/`. They exist because
arche kept being blocked by data licensing: ai4privacy is academic-only and
forbids derivatives, i2b2 needs a data-use agreement, OpenSanctions is a
purchase. This is the path that needs nobody's permission.

| world | records | the question it exists to answer |
|---|---|---|
| `ng_supplier_v0` | 6,144 observations of 2,000 Nigerian organisations | does a matcher survive an entity *legitimately changing*: a supplier moves, a director resigns, a bank account is replaced |
| `artists_v0` | 9,944 observations of 2,905 real African musicians | what is a name-variant list worth, when `Wizkid` and `Ayodeji Ibrahim Balogun` are one person |
| `places_v1` | a 665-row master sheet and 1,000 delivery requests | does a delivery endpoint verify, ask one question, or refuse, and how often does it verify the wrong door |

The thing none of them share with a public benchmark: every disagreement
between two records carries **why it happened**, not just that it exists.

(Counts are of what a matcher is given. A manifest reports the entities the
generator *drew*, which is a larger number where some were never written to a
catalogue: 2,941 artists drawn, 2,905 with at least one observation.)

Run this from the repository root.
""")

code("""
from arche_synthetic import load

w = load("data/synthetic/worlds/ng_supplier_v0")
w.describe()
""")

md("""
## What a matcher sees, and what it does not

One file is the input. Everything else is the answer key, and the generator
refuses to write a world where the two are mixed: `export.check_no_leak`
compares the observation columns against a forbidden list at write time, so a
truth column cannot reach the file a matcher is given even by accident.

`record_id` is a content hash for the same reason. If it encoded the entity id
the truth would be derivable from the input by string manipulation.
""")

code("""
print("given to a matcher:", w.given_to_a_matcher)
print("tables:", ", ".join(f"{k} ({len(v):,})" for k, v in sorted(w.tables.items())))
print()
print("one observation:")
for key, value in list(w.observations[0].items())[:8]:
    print(f"  {key:<16} {value}")
""")

md("""
## The column no other benchmark has

`differences.parquet` is one row per (pair, attribute): two records, the field
they disagree on, and the reason. The reasons fall into three kinds, and the
first one is the point.

| kind | example | are both records true? |
|---|---|---|
| `change` | the supplier moved; the director resigned | **yes**, at their respective times |
| `representation` | `Établissements Koné & Fils SARL` becomes `ETS Kone & Fils` | yes, the same fact encoded differently |
| `error` | a typo, an OCR misread, a truncation | no, one of them is a distortion |

Existing synthetic ER benchmarks produce only the third row: take a record,
corrupt it, call the result a duplicate. A matcher tuned on that learns that
all disagreement means "different entity", and then splits entities in
production the first time a supplier moves.
""")

code("""
import pandas as pd

by_kind = w.difference_counts()
print({k: f"{v:,}" for k, v in sorted(by_kind.items())})

causes = pd.Series(w.difference_counts("cause")).sort_values(ascending=False)
causes.head(12).to_frame("rows")
""")

md("""
## One supplier that moved

The `change` rows are the ones worth looking at by hand. Take an entity whose
address changed, pull every observation of it in time order, and read what the
sources say. Both records are true; a matcher that reads the address and calls
them different entities has split a supplier in half.
""")

code("""
moved = next(r for r in w.differences if r["cause"] == "ORG_RELOCATED")
records = w.records_of(moved["entity_id"])

print(f"entity {moved['entity_id']}, seen {len(records)} times\\n")
for r in records:
    print(f"  {r['observed_at']}  {r['source']:<8} {r['name'][:38]:<38} {r['city']}")

print("\\nwhy the first two disagree:")
for d in w.why(records[0]["record_id"], records[1]["record_id"]):
    print(f"  {d['attribute']:<14} {d['difference_kind']:<15} {d['cause']}")
""")

md("""
## The other two families

The same call opens them. `kind` says which family you have, because the
tables differ: an artist world has `collisions` (two different artists who
genuinely share a name) and no lifecycle events; a place world has a master
sheet and delivery requests rather than observations.
""")

code("""
artists = load("data/synthetic/worlds/artists_v0")
artists.describe()
print()

places = load("data/synthetic/worlds/places_v1")
places.describe()
""")

md("""
The artist world's `collisions` table is what keeps the variant-list
experiment honest: a list that merges every name it knows about will merge
these too, and the cost has to be printed beside the gain.
""")

code("""
pd.DataFrame(artists.collisions).head(5)
""")

md("""
## Reproducible, and saying so

Every world carries a manifest: the seed, the generator version, a content
fingerprint per table, and a provenance block per asset saying where the data
came from and what class of assumption it is. Two runs at the same seed agree
to the byte, which is checked by fingerprint rather than by comparing parquet
files (parquet embeds a writer version, so byte-identical data can produce
byte-different files).
""")

code("""
m = w.manifest
print("seed:", m["seed"], " generator:", m["generator_version"])
print("fingerprints:")
for table, digest in m["content_fingerprints"].items():
    print(f"  {table:<14} {digest[:24]}...")
print("\\nprovenance:")
for entry in m["provenance"]:
    print(f"  {entry['asset']}\\n    {entry['class']}")
""")

md("""
## Generate one yourself

Every world is a seed and a command. From `data/synthetic`:

```sh
python -m arche_synthetic --scale 400 --out worlds/small              # suppliers
python -m arche_synthetic --world-pack artists_v0 --scale 10000 --out worlds/artists_v0
python -m arche_synthetic --world-pack places_v1 --scale 1000 --out worlds/places_v1
```

`--scale` means organisations for the supplier world, records for artists and
requests for places. Each takes under ten seconds at full size.

## Where to read next

- **[27 What a variant list is worth](27_what_a_variant_list_is_worth.ipynb)**: the
  experiment Splink's author asked for, end to end.
- **[28 Does the ledger beat batch](28_does_the_ledger_beat_batch.ipynb)**: the seven
  arms over the supplier world, and the relocation finding.
- `data/synthetic/DATACARD.md` for every cause with its count, and what this
  data is not.
""")


def build() -> Path:
    nb = {
        "cells": [
            {
                "cell_type": kind,
                "metadata": {},
                "source": text.splitlines(keepends=True),
                **({"outputs": [], "execution_count": None} if kind == CODE else {}),
            }
            for kind, text in cells
        ],
        "metadata": {
            "kernelspec": {"display_name": "Python 3", "language": "python",
                           "name": "python3"},
            "language_info": {"name": "python"},
        },
        "nbformat": 4,
        "nbformat_minor": 5,
    }
    out = Path(__file__).with_name("26_what_is_in_a_world.ipynb")
    out.write_text(json.dumps(nb, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return out


if __name__ == "__main__":
    print(build())
