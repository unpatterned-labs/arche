# arche-core

**Know what's real.**

An open engine for messy data. Find the entities, resolve who or what they are,
and decide which records are the same thing — with the evidence, the
refutations, and a signed decision you can re-check.

arche tells you and your agent what — and who — your data is actually talking
about. It finds the entities in any document or system, standardises them for
the names and addresses people actually use, and works out which real-world
thing each one refers to. It keeps disagreement between sources instead of
erasing it, says plainly when it will not decide, and signs every decision so
you can re-check it months later.

| | |
|---|---|
| **detect** | Find the entities and the identifying data in text and documents. |
| **resolve** | Work out which real-world thing each reference points at — and abstain when the evidence does not support a verdict. |
| **protect** | Apply the statute that governs the data, and cite the section it came from. |
| **attest** | Sign a decision together with the evidence and the exact representation that produced it. |

Two records read *Damini Ogulu* and *Burna Boy*. Three clinic registers read
*Fatima Abdullahi*, *Fatuma Abdullahi*, *F. Abdulahi*. Two sanctioned men share
the name Khalid Mehmood, the same country and the same programme, and have
different fathers and different national IDs. Getting those three cases right —
two splits to heal, one merge to refuse — is the whole job.

Calibrated on the world's hardest identity data, and built for how the world
actually writes names and addresses everywhere. Africa is where the engine was
made good, not the limit of where it works: the launch statute packs cover
Nigeria, Kenya, South Africa and Ghana alongside GDPR and HIPAA Safe Harbor.

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
| Government IDs | Nigerian NIN, BVN, TIN, RC, PVC, drivers licence; Kenyan National ID, Huduma Namba, KRA PIN, NHIF; South African ID, tax, passport; Ghana Card, SSNIT, TIN; plus wider African ID patterns |
| Names and local NER | African name lexicon and equivalence data, with optional GLiNER soft-PII detection |
| Phones | libphonenumber-backed E.164 normalization across African networks |
| Addresses | Nigeria and South Africa parser MVP |
| Digital identifiers | DIDs, Bitcoin addresses, Ethereum addresses |
| Network identifiers | IPv4 and IPv6 detection with private and special-range flags |
| Documents | PDF, DOCX, PPTX, XLSX, and HTML parsing via `arche-core[doc]` |

**How Huduma Namba is detected, because the distinction matters.** A Huduma
Namba has no check digit and shares its length range with NHIF numbers and the
Kenyan National ID, so a bare 8-digit string carries no evidence of which of the
three it is. Detection is therefore **cue-anchored**: `PII-2-HUDUMA` is emitted
where the text says "Huduma", and a bare number is reported as whatever the
bare-digit patterns make of it. That is the same evidence a person uses, and it
is why this pattern carries 0.88 confidence where the bare-digit ones sit at
0.40–0.45. Until v0.3.0a2 there was no pattern at all and Huduma numbers were
reported as `PII-2-NHIF` — mislabelled rather than missed.

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
from collections import Counter
from arche import Pipeline

pipeline = Pipeline(jurisdiction="ZA")
result = pipeline.process_file("dsar_response.pdf")

print(Counter(d.category for d in result.detections))
print(Counter(o.action for o in result.policy_outcomes))
print(result.redacted_text)
```

`Result` is a plain dataclass with the fields `document_hash`, `detections`,
`addresses`, `policy_outcomes`, `redacted_text`, `audit_log`, `metadata`. There
is no `summary()` helper — count over `detections` / `policy_outcomes` instead.
On `Pipeline(jurisdiction="ZA").process("ID 8001015009087, phone 082 555 1234.")`
the two `Counter` lines print:

```text
Counter({'PII-2-NATIONAL_ID': 1, 'PII-3-PHONE': 1})
Counter({'mask': 1, 'tokenize': 1})
```

## Name matching

```python
from arche import match

score = match("Mamadou Diallo", "Muhammad Jallow", jurisdiction="NG")
print(score.decision, score.score)
# match 0.8865
```

Use this when you need culturally aware name matching before or after PII detection.

## Documentation

- Docs: <https://unpatterned-labs.github.io/arche/>
- Quick start: `docs-site/docs/getting-started/quickstart.md`
- API reference: `docs-site/docs/api/index.md`
- Examples: `examples/`

## License

The framework is Apache-2.0. Dataset licensing is documented separately in the dataset cards and repository licensing files.
