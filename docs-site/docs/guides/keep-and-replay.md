# Keep, explain, replay

By the end of this page you have a ledger on disk that holds every decision you asked arche to make, and you can look any of them up by id, ask what carried it, make it again under the engine installed now, and see which records the decisions have joined into one entity, which pairs are still open, and what evidence would close them. Everything runs offline on `arche-core[ledger]`.

```sh
pip install "arche-core[ledger]"
```

```python
import arche

ledger = arche.attach("duckdb:///:memory:")            # a path keeps it: duckdb:///people.duckdb
person = dict(entity="person", jurisdiction="NG", backend="basic", store=ledger)

t1 = "Mary Smith, NIN 12345678901, 12 Awolowo Road Ikoyi, mary.smith@example.com"
t2 = "Mary Smith, NIN 12345678901, phone 08035557890, mary.smith@example.com"
t3 = "Mary Jones, NIN 12345678901, phone 08035557890, 4 Elim Street Enugu"
t4 = "Mary Jones, NIN 12345678901, mary.jones@example.com, 4 Elim Street Enugu"

r12 = arche.compare(t1, t2, **person)
r23 = arche.compare(t2, t3, **person)
r34 = arche.compare(t3, t4, **person)
for label, r in (("1-2", r12), ("2-3", r23), ("3-4", r34)):
    print(label, r.identity, r.action, "|", r.explanation)
print(r12.decision_id[:40])
```

```text
1-2 same_entity merge | national ID match; email match; name similarity 100%
2-3 same_entity merge | national ID match; phone match; name similarity 84%
3-4 same_entity merge | national ID match; name similarity 100%
dec:sha256:fa3f36b21647c0ffdceacae9be9ca
```

`store=` on any verb records the receipt with the inputs it was made from; the receipt is identical with or without it. `reconcile`, `dedupe`, `find`, `deidentify` and `resolve_documents` take the same keyword, and a batch verb also stores the two lists it ran over, so an edge can be replayed against the exact batch it was scored in. A ledger is a DuckDB file on your disk holding the inputs as given, the receipts, and an append-only log of what was recorded, linked, merged and superseded. Nothing leaves your machine.

The four records above are one person: Mary Smith married, moved, and became Mary Jones. Only adjacent pairs were compared, a bank statement against a payslip, the payslip against a utility bill, the bill against a lease. Nothing compared the first record with the last. The rest of the page uses that chain, because it is the case a wrong answer hides best.

## Look a decision up by id

```python
past = ledger.decision(r12.decision_id)
print(past.identity, past.action, "| made with", past.call)
print(past.pins["engine"], past.pins["thresholds"])
print(ledger.record(past.record_a).text)
print(len(ledger.history(past.record_b)), "decisions touched the second record")
```

```text
same_entity merge | made with {'backend': 'basic', 'entity': 'person', 'jurisdiction': 'NG'}
arche-core@0.9.0 {'distinctive_floor': 0.75, 'match': 0.85, 'review': 0.4}
Mary Smith, NIN 12345678901, 12 Awolowo Road Ikoyi, mary.smith@example.com
2 decisions touched the second record
```

A stored decision carries the verdict, the call that made it, the pins (engine version, thresholds, comparator library) and the ids of the two records it was made over. `ledger.record(id)` gives a record back as it was given, and `ledger.history(id)` lists every decision that touched it, newest first.

## Ask what carried it

```python
why = ledger.explain(r23.decision_id)
print(why["supporting"], why["refuting"], why["missing"])
print(why["shared"])
alone = arche.compare("NIN 12345678901, 12 Awolowo Road Ikoyi", "NIN 12345678901, phone 08035557890",
                      entity="person", jurisdiction="NG", backend="basic")
print(alone.identity, alone.action, "|", alone.explanation)
```

```text
['national_id', 'phone'] ['name_tf'] ['registration_id', 'dob', 'address']
{'national_id': '12345678901', 'phone': '08035557890'}
review no_op | national ID match
```

