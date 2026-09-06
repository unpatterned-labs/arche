# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Three pieces of text, one person, and a decision you can get back by id.

Run with:

    uv run --no-sync python examples/quick_text_resolution.py

The ``regex`` extractor is deterministic and downloads nothing. The ledger is
an in-memory DuckDB here; give ``attach`` a file path to keep it.
"""

from __future__ import annotations

import arche

TEXT_1 = "Adesola Okonkwo, NIN 12345678901, address: 123 Maple Street, adesola@example.com"
TEXT_2 = "Adesola Okonkwo, NIN 12345678901, adesola@gmail.com, address: 124 Maple Street"
TEXT_3 = "Adesola E. Okonkwo, NIN 12345678901, adesola@gmail.com, address: 231 Elim Street"

ledger = arche.attach("duckdb:///:memory:")
person = dict(entity="person", jurisdiction="NG", backend="regex", store=ledger)

r12 = arche.compare(TEXT_1, TEXT_2, **person)
r13 = arche.compare(TEXT_1, TEXT_3, **person)
r23 = arche.compare(TEXT_2, TEXT_3, **person)

for label, receipt in (("1<->2", r12), ("1<->3", r13), ("2<->3", r23)):
    print(f"{label}  {receipt.identity:<12} {receipt.action:<6} {receipt.explanation}")

(entity,) = ledger.entities()
print("\none entity from three texts")
print("  shared   ", entity.shared)
print("  conflicts", entity.conflicts)

why = ledger.explain(r12.decision_id)
print("\nwhy 1<->2 is", why["identity"], "/", why["action"])
print("  supporting", why["supporting"], "| refuting", why["refuting"], "| missing", why["missing"])

replay = ledger.replay(r12.decision_id)
print("\nreplay of", r12.decision_id[:30] + "...", "reproduced =", replay.reproduced)
