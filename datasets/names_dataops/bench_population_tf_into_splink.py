# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Q2: does the population table's small-batch property transfer INTO Splink?

    uv run python datasets/names_dataops/bench_population_tf_into_splink.py

`bench_population_vs_batch.py` established the one measured property that is
arche's and not Splink's: with nothing to learn from, Splink merges 368 of 400
known-different schools that share a name, because a batch of 1,200 records
cannot know `COMMUNITY PRIMARY SCHOOL` is common; arche reads a shipped
population table and merges 2 at every size.

Plan §7f proposes Splink as the default scorer with arche as the layer that
declares, guards, decides and remembers. That proposal has a hole if the
small-batch property can only live in arche's own engine. So: **hand the
population to Splink.** Splink can take a pre-computed term-frequency table
(`register_term_frequency_lookup`) in place of the one it would count from the
batch. If a population-derived table makes the filler-0 false merges collapse,
the property is a *data* property that any Fellegi-Sunter scorer can consume,
and the architecture holds. If it does not, `basic` stays below the size
floor for a reason.

What the population is, stated plainly
--------------------------------------
Splink's term-frequency adjustment is per *value* of the compared column --
the whole school name -- where arche's shipped table is per *token*. A
token table cannot be registered as a value lookup without inventing a
combination rule, so this run builds the value-level table from the full
Nigerian school register itself: 107,670 names, the population the labelled
records were drawn from. That is the most favourable population possible,
and the result is an upper bound on what a shipped table could do for
Splink, not a measurement of arche's table inside it. The gap between the
two is a build task (a value-level table per domain), not an open question.

Three arms at each filler size, labels identical throughout:

    splink / batch TF        Splink as it ships: frequencies counted from the batch
    splink / population TF   the same model, frequencies read from the register
    arche                    the shipped place pack and its shipped table
"""
from __future__ import annotations

import csv
import json
import sys
import warnings
from collections import Counter
from pathlib import Path

warnings.filterwarnings("ignore")

_HERE = Path(__file__).resolve().parent
_REPO = _HERE.parents[1]
sys.path.insert(0, str(_REPO / "packages" / "arche-core" / "src"))
sys.path.insert(0, str(_HERE))

OUT = _HERE / "bench_population_tf_into_splink_result.json"
FILLERS = (0, 500, 2000)


def population_tf() -> "pd.DataFrame":  # noqa: F821
    """`name -> tf_name` over the whole register, in Splink's lookup shape."""
    import pandas as pd

    import bench_splink_nigeria as base

    counts: Counter[str] = Counter()
    for r in csv.DictReader(base.CSV_PATH.open(encoding="utf-8")):
        n = (r["name"] or "").strip()
        if n:
            counts[n] += 1
    total = sum(counts.values())
    return pd.DataFrame({"name": list(counts), "tf_name": [c / total for c in counts.values()]})


def run_splink(records: list[dict], *, tf_lookup=None):
    """`bench_splink_nigeria.run_splink`, with an optional registered lookup."""
    import pandas as pd
    from splink import DuckDBAPI, Linker

    import bench_splink_nigeria as base

    df = pd.DataFrame([{"unique_id": r["id"], "name": r["name"],
                        "lat": r["lat"], "lon": r["lon"]} for r in records])
    linker = Linker(df, base.splink_settings(), db_api=DuckDBAPI())
    if tf_lookup is not None:
        # Registered before training so EM and prediction both read it. This
        # is the whole intervention: everything else about the model is the
        # published recipe.
        linker.table_management.register_term_frequency_lookup(tf_lookup, "name")
    base.splink_train(linker)
    out = linker.inference.predict(
        threshold_match_probability=0.01).as_pandas_dataframe()
    return [(base.norm(p), s) for p, s in zip(
        zip(out["unique_id_l"], out["unique_id_r"], strict=False),
        out["match_probability"], strict=False)]


def main() -> int:
    import bench_population_vs_batch as pvb
    import bench_splink_nigeria as base

    negatives, positives, others = base.build()
    lookup = population_tf()
    print(f"  {len(negatives)} observed negatives, {len(positives)} constructed positives")
    print(f"  population lookup: {len(lookup):,} distinct names from the full register\n",
          flush=True)

    results = {}
    print(f"  {'filler':>8}{'records':>9}{'arm':>26}{'true':>7}{'false':>7}", flush=True)
    print("  " + "-" * 57, flush=True)
    for filler in FILLERS:
        records, neg_ids, pos_ids = base._records(negatives, positives, others[:filler])
        row = {}
        for label, kwargs in (("splink / batch TF", {}),
                              ("splink / population TF", {"tf_lookup": lookup})):
            try:
                scored = pvb.score(run_splink(records, **kwargs), neg_ids, pos_ids,
                                   is_arche=False)
                row[label] = scored
            except Exception as exc:                       # noqa: BLE001
                row[label] = {"error": f"{type(exc).__name__}: {exc}"}
                print(f"    {label} failed at filler={filler}: {exc}", flush=True)
        try:
            row["arche"] = pvb.score(base.run_arche(records), neg_ids, pos_ids, is_arche=True)
        except Exception as exc:                           # noqa: BLE001
            row["arche"] = {"error": f"{type(exc).__name__}: {exc}"}

        for label, block in row.items():
            for thr, counts in block.items():
                if isinstance(counts, dict) and "true" in counts:
                    print(f"  {filler:>8}{len(records):>9}{label + ' ' + thr:>26}"
                          f"{counts['true']:>7}{counts['false']:>7}", flush=True)
        print(flush=True)
        results[str(filler)] = {"records": len(records), **row}

    OUT.write_text(json.dumps({
        "benchmark": "the population table as a Splink input",
        "question": "does registering a population-derived term-frequency lookup "
                    "give Splink the small-batch property arche's shipped table gives arche?",
        "population": "value-level frequencies over the full Nigerian school register "
                      "(107,670 names) -- the most favourable population, an upper bound",
        "labels": "identical at every filler size (bench_splink_nigeria)",
        "seed": base.SEED,
        "results": results,
    }, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"  wrote {OUT.relative_to(_REPO)}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
