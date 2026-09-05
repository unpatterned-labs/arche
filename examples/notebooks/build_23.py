# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0
"""Generate 23_three_texts_one_person.ipynb.

    python examples/notebooks/build_23.py

Three pieces of text about one person, five lines of code, and a decision you
can look up and make again afterwards. No data files, no model download: the
`regex` extractor is deterministic and runs offline.
"""
from __future__ import annotations

import json
from pathlib import Path

MD, CODE = "markdown", "code"
cells: list[tuple[str, str]] = []
md = lambda t: cells.append((MD, t.strip("\n")))      # noqa: E731
code = lambda t: cells.append((CODE, t.strip("\n")))  # noqa: E731


md("""
# Three texts, one person

**Five lines to a decision. One id to get it back.**

Three fragments of text mention someone called Adesola Okonkwo. They share a national identity number. They do not agree on an email address, and none of the three addresses match. Are they the same person?

`compare` answers that for any two of them. The ledger is what notices that three answers describe *one* entity, keeps every receipt, and can make any of them again later — which is the part that matters six months on, when somebody asks why these records were joined.

Everything here runs offline in a few seconds. The `regex` extractor is deterministic and downloads nothing.
""")

code('''
import tempfile, pathlib
import arche

text1 = "Adesola Okonkwo, NIN 12345678901, address: 123 Maple Street, adesola@example.com"
text2 = "Adesola Okonkwo, NIN 12345678901, adesola@gmail.com, address: 124 Maple Street"
text3 = "Adesola E. Okonkwo, NIN 12345678901, adesola@gmail.com, address: 231 Elim Street"

# A ledger is a DuckDB file on your disk. Here it goes in a temp folder so the
# notebook leaves nothing behind; point it anywhere you want to keep it.
LEDGER = pathlib.Path(tempfile.mkdtemp()) / "okonkwo.duckdb"
ledger = arche.attach(f"duckdb:///{LEDGER}")

person = dict(entity="person", jurisdiction="NG", backend="regex", store=ledger)
r12 = arche.compare(text1, text2, **person)
r13 = arche.compare(text1, text3, **person)
r23 = arche.compare(text2, text3, **person)

for name, r in (("1↔2", r12), ("1↔3", r13), ("2↔3", r23)):
    print(f"{name}  {r.identity:<12} {r.action:<6} {r.explanation}")
''')

md("""
## Reading the three verdicts

Every pair says `same_entity`: the shared national id clears the distinctiveness gate on its own. But the **action** axis differs, and that difference is the honest part.

- 1↔2 and 1↔3 say `hold`: the id agrees, the email *disagrees*, and nothing else corroborates. arche will not recommend a merge on one identifier when another identifier conflicts.
- 2↔3 says `merge`: id **and** email agree. Two independent identifiers is corroboration.

`identity` is what arche believes. `action` is what it recommends you do about it. Keeping them separate is why a downstream system can link the records while still routing the conflict to someone.
""")

code('''
(entity,) = ledger.entities()

print("entity   ", entity.entity_id)
print("records  ", len(entity.records))
print("shared   ", entity.shared)
print("conflicts", entity.conflicts)
print("linked by", len(entity.decision_ids), "decisions")
''')

md("""
## What the ledger did with three pairwise answers

Each `compare` looked at two texts. The ledger looked at the three receipts together: 1 is linked to 2, 1 is linked to 3, 2 is linked to 3 — one connected component, so one entity, with the attributes every record agrees on (`shared`) and the ones they disagree about (`conflicts`) read off the records themselves.

Nothing was averaged and nothing was overwritten. The two `hold` receipts are still `hold`; the entity exists because the identity axis of all three said the same thing. If a later decision had said `different` about one of them it would have been recorded too, and it would not have unlinked anything on its own — a contradiction is something to show a reviewer, not something to resolve by deleting a row.

The `regex` extractor read the national id and the email. It did not read the name or the street, so those are not in `shared` or `conflicts` — they are simply absent, and `explain` says so.
""")

code('''
why = ledger.explain(r12.decision_id)
for key in ("identity", "action", "basis", "supporting", "refuting", "missing", "shared"):
    print(f"{key:<11}", why[key])
''')

md("""
## Getting a decision back, from nothing but its id

Close the ledger, open the file again as if this were a different process a month later, and ask for the receipt by id. Then ask the engine to make the same decision again.
""")

code('''
ledger.close()

later = arche.attach(f"duckdb:///{LEDGER}")
past = later.decision(r12.decision_id)
print(past.identity, past.action, "| recorded", past.recorded_at.isoformat(timespec="seconds"))
print("made with", past.call)
print("pinned to", past.pins["engine"], "/ thresholds", past.pins["thresholds"])

replay = later.replay(r12.decision_id)
print("\\nreproduced:", replay.reproduced, "| changed:", replay.changed)
''')

