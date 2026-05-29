# arche — PII + digital identity detection with statute-aware policy

**African-first, globally pluggable.** Detect PII, digital identifiers, phones, addresses, and IPs across African jurisdictions. Every detection carries its **sensitivity tier** (high / moderate / low) and the **regulatory citation** it was made under. Apply six closed policy actions grounded in NDPA-2023, POPIA, Kenya DPA, or Ghana DPA.

```bash
pip install arche-core
```

```python
from arche import Pipeline

pipeline = Pipeline(jurisdiction="NG")   # auto-loads NDPA-2023
result = pipeline.process(
    "Fatima Abdullahi, NIN 12345678901, BVN 22100987654."
)

for d in result.detections:
    print(f"{d.category:18} tier={d.sensitivity_tier.value:8} "
          f"citation={d.regulatory_citation}")
# PII-2-BVN          tier=high     citation=NDPA-2023 s.30, CBN BVN policy 2014
# PII-2-NIN          tier=high     citation=NDPA-2023 s.30, NIMC Act s.27
# PII-1-NAME         tier=moderate citation=NDPA-2023 s.30   (x2 - given + family name)

print(result.redacted_text)
# NAME_... NAME_..., NIN [NIN], BVN [BVN].
```

Per-country detectors, statute-grounded policy enforcement, PII-tier classification, and the regulatory citation surfaced on every detection — in one call.

---

## What arche detects

| Category | Module | Coverage |
|---|---|---|
| **Government IDs** | `arche.detect.{ng,ke,za,gh}` + `arche.detect._africa` | NG: NIN, BVN, TIN, RC, voter PVC, drivers licence. KE: National ID + Huduma, KRA PIN, NHIF. ZA: SA ID (Luhn + DOB/gender decode), tax reference, passport. GH: Ghana Card, SSNIT, TIN. Plus 11 non-launch African countries. |
| **Phones** | `arche.detect._africa.phones` | libphonenumber-backed E.164 normalization across all African networks. |
| **Addresses** | `arche.addr` | NG + ZA MVP today. Full PRD §5 parser is Stage 2 work. |
| **IP addresses** | `arche.detect.ip` | IPv4 + IPv6 via stdlib `ipaddress`. RFC1918 / loopback / multicast flagged. False-positive suppression for "v1.2.3.4" version strings. |
| **Digital identifiers** | `arche.detect.digital_id` | W3C DIDs (`did:key`, `did:web`, `did:ion`, + 5 more known methods). Bitcoin (P2PKH, P2SH, bech32). Ethereum (EIP-55 confidence boost for mixed-case). |
| **Soft PII** *(opt-in)* | `arche-core[detect]` → GLiNER2-PII | Multilingual neural NER for names / orgs / locations. |

