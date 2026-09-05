# Keep and replay a decision

Every verb in arche returns a receipt whose `decision_id` reproduces from the same inputs. The ledger is where a receipt goes so it can be found again: looked up by id, explained, made again, and joined with the other receipts that turn out to describe the same thing.

```bash
pip install "arche-core[ledger]"
```

A ledger is a DuckDB file on your disk. It holds the inputs as given, the receipts, and an append-only log of what was recorded, linked, merged and superseded. Nothing leaves your machine.

## Record

Pass `store=` to any verb. The receipt is identical with or without it.

```python
import arche

text1 = "Adesola Okonkwo, NIN 12345678901, address: 123 Maple Street, adesola@example.com"
text2 = "Adesola Okonkwo, NIN 12345678901, adesola@gmail.com, address: 124 Maple Street"
text3 = "Adesola E. Okonkwo, NIN 12345678901, adesola@gmail.com, address: 231 Elim Street"

ledger = arche.attach("duckdb:///:memory:")            # a path keeps it: duckdb:///people.duckdb
person = dict(entity="person", jurisdiction="NG", backend="regex", store=ledger)

r12 = arche.compare(text1, text2, **person)
r13 = arche.compare(text1, text3, **person)
r23 = arche.compare(text2, text3, **person)
```

`reconcile`, `dedupe`, `find` and `resolve_documents` take the same keyword. A batch verb also stores the two lists it ran over, so an edge can be replayed against the exact batch it was scored in.

## Look up

```python
past = ledger.decision(r12.decision_id)
print(past.identity, past.action, "| made with", past.call)
print(past.pins["engine"], past.pins["thresholds"])
print(ledger.record(past.record_a).text)
```

```text
same_entity hold | made with {'backend': 'regex', 'entity': 'person', 'jurisdiction': 'NG'}
arche-core@0.7.0a1 {'distinctive_floor': 0.75, 'match': 0.85, 'review': 0.4}
Adesola Okonkwo, NIN 12345678901, address: 123 Maple Street, adesola@example.com
```

`ledger.history(record_id)` lists every decision that touched a record, newest first.

## Explain

```python
why = ledger.explain(r12.decision_id)
print(why["supporting"], why["refuting"], why["missing"])
print(why["shared"])
```

```text
['national_id'] ['email'] ['registration_id', 'phone', 'dob', 'name', 'address']
{'national_id': '12345678901'}
```

`supporting` agreed, `refuting` disagreed or vetoed, `missing` are identifying fields neither record supplied. `shared` carries the agreed values, because "the national id matched" is the claim and the id is the evidence.

## Replay

```python
replay = ledger.replay(r12.decision_id)
print(replay.reproduced, replay.changed)
```

```text
True {}
```

`reproduced` is true when the engine installed now produces the **same `decision_id`, byte for byte**. That is stronger than "the same verdict": nothing that fed the decision has moved. When something has, `changed` names it:

```python
real = arche.__version__
try:
    arche.__version__ = "1.0.0"                        # pretend a release happened
    drift = ledger.replay(r12.decision_id)
finally:
    arche.__version__ = real

print(drift.reproduced, drift.changed)
print(drift.then.identity, "->", drift.now["identity"])
```

```text
False {'pins.engine': {'then': 'arche-core@0.7.0a1', 'now': 'arche-core@1.0.0'}}
same_entity -> same_entity
```

The verdict held; the id moved because the engine pin did. That is the intended behaviour. A decision is reproducible only against the code that made it, and the id refuses to pretend otherwise.

A decision made with an argument the ledger cannot store — a `Declaration` object, an `issuer_key`, a frequency table — records the argument's *name* and `replay` declines with a message naming it. Such a receipt can still be re-verified from its signature; see [Interpret a decision](interpret-decisions.md).

## Entities

A decision whose identity is `same_entity` (or `match`, for a batch) links its two records. Linked records form an entity; a later decision that links two entities merges them. `review` never links.

```python
(entity,) = ledger.entities()
print(len(entity.records), "records, linked by", len(entity.decision_ids), "decisions")
print("shared   ", entity.shared)
print("conflicts", entity.conflicts)
```

```text
3 records, linked by 3 decisions
shared    {'national_id': '12345678901'}
conflicts {'email': ['adesola@example.com', 'adesola@gmail.com']}
```

`shared` is every attribute the member records agree on; `conflicts` every one they do not. Nothing is averaged, and the two `hold` receipts are still `hold` — a conflict is something to show a reviewer, not something to resolve by deleting a row.

## Cases

Pairs still at `review` are the open questions. Each comes with what would settle it.

```python
suppliers = [{"id": "s1", "name": "Kijani Tea Exporters Ltd", "city": "Nairobi"}]
registry = [{"id": "r1", "name": "Kijani Tea Exporters Limited", "city": "Nairobi"},
            {"id": "r2", "name": "Kijani Coffee", "city": "Nairobi"}]
arche.reconcile(suppliers, registry, entity="organisation", store=ledger)

for case in ledger.cases():
    print(case.record_a.caller_id, "<->", case.record_b.caller_id, "|", case.decision.explanation)
    print(case.would_resolve)
```

```text
s1 <-> r2 | review: no field agreed strongly
['national_id', 'registration_id', 'phone', 'email', 'dob', 'address']
```

## Observe

Go and get one of those fields — from a registry, a reviewer, another document — and hand it back. `observe` writes the enriched record, makes every open decision about the old one again, and records which receipt each new one supersedes. The old receipts stay, marked.

```python
third = ledger.decision(r13.decision_id).record_b
fresh = ledger.observe(third, {"name": "Adesola Okonkwo"})
for d in fresh:
    print(d.identity, d.action, "supersedes", d.supersedes[:20], "| knows", sorted(d.factors))
print(ledger.decision(r13.decision_id).superseded_by is not None)
```

```text
same_entity merge supersedes dec:sha256:b1123feef | knows ['email', 'national_id']
same_entity hold supersedes dec:sha256:45848124c | knows ['email', 'national_id']
True
```

That is the whole loop — `cases()` says what is open and what would help, you fetch it however you like, `observe` folds it in — with you, or your agent, holding the wheel. arche records; it does not act.

## Events

```python
for event in ledger.events():
    print(event.kind)
```

Every recording, link, merge, observation and supersession is a line in an append-only log. Nothing above deleted or edited a row.

## What is stored, and where

The ledger keeps the inputs **as given** — the text, or the record — because replay needs them. It is your file, on your disk, like `decisions.json` beside your PDFs. Do not point it at a shared drive you would not put the source records on. A mode that keeps only hashed ids is planned; ask if you need it.

From the command line, `arche resolve-documents FOLDER --store FILE.duckdb` records every verdict the same way and adds a value-free entity summary to its JSON output: document names and the *names* of the fields they agree on, never the values.
