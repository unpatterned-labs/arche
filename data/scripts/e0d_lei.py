#!/usr/bin/env python
"""E0d, retrieval of organisations: E0's experiment on GLEIF LEI names.

Every LEI record carries the entity's legal name and, for about half a million
of them, names the registration authority itself asserts: previous legal
names, trading names, ASCII transliterations and the legal name in another
language. Those are real alias labels, which the facility data does not have.

Candidate lanes, admitted on development-split headroom only (TF-IDF recall@10
at most 0.92), with the preregistration written before any test query:

* ``lei_global``  a salted-hash sample of 4,000 entities outside Africa
* ``lei_africa``  every African entity with another name (2,053)

Sole proprietors are excluded (their names are people's names), as are
annulled and duplicate registrations. The extract lives in ~/.cache/arche/lei/
(GLEIF Golden Copy, CC0) with its sha256 and fetch time; it is not committed.

    python data/scripts/e0d_lei.py --headroom
    python data/scripts/e0d_lei.py --out data/er_bench/benchmark_e0d_lei_result.json
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import importlib.util
import json
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("e0b_retrieval", HERE / "e0b_retrieval.py")
e0b = importlib.util.module_from_spec(_spec)
sys.modules["e0b_retrieval"] = e0b
_spec.loader.exec_module(e0b)
e0 = e0b.e0

CACHE = Path.home() / ".cache" / "arche" / "lei"
EXTRACT = CACHE / "lei_names.jsonl.gz"
PREREG = e0.DATA / "er_bench" / "benchmark_e0d_lei_preregistration.json"
MAX_ENTITIES, MAX_NAMES = 4000, 8
AFRICA = frozenset({
    "NG", "GH", "KE", "ZA", "EG", "MA", "TN", "DZ", "CI", "SN", "CM", "UG", "TZ", "RW", "ET",
    "MU", "BW", "NA", "ZM", "ZW", "MW", "MZ", "AO", "BJ", "TG", "BF", "ML", "NE", "GA", "CG",
    "CD", "LR", "SL", "GM", "GN", "SC", "CV", "LS", "SZ", "MG", "SD", "LY", "DJ", "SO", "ER",
    "SS", "CF", "TD", "GQ", "GW", "KM", "ST", "MR", "BI",
})


def _salted(*parts: str) -> int:
    return int(hashlib.sha256("\0".join(("e0d-sample",) + parts).encode()).hexdigest()[:12], 16)


def _lane(name: str, keep) -> e0.Lane:
    entities: dict[str, list[str]] = {}
    with gzip.open(EXTRACT, "rt", encoding="utf-8") as fh:
        for line in fh:
            d = json.loads(line)
            if keep(d):
                seen: dict[str, str] = {}
                for n in [d["legal"]] + [o[0] for o in d["other"]]:
                    shown = " ".join(n.split())
                    if shown:
                        seen.setdefault(" ".join(shown.casefold().split()), shown)
                if len(seen) > 1:
                    entities[d["lei"]] = list(seen.values())
    chosen = sorted(entities, key=lambda q: _salted(name, q))[:MAX_ENTITIES]
    gallery = []
    for lei in sorted(chosen):
        variants = sorted(entities[lei], key=lambda s: _salted(name, lei, s))[:MAX_NAMES]
        gallery += [(f"{lei}#{i}", lei, s) for i, s in enumerate(sorted(variants))]
    members: dict[str, set[str]] = defaultdict(set)
    for gid, ent, _ in gallery:
        members[ent].add(gid)
    truth = {gid: members[ent] - {gid} for gid, ent, _ in gallery}
    block = [{"id": gid, "name": t} for gid, _, t in gallery]
    return e0.Lane(name, list(gallery), gallery, truth, self_join=True,
                   note=f"{len(chosen)} of {len(entities)} entities with another name, "
                        f"<= {MAX_NAMES} names each, salted-hash sample",
                   sources={EXTRACT.name: e0._sha(EXTRACT)},
                   blocker_records=(block, block))


def lane_lei_global() -> e0.Lane:
    return _lane("lei_global", lambda d: d["country"] not in AFRICA)


def lane_lei_africa() -> e0.Lane:
    return _lane("lei_africa", lambda d: d["country"] in AFRICA)


CANDIDATES = {"lei_global": lane_lei_global, "lei_africa": lane_lei_africa}


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
        raise SystemExit("LEI extract changed since the preregistration; refusing to run")
    e0.LANES.update(CANDIDATES)
    e0.MODELS = Path.home() / ".cache" / "arche" / "models" / "e0d"
    import torch

    started = time.time()
    out: dict[str, Any] = {
        "schema": "arche.e0d_lei.v1", "base": e0.BASE, "seeds": list(e0.SEEDS),
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
