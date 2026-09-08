<div class="arche-hero" markdown>

# Are these the same thing?

<p class="arche-hero__sub">arche decides whether messy records of people, organisations, places and products describe one real-world thing — shows the evidence, says <em>I don't know</em> when it should, and keeps a receipt you can replay later.</p>

<span class="arche-hero__status">0.8.0 · Apache-2.0 · runs offline on CPU</span>

</div>

Three fragments of text mention someone. They share a national id and a name — once with a middle initial — disagree on an email, and none of the addresses match. Same person?

```python
import arche

text1 = "Adesola Okonkwo, NIN 12345678901, address: 123 Maple Street, adesola@example.com"
text2 = "Adesola Okonkwo, NIN 12345678901, adesola@gmail.com, address: 124 Maple Street"
text3 = "Adesola E. Okonkwo, NIN 12345678901, adesola@gmail.com, address: 231 Elim Street"

ledger = arche.attach("duckdb:///:memory:")            # a file path keeps it
person = dict(entity="person", jurisdiction="NG", backend="basic", store=ledger)

r12 = arche.compare(text1, text2, **person)
r13 = arche.compare(text1, text3, **person)
r23 = arche.compare(text2, text3, **person)
print(r12.identity, r12.action, "|", r23.identity, r23.action)

(entity,) = ledger.entities()                          # three texts, one person
print(entity.shared, entity.conflicts)
print(ledger.replay(r12.decision_id).reproduced)       # the same decision, again
```

```text
same_entity merge | same_entity merge
{'national_id': '12345678901'} {'email': ['adesola@example.com', 'adesola@gmail.com'], 'full_name': ['Adesola Okonkwo', 'Adesola E. Okonkwo']}
True
```

Two axes, on purpose. `identity` is what arche believes: all three pairs are the same person, because a shared national id is distinctive. `action` is what it recommends: `merge`, because the name corroborates the id — on a national id alone, with nothing else agreeing, it would say `hold`. The ledger notices that three pairwise answers describe one entity, keeps the receipts, and can make any of them again. The email the records disagree on is not averaged away: it sits in `conflicts`, beside the name spelled two ways, for whoever acts on the entity to see.

The same detectors answer the question before that one: what personal data is in this text, and can I hand on a copy?

```python
safe = arche.deidentify(text1, jurisdiction="NG", backend="basic")
print(safe.text)                                       # the statute chose each rendering
print(safe.count, "spans under", safe.statute, "|", safe.decision_id[:28])
```

```text
NAME_f71c6342 NAME_925a28e1, NIN [NIN], address: [ADDRESS], EMAIL_3f6caee6
5 spans under NDPA-2023 | red:sha256:2f39ce00381bd80d7
```

## What you get

| | |
|---|---|
| **The personal data, with the law attached** | `detect_pii` returns every span with its category, confidence and the statute section it falls under; `deidentify` returns the copy the statute permits, and the copy is a decision with an id. |
| **A verdict with a third option** | `same_entity`, `review`, `different` for a pair; `match`, `review` for a batch. `review` is a real answer, not a failure. |
| **The evidence** | per-field agreement, the gate that cleared or refused, what was missing. |
| **A receipt** | `decision_id` is a content hash over the evidence and the pinned versions. Same inputs, same id, byte for byte. Sign it; hand it to someone who does not trust you. |
| **A ledger, if you want one** | `store=` records every verdict -- and every redaction -- with the inputs it was made from. Look one up by id, explain it, replay it, see which records it linked into an entity, add evidence, decide again. |
| **A refusal when it should refuse** | no jurisdiction it can infer, a statute that does not cover the country, a pair whose only agreement is a common name: each comes back as its own answer, never as a guess dressed as a verdict. |
| **Nothing leaving the process** | the base install runs on CPU with no model and no network; models are optional extras that propose, never decide. |

## Start here

```bash
pip install "arche-core[ledger]"
```

- [Quickstart](getting-started/quickstart.md) — find and mask, then the example above, then two lists.
- [Keep and replay a decision](guides/keep-and-replay.md) — the ledger.
- [Association analysis](guides/association-analysis.md) — Mary Smith became Mary Jones; why the first record and the last are one person.
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

## Scope

arche is pre-1.0: 0.8.0 is the first release out of alpha, and its APIs and calibration can still change between minor versions. Do not use it to make production decisions about personal data without independent privacy, security, legal and accuracy review.

The `basic` extractor used above is deterministic and offline; it reads identifiers, emails, and names from a shipped lexicon of 13,342 African given and family names, not streets. `backend="auto"` adds GLiNER2-PII when the `[detect2]` extra is installed, as a proposer the validators and the statute still decide over. The document parser is an optional extra too. `arche-mcp` is a separate, optional package that exposes the same functions to an agent, including the ledger.
