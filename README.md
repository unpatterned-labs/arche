# arche-core

**The identity data engine for Africa.**

Arche finds identifying data, helps protect it according to the right jurisdiction, and prepares it for privacy-preserving resolution.

The public `arche-core` package focuses on three connected jobs:

- **Detect** identifying data in African text and documents.
- **Protect** it with jurisdiction-aware masking, tokenization, generalization, dropping, retention, and audit actions.
- **Resolve** more safely by producing normalized, policy-aware signals such as tokenized IDs, names, phones, and addresses.

Today, Detect and Protect are the lead product surface. Resolution support is intentionally narrow: name matching, tokenized identifiers, and optional Splink-backed workflows for larger linkage tasks.

> [!WARNING]
> `arche-core` is pre-beta software. It is suitable for research, prototyping,  evaluation, benchmarking, and contribution. APIs may change between alpha releases. Do not use it with real personal data until you have completed your own legal, privacy, and security review.

## Install

```bash
pip install arche-core
```

Optional extras add heavier capabilities:

```bash
pip install "arche-core[doc]"       # PDF, DOCX, PPTX, XLSX, HTML parsing
pip install "arche-core[detect]"    # GLiNER2-PII soft-PII detection
pip install "arche-core[presidio]"  # Microsoft Presidio integration
pip install "arche-core[resolve]"   # Splink + DuckDB resolution support
```

## Quick example

```python
from arche import Pipeline

pipeline = Pipeline(jurisdiction="NG")
result = pipeline.process(
    "Fatima Abdullahi, NIN 12345678901, BVN 22100987654."
)

print(result.redacted_text)
# NAME_... NAME_..., NIN [NIN], BVN [BVN].

for detection in result.detections:
    print(
        detection.category,
        detection.sensitivity_tier.value,
        detection.regulatory_citation,
    )
```

Same pipeline shape works for the four launch jurisdictions:

| Jurisdiction | Policy loaded |
|---|---|
| `NG` | NDPA-2023 |
| `ZA` | POPIA |
| `KE` | Kenya DPA |
| `GH` | Ghana DPA |

## What Arche can detect

| Area | Current coverage |
|---|---|
| Government IDs | Nigerian NIN, BVN, TIN, RC, PVC, drivers licence; Kenyan National ID, Huduma, KRA PIN, NHIF; South African ID, tax, passport; Ghana Card, SSNIT, TIN; plus wider African ID patterns |
| Names and local NER | African name lexicon and equivalence data, with optional GLiNER soft-PII detection |
| Phones | libphonenumber-backed E.164 normalization across African networks |
| Addresses | Nigeria and South Africa parser MVP |
| Digital identifiers | DIDs, Bitcoin addresses, Ethereum addresses |
| Network identifiers | IPv4 and IPv6 detection with private and special-range flags |
| Documents | PDF, DOCX, PPTX, XLSX, and HTML parsing via `arche-core[doc]` |

## Detect, Protect, Resolve

### Detect

`Pipeline.process(...)` finds identity signals and PII spans in text. With `arche-core[doc]`, `Pipeline.process_file(...)` parses supported document files and runs the same detection pipeline over extracted text.

### Protect

Every detection can carry a category, sensitivity tier, regulatory citation, and policy action. The policy layer maps detections to one of six actions:

| Action | Purpose |
|---|---|
| `mask` | Replace direct identifiers such as high-risk government IDs |
| `tokenize` | Produce deterministic pseudonyms for privacy-preserving joins |
| `drop` | Remove data that should not continue through the workflow |
| `generalize` | Reduce precision, such as street address to city |
| `audit` | Keep an event trail without storing raw PII values |
| `retain` | Leave data that the policy permits to pass through |

### Resolve

Resolution depends on clean, protected signals. Arche helps prepare those signals by normalizing phones, identifying IDs, detecting names, parsing address fragments, and producing deterministic tokens that can become privacy-preserving join keys.

For current resolution workflows, install:

```bash
pip install "arche-core[resolve]"
```

## Document scanning

```python
from arche import Pipeline

pipeline = Pipeline(jurisdiction="ZA")
result = pipeline.process_file("dsar_response.pdf")

print(result.summary())
print(result.redacted_text)
```

## Name matching

```python
from arche.match import match

score = match("Mamadou Diallo", "Muhammad Jallow", jurisdiction="NG")
print(score.decision, score.score)
```

Use this when you need culturally aware name matching before or after PII detection.

## Documentation

- Docs: <https://unpatterned-labs.github.io/arche/>
- Quick start: `docs-site/docs/getting-started/quickstart.md`
- API reference: `docs-site/docs/api/index.md`
- Examples: `examples/`

## License

The framework is Apache-2.0. Dataset licensing is documented separately in the dataset cards and repository licensing files.
