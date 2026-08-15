# Attest: the signature on the decision

*What an arche attestation actually guarantees, the difference between a valid signature and a trusted one, and why the format choices were made the way they were.*

---

Every other concept page here is about reaching a decision. This one is about proving which decision you reached, to someone who was not there.

An attestation binds three things together under one signature: the **decision**, the **evidence** that produced it, and the **pins**. The versions of every component involved, including the declaration that decided what the records meant. The claim it makes is deliberately narrow:

> Given this evidence and this representation, this was the decision.

It is not a claim that the two records *are* the same entity for all time. Places move, people change names, registries are re-keyed. A system that signed "these are the same" would be signing something it cannot know. Signing "under these inputs, this engine concluded this" is a claim that stays true.

> arche is a library, not an issuer. It never holds a long-lived key. Callers provide their own Ed25519 keys and arche signs with them. This is the only model compatible with sovereign and on-premises deployments. There is no arche-the-organisation root key to trust, revoke, or subpoena.

---

## `valid` is not `trusted`

This is the correction to make before anything else on this page, because it changes how verification code should be written.

A signature verifies *against a key*. The question that matters is where that key came from. If it came from the token itself. The `kid` header. Then the signer chose it, and an impostor can sign anything with their own keypair and set a matching `kid`. The signature will verify perfectly. It proves the token is internally consistent. It proves nothing about who issued it.

`VerificationResult` says so in two fields:

- **`valid`**. The signature matches the key that was resolved.
- **`trusted`**. That key came from somewhere the caller controls: a pinned `public_key`, or their own `resolver`. A self-asserted key is never trusted.
- **`key_source`**. `"pinned"`, `"resolver"`, or `"self-asserted"`.

`verify()` now **fails closed**. `allow_did_key_from_kid` defaults to `False`; it defaulted to `True` through v0.3.0a1. Calling the obvious function with the obvious arguments no longer quietly trusts the attacker's own key.

```python
from arche.sign import generate_keypair
from arche.sign.jws import sign, verify

issuer = generate_keypair()
token = sign({"claim": "the bearer is a licensed clinic"}, issuer.private_key,
             kid=issuer.did_key)

# An impostor signs the same claim with their own key, naming their own kid.
impostor = generate_keypair()
forged = sign({"claim": "the bearer is a licensed clinic"}, impostor.private_key,
              kid=impostor.did_key)

def report(label, result):
    print(f"{label:34} valid={result.valid!s:5} trusted={result.trusted!s:5} "
          f"key_source={result.key_source}")

report("genuine, no key", verify(token))
report("genuine, self-asserted key", verify(token, allow_did_key_from_kid=True))
report("genuine, pinned key", verify(token, public_key=issuer.public_key))
report("FORGED, self-asserted key", verify(forged, allow_did_key_from_kid=True))
report("FORGED, pinned key", verify(forged, public_key=issuer.public_key))

print()
print(verify(token).error)
```

```text
genuine, no key                    valid=False trusted=False key_source=None
genuine, self-asserted key         valid=True  trusted=False key_source=self-asserted
genuine, pinned key                valid=True  trusted=True  key_source=pinned
FORGED, self-asserted key          valid=True  trusted=False key_source=self-asserted
FORGED, pinned key                 valid=False trusted=False key_source=pinned

No trusted key available: pass public_key=, or a resolver=. To verify a token's integrity without authenticating its issuer, pass allow_did_key_from_kid=True — but note that a self-asserted key proves nothing about who signed.
```

Read rows two and four together. They are indistinguishable on `valid`. Only `trusted` separates the genuine issuer from the impostor, and it does so in both directions. **Check `trusted`, not `valid`, whenever the signature is meant to prove *who* signed.**

!!! warning "The higher-level verifiers do not fail closed the same way"

    `verify_attestation()` and `verify_sd_jwt()` still fall back to the self-asserted key and report `trusted=False`, rather than refusing. That is deliberate. It keeps a genuinely offline inspection path working, which is the whole point of `did:key`, but it means the burden moves to you. A verification result you did not pass a key or resolver to is an integrity check, not an authentication.

### What this changes about "offline verification"

Earlier versions of this page said the recipient "needs nothing but the JWS string". That was true about *integrity* and misleading about everything else. The accurate statement:

- Verifying a signature **needs no network, no PKI, and no resolver**. That property is real and it is why `did:key` was chosen.
- Verifying an *issuer* needs a key you already trust, obtained out of band. There is no format that removes this requirement; formats that appear to remove it have moved it into a PKI you also have to trust.

