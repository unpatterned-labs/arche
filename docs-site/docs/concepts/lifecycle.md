# The identity lifecycle

*Verb by verb: what arche does today, what is gated, and what does not exist. The page to check before you build on any of it.*

---

Three pages on this site describe how work moves through arche, and they answer different questions. [How arche works](how-it-works.md) is the walkthrough. One record, all four verbs, for a reader meeting entity resolution for the first time. [Architecture](architecture.md) is the internal structure, layered by what each component is permitted to conclude. **This page is the inventory.** It exists to answer "can arche do X today", including the cases where the answer is no, and it is deliberately unflattering where the code deserves it.

The four verbs are **detect · resolve · protect · attest**. An earlier version of this page used Detect → Resolve → Verify → Govern with Link as a fifth, unshipped step. Two of those words were never the shipped vocabulary, and the ordering implied a pipeline that the code does not have. `resolve` and `protect` are independent surfaces, not consecutive stages, and most callers use one without the other.

| Question | Today's answer |
|---|---|
| Find government IDs, phones, names, addresses in African text? | Yes — 26 ID patterns across 15 countries, plus cross-cutting detectors |
| Attach the governing statute section to each finding? | Yes — six packs, every category cited |
| Decide whether two records are the same person? | Yes — `resolve.pairwise`, signable, with abstention |
| Link two lists of thousands of records? | Yes — `resolve.crosswalk`, for persons, places and artists |
| Decide whether two records are the same *place*? | List crosswalk only. `pairwise(entity="place")` raises |
| Refuse to send personal data to a third party? | Yes — `guard.EgressGuard`, fail-closed |
| Sign a decision so a stranger can check it offline? | Yes — Ed25519 / JWS / SD-JWT-VC |
| Prove the audit log has not had rows removed? | **No** — append-only by convention only |
| Connect a resolved reference to a national registry? | **No** — gated, no adapter of any kind |
| Serve any of this over MCP? | **No** — no MCP module exists in the wheel or the source tree |

---

## Detect: what arche can find in text

`Pipeline(jurisdiction=...)` runs a detector set chosen for that jurisdiction. Each detector proposes spans; none of them decides what happens next.

