# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Does a shipped population table beat batch-estimated term frequency?

    uv run python datasets/names_dataops/bench_population_vs_batch.py

This is the load-bearing claim behind arche's frequency tables, stated in
`docs-site/docs/concepts/probabilistic-linkage-vs-representation.md`:

    Splink estimates `u` from the data you hand it, by EM. That cannot learn
    `hospital` is common if neither input list contains many hospitals -- and in
    a two-record comparison it cannot learn anything at all. arche ships the
    frequencies.

`bench_splink_nigeria.py` cannot test it. At 13,200 records Splink's batch is a
perfectly good sample of Nigerian school names, so its term-frequency adjustment
already knows `COMMUNITY PRIMARY SCHOOL` is common -- and it wins there, 190
true of 200 at 0 false of 400 against arche's 146 and 2. A claim about small
batches is not tested by a large one.

So this varies the one thing that matters and holds everything else fixed. The
labels are identical at every size -- the same 400 observed negatives and the
same constructed positives from `bench_splink_nigeria` -- and only the FILLER
changes, which is the population Splink learns its frequencies from.

    filler 0      the labelled records alone; nothing to learn from
    filler 500    a small register
    filler 2000   a medium one
    filler 12000  the published benchmark

If the claim is right, Splink degrades as the filler shrinks and arche does not,
because arche is reading a 1.25M-record table that does not change. If Splink
holds up, the population table is not the moat and the strategy resting on it
needs revisiting.

**Read the two columns together.** An engine that merges nothing has zero false
merges and is useless; an engine that merges everything finds every positive.
Neither number means anything alone.
"""
from __future__ import annotations

import json
import sys
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")

_HERE = Path(__file__).resolve().parent
_REPO = _HERE.parents[1]
sys.path.insert(0, str(_REPO / "packages" / "arche-core" / "src"))
sys.path.insert(0, str(_HERE))

OUT = _HERE / "bench_population_vs_batch_result.json"

#: Filler sizes. The labelled records are ~1,600 on top of each of these.
FILLERS = (0, 500, 2000, 12000)


def score(pairs, neg_ids, pos_ids, *, is_arche):
    """True merges among constructed positives, false among observed negatives."""
    out = {}
    thresholds = ((0.9, 0.5) if not is_arche else (None,))
    for thr in thresholds:
        if is_arche:
            asserted = {p for p, _s, d in pairs if d == "match"}
            surfaced = {p for p, _s, _d in pairs}
            out["arche_match"] = {"true": len(asserted & pos_ids),
                                  "false": len(asserted & neg_ids)}
            out["arche_surfaced"] = {"true": len(surfaced & pos_ids),
                                     "false": len(surfaced & neg_ids)}
        else:
            asserted = {p for p, s in pairs if s >= thr}
            out[f"splink@{thr}"] = {"true": len(asserted & pos_ids),
                                    "false": len(asserted & neg_ids)}
    return out


def main() -> int:
    import bench_splink_nigeria as base

    negatives, positives, others = base.build()
    print(f"  {len(negatives)} observed negatives, "
          f"{len(positives)} constructed positives\n", flush=True)

    results = {}
    print(f"  {'filler':>8}{'records':>9}{'engine':>18}"
          f"{'true':>7}{'false':>7}", flush=True)
    print("  " + "-" * 49, flush=True)

    for filler in FILLERS:
        records, neg_ids, pos_ids = base._records(
            negatives, positives, others[:filler])
        row = {}
        try:
            row.update(score(base.run_splink(records), neg_ids, pos_ids,
                             is_arche=False))
        except Exception as exc:                       # noqa: BLE001
            row["splink_error"] = f"{type(exc).__name__}: {exc}"
            print(f"    splink failed at filler={filler}: {exc}", flush=True)
        try:
            row.update(score(base.run_arche(records), neg_ids, pos_ids,
                             is_arche=True))
        except Exception as exc:                       # noqa: BLE001
            row["arche_error"] = f"{type(exc).__name__}: {exc}"

        for engine, counts in row.items():
            if isinstance(counts, dict):
                print(f"  {filler:>8}{len(records):>9}{engine:>18}"
                      f"{counts['true']:>7}{counts['false']:>7}", flush=True)
        print(flush=True)
        results[str(filler)] = {"records": len(records), **row}

    OUT.write_text(json.dumps({
        "benchmark": "population table versus batch-estimated term frequency",
        "question": "does a shipped frequency table beat batch TF when the "
                    "batch is small?",
        "labels": "identical at every filler size; only the population Splink "
                  "learns frequencies from changes",
        "negatives": "observed; two schools in different states are not one",
        "positives": "CONSTRUCTED; one record recorded twice",
        "seed": base.SEED,
        "results": results,
    }, indent=2), encoding="utf-8")
    print(f"  wrote {OUT}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
