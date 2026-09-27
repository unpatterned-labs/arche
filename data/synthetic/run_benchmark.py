#!/usr/bin/env python
# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Run the arms over a generated world and write the stratified report.

    python data/synthetic/run_benchmark.py                       # all seven arms
    python data/synthetic/run_benchmark.py --fast                # the five cheap ones
    python data/synthetic/run_benchmark.py --arms exact,arche/pack
    python data/synthetic/run_benchmark.py --world worlds/small --out /tmp/r.json

Writes `benchmark_result.json` beside the world and prints the table. Every
number is measured on the machine it printed on; nothing here carries a
constant from a previous run.

All seven arms over the 150-supplier world take about three and a half minutes,
and the two ledger arms are 92% of that: they resolve each arriving record
against everything stored so far, which is n^2 comparisons by construction
rather than an inefficiency to be removed. `--fast` drops those two and returns
in about twenty seconds, which is the loop to work in; run the full set before
quoting a number.

Deliberately *not* cached between runs. A cache key can see the world's
fingerprints and the installed version, but not an edit to the engine under
`packages/`, which is exactly when a re-run matters -- and a benchmark that
serves a stale number is worse than one that is slow. Use `--arms` to re-run
one arm instead.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_REPO = _HERE.parents[1]
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_REPO / "packages" / "arche-core" / "src"))

from arche_synthetic.evaluate import Benchmark, table  # noqa: E402
from arms import ARMS  # noqa: E402

#: What `--fast` runs: every arm that finishes in seconds. The two it leaves out
#: are the incremental ones, whose cost is the n^2 comparison their design
#: implies and not an inefficiency.
FAST_ARMS = tuple(a for a in ARMS if not a.startswith("arche/ledger"))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--world", default=str(_HERE / "worlds" / "ng_supplier_v0"))
    ap.add_argument("--arms", default=None,
                    help=f"comma-separated subset of: {', '.join(ARMS)}")
    ap.add_argument("--fast", action="store_true",
                    help="skip the two ledger arms, which are 92% of the runtime")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    if args.arms and args.fast:
        print("  --fast and --arms both name a set of arms; pass one", file=sys.stderr)
        return 2
    chosen = args.arms or ",".join(FAST_ARMS if args.fast else ARMS)

    world = Path(args.world)
    bench = Benchmark.load(world)
    print(f"  world        {world.name}")
    print(f"  records      {len(bench.truth)}")
    print(f"  entities     {len(bench.by_entity)}")
    print(f"  true pairs   {len(bench.true_pairs)}")
    print(f"  strata       {', '.join(sorted(bench.by_kind))}\n")

    # arche computes its own blocking recall when given the truth; the other
    # arms have theirs computed from the candidate set they report.
    truth_pairs = [tuple(p) for p in sorted(bench.true_pairs)]

    reports = []
    for name in [a.strip() for a in chosen.split(",") if a.strip()]:
        if name not in ARMS:
            print(f"  unknown arm {name!r}; known: {', '.join(ARMS)}", file=sys.stderr)
            return 2
        print(f"  running {name} …", flush=True)
        arm = ARMS[name]
        predictions = (arm(bench.observations, truth_pairs=truth_pairs)
                       if name.startswith("arche/") else arm(bench.observations))
        reports.append(bench.score(predictions))

    print("\n" + table(reports) + "\n")
    print("  recall by cause (the column no other benchmark has):")
    causes = sorted({c for r in reports for c in r["recall_by_stratum"] if "/" in c})
    width = max((len(c) for c in causes), default=10)
    header = " " * (width + 4) + "".join(f"{r['arm'][:13]:>15}" for r in reports)
    print(header)
    for cause in causes:
        row = f"    {cause:<{width}}"
        for r in reports:
            entry = r["recall_by_stratum"].get(cause)
            row += f"{entry['recall']:>15.3f}" if entry else f"{'—':>15}"
        n = next((r['recall_by_stratum'][cause]['true_pairs']
                  for r in reports if cause in r['recall_by_stratum']), 0)
        print(f"{row}   (n={n})")

    if args.out:
        out = Path(args.out)
    elif len(reports) < len(ARMS):
        # A partial run must not replace the file that RESULTS.md quotes with a
        # subset of it. Silently overwriting seven arms with four is how a table
        # loses rows nobody notices are missing.
        out = world / f"benchmark_result_{len(reports)}_arms.json"
        print(f"\n  {len(reports)} of {len(ARMS)} arms, so writing {out.name} rather "
              f"than benchmark_result.json")
    else:
        out = world / "benchmark_result.json"
    # newline="\n": the repository pins LF, and without it every run of the
    # benchmark on Windows rewrites this file entirely as a line-ending diff.
    out.write_text(json.dumps({"world": world.name,
                               "records": len(bench.truth),
                               "true_pairs": len(bench.true_pairs),
                               "arms": reports}, indent=2) + "\n",
                   encoding="utf-8", newline="\n")
    print(f"\n  written to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
