# Resolve documents

By the end of this page you can point arche at a folder of documents and get back the record each one describes, a verdict for every pair, and a masked report you can paste into a ticket, with the whole run kept in a ledger if you want it. The example below writes three small text files and runs on the base install; PDFs need `arche-core[doc]` and are covered further down.

```python
from pathlib import Path
import arche

folder = Path("statements")
folder.mkdir(exist_ok=True)
(folder / "bank_statement.txt").write_text(
    "Zenith Bank Plc. Statement of account for Adesola Ebun Okonkwo.\n"
    "Address: 123 Maple Street, Ikeja, Lagos. Email adesola@example.com.\n", encoding="utf-8")
(folder / "invoice.txt").write_text(
    "Invoice PEDHCF-00012 to Adesola Okonkwo, 123 Maple Street, Ikeja.\n"
    "Phone 0803 555 7890.\n", encoding="utf-8")
(folder / "payslip.txt").write_text(
    "Kijani Tea Exporters Ltd. Payslip for Adesola Okonkwo, NIN 12345678901.\n"
    "Phone 0803 555 7890. Paid to account at Zenith Bank Plc.\n", encoding="utf-8")

report = arche.resolve_documents(folder, jurisdiction="NG", extraction_backend="basic", progress=False)
print(report.table())
```

```text
EXTRACTED RECORDS
document            name                    email                   phone                   national_id             address               
------------------------------------------------------------------------------------------------------------------------------------------
bank_statement.txt  Ades****************    ades***************     -                       -                       123 **************************
invoice.txt         Ades***********         -                       0803*********           -                       123 *******************
payslip.txt         Ades***********         -                       0803*********           1234*******             -                     

RESOLUTION
document a                   document b                   verdict        score
------------------------------------------------------------------------------
bank_statement.txt           invoice.txt                  review        0.9958
bank_statement.txt           payslip.txt                  review        0.9575
invoice.txt                  payslip.txt                  same_entity   1.0000
```

A bank statement, an invoice, a payslip: three documents from three organisations that have never heard of each other, different spellings of one name, and no shared customer identifier. `resolve_documents` parses each file, finds the personal data under the statute, assembles a record per document, and compares every pair. `source` may be a folder, a glob such as `"docs/*.pdf"`, a single file, or a list of any of those. Values in the table are masked, so the default is safe to paste into an issue; `report.table(reveal=True)` shows them.

Every stage is a shipped layer you can call on its own: `arche.doc.parse` for the text, `detect_pii` for the spans, `extract` for names and places, `compare` for the verdict. The point of the one call is that they compose here, once, so you never write a regular expression against a document.

## Read the verdicts, not the scores

```python
for d in report.decisions:
    print(d["a"], d["b"], d["identity"], d["score"], d["factors"])
print(report.unlinked())
```

```text
bank_statement.txt invoice.txt review 0.9958 {'name': 0.8, 'address': 0.8957, 'name_tf': 0.6797}
bank_statement.txt payslip.txt review 0.9575 {'name': 0.8, 'name_tf': 0.6797}
invoice.txt payslip.txt same_entity 1.0 {'name': 1.0, 'phone': 1.0, 'name_tf': 1.0}
['bank_statement.txt']
```

A score of 0.9958 is still `review`. The invoice and the payslip are one person: same name, same phone. The bank statement carries a middle name and nothing else that the other two hold, so it agrees on a name and an address and on nothing rare, which is what `name_tf` measures: name similarity weighted by how uncommon the shared tokens are. A merge needs agreement on something rare, and a shared given name is not it. `report.unlinked()` lists the documents no verdict tied to anything; the bank statement is a case for a person, not a lost record.

The same shape shows up on the repository's sample PDFs, where the ordering by score is the inverse of the ordering by verdict. This is what [notebook 02](https://github.com/unpatterned-labs/arche/blob/main/examples/notebooks/02_same_person_across_documents.ipynb) prints over `data/docs`:

```text
pair                                          score   name_tf   verdict
Monzo / Invoice                              0.9656   0.6393   review
Monzo / Paystatement                         0.9974   0.6393   review
Invoice / Paystatement                       0.9903   1.0000   same_entity
```

The highest-scoring pair is a review and a lower one is a merge. The threshold was never the interesting part. This is the same rule that stops two records called *General Hospital* merging on their name, and two different people called *Ibrahim Musa* becoming one person.

## Know where each value came from

```python
print(report.record_provenance["payslip.txt"])
print(report.provenance["payslip.txt"])
print(report.detections["payslip.txt"])
```