| Detector package | Finds | In the default set |
|---|---|---|
| `ng` / `ke` / `za` / `gh` | Per-country government IDs — NG (NIN, BVN, TIN, RC, voter PVC, driver's licence), KE (national ID, KRA PIN, NHIF), ZA (SA ID with full Luhn and DOB/gender/citizenship decode, tax reference, passport), GH (Ghana Card, SSNIT, TIN) | Yes, for that jurisdiction |
| `core` (`_africa`) | Eleven further African countries (RW, TZ, UG, ET, CI, SN, CM, EG, MA, AO, MZ) and phone numbers via `phonenumbers`, E.164 across 30+ networks. 26 ID patterns in total | Yes |
| `names` | African given names and surnames from an equivalence lexicon | Yes |
| `locations` | African city gazetteer — 102 cities under 236 lookup keys, aliases included | Yes |
| `addr` | Address spans for NG / ZA / KE / GH and the UK: components, landmark anchors, jurisdiction inference | Yes |
| `ip` | IPv4 and IPv6 via stdlib `ipaddress`, with private / loopback / multicast flagged and `v1.2.3.4` version strings suppressed | Yes |
| `digital_id` | W3C DIDs across nine methods, Bitcoin (P2PKH, P2SH, bech32), Ethereum with an EIP-55 checksum flag | Yes |
| `emails` | Email addresses (`PII-3-EMAIL`) | **No — opt-in** |
| `arche-core[detect]` | GLiNER2-PII for multilingual soft-PII. Never on the critical path | No — optional extra |

Every detection carries a `category` from the Pan-African PII Taxonomy, a `sensitivity_tier` of `high` / `moderate` / `low`, a `regulatory_citation` once a statute is applied, and a `confidence` that is deliberately not a uniform 1.0. A rule's base confidence encodes what the shape alone is worth (Ghana Card 0.95, KRA PIN 0.92, NIN 0.55, Kenyan national ID 0.40, because a bare seven-or-eight-digit number is weak evidence) and a passing structural validator raises it. `metadata["validator_status"]` records which check ran.

### Known gaps in detect

These are the ones that change what you can promise, so they are stated rather than left to be discovered.

**`Pipeline` does not detect email addresses by default.** `emails` is not in the default detector set, and the reason is compatibility. Adding it would change existing callers' detections, policy outcomes and redacted text. The detector itself works standalone, and you can opt in:

```python
from arche import Pipeline
from arche.detect.emails import detect_emails

p = Pipeline(jurisdiction="NG")
print("default detector packages:", p.describe()["detectors"])
t = "Zainab Bello, zainab.bello@example.com, NIN 12345678901."
print("pipeline default :", [(d.category, d.text) for d in p.process(t).detections])
print("standalone       :", [(d.category, d.text) for d in detect_emails(t)])
```

```text
default detector packages: ['ng', 'names', 'locations', 'ip', 'digital_id', 'addr', 'core']
pipeline default : [('PII-2-NIN', '12345678901'), ('PII-1-NAME', 'Zainab'), ('PII-1-NAME', 'zainab')]
standalone       : [('PII-3-EMAIL', 'zainab.bello@example.com')]
```

**`Pipeline(address_parsing=True)` does nothing.** The flag is a placeholder hook in `workflow/_primitive.py` that imports `arche.addr.parse_address` and discards it. Address spans reach the pipeline through the `addr` *detector package*, which is in the default set, so addresses are detected, but not because of that parameter. Passing it is harmless and misleading.

**Overlapping detections corrupt the redacted text.** `policy.apply_policy` splices replacements in reverse start order, which is correct for disjoint spans and wrong for nested ones. When one detection sits inside another. A name inside an email address, a name or a city inside an address span. The second splice uses offsets measured against the original text after the working text has already changed length. The output is malformed, and it can leave a fragment of the value that was meant to be removed:

```python
from arche import Pipeline

p = Pipeline(jurisdiction="NG")
for t in ["12 Adeola Odeku Street, Victoria Island, Lagos.",
          "Plot 5 Ibrahim Taiwo Road, behind the Total filling station, Kano."]:
    r = p.process(t)
    print("dets:", [(d.category, d.text, d.start, d.end) for d in r.detections])
    print("out :", repr(r.redacted_text))
```

```text
dets: [('PII-1-NAME', 'Adeola', 3, 9), ('PII-4-LOCATION', 'Lagos', 41, 46), ('PII-4-ADDRESS', '12 Adeola Odeku Street, Victoria Island, Lagos', 0, 46)]
out : '[ADDRESS], Lagos.'
dets: [('PII-1-NAME', 'Ibrahim', 7, 14), ('PII-4-LOCATION', 'Kano', 61, 65), ('PII-4-ADDRESS', 'Plot 5 Ibrahim Taiwo Road', 0, 25), ('PII-4-ADDRESS', 'behind the Total filling station, Kano', 27, 65)]
out : '[ADDRESS]o Road, [ADDRESS].'
```

`'[ADDRESS]o Road'` is the whole problem in one line. Until overlap resolution lands, treat `redacted_text` as unsafe for release on any input where address, location and name detections can overlap, and read `result.detections` and `result.policy_outcomes`, which are correct, rather than the rewritten string.

**Detection is a lexicon, and lexicons have holes.** `Fatima` is in the name lexicon and `Fatuma` is not; `Abdullahi` and `Abdulahi` both are. Nothing downstream can protect a span no detector proposed, so measure coverage on your own corpus before treating the redacted output as a compliance control.

---

## Resolve: deciding who is who

Two engines, deliberately not merged, because they answer different questions and combine evidence under different laws.

| | `resolve.pairwise` | `resolve.crosswalk` |
|---|---|---|
| Question | Are these two the same? | Link two lists at scale |
| Input | Two `canonical.Reference` objects | Two lists of records |
| Combination law | Fellegi–Sunter log-odds | Weighted arithmetic mean |
| Output | A signable `CoReferenceDecision` | Edges, each with evidence and a `decision_id` |
| Entities | Person only | `person`, `place`, `artist` |
| Signing | `attest(decision, key)` | `resolve.reconcile.sign_edges` |

The scores from the two engines are not comparable, and that is intentional rather than an oversight awaiting a refactor. Converging their gate policies would either weaken pairwise's guarantee that two identical *common* names must not clear, or change facility-crosswalk scores. A benchmarked change, not tidying.

### Abstention, and the three conditions

`pairwise` returns `same_entity`, `review`, or `different` on the `identity` axis, and a separate recommended `action`. `same_entity` requires **all three** of: the score at or above the jurisdiction's match threshold (0.85 by default); the distinctive-signal gate cleared by a shared exact identifier or a genuinely rare shared name token; and at least two fields that actually agreed. Two records sharing nothing but an exact national ID satisfy the first two and fail the third, landing in `review` at a score of 0.9999. The worked output is [on the walkthrough page](how-it-works.md#3-resolve). A conflicting identifier is decisive in the other direction and returns `different` regardless of how well the names match.

### The geographic veto

On the `place` pack, distance is a constraint rather than a weighted signal: `veto_km: 10.0`. Before v0.3.0a1 geography was scored at weight 1.0 against name and token-frequency's combined 4.0, it could be outvoted, and it was. Two Kano facilities sharing a common Hausa name merged 143 km apart with the geo comparator itself scoring 0.000. Three properties of the replacement are deliberate and visible in one run:

```python
from arche.resolve import crosswalk

A = [{"name": "Kauyen Adam Health Post", "lat": "12.0000", "lon": "8.5000"}]
B = [
    {"name": "Kauyen Adam Health Post", "lat": "12.0100", "lon": "8.5100"},  # 1.5 km
    {"name": "Kauyen Adam Health Post", "lat": "12.4000", "lon": "8.9000"},  # far
    {"name": "Kauyen Adam Health Post", "lat": "", "lon": ""},               # no coords
]

for e in crosswalk(A, B, entity="place")["matches"]:
    print(f"b_id={e['b_id']}  {e['decision']:8} score={round(e['score'], 3)}  {e['evidence']}")
```

```text
b_id=2  match    score=1.0  {'name': 1.0, 'name_tftoken': 1.0, 'name_type': 1.0}
b_id=0  match    score=0.919  {'name': 1.0, 'name_tftoken': 1.0, 'name_type': 1.0, 'geo': 0.595, 'distance_km': 1.56}
b_id=1  review   score=0.8  {'name': 1.0, 'name_tftoken': 1.0, 'name_type': 1.0, 'geo': 0.0, 'distance_km': 62.2, 'geo_conflict_km': 62.2}
```

The distant pair is demoted to `review` and carries `geo_conflict_km` as the reason; it is **never** demoted to `no_match`, because distance says a human must look, not that the answer is no. The coordless record is **never vetoed**. You cannot refute a claim on evidence you do not have, and note that it therefore scores *higher* than the pair 1.56 km apart, which is the honest consequence of not penalising missing data. The threshold was set by a sweep that moved LGA agreement from 78.4% to 88.1%; what that number can and cannot tell you is set out in full on [the place benchmark](place-benchmark.md), where it is called a consistency check rather than validation.

### Also in resolve

`resolve.resolve_entities` is the older clustering path over extracted entities: it attempts Splink via the `arche-core[resolve]` extra once there are ten or more entities, and falls back to fuzzy matching plus union-find with the name equivalence lexicon otherwise. `arche.link` is a function, not a module, and it resolves entity lists from several of *your* sources into one identity graph. Resolution across your own data, not linkage to somebody else's registry. `TokenFrequencyTable.default()` loads the population frequency table for persons, and `default(domain="artist")` a 500k-artist MusicBrainz sample.

### What resolve does not do

- **`pairwise(entity="place")` raises**. `NotImplementedError: pairwise entity='place' is not available yet; person only. Use crosswalk(...) for place lists.` The same holds for products: there is no product pack.
- **`orthography=` is not wired into `crosswalk`.** It is opt-in on `shared_name_distinctiveness` and `TokenFrequencyTable.weighted_token_sim`, and defaults to `None` on both. The place pack does not set it, so `crosswalk(..., entity="place")` does not use the Hausa pack, and the measured 13-pair gain on the Kano benchmark came from binding the comparator explicitly. Plumbing it through the comparator spec is outstanding.
- **A declared `id_family` does not mint an `entity_id`.** `Declaration.binding_fields()` exists, but `ids.identity_binding_key` is not declaration-aware and matches arche's own fixed identifier names.
- **No collective or graph-based resolution.** Clustering under transitive closure is the open remainder of the inference half and is gated post-beta, not implied by anything shipped.

---

## Protect: holding data under the law that applies

`arche.policy` routes each detection through the applicable statute and applies one of six closed actions. The set is closed on purpose; a seventh is a design decision, not a configuration change.

| Action | Behaviour |
|---|---|
| `mask` | Replace with a `[CATEGORY]` placeholder |
| `tokenize` | Replace with a deterministic, non-reversible token |
| `drop` | Remove the span entirely |
| `generalize` | Reduce specificity (DOB → year, address → city) |
| `audit` | Log the decision, leave the text untouched |
| `retain` | Allowlist; pass through unchanged |

Six statute packs ship as YAML at `arche/policy/statutes/`: `NDPA-2023` (Nigeria), `GDPR` (EU/EEA), `HIPAA-SAFE-HARBOR` (US health), `KENYA-DPA`, `POPIA` (South Africa) and `GHANA-DPA`. Every category in every pack carries a statute-section citation. Each pack declares a `review_status` separately from its `version`, because "we finished it" and "someone official checked it" are different claims. All six are `self-reviewed`, none claims regulator review, and the loader fails closed on a pack that claims it without naming a reviewer. Three packs still carry a stale `v0.1-scaffold` version label that understates their completeness; correcting them is outstanding in our roadmap.

One **overlay** ships alongside the packs: `EU-AI-ACT`, applied with `Pipeline(overlays=["EU-AI-ACT"])`. It is not a per-field statute. The AI Act governs the system, not the field, so it asserts at document level whether the run met a record-keeping (Art 12), transparency (Art 50) or data-minimisation (GDPR Art 5(1)(c) / Art 25) obligation and stamps the result into `Result.metadata`. Its own YAML states the boundary: evidence the operator presents, not a compliance certificate.

`guard.EgressGuard` wraps a statute-aware `Pipeline` so nothing crosses a boundary a policy did not permit. All four of its teeth default to deny: no statute means no permission; an undeclared cross-border transfer is refused with the statute cited; a provider outside the allow-list is refused; and any exception becomes a refusal rather than a fallthrough that emits the original text. The projection guarantee is that no raw *detected* value appears in any output field, which, as the detect section above makes clear, is not the same as no PII appearing. The worked example is [on the architecture page](architecture.md#5-the-egress-guard-fail-closed-four-teeth).

`arche.render` masks by default when a resolved record is displayed, and attributes marked `restricted` in a [declaration](../how-to/declare-your-schema.md) remain usable as match evidence and are never disclosable. `arche compare` on the CLI produces a masked-by-default HTML report.

### Known gaps in protect

- **`Pipeline.process` does not write to `graph.audit`.** It builds an audit view in memory and returns it on the `Result`. Persisting it is a wiring step you do, not a thing that happens.
- **The SQLite audit log is append-only by convention.** `prev_hash` and `signature` columns exist so hash-chaining can land without a migration, and nothing populates them. `export_signed()` proves a bundle was not altered after signing; it does not prove no row was removed before.
- **`protect.py` is not the `protect` verb.** It is a v0.1 Presidio wrapper reachable only through the deprecated lazy surface. The verb is implemented by `policy` + `guard` + `render`, and renaming the module is a breaking change waiting for v0.4.
- **The overlapping-span corruption** described under detect is a `protect` bug as much as a detect one. It is in `policy.apply_policy`.

---

## Attest: signing the decision

`arche.sign` produces Ed25519 / JWS envelopes over a `Pipeline.Result`; `arche.attest` produces an `Attestation` over one co-reference decision; `arche.credentials.sd_jwt` re-frames either as an IETF SD-JWT-VC with selective disclosure and optional holder key binding. Compact serialization only. `resolve.reconcile.sign_edges` does the same job for crosswalk edges at list scale.

Three properties are worth knowing before you write verification code, and all three are covered in depth on [the attest page](attest.md).

- **`valid` is not `trusted`.** `valid` says the signature matches the key that was resolved; only `trusted` says that key came from somewhere the caller controls. `sign.jws.verify()` now fails closed. `allow_did_key_from_kid` defaults to `False`, where it defaulted to `True` through v0.3.0a1. The higher-level `verify_attestation()` and `verify_sd_jwt()` deliberately still fall back to the self-asserted key and report `trusted=False` rather than refusing, which keeps offline inspection working and moves the burden to you.
- **`reproducible` is derived from the decision's pins**, not from the signing format. A decision built from a hosted model's extraction attests `reproducible: False`, and so does anything depending on a live provider response.
- **Keyless ids are not PII-free.** `reference_id` and `decision_id` are hashes over normalised attributes, and a bare SHA-256 of an eleven-digit NIN is brute-forceable, so `attest` refuses to sign a keyless decision by default. Supply an `issuer_key` and the ids become HMAC pseudonyms. Stable per issuer, unlinkable across issuers.

### What attest does not do

`did:key` is the only DID method implemented; there is no `did:web` resolution, no key-provider abstraction, and no HSM or PKCS#11 signing. EdDSA is the only algorithm. Post-quantum hybrid signing is designed and not built. There is no `arche-core[pqc]` extra. PAdES and JSON-LD VC were considered and rejected for the base wheel, with the reasoning recorded rather than left implicit.

---

## External evidence: the thing that looks like linking and is not

`arche.adapters` ships, and it is new enough to be easy to misread. An adapter asks a third party a question and brings back a witnessed observation. It never returns a merge decision: `ProviderEvidence.verdict` is one of `corroborates`, `contradicts`, `inconclusive`, and `match` and `different` are conspicuously absent from that list, because a geocoder is not entitled to an opinion about identity.

Two rules constrain adapters beyond that. Every adapter is an **egress destination**. Sending a citizen's address to a geocoder *is* a cross-border transfer, so adapters route through `EgressGuard` and the statute pack decides whether a reference may be sent at all. And a **provenance firewall** keeps provider responses out of the data packs, the frequency tables and the benchmark: every evidence object carries a licence class, and only `cc0`, `gers` and `user-owned` may be ingested. `odbl-attribution` is not on that list, so OpenStreetMap-derived evidence can inform a single decision and can never enter a pack. Because a live API response cannot be replayed by a stranger, adapter pins declare `reproducible: False` and the attestation says so.

One adapter is implemented, for Nominatim, and it is lazy-imported so nothing pulls `httpx` until you use it.

---

## What does not exist

Stated so adopters can hold us to scope.

**No registry or DPI linking.** Connecting a resolved reference to OpenCRVS, MOSIP, DHIS2, OpenG2P or FHIR has no implementation. There is no `arche.link` module and no registry adapter. This is a sequencing decision: an adapter that is not integration-tested against a running instance is scaffolding, and scaffolding in an identity library is worse than an honest gap. When it opens, its shape is already fixed by two rules enforced elsewhere. A verdict from an external registry is evidence and never a decision, and every adapter is an egress destination.

One distinction survives whatever ships: registry *linking* (this reference co-refers with that registry record) is not identity *proofing* (the presenting party **is** that record's subject). arche does the first. The second needs possession, biometrics, or consent, and is not a library's job.

**No MCP server.** There is no MCP module in the wheel or the source tree. Some docstrings mention an MCP surface as a design target; any description of arche MCP tools is describing something that does not exist yet.

**No risk, churn or fraud heuristics.** The early `arche.signal` layer was example-tier guessing and was removed. Its compliance half is the statute-grounded `policy_outcomes` on `Pipeline.Result`.

**No pluggable storage backend.** SQLite is the only one; `StorageBackend` is named in an RFC and does not exist as a protocol. If you need the rows elsewhere, `AuditLog.export()` gives you them.

---

## Why the order matters

Every verb downstream inherits the errors of the one above it, which is why detection has to be right before anything else is worth having. A signed envelope binding `[NIN]` to NDPA-2023 s.30 is only useful if the NIN was actually detected and the surrounding text was not mislabelled. An audit row saying "PII-2-BVN masked under s.30, tier=high" is only auditable if the detection was correct. A merge on a shared NIN is only correct if NIN detection did not mislabel a serial number.

The same logic runs one step further, and it is why registry linking is gated behind resolution rather than built alongside it: a link receipt that binds the wrong reference to a registry record is a signed mistake, and a signed mistake is harder to withdraw than an unsigned one.

---

## What's next

- [How arche works](how-it-works.md). The same four verbs as a single worked example
- [Architecture](architecture.md). The internal layering, and which components may conclude anything
- [Attest: the signature on the decision](attest.md). `valid` versus `trusted`, in full
- [The place benchmark](place-benchmark.md). What the veto threshold was tuned against, and the limits of that measurement