md("""
`reproduced=True` means the receipt the installed engine produces today carries the **same `decision_id`, byte for byte**. That id is a content hash over the rounded evidence and the pinned versions, so this is a stronger statement than "the verdict is the same": nothing that fed the decision has moved.

When something *has* moved, `replay` says what. Below, the engine version is faked to a future release so you can see the shape of that answer without waiting for one.
""")

code('''
real_version = arche.__version__
try:
    arche.__version__ = "1.0.0"           # pretend a release happened
    drift = later.replay(r12.decision_id)
finally:
    arche.__version__ = real_version

print("reproduced:", drift.reproduced)
for key, change in drift.changed.items():
    print(f"  {key}: {change['then']}  ->  {change['now']}")
print("verdict then/now:", drift.then.identity, "/", drift.now["identity"])
''')

md("""
The verdict did not change; the id did, because the engine pin did. That is the intended behaviour: a decision is only reproducible against the code that made it, and the id refuses to pretend otherwise. A replay that reported `reproduced=True` across a release would be hiding exactly the thing an auditor asks about.

## The history is append-only

Every recording, link and merge is an event. Nothing above deleted or edited a row.
""")

code('''
for event in later.events():
    refs = {k: (v[:18] + "…" if isinstance(v, str) and len(v) > 18 else v)
            for k, v in event.refs.items() if k != "records"}
    print(f"{event.kind:<20} {refs}")
''')

md("""
## Adding evidence: the loop an agent runs

Suppose a reviewer, a registry lookup, or a better extractor supplies the name for the third record. `observe` writes the enriched record, makes every open decision about it again, and records which receipt each new one **supersedes**. The old receipts stay; they are marked, not removed.
""")

code('''
third = later.decision(r13.decision_id).record_b
print("before:", later.record(third).attributes)

fresh = later.observe(third, {"name": "Adesola Okonkwo"})
for d in fresh:
    print(f"{d.identity:<12} {d.action:<6} supersedes {d.supersedes[:22]}…  now knows {sorted(d.factors)}")

print("old 1↔3 superseded:", later.decision(r13.decision_id).superseded_by is not None)
''')

md("""
That is the whole agentic loop, with the caller holding the wheel: `cases()` says what is open and what would settle it, the caller fetches it however they like, `observe` folds it in. Here every pair was already `same_entity`, so there was nothing open; the next cell shows what an open case looks like.
""")

code('''
suppliers = [{"id": "s1", "name": "Kijani Tea Exporters Ltd", "city": "Nairobi"},
             {"id": "s2", "name": "Zenith Bank Plc", "city": "Lagos"}]
registry  = [{"id": "r1", "name": "Kijani Tea Exporters Limited", "city": "Nairobi"},
             {"id": "r2", "name": "Kijani Coffee", "city": "Nairobi"}]

result = arche.reconcile(suppliers, registry, entity="organisation", store=later)
for edge in result["matches"]:
    print(f"{edge['a_id']}↔{edge['b_id']}  {edge['decision']:<7} {edge['score']:.4f}")

for case in later.cases():
    print("\\nopen:", case.record_a.caller_id, "↔", case.record_b.caller_id,
          "|", case.decision.explanation)
    print("would resolve:", case.would_resolve)
''')

md("""
`s1↔r1` matched — *Ltd* and *Limited* are the same company — and the ledger built a second entity for it. `s1↔r2` is `review`: same rare word, *Kijani*, different business. The case lists the fields that would settle it. Go and get one of them; call `observe`.

## What this was, in one paragraph

Five lines produced three verdicts. The ledger turned three verdicts into one entity without deciding anything the engine had not already decided, kept the receipts and the inputs behind them, gave any receipt back by id, made it again on request and named what had moved when something had, and folded new evidence in by superseding rather than overwriting. Every one of those is a query against a DuckDB file you own.
""")

code('''
later.close()
print("ledger file:", LEDGER, f"({LEDGER.stat().st_size // 1024} KB)")
''')


def build() -> Path:
    nb = {
        "cells": [
            {
                "cell_type": kind,
                "metadata": {},
                "source": text.splitlines(keepends=True),
                **({"outputs": [], "execution_count": None} if kind == CODE else {}),
            }
            for kind, text in cells
        ],
        "metadata": {
            "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
            "language_info": {"name": "python"},
        },
        "nbformat": 4,
        "nbformat_minor": 5,
    }
    out = Path(__file__).with_name("23_three_texts_one_person.ipynb")
    out.write_text(json.dumps(nb, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return out


if __name__ == "__main__":
    print(build())
