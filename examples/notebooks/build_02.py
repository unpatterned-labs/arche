# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0
"""Generate 02_same_person_across_documents.ipynb.

Run from the repo root:  python examples/notebooks/build_02.py
"""
from __future__ import annotations

import json
from pathlib import Path

MD, CODE = "markdown", "code"
cells: list[tuple[str, str]] = []


def md(text: str) -> None:
    cells.append((MD, text.strip("\n")))


def code(text: str) -> None:
    cells.append((CODE, text.strip("\n")))


md("""
# Is this the same person, across three documents?

**A bank statement, an invoice, and a payslip. Three cells.**

The documents are real: different issuers, different layouts, different spellings
of the same name, no shared identifier. The question is the one entity resolution
exists to answer — do these three records refer to one person?

An earlier version of this notebook took thirteen cells, and four of them were
you writing regular expressions:

```python
ORG    = re.compile(r"\\b(ltd|limited|inc|llc|plc|gmbh|corp|bank)\\b", re.I)
PERSON = re.compile(r"^[A-Z][a-z]+(?: [A-Z][a-z\\-']+){1,3}$")
EMAIL  = re.compile(r"\\b([\\w.\\-]+@[\\w.\\-]+\\.\\w+)\\b")
```

Every one of those is a worse version of something `arche` already ships. The
email pattern misses quoted locals and plus-addressing that `detect_emails`
handles. The person pattern cannot see a Yoruba or Hausa name that does not fit
`Firstname Lastname` — which is the exact failure this project exists to fix.
The organisation list is a hand-written stop list of English legal suffixes.

**If you are writing a regex against a document, that is a bug in our API.** So
the whole path now lives in the library: parse, detect, extract, assemble the
record, resolve, report.
""")

md("""
## 1. Documents in
""")

code("""
import os
os.environ.setdefault("TORCHDYNAMO_DISABLE", "1")   # Windows without MSVC

from arche import resolve_documents

report = resolve_documents("../../data/docs/*.pdf", jurisdiction="NG")
print(report.table())
""")

md("""
That is the whole thing.

`resolve_documents` composed five shipped layers and left you nothing to
reimplement: `doc.parse` read the PDFs, `Pipeline(jurisdiction="NG")` ran
statute-aware detection, `extract` found names and places, `Reference` assembled
each document into a canonical record, and `resolve.compare` judged every pair.

Two details worth seeing in the output above.

**Values are masked by default.** The table is safe to paste into an issue or a
slide without thinking about it. `report.table(reveal=True)` when you need the
real values, and that choice is explicit rather than a flag you forgot.

**Identifiers came from the detectors, names from the extractor.** That split is
deliberate: a phone number or a national ID is validated (check digits, length,
prefix), while a name is *recognised*. Guessing an ID from a pattern is how you
merge two people who share a formatting quirk.

Note the verdicts. Two pairs scored above 0.96 and still came back `review`, not
`same_entity` — the distinctive-evidence gate refusing to auto-merge on evidence
it cannot justify. A high score is not a decision.
""")

md("""
## 2. The data, as data
""")

code("""
# Every record and every verdict, as JSON — for a ticket, a fixture, or the
# next pipeline stage. `save_json(path)` writes it straight to disk.
print(report.to_json()[:1400], "...")

print("\\n\\nper-document detection census:")
for doc, census in report.detections.items():
    print(f"  {doc[:44]:46} {census}")

if report.errors:
    print("\\nskipped:", report.errors)
""")

md("""
`report.to_dicts()` gives the same thing as a list of rows if you would rather
load it into pandas. `report.records` is the raw extracted record per document,
and `report.decisions` carries each verdict with its factors and its
`decision_id` — the content hash that makes the decision citable and signable.

## 3. Why a verdict went the way it did
""")

code("""
# A decision you cannot explain is indistinguishable from a bug, so every
# verdict carries the factors that produced it.
for d in report.decisions:
    factors = ", ".join(f"{k}={v}" for k, v in sorted(d["factors"].items())
                        if isinstance(v, (int, float)))
    print(f"{d['a'][:26]:28} vs {d['b'][:26]:28} {d['identity']:12} {d['score']:.4f}")
    print(f"    {factors[:96]}")
    print(f"    decision_id {str(d['decision_id'])[:52]}")
""")

md("""
## What this establishes, and what it does not

**Establishes.** Three documents of different types, from different issuers,
with no shared identifier, resolved from file paths to signed verdicts in one
call — with no pattern-matching written by the caller.

**Does not establish.**

* **Three documents is a demonstration, not a benchmark.** For measured numbers
  on data we did not label, see the false-merge-rate and place-benchmark
  notebooks alongside this one.
* **Extraction quality bounds everything downstream.** If `extract` picks the
  wrong span for a name, resolution is judging the wrong string. The detection
  census in cell 2 is there so you can see what was found before you trust what
  was decided.
* **A scanned image yields nothing.** There is no OCR in this path; such a file
  lands in `report.errors` rather than failing the run.
* **`review` is the honest answer here.** Two of these three pairs are not
  auto-merged, and that is the gate working. Do not read the high scores as
  agreement.
""")

nb = {
    "cells": [
        {"cell_type": kind, "metadata": {},
         "source": (src + "\n").splitlines(keepends=True),
         **({"execution_count": None, "outputs": []} if kind == CODE else {})}
        for kind, src in cells
    ],
    "metadata": {
        "kernelspec": {"display_name": "Python 3", "language": "python",
                       "name": "python3"},
        "language_info": {"name": "python", "version": "3.12"},
    },
    "nbformat": 4, "nbformat_minor": 5,
}
out = Path(__file__).resolve().parent / "02_same_person_across_documents.ipynb"
out.write_text(json.dumps(nb, indent=1, ensure_ascii=False), encoding="utf-8")
n_code = sum(1 for k, _ in cells if k == CODE)
print(f"wrote {out}  ({len(cells)} cells, {n_code} code)")
