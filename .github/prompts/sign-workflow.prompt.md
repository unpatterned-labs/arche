---
mode: agent
description: Implement or extend a signing / credentials / DSAR workflow.
---

# Sign / credentials / DSAR workflow change

Use this for changes in `arche/sign/`, `arche/credentials/`, or `arche/workflow/dsar.py`. The constraints are tighter here because the artefacts are legally meaningful.

## 1. Read first
- `.github/instructions/signing-and-credentials.instructions.md` — hard rules (offline verification, caller-held keys, envelope versioning).
- The verifiability roadmap (`docs/` — search for `verifiability_roadmap`).
- The existing module nearest to where the change lives.

## 2. Scope confirmation
State which **artefact shape** you are changing:
- A new signature algorithm → likely `arche/sign/keys.py` + `arche/sign/jws.py`.
- A new envelope claim → bump `ENVELOPE_SCHEMA_VERSION` in `arche/sign/envelope.py`.
- A new credential format → new module under `arche/credentials/` mirroring the SD-JWT-VC structure.
- A new DSAR template → `arche/workflow/_dsar_templates.py` + a test fixture.

If you can't name the artefact shape, the scope is wrong.

## 3. Cryptographic hygiene
- **No hand-rolled crypto.** Use the `cryptography` library for Ed25519 / ECDSA / RSA primitives.
- **Caller-held keys.** Your code generates keypairs and returns them; it does not persist them to a default location. If persistence is needed, the caller passes a path explicitly.
- **Offline verification.** Any signing change that requires the verifier to make a network call is a regression. The `kid` in the JWS header embeds the `did:key`, which carries the public key — no resolver, no registry.
- **PQC is Stage 2.** Do not implement post-quantum primitives speculatively. The narrative + hybrid envelope shape is enough for v0.2.

## 4. Envelope versioning
If you change the signed-document shape:
- Bump `ENVELOPE_SCHEMA_VERSION` in `arche/sign/envelope.py`.
- Keep old envelopes verifiable — add a path through `verify()` that handles the previous shape.
- Add a regression test that loads a v(previous)-encoded envelope and successfully verifies it.

## 5. DSAR constraints (Stage 1)
- `dispatch_mode="draft_only"` is the **only** supported mode through Stage 4. Do not add an autonomous-dispatch path even if it would be technically easy.
- DSAR letter templates per jurisdiction live in `_dsar_templates.py` — additive changes only; never remove a jurisdiction's template without a deprecation cycle.
- The output is **a draft + a signed envelope**. The citizen reviews and dispatches manually. This is by design (PRD §7.4, §15.3).

## 6. Tests
- Round-trip: `sign(payload) → verify(jws)` returns the original payload byte-equal.
- Tampering: mutate one byte of the JWS and assert verification fails.
- Wrong key: verify with a different `did:key` and assert failure.
- Offline: confirm verification works with `socket.socket` patched to raise (proves no network).
- Envelope versioning: load a v(previous) envelope and verify successfully.
- DSAR: per jurisdiction, assert the letter contains the regulator-required clauses (cite the section in the test name).

## 7. PR summary
- One sentence: what changed and why.
- The artefact shape impact (envelope version bump, new claim, new template).
- The cryptographic primitive used (cite library + algorithm).
- The offline-verifiability guarantee (which test proves it).

## Hard "no"s
- No private keys in fixtures. Generate in-test.
- No `httpx` / `requests` import in `arche.sign` or `arche.credentials`.
- No autonomous DSAR dispatch.
- No "trust on first use" — every verification is keypair-bound from byte one.
