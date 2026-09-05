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
same_entity merge | made with {'backend': 'regex', 'entity': 'person', 'jurisdiction': 'NG'}
arche-core@0.8.0 {'distinctive_floor': 0.75, 'match': 0.85, 'review': 0.4}
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
['name', 'name_tf', 'national_id'] ['email'] ['registration_id', 'phone', 'dob', 'address']
{'name': 'Adesola Okonkwo', 'national_id': '12345678901'}
```

`supporting` agreed, `refuting` disagreed or vetoed, `missing` are identifying fields neither record supplied. `shared` carries the agreed values, because "the national id matched" is the claim and the id is the evidence. The name is there because the `regex` extractor reads it from a shipped lexicon of 13,342 African names; had it not been, the id alone would have made the action `hold` rather than `merge`.

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
False {'pins.engine': {'then': 'arche-core@0.8.0', 'now': 'arche-core@1.0.0'}}
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
conflicts {'email': ['adesola@example.com', 'adesola@gmail.com'], 'full_name': ['Adesola Okonkwo', 'Adesola E. Okonkwo']}
```

`shared` is every attribute the member records agree on; `conflicts` every one they do not. Nothing is averaged: the two email addresses and the two spellings of the name stay visible on the entity, because a conflict is something to show a reviewer, not something to resolve by deleting a row. `entity.held_together_by` says `direct` — every pair of the three was itself decided — or `transitive`, when two records are in one entity only because each matched a third; the same word `dedupe()` uses for its clusters. Transitive is where a resolution system quietly merges two different things, so the ledger says which is which, and for a transitive entity `weak_links` names the records whose removal would split it and `bridges` the decisions that would.

## Why are these two records one entity?

The question a user of any resolution system asks first, and — Talburt's example — the one a wrong answer hides best: *Mary Smith* and *Mary Jones* at different addresses, never compared, in one entity. A name changed and an address changed, and the records that connect them were compared. The explanation is that chain, and `path` hands it back as decisions, each with its own evidence.

```python
t4 = "Adesola Okonkwo, NIN 12345678901, adesola@gmail.com, phone 08035557890"
r34 = arche.compare(text3, t4, **person)          # a fourth record, linked to the third

first = ledger.decision(r12.decision_id).record_a
fourth = ledger.decision(r34.decision_id).record_b
for d in ledger.path(first, fourth):
    print(d.identity, d.action, "|", d.explanation)
```

```text
same_entity merge | national ID match; name similarity 100%
same_entity merge | national ID match; email match; name similarity 80%
same_entity merge | national ID match; email match; name similarity 80%
```

The first and fourth records were never compared; three decisions make them one person. `path` returns the shortest chain, ties broken toward the strongest evidence, so the explanation offered is the best one available. `ledger.graph()` is the same structure as a `networkx.Graph` — records as nodes, linking decisions as edges — for whatever analysis you want to run over it; a `review` is never an edge, so a connected component is exactly one entity.

For any entity, `weak_links` names the records whose removal would split it and `bridges` the decisions that would. A four-record chain has two of each; a clique has none. That is the association analysis a reviewer needs first: not "how similar are these", but "what is this entity resting on".

## Read data from the same file

A DuckDB file that holds the ledger can hold, or read, the tables being resolved. `read()` returns rows as dicts, ready for a verb: a table in the file, a `.csv` / `.parquet` / `.json` path, or a `SELECT`.

<!-- docs-test: fragment -->
```python
ledger = arche.attach("duckdb:///suppliers.duckdb")
result = arche.reconcile(ledger.read("suppliers"), ledger.read("registry.parquet"),
                         entity="organisation", store=ledger)
```

The ledger's own tables are `arche_*`; everything else in the file is yours. The `duckdb:///` scheme is where other stores will hang later; `attach` is the door to the data as well as to the decisions.

## Cases

Pairs still at `review` are the open questions. Each comes with what would settle it.

