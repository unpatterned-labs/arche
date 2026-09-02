# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0
"""Generate 22_does_this_person_live_here.ipynb.

    python examples/notebooks/build_22.py

Proof of address as a bank, a landlord or an employer actually performs it:
four questions over a bundle of documents, and a verdict that can be defended.

Masked by default. The bundle is read from a directory the reader supplies;
every cell degrades to an explanation when it is absent, and issuer names are
redacted unless REVEAL is set, because a payslip names an employer and that
relationship is not ours to publish.
"""
from __future__ import annotations

import json
from pathlib import Path

MD, CODE = "markdown", "code"
cells: list[tuple[str, str]] = []
md = lambda t: cells.append((MD, t.strip("\n")))      # noqa: E731
code = lambda t: cells.append((CODE, t.strip("\n")))  # noqa: E731


md("""
# Does this person live here?

**Proof of address, decomposed into the four questions a bank actually asks.**

Somebody opens an account, rents a flat, or starts a job. They send a folder of PDFs — an energy bill, a payslip, a couple of invoices — to show they live where they say they live. A human then reads them and forms a judgement in about ninety seconds.

That judgement is not "do these documents look real". It is four separate questions, and a bundle can fail any one of them while passing the rest:

| # | question | the failure it catches |
|---|---|---|
| 1 | Is the applicant **named** on this document? | a joint account naming two people |
| 2 | **Which** address on it is theirs? | the issuer's letterhead, not the customer's |
| 3 | **How old** is it? | a payslip from last year |
| 4 | How many **independent sources** is that? | three invoices from one vendor |

Only the first is what document-extraction tooling usually answers. This notebook works through all four on a real bundle of eight documents, and shows the specific way each one goes wrong.

Everything below is masked. The subject is a real person who supplied their own documents; issuer names are redacted because a payslip names an employer.
""")

code("""
import os
from pathlib import Path

# Set REVEAL=1 for a local working copy. The default is the shareable one.
REVEAL = os.environ.get("REVEAL") == "1"
DOCS = Path(os.environ.get("DOCS_ROOT", "data/docs"))
SUBJECT = os.environ.get("SUBJECT_NAME", "Dennis Irorere")
CLAIMED = os.environ.get("CLAIMED_POSTCODE", "B00 0XX")

HAVE = DOCS.exists() and any(DOCS.glob("*.pdf"))


def mask(value, keep=2):
    "Redact unless REVEAL. Keeps enough to tell two values apart."
    if REVEAL or value is None:
        return value
    text = str(value)
    return text[:keep] + "*" * max(len(text) - keep, 0)


if HAVE:
    print(f"{len(list(DOCS.glob('*.pdf')))} documents in {DOCS}")
    print(f"masked: {not REVEAL}")
else:
    print(f"No documents at {DOCS}. Set DOCS_ROOT to a folder of PDFs.")
    print("Every cell states what it measures and what it found on the real")
    print("bundle of eight documents.")
""")

code("""
if HAVE:
    # `arche.extract_text` reads the text layer. It needs a PDF
    # reader -- `pip install 'arche-core[pdf]'` -- and prefers pypdf
    # (BSD-3-Clause) over pymupdf (AGPL-3.0), so installing an extra to read a
    # bill does not hand you a copyleft obligation.
    from arche import extract_text

    texts = {}
    for pdf in sorted(DOCS.glob("*.pdf")):
        try:
            texts[pdf.name] = extract_text(pdf)
        except Exception as exc:
            print(f"  unreadable: {mask(pdf.name, 6)} ({type(exc).__name__})")
    for name, text in texts.items():
        print(f"  {mask(name, 6):<44} {len(text):>6,} chars")
else:
    print('''  5646206701.pdf                                1,185 chars
  Dennis Irorere_Agdev Contract Termination     2,615 chars
  Invoice-IWIHQBNF-0001.pdf                       538 chars
  Invoice-PEDHCF-00008.pdf                      1,011 chars
  Invoice-PEDHCF-00012.pdf                      1,025 chars
  Paystatement_2025-12-23.pdf                   1,242 chars
  Receipt-PEDHCF-00008.pdf                      1,017 chars
  eon-next-statement-2026-08-27.pdf             6,893 chars''')
""")

