# Architecture

*How arche-core is actually layered, which component is allowed to conclude anything, and where the map is still untidy.*

---

The product describes itself in four verbs: **detect · resolve · protect · attest**. Find the entities, work out who they actually are, hold them under the law that applies, and sign the decision.

Those four verbs are a good account of what you can *do* with arche. They are not how the code is layered, and a page that draws them as four boxes with arrows between them would be the same mistake this page is replacing. The previous version of this page described five substrates — detect, policy, sign, audit, workflow — flowing one into the next. Two of the four headline verbs did not appear in it at all, and the page carried a note apologising for covering "the detection half". When an architecture diagram needs a note explaining which half of the product it omits, the diagram is wrong.

**The organising principle is authority: what a component is permitted to conclude.** Almost everything in arche produces evidence and is forbidden to reach a verdict. A small, named set of components reaches verdicts, and each one has a written combination law. Attestation then binds a verdict to the evidence and the versions that produced it. The four verbs cut across those layers rather than stacking on top of each other.

<div class="layers" markdown>
<div class="layer layer--binds" markdown>
<div class="layer__label" markdown>
<span class="layer__name">attest</span>
<span class="layer__role">binds a verdict to its evidence</span>
</div>
<div class="layer__body" markdown>
`ids` · `sign` · `attest` · `credentials`
<span class="layer__note">content-addressed, signed, pinned</span>
</div>
</div>
<div class="layer layer--decides" markdown>
<div class="layer__label" markdown>
<span class="layer__name">deciders</span>
<span class="layer__role">five combination laws, each written down</span>
</div>
<div class="layer__body" markdown>
reconcile gate · coref gate · geographic veto · statute engine · egress guard
<span class="layer__note">the only layer permitted to conclude anything</span>
</div>
</div>
<div class="layer" markdown>
<div class="layer__label" markdown>
<span class="layer__name">proposers</span>
<span class="layer__role">produce evidence, never verdicts</span>
</div>
<div class="layer__body" markdown>
detectors · comparators · blockers · provider adapters · LLMs · docling
</div>
</div>
<div class="layer" markdown>
<div class="layer__label" markdown>
<span class="layer__name">the spine</span>
<span class="layer__role">the vocabulary everything speaks</span>
</div>
<div class="layer__body" markdown>
`canonical.Reference` · `ids` · `declare.Declaration`
</div>
</div>
</div>

Read it bottom-up. Nothing in the spine decides anything; nothing in the proposer layer decides anything; the decider layer is small enough to enumerate and each entry has a rule you can quote.

---

## The spine

Three modules carry the vocabulary every other layer speaks. They are the part of arche worth understanding first, and the part the old page never mentioned.

### `canonical.Reference`: the common currency

A `Reference` is one record's worth of claims about one thing: a list of `Attribute`s, a `record_id`, and a `source_system`. It is what extraction produces and what resolution consumes, and it is the reason the two halves of the product are one product.

The distinction it encodes is the one that carries the whole engine: **identity attributes versus descriptive attributes.** Agreement on a common name is weak evidence. Agreement on a distinctive identifier is strong. An `IdentityAttribute` is the subset that can tell one entity from another; everything else describes.

References arrive from two directions. `Reference.from_record(record)` is the structured path — you already have rows. `arche.extract` and `arche.ensemble` are the unstructured path — you have prose. Both land in the same shape, so the resolution engines never need to know which one you used.

### `ids`: the canonicalisation everything signable passes through

Every identifier arche emits is a pure function of its inputs. `ids.py` fixes what "the same inputs" means:

- **Canonical JSON** — sorted keys, compact separators, and no raw floats. Every float is rendered as a fixed 4-decimal string, so a hash does not depend on which machine computed it.
- **NFKD-normalised strings**, through the same normaliser the matcher compares with.
- **No timestamps** in the reproducible core.

That yields `document_content_id`, `reference_id`, `decision_id` — and one deliberately different thing, `entity_id`, which is an HMAC pseudonym keyed to the issuer. The reason is stated in the module: a bare SHA-256 of an eleven-digit NIN is brute-forceable, so anything derived from a low-entropy identifier and intended to be shared is keyed, not hashed. Keyless ids remain useful locally, but they are pseudonymous personal data, not "PII-free", and `attest` refuses to sign them by default.

### `declare.Declaration`: one YAML, five derived artefacts

This is arguably the most important architectural idea in the product, and the old page did not mention it.

