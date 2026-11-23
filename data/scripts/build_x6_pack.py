#!/usr/bin/env python
"""Build the X6 test pack in Oyo, held out of X6's training.

The X4 construction (``build_x4_pack.py``) applied to Oyo, the densest state
without labels after Lagos: 150 of the engine's Oyo review pairs, and 50
lookalike and 50 near-miss pairs, all blind.

    uv run --package arche-core python data/scripts/evaluate_facility_master.py \\
        --state Oyo --output ~/.cache/arche/x6/Oyo
    uv run --package arche-core python data/scripts/build_x6_pack.py \\
        --edges ~/.cache/arche/x6/Oyo/candidate_edges.csv --work ~/.cache/arche/x6
    uv run --package arche-core python data/scripts/build_facility_adjudication_pack.py \\
        --sample Oyo=~/.cache/arche/x6/Oyo/adjudication_sample.csv \\
        --output data/review_packs/nigeria_facilities_oyo_x6_2026-11-22
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("build_x4_pack", HERE / "build_x4_pack.py")
x4p = importlib.util.module_from_spec(_spec)
sys.modules["build_x4_pack"] = x4p
_spec.loader.exec_module(x4p)

if __name__ == "__main__":
    x4p.STATE, x4p.BAND, x4p.STRESS = "Oyo", 150, 50
    x4p.main()
