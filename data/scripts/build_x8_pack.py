#!/usr/bin/env python
"""Build the X8 test pack in Anambra, held out of X8's training.

The X4 construction (``build_x4_pack.py``) applied to Anambra, at 150 pairs: 70
of the engine's Anambra review pairs and 40 lookalike and 40 near-miss pairs,
all blind.

    uv run --package arche-core python data/scripts/evaluate_facility_master.py \\
        --state Anambra --output ~/.cache/arche/x8/Anambra --sample-size 0
    uv run --package arche-core python data/scripts/build_x8_pack.py \\
        --edges ~/.cache/arche/x8/Anambra/candidate_edges.csv --work ~/.cache/arche/x8
    uv run --package arche-core python data/scripts/build_facility_adjudication_pack.py \\
        --sample Anambra=~/.cache/arche/x8/Anambra/adjudication_sample.csv \\
        --output data/review_packs/nigeria_facilities_anambra_x8_2026-11-23
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
    x4p.STATE, x4p.BAND, x4p.STRESS = "Anambra", 70, 40
    x4p.main()