The 2-3 decision is the one that crosses the name change. `supporting` agreed, `refuting` disagreed or vetoed, `missing` are identifying fields neither record supplied. `shared` carries the agreed values, because "the national id matched" is the claim and the id is the evidence. Here `name_tf` refutes: *Mary Smith* and *Mary Jones* share only a common given name, and a shared common name is not evidence. The id and the phone carried it. The last line is the same id with no name at all: one exact identifier and nothing beside it comes back `review`, surfaced for a person rather than merged on its own.

## Make it again

```python
replay = ledger.replay(r23.decision_id)
print(replay.reproduced, replay.changed)
real = arche.__version__
try:
    arche.__version__ = "1.0.0"                        # pretend a release happened
    drift = ledger.replay(r23.decision_id)
finally:
    arche.__version__ = real

print(drift.reproduced, drift.changed)
print(drift.then.identity, "->", drift.now["identity"])
```

```text
True {}
False {'pins.engine': {'then': 'arche-core@0.9.0', 'now': 'arche-core@1.0.0'}}
same_entity -> same_entity
```

`reproduced` is true when the engine installed now produces the same `decision_id`, byte for byte. That is stronger than "the same verdict": nothing that fed the decision has moved. When something has, `changed` names it. In the second run the verdict held and the id moved because the engine pin did. That is the intended behaviour: a decision is reproducible only against the code that made it, and the id refuses to pretend otherwise.

`replay` hands back what the decision produced this time, not only a verdict on it. A redaction gives you the masked copy again, and a place endpoint its question:

```python
note = "Patient Casey Example (NIN 12345678901) called from 0803 555 7890."
safe = arche.deidentify(note, jurisdiction="NG", backend="basic", store=ledger)

again = ledger.replay(safe.decision_id)
print(again.reproduced)
print(again.now["text"])
```

```text
True
Patient Casey Example (NIN [NIN]) called from PHONE_d3100c11.
```

Note which direction that runs in. The ledger keeps the **original**, and the masked copy is re-derived from it; you cannot go the other way, because `[NIN]` does not contain a national id. That is what makes the copy safe to hand on and the ledger the thing to keep on your own disk.

A decision made with an argument the ledger cannot store (a `Declaration` object, an `issuer_key`, a frequency table) records the argument's name, and `replay` declines with a message naming it. Such a receipt can still be re-verified from its signature; see [Compare two records](compare-two-records.md).

## What the ledger knows

A decision whose identity is `same_entity` (or `match`, for a batch) links its two records. Linked records form an entity; a later decision that links two entities merges them. `review` never links.

### The entity the decisions built

```python
(entity,) = ledger.entities()
print(len(entity.records), "records, linked by", len(entity.decision_ids), "decisions |", entity.held_together_by)
print("shared   ", entity.shared)
print("conflicts", entity.conflicts)
```

```text
4 records, linked by 3 decisions | transitive
shared    {'national_id': '12345678901', 'phone': '08035557890'}
conflicts {'email': ['mary.smith@example.com', 'mary.jones@example.com'], 'full_name': ['Mary Smith', 'Mary Jones']}
```

`shared` is every attribute the member records agree on; `conflicts` every one they do not. Nothing is averaged: the two names and the two emails stay visible on the entity, because a conflict is something to show a reviewer, not something to resolve by deleting a row. There is no golden record here that says the person is called *Mary Smith-Jones*.

`held_together_by` says `direct` when every pair of members was itself decided, or `transitive` when two records are in one entity only because each matched a third; it is the same word `dedupe()` uses for its clusters. Transitive is where a resolution system quietly merges two different things, so the ledger says which is which.

### Why the first record is the same person as the last

```python
first = ledger.decision(r12.decision_id).record_a
last = ledger.decision(r34.decision_id).record_b
for d in ledger.path(first, last):
    print(d.identity, d.action, "|", d.explanation)
```

```text
same_entity merge | national ID match; email match; name similarity 100%
same_entity merge | national ID match; phone match; name similarity 84%
same_entity merge | national ID match; name similarity 100%
```

The first and last records were never compared; three decisions make them one person, and `path` hands the chain back as decisions, each with its own receipt. It returns the shortest chain, ties broken toward the strongest evidence, so the explanation offered is the best one available. The middle hop is where the surname changed, held by the id and the phone. A reviewer who does not believe it can `replay` any hop or `explain` it field by field.

### What the entity is resting on