Splink wants same-schema tables. Senzing wants its attribute dictionary. arche wants *your* schema, plus a statement of what your fields mean. One YAML assigns each field a role from a small closed vocabulary — `identifies`, `describes`, `ignore`, plus the orthogonal `restricted` axis — and from that single artefact arche derives:

| Derived from the declaration | Used by |
|---|---|
| Comparator specs | `crosswalk(..., decl=)` |
| Matcher slot assignment | `pairwise(..., decl=)` |
| Masking and disclosure policy | `render`, `report`, `attest` |
| An LLM extraction contract | `decl.tool_def()`, `arche.llm` |
| A content-hash pin | every `decision_id` produced under it |

The pin is what makes the declaration architectural rather than convenient. Reformatting the YAML does not change it; changing a weight does. It enters the decision hash, so the same two records under a different declaration produce a different `decision_id`. The representation is part of the claim.

Validation is deliberately unforgiving — unknown keys and typo'd roles are errors, each naming the offender — because a misspelled key in a file that governs disclosure must never silently mean "unrestricted".

```python
from arche.canonical import Reference
from arche.declare import Declaration
from arche.ids import reference_id
from arche.resolve import pairwise

decl = Declaration.from_yaml("examples/declarations/fisheries.decl.yaml")

a = Reference.from_record(
    {"lot_id": "A1", "supplier_name": "Ngozi Adeyemi", "vessel_id": "IMO9074729"},
    decl=decl,
)
b = Reference.from_record(
    {"lot_id": "B7", "supplier_name": "N. Adeyemi", "vessel_id": "IMO 9074729"},
    decl=decl,
)

print("declaration pin :", decl.pin())
print("reference_id a  :", reference_id(a, key=b"k" * 32))
print("quota restricted:", decl.restricted_for("quota_licence"))

d = pairwise(a, b, decl=decl, issuer_key=b"k" * 32)
print("decision        :", d.identity, "/", d.action, "score", round(d.score, 3))
print("gate            :", d.gate)
print("factors         :", d.factors)
print("declaration pin in the decision:", d.pins["declaration"])
```

```text
UserWarning: declaration 'fisheries-landings': fields ['vessel_id', 'quota_licence']
all map to the single pairwise identifier slot; only 'vessel_id' is used on the
pairwise path (crosswalk uses all of them).

declaration pin : fisheries-landings@1.2.0:sha256:28f13195e89a25e3
reference_id a  : ref:hmac-sha256:e20a39fcbb9d4b1cd4f6da33caa45295a64b0453907290eefc12b9395b1d85f0
quota restricted: True
decision        : same_entity / merge score 1.0
gate            : {'distinctive_cleared': True, 'clearing_signal': 'national_id', 'floor': 0.75}
factors         : {'name': 0.7826, 'national_id': 1.0, 'name_tf': 0.3677}
declaration pin in the decision: fisheries-landings@1.2.0:sha256:28f13195e89a25e3
```

Two things in that output are worth reading rather than skimming. The warning is the declaration layer telling you a real limitation to your face: the pairwise engine has one identifier slot, your declaration named two identifier fields, and only the first is used on that path. And `clearing_signal: national_id` is the slot name, not a claim about the vessel — the pairwise matcher's slots were named for the person pack and a declared `kind: id` routes into them.

---

## Proposers: everything that may not conclude

| Proposer | Produces | Never produces |
|---|---|---|
| `detect.{ng,ke,za,gh,_africa}` | Spans with categories and validator status | The action to take on them |
| `detect.gliner`, `detect.presidio` | Additional candidate spans | Anything the deterministic validators did not confirm |
| `resolve._matcher` comparators | Per-field similarities in [0, 1] | A match |
| `resolve._block` | Candidate pairs worth scoring | A score |
| `resolve._tokenfreq` | Token distinctiveness over a population | A threshold |
| `adapters.*` | `ProviderEvidence` with a licence class | A verdict |
| `arche.llm` | Proposed records and place mentions | A validated field, an entity id, or a merge |
| `arche.doc` (docling) | Parsed document text | Any interpretation of it |

Four of those deserve a note.

**Detectors detect; statutes decide.** A `Detection` carries a category, a span, a `regulatory_citation` and a `sensitivity_tier`. What happens to it — mask, tokenize, drop, generalize, audit, retain — is the statute's call, not the detector's.

