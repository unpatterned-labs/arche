# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""The place request against its twin: what the policy does, per rendering, and the sweep.

    uv run python data/synthetic/bench_place_request.py                    # places_v1
    uv run python data/synthetic/bench_place_request.py --world places_v0

Builds the world if it is absent, resolves every request with
`arche.resolve_place_request` against the world's master sheet, and scores
each endpoint against the truth by *what the policy did*:

    verified_right   verified, and it is the place the sentence meant
    verified_wrong   verified, and it is not -- the failure this product exists to prevent
    asked_right      one question, with the right place among the candidates shown
    asked_wrong      one question, and the right place is not among them
    refused_right    refused, and the sentence named a place the sheet does not hold
    refused_known    refused, and the sheet held it
    missed           the endpoint was never found in the sentence

Then the sweep: `verified_at` across 0.7-0.95 with the typo rule on and off,
so the policy's declared numbers can be read against a measurement.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_REPO = _HERE.parents[1]
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_REPO / "packages" / "arche-core" / "src"))

from arche_synthetic.places import OUTCOMES, PlaceBenchmark, build  # noqa: E402

WORLDS = _HERE / "worlds"


def main(argv: list[str] | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--world", default="places_v1", choices=("places_v0", "places_v1"))
    args = ap.parse_args(argv)
    world = WORLDS / args.world
    out = _HERE / f"bench_place_request_{args.world}.json"
    if not (world / "manifest.yaml").exists():
        build(seed=42, sheet=500, requests=1000, out=world,
              version=int(args.world[-1]))
    bench = PlaceBenchmark.load(world)
    print(f"  {len(bench.requests):,} requests, {len(bench.truth):,} endpoints, "
          f"{len(bench.sheet):,} sheet rows\n", flush=True)

    report = bench.score()
    print(f"  default policy: verified right {report['verified_right_rate']:.3f}, "
          f"verified WRONG {report['verified_wrong_rate']:.3f}, "
          f"questions {report['question_rate']:.3f}\n")
    short = {o: o.replace("verified_", "ver_").replace("refused_", "ref_")[:10] for o in OUTCOMES}
    print(f"  {'rendering':<19}" + "".join(f"{short[o]:>11}" for o in OUTCOMES))
    for rendering, counts in report["by_rendering"].items():
        n = sum(counts.values())
        asked = counts["asked_right"] + counts["asked_wrong"]
        top = report["asked_top_right"][rendering]
        print(f"  {rendering:<19}" + "".join(f"{counts[o] / n:>11.2f}" for o in OUTCOMES)
              + (f"   top-right {top / asked:.2f} of asked" if asked else ""))

    sweep = bench.sweep()
    print(f"\n  {'verified_at':>12}{'typo->ask':>11}{'ver_right':>11}"
          f"{'ver_wrong':>11}{'questions':>11}")
    for r in sweep:
        print(f"  {r['verified_at']:>12}{str(r['confirm_typo_matches']):>11}"
              f"{r['verified_right']:>11.3f}{r['verified_wrong']:>11.3f}{r['questions']:>11.3f}")

    out.write_text(json.dumps({"world": world.name, "default": report, "sweep": sweep},
                              indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"\n  wrote {out.relative_to(_REPO)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