```python
print("weak links:", [ledger.record(r).text.split(",")[0] for r in entity.weak_links])
print("bridges:   ", len(entity.bridges), "of", len(entity.decision_ids), "decisions")
```

```text
weak links: ['Mary Smith', 'Mary Jones']
bridges:    3 of 3 decisions
```

For a transitive entity, `weak_links` names the records whose removal would split it, the second and third here, the ones that carry the name change. `bridges` names the decisions that would: all three, because a chain has no redundancy. A clique has none of either. That is the question a reviewer needs answered first. Not "how similar are these four records", which a pairwise score already said, but "where would I look first if I doubted this". The answer is the 2-3 decision, and a reviewer knows it before opening a single record.

Suppose the reviewer compares the first and last records directly.

```python
r14 = arche.compare(t1, t4, **person)
print(r14.identity, r14.action, "|", r14.explanation)

(entity,) = ledger.entities()
print(entity.held_together_by, "| weak links:", list(entity.weak_links),
      "| hops:", len(ledger.path(first, last)))
```

```text
same_entity merge | national ID match; name similarity 84%
transitive | weak links: [] | hops: 1
```

The entity is now a cycle: no record holds it alone, the path between the ends is one hop, and it is still `transitive` only because pairs 1-3 and 2-4 remain unjudged. The structure told the reviewer which comparison to make; making it changed the structure.

### The same graph, your own analysis

```python
import networkx as nx

g = ledger.graph()
print(nx.number_connected_components(g), "entity;", g.number_of_edges(), "linking decisions")
print(sorted(round(c, 2) for c in nx.degree_centrality(g).values()))
```

```text
1 entity; 4 linking decisions
[0.67, 0.67, 0.67, 0.67]
```

`ledger.graph()` is a plain `networkx.Graph`: records as nodes, linking decisions as edges, `review` never an edge, so a connected component is exactly one entity and anything beyond this page is a line of networkx.

### Cases: the pairs still open

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

*Kijani Tea Exporters* and *Kijani Coffee* share one rare word and nothing else. `would_resolve` is the organisation pack's answer, strongest first: a registration id would decide it outright; an entity class could only hold it back; an address or a coordinate would add an independent signal. `s1` and `r1` matched on their registration id and are a second entity now, an organisation beside the person.

### Observe: add evidence and decide again

Go and get one of those fields, from a registry, a reviewer, another document, and hand it back. `observe` writes the enriched record, decides every open pair about the old one again, and records which receipt each new one supersedes. The old receipts stay, marked.

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

That is the whole loop. `cases()` says what is open and what would help, you fetch it however you like, `observe` folds it in, with you or your agent holding the wheel. arche records; it does not act. A batch edge re-decided this way goes through the pack's pair engine rather than the batch it came from, and the new receipt's pins say so.

### Resolve: a new record against the entities

A new document arrives: *M. Jones*, the national id, the phone. It has never been compared with anything. `resolve` compares it with every stored record of its type, groups the decisions by entity, and decides at the entity level.

```python
res = ledger.resolve("M. Jones, NIN 12345678901, phone 08035557890", entity_type="person")
print(res.verdict, "|", res.note)
print("as a whole:", res.entity_evidence["identity"], res.entity_evidence["explanation"])
print(len(res.entity.records), "records,", res.entity.held_together_by)
```

```text
found | matched 4 member(s) of one entity
as a whole: same_entity national ID match; phone match
5 records, transitive
```

`entity_evidence` is the part a single pair cannot give: the record compared with the entity as a whole, every attribute its members do not dispute. The id one member holds and the phone another holds both count, and the two surnames, being disputed, are left out rather than picked.

Now a record that looks like Mary and is not: her name, her old email, a different national id.

```python
res = ledger.resolve({"full_name": "Mary Smith", "national_id": "99999999999",
                      "email": "mary.smith@example.com"}, entity_type="person")
print(res.verdict, "|", res.note)
print(res.conflicts)
print(len(ledger.entities("person")), "entity;", len(ledger.entities("person")[0].records), "records")
```

```text
conflict | the nearest entity agrees on national_id and this record contradicts it; nothing was linked.
{'national_id': {'entity': '12345678901', 'record': '99999999999'}}
1 entity; 5 records
```

