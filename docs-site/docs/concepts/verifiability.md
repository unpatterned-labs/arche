# Verifiability: the signature on the decision

Every other page here is about reaching a decision — this one is about
proving which decision you reached, to someone who was not there. The
verifiability layer (`arche.sign`, `arche.attest`,
`arche.credentials.sd_jwt`) turns a `Pipeline.Result` or a resolution
edge into a claim a stranger can check offline, and it is the reason
[place identity](place-identity.md) and [from place to
entity](from-place-to-entity.md) can say *given this evidence and this
representation, this was the decision* and mean something by it.

> arche is a library, not an issuer. It never holds a long-lived key. Callers provide their own Ed25519 keys; arche signs with them. This is the only model compatible with sovereign / on-premises deployments.

## The sign-share-extract chain

`arche.sign` and `arche.credentials` let two parties exchange identity
claims without trusting an intermediary.

```
┌─────────────────────────┐                  ┌─────────────────────────┐
│  Issuer (Party A)       │                  │  Verifier (Party B)     │
│  - holds Ed25519 key    │                  │  - holds nothing        │
│  - runs Pipeline        │   JWS envelope   │  - verifies offline     │
│  - signs Result         │ ───────────────► │    against did:key      │
│                         │   wire transit   │    in JWS kid header    │
└─────────────────────────┘                  └─────────────────────────┘
```

The signed envelope carries:

- The document hash (SHA-256 of the original)
- The full `Pipeline.Result` (detections, policy outcomes, redacted text)
- Issuer `did:key` (the public key, self-describing)
- Issued timestamp + optional expiry
- Free-form purpose tag (`"dsar_response"`, `"kyc_attestation"`, ...)
- Jurisdiction + statute version

The verifier recovers everything *except* the original document text.
The redacted text and policy outcomes are signed, so the verifier can
trust them - but the issuer's tokenize salt isn't in the envelope, so
tokens can't be reversed by anyone other than the issuer.

---

## Why JWS, not PAdES, not raw JSON-LD VC

We considered three container formats:

| Format | Pros | Why we didn't pick it |
|---|---|---|
| **PAdES** (signed PDF) | Standard for legal contracts | Signs the PDF, not the structured detection tuple. arche's value is the policy-outcome set, not the PDF. |
| **W3C VC 1.1 JSON-LD** | Wallet ecosystem familiarity | JSON-LD context resolution plus URDNA2015 canonicalisation adds a dereferencing step and a graph-normalisation step before you can verify anything. Both are places a deployment can silently diverge. |
| **JWS** ✓ | Interoperable, simple, what EUDI Wallet ARF and MOSIP e-signet use under the hood | (selected) |

JWS over canonical JSON is the boring, interoperable, JOSE-stack-
compatible default. Every language has a verifier. SD-JWT-VC and signed
JWT are JWS underneath.

PAdES and JSON-LD VC 1.1 are not ruled out — if a deployment needs
either, they belong behind opt-in extras rather than in the base wheel.
Neither ships today.

---

## Why Ed25519, not ECDSA or RSA

Ed25519 is the modern default. Small (32-byte keys, 64-byte signatures),
fast on CPU, deterministic (no nonce-reuse footgun). EUDI Wallet, MOSIP
e-signet, and DIF / W3C examples all default to EdDSA.

**Ed25519 is the only algorithm implemented.** `alg` is `EdDSA` and
nothing else; there is no ECDSA or RSA-PSS path today. The two obvious
candidates, if a deployment forces them, are ECDSA P-256 (for FIPS-only
environments, at the cost of nonce management) and RSA-PSS (for legacy
PKI interop, since some e-government CAs still issue RSA certs). Both
belong behind opt-in extras; neither exists yet.

---

## Why `did:key`, not `did:web` or PEM

A `did:key:z6Mk...` identifier is **self-describing**: the base58btc-
multibase-encoded suffix contains the actual public key. A verifier
resolves it offline by decoding the suffix - no network call, no PKI,
no infrastructure.

This is the only DID method that works in an air-gapped deployment.
Where verifiers may be field tablets with intermittent connectivity,
that matters more than ecosystem familiarity.

