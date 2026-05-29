# Quick Start

Your first NDPA-compliant redaction in five minutes, then four power-user workflows that compose on top. Every example is copy-paste ready.

!!! tip "If you're new to arche-core, start with Example 1 and stop there"
    Example 1 — the `Pipeline` primitive — is the lead use case and covers ~95% of what most users need. Examples 2 onward are **power-user workflows** that build on the same primitives. Read them when you have a specific use case for signed envelopes, citizen DSAR drafting, wallet credentials, or standalone audit logs.

---

## 1. The Pipeline primitive — NDPA-2023 enforcement in one call

```python
from arche import Pipeline

pipeline = Pipeline(jurisdiction="NG", tokenize_salt="bank_2026")

text = (
    "Customer Adesola Okonkwo registered with NIN 12345678901 "
    "and BVN 22156789012. Contact phone 0803 555 7890. RC 245678."
)

result = pipeline.process(text)
print(result.redacted_text)
```

Output:

```
Customer Adesola Okonkwo registered with NIN [NIN] and BVN [BVN].
Contact phone PHONE_.... RC 245678.
```

The `Pipeline` auto-resolves `jurisdiction="NG"` to the NDPA-2023 statute YAML, runs the per-country detectors, applies the closed action set, and returns a typed `Result` with detections, policy outcomes, redacted text, and audit log entries.

Inspect the policy decisions:

```python
for o in result.policy_outcomes:
    print(f"{o.category:25s} -> {o.action:10s} ({o.statute_reference})")
```

```
PII-2-RC                  -> retain     (NDPA-2023 s.31 (legitimate interests))
PII-2-BVN                 -> mask       (NDPA-2023 s.30, CBN BVN policy 2014)
PII-2-NIN                 -> mask       (NDPA-2023 s.30, NIMC Act s.27)
```

Same code, different jurisdictions:

```python
Pipeline(jurisdiction="ZA")       # auto-loads POPIA
Pipeline(jurisdiction="KE")       # auto-loads KENYA-DPA
Pipeline(jurisdiction="GH")       # auto-loads GHANA-DPA
```

That's the whole core workflow. If this is all you need, skip the rest and go to [How arche Works](../concepts/how-it-works.md) or the [API Reference](../api/index.md).

---

# Power-user workflows

The four examples below ship in the package and are fully tested, but they are not the lead pitch. Read the one that matches your use case; skip the rest. They all compose on top of the `Pipeline` primitive from Example 1.

---

## 2. Sign, share, extract

```python
from arche.sign import SignWorkflow, VerifyExtractWorkflow, generate_keypair

# Party A — Bank's compliance officer
bank_key = generate_keypair()
signer = SignWorkflow(jurisdiction="NG", tokenize_salt="bank_2026")
signed = signer.sign(
    "Customer Adesola Okonkwo, NIN 12345678901, BVN 22156789012.",
    bank_key,
    purpose="dsar_response",
)
# signed is a JWS compact string ~1000 chars

# Wire transit happens here

# Party B — Recipient verifies offline
verifier = VerifyExtractWorkflow()
result = verifier.process(signed)

print(result.signature_valid)        # True (cryptographic verification)
print(result.issuer_did)              # bank's did:key
print(result.statute_at_signing)      # "NDPA-2023@v1.0"
print(result.redacted_text)           # "... NIN [NIN], BVN [BVN] ..."
```

The recipient verifies offline using the `did:key` embedded in the JWS header — no infrastructure, no resolver, no network call. The signature binds the entire envelope: the recipient can trust the redacted text, the detections, and the policy outcomes are exactly what the bank processed.

[Full sign-share-extract tutorial →](../tutorials/sign_share_extract.md)

---

## 3. Citizen-side DSAR

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
    request_type="access",
    targets=[
        DSAROrganization(name="Sterling Bank", dpo_email="dpo@sterlingbank.ng"),
        DSAROrganization(name="MTN Nigeria", dpo_email="dpo@mtn.ng"),
    ],
)

result = wf.run(citizen_key)
for draft in result.drafts:
    print(draft.letter_text)            # NDPA-2023 s.34 cited
    print(draft.signed_envelope)        # JWS for the DPO to verify
```

Each draft cites the correct statute section per jurisdiction:

- NDPA-2023 s.34 (Right of Access)
- POPIA s.23 (Access to personal information)
- Kenya DPA s.26(a) (Right of Access)
- Ghana DPA s.35 (Access to personal data)

Stage 1 ships `dispatch_mode="draft_only"`. The citizen reviews and dispatches manually; autonomous dispatch is Stage 4 with explicit consent mechanisms.

[Citizen DSAR tutorial →](../tutorials/citizen_dsar.md)

---

## 4. SD-JWT-VC with selective disclosure

```python
from arche.credentials import envelope_to_sd_jwt, present, verify_sd_jwt
from arche.sign import ArcheSignedDocument, generate_keypair
from arche import Pipeline

issuer_key = generate_keypair()
pipeline = Pipeline(jurisdiction="NG")
result = pipeline.process("Customer Adesola Okonkwo, NIN 12345678901.")

# Wrap in a signed envelope, then re-frame as SD-JWT-VC
envelope = ArcheSignedDocument.from_pipeline_result(
    result, issuer_did=issuer_key.did_key, purpose="kyc_attestation",
)
sd_jwt = envelope_to_sd_jwt(envelope, issuer_key=issuer_key)

# Holder presents only jurisdiction + purpose; hides everything else
presentation = present(sd_jwt.compact, disclose=["jurisdiction", "purpose"])

v = verify_sd_jwt(presentation)
print(v.disclosed_claims)
# {"jurisdiction": "NG", "purpose": "kyc_attestation"}
# Verifier cannot see detections, redacted_text, or doc_hash
```

SD-JWT-VC is the IETF selective-disclosure credential format that EUDI Wallet ARF and MOSIP Inji standardize on. The issuer signs the full credential; the holder controls which claims to disclose to each verifier; the verifier rejects any disclosure that doesn't match the signed `_sd` hashes.

---

## 5. SQLite audit log + signed regulator export

```python
from arche.graph.audit import AuditLog, AuditEvent
from arche.sign import generate_keypair

audit = AuditLog("./arche-audit.sqlite")     # or ":memory:" for ephemeral

# Emit detection events (typically done by Pipeline automatically)
audit.emit(AuditEvent.detection(
    document_hash="doc_001",
    category="PII-2-NIN",
    span=(30, 41),
    confidence=0.95,
    detector="rule:ng_nin",
))

# Markdown compliance report
print(audit.compliance_report_markdown())

# Signed export bundle (JWS) for regulator handoff
compliance_key = generate_keypair()
signed_bundle = audit.export_signed(key=compliance_key, purpose="ndpc_audit")
```

The audit log is append-only by convention. PII values are never stored — only category labels and character spans. Signed exports give the regulator cryptographic non-repudiation of what the deployment processed.

---

## What's next

<!-- - [How arche Works — the v0.2 thesis](../concepts/how-it-works.md)
- [Verifiable identity workflows](../concepts/verifiability.md) -->
- [Sign, share, extract tutorial](../tutorials/sign_share_extract.md)
- [Citizen DSAR tutorial](../tutorials/citizen_dsar.md)
- [API Reference](../api/index.md)