Every detection carries:
- **`category`** per the [Pan-African PII Taxonomy v0.1](https://github.com/unpatterned-labs/archetree/main/datasets/pan-african-pii-taxonomy) — 51 categories across PII-1..PII-9
- **`sensitivity_tier`** — `high` / `moderate` / `low` (NIST 800-122 framework, per-jurisdiction in YAML)
- **`regulatory_citation`** — exact statute section the loaded jurisdiction cites
- **`confidence`** — 1.0 for structurally validated, lower for shape-only

## What arche does with detections

Six closed policy actions:

| Action | When it's the default |
|---|---|
| **mask** | High-tier government IDs (NIN, SA ID, Ghana Card), financial accounts |
| **tokenize** | Personal names, contact info — preserves linking utility |
| **drop** | Special-category data (biometric, health, race, religion, passwords, payment cards) |
| **generalize** | Locational data (DOB → year, street address → city) |
| **audit** | Categories the statute permits but wants tracked |
| **retain** | Public-record categories (company registration numbers) |

The action mapping ships in YAML statute files (`arche/policy/statutes/`)
that you can read, audit, or extend. See
[the lifecycle page](concepts/lifecycle.md) for what arche does after
detection (verify, govern, resolve, link).

---

## The thesis

> Small specialized PII models — OpenAI Privacy Filter, GLiNER2-PII, ettin-68m-pii — are commoditizing detection. The differentiating contribution is not better detection; it's the **identity workflow framework** that composes detection with resolution, linking, verification, and governance into a coherent lifecycle. None of those small models do that. Detection is one floor; arche is the building.

[Read the full thesis →](concepts/how-it-works.md)

---

## Sign, share, extract — the headline capability

```python
from arche.sign import SignWorkflow, VerifyExtractWorkflow, generate_keypair

# Party A — bank's compliance officer
bank_key = generate_keypair()
signer = SignWorkflow(jurisdiction="NG")
signed = signer.sign(document_text, bank_key, purpose="dsar_response")

# Wire transit (signed is a string)

# Party B — recipient verifies offline, recovers structured result
result = VerifyExtractWorkflow().process(signed)
# result.signature_valid       True (offline did:key verification)
# result.statute_at_signing    "NDPA-2023@v1.0"
# result.redacted_text         "Customer ..., NIN [NIN], BVN [BVN], ..."
# result.policy_outcomes       [(PII-2-NIN, mask), (PII-2-BVN, mask), ...]
```

No infrastructure required. `did:key` is self-describing. Verification is purely cryptographic. The recipient knows: who signed (cryptographically), then, under what statute, what policy was applied — **without seeing the original document**.

[Sign-share-extract tutorial →](tutorials/sign_share_extract.md)

---

## Citizen-side DSAR

```python
from arche.workflow import DSARWorkflow, DSARRequestor, DSAROrganization
from arche.sign import generate_keypair

citizen_key = generate_keypair()

wf = DSARWorkflow(
    jurisdiction="NG",
    requestor=DSARRequestor(
        name="Adesola Okonkwo",
        identifier_label="NIN",
        identifier_value="12345678901",
        email="adesola@example.com",
    ),
    request_type="access",          # access | rectification | erasure | portability | objection
    targets=[
        DSAROrganization(name="Sterling Bank", dpo_email="dpo@sterlingbank.ng"),
    ],
)

result = wf.run(citizen_key)
for draft in result.drafts:
    print(draft.letter_text)           # cites NDPA-2023 s.34 (Right of Access)
    print(draft.signed_envelope)       # JWS-signed for DPO verification
```

African citizens have rights under NDPA, POPIA, Kenya DPA, and Ghana DPA that today are practically unexercisable — the bureaucracy is the barrier. arche generates compliant draft letters and cryptographic provenance so a citizen with a phone can exercise rights that previously needed a lawyer.

[Citizen DSAR tutorial →](tutorials/citizen_dsar.md)

---

## Lightweight by default

`pip install arche-core` is under 100 MB. No mandatory ML or DPI dependencies. Heavy capabilities are opt-in extras:

| Extra | What you get |
|---|---|
| `arche-core[detect]` | GLiNER2-PII via ONNX runtime for multilingual soft-PII |
| `arche-core[presidio]` | Microsoft Presidio recognizer plugin |
| `arche-core[resolve]` | Splink + DuckDB for billion-row entity resolution |
| `arche-core[doc]` | docling-backed PDF / DOCX / PPTX / XLSX parsing |
| `arche-core[doc-ocr]` | Adds easyocr for scanned documents |

Cold import: **<700ms** even with everything in v0.2 loaded. Lazy-import discipline is enforced by CI — nothing heavy loads from `import arche`.

---

## Where to start

- [Installation](getting-started/installation.md)
- [Quick Start — five examples in five minutes](getting-started/quickstart.md)
- [Why arche & when to use it](tutorials/arche_vs_alternatives.md) — by-persona guide for developers, researchers, DPOs, and journalists, plus the cross-tool benchmark
<!-- - [How arche Works — the v0.2 thesis explained](concepts/how-it-works.md) -->
<!-- - [Verifiable identity workflows](concepts/verifiability.md) -->
- [API Reference](api/index.md)

---

## License

Apache-2.0 for the framework. CC-BY-4.0 for the Pan-African PII Taxonomy and Africa Address Benchmark datasets. By [Unpatterned Labs](https://unpatterned.org).