```text
{'national_id': 'document', 'phone': 'document', 'name': 'document'}
{'parser': 'text', 'text_sha256': 'a77e4b9b11b8c110d139c9a47eb06d960e1fe86cdc217802bbd4071085edb76c', 'ocr': None, 'artifact_sha256': '0b571cc2e54a0c0aaef1f7c44c492f60ae002ce82afeb97f861d4d8b2b4dc400'}
{'PII-2-NIN': 1, 'PII-1-NAME': 2, 'PII-3-PHONE': 1}
```

`record_provenance` says which layer produced each field: `document` for the body text, `metadata` for a value a PDF asserts about itself in its header. `provenance` is what produced the parse: the hash of the exact bytes, the parser, whether OCR ran, and the digest of the rendered text that every cited span indexes into. That block goes inside every decision's pins, so a document-derived decision can be re-verified rather than only re-run: a parser upgrade changes the text, which changes the record, which changes the verdict, and the pins record that it did. `detections` is the count by category, never a value.

Identifiers come from the detectors, which validate check digits rather than match a shape. That boundary matters. Run over a British bank statement with `jurisdiction="NG"`, the detector set once reported 36 tax identification numbers, every one a ride reference or a transaction id that happened to be ten digits. Each landed at confidence 0.55, not 0.95, and none reached the identity record: a detector may over-fire, because for redaction over-firing is the safe direction, without that noise ever becoming evidence about who someone is.

## Let each document say where it is from

```python
inferred = arche.resolve_documents(folder, extraction_backend="basic", progress=False)
for doc, j in inferred.jurisdictions.items():
    print(doc, j["country"], "|", j["reason"])
print(inferred.errors)
```

```text
bank_statement.txt None | no jurisdiction signals found in the document
invoice.txt None | no jurisdiction signals found in the document
payslip.txt NG | strongest signal id.nin, 74% of total evidence weight
{}
```

`jurisdiction` defaults to `"auto"`: each document's own evidence (a postcode, a registrar's name, a currency, a company-form suffix, a national id) proposes a country, and `report.jurisdictions` says what was found and why. A document whose evidence is thin gets no statute rather than a guessed one, which is why the example at the top passes `jurisdiction="NG"`: an explicit jurisdiction always wins, and if it disagrees with a document's own evidence the disagreement lands in `report.jurisdiction_conflicts` rather than staying silent.

When a jurisdiction is inferred and no statute pack covers it, a conservative baseline floor applies. That is deliberate. On that British statement, switching from `NG` to `GB` took the false detections from 36 to zero, and it did so by switching protection off, because there was no UK pack at the time and a pipeline with no statute returns text unredacted. Detecting the right country is not the same as protecting the document.

`report.errors` is where a file that could not be parsed goes. It is recorded and skipped, never raised: one unreadable scan in a folder of twenty should not cost you the other nineteen.

## Compare documents against records you already hold

```python
registry = [{"id": "cust-001", "name": "Adesola Okonkwo", "phone": "08035557890", "national_id": "12345678901"},
            {"id": "cust-002", "name": "Ibrahim Musa", "phone": "08051112222"}]
against = arche.resolve_documents(folder, jurisdiction="NG", extraction_backend="basic",
                                  progress=False, candidates=registry)
for d in against.decisions:
    print(d["a"], "->", d["b"], d["identity"], d["score"], d["status"])
```

```text
bank_statement.txt -> cust-001 review 0.9575 proposed
bank_statement.txt -> cust-002 review 0.6303 proposed
invoice.txt -> cust-001 same_entity 1.0 proposed
invoice.txt -> cust-002 different 0.0526 proposed
payslip.txt -> cust-001 same_entity 1.0 proposed
payslip.txt -> cust-002 different 0.0526 proposed
```

Pass `candidates=` and each document is compared against your own list (a registry export, master data, records a reviewer already accepted) instead of against the other documents. Each candidate needs an `id` or `entity_id`. Every decision is marked `proposed`: the report asserts nothing and treats no extracted value as accepted evidence. The run is bounded by `max_candidate_pairs` (1,000 by default) and raises rather than silently running all pairs, so narrow the candidate set first.

## Keep the run

