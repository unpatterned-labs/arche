# How arche Works

arche-core does one job: **detect PII in African text and ground every detection in the data protection statute that classifies it.** Government IDs with check-digit validation. Phones with libphonenumber. Names with a 114-group equivalence lexicon. Addresses with landmark anchoring. Every detection emits a sensitivity tier and the regulatory citation that justifies the policy action applied to it.

This page walks through how a single `Pipeline.process(text)` call moves through the detection, policy, and audit stages. Signing, DSAR drafting, place lookup and entity matching compose on top of the same primitives — see [Verifiability](verifiability.md) and the workflow guides. Resolution and attestation, arche's lead capability today, are covered in [the representation engine](representation-engine.md) and [from place to entity](from-place-to-entity.md).

---

## The end-to-end call

```python
from arche import Pipeline

pipeline = Pipeline(jurisdiction="NG")
result = pipeline.process(
    "Customer Adesola Okonkwo, NIN 12345678901, phone 0803 555 7890."
)

print(result.redacted_text)
# Customer Adesola Okonkwo, NIN [NIN], phone PHONE_...

print(result.detections[0].regulatory_citation)
# NDPA-2023 s.30, NIMC Act s.27

print(result.policy_outcomes[0].action)
# mask
```

Behind that one call:

1. **Statute auto-loaded.** `Pipeline(jurisdiction="NG")` resolves to
   `NDPA-2023.yaml`. Override with `Pipeline(statute="NDPA-2023")` to
   pin a specific version.
2. **Detect.** Per-country detectors run in deterministic order - NG
   detectors first, then `_africa` cross-cutting (phones, generic IDs),
   then optional GLiNER2 if `arche-core[detect]` is installed.