A field tablet with no connectivity can still check that an envelope has not been altered. Deciding that the envelope came from the district health office is a key-distribution problem, and arche does not pretend to solve it.

---

## What is actually signed

Two different artefacts, for two different jobs.

| | `Attestation` (`arche.attest`) | `ArcheSignedDocument` (`arche.sign`) |
|---|---|---|
| Subject | One co-reference decision | One `Pipeline.Result` over a document |
| Carries | Decision, numeric evidence, gate, vetoes, jurisdiction, pins, content-addressed ids | Document hash, detections, policy outcomes, redacted text, statute version |
| Raw attribute values | **None**, unless explicitly opted in under SD-JWT | The redacted text only; the original document is never in it |
| Built by | `attest(decision, key)` | `SignWorkflow(...).sign(...)` |

An `Attestation` carries **no raw attribute values**. Only the decision, numeric evidence such as similarities and gate booleans, and content-addressed ids. That makes it shareable, with one condition attached, which the code enforces rather than documents.

### Keyless ids are not "PII-free"

`reference_id` and `decision_id` are hashes over the person's normalised attributes. A bare SHA-256 of an eleven-digit NIN can be brute-forced back to the NIN in seconds, so a keyless attestation is *pseudonymous personal data*, not anonymous data, and `attest` refuses to sign one by default.

Produce the decision with an `issuer_key` and the ids become HMAC pseudonyms: stable per issuer, so you can correlate the same person across your own documents, and unlinkable across issuers, so nobody else can correlate them with you.

### `reproducible` now means something

An attestation records whether the decision it carries can be replayed. Until recently that flag was computed as `mode == "jws"`. A fact about the *signing format* that said nothing about the decision. Every JWS attestation therefore claimed `reproducible: True`, including ones built from an LLM extraction whose own `extraction` pin recorded `reproducible: false` in the very same artifact.

It is now derived from the decision's pins. The engine's own path is deterministic. Canonical form, fixed-precision floats, sorted keys, so a decision is reproducible unless something that fed it declared otherwise. A hosted model's output is exactly that case: the representation and the decision maths replay, the extraction does not, and the attestation says so. Provider adapters do the same thing for the same reason; their `pin()` declares `reproducible: False` because a live API response cannot be replayed by a stranger.

```python
from arche.attest import attest, verify_attestation
from arche.canonical import Reference
from arche.resolve import pairwise
from arche.sign import generate_keypair

ISSUER_KEY = b"an issuer secret of at least 32b"
signing_key = generate_keypair()

a = Reference.from_record({"id": "A1", "full_name": "Ngozi Adeyemi",
                           "national_id": "12345678901"})
b = Reference.from_record({"id": "B7", "full_name": "N. Adeyemi",
                           "national_id": "12345678901"})

# 1. The engine extracted the records itself: every step replays.
engine = pairwise(a, b, issuer_key=ISSUER_KEY)

# 2. A hosted model proposed the records. The decision maths still replays;
#    the extraction does not, and its pin says so.
llm = pairwise(a, b, issuer_key=ISSUER_KEY, extra_pins={
    "extraction": {"model": "gpt-4o-mini", "prompt_sha256": "ab12…",
                   "reproducible": False},
})

for label, decision in (("engine extraction", engine), ("LLM extraction", llm)):
    signed = attest(decision, signing_key)
    print(f"{label:18} {decision.identity:12} "
          f"reproducible={signed.attestation.reproducible}")

signed = attest(engine, signing_key)
untrusted = verify_attestation(signed.compact)
trusted = verify_attestation(signed.compact, public_key=signing_key.public_key)
print()
print("no key :", untrusted.valid, untrusted.trusted, untrusted.key_source)
print("pinned :", trusted.valid, trusted.trusted, trusted.key_source)

# An unkeyed decision is refused: its ids would be brute-forceable.
try:
    attest(pairwise(a, b), signing_key)
except ValueError as exc:
    print()
    print(str(exc).split(".")[0] + ".")
```

```text
engine extraction  same_entity  reproducible=True
LLM extraction     same_entity  reproducible=False

no key : True False self-asserted
pinned : True True pinned

refusing to attest a keyless decision: its reference_id/decision_id are sha256 hashes of the person's attributes and can be brute-forced back to the source records, so the signed artifact would NOT be PII-free.
```

