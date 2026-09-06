# How arche works

arche has related capabilities, but they answer different questions. Keeping them separate prevents a useful score or extraction from becoming an unsupported identity claim.

| Capability | Question it answers | Main entry point |
|---|---|---|
| Pipeline | What sensitive or identifying information is in this text or file? | `Pipeline.process()` |
| Document resolution | Which document records may refer to the same person? | `resolve_documents()` |
| Record resolution | Which rows from two lists are candidates for the same entity? | `reconcile()` |
| Direct person comparison | Do these two specific person references describe one entity? | `compare()` |
| Address and spatial roles | What address or place is mentioned, and what role does it play? | `arche.addr`, `extract_places()` |

Each example below is a standalone Python script. Install the package, save a block as a `.py` file, and run `python filename.py`. The document example needs the optional document extra; the other examples work with `pip install arche-core`.

## Crosswalk two lists

Use `reconcile()` when you have two collections of records and want surfaced candidates with evidence. This example deliberately has a rare facility name and a common one. The common name goes to review even though it has the same raw score.

```python
from arche.resolve import reconcile

registry = [
    {"id": "registry-1", "name": "Gyaranya Health Post", "lat": 11.90, "lon": 8.50},
    {"id": "registry-2", "name": "General Hospital", "lat": 12.00, "lon": 8.50},
]
survey = [
    {"id": "survey-1", "name": "Gyaranya Health Post", "lat": 11.94, "lon": 8.50},
    {"id": "survey-2", "name": "General Hospital", "lat": 12.04, "lon": 8.50},
]

result = reconcile(registry, survey, entity="place", block=None)
for edge in result["matches"]:
    print(edge["a_id"], edge["b_id"], edge["decision"], edge["score"])
```

```text
registry-1 survey-1 match 0.8454
registry-2 survey-2 review 0.8454
```

Each returned edge also has `evidence`, `pins`, and a `decision_id`. A missing edge is not a `different` decision.

## Compare two people directly

Use `compare()` when the caller has already selected exactly two person references and needs an explicit identity claim.

```python
from arche.resolve import compare

decision = compare(
    {"name": "Fatima Abdullahi", "national_id": "12345678901"},
    {"name": "Fatuma Abdulahi", "national_id": "12345678901"},
)

print(decision.identity, decision.action, round(decision.score, 4))
print(decision.explanation)
```

```text
same_entity merge 1.0
national ID match; name similarity 91%
```

`compare()` can also return `review` or `different`. Its identity labels are not interchangeable with crosswalk labels. Structured records use the deterministic path; free text first needs a configured extraction backend.

## Process text with Pipeline

`Pipeline` detects and applies the selected jurisdiction's policy to one piece of text. It does not resolve two records into one entity.

```python
from arche import Pipeline

pipeline = Pipeline(jurisdiction="NG", detectors=None, audit=False)
result = pipeline.process(
    "Fatima Abdullahi, NIN 12345678901, phone 08031234567."
)

print([(item.category, item.text) for item in result.detections])
print(result.redacted_text)
```

```text
[('PII-2-NIN', '12345678901'), ('PII-1-NAME', 'Fatima'),
 ('PII-1-NAME', 'Abdullahi'), ('PII-3-PHONE', '08031234567')]
NAME_099000a2 NAME_e38a0fcd, NIN [NIN], phone PHONE_1b5b54b8.
```

The exact redaction tokens are implementation details. Use `detections`, `policy_outcomes`, and `metadata` when integrating the result.

## Resolve records extracted from documents

Install document support first:

```bash
pip install "arche-core[doc]"
```

This script writes two small documents, reads them, extracts identity signals, and compares the resulting records. Point it at your own folder in a real workflow. Plain text is read directly, with no extra; PDF and DOCX go through docling, so those need `arche-core[doc]`.