3. **Validate.** Structural validators (Luhn for SA ID, the 11-digit
   NIN constraint, BVN's 11-digit format) drop false positives.
4. **Policy.** The statute YAML maps each detected category to one of
   the six closed actions. The applied action carries a statute
   section reference into the `PolicyOutcome`.
5. **Redact.** Spans flagged for `mask` / `tokenize` / `drop` /
   `generalize` are rewritten into `result.redacted_text`. The original
   detection coordinates remain available in `result.detections`.
6. **Audit.** Each detection emits an `AuditEvent` row into the SQLite
   log (PII values never stored - only category labels, spans, and
   document hashes).

The `Result` object holds everything: detections, policy outcomes,
redacted text, audit entries, and the original (un-redacted) input for
verifiability use cases like `SignWorkflow`.

---

## API levels

| Level | What you get | When to use |
|---|---|---|
| **Workflow** | `Pipeline`, `DSARWorkflow`, `SignWorkflow` | "Run the whole substrate chain in one call" |
| **Substrate** | `arche.policy.apply_policy`, `arche.sign.sign`, `arche.graph.audit.AuditLog` | "I want control over one substrate" |
| **Primitive** | `arche.detect.ng.ids.detect_nigerian_ids`, `arche.policy.engine.apply_action` | "I'm building my own composition" |

Workflows call substrates. Substrates call primitives. No capability is
lost at any level - every workflow is just a thin orchestrator over
the substrates documented in [Architecture](architecture.md).

---

## Why this composition matters

A traditional PII library answers *"is this string a phone number?"*. arche answers *"this string is a Nigerian mobile under NDPA-2023 s.29 (sensitive personal data), which means it MUST be masked before processing, and I'm leaving an audit row that an NDPC investigator can verify against my deployment's records."*

That gap - between **detection** and **statute-grounded compliance evidence** - is what arche-core fills. The primitives exist in many libraries (libphonenumber detects phones, Presidio detects English-centric PII, GLiNER does multilingual NER). arche-core is the layer that turns those primitives into auditable compliance output by attaching the African-context layer (per-country ID validators, name equivalences, landmark addresses) to the statute-aware layer (versioned YAML, six closed actions, sensitivity tiers, regulatory citations).

That combination - detection + statute citation + audit log row - is the thesis. See [the roadmap](roadmap.md) for where the framework goes from here.

---

## Detector substrate - a deeper look

Per-country detectors live at `arche.detect.{ng,ke,za,gh}.ids`. Each is
a pure-Python module with a single entry function that returns a list
of `Detection` objects:

```python
from arche.detect.ng.ids import detect_nigerian_ids

for d in detect_nigerian_ids("My NIN is 12345678901 and BVN is 22156789012."):
    print(d.id_type, d.country, d.start, d.end, d.confidence, d.metadata)
# BVN NG 33 44 0.85 {'validator_status': 'format_valid'}
# NIN NG 10 21 0.6  {'validator_status': 'format_valid'}
```

Note the return type: the per-country ID detectors return `NationalID`
records (`text`, `country`, `id_type`, `confidence`, `start`, `end`,
`metadata`), not `Detection` objects. Taxonomy categories, sensitivity
tiers and citations are attached one layer up, by `Pipeline`.

Confidence is **not** a uniform 1.0. Each pattern carries a base
confidence reflecting how much the shape alone is worth — Ghana Card
0.95 and KRA PIN 0.92 have distinctive formats, while a bare Nigerian
NIN (0.55) or a 7-to-8-digit Kenyan National ID (0.40) could be almost
any number — and a passing structural check raises it. `metadata`
records which check ran, so a low score is explainable rather than
mysterious.

The `Detection.category` follows the Pan-African PII Taxonomy
(`PII-1..PII-9`, 54 categories at v0.1.1), shipped as a standalone
CC-BY-4.0 dataset at
[`datasets/pan-african-pii-taxonomy/`](https://github.com/unpatterned-labs/arche/tree/main/datasets/pan-african-pii-taxonomy).

---

## Policy substrate - six closed actions

Exactly six actions are available to a statute, and the set is closed:

| Action | Use case |
|---|---|
| `mask` | Sensitive PII surfacing to a less-privileged consumer (analyst, auditor) |
| `tokenize` | Need referential integrity across documents but not the underlying value |
| `drop` | The PII has no downstream use; remove it |
| `generalize` | Need partial signal (year of birth, city) without the full value |
| `audit` | The action is legal-allowed; just log that it happened |
| `retain` | Allowlist; statute permits passthrough |

A statute YAML maps each detection category to exactly one action plus
a free-text citation. The mapping is auditable and version-controlled,
not buried in code.

```yaml
# Excerpt from NDPA-2023.yaml
categories:
  PII-2-NIN:
    action: mask
    citation: "NDPA-2023 s.29 (sensitive personal data - biometric/identity)"
  PII-3-PHONE:
    action: tokenize
    citation: "NDPA-2023 s.26 (lawful basis: legitimate interest)"
```

Six packs ship — NDPA-2023, POPIA, Kenya DPA, Ghana DPA, GDPR and HIPAA
Safe Harbor — and each declares a `review_status` separately from its
`version`, because "we finished it" and "someone official checked it"
are different claims. All six are `self-reviewed`; none claims regulator
review, and the loader refuses a pack that claims it without naming a
reviewer. → [the pack table](architecture.md#substrate-2-policy)

---

## Sign substrate - offline verifiability

`arche.sign` does not require any infrastructure. The recipient verifies
the JWS using the issuer's `did:key`, which is embedded in the JWS
header. No DID resolver, no PKI, no network call.

```python
from arche.sign import SignWorkflow, VerifyExtractWorkflow, generate_keypair

issuer_key = generate_keypair()  # did:key:z6Mk...
signed = SignWorkflow(jurisdiction="NG").sign(
    document, issuer_key, purpose="dsar_response"
)

# Cold start verification - no network call
result = VerifyExtractWorkflow().process(signed)
assert result.signature_valid
assert result.statute_at_signing == "NDPA-2023@v1.0"   # id and version, pinned
```

`arche.credentials.sd_jwt` re-frames any signed envelope as an SD-JWT-VC
(IETF format) so the same document plays nicely with EUDI Wallet ARF
and MOSIP Inji ecosystems.

---

## Audit substrate - append-only, regulator-ready

Every detection emits an `AuditEvent` row into the SQLite log:

- `timestamp` - ISO 8601 UTC
- `event_type` - `detection` / `policy` / `address` / `workflow_start` / `workflow_end`
- `document_hash` - SHA-256 of the input (NOT the input itself)
- `category` - Pan-African PII Taxonomy label
- `span_start`, `span_end` - character offsets only; the substring stays in the document
- `action` - one of the six closed actions
- `statute_id`, `statute_reference` - which pack decided, and the section it cites
- `prev_hash`, `signature` - nullable, and **not populated today**. The
  columns exist so hash-chaining can land without a migration; until it
  does, the log is append-only by convention, not tamper-evident.

Export for regulator handoff:

```python
from arche.graph.audit import AuditLog

audit = AuditLog("./compliance.sqlite")
audit.compliance_report_markdown()   # Human-readable markdown
audit.export_signed(key=officer_key, purpose="ndpc_quarterly_audit")
# Returns a JWS-signed bundle the regulator can verify offline.
```

SQLite is the only backend. There is no storage-backend protocol and no
Postgres or graph extra; if you need the rows elsewhere, `audit.export()`
gives you them.

---

## What's next

- [Verifiability concepts](verifiability.md) - sign-share-extract deep dive
- [Architecture](architecture.md) - the substrate diagram
- [Sign, share, extract tutorial](../tutorials/sign_share_extract.md)
- [Citizen DSAR tutorial](../tutorials/citizen_dsar.md)