Crosswalk edges get the same treatment at list scale: every edge carries a `decision_id` hashed over its evidence and the run's pins, and `resolve.reconcile.sign_edges` signs exactly that claim.

---

## Selective disclosure, and the boundary it must not cross

`arche.credentials.sd_jwt` re-frames an attestation or an envelope as an IETF SD-JWT-VC. Each disclosable claim is a base64url-encoded `[salt, name, value]` tuple; the JWT payload carries a `_sd` array of SHA-256 digests; the disclosures ride after the JWT with `~` separators. The holder decides which to forward, and the verifier rejects any disclosure whose digest is not in `_sd`.

Three rules the code enforces rather than suggests:

1. **PII is never cleartext in a JWS.** `include_subject` with `mode="jws"` is a `ValueError`. Selective disclosure or nothing.
2. **An unbound PII-bearing credential is a bearer token**, so `include_subject` requires *either* a `holder_key`, which binds the credential via `cnf` and forces a KB-JWT at presentation, checked against a fresh `aud` and `nonce`. *or* an `expires_at` that time-boxes the damage. The key-bound path is the replay-proof one.
3. **`restricted` attributes are never disclosable.** This is where `protect` and `attest` meet, and the rule is two-sided: a field marked `restricted` in the declaration, or carrying a statute `drop` action, remains usable as *match evidence* and can never be disclosed. No flag overrides it. Evidence and disclosure are separate permissions, and the code treats them separately.

```python
from datetime import datetime, timedelta, timezone

from arche.attest import attest, present_attestation, verify_attestation
from arche.canonical import Reference
from arche.resolve import pairwise
from arche.sign import generate_keypair

ISSUER_KEY = b"an issuer secret of at least 32b"
issuer, holder = generate_keypair(), generate_keypair()

a = Reference.from_record({"id": "A1", "full_name": "Ngozi Adeyemi",
                           "national_id": "12345678901"})
b = Reference.from_record({"id": "B7", "full_name": "N. Adeyemi",
                           "national_id": "12345678901"})
decision = pairwise(a, b, issuer_key=ISSUER_KEY)

credential = attest(
    decision, issuer,
    mode="sd-jwt",
    include_subject=["full_name", "national_id"],
    holder_key=holder,                      # binds it; a KB-JWT is now required
    expires_at=datetime.now(timezone.utc) + timedelta(days=30),
)
print("disclosures issued:", len(credential.disclosures))

presentation = present_attestation(
    credential, disclose=["full_name"],
    holder_key=holder, aud="https://verifier.example", nonce="n-0f2c",
)
result = verify_attestation(
    presentation,
    public_key=issuer.public_key,
    require_key_binding=True,
    expected_aud="https://verifier.example",
    expected_nonce="n-0f2c",
)
print("valid:", result.valid, "| key_bound:", result.key_bound)
print("disclosed:", {k: v for k, v in result.claims.items()
                     if k in ("full_name", "national_id")})
print("decision  :", result.claims["decision"], "| reproducible:",
      result.claims["reproducible"])
```

```text
disclosures issued: 2
valid: True | key_bound: True
disclosed: {'full_name': 'Ngozi Adeyemi'}
decision  : same_entity | reproducible: False
```

Two claims were issued as disclosable; the holder forwarded one; the verifier saw one. And `reproducible` is `False` even though the underlying decision replays perfectly. An SD-JWT carries salted disclosure digests and is therefore never byte-stable. Both halves of the flag have to hold: the wire form must be reproducible *and* nothing that fed the decision may have declared otherwise.

---

## Where the guarantee stops

The most useful thing this page can do is mark the edge of what a signature buys.

**A signed envelope is tamper-evident. The audit log is not.** `arche.graph.audit` is a SQLite log that stores category labels, character spans and document hashes. Never PII values. Its schema has nullable `prev_hash` and `signature` columns so that hash-chaining lands as a migration-free change, and **nothing populates them today**. `export_signed()` proves a bundle was not altered *after signing*. It does not prove that no row was removed before. Treat the log as append-only by convention.

**Reproducible does not mean re-derivable by a third party.** A reproducible decision replays for someone holding the same records and the same issuer key. Keyed ids are the point. They stop a stranger brute-forcing the inputs, and the cost is that the stranger verifies the *signature* rather than recomputing the *decision*.

**A signature says nothing about whether the decision was right.** It says the decision was reached from this evidence under this representation. If the representation was wrong, the attestation faithfully records a wrong decision. That is the correct behaviour and it is worth being explicit about.

