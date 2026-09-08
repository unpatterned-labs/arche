# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""arche-synthetic — known entity worlds, imperfect observations, exact truth.

    from arche_synthetic import build

    world, manifest = build("ng_supplier_v0", seed=42, out=Path("worlds/ng"))

The object is a **benchmark, not a platform**: a world with known entities and
known state changes, observed through source systems that are stale, that
abbreviate, and that make mistakes -- with every resulting disagreement
labelled by *why it happened*. That last column is the one no published
entity-resolution benchmark has, and it is the reason to build this rather
than use SPIDER or FEBRL.

Why it exists at all: arche keeps being blocked by data licensing. ai4privacy
is academic-only and forbids derivatives; i2b2 needs a data-use agreement;
OpenSanctions is a purchase. Every one of those is somebody else's permission.
This is the path that needs nobody's.

The directory is named ``arche_synthetic`` inside the arche repo on purpose:
when it earns its own repository -- the trigger is a stratified result with
more than one matcher in it -- the move is a rename of its parent and nothing
else. Nothing here imports ``arche`` at module scope; the two uses (the name
lexicon and the identifier validators) are dev-time and local to a function.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

from . import evaluate, export, ids, lifecycle, observe, world
from .evaluate import Benchmark, Predictions

__version__ = "0.0.1"

#: Default horizon. Long enough that a supplier can move, be renamed, change a
#: director and change a bank account without the events piling into one month.
HORIZON = (date(2019, 1, 1), date(2026, 1, 1))

#: v0.1 scale. Small enough to run in CI and to audit by hand, big enough that
#: a Zipf surname draw actually collides. The detection set that moved arche's
#: numbers most was 240 rows; scale is not the thing that makes a benchmark
#: informative, and a stratum with 40 pairs in it is not a stratum.
SCALE = {"organisations": 2000, "people": 3000, "places": 1500}


def build(world_pack: str = "ng_supplier_v0", *, seed: int = 42,
          out: Path | None = None, scale: dict[str, int] | None = None,
          horizon: tuple[date, date] = HORIZON) -> tuple[world.World, dict[str, Any]]:
    """Generate a world, age it, observe it, and (with ``out``) write it.

    Deterministic: the same pack, seed, scale and horizon produce the same
    world, checked by content fingerprint rather than by file bytes.
    """
    counts = {**SCALE, **(scale or {})}
    built = world.generate(world_pack, seed, **counts)
    lifecycle.run(built, *horizon, seed=seed)
    observe.run(built, *horizon, seed=seed)
    manifest: dict[str, Any] = {}
    if out is not None:
        manifest = export.write(built, out, generator_version=__version__,
                                world_pack=world_pack,
                                notes={"horizon": [d.isoformat() for d in horizon]})
    return built, manifest


__all__ = ["HORIZON", "SCALE", "Benchmark", "Predictions", "__version__", "build",
           "evaluate", "export", "ids", "lifecycle", "observe", "world"]
