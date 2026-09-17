#!/usr/bin/env python
# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Build the `ng_supplier_v0` world.

    python data/synthetic/build_ng_supplier_v0.py
    python data/synthetic/build_ng_supplier_v0.py --scale 200 --out /tmp/small

Writes `worlds/ng_supplier_v0/` beside this file: `observations.parquet` (all a
matcher is given), `truth.parquet`, `differences.parquet`, `events.parquet`, a
JSON Schema per file, and `manifest.yaml`. Reproducible under the seed; the
manifest carries a content fingerprint per table so a rebuild can be checked
without comparing Parquet bytes.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_REPO = _HERE.parents[1]
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_REPO / "packages" / "arche-core" / "src"))

from arche_synthetic import SCALE, build  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--scale", type=int, default=None,
                    help="organisations; people and places scale with it")
    ap.add_argument("--out", default=None, help="output directory")
    args = ap.parse_args()

    scale = None
    if args.scale:
        ratio = args.scale / SCALE["organisations"]
        scale = {"organisations": args.scale,
                 "people": max(2, int(SCALE["people"] * ratio)),
                 "places": max(2, int(SCALE["places"] * ratio))}
    out = Path(args.out) if args.out else _HERE / "worlds" / "ng_supplier_v0"

    _, manifest = build("ng_supplier_v0", seed=args.seed, out=out, scale=scale)

    counts = manifest["counts"]
    print(f"  world       {manifest['world_id']}  seed {manifest['seed']}")
    print(f"  entities    {counts['entities']}")
    print(f"  observations{counts['observations']:>7}")
    print(f"  events      {counts['events']:>7}")
    print(f"  differences {counts['differences']:>7}  {counts['difference_kinds']}")
    print(f"  written to  {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