---

## The format choices, and why

Interesting once you have decided attestation is worth having; not the first question. Recorded here so nobody has to re-litigate them.

### Why JWS, not PAdES, not JSON-LD VC

| Format | Case for it | Why it was not picked |
|---|---|---|
| **PAdES** (signed PDF) | The standard for legal contracts | Signs the PDF, not the structured decision. arche's value is the evidence-and-outcome set, not the rendering. |
| **W3C VC 1.1 JSON-LD** | Wallet ecosystem familiarity | JSON-LD context resolution plus URDNA2015 canonicalisation adds a dereferencing step and a graph-normalisation step before you can verify anything. Both are places two deployments can silently diverge. |
| **JWS** ✓ | Interoperable, simple, what EUDI Wallet ARF and MOSIP e-signet use underneath | Selected. |

JWS over canonical JSON is the boring, interoperable default. Every language has a verifier. SD-JWT-VC and signed JWT are JWS underneath. Compact serialization only. The JSON serialization is not implemented.

PAdES and JSON-LD VC are not ruled out. If a deployment needs either, they belong behind opt-in extras rather than in the base wheel. Neither ships today.

### Why Ed25519

Small (32-byte keys, 64-byte signatures), fast on CPU, deterministic. No nonce-reuse footgun. EUDI Wallet, MOSIP e-signet and the DIF/W3C examples all default to EdDSA.

**It is the only algorithm implemented.** `alg` is `EdDSA` and nothing else. If a deployment forces alternatives, the two candidates are ECDSA P-256 (FIPS-only environments, at the cost of nonce management) and RSA-PSS (legacy PKI interop, since some e-government CAs still issue RSA certs). Both belong behind opt-in extras; neither exists.

### Why `did:key`

A `did:key:z6Mk…` identifier is self-describing: the base58btc-multibase-encoded suffix *contains* the public key. A verifier decodes it offline. No network call, no PKI, no infrastructure. It is the only DID method that works air-gapped, which matters more than ecosystem familiarity when verifiers are field tablets with intermittent connectivity.

The trade is precisely the one at the top of this page: self-describing means self-*asserted*. `did:key` gives you offline decoding, not offline authentication.

Scope, plainly: `did:key` is the only DID method arche implements. Keys load and export as PEM (`load_private_key_pem`, `export_public_pem`); there is no `did:web` resolution, no key-provider abstraction, and no HSM or PKCS#11 signing. Signing with a key you hold is the whole model.

### Why SD-JWT-VC for the wallet form

The EUDI Wallet architecture reference framework specifies SD-JWT-VC. IETF, selective disclosure, JWS-based, and SD-JWT-VC is structurally what the arche envelope already is: JWS over a JSON claim set, with disclosure logic on top. Picking it costs nothing and buys wallet interoperability.

### Post-quantum: designed, not shipped

NIST ratified ML-DSA (FIPS 204) in August 2024 and hybrid Ed25519 + ML-DSA is the obvious next step: the envelope grows a second signature and verifiers without ML-DSA support skip it gracefully. It is designed and not built. There is no `arche-core[pqc]` extra, and `liboqs-python` wheels are still not universal across the CPU and OS combinations arche has to run on. This section exists so nobody plans around a signature arche cannot produce.

---

## What this gives you, stated exactly

- **Tamper-evident artefacts.** A signed attestation binds the decision, its numeric evidence, and the pins. A signed envelope binds the document hash, the detections and the policy outcomes. The *log* is not tamper-evident.
- **Offline integrity checking.** No network, no PKI, no resolver.
- **Authenticated issuance, when you supply the key.** `trusted`, not `valid`.
- **PII-safe sharing by default**, enforced: keyless decisions are refused, JWS cleartext PII is refused, and `restricted` attributes are never disclosable.
- **An honest reproducibility flag**, derived from what actually fed the decision.
- **Holder-controlled disclosure** with replay defence, via key-bound SD-JWT-VC.
- **Sovereignty.** A library, not an issuer. No arche root key exists.

---

## What's next

- [Architecture](architecture.md). The layer this one sits on top of
- [Sign, share, extract](../tutorials/sign_share_extract.md). The envelope path end to end
- [Citizen DSAR](../tutorials/citizen_dsar.md). Attestation inside a statutory workflow
- [A place is not a point](../blog/a-place-is-not-a-point.md). Why the claim is scoped to a representation and a moment
