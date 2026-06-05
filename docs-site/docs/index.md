# arche-core

African PII, local NER, and identity-signal detection with statute-aware policy
in Python.

`arche-core` finds names, government identifiers, phone numbers, addresses,
digital identifiers, and other identity signals in African text and documents.
It then applies jurisdiction-aware policy so every detection can carry a
sensitivity tier, regulatory citation, and action such as `mask`, `tokenize`,
`drop`, `generalize`, `audit`, or `retain`.

## Why use this library

- Simple. One `Pipeline.process(...)` call runs detection, policy, redaction,
  and audit output.
- African-first. Launch support covers Nigeria, Kenya, South Africa, and Ghana,
  with wider African identifier, phone, name, and address support.
- Statute-aware. Detections are grounded in NDPA-2023, POPIA, Kenya DPA, or
  Ghana DPA policy files.
- Lightweight by default. Heavy ML, Presidio, Splink, and document parsing
  dependencies are opt-in extras.
- Useful for review workflows. You can scan text, PDFs, DOCX files, invoices,
  DSAR responses, leaked documents, KYC records, and review extracts
  without building a separate compliance layer first.

## Installation

```bash
pip install arche-core
```

For document parsing:

```bash
pip install "arche-core[doc]"
```

Optional extras include:

| Extra | Adds |
|---|---|
| `arche-core[doc]` | docling-backed PDF, DOCX, PPTX, XLSX, and HTML parsing |
| `arche-core[doc-ocr]` | OCR support for scanned documents |
| `arche-core[detect]` | GLiNER2-PII soft-PII detection |
| `arche-core[presidio]` | Microsoft Presidio integration |
| `arche-core[resolve]` | Splink and DuckDB entity resolution support |

## What does it do?

Given text or a supported document file, arche returns:

- the detected PII spans
- their taxonomy category
- a sensitivity tier
- the statute citation used by the loaded jurisdiction
- the policy action applied
- redacted text
- audit records suitable for later review

Supported launch jurisdictions:

| Jurisdiction | Policy loaded |
|---|---|
| `NG` | NDPA-2023 |
| `ZA` | POPIA |
| `KE` | Kenya DPA |
| `GH` | Ghana DPA |

## Example: detect PII in text

```python
from arche import Pipeline

pipeline = Pipeline(jurisdiction="NG")
result = pipeline.process(
    "Fatima Abdullahi, NIN 12345678901, BVN 22100987654."
)

print(result.redacted_text)
```

Example output:

```text
NAME_... NAME_..., NIN [NIN], BVN [BVN].
```

You can inspect the detections directly:

```python
for detection in result.detections:
    print(
        detection.category,
        detection.sensitivity_tier.value,
        detection.regulatory_citation,
    )
```

Example output:

| Category | Tier | Citation |
|---|---|---|
| `PII-2-NIN` | `high` | `NDPA-2023 s.30, NIMC Act s.27` |
| `PII-2-BVN` | `high` | `NDPA-2023 s.30, CBN BVN policy 2014` |
| `PII-1-NAME` | `moderate` | `NDPA-2023 s.30` |

## Example: scan a document

With `arche-core[doc]` installed, use the same pipeline on files:

```python
from arche import Pipeline

pipeline = Pipeline(jurisdiction="ZA")
result = pipeline.process_file("dsar_response.pdf")

print(result.summary())
print(result.redacted_text)
```

`process_file(...)` delegates parsing to the document substrate, then sends the
extracted text through the same detection and policy pipeline.

## What can it detect?

| Area | Current coverage |
|---|---|
| Government IDs | NG NIN, BVN, TIN, RC, PVC, drivers licence; KE National ID, Huduma, KRA PIN, NHIF; ZA ID, tax, passport; GH Ghana Card, SSNIT, TIN; plus wider African ID patterns |
| Names and local NER | African name lexicon and equivalence data, with optional GLiNER soft-PII detection |
| Phones | libphonenumber-backed E.164 normalization across African networks |
| Addresses | Nigeria and South Africa parser MVP |
| Digital identifiers | DIDs, Bitcoin addresses, Ethereum addresses |
| Network identifiers | IPv4 and IPv6 detection with private and special-range flags |

## Matching names

```python
from arche.match import match

score = match("Mamadou Diallo", "Muhammad Jallow", jurisdiction="NG")
print(score.decision, score.score)
```

Use this when you need culturally aware name matching before or after PII
detection.

## Next steps

- [Getting started](getting-started/quickstart.md)
- [Match African names](how-to/match-african-names.md)
- [Extract from an invoice](how-to/extract-from-invoice.md)
- [Nigerian fintech KYC cookbook](cookbooks/fintech-kyc.md)
- [Introducing arche v0.2](blog/introducing-arche.md)
- [Pipeline API reference](api/resolve.md)

## Licence

The framework is Apache-2.0. Dataset licensing is documented separately in the
dataset cards and repository licensing files.