A name and an email agreeing would carry a pairwise `review`; the entity knows more. Every one of its records agrees on the national id, and this one contradicts it. Identifier fields (`kind: id` in the pack) are the only ones that block: emails and addresses differ across Mary's own records, and blocking on those would undo the point of the exercise. The pairwise decisions are recorded as the engine issued them and opened as cases; the link is withheld and an event says why.

The other verdicts: `review` when nothing matched outright and the nearest pairs are opened as cases; `ambiguous` when members of two entities matched, because the newcomer may be the bridge that shows two entities are one, or one match is wrong, and either way the ledger does not merge entities on a newcomer's say-so; `not_found` when nothing came close.

## What was written, and where

```python
from collections import Counter

print(Counter(event.kind for event in ledger.events()))
```

```text
Counter({'decision_recorded': 13, 'record_linked': 3, 'run_recorded': 3, 'entity_created': 2, 'observation_recorded': 1, 'decision_superseded': 1, 'link_withheld': 1})
```

Every recording, link, merge, observation and supersession is a line in an append-only log. Nothing on this page deleted or edited a row.

The ledger keeps the inputs as given, the text or the record, because replay needs them. It is your file, on your disk, like `decisions.json` beside your PDFs. Do not point it at a shared drive you would not put the source records on. A mode that keeps only hashed ids is planned; ask if you need it.

## Read data from the same file

A DuckDB file that holds the ledger can hold, or read, the tables being resolved. `read()` returns rows as dicts, ready for a verb: a table in the file, a `.csv`, `.parquet` or `.json` path, or a `SELECT`.

<!-- docs-test: fragment -->
```python
ledger = arche.attach("duckdb:///suppliers.duckdb")
result = arche.reconcile(ledger.read("suppliers"), ledger.read("registry.parquet"),
                         entity="organisation", store=ledger)
```

The ledger's own tables are `arche_*`; everything else in the file is yours.

## From the shell or an agent

The same moves, from a shell. `--store FILE.duckdb` names the ledger, or set `ARCHE_LEDGER` once; values are masked unless you pass `--reveal`; every command takes `--json`.

```bash
export ARCHE_LEDGER=people.duckdb

arche compare --text "Mary Smith, NIN 12345678901, mary.smith@example.com" \
              "Mary Smith, NIN 12345678901, phone 08035557890" --record
#  same_entity  merge  national ID match; email match; name similarity 100%
#  decision_id dec:sha256:fa3f...

arche entities                       # what the decisions have linked together
arche decision dec:sha256:fa3f...    # the receipt, pins, and (masked) inputs
arche explain  dec:sha256:fa3f...    # supporting / refuting / missing
arche replay   dec:sha256:fa3f...    # reproduced: True, or what moved
arche path rec:sha256:b905... rec:sha256:8796...   # the chain of decisions that makes two records one
arche cases                          # pairs still at review, and what would settle each
arche observe rec:sha256:9f1a... --evidence '{"registration_id": "C.54321"}'
arche resolve --text "M. Jones, NIN 12345678901"   # a new record against the entities
```

`arche compare suppliers.csv registry.csv --entity organisation --store people.duckdb` records a batch the same way, and `arche resolve-documents FOLDER --store people.duckdb` does it for documents, adding a value-free entity summary to its JSON: document names and the names of the fields they agree on, never the values. From an agent, `arche mcp` exposes the same eight as tools (`decision`, `explain`, `replay`, `entities`, `path`, `cases`, `observe`, `resolve`) when the operator has set `ARCHE_LEDGER`; see [The MCP server](mcp-server.md).

## Where to read next

| You want to | Read |
|---|---|
| the fields on a receipt and what each means | [The decision](../how-it-works/the-decision.md) |
| a receipt re-verified from its signature | [Attested answers](../how-it-works/attestation.md) |
| documents in, linked entities out, kept in the same ledger | [Resolve documents](resolve-documents.md) |
| a redaction kept beside the matches | [Find and mask personal data](find-and-mask.md) |
| the ledger from an agent | [The MCP server](mcp-server.md) |
| a signed answer someone else can verify | [Attested answers](../how-it-works/attestation.md) |