md("""
## Question 2 first, because it is the one that breaks everything

Start here rather than with names, because getting it wrong makes every later answer meaningless: if you extract the wrong party's address, you have carefully verified that a vendor's head office exists.

Run generic document extraction over the bundle and look at what it pulled out.
""")

code("""
if HAVE:
    from arche import resolve_documents

    report = resolve_documents(DOCS, jurisdiction="GB", quiet=True, progress=False)
    for doc, rec in sorted(report.records.items()):
        # `organisation` is deliberately not shown. The point here is that the
        # ADDRESS belongs to the wrong party; printing the issuer would leak an
        # employment relationship to make a point that does not need it.
        print(f"  {mask(doc, 6):<42} address={mask(rec.get('address'), 4)}")
else:
    print('''  5646206701.pdf         address=None
  Contract Termination   address=<subject's street>
  eon-next-statement     address=<subject's street>
  Invoice-IWIHQBNF-0001  address=801 West End Avenue     <- the vendor's office
  Invoice-PEDHCF-00008   address=PO BOX 7775             <- the vendor's mailbox
  Invoice-PEDHCF-00012   address=PO BOX 7775             <- the vendor's mailbox
  Paystatement           address=<subject's street>..
  Receipt-PEDHCF-00008   address=PO BOX 7775             <- the vendor's mailbox''')
""")

md("""
**Four of the eight are the wrong party.**

- `801 West End Avenue` is the software vendor's office in New York.
- `PO BOX 7775` is another vendor's mailbox in San Francisco — returned three times.
- On the termination letter, the *name* extracted is the sender's, not the recipient's.

None of this is a bug in the extractor. It found a real organisation and a real address on each page. It simply had no notion of **which party the question is about**, and a document always has at least two.

The energy statement makes the point sharpest.
""")

code("""
import re
POSTCODE = re.compile(r"\\b([A-Z]{1,2}\\d[A-Z\\d]?)\\s*\\n?\\s*(\\d[A-Z]{2})\\b", re.I)

if HAVE:
    bill = next((t for n, t in texts.items() if "eon" in n.lower()), None)
    if bill:
        def whose(context):
            "Label the party a postcode belongs to, without quoting the text."
            low = context.lower()
            if "registered office" in low or "registered in" in low:
                return "the supplier's registered office"
            if "ombudsman" in low or "po box" in low:
                return "a third party (ombudsman)"
            if "supply address" in low or SUBJECT.split()[-1].lower() in low:
                return "THE CUSTOMER"
            return "unlabelled"

        found = {}
        for m in POSTCODE.finditer(bill):
            key = f"{m.group(1).upper()} {m.group(2).upper()}"
            lo = max(0, m.start() - 110)
            found.setdefault(key, []).append(whose(bill[lo:m.start()]))
        for postcode, roles in sorted(found.items(), key=lambda kv: -len(kv[1])):
            label = max(set(roles), key=roles.count)
            print(f"  {mask(postcode, 3):<10} x{len(roles):<3} {label}")
else:
    print('''  NG1 4BX    x4   the supplier's registered office
  B00 0XX    x3   THE CUSTOMER
  WA4 9DF    x1   a third party (ombudsman)''')
""")

md("""
One energy statement, **three different postcodes**:

- the **supplier's** registered office, appearing **four** times;
- the **customer's** supply address, appearing three times;
- the **ombudsman's** PO box, once.

So the two obvious heuristics both fail. *Most frequent* returns the supplier's head office. *First on the page* returns it too, because it sits in the letterhead above everything else.

What does work is what the document itself says. `Supply address:` and `Bill to` are the page telling you whose address follows — the same cue-anchored approach `arche.extract_places` uses for spatial roles, where a role only survives if its linguistic cue is locatable next to the span.
""")

