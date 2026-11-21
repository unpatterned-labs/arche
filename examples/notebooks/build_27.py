"""Build 27_four_invoices_one_person.ipynb.

    python examples/notebooks/build_27.py

The four sample invoices in data/doc_bench, end to end on one machine: parsed
by Docling, masked under the US pack, the parties on each read from layout,
the customers compared, the decisions kept in a ledger, and one combined
profile for the person they share -- with the record that cannot be settled
held, and the company at the same address kept separate.
"""

import json
from pathlib import Path

MD, CODE = "markdown", "code"
cells: list[tuple[str, str]] = []


def md(text: str) -> None:
    cells.append((MD, text.strip("\n")))


def code(text: str) -> None:
    cells.append((CODE, text.strip("\n")))


md("""
# Four invoices, one person

**A hotel folio, a flight booking, a sports-shop invoice and an advertising
invoice. Which of them are about the same customer, and what can we say about
that customer once they are joined?**

Reading a document is now mostly solved: Docling gives us the text and the
layout, and GLiNER finds the names and addresses in it. What is left is the
part people still do by hand:

1. **Who is the document for?** An invoice names several parties: the issuer
   in the letterhead, a sales contact, a second traveller. The customer is
   only one of them.
2. **Are two customers the same person?** And if the evidence is thin, the
   answer should be "hold it", not a guess.
3. **What do we know once they are joined?** We need one profile that says
   which document each value came from and where the documents disagree.

This notebook runs all of it on one machine, on the four sample PDFs in
`data/doc_bench`:

1. parse with Docling;
2. mask what the US pack lists, with a receipt per document;
3. read the parties on each document from its layout (`arche.doc.parties`);
4. compare the customers and keep the decisions in a ledger;
5. build **one combined profile** for the person they share;
6. explain the record that is held, and let a reviewer settle it;
7. keep the company at the same address **related, not merged**;
8. replay a receipt.

We **cannot verify an address** here: no address register is consulted. The
addresses are compared as text, and the profile says so.

```
pip install "arche-core[doc,detect2,ledger]"
```

**Values are masked in every output below** (`REVEAL = False`). The sample
documents are real-looking invoices, and a notebook output is easy to paste
somewhere it should not go. Set `REVEAL = True` locally to see them.
""")

code('''
import itertools, logging, time, warnings
from pathlib import Path

logging.disable(logging.WARNING)
warnings.filterwarnings("ignore")

import arche
from arche.doc import parse, parties
from arche.ledger import Ledger

REVEAL = False
BENCH = Path("../../data/doc_bench")
DOCS = {
    "invoice_10":    "hotel folio",
    "invoice_12_ak": "flight booking",
    "invoice_27":    "advertising invoice",
    "invoice_6_ak":  "sports-shop invoice",
}

def show(value, keep=4):
    """Masked unless REVEAL: the first `keep` characters, then stars."""
    if value is None:
        return "-"
    text = str(value)
    return text if REVEAL else text[:keep] + "*" * max(0, min(len(text) - keep, 16))

timings = {}
''')

md("""
## 1. Parse

Docling reads each PDF into text, keeping the layout as Markdown (tables stay
tables). This is the only slow step: about 20 s for all four on a laptop CPU,
mostly the first-run model load.
""")

code('''
t = time.perf_counter()
parsed = {name: parse(BENCH / f"{name}.pdf") for name in DOCS}
timings["parse"] = time.perf_counter() - t
for name, doc in parsed.items():
    print(f"{name:14} {DOCS[name]:20} {len(doc.text):6,} characters")
''')

md("""
## 2. Mask, with a receipt

`arche.deidentify(text, "US")` finds what the US pack lists (names, addresses,
phones, emails, account and card numbers, tax ids) and masks it. Every call
returns a decision id that pins the text's hash, the pack and the models, and
the call is written to the ledger. What a document *contains* is recorded;
the values are not.

The masked text is what you would send to anything outside this machine. The
steps below keep the original text, because matching needs the values, and the
ledger stores them under keyed record ids.
""")

code('''
ledger = Ledger(":memory:")
t = time.perf_counter()
for name, doc in parsed.items():
    masked = arche.deidentify(doc.text, "US", store=ledger)
    top = sorted(masked.by_category().items(), key=lambda kv: -kv[1])[:4]
    print(f"{name:14} {masked.count:3} spans masked  {masked.decision_id[:22]}…  "
          + ", ".join(f"{k.split('-', 2)[-1].lower()} {v}" for k, v in top))
timings["mask"] = time.perf_counter() - t
''')

