# Security Policy

`arche-core` detects personal data, applies statutory policy to it, and signs
the resulting decisions. A defect in any of those three can expose someone's
identity data or make a false claim verifiable. We take reports seriously and
we would rather hear about a suspected problem than not.

## Supported versions

| Version | Supported |
|---|---|
| `0.4.0a*` | Yes — current alpha line |
| `0.3.0a1` | No — carries the `EgressGuard` defect below; upgrade |
| `0.2.0a*` | No — superseded, please upgrade |
| `0.1.*` | No |

`arche-core` is pre-beta. There is no long-term support branch yet, and
security fixes land on the current alpha line only.

## Reporting a vulnerability

**Do not open a public issue for a security problem.**

Report privately via GitHub's
[private vulnerability reporting](https://github.com/unpatterned-labs/arche/security/advisories/new),
or by email to **connect@unpatterned.org** with `SECURITY` in the subject.

Please include, as far as you have it:

- what you did, ideally as a runnable snippet
- what you expected and what happened instead
- the `arche-core` version (`python -c "import arche; print(arche.__version__)"`)
  and which optional extras are installed
- whether real personal data was involved — **do not send us real personal
  data.** Reproduce with synthetic values wherever you can. If a report only
  makes sense with real data, tell us that and we will arrange a safer channel
  rather than have it sit in an inbox.

We will acknowledge within **3 working days** and give you an assessment within
**10 working days**. If we accept the report we will agree a disclosure date
with you, credit you in the advisory and changelog unless you would rather we
did not, and tell you when the fix ships. If we decide something is not a
vulnerability we will explain why rather than close it silently.

## What we consider in scope

- Personal data escaping a path that is documented as protecting it — for
  example a detector missing a category the statute pack maps, redacted output
  retaining a raw value, or a masked projection revealing one.
- Anything that causes a signature or attestation to be trusted when it should
  not be, or that lets a decision be altered without invalidating its signature.
- Private key material being logged, persisted unexpectedly, or written with
  permissive file modes.
- Server-side request forgery or path traversal in the ingest and document
  layers, including redirect handling and access to link-local or cloud
  metadata addresses.
- Unsafe deserialization, or code execution from parsing a document, statute
  pack, or declaration file.
- Dependency vulnerabilities that are reachable from `arche-core`'s own code
  paths.

## Trust anchoring: `valid` is not `trusted`

This is the most important thing to understand about verification here, and it
was a real defect in `arche-core` up to and including v0.3.0a1.

`verify()` requires a key you already trust. Passing none returns
`valid=False` with an error naming your options:

```python
from arche.sign import generate_keypair, sign, verify

attacker = generate_keypair()
issuer = generate_keypair()
forged = sign({"decision": "match"}, attacker.private_key,
              kid=attacker.did_key, typ="arche+jws")

verify(forged).valid                             # False — no trusted key
verify(forged, public_key=issuer.public_key).valid  # False — correct rejection

lenient = verify(forged, allow_did_key_from_kid=True)
lenient.valid       # True   — the signature does match the key
lenient.trusted     # False  — but the signer chose that key
lenient.key_source  # "self-asserted"
```

`allow_did_key_from_kid=True` is a legitimate offline path: it proves an
envelope is internally consistent with no network call. It authenticates
nothing, because the signer picks `kid`. Results from that path always report
`trusted=False`.

**Check `trusted`, not `valid`, whenever a signature is meant to prove who
signed.** `valid` answers "does this signature match this key". Only `trusted`
answers "and did that key come from somewhere I control".

The same two fields appear on `VerifyExtractResult` (as `signature_trusted`),
`AttestationVerifyResult`, and `SDJWTVerifyResult`.

**Prior behaviour:** before this change `allow_did_key_from_kid` defaulted to
`True`, so the bare call returned `valid=True` for the forgery above, and the
result carried nothing to indicate that. If you have code written against the
old default, it was not verifying issuers, and it needs a key.

## Known issues, stated plainly

We would rather write these down than have you find them.

### Fixed in 0.4.0a1: `EgressGuard` leaked on overlapping detections

`EgressGuard` in **0.3.0a1** could emit a detected value in clear text when two
detections overlapped. Nested spans — an address containing a location, which
the Nigerian detector set produces on ordinary addresses — caused the container
to be skipped and its uncovered prefix to cross the boundary unreplaced. The
skipped category was also missing from `GuardedProjection.fields`, so the loss
was silent, and because `ADDRESS` generalises where `LOCATION` is retained, the
span that survived was the more sensitive one.

**Affected:** `0.3.0a1`, which is the **only version published to PyPI** and
therefore the only one anyone can be running. Any use of
`arche.guard.EgressGuard`.

**Fixed in:** `0.4.0a1`. Overlapping detections are grouped into disjoint
regions, replaced once, with the most restrictive action in the region winning.

**Correction (2026-08):** this advisory previously said "Fixed in `0.3.0a2`" and
told readers to upgrade. **`0.3.0a2` was never published.** It was versioned,
changelogged and merged, and then superseded before release — so for a period
this file instructed people to upgrade to something that did not exist. The fix
itself has been in `main` throughout; only the release it rides in has changed.
We are recording the mistake rather than quietly editing the version number,
because an advisory that has been wrong once should say so.

**Action:** upgrade to `0.4.0a1` when it publishes. If you have shipped
projections built with `0.3.0a1`, re-check them for unreplaced address
fragments regardless — the defect is in the projection, not only in the code
that produced it.

No CVE has been requested: this is pre-release software with no known
deployments. We are recording it here rather than folding it into a "bug fixes"
line because the guard is a security control and a silent failure in one is
worth naming.

### Alpha status

`arche-core` has not had an external security audit. The statute packs are
`self-reviewed` — our own reading of the cited sections — and none claims
regulator review. Do not use `arche-core` with real personal data until you
have completed your own legal, privacy, and security review.

## Out of scope

- Findings from automated scanners with no demonstrated impact on
  `arche-core`'s own code paths.
- Vulnerabilities in optional extras' upstream packages — report those to the
  upstream project; tell us too if `arche-core` makes them reachable.
- The absence of a feature that would improve security but was never claimed.
  Please still tell us; we will treat it as a feature request rather than an
  advisory.
- Anything requiring an attacker who already has code execution or filesystem
  access on the machine running `arche-core`.

## Cryptography

Signing is Ed25519 with `did:key` issuer identification. The JWS `alg` header
is pinned to `EdDSA` and `alg=none` is rejected. Payloads are canonicalized
before hashing so a decision id is reproducible across runs and platforms.

We do not roll our own primitives; the crypto comes from
[`cryptography`](https://cryptography.io/). If you find us doing otherwise,
that is itself worth reporting.