Scope, plainly: `did:key` is the only DID method arche implements.
Keys can be loaded and exported as PEM (`load_private_key_pem`,
`export_public_pem`), but there is no `did:web` resolution, no key
provider abstraction, and no HSM / PKCS#11 signing. Signing with a key
you hold is the whole model.

---

## SD-JWT-VC - wallet interoperability

`arche.credentials.sd_jwt` re-frames an `ArcheSignedDocument` as an
IETF SD-JWT-VC. Why SD-JWT-VC and not W3C VC 1.1 JSON-LD? Because the
EUDI Wallet architecture reference framework specifies SD-JWT-VC (IETF,
selective disclosure, JWS-based), and SD-JWT-VC is structurally the
same as our envelope already — JWS over a JSON claim set with
disclosure logic on top. Picking it costs us nothing and buys wallet
interop.

```python
from arche import Pipeline
from arche.sign import ArcheSignedDocument, generate_keypair
from arche.credentials import envelope_to_sd_jwt, present, verify_sd_jwt

issuer_key = generate_keypair()
result = Pipeline(jurisdiction="NG").process(
    "Customer Adesola Okonkwo, NIN 12345678901."
)
envelope = ArcheSignedDocument.from_pipeline_result(
    result, issuer_did=issuer_key.did_key, purpose="kyc_attestation"
)

sd_jwt = envelope_to_sd_jwt(envelope, issuer_key=issuer_key)

# Holder presents only some claims
presentation = present(sd_jwt.compact, disclose=["jurisdiction"])
v = verify_sd_jwt(presentation)
# v.disclosed_claims -> {"jurisdiction": "NG"}
```

Each disclosable claim is a base64url-encoded `[salt, name, value]`
tuple. The JWT payload carries a `_sd` array of SHA-256 hashes; the
disclosures are appended to the JWT with `~` separators. The holder
decides which disclosures to forward; the verifier rejects any
disclosure whose hash isn't in `_sd`.

The result: cryptographic non-repudiation of issuer claims +
privacy through holder-controlled disclosure.

---

## Audit log - regulator-ready provenance

Every detection and policy decision flows into `arche.graph.audit` - a
SQLite-backed append-only log.

- **No PII values stored** - only category labels, character spans, and
  document hashes.
- **Append-only by convention** - modifications require explicit
  migration calls. This is a convention, not an enforced guarantee.
- **Markdown compliance reports** - `audit.compliance_report_markdown()`
  renders a regulator-readable summary.
- **Signed exports** - `audit.export_signed(key=...)` emits a
  JWS-wrapped bundle. Any auditor can verify offline that the bundle
  hasn't been tampered with after signing.

The schema includes nullable `prev_hash` and `signature` columns, but
**nothing populates them today**. Hash-chained tamper detection is
[in-flight work](roadmap.md#in-flight); the schema is ready for it so
that landing it needs no migration. Until then, a signed export proves
the bundle wasn't altered *after signing* — it does not prove that no
row was removed before.

---

## Post-quantum signatures - not shipped

NIST ratified ML-DSA (FIPS 204) and ML-KEM (FIPS 203) in August 2024,
and hybrid Ed25519 + ML-DSA signing is the obvious next step: the
envelope grows a second signature and verifiers without ML-DSA support
skip it gracefully. It is designed, not built — `arche-core[pqc]` does
not exist, and `liboqs-python` wheels are still not universal across the
CPU/OS combinations arche has to run on. Ed25519 is the only algorithm
today, and this section is here so nobody plans around a signature
arche cannot yet produce.

---

## What this gives you

- **Tamper-evident envelopes.** Every signed envelope binds the document
  hash, the detection set, and the policy decisions. (The *log* is not
  tamper-evident — see above.)
- **Offline verification.** Recipient needs nothing but the JWS string.
- **Wallet-format interoperability.** SD-JWT-VC is the format the EUDI
  Wallet ARF specifies.
- **Auditable trails.** Markdown reports + signed exports.
- **Sovereignty.** Library, not issuer. No arche-the-org root key.

Deterministic, offline-verifiable, and sovereignty-friendly, with the
gaps named rather than implied.
