#!/usr/bin/env python
"""X7: the density gate where it was meant to work, on fresh Lagos pairs.

X6 tested the gate in Oyo, where the ungated decider already coped. X7 repeats
X6 unchanged (X6's cross-encoder, which never saw Lagos; the same features; the
gate at 15 other HFR facilities within 2 km; the same pass rule) on a fresh
Lagos pack (``build_x7_pack.py``) sharing no record with X4's. The combiner is
fitted on every label read so far, now including Oyo.

    python data/scripts/x7_lagos_gate.py                      # dry run
    python data/scripts/x7_lagos_gate.py --test-labels <csv> --out <json>
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("x6_gate", HERE / "x6_gate.py")
x6 = importlib.util.module_from_spec(_spec)
sys.modules["x6_gate"] = x6
_spec.loader.exec_module(x6)

x6.PREREG = x6.DATA / "er_bench" / "benchmark_x7_lagos_gate_preregistration.json"
x6.TEST_PACK = x6.PACKS / "nigeria_facilities_lagos_x7_2026-11-23" / "adjudication_pack.csv"
x6.KINDS = Path.home() / ".cache" / "arche" / "x7" / "kinds.json"
x6.DEV = {**x6.DEV,
          "x6": x6.PACKS / "nigeria_facilities_oyo_x6_2026-11-22" / x6.x3.REVIEWED}

# Amendment 1 (2026-11-23, before any X7 label was read): three Oyo labels were
# changed after X6's result, exactly where the model erred. Development reads
# them as exported; the reviewer's file is left as is.
RESTORE = x6.PACKS / "nigeria_facilities_oyo_x6_2026-11-22" / "restore_exported.json"
_read_dev = x6.read_dev


def read_dev() -> list[dict]:
    fixes = json.loads(RESTORE.read_text(encoding="utf-8"))["outcomes"]
    rows = _read_dev()
    for r in rows:
        r["review_outcome"] = fixes.get(r["decision_id"], r["review_outcome"])
    return rows


x6.read_dev = read_dev

if __name__ == "__main__":
    if "--train" in sys.argv:
        raise SystemExit("X7 reuses X6's models; there is nothing to train")
    x6.main()
