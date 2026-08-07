# The identity lifecycle

arche-core organises identity work into five steps. Four of them ship;
one does not, and this page is explicit about which. Most users only
ever need `Pipeline` — see [How arche Works](how-it-works.md). The
lifecycle below is the mental model for building on the substrates
directly.

```
Detect → Resolve → Link → Verify → Govern
─────    ───────   ────   ──────    ──────
SHIPS    SHIPS     NO     SHIPS     SHIPS
```

**Link does not exist** in the sense that matters: there is no registry
or DPI adapter (OpenCRVS, MOSIP, DHIS2, OpenG2P, FHIR), no `arche.link`
module, and no signed link receipt. Connecting a resolved reference to
an *external system* is [gated roadmap work](roadmap.md#gated), blocked
on a real deployment to build against rather than on effort.

(There *is* a `link()` function — `from arche import link` — but it does
something different: it resolves entity lists from several of **your**
sources into one identity graph. That is resolution across your data,
not linkage to somebody else's registry.)

Everything else below describes code you can import today.

---

## What ships

### Detect

`arche.detect` + `arche.addr` find PII, identifiers, phones, addresses,
and IPs across African jurisdictions.

| Module | What it finds |
|---|---|
| `arche.detect.{ng,ke,za,gh}` | Per-country government IDs — 15 patterns: NG (NIN, BVN, TIN, RC, voter PVC, driver's licence), KE (National ID, KRA PIN, NHIF), ZA (SA ID, tax reference, passport), GH (Ghana Card, SSNIT, TIN). Check-digit / structural validators reject false positives. |
| `arche.detect._africa.ids` | 11 further African countries (RW, TZ, UG, ET, CI, SN, CM, EG, MA, AO, MZ) — 26 ID patterns in total across the continent. |
| `arche.detect._africa.phones` | libphonenumber-backed E.164 normalization across African networks. |
| `arche.addr` | Address parsing for NG / ZA / KE / GH and the UK: span detection, components, landmark anchors, jurisdiction inference, plus `extract_places` spatial roles and the `grade_places` referee. |
| `arche.detect.ip` | IPv4 + IPv6 via stdlib `ipaddress`. Private / loopback / multicast / reserved / link-local flagged in metadata. False-positive suppression for "v1.2.3.4" version strings. |
| `arche.detect.digital_id` | W3C DIDs (nine known methods: `key`, `web`, `ion`, `jwk`, `pkh`, `sov`, `indy`, `ethr`, `polygon`). Bitcoin (P2PKH, P2SH, bech32). Ethereum, with an EIP-55 checksum flag in metadata. |
| `arche-core[detect]` *(opt-in)* | GLiNER2-PII for multilingual soft-PII (names, orgs, locations). Never on the critical path. |

Every detection carries:
- **`category`** - Pan-African PII Taxonomy label
- **`sensitivity_tier`** - `high` / `moderate` / `low` (NIST 800-122 framework)
- **`regulatory_citation`** - the statute section the jurisdiction cites, once a statute is applied
- **`confidence`** - per-pattern, and it is *not* a uniform 1.0. A rule's base confidence encodes how much the pattern alone is worth (Ghana Card 0.95, KRA PIN 0.92, NIN 0.55, Kenya National ID 0.40 — a bare 7-or-8-digit number is weak evidence), and a passing structural validator raises it. `metadata["validator_status"]` says which check ran.

### Resolve

`arche.resolve` decides whether two references point at the same
real-world entity, and hands back the evidence.

- **`resolve.pairwise(a, b)`** — Fellegi–Sunter log-odds with an exact-id
  gate and id-conflict veto, returning a signable `CoReferenceDecision`
  with per-field evidence and a reproducible `decision_id`.
- **`resolve.crosswalk(list_a, list_b, entity=...)`** — link two lists at
  scale under union blocking, with `person` / `place` / `artist` entity
  packs. Every edge carries its evidence, a `decision_id`, and can be
  JWS-signed with `sign_edges`.
- **`resolve.resolve_entities`** — the older clustering path over
  extracted entities. It attempts Splink (via the `arche-core[resolve]`
  extra: Splink + DuckDB, Fellegi–Sunter with EM parameter estimation)
  once there are ≥10 entities, and falls back to fuzzy matching plus
  union-find with the 114-group name equivalence lexicon when Splink is
  not installed.

There is no `SplinkResolver` class and no pluggable storage backend. The
math, worked by hand against the shipped defaults, is in [From place to
entity](from-place-to-entity.md); the reasoning behind the packs is [the
representation engine](representation-engine.md). See also [the entity
resolution tutorial](../tutorials/entity_resolution.md).

### Verify

`arche.sign` + `arche.credentials.sd_jwt` produce offline-verifiable
signed envelopes.

- Ed25519 + did:key + JWS (compact serialization, RFC 7515). EdDSA is
  the only algorithm implemented.
- The `did:key` is embedded in the JWS `kid` header - recipients verify
  cryptographically without any PKI, resolver, or network call
- SD-JWT-VC re-framing, the format the EUDI Wallet ARF specifies
- Post-quantum (hybrid Ed25519 + ML-DSA) signing is designed but **not
  shipped**; there is no `arche-core[pqc]` extra. → [Verifiability](verifiability.md)

### Govern

`arche.policy` + `arche.graph.audit` apply statute-aware action and
record the decision.

- **Six statute packs**: NDPA-2023 (NG), POPIA (ZA), KENYA-DPA, GHANA-DPA,
  GDPR, HIPAA Safe Harbor. Every category in every pack carries a cited
  section, and every pack declares a `review_status`; all six are
  `self-reviewed` and none claims regulator review. Three still carry a
  stale `v0.1-scaffold` version label — see [Architecture](architecture.md#substrate-2-policy).
- **Six closed actions**: mask, tokenize, drop, generalize, audit, retain.
- **Append-only audit log**: SQLite-backed, PII values never stored
  (only category labels, character spans, document hashes). Append-only
  by convention; the `prev_hash` chaining that would make it
  tamper-evident is not populated yet.
- **Signed export**: `audit.export_signed(key=...)` produces a JWS-signed
  bundle a regulator can verify offline.

---

## What does not ship

### Link

Connecting a resolved reference to an external system — OpenCRVS, MOSIP,
DHIS2, OpenG2P, FHIR — has **no implementation in arche-core**. There is
no `arche.link` module and no adapter of any kind.

This is a sequencing decision, not an oversight. An adapter that is not
integration-tested against a running instance is scaffolding, and
scaffolding in an identity library is worse than an honest gap. When it
opens, the shape is fixed in advance by two rules already enforced
elsewhere: a verdict from an external registry is **evidence, never a
decision**, and every adapter is an **egress destination** subject to the
same boundary as any other. → [the gate on this work](roadmap.md#gated)

One distinction that survives whatever ships: registry *linking* (this
reference co-refers with that registry record) is not identity
*proofing* (the presenting party **is** that record's subject). arche
does the first. The second needs possession, biometrics, or consent, and
is not a library's job.

---

## How it composes

`arche.workflow.Pipeline` is the framework primitive. One call runs
detection → enrichment (tier + citation) → policy → audit:

```python
from arche import Pipeline

pipeline = Pipeline(jurisdiction="NG")
result = pipeline.process(text)

result.detections        # list[Detection] - each w/ tier + citation
result.policy_outcomes   # list[PolicyOutcome] - action applied + statute
result.redacted_text     # str - text after policy actions
result.audit_log         # list[dict] - PII-free audit rows
```

Higher-level reference workflows compose on top:

- `arche.sign.SignWorkflow` - runs Pipeline, signs the redacted output
- `arche.sign.VerifyExtractWorkflow` - verifies + extracts on the receive side
- `arche.workflow.DSARWorkflow` - citizen-side Data Subject Access
  Request letter generator (NDPA s.34, POPIA s.23, Kenya DPA s.26,
  Ghana DPA s.35)

---

## Why the order matters

Every step downstream inherits the errors of the step above it, which is
why detection has to be right before anything else is worth having.

- A signed envelope binding `[NIN]` to NDPA-2023 s.30 is only useful if
  the NIN was actually detected, and the surrounding text wasn't
  mislabelled.
- An audit row saying "PII-2-BVN detected, masked under NDPA s.30,
  tier=high" is only auditable if the detection was correct.
- A resolution that links two records on a shared NIN is only correct if
  NIN detection didn't mislabel a serial number.

The same logic runs one step further, and it is why [Link](#link) is
gated behind resolution rather than built alongside it: a link receipt
that binds the wrong reference to a registry record is a signed mistake,
and a signed mistake is harder to withdraw than an unsigned one.

For where each step is going, see [the roadmap](roadmap.md); for why
resolution rather than detection now leads, see [the representation
engine](representation-engine.md).