md("""
## 3. Who is each document for?

`arche.doc.parties()` splits the top of a document into blocks at its role
cues and reads the name in each block with GLiNER:

* **From / To / Bill To / Ship To / Guest / Passenger** cue lines;
* the **letterhead**, meaning the lines before any cue, which is the issuer;
* an **addressee line** that opens with an honorific (`MRS …`);
* a **name alone on a line under the letterhead**, like a hotel guest.

A party's address is the address-shaped lines straight after its name. A
repeated name or an account label may sit between them; another name may not.
Nothing outside a block is given a role.

The extractor finds every name on the page; it cannot say which one the page
is addressed to. The flight booking also names a second traveller, and the
folio prints the hotel's address beside the guest.
""")

code('''
t = time.perf_counter()
found = {name: parties(doc) for name, doc in parsed.items()}
timings["parties"] = time.perf_counter() - t
print(f"{'document':14} {'role':9} {'cue':24} {'kind':12} {'name':22} {'address':22} email")
for name, ps in found.items():
    for p in ps:
        print(f"{name:14} {p.role:9} {p.cue:24} {p.kind or '-':12} {show(p.name):22} "
              f"{show(p.address):22} {show(p.email)}")
''')

md("""
What the layout says, document by document:

| document | customer | issuer |
|---|---|---|
| hotel folio | a person, **name only**: a guest line has no address | the hotel, from the letterhead |
| flight booking | a person, from the `MRS …` addressee line, with an address and, elsewhere on the page, an email carrying the surname | the airline, from the letterhead under the addressee |
| advertising invoice | **an organisation** under `To`, with an address | the ad platform under `From` |
| sports-shop invoice | a person under `Bill To`, with an address (and the same again under `Ship To`) | the shop's address (its name is in a logo, so no text) |

The issuers are never candidates for the customer. That is the point of
reading roles.
""")

md("""
## 4. Compare the customers

Three of the four customers are people. `arche.compare(..., entity="person")`
decides each pair and writes the decision to the ledger. The organisation is
a different kind of entity and is dealt with in section 7.
""")

code('''
customer = {name: next(p for p in ps if p.role == "customer") for name, ps in found.items()}
people = {name: p.as_record(id=name) for name, p in customer.items() if p.kind == "person"}

t = time.perf_counter()
receipts = {}
for a, b in itertools.combinations(people, 2):
    r = arche.compare(people[a], people[b], entity="person", store=ledger)
    receipts[(a, b)] = r
    print(f"{a:14} ↔ {b:14} {r.identity:12} {r.score:.3f}  {r.explanation}")
timings["compare"] = time.perf_counter() - t
''')

md("""
* **Flight booking ↔ sports-shop invoice: `same_entity`.** Same name, and the
  same street address written two ways (capitals and `AVE` on one, `Avenue`
  on the other).
* **Hotel folio ↔ either: `review`, held.** The name agrees fully, but a name
  is all the folio has, and the person pack does not link people on a name
  alone. Section 6 shows what would settle it.
""")

md("""
## 5. One combined profile

The ledger turns linked decisions into entities. For each field the profile
shows every value seen, the document it came from, and whether the documents
agree.
""")

code('''
name_of = {}  # record id -> document
for (a, b), r in receipts.items():
    d = ledger.decision(r.decision_id)
    name_of[d.record_a], name_of[d.record_b] = a, b

def profile(entity):
    fields = {}
    for rec in entity.records:
        for field, value in rec.attributes.items():
            if field != "id":
                fields.setdefault(field, []).append((value, name_of[rec.record_id]))
    return fields

(person,) = ledger.entities("person")
print(f"entity {person.entity_id[:20]}…  {len(person.records)} documents, "
      f"held together {person.held_together_by}\\n")
print(f"{'field':8} {'status':22} values (document)")
for field, seen in profile(person).items():
    status = ("agree" if field in person.shared
              else "differ as text" if field in person.conflicts else "one document")
    values = "; ".join(f"{show(v)} ({DOCS[d]})" for v, d in seen)
    print(f"{field:8} {status:22} {values}")
''')

md("""
`address` shows as *differ as text* because the two spellings are different
strings. They are the same street, which the match shows (address similarity
88%). That is still a comparison of text: no register has confirmed the
address exists or that this person lives there. A profile should say which
of those it is, and this one does.
""")

md("""
## 6. The held record, and a reviewer

A held pair is a **case**: the decision, what supported it, what was missing,
and the fields that *would* settle it if a document carried them.
""")

code('''
for case in ledger.cases("person"):
    a = name_of[case.decision.record_a]
    b = name_of[case.decision.record_b]
    print(f"{DOCS[a]} ↔ {DOCS[b]}: {case.decision.identity} at {case.decision.score:.3f}")
    print(f"   supporting: {case.why['supporting']}   refuting: {case.why['refuting']}")
    print(f"   would settle it: {case.would_resolve}")
''')

md("""
Nothing on the folio settles it: no address, email, phone or date of birth.
It stays held until a person decides. Say a reviewer opens the hotel
reservation and finds the same email. They record a judgement, and the ledger
re-partitions. The machine decision is unchanged; the reviewer's assertion
sits above it, with their name and reason attached.
""")

