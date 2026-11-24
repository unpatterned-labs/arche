#!/usr/bin/env python
"""Build a place list from the provider lists themselves (the dev half only).

As uk_address_matcher learns its common end tokens from Companies House, this
counts how often each closing part of an address ("..., OKITIPUPA") appears
across the four provider lists, and keeps the frequent ones as town names. It
picks up the local spellings GeoNames lacks ("PORTHARCOURT", "OKOKOMAIKO").

Only the **dev half** is read (``build_parser_dev_pack.half_of``). The reserve
half is where G0c is drawn from, and its closing parts are G0c's city
answers; the G0b test pack is excluded too. The result is for
``arche.addr.places.register_places`` and is not shipped with arche.

    uv run --with pdfplumber --with openpyxl python data/scripts/build_places_from_lists.py
"""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import re
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, HERE / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


dev = _load("build_parser_dev_pack")
g0b = dev.g0b
OUT = g0b.G0B / "places_from_lists.json"
MIN_COUNT = 2
# A closing part that is not a town: a road, a landmark, a box, a unit.
NOT_TOWN = re.compile(
    r"(?i)\d|\b(?:road|rd|street|st|avenue|ave|close|crescent|lane|drive|way|highway|"
    r"expressway|bypass|junction|roundabout|round about|near|opposite|opp|behind|off|"
    r"beside|along|adj|next to|by|box|p\.?m\.?b|floor|room|suite|shop|plaza|mall|house|"
    r"building|complex|centre|center|hospital|clinic|market|station|stop|church|"
    r"mosque|school|hotel|bank|state|county|region|nigeria|kenya|ghana)\b")


def closing_part(cell: str) -> str | None:
    parts = [p.strip(" .-") for p in re.split(r"[,\n]", cell) if p.strip(" .-")]
    if len(parts) < 2:
        return None
    last = parts[-1]
    if NOT_TOWN.search(last) or not 1 <= len(last.split()) <= 3:
        return None
    return last


def main() -> None:
    with (g0b.PACK / "addresses.csv").open(encoding="utf-8") as fh:
        test = {dev.fold(r["address"]) for r in csv.DictReader(fh)}
    sources = [g0b.clearline(), g0b.cic(), g0b.nafuu(), g0b.equity()]
    counts: Counter = Counter()
    spelling: dict[str, Counter] = {}
    cells = 0
    for cellset in sources:
        for cell in sorted(set(cellset)):
            if dev.fold(cell) in test or dev.half_of(cell) != "dev":
                continue
            cells += 1
            last = closing_part(cell)
            if last is None:
                continue
            key = dev.fold(last)
            counts[key] += 1
            spelling.setdefault(key, Counter())[last] += 1
    rows = []
    for key, n in counts.most_common():
        if n < MIN_COUNT:
            break
        rank = 5 if n >= 20 else 4 if n >= 5 else 3
        rows.append([spelling[key].most_common(1)[0][0], "", "town", rank, n])
    OUT.write_text(json.dumps({
        "built_from": "dev half of the four G0b provider lists, minus the G0b test pack",
        "min_count": MIN_COUNT,
        "cells_read": cells,
        "test_pack_sha256": "sha256:" + hashlib.sha256(
            (g0b.PACK / "addresses.csv").read_bytes()).hexdigest(),
        "columns": ["name", "country", "kind", "rank", "count"],
        "rows": rows}, indent=1) + "\n", encoding="utf-8")
    print(cells, "cells;", len(rows), "names; top:", [r[0] for r in rows[:25]])


if __name__ == "__main__":
    main()