**Comparators score; gates decide.** A comparator returning 1.0 on a name is saying "these strings are identical", which is a fact about strings. Whether that permits a merge is a separate question with a separate answer, and the answer depends on how *distinctive* the shared token is in the population being reconciled.

**Providers fetch references; arche resolves.** `adapters/` is new in this line and its `__init__.py` states four rules. An adapter returns `ProviderEvidence` — candidates in canonical form plus provenance — and nothing an adapter says auto-merges. Every adapter is an egress destination, because sending a citizen's address to a geocoder *is* a cross-border transfer, so adapters route through `EgressGuard` and the statute pack decides whether a reference may be sent at all. And there is a **provenance firewall**: provider responses never feed the data packs, the frequency tables, or the benchmark, because the moment they do, those assets inherit the most restrictive licence in the chain. Every evidence object carries a `licence`, `may_enter_packs()` accepts open classes only, and `pin()` declares `reproducible: False` — a decision that depends on a live API response cannot be replayed by a stranger, and the attestation has to say so.

**Models propose; validators dispose.** The LLM lane is a proposer like any other. It fills a declaration-derived schema; the same deterministic validators then check every field. `arche.llm.harness` exists to *grade* a model against the engine, not to defer to it.

---

## Deciders: the five things allowed to conclude

This is the short list. Each entry has a combination law written down in the code, and the reason it is not the same law as its neighbours.

### 1 and 2. Two resolution gates, deliberately not merged

`resolve` ships two engines because there are two questions, not because of history:

| | `reconcile` / `crosswalk` | `coreference` / `pairwise` |
|---|---|---|
| Question | Link two lists at scale | Are these two the same? |
| Combination law | Weighted arithmetic mean | Fellegi-Sunter log-odds |
| Gate clears when | A distinctive-*kind* comparator reaches the floor **and**, for name-like kinds, what the two names share is itself rare | A genuinely **rare** shared name token exists |
| Output | Edges with `decision_id` and evidence | A signable `CoReferenceDecision` |

They share their primitives — comparators, normalisers, the token-frequency table, and the `DISTINCTIVE_FLOOR = 0.75` constant, all in `resolve/_matcher.py`, `_tokenfreq.py` and `_gate.py`. They now also share the *principle* behind the gate, which they did not until recently, and the story is worth telling because it is what this page is for.

Coref has always required a rare shared token, so two identical **common** names cannot clear it. Crosswalk took the maximum over its distinctive comparators, and a `placename` comparator returning 1.0 on two identical strings cleared the gate on its own — carrying no claim about rarity at all. The consequence was measurable and bad: two facilities named "General Hospital" 4.4 km apart merged with **exactly the same score and evidence** as two sharing a genuinely distinctive name.

The root cause was not the gate but the corpus. No place frequency table shipped, so the place pack fell through to the *person* table, where `hospital`, `health`, `clinic` and `centre` are unseen and therefore read as **rare**. Both halves are now fixed: a place table is built from CC0 and CC-BY sources across twenty countries and four sectors, and the crosswalk gate prices name-like similarity by the rarity of what the names actually share.

Two details of that fix are load-bearing. It consults distinctiveness **only against a population-scale table** — over a small self-calibrated corpus a token seen twice scores 0.71, below the floor, so the gate would refuse everything; callers passing their own corpus table keep the previous behaviour exactly. And rarity is measured two ways combined with `max` — a literally shared rare token, *or* a rare residual on both sides once generic words are stripped — because requiring literal overlap alone demoted 19 true matches whose identifying word differed by a single letter (`Kalahaddi` / `Kalahadi`) at zero distance. The measured cost of the final version on the Kano crosswalk is **2 pairs moved from `match` to `review`, and none lost**.

The scores from the two engines are still not comparable. That part is on purpose.

### 3. The geographic veto: a constraint, not a weight

Before v0.3.0a1 geography was a scored signal in the place pack, weighted 1.0 against name and token-frequency's combined 4.0. A weighted signal can be outvoted, and it was: two Kano facilities sharing a common Hausa name merged 143 km apart, with the geo comparator itself scoring 0.000.

`veto_km: 10.0` moves distance out of the scoring and into the decision. Two properties are deliberate: it demotes to `review` and **never** to `no_match`, because distance says a human must look rather than that the answer is no; and records without usable coordinates are never vetoed, because you cannot refute a claim on evidence you do not have.

