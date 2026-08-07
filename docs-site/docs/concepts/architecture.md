# Architecture

This page is the architectural reference for the **detect → policy → audit** half of arche-core: how the package is organised into substrate modules, which modules compose with which, and how signing, DSAR drafting and place lookup sit on top of the same detection foundation. Start at [How arche Works](how-it-works.md) for the walkthrough.

!!! note "The other half"
    arche's lead capability today is **resolution and attestation** — `resolve.pairwise`, `resolve.crosswalk`, `sign_edges`, the declaration format, and the LLM lane. Those run on a different set of primitives and are documented in [the representation engine](representation-engine.md), [from place to entity](from-place-to-entity.md), and the resolution guides. This page covers the detection substrate they compose with; it is not the whole package. The [roadmap](roadmap.md) records why the lead moved.

```
PIPELINE PATH (detect -> policy -> audit)
─────────────────────────────────────────────────────────────────
   Pipeline(jurisdiction="NG").process(text)
       │
       ▼
   arche.detect.*  →  arche.policy  →  arche.graph.audit
       │                  │                  │
       └── per-country    └── statute YAML   └── append-only
           ID detectors       + 6 actions        SQLite log
           + addresses        + tiers
           + phones           + citations
           + names lexicon

COMPOSITIONS ON THE SAME PRIMITIVES
────────────────────────────────────
   arche.sign            - Ed25519 + JWS + did:key  → sign Pipeline.Result
   arche.credentials     - SD-JWT-VC re-framing     → wallet interop
   arche.workflow.dsar   - Pipeline + statute       → DSAR draft letters
   arche.resolve_places  - gazetteer + receipts     → place lookup
   arche.match / link    - Fellegi-Sunter           → record matching
```

The Pipeline path is one call. The compositions ship in the same package. You compose at either level: top-down via `Pipeline`, or bottom-up by calling substrates directly. Detailed substrate-by-substrate reference follows below.

```python
from arche import Pipeline

pipeline = Pipeline(jurisdiction="NG")   # auto-loads NDPA-2023
result = pipeline.process(
    "Customer Adesola Okonkwo, NIN 12345678901, phone 0803 555 7890."
)
```

---

## The five substrates

```
┌─────────────────────────────────────────────────────────────┐
│                  INPUT (text or file)                       │
└──────────────────────┬──────────────────────────────────────┘
                       │
                       │  arche.doc.parse(path)         (optional)
                       │  docling - PDF/DOCX/PPTX/XLSX
                       ▼
              ┌────────────────┐
              │     DETECT     │   arche.detect.{ng,ke,za,gh,_africa}
              │  per-country   │   15 launch ID patterns + 11 more
              │  ID detectors  │   libphonenumber-backed phones
              └────────┬───────┘
                       │
                       ▼
              ┌────────────────┐
              │     POLICY     │   arche.policy.engine
              │ statute-driven │   six closed actions
              │   enforcement  │   NDPA / POPIA / KE / GH / GDPR / HIPAA
              └────────┬───────┘
                       │
                       ▼
              ┌────────────────┐
              │      SIGN      │   arche.sign  +  arche.credentials
              │ verifiability  │   Ed25519 + did:key + JWS
              │   substrate    │   SD-JWT-VC for wallet interop
              └────────┬───────┘
                       │
                       ▼
              ┌────────────────┐
              │     AUDIT      │   arche.graph.audit
              │  append-only   │   SQLite, PII-free rows
              │     log        │   PII values never stored
              └────────┬───────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────┐
│         OUTPUT - Result, signed envelope, audit row         │
└─────────────────────────────────────────────────────────────┘
```

Workflows like `Pipeline` and `DSARWorkflow` compose the substrates
above. The substrates are usable independently.

---

## Substrate 1: Detect

`arche.detect.{ng,ke,za,gh,_africa}` find PII and identifiers using
per-country detectors with check-digit / structural validation. Neural
NER (GLiNER2) is available as the opt-in `arche-core[detect]` extra and
is never on the critical path — the base wheel is rule-based and
CPU-only by design.

Launch jurisdictions cover 15 ID patterns:

- **NG**: NIN, BVN, TIN, RC number, voter PVC, driver's licence
- **KE**: National ID, KRA PIN, NHIF
- **ZA**: SA ID (full Luhn + DOB/gender/citizenship decode), tax
  reference, passport
- **GH**: Ghana Card, SSNIT, TIN

Plus 11 non-launch African countries (RW, TZ, UG, ET, CI, SN, CM, EG,
MA, AO, MZ) via `arche.detect._africa.ids` — 26 ID patterns in total
across `ID_PATTERNS`. Phone normalization runs
through `phonenumbers` (libphonenumber Python port) for E.164 across
all 30+ African telecom networks.

```python
from arche.detect.ng.ids import detect_nigerian_ids
from arche.detect._africa.phones import normalize_e164

ids = detect_nigerian_ids("NIN 12345678901, BVN 22156789012")
phone = normalize_e164("0803 555 7890", "NG")  # +2348035557890
```

---

## Substrate 2: Policy

`arche.policy` routes each detection through the applicable statute and
applies one of **six closed actions**:

| Action | Behaviour |
|---|---|
| `mask` | Replace with `[CATEGORY]` placeholder |
| `tokenize` | Replace with a deterministic token (rotating-key HMAC) |
| `drop` | Remove the span entirely |
| `generalize` | Reduce specificity (DOB → year, address → city) |
| `audit` | Emit an audit log entry but leave the text untouched |
| `retain` | Allowlist; pass through unchanged |

