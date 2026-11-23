#!/usr/bin/env python
"""Build the X7 test pack: fresh Lagos pairs, none from the X4 Lagos pack.

The X4 construction (``build_x4_pack.py``) applied to Lagos again, at 150 pairs:
80 of the engine's Lagos review pairs and 35 lookalike and 35 near-miss pairs,
all blind. Every GRID3 and HFR record in the X4 pack (and each GRID3 record's own
HFR twin) is excluded first, so no pair, facility or twin has been seen before.

    uv run --package arche-core python data/scripts/build_x7_pack.py \\
        --edges ~/.cache/arche/x4/Lagos/candidate_edges.csv --work ~/.cache/arche/x7
    uv run --package arche-core python data/scripts/build_facility_adjudication_pack.py \\
        --sample Lagos=~/.cache/arche/x7/Lagos/adjudication_sample.csv \\
        --output data/review_packs/nigeria_facilities_lagos_x7_2026-11-23
"""

from __future__ import annotations

import csv
import importlib.util
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("build_x4_pack", HERE / "build_x4_pack.py")
x4p = importlib.util.module_from_spec(_spec)
sys.modules["build_x4_pack"] = x4p
_spec.loader.exec_module(x4p)
x3p = x4p.x3p

X4_PACK = x3p.PACKS / "nigeria_facilities_lagos_x4_2026-11-22" / "adjudication_pack.csv"


def seen() -> set[str]:
    out: set[str] = set()
    with X4_PACK.open(encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            out |= {r["grid3_id"].split(":", 1)[1], r["hfr_id"].split(":", 1)[1]}
            if r.get("grid3_own_hfr_id"):
                out.add(r["grid3_own_hfr_id"].split(":", 1)[1])
    return out


def main() -> None:
    earlier = seen()
    i = sys.argv.index("--edges")
    edges, work = Path(sys.argv[i + 1]).expanduser(), Path(sys.argv[sys.argv.index("--work") + 1]).expanduser()
    (work / "Lagos").mkdir(parents=True, exist_ok=True)
    fresh = work / "Lagos" / "candidate_edges_fresh.csv"
    with edges.open(encoding="utf-8") as fh, fresh.open("w", encoding="utf-8", newline="") as out:
        rd = csv.DictReader(fh)
        w = csv.DictWriter(out, fieldnames=rd.fieldnames)
        w.writeheader()
        for r in rd:
            if {r["grid3_id"].split(":", 1)[1], r["hfr_id"].split(":", 1)[1]} & earlier:
                continue
            w.writerow(r)
    sys.argv[i + 1] = str(fresh)
    build = x3p.build
    x3p.build = lambda state, levels, used: build(state, levels, used | earlier)
    x4p.STATE, x4p.BAND, x4p.STRESS = "Lagos", 80, 35
    x4p.main()


if __name__ == "__main__":
    main()