```python
ledger = arche.attach("duckdb:///:memory:")            # a path keeps it
kept = arche.resolve_documents(folder, jurisdiction="NG", extraction_backend="basic",
                               progress=False, store=ledger)
for entity in ledger.entities():
    print([r.caller_id for r in entity.records], entity.shared, entity.conflicts)
print([c.record_a.caller_id + " <-> " + c.record_b.caller_id for c in ledger.cases()])
replay = ledger.replay(kept.decisions[-1]["decision_id"])
print(replay.reproduced, sorted(replay.then.pins["extraction"]["a"]))
```

```text
['invoice.txt', 'payslip.txt'] {'name': 'Adesola Okonkwo', 'phone': '0803 555 7890'} {}
['bank_statement.txt <-> invoice.txt', 'bank_statement.txt <-> payslip.txt']
True ['artifact_sha256', 'ocr', 'parser', 'text_sha256']
```

Hand the run a ledger and every verdict is recorded with the record it was made from. `ledger.entities()` shows which documents describe one thing, `ledger.cases()` the pairs still at review with what would settle each, and `ledger.replay()` makes any verdict again under the engine installed now, with the parse provenance in its pins. [Keep, explain, replay](keep-and-replay.md) has the rest: `observe` to add the field a reviewer went and found, `resolve` to place a new document against the entities.

## Hand the report on

```python
review = report.review()
print(list(review))
print(review["proposed_fields"][0])
print(review["unlinked"])
```

```text
['entity', 'proposed_fields', 'decisions', 'unlinked', 'errors']
{'document': 'bank_statement.txt', 'field': 'address', 'value': '123 **************************', 'source': 'document', 'confidence': 0.0, 'span': None}
['bank_statement.txt']
```

`report.review()` is the hand-off shape for a review pane or an agent: the fields each document proposed, every verdict, and the documents nothing linked, masked unless `reveal=True`. `report.to_json()` is the whole report for a ticket or a test fixture; `report.to_csv()` and `report.to_rows()` are the same rows for a spreadsheet or a DataFrame. An agent may prepare the inputs, summarise a masked report, or present a case to a person. It must not turn `review` into a match, reveal values outside the approved boundary, or treat a document-derived decision as independent evidence without reading its provenance.

## PDFs, and what a file says about itself

Plain text and Markdown are read directly. Everything else goes through docling and needs the extra.

```bash
pip install "arche-core[doc]"
```

<!-- docs-test: skip -->
```python
report = arche.resolve_documents("statements/*.pdf", jurisdiction="NG")
print(report.table())
```

The default `extraction_backend="auto"` uses a local model for names and places when one is installed and the rules otherwise; the examples above name `basic` so they run the same everywhere. No API key, no account, nothing leaves your machine.

A PDF carries three things before you read a word of it.

<!-- docs-test: skip -->
```python
from arche.doc import parse

doc = parse("invoice.pdf")
print(doc.info.author)              # 'Condor Flugdienst GmbH'
print(doc.info.producer.family)     # 'enterprise-report'
```

The issuer arrives for free: `author` is a high-confidence organisation sitting in the file header, the field an extractor otherwise guesses at from body text, and `record_provenance` marks it `metadata` when it is used. The producer is provenance: `browser-print` means a person printed it from a browser, `html-renderer` that a server rendered it, `enterprise-report` that a reporting system emitted it, and those imply different degrees of trust in the contents. And metadata is personal data: a bank statement's title has carried an account fragment and a date range, a booking confirmation's subject a real reference, so a pipeline that redacts the body and ignores the header has been leaking for as long as it has run. One caveat on every surface that touches this: metadata is a claim, not a verification. `producer` and `author` are trivially forged by anyone who can write a PDF. Read them as what the file says about itself.

## From the shell

```bash
arche resolve-documents statements/ --jurisdiction NG --out review.json
arche resolve-documents "shipments/*.pdf" --entity organisation --store suppliers.duckdb --out review.json
```

The JSON is the review artifact, values masked unless `--reveal`; `--candidates FILE` takes a CSV or JSON of your own records; `--store` adds a value-free entity summary to the output, document names and the names of the fields they agree on, never the values. `--extraction-backend` defaults to `basic` on the command line.

## Where to read next

| You want to | Read |
|---|---|
| the ledger: entities, cases, observe, replay | [Keep, explain, replay](keep-and-replay.md) |
| the spans and the statute behind the masked values | [Find and mask personal data](find-and-mask.md) |
| your own field names on the records | [Extract to your schema](extract-to-your-schema.md) |
| why a high score can be `review` | [Evidence, gates and distinctiveness](../how-it-works/evidence.md) |
| what each extra installs | [Extras](../reference/extras.md) |
| the same run from an agent | [The MCP server](mcp-server.md) |