Statutes are YAML files at `arche/policy/statutes/`. Six ship:

| Pack | Jurisdiction | Categories mapped | `version` | `review_status` |
|---|---|---|---|---|
| `NDPA-2023.yaml` | Nigeria | 27 | `v1.0` | `self-reviewed` |
| `GDPR.yaml` | EU/EEA | 27 | `v1.0` | `self-reviewed` |
| `KENYA-DPA.yaml` | Kenya | 22 | `v0.1-scaffold` | `self-reviewed` |
| `POPIA.yaml` | South Africa | 21 | `v0.1-scaffold` | `self-reviewed` |
| `GHANA-DPA.yaml` | Ghana | 21 | `v0.1-scaffold` | `self-reviewed` |
| `HIPAA-SAFE-HARBOR.yaml` | US (health) | 17 | `v1.0` | `self-reviewed` |

Every category in every pack carries a statute-section citation. The two
labels are independent by design: `version` is a claim about our work
(complete and stable), `review_status` a claim about the world (who
vouches for the mappings). No pack claims `regulator-reviewed`, and the
loader **fails closed** on one that does so without naming a reviewer.
The three `v0.1-scaffold` labels are stale — those packs are complete;
see [the roadmap](roadmap.md#today-v030a1).

```python
from arche.policy import load_statute, apply_policy

statute = load_statute("NDPA-2023")
statute.version, statute.review_status   # ('v1.0', 'self-reviewed')
applied = apply_policy(text, detections, statute)
```

---

## Substrate 3: Sign

`arche.sign` is the verifiability substrate. The recipient of a signed
document can verify it **offline** - no PKI, no resolver, no network
call - because the issuer's `did:key` is embedded in the JWS `kid`
header.

```python
from arche.sign import SignWorkflow, VerifyExtractWorkflow, generate_keypair

bank_key = generate_keypair()
signed = SignWorkflow(jurisdiction="NG").sign(
    document, bank_key, purpose="dsar_response"
)

# Recipient verifies offline
result = VerifyExtractWorkflow().process(signed)
assert result.signature_valid
```

Built on `cryptography` (Ed25519 + JWS compact serialization, RFC 7515).
Zero new base deps beyond what was already required.

`arche.credentials.sd_jwt` re-frames any signed envelope as an IETF
SD-JWT-VC for EUDI Wallet ARF / MOSIP Inji interop. The holder controls
which claims to disclose to which verifier; the issuer's signature
still binds the whole credential cryptographically.

Hybrid post-quantum signatures (Ed25519 + NIST FIPS 204 ML-DSA) are
designed but **not shipped**; see [the roadmap](roadmap.md).

---

## Substrate 4: Audit

`arche.graph.audit` is an append-only SQLite log:

- PII values are **never** stored. Only category labels, character
  spans, and SHA-256 document hashes.
- `audit.compliance_report_markdown()` produces a regulator-ready
  markdown report.
- `audit.export_signed(key=compliance_key, purpose="ndpc_audit")`
  produces a JWS-signed bundle for handoff.
- Nullable `prev_hash` / `signature` columns are wired into the schema
  today but are **not populated** — hash-chaining is [in-flight
  work](roadmap.md#in-flight), not a shipped guarantee. Treat the log as
  append-only by convention, not as tamper-evident.

There is no pluggable storage backend today: SQLite is the only one, and
`StorageBackend` does not exist as a public protocol.

---

## Substrate 5: Workflow

Workflows compose the four substrates above:

| Workflow | What it composes |
|---|---|
| `arche.workflow.Pipeline` | Detect → Policy → Audit |
| `arche.workflow.DSARWorkflow` | Pipeline → Sign → Audit + statute-aware DSAR drafting |
| `arche.sign.SignWorkflow` | Pipeline → Sign → Audit |
| `arche.sign.VerifyExtractWorkflow` | Verify → recover redacted text + policy outcomes |

Each workflow is a thin orchestrator; you can wire substrates manually.

---

## What's not in this package

Stated so adopters can hold us to scope:

- **No FHIR R4 emission or `Patient` / `Bundle` adapters.** Health-data interop is sector-pack work tied to a real deployment, not scaffolding.
- **No registry or DPI adapters** (OpenCRVS, MOSIP, DHIS2, OpenG2P format converters). Early stubs were deleted because they were empty modules pretending to be features. Adapters ship when there is a real deployment to build against.
- **No risk / churn / fraud / opportunity signal heuristics.** The early `arche.signal` layer was example-tier guessing and was removed. Its compliance half is now the statute-grounded `policy_outcomes` in `Pipeline.Result`.
- **No hash-chained or tamper-evident audit log** — the columns exist, the chaining does not.
- **No MCP server in the wheel.** It is built but unpublished; see [the roadmap](roadmap.md#in-flight).

See the [roadmap](roadmap.md) for the expansion paths and the explicit non-commitments that go with them.

---

## What's next

- [How arche Works](how-it-works.md) - the substrate-by-substrate walkthrough
- [Verifiability](verifiability.md) - sign-share-extract deep dive
- [Sign, share, extract tutorial](../tutorials/sign_share_extract.md)
- [Citizen DSAR tutorial](../tutorials/citizen_dsar.md)
