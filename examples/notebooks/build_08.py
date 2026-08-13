# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0
"""Generate 08_inside_the_one_call.ipynb.

Run from the repo root:  python examples/notebooks/build_08.py
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
# Inside the one call

**`resolve_documents()` in three cells is the product. This is what it does.**

[Notebook 02](02_same_person_across_documents.ipynb) turns three PDFs into
verdicts in one line. That is the right default, and it is also a black box. If
you are going to act on a decision — merge two customer records, pay an invoice,
file a report — you need to see what the box did.

So this notebook opens it. Same three documents, one layer per cell: parse,
detect, extract, assemble, compare, decide, attest.

Two things you will find on the way, neither of which is in the marketing:

* the pipeline confidently flags **36 Nigerian tax identification numbers** in a
  British bank statement, and every one is wrong;
* two documents score **0.9974** and are still not merged.

Both are the system working. The second one is the whole thesis.
""")

md("""
## 1. Parse — a PDF is not a string

`doc.parse` returns a structured document, not text. The distinction matters
because a bank statement *is* a table: read it as a flat string and every row
runs into the next, and the address on line 3 becomes part of the transaction on
line 4.
""")

code("""
import os, glob, logging, warnings
from collections import Counter
os.environ.setdefault("TORCHDYNAMO_DISABLE", "1")
logging.disable(logging.INFO); warnings.filterwarnings("ignore")

from arche.doc import parse

DOCS = sorted(glob.glob("../../data/docs/*.pdf"))
doc = parse(DOCS[0])
print(len(DOCS), "documents")
print()
print("available:", [a for a in dir(doc) if not a.startswith("_")])
print(f"pages {doc.num_pages}   text {len(doc.text):,} chars   tables {len(doc.tables)}")
print()
for line in doc.text.strip().splitlines()[:4]:
    print("  ", line[:78])
""")

md("""
`markdown` and `json` preserve the layout, `tables` gives the tabular regions
separately. Everything downstream reads `text`, but the structure is there when
a field only makes sense in its cell.

## 2. Detect — what counts as personal data depends on where you are

The same bytes, two jurisdictions. This is not a formatting difference: a
statute pack decides which categories exist, what tier they sit in, and which
clause to cite.
""")

code("""
from arche import Pipeline

text = doc.text
for jurisdiction in ("NG", "GDPR"):
    result = Pipeline(jurisdiction=jurisdiction).process(text)
    print(f"{jurisdiction:6} {dict(Counter(d.category for d in result.detections))}")

result = Pipeline(jurisdiction="NG").process(text)
d = result.detections[0]
print()
print("one detection carries:")
for attr in ("category", "confidence", "sensitivity_tier", "regulatory_citation",
             "identity_class", "detector"):
    print(f"  {attr:22} {getattr(d, attr, None)}")
""")

md("""
`PII-2-TIN` exists under `NG` and not under `GDPR` — a Nigerian tax
identification number is a named category in the NDPA and simply is not a thing
the GDPR pack looks for. The detection cites `NDPA-2023 s.30` because a reviewer
asking "why was this redacted?" deserves a clause, not a category name.

## 3. The 36 tax numbers that are not tax numbers

Thirty-six TIN detections in a British bank statement should bother you. Look at
what they actually matched.
""")

code("""
tins = [d for d in result.detections if d.category.endswith("TIN")]
print(f"{len(tins)} detections, {len({t.text for t in tins})} distinct values\\n")
for t in tins[:5]:
    context = text[max(0, t.start - 34):t.end + 16].replace("\\n", " ")
    print(f"  {t.text:12} conf {t.confidence:.2f}   ...{context}...")
""")

md("""
Bolt ride references. Viator transaction IDs. A direct-debit reference. Not one
is a tax number.

Three things are true at once here, and it is worth separating them:

1. **The detector is doing its job.** A Nigerian TIN is ten digits; these are ten
   digits. Without context there is no way to tell them apart on shape alone.
2. **The confidence says so.** Every one lands at **0.55**, not 0.95. The number
   is not decoration — it is the detector declining to be certain.
3. **None of them reached the record.** The record builder consumes only the
   identifier categories it maps to canonical fields, and `TIN` is not one of
   them. Thirty-six false positives, zero contamination of the match.

That third point is the design, not luck. **Detection and resolution are
separate boundaries.** A detector may over-fire — for redaction, over-firing is
the safe direction — without that noise ever becoming identity evidence. If TIN
*were* mapped, these 22 distinct values would be sitting in the record as
national identifiers, and a shared Bolt reference would look like a shared ID.

## 4. Extract — recognised, not validated

Detectors find things with *structure* — an email, a phone number, a checksum.
The extractor finds things that only a model can see: a person, an organisation,
a place. Two different jobs, deliberately not merged.
""")

code("""
from arche.extract import extract

entities = list(extract(text[:3000]))
print(dict(Counter(str(e.entity_type) for e in entities)))
print()
for e in sorted(entities, key=lambda e: -e.confidence)[:6]:
    print(f"  {str(e.entity_type):14} {e.text[:38]:40} conf {e.confidence:.3f}")
""")

md("""
The split is load-bearing. An identifier is **validated** — check digits, length,
prefix — so a match on one is strong evidence. A name is **recognised**, with a
confidence attached, so a match on one is weaker evidence that has to be weighed
against how common the name is.

Collapse the two and you get the failure this whole project exists to prevent: a
pattern-matched "identifier" that is really a formatting coincidence, treated as
proof that two people are one person.

## 5. Assemble — three documents, three records
""")

