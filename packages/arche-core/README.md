# arche-core

**Are these the same thing? arche decides, shows the evidence, and keeps the receipt.**

An open-source engine for deciding when messy records of people, places, organisations, and products refer to the same real-world entity, with evidence, not just similarity scores or identifiers.

```bash
pip install arche-core
```

## The problem

Your records came from different systems, written by different people, at different times. A supplier list, a registry export, six PDFs, a partner's spreadsheet. The same hospital, cooperative, product or person appears in all of them under different names, with no shared identifier anywhere.

Nothing in those files says which rows are about the same thing. That fact lives in the world, not in the data, so somebody has to **decide** it, and a decision that cannot be explained later is not much use in a system that pays people, ships medicine, or files a regulatory statement.

Most tools give you a similarity score. arche gives you a decision, the evidence behind it, and permission to say *I don't know*.

| | |
|---|---|
| **detect** | Find the entities and identifying data in text, documents and records. |
| **resolve** | Decide which real-world thing each reference points at, and abstain when the evidence does not support a verdict. |
| **protect** | Apply the statute that governs the data, citing the section it came from. |
| **attest** | Sign the decision together with the evidence and the exact representation that produced it. |

## What it resolves

One engine, five calibrated packs. A pack is configuration and data, never a fork.

| Pack | For | The hard case it handles |
|---|---|---|
| `person` | people | *Diallo* and *Jallow* are one name; two *Ibrahim Musa* are two men |
| `place` | facilities, addresses, settlements | identical names 282 km apart are two hospitals |
| `organisation` | companies, cooperatives, unions | a site and the company operating it share a name **and** a coordinate |
| `product_electronics` | catalogue items | a rare model code identifies; `Black T-Shirt` does not |
| `artist` | creative works and performers | one act, many stage names and transliterations |

```python
from arche.resolve import reconcile

result = reconcile(supplier_list, certifier_registry,
                   entity="organisation", id_field="id")

for edge in result["matches"]:
    print(edge["decision"], edge["score"], edge["evidence"])
```

## Compare two pieces of person text

For a fast, local first answer, pass the text directly to `compare`. This synthetic example uses the deterministic `regex` extractor, so it does not download or call a model.

```python
from arche import compare

text1 = "Adesola Okonkwo, NIN 12345678901, address: 123 Maple Street, adesola@example.com"
text2 = "Adesola Okonkwo, NIN 12345678901, adesola@gmail.com, address: 124 Maple Street"

receipt = compare(text1, text2, entity="person", jurisdiction="NG", backend="regex")
print(receipt.identity, receipt.action, receipt.explanation)
```

```text
same_entity hold national ID match
```

`hold` matters: the shared national ID is a strong signal, but the email conflict means Arche has not authorised a merge or downstream action. Treat the result as an evidence-cited resolution proposal. For richer name and address extraction, use the model-assisted backend after its local model is installed, or review the fields through the document/case workflow.

The runnable form is [examples/quick_text_resolution.py](../../examples/quick_text_resolution.py), which goes one step further: three texts, a ledger, and the entity they turn out to describe. The notebook [23_three_texts_one_person.ipynb](../../examples/notebooks/23_three_texts_one_person.ipynb) walks the same path with replay and `observe`.

## Keep the decision, and make it again

Every verdict already carries a `decision_id`: a content hash over the evidence and the pinned versions, so the same inputs give the same id byte for byte. A ledger is where that id becomes useful.

```bash
pip install "arche-core[ledger]"
```

```python
from arche import attach, compare

ledger = attach("duckdb:///people.duckdb")
r12 = compare(text1, text2, entity="person", jurisdiction="NG", backend="regex", store=ledger)
r13 = compare(text1, text3, entity="person", jurisdiction="NG", backend="regex", store=ledger)
r23 = compare(text2, text3, entity="person", jurisdiction="NG", backend="regex", store=ledger)

person, = ledger.entities()          # three texts, one entity
person.shared                        # {'national_id': '12345678901'}
person.conflicts                     # {'email': ['adesola@example.com', 'adesola@gmail.com']}

ledger.explain(r12.decision_id)      # supporting / refuting / missing, by field
ledger.replay(r12.decision_id)       # reproduced=True, or `changed` names what moved
ledger.cases()                       # pairs still at review, and what would settle them
ledger.observe(record_id, {...})     # add evidence, re-decide, supersede
```

The receipt is identical with or without `store=`. The ledger is a DuckDB file on your disk holding the inputs as given, the receipts, and an append-only event log; it records, and leaves what to *do* about a verdict to you.

## Bring your own candidate retrieval

At scale, the costly question is often which pairs deserve comparison. Retrieve candidate pairs in a warehouse, search index or specialist system, then let arche apply the calibrated comparators, gate and decision policy. Pin the retrieval configuration so the resulting decision remains reproducible.