code('''
folio = next(r for r, d in name_of.items() if d == "invoice_10")
shop = next(r for r, d in name_of.items() if d == "invoice_6_ak")
before = ledger.entity_of(folio)
assertion = ledger.assert_same(folio, shop, by="reviewer:demo",
                               reason="reservation record carries the same email")
after = ledger.entity(ledger.entity_of(folio))
print("folio's entity before:", before)
print("folio's entity after: ", after.entity_id[:20] + "…", f"{len(after.records)} documents,",
      "held together", after.held_together_by)
for a in ledger.assertions(folio):
    print("assertion:", a.kind, "by", a.asserted_by, "-", a.reason)
''')

md("""
Held together **transitive**: the folio joins through the reviewer's
assertion, not through a direct match with every member. A later
`assert_different` would split it back out. `ledger.lineage(entity)` records
each step.
""")

md("""
## 7. The company at the same address: related, not merged

The advertising invoice is addressed to an **organisation** at the street
address the person uses. That is worth knowing, because it may be the
person's own business. But a company and a person are never the same entity,
so arche records the shared address and does not merge.
""")

code('''
org = customer["invoice_27"]
print(f"organisation: {show(org.name)}  at {show(org.address)}\\n")
for name, rec in people.items():
    if rec.get("address"):
        r = arche.compare({"address": rec["address"]}, {"address": org.address}, entity="place")
        print(f"   address on the {DOCS[name]:20} vs the company's: {r.identity:7} "
              f"{r.score:.3f}  {r.explanation}")
''')

md("""
The addresses agree. The company's address also carries a PO Box the
person's does not, which is enough to keep the place comparison at `review`.
The relation is shown beside the profile and never folded into it.
""")

md("""
## 8. The combined table

Every record, every document, one row per document, grouped under the entity
each belongs to:
""")

code('''
entity_of = {rec.record_id: ledger.entity_of(rec.record_id) for rec in after.records}
print(f"{'document':22} {'entity':16} {'name':20} {'address':22} {'email':20} joined by")
for rec in after.records:
    doc = name_of[rec.record_id]
    via = ("reviewer assertion" if rec.record_id == folio
           else "match: name + address")
    attrs = rec.attributes
    print(f"{DOCS[doc]:22} {after.entity_id[:14]}… {show(attrs.get('name')):20} "
          f"{show(attrs.get('address')):22} {show(attrs.get('email')):20} {via}")
print(f"{DOCS['invoice_27']:22} {'(organisation)':16} {show(org.name):20} "
      f"{show(org.address):22} {show(org.email):20} related: shares the address")
''')

md("""
## 9. A receipt replays

Every decision id is the hash of its inputs, the pack and the pins. Replaying
it recomputes the decision from the stored records and checks that the id is
the same.
""")

code('''
r = receipts[("invoice_12_ak", "invoice_6_ak")]
replay = ledger.replay(r.decision_id)
print("decision:", r.decision_id[:30] + "…", r.identity)
print("replayed: reproduced =", replay.reproduced, " changed =", replay.changed or "nothing")
print("\\ntimings (s):", {k: round(v, 2) for k, v in timings.items()})
''')

md("""
## What this shows, and what it does not

* **Roles before matching.** Taking the most confident person or address on a
  page can pick the issuer or a second traveller. Here, reading roles from
  layout gave the right customer on all four documents.
* **Thin evidence is held, not guessed.** A name alone does not join a person
  to a profile. The case says what would settle it, and a reviewer's judgement
  is recorded as theirs.
* **Related is not the same.** The company at the person's address is shown
  next to the person, never merged into them.
* **Not verified.** No address register, email check or identity document was
  consulted. The profile joins what the documents *say*.
* **Four documents.** This shows the steps on four documents. It is not an
  accuracy measurement. Layout cues are a rule set, and a document laid out
  differently will need cues it does not have yet. When no cue applies, the
  result is "unassigned", not a guess.
""")

nb = {
    "cells": [
        {"cell_type": t, "metadata": {}, "source": (s + "\n").splitlines(True),
         **({"execution_count": None, "outputs": []} if t == CODE else {})}
        for t, s in cells
    ],
    "metadata": {
        "kernelspec": {"display_name": "Python 3", "language": "python",
                       "name": "python3"},
        "language_info": {"name": "python", "version": "3.11"},
    },
    "nbformat": 4,
    "nbformat_minor": 5,
}

out = Path(__file__).resolve().parent / "27_four_invoices_one_person.ipynb"
out.write_text(json.dumps(nb, indent=1, ensure_ascii=False), encoding="utf-8")
print(f"wrote {out.name}: {len(cells)} cells "
      f"({sum(1 for t, _ in cells if t == CODE)} code)")
