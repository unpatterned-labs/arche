# Association analysis

**Mary Smith married, moved, and became Mary Jones. Four records, two names, two addresses, one person — and the first and last were never compared.**

Users of a resolution system look at what was linked and ask why. Most of the time the answer is obvious: the names match, the addresses match. The cases that matter are the ones where it is not — where two records that look different are one entity because of the records *between* them. This page is that case, end to end, with the ledger's answer at each step.

```bash
pip install "arche-core[ledger]"
```

## Four records

```python
import arche

ledger = arche.attach("duckdb:///:memory:")            # a path keeps it
person = dict(entity="person", jurisdiction="NG", backend="regex", store=ledger)

t1 = "Mary Smith, NIN 12345678901, 12 Awolowo Road Ikoyi, mary.smith@example.com"
t2 = "Mary Smith, NIN 12345678901, phone 08035557890, mary.smith@example.com"
t3 = "Mary Jones, NIN 12345678901, phone 08035557890, 4 Elim Street Enugu"
t4 = "Mary Jones, NIN 12345678901, mary.jones@example.com, 4 Elim Street Enugu"

r12 = arche.compare(t1, t2, **person)
r23 = arche.compare(t2, t3, **person)
r34 = arche.compare(t3, t4, **person)
for label, r in (("1-2", r12), ("2-3", r23), ("3-4", r34)):
    print(label, r.identity, r.action, "|", r.explanation)
```

```text
1-2 same_entity merge | national ID match; email match; name similarity 100%
2-3 same_entity merge | national ID match; phone match; name similarity 84%
3-4 same_entity merge | national ID match; name similarity 100%
```

Only adjacent pairs were compared: a bank statement against a payslip, the payslip against a utility bill, the bill against a lease. Nothing compared the first record with the last. The 2–3 decision is the one that crosses the name change, and it says exactly what carried it: the national id and the phone, with the name agreeing only 84%.

## What the ledger built

```python
(entity,) = ledger.entities()
print(len(entity.records), "records |", entity.held_together_by)
print("shared   ", entity.shared)
print("conflicts", entity.conflicts)
```

```text
4 records | transitive
shared    {'national_id': '12345678901', 'phone': '08035557890'}
conflicts {'email': ['mary.smith@example.com', 'mary.jones@example.com'], 'full_name': ['Mary Smith', 'Mary Jones']}
```

One entity, and the ledger says how it is held: `transitive`. Every record agrees on the id; every record that has a phone agrees on it; and the two names and the two emails sit in `conflicts` where a reviewer can see them. Nothing was averaged into a golden record that says the person is called *Mary Smith-Jones*.

## Why is the first record the same person as the last?

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

That is the explanation facility answering the question by id. Three decisions, each with its own receipt, and the middle one is where the surname changed — held by the id and the phone. A user who does not believe it can `replay` any hop, or `explain` it field by field.

## What is this entity resting on?

```python
print("weak links:", [ledger.record(r).text.split(",")[0] for r in entity.weak_links])
print("bridges:   ", len(entity.bridges), "of", len(entity.decision_ids), "decisions")
```

```text
weak links: ['Mary Smith', 'Mary Jones']
bridges:    3 of 3 decisions
```

`weak_links` are the records whose removal would split the entity — the second and third here, the ones that carry the name change. `bridges` are the decisions that would: all three, because a chain has no redundancy. That is what association analysis is for. Not "how similar are these four records" — a pairwise score already said — but "what is this entity resting on, and where would I look first if I doubted it". The answer is the 2–3 decision, and a reviewer knows it before opening a single record.

## Verify the weak point

A reviewer compares the first and last records directly.

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

The entity is now a cycle: no record holds it alone, the path between the ends is one hop, and it is still `transitive` only because pairs 1–3 and 2–4 remain unjudged. The structure told the reviewer which comparison to make; making it changed the structure. That is the loop.

## The same graph, your analysis

`ledger.graph()` is a plain `networkx.Graph` — records as nodes, linking decisions as edges, `review` never an edge — so anything beyond this is a line of networkx:

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

From the shell, the same questions are `arche entities`, `arche path A B` and `arche decision ID`; from an agent, the `entities`, `path` and `decision` tools of `arche-mcp` when the operator has set `ARCHE_LEDGER`. See [Keep and replay a decision](keep-and-replay.md) for the rest of the ledger.

## A fifth record, against the entity

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

`entity_evidence` is the part a single pair cannot give: the record compared with the entity *as a whole* — every attribute its members do not dispute — so the id one member holds and the phone another holds both count, and the two surnames, being disputed, are left out rather than picked.

Now a record that looks like Mary and is not: her name, her old email, a different national id.

```python
res = ledger.resolve({"full_name": "Mary Smith", "national_id": "99999999999",
                      "email": "mary.smith@example.com"}, entity_type="person")
print(res.verdict, "|", res.note)
print(res.conflicts)
print(len(ledger.entities()), "entity;", len(ledger.entities()[0].records), "records")
```

```text
conflict | the nearest entity agrees on national_id and this record contradicts it; nothing was linked.
{'national_id': {'entity': '12345678901', 'record': '99999999999'}}
1 entity; 5 records
```

A name and an email agreeing would carry a pairwise `review`; the entity knows more. Every one of its records agrees on the national id, and this one contradicts it. Identifier fields — `kind: id` in the pack — are the only ones that block: emails and addresses differ across Mary's own records, and blocking on those would undo the point of the exercise. The decisions are recorded as the engine issued them; the link is withheld and an event says why.

The other verdicts: `review` when nothing matched outright and the nearest pairs are opened as cases; `ambiguous` when members of two entities matched — the newcomer may be the bridge that shows two entities are one, or one match is wrong, and either way the ledger does not merge entities on a newcomer's say-so; `not_found` when nothing came close. From the shell, `arche resolve --text "..."` or `--record '{...}'`; from an agent, the `resolve` tool.

## What this is not

It is not a golden record. The entity has no canonical name and no canonical address; it has records, the decisions that hold them together, the attributes they agree on and the ones they do not. `resolve` reads that structure. It does not write a merged Mary that someone downstream would take for a fact.