```python
from arche.resolve import reconcile

result = reconcile(
    supplier_records,
    product_offers,
    entity="product_electronics",
    candidate_pairs=[{
        "a_id": "supplier-7",
        "b_id": "offer-103",
        "route": "title-vector-v3",
        "retrieval_score": 0.981,
    }],
    candidate_pins={
        "provider": "warehouse-vector-search",
        "index": "travel-title@sha256:abc123",
        "filters": {"city": "Paris"},
        "top_k": 20,
    },
)
```

The retrieval score proposes a comparison. It does not decide identity. Each returned edge includes the retrieval route, scored evidence, the verdict and a `decision_id` that pins the retrieval provenance too.

## From documents to decisions

Unstructured input is a first-class entry point, not a preprocessing step you bolt on.

```python
from arche import resolve_documents

candidates = [{"entity_id": "ent_supplier_17", "name": "Kijani Tea Exporters Limited"}]
report = resolve_documents("shipments/*.pdf", entity="organisation", candidates=candidates)
print(report.review())
```

That parses each file, detects the identifying data with the governing statute attached, builds a record per document, and compares it against the explicit caller-owned candidate set. Labelled commercial fields such as supplier, distributor, estate, and registration ID are proposed with spans for review; they are not claims or accepted Evidence. Candidate results are proposals. `review()` is the masked hand-off for a review pane or an agent, and `unlinked()` names the documents no verdict tied to anything. `max_candidate_pairs` defaults to 1,000, so callers narrow candidates rather than accidentally comparing every document against a full master table.

Give the run a ledger and the verdicts outlive the report:

```python
from arche import attach, resolve_documents

ledger = attach("duckdb:///suppliers.duckdb")
report = resolve_documents("shipments/*.pdf", entity="organisation", store=ledger)

for entity in ledger.entities():          # which documents describe one thing
    print(entity.shared, entity.conflicts)
ledger.replay(report.decisions[0]["decision_id"]).reproduced   # True, or what moved
```

`extraction_backend="regex"` is the deterministic, air-gapped choice; omit it to retain the model-assisted default.

## Decisions you can hand to someone who does not trust you

Every decision has a reproducible `decision_id`, hashed over the rounded evidence and the pinned versions. No timestamp, no raw float. Same inputs, same id, byte for byte.

```python
from arche.resolve.reconcile import sign_edges
from arche.sign import generate_keypair

signed = sign_edges(result, private_key=key.private_key, kid=key.did_key)
```