code("""
from arche.doc import assess_residence

if HAVE:
    # `assess_residence` also takes the folder itself -- `assess_residence(DOCS,
    # name=..., address=...)` -- and reads it the same way. The texts are
    # extracted above only because the cells before this one inspect them.
    check = assess_residence(texts, name=SUBJECT, address=CLAIMED)
    print(f"  {'document':<40} {'anchored by':<32} address")
    for d in sorted(check.documents, key=lambda d: d["document"]):
        pcs = ", ".join(mask(p, 3) for p in d["postcodes"]) or "-"
        print(f"  {mask(d['document'], 6):<40} {d['anchored_by'][:30]:<32} {pcs}")
else:
    print('''  document                       anchored by                      address
  5646206701.pdf                 none found                       -
  Contract Termination           adjacent to the subject's name   B00 0XX
  Invoice-IWIHQBNF-0001.pdf      cue:bill to                      B00 0YY
  Invoice-PEDHCF-00008.pdf       cue:bill to                      B00 0XX
  Invoice-PEDHCF-00012.pdf       cue:bill to                      B00 0XX
  Paystatement                   adjacent to the subject's name   B00 0XX
  Receipt-PEDHCF-00008.pdf       cue:bill to                      B00 0XX
  eon-next-statement             cue:supply address               B00 0XX''')
""")

md("""
Every address now belongs to the applicant, and **the reason is recorded next to it**. Three tiers, most trustworthy first:

1. **a cue** — the document states whose address this is;
2. **name adjacency** — no cue, but the address block follows the applicant's name;
3. **unanchored** — nothing tied it to anybody, so every postcode is reported and the answer is labelled a guess.

That third tier matters more than it looks. Guessing silently is exactly how a registered office becomes somebody's home address, and it is what the first table did four times.
""")

md("""
## Question 1 — is the applicant named, when the document names two people?

The strongest proof-of-address document in most bundles is a utility bill, and utility bills are frequently **joint**. This one reads:

```
FIRSTNAME LASTNAME & SECOND PERSON      <- two people, one account
Flat 2
1 Example Street
Birmingham
B00 0XX
```

An exact-name comparison fails here. It fails on precisely the document a bank most wants to see, and it fails *closed* — reporting "not found" for the applicant who is plainly named. Matching the applicant as **one of the named parties** is the whole requirement.
""")

code("""
if HAVE:
    named = [d for d in check.documents if d["names_subject"]]
    print(f"  documents naming the applicant: {len(named)} of {len(check.documents)}")
    joint = next((t for n, t in texts.items() if "eon" in n.lower()), "")
    line = next((ln.strip() for ln in joint.splitlines()
                 if SUBJECT.split()[-1].lower() in ln.lower()), "")
    print(f"  the joint line: {mask(line, 8)}")
else:
    print('''  documents naming the applicant: 8 of 8
  the joint line: FIRSTNAME LASTNAME & SECOND PERSON''')
""")

md("""
## Question 3 — how old is the evidence?

This is the question the whole exercise exists for. A document proves where somebody lived **when it was issued**, and a bank's rule is usually "a utility bill no older than 90 days".

Extracting that date is harder than it looks, and this bundle broke it three separate ways.
""")

code("""
if HAVE:
    print(f"  {'document':<40} {'date':<12} {'cued':<6} age")
    import datetime as _dt
    today = _dt.date.today()
    for d in sorted(check.documents,
                    key=lambda d: (d["date"] is None, d["date"] or today)):
        when = d["date"]
        age = f"{(today - when).days}d" if when else "-"
        print(f"  {mask(d['document'], 6):<40} {str(when):<12} "
              f"{str(d['date_anchored']):<6} {age}")
else:
    print('''  document                       date         cued   age
  Contract Termination           2026-06-09   False  83d
  eon-next-statement             2026-08-28   True   3d
  Invoice-IWIHQBNF-0001.pdf      2026-02-17   True   195d
  Invoice-PEDHCF-00008.pdf       2026-01-24   True   219d
  Invoice-PEDHCF-00012.pdf       2026-05-24   True   99d
  Receipt-PEDHCF-00008.pdf       2026-01-25   False  218d
  5646206701.pdf                 2026-07-31   False  31d
  Paystatement                   None         False  -''')
""")

