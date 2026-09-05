<div class="arche-hero" markdown>

# Are these the same thing?

<p class="arche-hero__sub">arche decides whether messy records of people, organisations, places and products describe one real-world thing — shows the evidence, says <em>I don't know</em> when it should, and keeps a receipt you can replay later.</p>

<span class="arche-hero__status">Alpha software · Apache-2.0 · runs offline on CPU</span>

</div>

Three fragments of text mention someone. They share a national id, disagree on an email, and none of the addresses match. Same person?

```python
import arche

text1 = "Adesola Okonkwo, NIN 12345678901, address: 123 Maple Street, adesola@example.com"
text2 = "Adesola Okonkwo, NIN 12345678901, adesola@gmail.com, address: 124 Maple Street"
text3 = "Adesola E. Okonkwo, NIN 12345678901, adesola@gmail.com, address: 231 Elim Street"

ledger = arche.attach("duckdb:///:memory:")            # a file path keeps it
person = dict(entity="person", jurisdiction="NG", backend="regex", store=ledger)

r12 = arche.compare(text1, text2, **person)
r13 = arche.compare(text1, text3, **person)
r23 = arche.compare(text2, text3, **person)
print(r12.identity, r12.action, "|", r23.identity, r23.action)

(entity,) = ledger.entities()                          # three texts, one person
print(entity.shared, entity.conflicts)
print(ledger.replay(r12.decision_id).reproduced)       # the same decision, again
```

```text
same_entity hold | same_entity merge
{'national_id': '12345678901'} {'email': ['adesola@example.com', 'adesola@gmail.com']}
True
```

Two axes, on purpose. `identity` is what arche believes: all three pairs are the same person, because a shared national id is distinctive. `action` is what it recommends: `hold` where the email conflicts and nothing else corroborates, `merge` where two identifiers agree. The ledger notices that three pairwise answers describe one entity, keeps the receipts, and can make any of them again.

## What you get back

| | |
|---|---|
| **A verdict with a third option** | `same_entity`, `review`, `different` for a pair; `match`, `review` for a batch. `review` is a real answer, not a failure. |
| **The evidence** | per-field agreement, the gate that cleared or refused, what was missing. |
| **A receipt** | `decision_id` is a content hash over the evidence and the pinned versions. Same inputs, same id, byte for byte. Sign it; hand it to someone who does not trust you. |
| **A ledger, if you want one** | `store=` records every verdict with the inputs it was made from. Look one up by id, replay it, see which records it linked into an entity, add evidence, decide again. |

## Start here

```bash
pip install "arche-core[ledger]"
```

- [Quickstart](getting-started/quickstart.md) — the example above, then two lists.
- [Keep and replay a decision](guides/keep-and-replay.md) — the ledger.
- [Resolve documents](guides/documents-to-decision.md) — five PDFs in, linked entities out.
- [Interpret a decision](guides/interpret-decisions.md) — what `review` means and what to do with it.

## What it resolves

One engine, five calibrated packs. A pack is configuration and data, never a fork.

| Pack | For | The hard case it handles |
|---|---|---|
| `person` | people | *Diallo* and *Jallow* are one name; two *Ibrahim Musa* are two men |
| `place` | facilities, addresses, settlements | identical names 282 km apart are two hospitals |
| `organisation` | companies, cooperatives, unions | a site and the company operating it share a name **and** a coordinate |
| `product_electronics` | catalogue items | a rare model code identifies; `Black T-Shirt` does not |
| `artist` | creative works and performers | one act, many stage names and transliterations |

## How it relates to Splink

**Splink is the better matcher, and arche can use it.** Measured, not a courtesy: on Febrl 4, on Splink's `historical_50k`, and on a Nigerian school register, Splink wins every time. `reconcile(backend="splink")` hands the scoring to Splink and keeps what arche puts around a score: per-field evidence, a gate that can refuse a merge and say why, reproducible decision ids, signing, a review pack a person can work, and now a ledger. Use Splink directly when you want the best probability that two rows are the same person. Use arche when you need to show why a decision was made, and prove later that it has not changed. See [the benchmarks](reference/benchmarks.md), including the runs where arche loses.

## Scope for alpha

arche is alpha software. Its APIs and calibration can change. Do not use it to make production decisions about personal data without independent privacy, security, legal and accuracy review.

The `regex` extractor used above is deterministic and offline; it reads identifiers and emails, not names or streets. The model-backed extractors and the document parser are optional extras. `arche-mcp` is a separate, optional package that exposes the same functions to an agent; it does not yet expose the ledger.
