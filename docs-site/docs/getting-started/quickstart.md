# Quick Start

Four verbs, five minutes, no API key. `detect` finds the entities and identifying data, `resolve` works out which real-world thing each one refers to, `protect` applies the law that governs it, and `attest` signs the result. Everything below was run against v0.3.0a1 and the output is what it actually printed.

```bash
pip install arche-core
```

The base install is pure Python and runs offline. Heavy capabilities are opt-in extras.

---

## 1. detect + protect: one call

Detection and policy are a single pass, because a detection without the rule that classifies it is not much use.

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

```text
Customer Adesola Okonkwo registered with NIN [NIN] and BVN [BVN]. Contact phone PHONE_847fca26. RC 245678.
```

Each detection carries the statute section that classified it, and one of six closed actions:

```python
for o in result.policy_outcomes:
    print(f"{o.category:12} -> {o.action:10} {o.statute_reference}")
```

```text
PII-2-RC     -> retain     NDPA-2023 s.31 (legitimate interests)
PII-2-BVN    -> mask       NDPA-2023 s.30, CBN BVN policy 2014
PII-2-NIN    -> mask       NDPA-2023 s.30, NIMC Act s.27
PII-3-PHONE  -> tokenize   NDPA-2023 s.30
```

`RC 245678` survives on purpose — a company registration number is public under NDPA s.31, and the pack says `retain`. The phone becomes a deterministic token, so the same number in two systems yields the same string and can still be joined on without ever being read.

!!! warning "Always check what was detected, not just what came back"

    `Adesola Okonkwo` is **not** redacted above. The name detector runs, but this name is not in the lexicon, so nothing was found and nothing was removed. `redacted_text` looks clean either way. Print `result.detections` and confirm the list is what you expected — an empty list means nothing was redacted, not that nothing was there. Install `arche-core[detect]` for GLiNER-backed name detection.

Same call, different law:

```python
Pipeline(jurisdiction="ZA")   # POPIA
Pipeline(jurisdiction="KE")   # Kenya DPA
Pipeline(jurisdiction="GH")   # Ghana DPA
Pipeline(jurisdiction="DE")   # GDPR
```

---

## 2. resolve: which real thing is this?

Two records, two spellings, one national ID:

```python
from arche import resolve
from arche.canonical import Reference

a = Reference.from_record({"name": "Fatima Abdullahi", "national_id": "12345678901"})
b = Reference.from_record({"name": "Fatuma Abdulahi",  "national_id": "12345678901"})

decision = resolve.pairwise(a, b)
print(decision.identity, decision.score)
```

```text
same_entity 1.0
```

`identity` is one of `same_entity`, `different`, or **`review`**. That third answer is the point of the whole engine, and the next example is where you see it earn its place.

### Whole lists: `crosswalk`

```python
from arche import resolve

registry = [
    {"name": "Karfi Health Post",    "lat": "11.62", "lon": "8.49"},
    {"name": "Tsalle Health Post",   "lat": "11.71", "lon": "8.33"},
    {"name": "Yan Bawa Health Post", "lat": "11.50", "lon": "8.00"},
]
survey = [
    {"name": "Karfi Health Clinic",              "lat": "11.62", "lon": "8.49"},
    {"name": "Tsalle Primary Health Care Centre","lat": "11.71", "lon": "8.33"},
    {"name": "Yan Bawa Health Post",             "lat": "12.50", "lon": "9.00"},
]

result = resolve.crosswalk(registry, survey, entity="place")

for m in result["matches"]:
    ev = m["evidence"]
    print(f'{m["decision"]:7} {m["score"]:.3f} {ev.get("distance_km", 0):7.2f} km  '
          f'{registry[m["a_id"]]["name"]:22} <-> {survey[m["b_id"]]["name"]}')
```

```text
review  0.800  155.54 km  Yan Bawa Health Post   <-> Yan Bawa Health Post
match   0.730    0.00 km  Karfi Health Post      <-> Karfi Health Clinic
review  0.631    0.00 km  Tsalle Health Post     <-> Tsalle Primary Health Care Centre
```

Three rows, three different behaviours, and they are worth reading one at a time.

