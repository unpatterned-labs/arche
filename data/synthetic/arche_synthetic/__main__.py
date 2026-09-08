# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""``python -m arche_synthetic`` — build a world without a checkout.

    python -m arche_synthetic --scale 400 --out ./worlds/ng_supplier_v0
"""

from __future__ import annotations

import argparse
from pathlib import Path

from . import SCALE, build


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="arche-synthetic",
                                 description=__doc__.splitlines()[0])
    ap.add_argument("--world-pack", default="ng_supplier_v0")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--scale", type=int, default=None,
                    help="organisations; people and places scale with it")
    ap.add_argument("--out", default="worlds/ng_supplier_v0")
    args = ap.parse_args(argv)

    scale = None
    if args.scale:
        ratio = args.scale / SCALE["organisations"]
        scale = {"organisations": args.scale,
                 "people": max(2, int(SCALE["people"] * ratio)),
                 "places": max(2, int(SCALE["places"] * ratio))}

    _, manifest = build(args.world_pack, seed=args.seed, out=Path(args.out), scale=scale)
    counts = manifest["counts"]
    print(f"  {manifest['world_id']}  seed {manifest['seed']}")
    print(f"  entities     {counts['entities']}")
    print(f"  observations {counts['observations']}")
    print(f"  differences  {counts['differences']}  {counts['difference_kinds']}")
    print(f"  written to   {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
