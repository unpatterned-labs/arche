# Quickstart

Two questions, in the order people meet them: *are these two the same?* and *which of these are the same as those?* Both run offline in seconds. Everything below is the installed package; no notebook, no repository checkout, no model download.

```bash
pip install "arche-core[ledger]"
```

## Are these two the same?

```python
import arche

text1 = "Adesola Okonkwo, NIN 12345678901, address: 123 Maple Street, adesola@example.com"
text2 = "Adesola Okonkwo, NIN 12345678901, adesola@gmail.com, address: 124 Maple Street"

receipt = arche.compare(text1, text2, entity="person", jurisdiction="NG", backend="regex")
print(receipt.identity, receipt.action, "|", receipt.explanation)
print(receipt.factors)
```

```text
same_entity merge | national ID match; name similarity 100%
{'name': 1.0, 'national_id': 1.0, 'email': 0.0, 'name_tf': 1.0}
```

`identity` says the two texts describe one person: a shared national id clears the distinctiveness gate on its own. `action` says `merge` because a second field, the name, corroborates it. Had the name been absent — an id and a conflicting email and nothing else — the action would have been `hold`: same belief, no recommendation to act on it yet. Keeping the two axes apart is what lets a system link records while routing a conflict to someone.

`receipt.decision_id` is a content hash over the rounded evidence and the pinned versions. Run the same call again and you get the same id, byte for byte.

## Keep it

Add `store=` and the same call also records the receipt, with the two inputs it was made from, in a DuckDB file you own.

```python
ledger = arche.attach("duckdb:///:memory:")            # or duckdb:///people.duckdb
person = dict(entity="person", jurisdiction="NG", backend="regex", store=ledger)

text3 = "Adesola E. Okonkwo, NIN 12345678901, adesola@gmail.com, address: 231 Elim Street"
r12 = arche.compare(text1, text2, **person)
r13 = arche.compare(text1, text3, **person)
r23 = arche.compare(text2, text3, **person)

(entity,) = ledger.entities()
print(len(entity.records), "records |", entity.shared, "|", entity.conflicts)
print(ledger.explain(r12.decision_id)["refuting"])
print(ledger.replay(r12.decision_id).reproduced)
```

```text
3 records | {'national_id': '12345678901'} | {'email': ['adesola@example.com', 'adesola@gmail.com'], 'full_name': ['Adesola Okonkwo', 'Adesola E. Okonkwo']}
['email']
True
```

Three pairwise verdicts became one entity, with what the records agree on and what they do not. [Keep and replay a decision](../guides/keep-and-replay.md) covers the rest of the ledger: looking a decision up by id, what `replay` reports when something has changed, the open cases, and adding evidence.

## Which of these are the same as those?

The batch question. Each list needs a stable `id`; the pack says which other fields are read.

```python
suppliers = [
    {"id": "s1", "name": "Kijani Tea Exporters Ltd", "city": "Nairobi"},
    {"id": "s2", "name": "Zenith Bank Plc", "city": "Lagos"},
]
registry = [
    {"id": "r1", "name": "Kijani Tea Exporters Limited", "city": "Nairobi"},
    {"id": "r2", "name": "Kijani Coffee", "city": "Nairobi"},
]

result = arche.reconcile(suppliers, registry, entity="organisation", store=ledger)
for edge in result["matches"]:
    print(edge["a_id"], edge["b_id"], edge["decision"], edge["score"])
```

```text
s1 r1 match 1.0
s1 r2 review 0.5798
```

`s1↔r1` matched: *Ltd* and *Limited* are the same company. `s1↔r2` is `review`: they share the rare word *Kijani* and nothing else. Pairs below the review floor are not returned, and their absence is not a claim that they differ.

`review` is a queue for a person or a process, not a score to round up. With a ledger attached, `ledger.cases()` lists these pairs and what would settle each one.

## Next

- [Keep and replay a decision](../guides/keep-and-replay.md)
- [Resolve documents](../guides/documents-to-decision.md)
- [Interpret a decision](../guides/interpret-decisions.md)
- [Record resolution API](../reference/record-resolution.md)
