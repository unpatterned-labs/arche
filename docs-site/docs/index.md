<div class="arche-hero" markdown>

# Know what's real.

<p class="arche-hero__sub">The open engine for messy, multilingual data. Find
the entities, resolve who they actually are, protect them under the law that
applies, and sign every decision.</p>

<span class="arche-hero__status">v0.3.0a1 &middot; pre-beta &middot; Apache-2.0</span>

</div>

arche tells you and your agent what — and who — your data is actually talking
about. It finds the entities in any document or system, standardises them for
the names and addresses people actually use, and works out which real-world
thing each one refers to. Along the way it keeps disagreement between sources
instead of erasing it, protects everything under the law that applies, and
signs every decision.

<div class="arche-verbs" markdown>
<div class="arche-verb" markdown>
<p class="arche-verb__name">detect</p>
<p class="arche-verb__body">Find the entities and the identifying data in text and documents.</p>
</div>
<div class="arche-verb" markdown>
<p class="arche-verb__name">resolve</p>
<p class="arche-verb__body">Work out which real-world thing each reference points at — and abstain when the evidence does not support a verdict.</p>
</div>
<div class="arche-verb" markdown>
<p class="arche-verb__name">protect</p>
<p class="arche-verb__body">Apply the statute that governs the data, and cite the section it came from.</p>
</div>
<div class="arche-verb" markdown>
<p class="arche-verb__name">attest</p>
<p class="arche-verb__body">Sign a decision together with the evidence and the representation that produced it.</p>
</div>
</div>

## The problem, in three records

Two catalogue rows read *Damini Ogulu* and *Burna Boy*. Three clinic registers
around Kano read *Fatima Abdullahi*, *Fatuma Abdullahi*, *F. Abdulahi*. And two
sanctioned men share the name Khalid Mehmood, the same country and the same
programme, with different fathers and different national IDs.

Two of those are one entity wearing different names. One is two entities
wearing the same name. Software that gets the first two right by loosening its
matching gets the third one catastrophically wrong. Holding all three at once
is the job.

## Why use this library

- **It abstains.** When the evidence does not support a verdict, resolution
  returns `review` rather than guessing. An agent that flips two people has a
  much worse day than one that asks.
- **Every decision cites its law.** Detections carry a sensitivity tier and the
  specific statute section that classifies them — NDPA-2023, POPIA, Kenya DPA,
  Ghana DPA, GDPR, or HIPAA Safe Harbor.
- **Every decision can be signed** together with the exact representation that
  produced it, so the claim *given this evidence and this representation, this
  was the decision* is checkable by anyone.
- **Your schema, not ours.** One YAML declares your fields; arche generates the
  comparators, the masking, and the extraction contract your LLM fills.
- **Bring any model.** An LLM is a proposer, never the decider. It reads messy
  text into your declared fields — hallucinated fields become violations rather
  than values — and the engine grades its judgment against a deterministic
  oracle, counting `review` as an honest abstention rather than a miss. The
  integration surface is one callable.
  [Bring your own LLM](how-to/bring-your-own-llm.md).
- **Calibrated on the hardest identity data there is.** Africa is where the
  engine was made good, not the limit of where it runs. The name equivalence
  and frequency data ships as inspectable files you can read and correct.
- **Lightweight by default.** Heavy ML, Presidio, Splink, and document parsing
  are opt-in extras.

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

These outputs are useful for redaction today and for safer record linkage later:
tokenized IDs, normalized phones, detected names, and parsed address fragments
can become privacy-preserving join signals.

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
from collections import Counter
from arche import Pipeline

pipeline = Pipeline(jurisdiction="ZA")
result = pipeline.process_file("dsar_response.pdf")

print(Counter(d.category for d in result.detections))
print(Counter(o.action for o in result.policy_outcomes))
print(result.redacted_text)
```

`Result` is a plain dataclass - there is no `summary()` helper. Its fields are
`document_hash`, `detections`, `addresses`, `policy_outcomes`, `redacted_text`,
`audit_log`, and `metadata`; counting over `detections` / `policy_outcomes` is
how you get a per-category and per-action rollup. On the equivalent inline call
`Pipeline(jurisdiction="ZA").process("ID 8001015009087, phone 082 555 1234.")`
those two lines print:

```text
Counter({'PII-2-NATIONAL_ID': 1, 'PII-3-PHONE': 1})
Counter({'mask': 1, 'tokenize': 1})
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
from arche import match

score = match("Mamadou Diallo", "Muhammad Jallow", jurisdiction="NG")
print(score.decision, score.score)
# match 0.8865
```

Use this when you need culturally aware name matching before or after PII
detection.

## What ships today

| Verb | What arche does today |
|---|---|
| detect | Finds entities, PII, and identity signals in text and supported document files |
| resolve | Scores a pair or a whole table, returns `same_entity` / `review` / `different`, and abstains rather than guessing |
| protect | Applies jurisdiction-aware policy actions and emits audit-ready output with the statute section cited |
| attest | Signs a decision with its evidence and the representation that produced it |


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
