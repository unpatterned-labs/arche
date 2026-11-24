#!/usr/bin/env python
"""Build the dev pack for address-parser work, disjoint from G0b's test pack.

G0b scored the parsers on 250 labelled addresses; that pack is now the test set
and a parser fixed while looking at it would be tuned to it. This builds what
the work is done on instead, from the same four provider lists
(``build_g0b_pack.py``) and with the same cleaning:

1. Every distinct address cell, minus anything that folds (case and punctuation
   removed) to a G0b address, in any of the four lists.
2. The rest split in two by ``sha256(folded text)``: **dev** (even first byte)
   and **reserve** (odd). The split is on the text alone, so one address listed
   by two insurers falls on one side.
3. The dev pack is a seeded sample of the dev half. The reserve half is not
   written anywhere and is not to be looked at: the next blind pack (G0c) is
   drawn from it, after the parser work is done.

The pack goes to ``~/.cache/arche/g0b/dev/`` in the same form as G0b's
(``items.csv``, ``pack.json``, the same ``LABELLING.md``), so it opens in
Studio's Label tab and the export has the same columns. Unlike the test pack,
its labels may be read and its errors studied; only the reserve stays blind.

    uv run --with pdfplumber --with openpyxl python data/scripts/build_parser_dev_pack.py
"""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import random
import re
import shutil
from pathlib import Path

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("build_g0b_pack", HERE / "build_g0b_pack.py")
g0b = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(g0b)

DEV = g0b.G0B / "dev"
SEED = 20261124
# Heavier on NG, where every parser did worst; Nafuu's list is small.
QUOTA = {("ng", "clearline"): 90, ("ke", "cic"): 45, ("ke", "nafuu"): 15,
         ("gh", "equity"): 50}


def fold(text: str) -> str:
    return " ".join(re.sub(r"[^0-9a-z]+", " ", text.casefold()).split())


def half_of(text: str) -> str:
    return "dev" if hashlib.sha256(fold(text).encode()).digest()[0] % 2 == 0 else "reserve"


def main() -> None:
    with (g0b.PACK / "addresses.csv").open(encoding="utf-8") as fh:
        test = {fold(r["address"]) for r in csv.DictReader(fh)}
    sources = {("ng", "clearline"): g0b.clearline(), ("ke", "cic"): g0b.cic(),
               ("ke", "nafuu"): g0b.nafuu(), ("gh", "equity"): g0b.equity()}
    rng = random.Random(SEED)
    rows, counts, seen = [], {}, set()
    for (country, source), cells in sources.items():
        pool = sorted({c for c in cells if len(c.split()) >= 2})
        fresh = [c for c in pool if fold(c) not in test]
        dev = [c for c in fresh if half_of(c) == "dev"]
        take = rng.sample(dev, min(QUOTA[(country, source)], len(dev)))
        take = [c for c in take if fold(c) not in seen]
        seen |= {fold(c) for c in take}
        counts[f"{country}/{source}"] = {
            "distinct": len(pool), "in_test_pack": len(pool) - len(fresh),
            "dev_half": len(dev), "reserve_half": len(fresh) - len(dev),
            "sampled": len(take)}
        for text in take:
            rid = hashlib.sha256(f"g0b-dev\0{source}\0{text}".encode()).hexdigest()[:12]
            rows.append({"id": rid, "country": country, "source": source, "address": text})
    rng.shuffle(rows)
    assert not {fold(r["address"]) for r in rows} & test
    DEV.mkdir(parents=True, exist_ok=True)
    for name in ("addresses.csv", "items.csv"):
        with (DEV / name).open("w", encoding="utf-8", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=["id", "country", "source", "address"])
            w.writeheader()
            w.writerows(rows)
    spec = json.loads((g0b.PACK / "pack.json").read_text(encoding="utf-8"))
    spec["title"] = "Parser dev addresses (NG, KE, GH)"
    (DEV / "pack.json").write_text(json.dumps(spec, indent=1) + "\n", encoding="utf-8")
    shutil.copyfile(g0b.PACK / "LABELLING.md", DEV / "LABELLING.md")
    (DEV / "build.json").write_text(json.dumps(
        {"seed": SEED, "split": "sha256(fold(text))[0] % 2: even dev, odd reserve",
         "quota": {f"{k[0]}/{k[1]}": v for k, v in QUOTA.items()},
         "counts": counts, "rows": len(rows),
         "test_pack_sha256": "sha256:" + hashlib.sha256(
             (g0b.PACK / "addresses.csv").read_bytes()).hexdigest(),
         "labelling_guide_sha256": "sha256:" + hashlib.sha256(
             (DEV / "LABELLING.md").read_bytes()).hexdigest(),
         "raw_sha256": {p.name: "sha256:" + hashlib.sha256(p.read_bytes()).hexdigest()
                        for p in sorted(g0b.RAW.iterdir())}}, indent=2) + "\n",
        encoding="utf-8")
    print(json.dumps(counts, indent=1), len(rows))


if __name__ == "__main__":
    main()
