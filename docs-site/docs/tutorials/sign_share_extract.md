# Tutorial: Sign, share, extract

A walkthrough of the headline arche-core v0.2 capability. A bank's compliance officer signs a customer record under NDPA-2023; a regulator verifies the signature offline and recovers what was processed.

## What you'll build

A complete end-to-end flow:

1. **Process** a Nigerian customer record through `Pipeline` under NDPA-2023.
2. **Sign** the result with the bank's `did:key`.
3. **Share** the signed envelope (a single string).
4. **Verify** offline at the recipient.
5. **Re-frame** as SD-JWT-VC for wallet-ecosystem consumers.

No external services. No infrastructure. Pure crypto + structured JSON.

## Setup

```bash
pip install arche-core
```

That's the full dependency surface for this tutorial. No extras
required.

## Step 1 — Process the document

```python
from arche import Pipeline

pipeline = Pipeline(
    jurisdiction="NG",                    # auto-loads NDPA-2023
    tokenize_salt="sterling_bank_2026",   # per-org secret
)

document = (
    "Customer Adesola Okonkwo registered with NIN 12345678901 "
    "and BVN 22156789012. Contact phone 0803 555 7890. "
    "Company: RC 245678."
)

result = pipeline.process(document)
print(result.redacted_text)
```

Output:

```
Customer Adesola Okonkwo registered with NIN [NIN] and BVN [BVN]. Contact phone PHONE_.... Company: RC 245678.
```

NIN and BVN are masked (NDPA-2023 s.30); the phone is **tokenized** (s.30) so records stay linkable; RC is retained (s.31, legitimate interests). The name `Adesola Okonkwo` is left untouched here because it isn't in the bundled name lexicon — add GLiNER soft-PII detection via `arche-core[detect]` to tokenize free-form names too.

## Step 2 — Sign

Generate an Ed25519 keypair for the bank's compliance officer:

```python
from arche.sign import generate_keypair

bank_key = generate_keypair()
print(bank_key.did_key)
# did:key:z6MkTestSomethingSomethingPublicKey
```

`generate_keypair()` produces a `Keypair` carrying the private key (held locally), the public key, and the canonical `did:key` identifier. The public key is *encoded into* the `did:key` string — no separate distribution needed.

Now sign the document via `SignWorkflow`:

```python
from arche.sign import SignWorkflow

signer = SignWorkflow(
    jurisdiction="NG",
    statute="NDPA-2023",
    tokenize_salt="sterling_bank_2026",
)

signed_envelope = signer.sign(
    document,
    bank_key,
    purpose="dsar_response",          # free-form intent tag
)

print(signed_envelope[:80] + "..." + signed_envelope[-20:])
```

`signed_envelope` is a JWS compact-form string: three base64url-encoded segments separated by dots. Header, payload (the `ArcheSignedDocument` carrying the full `Pipeline.Result`), signature.

The whole thing is around 1000 characters. Email it, ship it in an HTTP body, encode it in a QR code, write it to disk. It's a string.

## Step 3 — Share

There's no step 3 in code. The signed envelope is a single string. Send it however you'd send any other string.

The recipient needs nothing in advance — no public key out-of-band, no PKI infrastructure, no resolver. The `did:key` in the JWS `kid` header carries the public key encoded directly. Verification is offline.

## Step 4 — Verify and extract

At the recipient:

```python
from arche.sign import VerifyExtractWorkflow

verifier = VerifyExtractWorkflow(
    require_purpose="dsar_response",   # reject other purposes
    require_jurisdiction="NG",          # reject cross-jurisdiction misuse
    check_expiry=True,
)

extracted = verifier.process(signed_envelope)

print(extracted.signature_valid)
print(extracted.issuer_did)              # bank's did:key
print(extracted.statute_at_signing)      # "NDPA-2023@v1.0"
print(extracted.redacted_text)
print(extracted.policy_outcomes)
```

What the recipient now knows:

- **Who signed**: cryptographically. The `did:key` is the public key; the   signature verified against it. No third party needed.
- **When**: `issued_at` is in the envelope.
- **What statute was applied**: `NDPA-2023@v1.0`.
- **What was detected**: category codes (`PII-2-NIN`, `PII-2-BVN`, ...).
- **What was redacted**: the `[NIN]` and `[BVN]` placeholders mark the spans the bank masked.

What the recipient cannot do:

- See the original PII values (they're not in the envelope).
- Reverse the tokens (the salt is held by the bank).
- Modify any of the above (any change breaks the signature).

## Step 5 — Re-frame as SD-JWT-VC

For wallet-ecosystem consumers (EUDI Wallet, MOSIP Inji), re-frame the envelope as an SD-JWT Verifiable Credential:

```python
from arche.sign import ArcheSignedDocument
from arche.credentials import envelope_to_sd_jwt, present, verify_sd_jwt

# Step 1: rebuild the envelope (or keep it from when you signed)
envelope = ArcheSignedDocument.from_pipeline_result(
    result, issuer_did=bank_key.did_key, purpose="dsar_response",
)

# Step 2: convert to SD-JWT-VC. Every envelope field is disclosable.
sd_jwt = envelope_to_sd_jwt(envelope, issuer_key=bank_key)

# Step 3: holder discloses only the statute, hides everything else
presentation = present(sd_jwt.compact, disclose=["jurisdiction", "statute"])

# Step 4: third party verifies the presentation
v = verify_sd_jwt(presentation)
print(v.disclosed_claims)
# {"jurisdiction": "NG", "statute": "NDPA-2023@v1.0"}
```

The third party knows the credential was issued by the bank (signature binds the whole credential) under NDPA-2023 jurisdiction — but cannot see which categories of PII were detected, what redacted text was produced, or the document hash.

## What's next

- [Citizen DSAR tutorial](citizen_dsar.md) — uses the same primitives to
  generate compliant DSAR letters for NDPA / POPIA / Kenya DPA / Ghana DPA.
<!-- - [Verifiability concepts](../concepts/verifiability.md) — the
  architectural rationale for JWS, did:key, Ed25519, SD-JWT-VC. -->
- [API: `arche.sign`](../api/sign.md) — full reference.
- [API: `arche.credentials`](../api/credentials.md) — SD-JWT-VC details.