```python
import csv
from collections import Counter

from arche.resolve import crosswalk

with open("data/GRID3_NGA_health_facilities_v2.csv", encoding="utf-8-sig") as fh:
    grid3 = [r for r in csv.DictReader(fh) if r["state"] == "Kano"]
with open("data/osm_kano.csv", encoding="utf-8-sig") as fh:
    osm = [r for r in csv.DictReader(fh) if r["name"].strip()]

A = [{"name": r["name"], "lat": r["lat"], "lon": r["lon"]} for r in osm]
B = [{"name": r["facility_name"], "lat": r["latitude"], "lon": r["longitude"]}
     for r in grid3]

result = crosswalk(A, B, entity="place")
print(Counter(e["decision"] for e in result["matches"]))

vetoed = [e for e in result["matches"] if "geo_conflict_km" in e["evidence"]]
print("edges carrying geo_conflict_km:", len(vetoed))

worst = max(vetoed, key=lambda e: e["score"])
print("names   :", A[worst["a_id"]]["name"], "<>", B[worst["b_id"]]["name"])
print("score   :", round(worst["score"], 3), "-> decision:", worst["decision"])
print("evidence:", worst["evidence"])
```

```text
Counter({'match': 564, 'review': 529})
edges carrying geo_conflict_km: 279
names   : Kauyen Adam Health Post <> Kauyen Adam Health Post
score   : 0.805 -> decision: review
evidence: {'name': 1.0, 'name_tftoken': 1.0, 'name_type': 1.0, 'geo': 0.025, 'distance_km': 11.06, 'geo_conflict_km': 11.06}
```

That is the architecture in one edge. Two byte-identical names, every name comparator at 1.0, a score of 0.805 comfortably over the 0.7 threshold — and the edge still lands in `review`, carrying the distance that put it there. No weight could have produced that outcome; only a constraint could.

The threshold was set by a sweep, and what it can and cannot tell you is documented honestly in [the place benchmark](place-benchmark.md): LGA agreement moves 78.4% → 88.1%, and that number is a consistency check against a weak label, not validation.

### 4. The statute engine

`arche.policy` routes each detection through the applicable statute and applies one of **six closed actions**. The set is closed on purpose; a seventh action is a design decision, not a configuration change.

| Action | Behaviour |
|---|---|
| `mask` | Replace with a `[CATEGORY]` placeholder |
| `tokenize` | Replace with a deterministic token |
| `drop` | Remove the span entirely |
| `generalize` | Reduce specificity (DOB → year, address → city) |
| `audit` | Log the decision, leave the text untouched |
| `retain` | Allowlist; pass through unchanged |

Six statute packs ship as YAML at `arche/policy/statutes/`:

| Pack | Jurisdiction | `version` | `review_status` |
|---|---|---|---|
| `NDPA-2023.yaml` | Nigeria | `v1.0` | `self-reviewed` |
| `GDPR.yaml` | EU/EEA | `v1.0` | `self-reviewed` |
| `HIPAA-SAFE-HARBOR.yaml` | US (health) | `v1.0` | `self-reviewed` |
| `KENYA-DPA.yaml` | Kenya | `v0.1-scaffold` | `self-reviewed` |
| `POPIA.yaml` | South Africa | `v0.1-scaffold` | `self-reviewed` |
| `GHANA-DPA.yaml` | Ghana | `v0.1-scaffold` | `self-reviewed` |

Every category in every pack carries a statute-section citation. The two labels are independent by design: `version` is a claim about our work, `review_status` a claim about the world — who vouches for the mappings. No pack claims `regulator-reviewed`, and the loader fails closed on one that does so without naming a reviewer. The three `v0.1-scaffold` labels remain in the shipped YAML; they understate packs that are complete, and correcting them is outstanding in our roadmap.

### 5. The egress guard: fail-closed, four teeth

`guard.EgressGuard` wraps a statute-aware `Pipeline` so that nothing crosses a boundary a policy did not permit. All four teeth default to deny:

1. **Deny on absence.** No statute means no policy means no permission. This one matters more than it looks: a bare `Pipeline()` with no statute returns text *unchanged*, so the guard has to treat "no policy" as "no permission" rather than trusting the pipeline's output.
2. **Deny on undeclared cross-border transfer**, with the statute cited.
3. **Deny on a provider outside the allow-list.**
4. **Deny on exception.** Any error becomes a refusal, never a fallthrough that emits the original text.

