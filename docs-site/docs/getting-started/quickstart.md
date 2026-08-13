# Quick Start

**Know what's real.**

An open engine for messy data. Find the entities, resolve who or what they are,
and decide which records are the same thing — with the evidence, the
refutations, and a signed decision you can re-check.

Five minutes, no API key, no account, nothing leaves your machine. Every output
below is what the code actually printed.

```bash
pip install arche-core[doc]
```

---

## One minute: three documents, one question

You have a bank statement, an invoice and a payslip. Different issuers,
different layouts, different spellings of the same name, no shared identifier.
Are they the same person?

```python
from arche import resolve_documents

report = resolve_documents("statements/*.pdf")
print(report.table())
```

```text
EXTRACTED RECORDS
document                    name              email               phone      organisation
-----------------------------------------------------------------------------------------
Monzo_bank_statement.pdf    Denn***********   —                   7211****   Monz**********
Invoice-PEDHCF-00012.pdf    Denn*********     deni**************  —          Netl*********
Paystatement_2025-12.pdf    Denn*********     —                   —          Viat******

RESOLUTION
document a                  document b                  verdict        score
-----------------------------------------------------------------------------
Monzo_bank_statement.pdf    Invoice-PEDHCF-00012.pdf    review        0.9656
Monzo_bank_statement.pdf    Paystatement_2025-12.pdf    review        0.9974
Invoice-PEDHCF-00012.pdf    Paystatement_2025-12.pdf    same_entity   0.9903
```

That is the whole thing. No regular expressions, no field mapping, no schema.

**Values are masked by default.** The table above is safe to paste into an issue
without thinking about it. `report.table(reveal=True)` when you need the real
values, and that choice is explicit rather than a flag you forgot.

### Read the verdicts before you read the scores

The **highest-scoring pair is not a match**. `0.9974` came back `review`, while
`0.9903` came back `same_entity`.

That is not a bug. The bank statement says `Dennis Aibuedefe Irorere` and the
other two say `Dennis Irorere`. A merge requires agreement on something *rare*,
and a shared given name is not rare enough to justify merging two people's
financial records without a human looking. The score says the records are
broadly consistent; the gate says nobody has earned a merge.

**A score is not a decision.** That distinction is most of what arche is for.

---

## Two minutes: the data, as data

```python
report.to_json()                      # records, verdicts, timing, errors
report.to_dicts()                     # one row per document, for pandas
report.save_json("out.json")          # straight to disk
report.records                        # raw extracted record per document
report.decisions                      # each verdict, with factors and decision_id
report.timing.slowest                 # ('invoice_10.pdf', 67.4)
```

Long runs print progress to stderr as they go, so a three-minute job never looks
like a hang:

```text
[1/4] parsing invoice_10.pdf (0.0s)
[1/4] detecting + extracting invoice_10.pdf (49.0s)
[2/4] parsing invoice_12_ak.pdf (67.4s)
```

`progress=False` silences it, `progress="jsonl"` emits one JSON object per line
for agent loops, and `ARCHE_PROGRESS=0` overrides everything for CI. Output goes
to **stderr**, so piped stdout and `to_json()` stay clean.

---

## Three minutes: why a verdict went that way

A decision you cannot explain is indistinguishable from a bug.

```python
for d in report.decisions:
    print(d["identity"], d["score"], d["factors"])
    print(d["decision_id"])
```

```text
review 0.9656 {'name': 0.8, 'address': 0.4416, 'name_tf': 0.6393}
dec:sha256:6905b79403b22a17dc471dd2d054882a30ba314c7230e3af9845b27a6d146238
```

`name` is string similarity. `name_tf` is the same comparison **weighted by how
rare the shared tokens are** — matching on `Irorere` is worth far more than
matching on a common given name, because rarity is what identifies.

`decision_id` is a content hash over the evidence and the inputs. No timestamp,
no randomness: anyone holding the same inputs recomputes the same id. That is
what makes a verdict checkable months later rather than merely stored.

---

## Two lists instead of two documents

The same engine links two catalogues — a registry against a survey, your
customers against a supplier file:

```python
from arche.resolve import crosswalk

result = crosswalk(list_a, list_b, entity="place")
for edge in result["matches"]:
    print(edge["a_id"], edge["b_id"], edge["decision"], edge["score"])
```

Packs ship for `person`, `place`, `artist` and `product_electronics`, or bring
your own comparators for your schema. Every pack is configuration over one
engine, never a fork.

**These are measured on public benchmarks with complete ground truth**, so false
merges are visible rather than assumed:

| Benchmark | Precision | Recall |
|---|---|---|
| Leipzig Geographic Settlements (places, 4 sources) | 0.9862 | 0.9654 surfaced |
| DBLP–ACM (bibliographic) | 0.9506 | 0.9960 |
| Leipzig Abt-Buy (products, experimental) | 0.9707 | 0.6636 |

Reproduce them with `python data/scripts/benchmark_leipzig.py`.

---

## What else is in the box

Below the fold on purpose — you do not need any of this on day one.

**Documents carry provenance.** `parse()` reads what a file says about itself:

```python
from arche.doc import parse

doc = parse("invoice.pdf")
doc.info.author              # 'Condor Flugdienst GmbH'  — the issuer, free
doc.info.producer.family     # 'browser-print' | 'html-renderer' | 'enterprise-report'
```

Whether a human printed a document from a browser or a reporting system emitted
it tells you how much to trust its contents. Treat every field as a *claim by
the file*: metadata is trivially forged.

**Data-protection policy, when you need it.** If you are handling personal data
under a named regime, `Pipeline(jurisdiction=...)` applies a statute pack that
maps each detected category to an action with a citation, and `EgressGuard`
decides what may leave your boundary. Packs ship for Nigeria, South Africa,
Kenya, Ghana, the EU, the UK and HIPAA.

This is a **policy template keyed to scope you select** — it does not determine
which law applies to your processing, because that turns on establishment, on
where your data subjects are, and on sector, none of which a country code can
decide. → [Detect and govern](../concepts/lifecycle.md)

---

## Next

- [Is this the same person, across three documents?](https://github.com/unpatterned-labs/arche/blob/main/examples/notebooks/02_same_person_across_documents.ipynb) — the notebook this page opens with
- [Inside the one call](https://github.com/unpatterned-labs/arche/blob/main/examples/notebooks/08_inside_the_one_call.ipynb) — every layer, one per cell
- [What is the false-merge rate?](https://github.com/unpatterned-labs/arche/blob/main/examples/notebooks/06_what_is_the_false_merge_rate.ipynb) — the benchmark that measures precision
- [Similar is not the same](../blog/similar-is-not-the-same.md) — why embeddings do not settle identity
