#!/usr/bin/env python
"""Build the G0b blind address pack from published health-insurance provider lists.

Sources (downloaded by the user's decision to ``~/.cache/arche/g0b/raw``, never
committed or redistributed):

* NG: Clearline HMO hospital list (PDF table: state, town, name, address, contact)
* KE: CIC corporate provider panel 2026 (PDF table: county, ..., physical location)
* KE: Jubilee Cover Nafuu panel (PDF table: location, name, physical address)
* GH: Equity Health Insurance HSP list 2025 (xlsx: region and suburb headers, location)

Only the **address cell** is kept. Phone numbers, e-mails, names of people and
working hours are dropped, and contact text that leaks into an address cell
(``TEL:``, ``EMAIL``, ``DR.``/``MR.`` onwards, phone-like digit runs) is cut. The
provider's name is not shown to the labeller.

The pack is a seeded, stratified sample: NG 100, KE CIC 60, KE Nafuu 40, GH 50.
It is written to ``~/.cache/arche/g0b/pack/`` as ``addresses.csv``, the arms'
input (id, country, source, address), and ``labels.csv``, the same rows with
empty part columns for a person to fill in, blind: no parser output appears
anywhere in the pack.

    uv run --with pdfplumber --with openpyxl python data/scripts/build_g0b_pack.py
"""

from __future__ import annotations

import csv
import hashlib
import json
import random
import re
from pathlib import Path

G0B = Path.home() / ".cache" / "arche" / "g0b"
RAW = G0B / "raw"
PACK = G0B / "pack"
SEED = 20261123
QUOTA = {("ng", "clearline"): 100, ("ke", "cic"): 60, ("ke", "nafuu"): 40, ("gh", "equity"): 50}
PARTS = ("house_number", "road", "unit", "suburb", "city", "state", "postcode", "landmark")

_CUT = re.compile(r"(?i)\b(tel|tel no|phone|email|e-mail|mobile)\b.*$|"
                  r"\b(dr|mr|mrs|ms|prof)\.?\s+[a-z].*$")
_PHONE = re.compile(r"(\+?\d[\d \-/]{8,}\d)")


def clean(cell: str | None) -> str:
    text = " ".join((cell or "").split())
    text = _CUT.sub("", text)
    text = _PHONE.sub("", text)
    return " ".join(text.strip(" ,;:-").split())


def pdf_rows(name: str) -> list[list[str]]:
    import pdfplumber

    rows = []
    with pdfplumber.open(RAW / name) as pdf:
        for page in pdf.pages:
            for table in page.extract_tables():
                rows += [[c or "" for c in r] for r in table]
    return rows


def clearline() -> list[str]:
    return [clean(r[3]) for r in pdf_rows("clearline-hmo-hospital-list.pdf")
            if len(r) >= 4 and r[0] and r[0] != "STATE"]


def cic() -> list[str]:
    return [clean(r[4]) for r in pdf_rows("CORPORATE-PROVIDER-PANEL-2026-1.pdf")
            if len(r) >= 5 and r[3] and r[4] and r[4] != "Physical Location"]


def nafuu() -> list[str]:
    return [clean(r[2]) for r in pdf_rows("Cover-Nafuu-Panel.pdf")
            if len(r) >= 3 and r[1] and r[2] and r[2] != "PHYSICAL ADDRESS"]


def equity() -> list[str]:
    import openpyxl

    out = []
    wb = openpyxl.load_workbook(RAW / "ROSEWOOD-HSP-List-2025.xlsx", read_only=True)
    for ws in wb.worksheets:
        header = None
        for row in ws.iter_rows(values_only=True):
            cells = ["" if c is None else str(c) for c in row]
            if "Location" in cells:
                header = cells.index("Location")
                continue
            if header is not None and len(cells) > header and cells[1] and cells[header]:
                out.append(clean(cells[header]))
    return out


def main() -> None:
    sources = {("ng", "clearline"): clearline(), ("ke", "cic"): cic(),
               ("ke", "nafuu"): nafuu(), ("gh", "equity"): equity()}
    rng = random.Random(SEED)
    rows, counts = [], {}
    for (country, source), cells in sources.items():
        pool = sorted({c for c in cells if len(c.split()) >= 2})
        take = rng.sample(pool, min(QUOTA[(country, source)], len(pool)))
        counts[f"{country}/{source}"] = {"cells": len(cells), "distinct": len(pool),
                                         "sampled": len(take)}
        for text in take:
            rid = hashlib.sha256(f"g0b\0{source}\0{text}".encode()).hexdigest()[:12]
            rows.append({"id": rid, "country": country, "source": source, "address": text})
    rng.shuffle(rows)
    PACK.mkdir(parents=True, exist_ok=True)
    with (PACK / "addresses.csv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["id", "country", "source", "address"])
        w.writeheader()
        w.writerows(rows)
    with (PACK / "labels.csv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["id", "country", "address", *PARTS, "skip"])
        w.writeheader()
        w.writerows([{"id": r["id"], "country": r["country"], "address": r["address"]}
                     for r in rows])
    (PACK / "build.json").write_text(json.dumps(
        {"seed": SEED, "quota": {f"{k[0]}/{k[1]}": v for k, v in QUOTA.items()},
         "counts": counts, "rows": len(rows),
         "raw_sha256": {p.name: "sha256:" + hashlib.sha256(p.read_bytes()).hexdigest()
                        for p in sorted(RAW.iterdir())}}, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(counts))


if __name__ == "__main__":
    main()
