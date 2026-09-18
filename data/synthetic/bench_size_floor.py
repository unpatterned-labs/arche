# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Q3: where does Splink overtake arche's own engine as the world grows?

    uv run python data/synthetic/bench_size_floor.py            # from the repo root

Plan §7f proposes Splink as the default scorer *above a size floor* and
arche's engine (`basic`: shipped frequency table, gates, no training) below
it. The floor is the record count at which a trained Fellegi-Sunter model,
learning its parameters from the batch in front of it, stops paying for the
thinness of that batch. The Nigerian register showed the mechanism -- with
nothing to learn from, Splink merges 368 of 400 known-different schools and
arche merges 2 -- but a register is one shape. This sweeps the supplier world
instead, because the floor is a property of the *world*, not of the engine,
and the supplier world is the one the chosen vertical looks like.

Same generator, same seed, same source parameters, four sizes. Two arms:

    arche/pack   the shipped organisation pack, no threshold to tune
    splink       the published recipe (`arm_splink.py`), at 0.5 -- its own
                 decision boundary -- and at 0.9

Read false merges first, then recall on the `change` stratum, because that is
the pair of numbers the vertical cares about: a supplier that moved is the
same supplier, and two suppliers that share a common name are not.

The size floor is where Splink's false merges at its own boundary fall to
arche's, and stay there. Below it, `basic`; above it, a recipe. If there is
no such point on this world, the plan's premise is wrong and this file says
so.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_REPO = _HERE.parents[1]
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_REPO / "packages" / "arche-core" / "src"))

from arche_synthetic import SCALE, Benchmark, build  # noqa: E402
from arm_splink import splink_arm  # noqa: E402
from arms import arche_pack  # noqa: E402

SCALES = (150, 400, 1000, 2000)
PACK = "ng_supplier_v0"
SEED = 42
OUT = _HERE / "bench_size_floor_result.json"


def world_for(scale: int) -> Path:
    """Build (once) and return the world directory for a scale."""
    out = _HERE / "worlds" / f"{PACK}_s{scale}" if scale != SCALE["organisations"] \
        else _HERE / "worlds" / PACK
    if not (out / "manifest.yaml").exists():
        ratio = scale / SCALE["organisations"]
        build(PACK, seed=SEED, out=out, scale={
            "organisations": scale,
            "people": max(2, int(SCALE["people"] * ratio)),
            "places": max(2, int(SCALE["places"] * ratio))})
    return out


def main() -> int:
    results = {}
    print(f"  {'scale':>6}{'records':>9}{'arm':>14}{'prec':>7}{'recall':>8}"
          f"{'change':>8}{'false':>7}{'secs':>7}", flush=True)
    print("  " + "-" * 66, flush=True)
    for scale in SCALES:
        bench = Benchmark.load(world_for(scale))
        truth_pairs = [tuple(p) for p in sorted(bench.true_pairs)]
        rows = {}

        r = bench.score(arche_pack(bench.observations, truth_pairs=truth_pairs))
        rows["arche/pack"] = r
        for thr in (0.5, 0.9):
            r = bench.score(splink_arm(bench.observations, threshold=thr))
            rows[f"splink@{thr}"] = r

        for arm, r in rows.items():
            o = r["overall"]
            claimed = o["claimed_pairs"]
            false = claimed - round(o["recall"] * o["true_pairs"])
            change = r["recall_by_stratum"].get("change", {}).get("recall", float("nan"))
            print(f"  {scale:>6}{len(bench.truth):>9}{arm:>14}{o['precision']:>7.3f}"
                  f"{o['recall']:>8.3f}{change:>8.3f}{false:>7}{r['seconds']:>7.0f}",
                  flush=True)
            r["false_merges"] = false
        print(flush=True)
        results[str(scale)] = {"records": len(bench.truth),
                               "true_pairs": len(bench.true_pairs),
                               "arms": {k: {"overall": v["overall"],
                                            "false_merges": v["false_merges"],
                                            "change": v["recall_by_stratum"].get("change"),
                                            "seconds": v["seconds"],
                                            "notes": v.get("notes", {})}
                                        for k, v in rows.items()}}

    OUT.write_text(json.dumps({
        "benchmark": "the size floor: where Splink overtakes arche's own engine",
        "world_pack": PACK, "seed": SEED, "scales": list(SCALES),
        "results": results,
    }, indent=2, default=str) + "\n", encoding="utf-8", newline="\n")
    print(f"  wrote {OUT.relative_to(_REPO)}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