```python
from arche import Pipeline
from arche.guard import EgressGuard, GuardDenied

# No statute means no policy means no permission.
try:
    EgressGuard(Pipeline(), key="k" * 32).guarded("NIN 12345678901")
except GuardDenied as exc:
    print("no statute   :", exc.reason)

guard = EgressGuard(
    Pipeline(jurisdiction="NG"), key="k" * 32, allowed_providers={"openai"}
)

projection = guard.guarded(
    "Customer Adesola Okonkwo, NIN 12345678901.", provider="openai"
)
print("projection   :", projection.redacted_text)
print("fields       :", [(f.category, f.action, f.tier) for f in projection.fields])

try:
    guard.guarded("NIN 12345678901", provider="openai", crosses_border=True)
except GuardDenied as exc:
    print("cross-border :", exc.reason)
    print("citation     :", exc.citation)
```

```text
no statute   : no statute configured on the pipeline — no policy means no permission to emit
projection   : Customer Adesola Okonkwo, NIN [NIN:15bcda3f9265f209].
fields       : [('PII-2-NIN', 'mask', 'high')]
cross-border : cross-border transfer without a permitted basis (declared=None, permitted=['binding_corporate_rules', 'explicit_consent', 'ndpc_adequacy_assessment', 'standard_contractual_clauses'])
citation     : NDPA-2023 cross-border transfer rules
```

The projection guarantee is precise, and worth stating precisely: **no raw *detected* value appears in any output field.** Dropped categories are removed; everything else becomes a strong keyed token from `arche._tokens` — deliberately not the 32-bit masking token `policy.engine` uses, which is fine for masking and far too small for anything an outside party will hold. The guarantee does not extend to PII no detector found. In the output above, "Adesola Okonkwo" survives because the base rule-based pass does not carry a person-name detector for this jurisdiction; the guard cannot tokenise a span nobody proposed.

---

## Attestation closes the loop

The top layer takes a verdict, the evidence that produced it, and the pinned versions of everything involved, and makes the whole thing checkable by someone who was not there. `ids` gives it a reproducible address, `sign` gives it an Ed25519 signature over canonical JSON, `attest` gives it a PII-free claim set, `credentials` gives it a selectively disclosable wallet form.

The one thing to carry over from this page: `valid` answers "does this signature match this key", and only `trusted` answers "did that key come from somewhere I control". → [Attest: the signature on the decision](attest.md).

---

## What composes what

The layers are usable directly. These are the orchestrators that wire them up for you, and none of them does anything you could not do by hand.

| Composition | Wires together |
|---|---|
| `arche.Pipeline` | detectors → statute → `Result` (detections, policy outcomes, redacted text) |
| `arche.workflow.DSARWorkflow` | Pipeline → sign → statute-aware DSAR drafting (citizen-side, draft only) |
| `arche.sign.SignWorkflow` | Pipeline → JWS envelope over the `Result` |
| `arche.sign.VerifyExtractWorkflow` | verify → recover redacted text and policy outcomes |
| `arche.resolve.crosswalk` | blocking → comparators → weighted mean → gate → veto → edges |
| `arche.resolve.pairwise` | references → Fellegi-Sunter → gate → signable decision |
| `arche.guard.EgressGuard` | Pipeline → four-teeth deny → tokenised projection |
| `arche.resolve_places` | gazetteer lookup → compliance block → JWS receipt |
| `arche compare` (CLI) | two files → crosswalk → masked-by-default HTML report |

---

## The module map

Thirty-odd modules, grouped by the layer they belong to. This is the whole surface, including the parts that are not load-bearing.

| Layer | Modules |
|---|---|
| Spine | `canonical`, `ids`, `declare`, `_types` |
| Ingest | `ingest` (URL, SSRF-guarded), `doc` (docling, optional), `workflow._ingest` |
| Propose — detect | `detect/{ng,ke,za,gh,_africa,gliner,presidio}`, `addr`, `jurisdictions`, `extract`, `ensemble`, `locate` |
| Propose — compare | `resolve/{_matcher,_block,_tokenfreq,_orthography,_geo,_rerank,_relate}` |
| Propose — external | `adapters`, `llm` |
| Decide | `resolve/{reconcile,coreference,_gate,places,classical,artists}`, `policy`, `guard` |
| Attest | `sign`, `attest`, `credentials`, `graph.audit` |
| Present | `render`, `report`, `cli`, `workflow._format` |
| Compose | `workflow` (`Pipeline`, `DSARWorkflow`), `resolve/metrics` |
| Legacy v0.1 shelf | `audit` (in-memory), `governance`, `protect`, `types`, `models`, `config`, `graph.networkx_view` |

