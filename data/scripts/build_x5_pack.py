#!/usr/bin/env python
"""Build the X5 test pack in FCT, held out of X5's training.

The X4 construction (``build_x4_pack.py``) applied to FCT: the engine's FCT
review band (all of it when it holds no more than 150 pairs), and 45
lookalike and 45 near-miss pairs, all blind.

    uv run --package arche-core python data/scripts/evaluate_facility_master.py \\
        --state Fct --output ~/.cache/arche/x5/Fct --sample-size 0
    uv run --package arche-core python data/scripts/build_x5_pack.py \\
        --edges ~/.cache/arche/x5/Fct/candidate_edges.csv --work ~/.cache/arche/x5
    uv run --package arche-core python data/scripts/build_facility_adjudication_pack.py \\
        --sample FCT=~/.cache/arche/x5/Fct/adjudication_sample.csv \\
        --output data/review_packs/nigeria_facilities_fct_x5_2026-11-22
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
    x4p.STATE = "Fct"
    x4p.main()
