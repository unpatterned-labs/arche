---
applyTo:
  - "packages/arche-core/src/arche/sign/**/*.py"
  - "packages/arche-core/src/arche/credentials/**/*.py"
  - "packages/arche-core/src/arche/workflow/dsar.py"
  - "packages/arche-core/tests/test_sign*.py"
  - "packages/arche-core/tests/test_credentials*.py"
  - "packages/arche-core/tests/test_dsar*.py"
---

# Signing, credentials, and verifiability

## Roadmap context
This layer is the substrate for the **sign-share-extract identity workflow** (verifiability roadmap, locked 2026-06-02). Party A signs a document + its policy-applied detection set; Party B verifies offline and extracts identity claims selectively.

Layers:
- `arche.sign` — Ed25519 + did:key + JWS envelope. Pure-Python via `cryptography`.
- `arche.credentials` — SD-JWT-VC (IETF selective-disclosure JWT). Used by EUDI Wallet ARF and MOSIP Inji.
- `arche.workflow.dsar` — citizen-side Data Subject Access Request workflow. Stage 1 ships **`dispatch_mode="draft_only"`** only.

PQC (Ed25519 + ML-DSA per NIST FIPS 204) is **Stage 2** as the `arche-core[pqc]` extra. Do not implement PQC primitives speculatively — write the narrative, ship the hybrid envelope shape, defer the cryptography.

## Hard rules
- **arche never stores private keys.** Every keypair is caller-held. `generate_keypair()` returns a `Keypair` dataclass; the consumer is responsible for persistence. If you find code that writes a private key to a default location, that's a bug.
- **Verification is offline.** The `kid` in every JWS embeds the `did:key`, so the verifier needs no resolver, no DID registry, no network. Any change that introduces a network call into `verify()` is a regression.
- **The envelope is versioned.** `ENVELOPE_SCHEMA_VERSION` in `arche/sign/envelope.py` must be bumped for any breaking change to the signed-document shape. Old envelopes must remain verifiable.
- **SD-JWT-VC is the v0.2 credential format.** JSON-LD VC 1.1 via `didkit` is Stage 3 (`arche-core[didkit]`). Do not pull JSON-LD libraries into the base install.

## DSAR workflow constraints (Stage 1)
- `dispatch_mode="draft_only"` is the **only** supported mode. The workflow generates a compliant draft letter + a cryptographic envelope; the citizen reviews and dispatches manually.
- Autonomous dispatch is **deferred to Stage 4** with explicit consent mechanisms because incorrect legal letters dispatched at scale could cause real harm (PRD §7.4, §15.3).
- Org-side DSAR receipt + automated response is **Stage 3** work. Do not start it here.

## What to do
- New signature primitives → `arche/sign/jws.py` (low-level) or `arche/sign/workflow.py` (high-level).
- New credential formats → `arche/credentials/<format>.py` with its own `issue_*`, `verify_*`, and `present` functions. Mirror the SD-JWT module structure.
- New DSAR statute templates → `arche/workflow/_dsar_templates.py`. Pair with a `tests/test_dsar_<country>.py` fixture.

## What to NOT do
- Do not add a key-management service. The SDK is **stateless about keys** by design.
- Do not import network libraries (`httpx`, `requests`) into `arche.sign` or `arche.credentials`. Both must work air-gapped.
- Do not write your own crypto primitives. Use `cryptography` for Ed25519 / ECDSA / RSA; use the `jwcrypto` or hand-rolled JWS only if it's been reviewed; SD-JWT-VC goes through the existing reference implementations.

## Tests
- `tests/test_sign_*.py` — round-trip sign / verify with offline key handling.
- `tests/test_credentials_*.py` — SD-JWT-VC issue / present / verify, including selective disclosure.
- `tests/test_dsar_*.py` — DSAR letter generation per jurisdiction, draft-only assertion.
- Every test that mints a keypair should do so in-test (`generate_keypair()`); **never** check in a private key, even a "test" one.