```python
from pathlib import Path

from arche import resolve_documents

# Plain text keeps the example dependency-free; a folder of PDFs behaves the
# same way and is what you would actually hand it.
folder = Path("demo-docs")
folder.mkdir(exist_ok=True)

for filename, text in {
    "statement.txt": "Fatima Abdullahi\nNIN 12345678901\nPhone 08031234567",
    "invoice.txt": "Fatuma Abdulahi\nNIN 12345678901\nPhone 08031234567",
}.items():
    (folder / filename).write_text(text, encoding="utf-8")

report = resolve_documents(
    str(folder), jurisdiction="NG", extraction_backend="regex", quiet=True,
    progress=False,
)
print([(item["identity"], item["score"]) for item in report.decisions])
print(report.table())
```

```text
[('same_entity', 1.0)]

EXTRACTED RECORDS
document       name                    phone                   national_id
-------------------------------------------------------------------------------------
invoice.txt    Fatu***********         0803*******             1234*******
statement.txt  Fati************        0803*******             1234*******

RESOLUTION
document a                   document b                   verdict        score
------------------------------------------------------------------------------
invoice.txt                  statement.txt                same_entity   1.0000
```

`DocumentReport` retains records, masked summaries, decisions, parser errors, and extraction provenance. This example selects the dependency-free `regex` extractor; choose an installed model backend deliberately when the document language or layout needs it. Check `report.errors` before treating a folder run as complete.

## Parse an address and label its spatial role

Address parsing gives structured location signals. Spatial-role extraction says how a place is used in a sentence and retains the cue that supports the role.

```python
from arche.addr import extract_places, parse_address

address = parse_address("7B Allen Avenue, Ikeja, Lagos")
print(address.components.street, address.components.city, address.country_inferred)

text = (
    "Pick up from 7B Allen Avenue, Ikeja and deliver to "
    "12 Adeola Odeku Street, Victoria Island."
)
for mention in extract_places(text):
    print(mention.role, mention.text, mention.cue, mention.confidence)
```

```text
Allen Avenue Lagos NG
origin 7B Allen Avenue, Ikeja Pick up from 0.95
destination 12 Adeola Odeku Street, Victoria Island deliver to 0.95
```

Spatial roles can be `origin`, `destination`, `location`, `via`, or `unknown`. `unknown` is a deliberate abstention when the text does not support a role.

## The record-resolution path

`reconcile()` works in four stages:

1. **Candidate generation.** Blocking avoids scoring every possible pair.
2. **Comparison.** Entity-specific comparators inspect names, identifiers, coordinates, types, and other available fields.
3. **Decision gate.** Supporting signals can strengthen a candidate, but a distinctive signal is required for an automatic `match`.
4. **Evidence artifact.** Each returned edge includes its evidence, run pins, and a reproducible `decision_id`.

The result labels are `match` and `review`. Candidates below the review floor are omitted. A returned score is a decision signal, not a calibrated probability.

## The maths, stated plainly

Record linkage combines several pieces of evidence. A shared rare identifier is more informative than a shared common name; a facility type or coordinate can support the decision but should not create identity by itself.

arche uses comparison scores, thresholds, a review band, and entity-specific representation data such as frequency tables and vocabularies. The key product choice is not to collapse every candidate into yes or no. `review` remains a first-class output when the evidence is insufficient.

For large-scale probabilistic model training and distributed execution, use Splink. arche's current focus is the representation, evidence, and decision boundary around a match.

## Pipeline and documents

`Pipeline` processes text or a file for detection and policy handling. It is not the same as a table crosswalk. `resolve_documents()` composes document parsing, detection, record assembly, and direct comparisons into a report for a set of documents.

This distinction matters: a document can be correctly parsed yet still be too ambiguous to link, and two records can be matchable even when no document pipeline is involved.

## Addresses are not just strings

`arche.addr` parses addresses, landmarks, and jurisdiction clues. `extract_places()` also identifies spatial roles such as origin, destination, location, and via. The role label carries the cue that supported it and returns `unknown` when the text does not justify a committed role.

Address parsing and place resolution are complementary. Parsing turns text into structured signals; resolution evaluates whether two records refer to the same place. Neither alone establishes that an address is authoritative or current.

## Agents and automation

Agents can propose fields, call the API, explain returned evidence, and route `review` candidates. They should not make an unreviewed identity claim, silently upgrade a review, or treat an LLM answer as a substitute for provenance.