**Row 2 is a merge.** `Karfi Health Post` and `Karfi Health Clinic` are the same place at the same coordinates; the facility-type words differ and the distinctive part agrees.

**Row 1 is the geographic veto.** The names are byte-identical — every name comparator scores 1.0 — and the records sit 155 km apart. Distance is a physical constraint rather than a weighted preference, so the pair is demoted. Note it is demoted to `review`, never dropped: distance says a human must look, not that the answer is no.

**Row 3 is a tier difference.** Same settlement, but a health post and a primary health care centre are different levels of care with different staffing. Plausible, not distinctive, so it waits for a person.

None of those three needed a model, a network call, or an API key.

---

## 3. attest: sign the decision

A decision is worth what your ability to defend it later is worth.

```python
from arche import resolve
from arche.canonical import Reference
from arche.attest import attest, verify_attestation
from arche.sign import generate_keypair

ISSUER_KEY = b"replace-with-a-real-32-byte-secret!"   # >= 32 bytes

a = Reference.from_record({"name": "Fatima Abdullahi", "national_id": "12345678901"})
b = Reference.from_record({"name": "Fatuma Abdulahi",  "national_id": "12345678901"})
decision = resolve.pairwise(a, b, issuer_key=ISSUER_KEY)

kp = generate_keypair()
signed = attest(decision, kp, mode="jws")

v = verify_attestation(signed.compact, public_key=kp.public_key)
print(v.valid, v.trusted, v.reproducible)
print(decision.decision_id)
```

```text
True True True
dec:hmac-sha256:f5f26b63420a418b2b4774fd584c131e84ca904c05df310a253a85a731789af8
```

Three separate questions, and conflating them is the mistake this API exists to prevent. `valid` — does the signature match the key it was checked against? `trusted` — did that key come from somewhere **you** control, rather than one the token named for itself? `reproducible` — can the decision be replayed from its evidence? Had a language model extracted the fields, `reproducible` would read `False`.

**Always check `trusted`, not just `valid`.** Verifying without pinning a key proves a token is internally consistent, not that anyone in particular made it.

`decision_id` is a content address over the evidence and the exact representation that produced it. Same inputs and same key, same id — tomorrow or in five years.

---

# Power-user workflows

The four examples below ship in the package and are fully tested, but they are not the lead pitch. Read the one that matches your use case; skip the rest. They all compose on top of the `Pipeline` primitive from Example 1.

---

## 2. Sign, share, extract

```python
from arche.sign import SignWorkflow, VerifyExtractWorkflow, generate_keypair

# Party A - Bank's compliance officer
bank_key = generate_keypair()
signer = SignWorkflow(jurisdiction="NG", tokenize_salt="bank_2026")
signed = signer.sign(
    "Customer Adesola Okonkwo, NIN 12345678901, BVN 22156789012.",
    bank_key,
    purpose="dsar_response",
)
# signed is a JWS compact string ~1000 chars

# Wire transit happens here

# Party B - Recipient verifies offline
verifier = VerifyExtractWorkflow()
result = verifier.process(signed)

print(result.signature_valid)        # True (cryptographic verification)
print(result.issuer_did)              # bank's did:key
print(result.statute_at_signing)      # "NDPA-2023@v1.0"
print(result.redacted_text)           # "... NIN [NIN], BVN [BVN] ..."
```

The recipient verifies offline using the `did:key` embedded in the JWS header - no infrastructure, no resolver, no network call. The signature binds the entire envelope: the recipient can trust the redacted text, the detections, and the policy outcomes are exactly what the bank processed.

[Full sign-share-extract tutorial](../tutorials/sign_share_extract.md)

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

[Citizen DSAR tutorial](../tutorials/citizen_dsar.md)

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

The audit log is append-only by convention. PII values are never stored - only category labels and character spans. Signed exports give the regulator cryptographic non-repudiation of what the deployment processed.

---

## What's next

- [Sign, share, extract tutorial](../tutorials/sign_share_extract.md)
- [Citizen DSAR tutorial](../tutorials/citizen_dsar.md)
- [API Reference](../api/index.md)
