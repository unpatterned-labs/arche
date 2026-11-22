#!/usr/bin/env python
"""E0e, retrieval of UK companies by their previous names: E0 on Companies House.

Companies House publishes, for every live company, its current name and up to
ten previous names, each recorded when the registrar accepted the change. A
company and its old names are one entity; that is the label. Unlike GLEIF there
is only one kind of alias here, the name change, so this lane is the hardest
string problem of the set: a rebrand can keep nothing of the old name.

Candidate lane, admitted on development-split headroom only (TF-IDF recall@10
at most 0.92), with the preregistration written before any test query:

* ``ch_gb``  a salted-hash sample of 4,000 of the 533,174 companies with a
             previous name, each with its current name and up to 7 old names

The extract lives in ~/.cache/arche/companies_house/ (Basic Company Data
2026-11-01, Open Government Licence v3.0) and is not committed. Many company
names contain a person's name; the extract is used here and nowhere else.

    python data/scripts/e0e_companies_house.py --headroom
    python data/scripts/e0e_companies_house.py --out data/er_bench/benchmark_e0e_companies_house_result.json
"""  # noqa: E501

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import time
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("e0d_lei", HERE / "e0d_lei.py")
e0d = importlib.util.module_from_spec(_spec)
sys.modules["e0d_lei"] = e0d
_spec.loader.exec_module(e0d)
e0b, e0 = e0d.e0b, e0d.e0

EXTRACT = Path.home() / ".cache" / "arche" / "companies_house" / "ch_names.jsonl.gz"
PREREG = e0.DATA / "er_bench" / "benchmark_e0e_companies_house_preregistration.json"


def lane_ch_gb() -> e0.Lane:
    # e0d's builder reads its module-level EXTRACT when called; point it here.
    e0d.EXTRACT = EXTRACT
    return e0d._lane("ch_gb", lambda d: True)


CANDIDATES = {"ch_gb": lane_ch_gb}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--headroom", action="store_true", help="dev-only admission check")
    ap.add_argument("--epochs", type=int, default=2)
    ap.add_argument("--retrain", action="store_true")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    e0b.CANDIDATES.clear()
    e0b.CANDIDATES.update(CANDIDATES)
    if args.headroom:
        print(json.dumps(e0b.headroom(), indent=2, sort_keys=True))
        return
    prereg = json.loads(PREREG.read_text(encoding="utf-8"))
    if prereg["pass_rule"] != e0.PASS:
        raise SystemExit("pass rule differs from the preregistration; refusing to run")
    if prereg["data"]["extract_sha256"] != e0._sha(EXTRACT):
        raise SystemExit("extract changed since the preregistration; refusing to run")
    e0.LANES.update(CANDIDATES)
    e0.MODELS = Path.home() / ".cache" / "arche" / "models" / "e0e"
    import torch

    started = time.time()
    out: dict[str, Any] = {
        "schema": "arche.e0e_companies_house.v1", "base": e0.BASE, "seeds": list(e0.SEEDS),
        "pass_rule": e0.PASS, "preregistration_sha256": e0._sha(PREREG),
        "torch": torch.__version__, "device": "cuda" if torch.cuda.is_available() else "cpu",
        "lanes": {name: e0.run_lane(name, args) for name in prereg["lanes_admitted"]},
    }
    out["seconds"] = round(time.time() - started, 1)
    if args.out:
        Path(args.out).write_text(json.dumps(out, indent=2, sort_keys=True) + "\n",
                                  encoding="utf-8")
        print(f"\nwrote {args.out}")


if __name__ == "__main__":
    main()