Detection coverage, since it is the number most often asked for: 26 ID patterns in `detect._africa.ids.ID_PATTERNS`, across the four launch jurisdictions (NG: NIN, BVN, TIN, RC, PVC, driver's licence; KE: national ID, KRA PIN, NHIF; ZA: SA ID with full Luhn and DOB/gender/citizenship decode, tax reference, passport; GH: Ghana Card, SSNIT, TIN) plus eleven further African countries (RW, TZ, UG, ET, CI, SN, CM, EG, MA, AO, MZ). Phone normalisation runs through `phonenumbers` for E.164 across all 30+ African networks. Neural NER (GLiNER2) is the opt-in `arche-core[detect]` extra and is never on the critical path — the base wheel is rule-based and CPU-only by design.

---

## Where the map is untidy

Stated so nobody has to discover it by reading source.

- **`protect.py` is not the `protect` verb.** It is a v0.1 Presidio wrapper (`detect_pii`, `redact`) reachable only through the deprecated lazy surface. The verb `protect` is implemented by `policy` + `guard` + `render`. The module name is a trap, and renaming it is a breaking change waiting for v0.4.
- **Three audit paths exist.** `graph.audit` is the SQLite one and the one to use. `arche.audit` is the v0.1 in-memory log. `governance.py` carries a hand-maintained sensitivity map that will drift from the statute YAML; it is not exported from `arche/__init__.py` and nothing outside its own tests calls it.
- **`Pipeline.process` does not write to `graph.audit`.** It builds its audit view in memory and returns it on the `Result`. Persisting it is a wiring step, not a missing feature, but today an audit log only fills up if you emit to it.
- **A declared `id_family` does not yet mint an `entity_id`.** `Declaration` exposes `binding_fields()`, but `ids.identity_binding_key` is not declaration-aware — it matches arche's own fixed identifier names. In the sample at the top of this page the merge is correct and `entity_id` is `None`.
- **`orthography=` is not wired into `crosswalk`.** It is opt-in on `shared_name_distinctiveness` and `TokenFrequencyTable.weighted_token_sim` only, and it defaults to `None` on both. The place pack does not set it, so `crosswalk(..., entity="place")` does not use the Hausa pack. The measured 13-pair gain in [the place benchmark](place-benchmark.md) came from binding the comparator explicitly. Plumbing it through the comparator spec is outstanding work.
- **`arche.detect` is a callable module.** `detect(text)` forwards to the pipeline while `arche.detect.ng.ids` is a real subpackage. The docstrings disagree with each other about whether this is temporary; the class docstring carries the later decision, which is that it stays as the documented Level-2 API.

---

## What's not in this package

Stated so adopters can hold us to scope.

- **No MCP server.** There is no MCP module in the wheel and none in the source tree. Any description of arche MCP tools is describing something that does not exist yet;
- **No FHIR R4 emission or registry/DPI adapters** (OpenCRVS, MOSIP, DHIS2, OpenG2P). Early stubs were deleted because they were empty modules pretending to be features. Adapters ship when there is a real deployment to build against.
- **No risk / churn / fraud signal heuristics.** The early `arche.signal` layer was example-tier guessing and was removed. Its compliance half is now the statute-grounded `policy_outcomes` on `Pipeline.Result`.
- **No hash-chained audit log.** The `prev_hash` and `signature` columns exist and nothing populates them. The log is append-only by convention, not tamper-evident.
- **No pluggable storage backend.** SQLite is the only one; `StorageBackend` is named in an RFC and does not exist as a protocol.
- **No pairwise place or product resolution.** `pairwise(entity="place")` raises; `crosswalk` is the place path.
- **No post-quantum signatures.** There is no `arche-core[pqc]` extra.

---

## What's next

- [How arche works](how-it-works.md) — the walkthrough of a single `Pipeline` call
- [Attest: the signature on the decision](attest.md) — what a signature does and does not prove
- [A representation engine, not an inference engine](representation-engine.md) — why the spine is shaped this way
- [The place benchmark](place-benchmark.md) — what the veto threshold was tuned against, and what that measurement cannot tell you
- [Declare your schema](../how-to/declare-your-schema.md) — the declaration layer, end to end
