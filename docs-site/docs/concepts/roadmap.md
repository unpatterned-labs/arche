# Roadmap

The single source of truth for what arche ships today, what gates the beta release, what is in flight, and what is deliberately gated. Updated every release.

**Status vocabulary**, used consistently below: **Shipped** (in the wheel, tested, documented) · **In flight** (active work with a named deliverable) · **Gated** (designed, sequenced behind a prerequisite we name) · **Not committed** (visible on the horizon; no promise).

!!! warning "Status: v0.3.0a1 — first alpha of the beta line"
    Not beta itself. APIs may change between alpha releases; not for production use against real personal data yet. Of the four named beta criteria below, one is met, one is partially met, two are open. Bug reports, issues, and contributions are very welcome.

---

## Today: v0.3.0a1

`pip install arche-core` · 1,561 tests in `packages/arche-core/tests` · ~2.5 MB base wheel, CPU-only, no mandatory ML dependencies · Python 3.11–3.13.

### Resolve: the lead capability

- **`resolve.pairwise(a, b)`** — "are these two the same?" Fellegi–Sunter log-odds with an exact-id gate and id-conflict veto, returning a signable `CoReferenceDecision` with per-field evidence and a reproducible `decision_id`.
- **`resolve.crosswalk(list_a, list_b)`** — link two lists at scale. **Union blocking** (H3 spatial ∪ rare-token ∪ shared-id) keeps true pairs whose coordinates disagree by kilometres or are missing entirely; per-run `blocking.recall` when you supply labelled truth. Every edge carries evidence, a `decision_id` hashed over that evidence plus provenance pins, and can be **JWS-signed** with `sign_edges`.
- **Entity packs as config, not forks** — `person`, `place`, `artist`. A new entity type is [a data pack, not new code](https://github.com/unpatterned-labs/arche/tree/main/datasets).
- **The distinctive-signal gate** — supporting signals (geo, containment, address) amplify but never manufacture a merge; `review` is a first-class outcome, not a failure.
- Measured: **40% → 0%** false-match rate on arche's African-name evaluation set (not yet published as a runnable benchmark — see *In flight*); [zero false merges at 0.877 auto-match recall](../tutorials/person_resolution_at_scale.md) on the synthetic Febrl 4 record-linkage set.

### Declare: your schema, not ours

One YAML declares *your* fields and annotates each with arche's roles (`identifies` / `describes` / `ignore`, comparator kind, `restricted`, statute class). From it arche generates comparators, masking, LLM tool definitions, validation, and a content-hash **pin** that enters every `decision_id`. No schema registry, ever. → [Declare your schema](../how-to/declare-your-schema.md)

### The LLM lane: models propose, the engine executes

- **`extract_declared`** — declaration-driven extraction through any model (`complete_fn` callable or `LLMConfig`: OpenAI / Anthropic / Ollama / litellm). Hallucinated fields become violations, never values.
- **`extract_places_llm`** — cue-verified spatial role proposals: a committed role survives only if its cue is locatable in the source, adjacent to the span, and pack-consistent; otherwise it downgrades to `unknown`.
- **`grade_pairs` / `grade_extractions`** — the deterministic engine as oracle, with `review` counted as abstention rather than error.
- Honest pins throughout: `model`, `prompt_sha256`, declaration pin, `reproducible: false`.

### Places, addresses, and spatial roles

- Address parsing for NG / ZA / KE / GH and the UK, with **landmark anchors** ("behind the Total filling station, Madina Junction") as first-class matching components and a multilingual relation vocabulary.
- **`extract_places`** — spatial role labeling (origin / destination / location / via / unknown) with the linguistic cue as evidence and structural abstention on conflict, negation, or absent cues.
- **The referee ships in the wheel**: a 54-sentence labelled gold set (`load_gold`) plus `grade_places`, a refusal-aware scorer that prices `over_guess` and `missed_by_abstention` separately from F1 — so anyone can grade *their* extractor, including an LLM. → [extract places with roles](../how-to/extract-places-with-roles.md)

### Detect + govern: the African-context layer

- Per-country ID detectors: Nigeria (NIN, BVN, TIN, RC, voter PVC, driver's licence), Kenya (National ID, KRA PIN, NHIF), South Africa (SA ID with Luhn + DOB/gender/citizenship decode, tax reference, passport), Ghana (Ghana Card, SSNIT, TIN), plus 11 further African patterns. libphonenumber-backed normalization across 30+ networks.
- **114-group name equivalence lexicon** (450 forms, 20+ ethnic and linguistic traditions) and population-scale frequency tables.
- **Six statute packs** — NDPA-2023, POPIA, Kenya DPA, Ghana DPA, GDPR, HIPAA Safe Harbor — each carrying a complete category mapping with a cited section on every category, and each declaring `review_status` (`self-reviewed` or `regulator-reviewed`; the loader refuses the latter without a named reviewer). All six are `self-reviewed`; none claims regulator review. Six closed actions, sensitivity tiers, a citation on every detection. *Label debt, stated: NDPA-2023, GDPR and HIPAA carry `version: v1.0` while POPIA, Kenya DPA and Ghana DPA still carry `version: v0.1-scaffold` even though their mappings are complete — the relabelling the v0.3.0a1 notes describe has not landed in the shipped packs yet.*
- `Pipeline(jurisdiction=...)` composes detect → policy → audit; SQLite append-only audit log that never stores PII values.
- **Pan-African PII Taxonomy v0.1** — 54 categories, CC-BY-4.0, published as a standalone dataset.

### Attest, and the command line

- `arche.sign` (Ed25519 + JWS + did:key), `arche.attest`, `arche.credentials.sd_jwt` (SD-JWT-VC with key binding), `arche.workflow.dsar`.
- **`arche compare`** and **`arche schema`** — link two files into a masked, shareable HTML report plus a `decisions.json` sidecar; validate a declaration or generate LLM tool-definitions from it. Both in one command.
- The MCP server is **not** in this list, and it is **not built**. See *In flight* for the correction.

---

## Beta: v0.3.0 (the named criteria)

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
- **`arche-mcp`, the MCP server** — **not built.** Earlier versions of this page said it was "built but unpublished" and described its security behaviour in detail: that it exposed offsets and evidence rather than raw PII, that no agent path offered a reveal option, and that it failed closed without a statute. **None of that code exists.** There is no MCP module in this repository and none in the wheel; `uvx arche-mcp` does not resolve because there is nothing to resolve. The claim was wrong, it asserted security properties of software that was never written, and it is corrected here rather than quietly deleted. Design work is real and the four verbs map cleanly onto tools; building it is a post-v0.3.0a2 milestone, and nothing about its behaviour should be relied on until it is on PyPI with tests.
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

**Books first — with the coverage problem stated up front.** ISBN is a clean, checksummed, globally-issued identifier with an open catalogue behind it, and `compare_isbns` already ships. Editions, translations, reissues and imprints give exactly the same shape as the facility problem: the same work under many names, many identifiers, and a genuine question about when two records are one thing.

What the first probe found, though, is that the binding constraint is not matching. Taking one real book with a known author, title and publisher, Open Library returns **zero** results for the author and zero for the exact title. The record is not there to be matched. This is the ordinary case for small-press, regional and self-published output, and it is the case that matters most to the people arche is built for — the same long-tail absence that makes African identity data hard, showing up in a bibliographic registry.

That reframes the work rather than cancelling it. A resolver's honest verdict when a catalogue has no candidate is *not found*, and saying so is a feature: the failure mode worth preventing is a confident merge onto the nearest plausible listing. So the deliverable is a **coverage report before an accuracy report** — what fraction of a given catchment the registry actually holds — because a matcher measured only on records that exist will overstate itself on every corpus with a long tail.

**Then food traceability and audit.** A batch moving from farm to processor to distributor to retailer is described differently at every hop, and the reconciliation has to survive that. This is where the parts arche already has stop being separate features: resolution links the hops, the attestation makes each link independently checkable, and the review queue is where a human decides whether two consignments are the same consignment. An audit trail whose links cannot be verified is a spreadsheet with better branding.

Both are gated the same way as everything else here: a partner with the problem and data to run it against, not a demo.

---

## The refutation gap, and the first precision number

Every accuracy figure published here so far — Kano, London — comes from a labelled set built by us, and each measures the same thing: how many true pairs we find. None of them can measure a **false merge**, because none of them knows every pair that is *not* a match. Eighty-six labelled London pairs cannot tell you what the engine does to the other few thousand.

The [Leipzig entity-resolution benchmarks](https://dbs.uni-leipzig.de/research/projects/benchmark-datasets-for-entity-resolution) close that hole, and they are the reason this section exists. Their mappings are *complete*: every pair not listed is a known non-match, so precision becomes measurable for the first time. They are CC-BY-4.0, downloadable without registration, and widely enough used that our numbers can be read against other people's.

**The first run, on DBLP–ACM** — 2,616 × 2,294 records, 2,224 true pairs, no bibliographic pack, comparators declared by hand:

| | |
|---|---|
| Blocking recall | 0.9996 — one true pair never proposed |
| Surfaced recall | 0.9996 |
| Recall at `match` | 0.9960 |
| **Precision at `match`** | **0.8500** — 2,215 true, **391 false merges** |

Recall is essentially perfect. Precision is not, and the false merges have one shape: recurring generic titles. `Guest editorial` appears eight times in ACM, `Book reviews` eight, `Reminiscences on Influential Papers` seven. This is the "General Hospital" defect — agreement on a string that is identical everywhere read as evidence of identity — reproduced in a third domain, on data we did not choose or label.

**The part that is a genuine architectural finding.** Of the 254 exact cross-source title collisions that are *not* true pairs, 213 disagree on year. And year agrees on **2,224 of 2,224** true pairs — 100.00%. A discriminator this clean should be trivial to exploit, so we tried the obvious thing and raised its weight:

| `year` weight (against 7.0 on title + authors) | Precision | Recall |
|---|---|---|
| 0.5 | 0.8500 | 0.9960 |
| 2.0 | 0.8761 | 0.9987 |
| 7.0 | 0.6531 | 0.9996 |
| 25.0 | 0.6531 | 0.9996 |

Precision peaks early and then **collapses**. The reason is structural, not a tuning miss: a weight is symmetric. Weighting a field up punishes disagreement, but it rewards agreement by exactly as much — and *agreement on a year is not evidence*, because thousands of unrelated papers share one. Turning up a discriminator turns up the noise it sits in. There is no weight that recovers what the field plainly knows.

This is the same argument the geographic veto already makes in the code — "two buildings 143 km apart are not one building however alike their names" — but it is now demonstrated on an attribute with no coordinates, in a domain with no pack, on someone else's data. **Some attributes refute without confirming.** They cannot be expressed as weights, and today arche has no way to declare one.

Grepping for what exists: there are exactly **two vetoes in the entire engine**. `veto_km`, which requires latitude and longitude, and `id_conflict`, which is hardcoded to the literal field name `national_id`. Both are domain-specific, and neither is reachable from a declaration. So the gap is not a missing books pack or a missing product pack — it is a missing *primitive*, and it blocks books (year, edition), products (model, pack size, voltage), charge points (connector type), and people (date of birth) identically.

**The deliverable, therefore, is a declarable discriminator veto** — an attribute the author marks as refuting, which demotes to `review` on disagreement, never to `no_match`, and never fires on a missing value, because you cannot refute on absent evidence. That is the rule the geographic veto already follows; this generalises it rather than inventing it.

**Built, and measured on the same run.** `refutes_below` ships as a comparator flag. On the declaration above, with nothing else changed:

```text
baseline (year scored)     P=0.8500  R=0.9960   (TP 2215, FP 391)
year refutes_below 0.99    P=0.9506  R=0.9960   (TP 2215, FP 115)
```

276 false merges removed, **zero true matches lost**. The earlier projection on this page said ≈ 0.93; the measured figure is better because year also separates near-title false merges, not only the exact-title collisions the projection counted. Reproduce with `uv run python data/scripts/benchmark_leipzig.py`.

One detail worth keeping, because it inverts the obvious intuition: a heavy weight does not merely fail to demote a false merge, it *overcorrects* on true ones. At weight 25 a disagreeing pair falls under the floor and the edge is dropped entirely, so a reviewer never sees the conflict. A refutation keeps the pair and queues it. The weight is worse in both directions at once.

No shipped pack declares `refutes_below` yet, and a test enforces that. Turning it on for `place` changes that pack's published numbers, so it is a separate measured decision.

It was sequenced ahead of any new entity lane on purpose. A lane built before it inherits the defect; a lane built after it gets the fix for free.

| Deliverable | Detail |
|---|---|
| **Discriminator veto** | **Done.** Declarable, demote-to-review, missing-value-safe; the geographic veto becomes one instance of it rather than the only one |
| **Leipzig as a standing benchmark** | DBLP–ACM and Abt–Buy in CI, precision and false-merge rate reported every release, published whichever way they fall |
| **A false-merge rate on every benchmark page** | Kano and London currently report recall only; both get the caveat until a complete mapping exists for them |

**On Apache Ossie** (incubating; formerly Open Semantic Interchange): it is a vendor-neutral way to exchange *semantic models* as JSON/YAML across analytics and BI tools. It is not a matching engine and not a competitor — the honest seam is arche's declaration, which is already a portable contract about what fields mean. Emitting and ingesting that as an Ossie-compatible artifact is plausible and cheap. It is deliberately **not** committed: the project is in incubation, its schema will churn, and threading a moving format through our most load-bearing contract buys nothing this quarter. Watched, not adopted.

---

## The document lane, and what is being built in it

**In progress for v0.4.0a1.** This section exists so the work is legible while
it is happening rather than only after it lands.

The lane is the path from a file on disk to a signed decision: **parse → read
metadata → detect under a statute → extract → assemble a record → resolve →
report**. `arche.resolve_documents()` runs all of it in one call, and
[notebook 02](https://github.com/unpatterned-labs/arche/blob/main/examples/notebooks/02_same_person_across_documents.ipynb)
does three PDFs in three cells with no user-written regex.

Where it sits against the rest of the project: extraction is **not** the
differentiator. Vendors in that space produce *references*. What arche adds is
which real-world entity a reference denotes, whether the data may move, and a
signature over the decision. The document work exists so that differentiator is
reachable in under a minute rather than after an afternoon of glue code.

### Shipped in this lane

| | What changed |
|---|---|
| **One-call resolution** | `resolve_documents(source)` — glob, directory or file — returns records, verdicts and a report. Thirteen notebook cells became three, and four user-written regexes became none. |
| **Document metadata** | `ParsedDocument.metadata` was `{}` for the life of the module while every PDF carried title, author, producer and dates. Now populated, with a typed `.info` view. |
| **Producer provenance** | `browser-print` / `html-renderer` / `enterprise-report` — whether a human printed a document from a browser or a reporting system emitted it. A trust signal from data we already hold. |
| **Metadata as personal data** | A bank statement's `Title` carries an account fragment; a flight confirmation's `Subject` carries a booking reference. Those fields are now scanned and masked instead of invisible to redaction. |
| **Progress and timing** | A three-minute run used to print nothing and was indistinguishable from a hang. Progress writes to a **stream**, never through `logging` — the library silences third-party loggers, so anything logging-based would be swallowed by its own silencer. TTY, CI log, notebook and agent (`ARCHE_PROGRESS=jsonl`) all work, with no new dependency. |
| **Baseline statute floor** | `Pipeline(on_uncovered="baseline")` — see below. |

### The baseline floor, and the trap it closes

arche ships statute packs for six regimes. **Everywhere else — the UK, the US
outside HIPAA, India, Brazil, most of the world — no statute resolves, and a
Pipeline with no statute returns `redacted_text` unchanged.** Nothing is masked.

That becomes dangerous the moment jurisdiction detection lands. Measured on a
British bank statement:

```text
jurisdiction="NG"    36 false PII-2-TIN detections   email IS masked
jurisdiction="GB"     0 false detections             email is NOT masked
```

So "correcting" the jurisdiction takes the headline false-positive count from 36
to zero **by switching protection off**. That is the most flattering available
reading of our own data, and this project has already had to retract claims of
that shape.

`BASELINE.yaml` is the floor that makes the correction safe: the categories no
regime disputes (email, phone, national identifier, passport, address, payment
card), at the strictest action any shipped pack assigns. It is **not law**, and
every citation it emits says so in words — `"no statute pack for this
jurisdiction — arche baseline floor, not law"`. It invents no lawful bases and no
data-subject rights, because those are creatures of statute. Country-specific
identifiers are deliberately absent: a floor that guessed at foreign identifiers
would repeat the mistake it exists to fix.

It is **off by default** (`on_uncovered="silent"`), so no existing caller's
output moves. `"warn"` names the uncovered jurisdiction and the consequence.

### Still to build in this lane

| Item | Note |
|---|---|
| **Jurisdiction inference** | Evidence-based and inspectable — registration identifiers, postcode shape, currency, issuer name, phone country code — that **abstains** rather than guesses when signals conflict. An explicit `jurisdiction=` always wins. Gated behind the floor above, for the reason given. |
| **Typed extraction** | `extract(schema=YourModel, document=parsed)` returning a validated instance with spans and pages. pydantic is already a base dependency, so this costs nothing on the wheel. |
| **Export** | `to_rows()` as the primitive, then `to_csv()`. Google Sheets and pandas become three lines of user code on top of it rather than shipped surface with an auth story to own. `to_json()` and `save_json()` already exist; masking is the default on every path. |
| **Report shapes** | `table()` for reading, `to_dicts()` for rows, `to_json()` for a ticket or the next pipeline stage — plus timing, so "what was slow?" is answerable after the fact. |
| **Pluggable parse/extract backends** | `parse` and `extract` take a `backend=`. The default, `"local"`, runs entirely on your machine and makes no network calls. The interface is public so a hosted extractor can be substituted where a document defeats local parsing. Any backend that leaves the machine must declare an egress class, is refused under `ARCHE_OFFLINE=1`, and is recorded in the decision pins — a decision produced remotely is not byte-identical to one produced locally, by design. arche does not bundle, endorse or require any commercial extractor, and none is installed by default. |
| **Content credentials (C2PA)** | **Gated, not scheduled.** The type ships with an honest empty state; the reader does not. XMP is zero bytes in every PDF available to this project, so a reader could be written but not demonstrated, and an untestable trust feature is worse than none. `ai_generated` is tri-state: absence of a manifest yields *unknown*, never *human-authored*. Gate: build it when we hold at least five documents that actually carry a manifest. |

### Not built, and why

**A fix to context-free identifier detectors.** The 36 false TINs are only
partly a jurisdiction bug — `NG_TIN` matches a bare ten-digit run, so a
*correct* Nigerian jurisdiction on a Nigerian bank statement still flags every
transaction reference. That is a detector-calibration change which moves
published numbers, and it belongs in its own release with its own measurement.

**New EU/US identifier packs.** That is what currently makes "correct
jurisdiction" mean "fewer detectors". It is a large separate project and should
not be smuggled into this one.

---

## Next: v0.3.0a2 and the UK charge-point benchmark

A dated plan, so it can be held to. Target **2026-08-18**.

Two correctness fixes come first, because both were found by auditing our own claims and one of them is a security defect in shipped code.

**`EgressGuard` fails open on nested detections.** The guard's stated guarantee is that no raw *detected* value appears in any output field. On overlapping spans that is false. The Nigerian detector set produces nesting on ordinary addresses: `PII-4-ADDRESS` covering "12 Awolowo Road, Ikoyi, Lagos" and `PII-4-LOCATION` covering "Lagos". The projection consumes the inner span, skips the outer one, and the address prefix crosses the boundary in clear while `PII-4-ADDRESS` disappears from the output fields entirely. Severity inverts as well: the dropped span is the more restricted one. The fix is not novel work — `policy.engine` already resolves overlapping spans into disjoint regions with most-restrictive-action-wins, and that logic ports across. Ships as **v0.3.0a2** with the defect described plainly in the changelog and `SECURITY.md`, not folded into a "bug fixes" line.

**Then the UK charge-point benchmark**, and the question it exists to answer is whether this engine is calibrated to Nigeria or overfitted to it. Those are different problems with very different costs.

Early probing says calibrated, and says so in a useful way. The shipped place pack carries `decay_km: 3.0` and `veto_km: 10.0`, sized for health facilities kilometres apart. UK charge points that are genuinely different entities sit tens of metres apart, so geographic similarity saturates near 1.0 for true and false pairs alike and the veto never fires. The place frequency table has the same shape of gap: it is built on health, energy, education and civic vocabulary, so `supercharger`, `charging`, `rapid` and the operator names are unseen tokens, hit the unknown floor, and read as *rare* — the "General Hospital" failure reproduced in a domain the table has never seen. Recovering accuracy needed **parameters and a frequency stratum, not comparator changes**. If that holds up under a real labelled set, the finding is that the architecture generalises and the calibration does not travel, which is the honest and much cheaper answer.

**Independence is the gate, and it runs before anything else.** Open Charge Map is an aggregator and may ingest the national registry; if it does, that pair is a key join wearing an entity-resolution costume, exactly as GRID3 and OpenStreetMap were in Kano. The test is the one already published on [the place benchmark](place-benchmark.md): median separation and the fraction of matches at exactly 0.00 km. It runs first, and its result is published whichever way it falls. A failed independence test is a finding, not a failed benchmark.

| Deliverable | Detail |
|---|---|
| **v0.3.0a2** | `EgressGuard` overlap fix with nested-span tests; disclosure in `CHANGELOG.md` and `SECURITY.md` |
| **Truth-in-docs sweep** | This page's MCP claims, corrected above; statute-pack version labels; the wheel-size and test-count figures; the "independently-recorded boundaries" phrasing that our own benchmark page contradicts |
| **UK charge-point benchmark** | Independence test as a gate, 300–500 stratified labelled pairs, precision at `match` ≥ 0.95, surfaced recall ≥ 0.90, false-merge rate ≤ 0.02, blocking recall ≥ 0.98 at metre scale |
| **An EV comparator pack + frequency stratum** | Calibration shipped as data, not code, and reported as the finding |

**Explicitly not in this window:** the MCP server; an `arche-langchain` package; document extraction of our own. On the last one the position is settled — vendors in that space produce *references*; what arche adds is which real-world entity a reference denotes, whether you may retain it, and a signature over the decision. Bring your own extractor.

---

## Representation: where a learned vector may and may not enter

We reviewed this properly — place and Earth embeddings, dense vector matching, and hyperdimensional computing — against the shipped engine. The position, and the work it implies, are stated here because "does arche use embeddings?" is a fair question with a specific answer.

**No learned vector enters the decision path.** Not as a comparator, not in the distinctive-evidence gate, not in `factors`. Three reasons, in descending order of how hard they are to argue with:

- **Frequency weighting cannot be expressed as a similarity.** Fellegi-Sunter prices agreement at `log(m/u)`, where `u` is a property of how common the value is *in the population being linked*. A cosine is a function of two strings; there is no argument for the population. Agreement on "Ibrahim" being weaker evidence than agreement on "Gyaranya" is not a fact about those strings, and no encoder recovers it.
- **A single opaque score cannot clear a gate honestly.** `DISTINCTIVE_FLOOR = 0.75` is a claim about rarity. A cosine of 0.75 is not, and letting one clear the other would make the abstention guarantee decorative.
- **An embedding of a name is invertible personal data**, and it would break both the "no raw PII in evidence" guarantee and the replayability of `decision_id`, which a model update silently invalidates.

**Two places a model legitimately helps, and we intend to use both.**

*Candidate generation.* Every production place matcher in this literature puts its embedding here and nowhere else. Overture's blocking model uses name, category and address embeddings; the winning Foursquare Kaggle solutions generated candidates from spatial proximity **and** name-embedding neighbours, because neither channel alone reached acceptable recall. OpenSanctions states the division of labour plainly — embeddings are *"phenomenal at surfacing a wide set of match candidates"* but *"less suited to help discern false positives."* A blocker changes which pairs are offered, never what a decision means, so it never touches `decision_id`.

*Pack authoring, offline.* A model proposing name-equivalence and orthography groups that a human accepts into YAML buys cross-script recall with no runtime vector, exact frequency weighting, and the contributor model intact. This is the pattern `extract_places_llm` already ships — model proposes, engine verifies — pointed at the data packs for the first time.

**The blocker is not the representation; it is that we cannot yet measure the question.** There is no African name-matching benchmark and no Nigerian place-resolution evaluation set — not in this repository and not in the published literature. Every place-ER benchmark we could verify is North American, European, or East and Southeast Asian. So the honest position is not "an embedding would lose" but "arche cannot tell whether it would win," and the instrument that decides it is the deliverable.

**Scope of the next series of work, in order:**

| Work | What it is |
|---|---|
| **A place frequency table** | Correctness, not research. Only person and artist frequency corpora ship today, so facility words (`hospital`, `health`, `clinic`, `centre`) are unseen by the table, read as rare, and clear the distinctiveness floor. Two facilities named "General Hospital" 4.4 km apart currently merge with the same score and evidence as two sharing a genuinely rare name. The mechanism is right — on person names it correctly routes `Ibrahim Musa` to `review` — the corpus is missing |
| **Two licence classes** | `cdla-permissive-2.0` and `apache-2.0` are absent from the provenance firewall's taxonomy, so Overture Places — permissively licensed, and deliberately free of OSM share-alike — classifies as `unknown` and is barred from packs. The firewall is over-restrictive against the best available source, on a taxonomy gap rather than a licence problem |
| **The Nigerian place-resolution gold set** | Thousands of adjudicated pairs, not the 120 we have. Labelled with two independent models over an explicit evidence hierarchy, disagreements routed to human adjudication. Published. This is the contribution, and no equivalent exists for any African country |
| **Blocking recall, measured** | `blocking_recall()` returns a number only if you hand it truth pairs, which no benchmark of ours currently does. Above ~0.95 and the embedding question is closed for the foreseeable future. Below, and the answer is a name-similarity blocking channel — a fourth key beside h3, rare-token and shared-id |
| **Comparators before contenders** | Thread `orthography=` through `reconcile()`; give the `type` comparator a calibrated non-zero weight instead of shipping it at 0. Both are known gaps, both are cheap, and both must be closed before anything is benchmarked against them |

**Ship criterion for a blocking channel, set in advance:** recall up ≥2 points absolute, candidate pairs up ≤25%, and the gain concentrated in the named zero-token-overlap slice. `false_merge_rate` must stay at 0 on hard negatives. If the work is blocking-only, the `match` count must **not** change — newly blocked pairs are unlabelled, so a run reporting "more matches" is reporting nothing until those pairs are adjudicated.

**What we will not build:** an embedding comparator inside the weighted mean or the log-odds sum; an end-to-end neural matcher (it is a baseline to report against, not a component); Earth or location embeddings inside resolution — the location-encoding field's own consolidating benchmark contains no matching task, and swapping a distance a reviewer reads in metres for a cosine they cannot is a straight loss; and embeddings for facility-type alignment, because "Health Post → PHC" is an ordinal tier relation usually recording an upgrade event, not a similarity.

## Not committed

Visible on the horizon; named so adopters can push, not promised. Jurisdiction depth beyond Africa (Brazil LGPD, India DPDP, Indonesia PDP, Mexico, Philippines — each roughly one statute pack plus one detector pack); sector packs over the African base (health, agriculture, energy, manufacturing); multimodal spatial grounding.

**Hypervector/HDC matching** stays research-only, and the gate is now specific: it enters the roadmap if a seeded binary-hypervector comparator raises recall by ≥3 points absolute at `false_merge_rate = 0` against the shipped token-frequency and Fellegi-Sunter matcher, on published benchmark slices, without enlarging the review queue, without adding a numeric dependency to the base wheel, and while still answering *which token* cleared the gate. Until the benchmark exists this is not evaluable, so the first deliverable is the benchmark, not the matcher. Worth stating plainly: hyperdimensional computing's own 52-page applications survey contains no record linkage, entity resolution, or name matching. There is no prior art here and no baseline but our own.

---

## Direction changes worth stating

A roadmap that never records its own reversals is a wish list. Four, with reasons:

- **A new entity lane is no longer the next step; a missing primitive is.** The plan was to pick a lane — products, or books — and build it. Running a public benchmark with complete ground truth first showed that the engine's weakest point is not coverage of a domain but the absence of any way to declare an attribute that *refutes*, and that no amount of weighting substitutes for one. Building a lane on top of that would have shipped the defect into it. → *[the refutation gap](#the-refutation-gap-and-the-first-precision-number)*

- **The lead moved from "African PII detection" to "know the real-world entity, prove the decision."** Detection is a layer, not the product; resolution plus attestation is. African calibration remains the wedge and the credential — the hardest identity data in the world — rather than the scope. → [the thesis](representation-engine.md)
- **An MCP server is now on the roadmap at all**, reversing an early non-commitment ("agent integration is downstream of framework adoption"). Agents turned out to be an *install surface*, not a later channel. The server is **not** built — see *In flight*, where an earlier false claim on this page is corrected. The reversal of the non-commitment stands; the implementation has not started.
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