```python
suppliers = [{"id": "s1", "name": "Kijani Tea Exporters Ltd", "city": "Nairobi",
              "registration_id": "C.12345"}]
registry = [{"id": "r1", "name": "Kijani Tea Exporters Limited", "city": "Nairobi",
             "registration_id": "C.12345"},
            {"id": "r2", "name": "Kijani Coffee", "city": "Nairobi"}]
arche.reconcile(suppliers, registry, entity="organisation", store=ledger)

for case in ledger.cases():
    print(case.record_a.caller_id, "<->", case.record_b.caller_id, "|", case.decision.explanation)
    print(case.would_resolve)
    open_record = case.record_b.record_id
```

```text
s1 <-> r2 | review: no field agreed strongly
['registration_id', 'entity_class', 'address', 'lat + lon']
```

*Kijani Tea Exporters* and *Kijani Coffee* share one rare word and nothing else. The list is the organisation pack's answer, strongest first: a registration id would decide it outright; an entity class could only hold it back; an address or a coordinate would add an independent signal.

## Observe

Go and get one of those fields — from a registry, a reviewer, another document — and hand it back. `observe` writes the enriched record, decides every open pair about the old one again, and records which receipt each new one supersedes. The old receipts stay, marked.

```python
fresh = ledger.observe(open_record, {"registration_id": "C.54321"})
for d in fresh:
    print(d.identity, d.action, "| supersedes", d.supersedes[:20], "|", d.explanation)
print("open cases:", len(ledger.cases()))
```

```text
different no_op | supersedes xwd:sha256:d72db93de | no organisation evidence reached the surfacing floor of 0.55
open cases: 0
```

The registry says *Kijani Coffee* is `C.54321`; the supplier record says `C.12345`. Two exact identifiers that disagree, and the shared word is no longer enough: the pair drops below the floor and the case closes as `different`. Had the registry returned `C.12345`, it would have closed as `same_entity`.

That is the whole loop — `cases()` says what is open and what would help, you fetch it however you like, `observe` folds it in — with you, or your agent, holding the wheel. arche records; it does not act. A batch edge re-decided this way goes through the pack's pair engine rather than the batch it came from, and the new receipt's pins say so.

## Events

```python
for event in ledger.events():
    print(event.kind)
```

Every recording, link, merge, observation and supersession is a line in an append-only log. Nothing above deleted or edited a row.

## What is stored, and where

The ledger keeps the inputs **as given** — the text, or the record — because replay needs them. It is your file, on your disk, like `decisions.json` beside your PDFs. Do not point it at a shared drive you would not put the source records on. A mode that keeps only hashed ids is planned; ask if you need it.

## From the command line

The same six moves, from a shell. `--store FILE.duckdb` names the ledger, or set `ARCHE_LEDGER` once; values are masked unless you pass `--reveal`; every command takes `--json`.

```bash
export ARCHE_LEDGER=people.duckdb

arche compare --text "Adesola Okonkwo, NIN 12345678901, adesola@example.com"                      "Adesola Okonkwo, NIN 12345678901, adesola@gmail.com" --record
#  same_entity  merge  — national ID match; name similarity 100%
#  decision_id dec:sha256:e77c…

arche entities                       # what the decisions have linked together
arche decision dec:sha256:e77c…      # the receipt, pins, and (masked) inputs
arche explain  dec:sha256:e77c…      # supporting / refuting / missing
arche replay   dec:sha256:e77c…      # reproduced: True, or what moved
arche path rec:sha256:b905… rec:sha256:87966…   # the chain of decisions that makes two records one
arche resolve --text "M. Jones, NIN 12345678901"   # a new record against the entities
arche cases                          # pairs still at review, and what would settle each
arche observe rec:sha256:9f1a… --evidence '{"registration_id": "C.54321"}'
```

`arche compare suppliers.csv registry.csv --entity organisation --store people.duckdb` records a batch the same way, and `arche resolve-documents FOLDER --store people.duckdb` does it for documents, adding a value-free entity summary to its JSON: document names and the *names* of the fields they agree on, never the values.
