# Roadmap

The single source of truth for what arche ships today, what gates the beta release, what is in flight, and what is deliberately gated. Updated every release.

**Status vocabulary**, used consistently below: **Shipped** (in the wheel, tested, documented) · **In flight** (active work with a named deliverable) · **Gated** (designed, sequenced behind a prerequisite we name) · **Not committed** (visible on the horizon; no promise).

!!! warning "Status: v0.3.0a1 — first alpha of the beta line"
    Not beta itself. APIs may change between alpha releases; not for production use against real personal data yet. Of the four named beta criteria below, one is met, one is partially met, two are open. Bug reports, issues, and contributions are very welcome.

---

## Today — v0.3.0a1

`pip install arche-core` · 1,456 tests in `packages/arche-core/tests` · ~1.3 MB base wheel, CPU-only, no mandatory ML dependencies · Python 3.11–3.13.

### Resolve — the lead capability

- **`resolve.pairwise(a, b)`** — "are these two the same?" Fellegi–Sunter log-odds with an exact-id gate and id-conflict veto, returning a signable `CoReferenceDecision` with per-field evidence and a reproducible `decision_id`.
- **`resolve.crosswalk(list_a, list_b)`** — link two lists at scale. **Union blocking** (H3 spatial ∪ rare-token ∪ shared-id) keeps true pairs whose coordinates disagree by kilometres or are missing entirely; per-run `blocking.recall` when you supply labelled truth. Every edge carries evidence, a `decision_id` hashed over that evidence plus provenance pins, and can be **JWS-signed** with `sign_edges`.
- **Entity packs as config, not forks** — `person`, `place`, `artist`. A new entity type is [a data pack, not new code](https://github.com/unpatterned-labs/arche/tree/main/datasets).
- **The distinctive-signal gate** — supporting signals (geo, containment, address) amplify but never manufacture a merge; `review` is a first-class outcome, not a failure.
- Measured: **40% → 0%** false-match rate on arche's African-name evaluation set (not yet published as a runnable benchmark — see *In flight*); [zero false merges at 0.877 auto-match recall](../tutorials/person_resolution_at_scale.md) on the synthetic Febrl 4 record-linkage set.

### Declare — your schema, not ours

One YAML declares *your* fields and annotates each with arche's roles (`identifies` / `describes` / `ignore`, comparator kind, `restricted`, statute class). From it arche generates comparators, masking, LLM tool definitions, validation, and a content-hash **pin** that enters every `decision_id`. No schema registry, ever. → [Declare your schema](../how-to/declare-your-schema.md)

### The LLM lane — models propose, the engine executes

- **`extract_declared`** — declaration-driven extraction through any model (`complete_fn` callable or `LLMConfig`: OpenAI / Anthropic / Ollama / litellm). Hallucinated fields become violations, never values.
- **`extract_places_llm`** — cue-verified spatial role proposals: a committed role survives only if its cue is locatable in the source, adjacent to the span, and pack-consistent; otherwise it downgrades to `unknown`.
- **`grade_pairs` / `grade_extractions`** — the deterministic engine as oracle, with `review` counted as abstention rather than error.
- Honest pins throughout: `model`, `prompt_sha256`, declaration pin, `reproducible: false`.

### Places, addresses, and spatial roles

- Address parsing for NG / ZA / KE / GH and the UK, with **landmark anchors** ("behind the Total filling station, Madina Junction") as first-class matching components and a multilingual relation vocabulary.
- **`extract_places`** — spatial role labeling (origin / destination / location / via / unknown) with the linguistic cue as evidence and structural abstention on conflict, negation, or absent cues.
- **The referee ships in the wheel**: a 54-sentence labelled gold set (`load_gold`) plus `grade_places`, a refusal-aware scorer that prices `over_guess` and `missed_by_abstention` separately from F1 — so anyone can grade *their* extractor, including an LLM. → [extract places with roles](../how-to/extract-places-with-roles.md)

### Detect + govern — the African-context layer

- Per-country ID detectors: Nigeria (NIN, BVN, TIN, RC, voter PVC, driver's licence), Kenya (National ID, KRA PIN, NHIF), South Africa (SA ID with Luhn + DOB/gender/citizenship decode, tax reference, passport), Ghana (Ghana Card, SSNIT, TIN), plus 11 further African patterns. libphonenumber-backed normalization across 30+ networks.
- **114-group name equivalence lexicon** (450 forms, 20+ ethnic and linguistic traditions) and population-scale frequency tables.
- **Six statute packs** — NDPA-2023, POPIA, Kenya DPA, Ghana DPA, GDPR, HIPAA Safe Harbor — each carrying a complete category mapping with a cited section on every category, and each declaring `review_status` (`self-reviewed` or `regulator-reviewed`; the loader refuses the latter without a named reviewer). All six are `self-reviewed`; none claims regulator review. Six closed actions, sensitivity tiers, a citation on every detection. *Label debt, stated: NDPA-2023, GDPR and HIPAA carry `version: v1.0` while POPIA, Kenya DPA and Ghana DPA still carry `version: v0.1-scaffold` even though their mappings are complete — the relabelling the v0.3.0a1 notes describe has not landed in the shipped packs yet.*
- `Pipeline(jurisdiction=...)` composes detect → policy → audit; SQLite append-only audit log that never stores PII values.
- **Pan-African PII Taxonomy v0.1** — 54 categories, CC-BY-4.0, published as a standalone dataset.

### Attest, and the command line

- `arche.sign` (Ed25519 + JWS + did:key), `arche.attest`, `arche.credentials.sd_jwt` (SD-JWT-VC with key binding), `arche.workflow.dsar`.
- **`arche compare`** and **`arche schema`** — link two files into a masked, shareable HTML report plus a `decisions.json` sidecar; validate a declaration or generate LLM tool-definitions from it. Both in one command.
- The MCP server is **not** in this list. It is built but unpublished — see *In flight*.

---

## Beta — v0.3.0 (the named criteria)

We mark arche **beta** when these are true. Status is tracked here every release, and revisions are made in the open rather than by quietly re-checking a box.

| # | Criterion | Status |
|---|---|---|
| 1 | Every shipped statute pack carries a complete category mapping with cited sections and a declared `review_status` | ✅ **Met** — all six packs map every category they cover to a closed action with a cited section, and all six declare `review_status: self-reviewed`; none claims regulator review |
| 2 | The **Africa Address Benchmark v0.1** is published with ground-truth parses for real African address strings and cross-tool baselines (libpostal, Google Geocoding) | ⬜ Open |
| 3 | The v0.1 backward-compat surface is removed | ⚠️ **Partially met** — the callable-module shim `arche.resolve(text)` is gone in v0.3.0a1; the remaining PEP 562 lazy v0.1 names are now formally deprecated with removal targeted for **v0.4** |
| 4 | At least one **production deployment** running cleanly for ≥90 days, documented as an open case study | ⬜ Open |

**Criterion 1 was revised in v0.3.0a1.** It previously read "POPIA, Kenya DPA and Ghana DPA reach v1.0 after structured DPA consultation." Two things forced the change: the product now ships six statute packs rather than four, and our own labels were incoherent (GDPR and HIPAA shipped as `v1.0` with no external review while three complete African packs sat at `v0.1-scaffold`). Completeness and review are now separate, declared axes: `version` is a claim about our work, `review_status` a claim about the world. Regulator review is tracked **per pack** and pursued continuously; it no longer gates a release, and we never imply it has happened when it hasn't. The `version` relabelling that follows from the split is not finished in the shipped packs — see the note under *Detect + govern* above.

**Criterion 3 is honestly partial.** Deleting the whole lazy v0.1 surface in the same release as the shim removal would break alpha users twice in one step. The callable shims are gone; the remaining legacy names live through the 0.3 line as a deprecated surface and are removed in v0.4.

---

## In flight

Active work with named deliverables. Two tracks run in parallel — the measured evidence, and the compliance substrate.

**Track 1 — evidence anyone can re-run**

- **African Name Benchmark** — the flagship: labelled slices, published baselines including embedding and LLM comparators, so the 40% → 0% claim is reproducible by strangers. Scope is frozen before building.
- **OpenSanctions pairs baseline** — the external comparison run that calibrates our numbers against a public set, including how named production matchers score on the same pairs. Until it exists we make no comparative claim about other tools' behaviour.
- **Facility crosswalk benchmark** — the Nigeria registry reconciliation as a measured artifact, not a demo.
- **Spatial role labeling — the gold set** — grow it from a 54-sentence probe to 300+ dual-annotated items across five register slices with reported agreement and published baselines. This is load-bearing: without it, the spatial-role claim is marketing.

**Track 2 — the compliance substrate**

- **EgressGuard completion** — the boundary that decides what may leave, with region/provider pinning.
- **Hash-chained audit + Merkle checkpoints** — `prev_hash` is stubbed today; replay and bitemporal query follow.
- **`arche-mcp`, the MCP server** — built and guarded by design (offsets and evidence, never raw PII; no reveal option on any agent path; fails closed without a statute), but **not yet published**: it is not in the `arche-core` wheel and `uvx arche-mcp` does not resolve. Publishing it, then closing the production gaps — auth/delegation first, then tool-call attestation and audit events — is this track's next deliverable. Until it is on PyPI, treat it as in flight, not shipped.
- **EU AI Act overlay** — gated on a deployment that actually needs it. *No EU AI Act statute pack ships today*; Annex III obligations were deferred to December 2027 by the June 2026 Digital Omnibus, and we will not imply otherwise.

**Place lane remainder** — calibrating the `type` comparator on labelled pairs (it ships at weight 0, visible in evidence, deliberately unscored until then); mid-hierarchy containment hygiene; comparator-firing documentation.

---

## Gated

Designed, sequenced, and honestly blocked on a named prerequisite.

| Work | Gate |
|---|---|
| **Transitive clustering** (union-find over pairwise edges, persistent cluster ids) | After the benchmark — blind clustering is where chained false merges hide, so arche's version stays gated: drop non-distinctive edges before components form, flag bridge records to review |
| **Entity relationship analysis** — households, networks, bridges | After clustering. Relationships connect *entities*; before clustering we hold only *references*, so ERA would put one person in the network three times. Then: `relationships:` in the declaration → analysis primitives (consume-don't-build) → **governed relationships** (edges are personal data: statute classes, masking, signable relationship claims) |
| **Contextual spatial roles** (`context=` for anaphora and deixis) | The conversational gold slice lands first — eval ahead of feature |
| **Privacy-preserving record linkage** | Real demand from a linkage unit. Then: consume `clkhash` behind an extra as a comparator *variant*, never a new declaration kind. The cheap seam — the declaration pin as the pre-encoding contract between parties — is the part worth building now |
| **Warehouse / dbt integration** | A team running dbt who wants the entity map and will tell us what shape it needs |
| **Registry adapters** (OpenCRVS, MOSIP, Companies House) | A real deployment to build against, not scaffolding. Verdicts from adapters are evidence, never decisions; every adapter is an egress destination |
| **A fine-tuned small model** for extraction/roles | The gold sets first, then verifier-gated distillation, then it ships only if it beats the deterministic floor *without* raising over-guess |
| **OpenMRS integration** — patient record linkage across facility EMRs | A deployment with real duplicate burden. The facility crosswalk is the half we have already proven; the patient half is the same engine with a person pack and a much higher cost of a wrong merge. Gated on a partner who will adjudicate the review queue, because a duplicate-patient decision nobody signs off is a decision nobody can defend |
| **Product resolution** — the same engine, non-person entities | Deliberately sequenced after places, because products are where the representation thesis gets its cleanest test: a product has identifiers (ISBN, GTIN, batch), names that vary by market and language, and no privacy surface at all, so the engine can be measured without a statute in the way |

### Where product resolution starts

Two beachheads, chosen because each has a public identifier to anchor on and a real reconciliation problem behind it.

**Books first.** ISBN is a clean, checksummed, globally-issued identifier with an open catalogue behind it, and `compare_isbns` already ships. Editions, translations, reissues and imprints give exactly the same shape as the facility problem: the same work under many names, many identifiers, and a genuine question about when two records are one thing. It is the cheapest honest test of whether the engine generalises past people and places.

**Then food traceability and audit.** A batch moving from farm to processor to distributor to retailer is described differently at every hop, and the reconciliation has to survive that. This is where the parts arche already has stop being separate features: resolution links the hops, the attestation makes each link independently checkable, and the review queue is where a human decides whether two consignments are the same consignment. An audit trail whose links cannot be verified is a spreadsheet with better branding.

Both are gated the same way as everything else here: a partner with the problem and data to run it against, not a demo.

---

## Not committed

Visible on the horizon; named so adopters can push, not promised. Jurisdiction depth beyond Africa (Brazil LGPD, India DPDP, Indonesia PDP, Mexico, Philippines — each roughly one statute pack plus one detector pack); sector packs over the African base (health, agriculture, energy, manufacturing); hypervector/HDC matching (research only until it beats the shipped matcher on a published slice); multimodal spatial grounding.

---

## Direction changes worth stating

A roadmap that never records its own reversals is a wish list. Three, with reasons:

- **The lead moved from "African PII detection" to "know the real-world entity, prove the decision."** Detection is a layer, not the product; resolution plus attestation is. African calibration remains the wedge and the credential — the hardest identity data in the world — rather than the scope. → [the thesis](representation-engine.md)
- **An MCP server is now on the roadmap at all**, reversing an early non-commitment ("agent integration is downstream of framework adoption"). Agents turned out to be an *install surface*, not a later channel. The server is built; publishing it is in flight, and the reversal is recorded here whether or not it lands on schedule.
- **Resolution left the "power-user" shelf.** `resolve`, `sign`, and `attest` were once documented as extras behind the detection pitch. They are the pitch.

**Standing non-commitments** (unchanged): no fine-tuned PII model in the base wheel — detectors stay rule-based and check-digit-validated, with neural NER as an opt-in extra; no production DPI adapters as scaffolding; no arXiv paper as a deliverable — engineering ships as documented work and benchmarks; no claim of regulator endorsement, ever, without a named reviewer and a date.

---

## Where to weigh in

- **GitHub issues** are the canonical place to push on scope, prioritisation, or the beta criteria. Issues tagged `roadmap` get triaged first.
- **The data packs are the contribution surface** — a name equivalence, a Pidgin or Yoruba role cue, a labelled sentence from your region, a statute correction. Each is a YAML edit, not a code change. → [the data packs](https://github.com/unpatterned-labs/arche/tree/main/datasets)
- **The pilot**: if you run identity data in a Nigerian or Kenyan fintech, a South African health-tech, or a Ghanaian public-data team and want to be the documented ≥90-day deployment (criterion 4), open a `pilot` issue.

We work in public, and we would rather be held to a concrete criterion than praised for a vague one.

---

*Updated every release. Last updated for arche-core v0.3.0a1 (2026-08). This page is the public contract; where it disagrees with anything else, this page is what we can be held to.*