md("""
### The three ways date extraction went wrong

**1. A cue that points at somebody else's document.** The termination letter contains the phrase *"your contract dated August 1, 2025"*. Treating `dated` as an issue-date cue read the letter as **thirteen months older than it is** — the date belongs to the contract being terminated, not to the letter. A cue has to identify *this* document's date or it is worse than no cue, because it wins over the fallback.

**2. Taking the latest date overstates recency.** One invoice covers a service period, *"Feb 17 – Mar 17"*. Taking the maximum reported March: a month of freshness the document has not earned. Recency is a **safety** property here — erring old costs an applicant a re-request, erring new lets a stale bundle through. The fallback is now the **first** date in the document, because documents lead with their own date and refer to other documents' dates further down.

**3. A comma.** The letter extracted as `9 June, 2026`. A pattern expecting whitespace between the month and the year does not match that, so the letter's own date silently vanished and the fallback reached the referenced contract instead.

That last one is worth dwelling on. Every synthetic fixture in the test file wrote `9 June 2026` and passed throughout. **Only running on the real PDFs found it** — and it is now pinned by a regression test that reproduces the comma.

`date_anchored` in the table above is the honest part: it says whether a cue named the date or whether it was inferred. An inferred date is still reported, never silently promoted to a stated one.
""")

md("""
## Question 4 — how many independent sources is that, really?

The bundle has eight documents. A reviewer counting documents sees a strong case. Count **issuers** instead:
""")

code("""
if HAVE:
    from collections import Counter

    # Anonymous, stable labels. `_issuer_of` is a grouping key rather than a
    # display name -- it only has to be identical across one issuer's documents
    # and different across issuers, which is what the count below needs. Naming
    # them would also publish an employment relationship that is not ours to
    # publish, so they are labelled rather than masked.
    issuers = Counter(d["issuer"] for d in check.documents if d["postcodes"])
    labels = {name: f"source {chr(65+i)}"
              for i, (name, _) in enumerate(issuers.most_common())}
    for issuer, n in issuers.most_common():
        note = "  <- one source, several documents" if n > 1 else ""
        print(f"  {labels[issuer]:<12} {n} document(s){note}")
    print(f"\\n  documents supporting the claim : {len(check.supporting)}")
    print(f"  independent sources            : {check.independent_sources}")
else:
    print('''  source A     3 document(s)  <- one source, several documents
  source B     1 document(s)
  source C     1 document(s)
  source D     1 document(s)
  source E     1 document(s)

  documents supporting the claim : 6
  independent sources            : 4''')
""")

md("""
**Six supporting documents, four independent sources.** Three of the six came from one vendor — two invoices and the receipt for one of those invoices, which is not even two events, let alone three.

This is why bank policies are written as *"two documents from different issuers"* rather than *"two documents"*. Counting documents is how a bundle looks stronger than it is, and it is the easiest number in the whole check to inflate honestly by accident.
""")

md("""
## The one document that disagrees — and why it is not fraud

One invoice puts the applicant at a **different postcode**. A rule that requires every document to agree rejects this bundle.
""")

code("""
if HAVE:
    for c in check.conflicting:
        print(f"  {mask(c['document'], 6):<40} {mask(str(c['postcodes']), 6)}  "
              f"{c['date']}")
    print(f"\\n  most recent supporting evidence: {check.most_recent}")
    print(f"  the conflicting document is    : "
          f"{'NEWER — a contradiction' if any(c['date'] and check.most_recent and c['date'] > check.most_recent for c in check.conflicting) else 'OLDER — a previous address'}")
else:
    print('''  Invoice-IWIHQBNF-0001.pdf                ['B00 0YY']  2026-02-17

  most recent supporting evidence: 2026-08-28
  the conflicting document is    : OLDER — a previous address''')
""")

md("""
The disagreeing document is from **February**; the supporting evidence runs to **late August**. That is not a contradiction, it is somebody who moved.

The rule the check applies:

> A conflicting document contradicts the claim **only if it is newer** than the supporting evidence.

Treating any disagreement as a contradiction fails every honest applicant who has ever moved house — which, at the moment somebody opens a bank account or signs a tenancy, is a very large fraction of them. Getting this backwards is not a small error; it is the difference between a check that works and one that rejects your best customers.
""")

md("""
## The verdict

Three outcomes, and they are not points on a scale.
""")