A recipient checks two independent things: the signature, which establishes who issued it and that nothing changed since, and the recomputed id, which establishes that the id is the honest address of *this* evidence rather than one lifted from a more favourable decision. They fail differently, which is what makes the pair useful. See [re-verify a decision](https://unpatterned-labs.github.io/arche/how-to/re-verify-a-decision/).

## What is measured

Published whichever way it falls, with the caveats attached rather than in a footnote.

| What | Baseline | arche | Read it as |
|---|---|---|---|
| **Leipzig DBLP–ACM** | out of the box, precision 0.8500, 391 false merges | precision **0.9506**, recall 0.9960 | Complete ground truth, so false merges are counted rather than estimated. The gain is not default: it needs one declared discriminator on `year` |
| **Leipzig Abt-Buy** (products) | name only, F1 0.3443 | F1 **0.7883**, precision 0.9707 | 62 false merges down to 22 |
| **Organisation lane** | token-sort F1 0.8898 | F1 **0.9493** | False merges 21 → 4. Anglophone restaurant listings, so it says nothing about African organisation names |
| **Name frequency** *(ablation)* | the same engine with the frequency signal off: precision 0.162, 7,705 false merges | precision **0.946**, 41 false merges | 1,114 real same-surname pairs from a public voter register. Recall is the cost: **48%** on same-person pairs differing by a dropped middle name |
| **Multilingual detection** | Presidio 37/48 | **47/48** | **Not re-runnable.** The 48-case set is not in this repo and nothing here computes the number. Unverified until rebuilt |

The honest ledger, in full, is in [the whole picture](https://unpatterned-labs.github.io/arche/about/the-whole-picture/), including the benchmarks that are too small, the abstention policy that is not yet precommitted, and the head-to-head against frontier models that has not been run.

For a local OpenSanctions Pairs smoke evaluation, download the CC-BY-NC-4.0 dataset under its terms and run `uv run python data/scripts/benchmark_opensanctions_pairs.py --input path/to/sample_1000.json`. The script reports only the supported person/person and organisation/organisation pairs, and reports structural or mixed-schema pairs as skipped; it does not turn an evaluation result into a runtime pack or an operational sanctions-screening policy.

## Why the calibration comes from where it does

The engine is general. The organisation frequency table is built from company registrations across 65 jurisdictions, the product work is benchmarked on US retail catalogues, and the place work runs on UK hospitals and Nigerian clinics alike.

### CLI discovery and releases

`arche` is intended to be usable without memorising a hidden command tree:

```text
arche version             # the installed arche-core version
arche list                # compare, review, schema, datasets, and version
arche datasets            # truth coverage before choosing a benchmark
arche datasets --json     # the same catalog for an application or agent
arche review template PACK outcomes.csv  # value-free IDs for human adjudication
arche resolve-documents tea-shipment.pdf --entity organisation --candidates suppliers.json --store tea-cases.duckdb --out tea-review.json
```

`arche datasets` never reads record values. It distinguishes complete mappings (which can measure false merges and support an evaluated-method qualification) from unlabelled review packs (which can support adjudication but cannot qualify a method). `arche review template` writes only decision IDs and empty review fields, so the reviewer can supply the outcome separately from record values.

`arche resolve-documents` is the shortest document front door: it emits a masked proposed-field/candidate review artifact and opens an unresolved case when it cannot safely link a supplied candidate. Add `--store FILE.duckdb` to record every verdict and its records in a local ledger; the JSON artifact then also lists the entities those verdicts built, by document name and field *name* only. The release version is single-sourced in `src/arche/_version.py`; Hatch reads that value into wheel metadata, so a release bump changes one file and must be made only as part of a release commit.

What is unusual is where the defaults were tested first. Jaro-Winkler, the string comparator underneath most record linkage, pays a bonus for a shared prefix, because it was tuned on US Census surnames where clerical typos land at the end of a word. *Diallo* and *Jallow* are one Fula family name split by a colonial spelling border, and they share no prefix at all. That assumption fails identically on Arabic transliteration, on Cantonese romanisation, and on any register where one name has three spellings.

So: **general-purpose entity resolution that ships its representation data, built by people who met the defaults first where the defaults break hardest.** Six statute packs ship, covering NDPA (Nigeria), POPIA (South Africa), Kenya DPA, Ghana DPA, GDPR and HIPAA Safe Harbor, alongside a baseline floor that applies where no pack exists.

## Install

```bash
pip install arche-core                   # ~3 MB, CPU only, no ML dependencies
pip install "arche-core[doc]"            # PDF, DOCX, PPTX, XLSX, HTML
pip install "arche-core[detect]"         # GLiNER2-PII soft-PII detection
pip install "arche-core[presidio]"       # Microsoft Presidio integration
pip install "arche-core[resolve]"        # Splink + DuckDB at scale
```

Runs offline by default. Nothing leaves the machine unless you configure a backend that does, and an `EgressGuard` has to be cleared before it can.

> [!WARNING]
> `arche-core` is pre-beta. Suitable for research, prototyping, evaluation, benchmarking and contribution. APIs may change between alpha releases. Do not use it against real personal data until you have completed your own legal, privacy and security review.

## If your problem is inference, use Splink

We mean this literally. Entity resolution has two halves. The mathematics of combining evidence is solved, has a founding paper from 1969, and has excellent free software in [Splink](https://moj-analytical-services.github.io/splink/). arche is about the other half: what the records look like when they are compared, what counts as agreement, and what agreement is worth. Every gain claimed here is a gain in representation, and none of it is a better estimator.

## Source and issues

[github.com/unpatterned-labs/arche](https://github.com/unpatterned-labs/arche)

## Look at a decision

[`arche studio`](https://github.com/unpatterned-labs/arche/tree/main/tools/arche-studio) is a local reading tool. Three files, the standard library, no
framework and no install beyond `arche-core` itself.

```bash
python tools/arche-studio/serve.py     # opens http://127.0.0.1:8765
```

Five modes over one evidence panel:

| | |
|---|---|
| **Compare** | two ad-hoc records, the decision, and a plain sentence saying why it held back |
| **Spatial roles** | paste text or drop a document; origins, destinations and waypoints marked with the cue that decided each |
| **Redact** | run a record through a statute pack and see the action, the cited section, and what was written instead |
| **Verify** | check a signed decision two ways: the signature, and whether its id recomputes from its own evidence |
| **Review queue** | a dense grid over an adjudication pack, sortable and searchable, marking outcomes to a labelled copy |

It is alpha, says so on the page, binds to `127.0.0.1`, and has no
authentication. It is a tool for reading our own queues, not a product.

## Documentation

| | |
|---|---|
| [The whole picture](https://unpatterned-labs.github.io/arche/about/the-whole-picture/) | what is built, what is measured, what is not proven |
| [Quickstart](https://unpatterned-labs.github.io/arche/getting-started/quickstart/) | install, then a first result |
| [How it works](https://unpatterned-labs.github.io/arche/tutorials/how-it-works/) | the pipeline, the comparators, and how a decision is reached |
| [What matching looks like](https://unpatterned-labs.github.io/arche/tutorials/what-matching-looks-like/) | the failure modes side by side, with real verdicts |
| [Re-verify a decision](https://unpatterned-labs.github.io/arche/how-to/re-verify-a-decision/) | check a signed decision you did not issue |
| [Runnable notebooks](https://github.com/unpatterned-labs/arche/tree/main/examples/notebooks) | 14, from first call to crosswalking a national register |

## Contributing

The representation data is open on purpose. A pack that everyone corrects is a better pack, and the corrections are the point. If you know an equivalence, a vocabulary or a frequency we do not, that is the highest-value contribution there is. See [CONTRIBUTING.md](https://github.com/unpatterned-labs/arche/blob/main/CONTRIBUTING.md).

## License

Apache-2.0. The datasets carry their own licences, recorded beside them.