code("""
from arche import resolve_documents

report = resolve_documents("../../data/docs/*.pdf", jurisdiction="NG")
for doc_name, rec in report.records.items():
    print(f"{doc_name[:40]:42}")
    for k, v in sorted(rec.items()):
        print(f"    {k:14} {v}")
    print()
""")

md("""
Read the names.

```
Monzo statement  ->  Dennis Aibuedefe Irorere
Invoice          ->  Dennis Irorere
Payslip          ->  Dennis Irorere
```

One document carries a middle name and two do not. That is the single most
ordinary fact in identity data, and it is about to decide everything.

The addresses vary too — `3 Marina Place`, `3 Marina Place, Birmingham B16`, and
a `PO BOX` that belongs to the *issuer* rather than the person. Nobody wrote a
rule for any of this.

## 6. Compare — the factors behind each score
""")

code("""
for dec in report.decisions:
    print(f"{dec['a'][:24]:26} vs {dec['b'][:24]:26} -> {dec['score']:.4f}")
    for k, v in sorted(dec["factors"].items()):
        print(f"     {k:12} {v}")
    print()
""")

md("""
`name` is string similarity. `name_tf` is the same comparison **weighted by how
distinctive the shared tokens are** — a match on `Irorere` is worth far more than
a match on a common given name, because rarity is what identifies.

The middle name costs the Monzo pairs on both: `name` 0.8 instead of 1.0, and
`name_tf` **0.6393** instead of 1.0.

## 7. Decide — why 0.9974 is not a merge

Here is the result that matters.
""")

code("""
from arche.resolve._gate import DISTINCTIVE_FLOOR

print(f"gate floor = {DISTINCTIVE_FLOOR}\\n")
print(f"{'pair':<50} {'score':>7}  {'name_tf':>8}  verdict")
print("-" * 84)
for dec in report.decisions:
    pair = f"{dec['a'][:22]} / {dec['b'][:22]}"
    tf = dec["factors"].get("name_tf", 0.0)
    print(f"{pair:<50} {dec['score']:>7.4f}  {tf:>8.4f}  {dec['identity']}")
""")

md("""
**The highest-scoring pair in the notebook is not a match.**

`Monzo / Payslip` scores **0.9974** and returns `review`. `Invoice / Payslip`
scores **0.9903** — lower — and returns `same_entity`. The ordering by score is
the opposite of the ordering by verdict.

The reason is the gate. A merge requires a *distinctive* signal above **0.75**,
and the Monzo pairs sit at `name_tf` 0.6393 because `Dennis Aibuedefe Irorere`
and `Dennis Irorere` do not share enough rare material. The score says the
records are broadly consistent. The gate says nothing rare enough has been
agreed on to justify merging two people's financial records without a human.

**A score is not a decision.** This is the same rule that stops two
`General Hospital` records merging on an identical name, and the same one that
stops two people called `Ibrahim Musa` becoming one person. It is not tuned for
this notebook; it is the shipped constant, and lowering it to 0.70 to make this
pair merge would break that person case — measured, not assumed.

The honest reading of this run: **one confirmed match, two cases for a human**,
from three documents with no shared identifier.

## 8. Attest — a decision you can cite
""")

code("""
dec = report.decisions[0]
print("decision_id:", dec["decision_id"])
print()
print("A content hash over the evidence and the pins — no timestamp, no")
print("randomness. Anyone holding the same inputs recomputes the same id,")
print("which is what makes the verdict checkable rather than merely stored.")
print()
report.save_json("../../data/docs/report.json")
print("full report written to data/docs/report.json")
print()
print("Note it is written INSIDE data/docs/, which is gitignored. Values are")
print("masked by default, but a report derived from personal documents still")
print("names the bank, the employer and the statement dates in its filenames.")
""")

md("""
## What this establishes, and what it does not

**Establishes.** Every layer is inspectable, and the interesting behaviour is
visible rather than buried: a jurisdiction changing what counts as personal
data, a detector over-firing without contaminating the match, and a gate
refusing a 0.9974 merge for a stated reason.

**Does not establish.**

* **Three documents is a demonstration.** For measured accuracy on data we
  neither chose nor labelled, see the [false-merge-rate](06_what_is_the_false_merge_rate.ipynb)
  and [places benchmark](07_places_on_a_public_benchmark.ipynb) notebooks.
* **Extraction bounds everything downstream.** If the extractor picks the wrong
  span for a name, resolution is judging the wrong string with full confidence.
  Cell 4 exists so you look at that before trusting cell 7.
* **The `PO BOX` in the invoice record is the issuer's address, not the
  person's.** Nothing in this pipeline knows the difference, and it quietly
  weakened one comparison. Field-level provenance — *whose* address is this? —
  is not solved here.
* **36 false positives is a real false-positive rate**, on one document, from
  one detector. It was harmless because of how the record is assembled. Map TIN
  into the record and it stops being harmless.
* **No OCR.** A scanned image yields no text and lands in `report.errors`.
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
out = Path(__file__).resolve().parent / "08_inside_the_one_call.ipynb"
out.write_text(json.dumps(nb, indent=1, ensure_ascii=False), encoding="utf-8")
n_code = sum(1 for k, _ in cells if k == CODE)
print(f"wrote {out}  ({len(cells)} cells, {n_code} code)")
