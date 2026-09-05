# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Mary Smith married, moved, and became Mary Jones. Why are the first and last
records one person when they were never compared?

Run with:

    uv run --no-sync python examples/association_analysis.py

Offline; the ``regex`` extractor downloads nothing. The same walk, with the
outputs explained, is the docs page *Association analysis*.
"""

from __future__ import annotations

import arche

ledger = arche.attach("duckdb:///:memory:")
person = dict(entity="person", jurisdiction="NG", backend="regex", store=ledger)

texts = [
    "Mary Smith, NIN 12345678901, 12 Awolowo Road Ikoyi, mary.smith@example.com",
    "Mary Smith, NIN 12345678901, phone 08035557890, mary.smith@example.com",
    "Mary Jones, NIN 12345678901, phone 08035557890, 4 Elim Street Enugu",
    "Mary Jones, NIN 12345678901, mary.jones@example.com, 4 Elim Street Enugu",
]

# Only adjacent pairs are compared: statement vs payslip, payslip vs bill, bill vs lease.
receipts = [arche.compare(a, b, **person) for a, b in zip(texts, texts[1:], strict=False)]
for n, r in enumerate(receipts, start=1):
    print(f"{n}-{n + 1}  {r.identity:<12} {r.action:<6} {r.explanation}")

(entity,) = ledger.entities()
label = {rec.record_id: rec.text.split(",")[0] for rec in entity.records}
print(f"\none entity, {len(entity.records)} records, held together {entity.held_together_by}")
print("  shared   ", entity.shared)
print("  conflicts", entity.conflicts)
print("  weak links", [label[r] for r in entity.weak_links],
      "| bridges", len(entity.bridges), "of", len(entity.decision_ids), "decisions")

first = ledger.decision(receipts[0].decision_id).record_a
last = ledger.decision(receipts[-1].decision_id).record_b
print("\nwhy is the first record the same person as the last?")
for d in ledger.path(first, last):
    print(f"  {label[d.record_a]:<11} -> {label[d.record_b]:<11} "
          f"{d.identity} {d.action}  {d.explanation}")

print("\na reviewer compares first and last directly:")
r = arche.compare(texts[0], texts[-1], **person)
print(f"  {r.identity} {r.action}  {r.explanation}")
(entity,) = ledger.entities()
print(f"  now {entity.held_together_by}, weak links {list(entity.weak_links)}, "
      f"path {len(ledger.path(first, last))} hop")

print("\na fifth record, never compared with anything, against the entity:")
res = ledger.resolve("M. Jones, NIN 12345678901, phone 08035557890", entity_type="person")
print(f"  {res.verdict}  {res.note}")
print(f"  as a whole: {res.entity_evidence['identity']}  {res.entity_evidence['explanation']}")
print(f"  entity now {len(res.entity.records)} records")

print("\na record with her name and her old email, but a different national id:")
res = ledger.resolve({"full_name": "Mary Smith", "national_id": "99999999999",
                      "email": "mary.smith@example.com"}, entity_type="person")
print(f"  {res.verdict}  {res.note}")
print(f"  conflicts {res.conflicts}")