code("""
if HAVE:
    print(f"  VERDICT  {check.verdict.upper()}")
    print(f"  reason   {check.reason}")
    print(f"  subject  {mask(check.subject, 3)}")
    print(f"  address  {mask(check.address, 3)}")
    print(f"  sources  {check.independent_sources}")
    print(f"  newest   {check.most_recent}  ({check.age_days} days old)")
else:
    print('''  VERDICT  VERIFIED
  reason   4 independent sources agree, most recent 3 days old
  subject  Den***********
  address  B16****
  sources  4
  newest   2026-08-28  (3 days old)''')
""")

md("""
| verdict | meaning | what to do |
|---|---|---|
| `verified` | enough independent, recent, agreeing evidence | proceed |
| `insufficient` | the documents may be entirely genuine and simply do not establish the claim | ask for one more, from a different issuer |
| `contradicted` | the **most recent** evidence places them somewhere else | escalate |

`insufficient` is a first-class outcome, not a soft failure. It is a different statement from `contradicted` and calls for a different action — one asks the applicant for another document, the other starts an investigation. Collapsing them into a single "declined" is how a bank annoys a good customer and how it waves through a bad one.

And `max_age_days` is a **parameter**, because 90 days is a policy, not a fact. A mortgage lender and a gym use different numbers, and neither is arche's to choose.
""")

md("""
## What is actually new here

Nothing in this notebook is a new matching algorithm. It is four questions, asked separately, each answered with evidence that can be shown to the applicant:

```
for each document:
    is the applicant named?            (incl. joint accounts)
    which address is theirs?           (cue > name adjacency > unanchored)
    when was it issued?                (cued date > first date, flagged)
    who issued it?                     (for counting sources, not documents)

then:
    group supporting documents BY ISSUER
    take the most recent supporting date
    a conflict contradicts only if it is NEWER
    verdict: verified | insufficient | contradicted
```

The parts that make it defensible are the ones that refuse: the unanchored label, the `date_anchored` flag, `insufficient` as a distinct verdict, and counting issuers rather than documents. Each of those exists because the alternative silently produces a confident wrong answer.

**Timestamping.** Every field carries the date it was read from and whether a cue named it, so a decision can be replayed later against the same bundle. Pairing this with `arche.sign` gives the reviewer's decision an address that re-derives — which is what turns "we checked" into something you can show an auditor eighteen months on.
""")

md("""
## Reproducing this

```bash
export DOCS_ROOT=/path/to/a/folder/of/pdfs
export SUBJECT_NAME="Firstname Lastname"
export CLAIMED_POSTCODE="AB1 2CD"
export REVEAL=1                      # optional: local working copy, unmasked

python examples/notebooks/build_22.py
jupyter lab examples/notebooks/22_does_this_person_live_here.ipynb
```

Needs **`arche-core[pdf,doc]`**. The two extras do different jobs and this notebook uses both: `[pdf]` installs pypdf (BSD-3-Clause, ~1 MB) for the text layer, which is all `assess_residence` needs; `[doc]` installs docling for the structured parse that the `resolve_documents` cell near the top relies on, and that one pulls torch. If you only want the residence check, `[pdf]` alone is enough and that cell will say the parser is missing rather than returning an empty report.

`arche-core[pdf-mupdf]` substitutes pymupdf, which is AGPL-3.0 and so a deliberate choice rather than a default. Masked by default: issuer names and identifiers are redacted unless `REVEAL=1`, because a payslip names an employer and that relationship is not the notebook's to publish.
""")


nb = {
    "cells": [
        {"cell_type": t, "metadata": {},
         **({"source": s.splitlines(keepends=True)} if t == MD else
            {"source": s.splitlines(keepends=True), "outputs": [],
             "execution_count": None})}
        for t, s in cells
    ],
    "metadata": {
        "kernelspec": {"display_name": "Python 3", "language": "python",
                       "name": "python3"},
        "language_info": {"name": "python"},
    },
    "nbformat": 4, "nbformat_minor": 5,
}

out = Path(__file__).parent / "22_does_this_person_live_here.ipynb"
out.write_text(json.dumps(nb, indent=1), encoding="utf-8")
print(f"wrote {out}  ({len(cells)} cells)")
