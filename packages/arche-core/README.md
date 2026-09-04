# arche-core

**Know what's real.**

An open-source engine for deciding when messy records of people, places, organisations, and products refer to the same real-world entity, with evidence, not just similarity scores or identifiers.

```bash
pip install arche-core
```

## The problem

Your records came from different systems, written by different people, at different times. A supplier list, a registry export, six PDFs, a partner's spreadsheet. The same hospital, cooperative, product or person appears in all of them under different names, with no shared identifier anywhere.

Nothing in those files says which rows are about the same thing. That fact lives in the world, not in the data, so somebody has to **decide** it, and a decision that cannot be explained later is not much use in a system that pays people, ships medicine, or files a regulatory statement.

Most tools give you a similarity score. arche gives you a decision, the evidence behind it, and permission to say *I don't know*.

| | |
|---|---|
| **detect** | Find the entities and identifying data in text, documents and records. |
| **resolve** | Decide which real-world thing each reference points at, and abstain when the evidence does not support a verdict. |
| **protect** | Apply the statute that governs the data, citing the section it came from. |
| **attest** | Sign the decision together with the evidence and the exact representation that produced it. |

## What it resolves

One engine, five calibrated packs. A pack is configuration and data, never a fork.

| Pack | For | The hard case it handles |
|---|---|---|
| `person` | people | *Diallo* and *Jallow* are one name; two *Ibrahim Musa* are two men |
| `place` | facilities, addresses, settlements | identical names 282 km apart are two hospitals |
| `organisation` | companies, cooperatives, unions | a site and the company operating it share a name **and** a coordinate |
| `product_electronics` | catalogue items | a rare model code identifies; `Black T-Shirt` does not |
| `artist` | creative works and performers | one act, many stage names and transliterations |

```python
from arche.resolve import reconcile

result = reconcile(supplier_list, certifier_registry,
                   entity="organisation", id_field="id")

for edge in result["matches"]:
    print(edge["decision"], edge["score"], edge["evidence"])
```

## Bring your own candidate retrieval

At scale, the costly question is often which pairs deserve comparison. Retrieve
candidate pairs in a warehouse, search index or specialist system, then let
arche apply the calibrated comparators, gate and decision policy. Pin the
retrieval configuration so the resulting decision remains reproducible.

```python
from arche.resolve import reconcile

result = reconcile(
    supplier_records,
    product_offers,
    entity="product_electronics",
    candidate_pairs=[{
        "a_id": "supplier-7",
        "b_id": "offer-103",
        "route": "title-vector-v3",
        "retrieval_score": 0.981,
    }],
    candidate_pins={
        "provider": "warehouse-vector-search",
        "index": "travel-title@sha256:abc123",
        "filters": {"city": "Paris"},
        "top_k": 20,
    },
)
```

The retrieval score proposes a comparison. It does not decide identity. Each
returned edge includes the retrieval route, scored evidence, the verdict and a
`decision_id` that pins the retrieval provenance too.

## Persist entity decisions locally

The vNext runtime starts with a local DuckDB store for stable entity identities, immutable observations, evidence, and decision receipts. Its deterministic planner can assess a case and select only permitted, costed actions; an optional future LLM planner must use the same durable boundary and cannot execute tools or mutate identity state directly.

```bash
pip install "arche-core[runtime]"
```

```python
from datetime import UTC, datetime

from arche import attach
from arche.runtime import Entity, new_entity_id

engine = attach("duckdb:///arche.duckdb")
entity = Entity(
    entity_id=new_entity_id(),
    entity_type="organisation",
    identity_unit="legal_entity",
    created_at=datetime.now(UTC),
)
engine.store.write_entities([entity])
```

### Adapt existing resolver output

The current deterministic resolver remains unchanged. Record its emitted receipts and candidate-pair cost in the durable runtime when a caller is ready to do so:

```python
from datetime import UTC, datetime

from arche.runtime import adapt_reconcile_result
from arche.resolve import reconcile

result = reconcile(left_records, right_records, entity="organisation")
run, receipts = adapt_reconcile_result(
    result,
    run_id="run_20260902_001",
    created_at=datetime.now(UTC),
)
engine.store.write_decisions(receipts)
engine.store.write_resolution_runs([run])
```

`unsurfaced_pairs` is a cost/coverage metric, not a claim that those candidate pairs are different entities. Existing resolver factors and pins are retained as receipt provenance; callers may attach durable Evidence IDs when those records already exist.

### Open an uncertain resolution case

`ResolutionCase` is the boundary for difficult cases. It records an unresolved question and the observations already known; a permitted action authorises one source and does not invoke it. Its output must be ingested as a new Observation before normal evidence and inference can use it.

```python
from datetime import UTC, datetime

from arche.runtime import EvidenceAction, ResolutionCase

case = ResolutionCase("case_01", "Which supplier is this?", ("obs_01",), (), datetime.now(UTC))
action = EvidenceAction("act_01", case.case_id, "registry_lookup", "supplier_registry", datetime.now(UTC), "supplier-policy-v1")
engine.store.write_resolution_cases([case])
engine.store.write_evidence_actions([action])

# A connector supplies this immutable Observation; it cannot link an entity directly.
engine.ingest_action_observation("act_01", registry_observation)
```

There is deliberately no built-in external provider in `arche-core`. Applications supply a read-only connector that satisfies the explicit capability contract; the included deterministic planner can choose only among those permitted actions under an explicit budget.

`HttpEvidenceConnector` is the opt-in reference connector for an application-approved HTTPS source; it is not a bundled provider or autonomous crawler. The application retains lookup values in its request builder, while Arche persists only request/result hashes, response status, cost, and a success or failure Observation. It enforces the action's cost ceiling plus a connector-local request window. A failed or exhausted request is terminal for that action, so retries require a new `EvidenceAction` and remain visible in history.

```python
from arche.runtime import ExternalEvidenceRequest, HttpEvidenceConnector, ToolCapability

registry_connector = HttpEvidenceConnector(
    ToolCapability("supplier_registry", ("registry_lookup",), "supplier-policy-v1"),
    "https://registry.example/v1",
    # The application owns this value and it is never stored in Observation provenance.
    lambda action: ExternalEvidenceRequest("/suppliers", (("query", supplier_name),)),
    estimated_cost=0.02,
    max_requests=30,
    window_seconds=60.0,
)
engine.execute_evidence_action("act_01", registry_connector)
```

### Re-enter resolution after evidence arrives

Cases can expose deterministic evidence gaps before any planning occurs. A read-only connector must declare the same source, action type, and policy pin as the permitted action; it can return only an Observation. Normal resolver output is then recorded back against the case with persisted Evidence IDs.

```python
from arche.runtime import ToolCapability, what_would_resolve

for gap in what_would_resolve(case):
    print(gap.field, gap.reason)

# registry_connector.capability must match the persisted EvidenceAction exactly.
assert registry_connector.capability == ToolCapability(
    "supplier_registry", ("registry_lookup",), "supplier-policy-v1"
)
engine.execute_evidence_action("act_01", registry_connector)

run, receipts = engine.record_case_reconcile_result(
    case.case_id,
    reconcile_result,
    run_id="run_20260902_002",
    created_at=datetime.now(UTC),
    evidence_ids_by_decision={"xwd:...": ("ev_registry_01",)},
)
```

### Release a decision only with independent evidence

`ResolutionDecisionPolicy` is the boundary between a resolver receipt and an operational instruction. It deliberately has no universal score threshold: pairwise and batch resolver scores are not comparable or calibrated across domains. It can release only evidence-backed `link` or `create` outcomes from the policy's required number of independent Observation sources. Otherwise it records `review` (for a weak positive) or `abstain` (for an unsupported negative) in immutable case history. It never changes entity memory itself.

```python
from arche.runtime import ResolutionDecisionPolicy

outcome = engine.apply_resolution_decision_policy(
    case.case_id,
    receipts[0].decision_id,
    policy=ResolutionDecisionPolicy("supplier-link-v1"),
    recorded_at=datetime.now(UTC),
)

if outcome.action == "link":
    # An application or human workflow explicitly performs the released action.
    execution = engine.execute_released_policy_decision(
        outcome,
        application_executor,
        recorded_at=datetime.now(UTC),
    )
    print(execution.outcome, execution.result_hash)
else:
    print(outcome.action, outcome.reason)
```

`application_executor` is caller-owned and must return a hash-only `PolicyExecution`; Arche verifies that the exact policy release exists, records the executor outcome, and refuses repeat submission of the same receipt. The case history first records the resolver receipt, then the policy outcome, then any application execution. This makes a later policy revision or human decision traceable without giving the planner or connector authority to assert a canonical entity relationship.

### Plan only after assessing the case

The built-in planner is deterministic and transparent. It first returns a structured assessment of the question, candidate entities, evidence gaps, eligible actions, unavailable actions, and configured resolver methods. It then selects only compatible, read-only, costed evidence actions and at most one eligible resolver recommendation within the supplied budget; planning does not execute either.

```python
from arche.runtime import ResolutionBudget, ResolutionIntent, ResolutionMethod

case = ResolutionCase(
    "case_01",
    "Which supplier is this?",
    ("obs_01",),
    (),
    datetime.now(UTC),
    intent=ResolutionIntent(
        "organisation",
        "reconcile",
        ("name", "registration_id"),
        "supplier-policy-v1",
        candidate_pairs=250_000,
    ),
)
engine.store.write_resolution_cases([case])

selected_method = ResolutionMethod(
    "splink_supplier_v1",
    "splink",
    ("organisation",),
    ("reconcile",),
    "supplier-policy-v1",
    "sha256:caller-owned-splink-settings",
    required_fields=("name", "registration_id"),
    max_candidate_pairs=1_000_000,
    estimated_cost=0.05,
)
plan = engine.plan_case(
    case.case_id,
    capabilities=(registry_connector.capability,),
    budget=ResolutionBudget(max_actions=1, max_cost=0.25),
    methods=(selected_method,),
)
for action in plan.actions:
    print(action.gap_field, action.rationale, action.estimated_cost)
for method in plan.methods:
    print(method.resolver, method.configuration_pin, method.rationale)

plan_event = engine.record_case_plan(plan, recorded_at=datetime.now(UTC))
```

`ResolutionIntent` contains only the requested operation, entity type, available field names, candidate-pair scale, and a policy pin; it does not persist record values. A `ResolutionMethod` is caller-configured and has a configuration pin, so the planner can recommend a configured Splink, deterministic, domain, or other resolver without inventing settings or importing/running it. The assessment records why every method was eligible or excluded.

This is the baseline for an optional future LLM planner. Any such planner must choose from the same assessed gaps and permitted capabilities, meet the same budget, and produce a comparable plan before an application executes it. It cannot create a new action type, call an unapproved source, bypass observation and evidence records, or directly run a selected resolver.

This contract is the foundation for later `ResolutionCase` work: external tool output returns as an immutable observation, is evaluated by the normal evidence and policy pipeline, and never grants the tool direct authority to merge identities.

### Let an optional agent advise on an already-bounded plan

`AgentPlanAdvice` is the narrow agentic boundary. A caller-owned planner may interpret the case and recommend only action or method IDs already selected by a persisted deterministic `EvidencePlan`; `record_agent_plan_advice()` rejects invented tools, methods, or budgets. It records stable reason codes, uncertainty targets, and a SHA-256 reference to caller-managed free-form reasoning, but it cannot execute a connector or resolver, approve a method, or mutate entity memory.

### Gate optional Splink and domain methods on evaluated configurations

Set a non-core `ResolutionMethod.benchmark_id` and provide an exact passing `MethodBenchmarkQualification` to `plan_case()`. The qualification pins its method/resolver/configuration, benchmark and dataset identities, evaluator version, and hash-addressed result; it does not make an accuracy claim in runtime state. Without it, the method is ineligible. A changed settings pin or benchmark requires a new qualification before the planner can recommend the runner.

`SplinkResolutionMethodExecutor` and `DomainResolutionMethodExecutor` bind caller-owned runner functions to one resolver identifier and executor pin. They return the existing hash-only `ResolutionMethodExecution` contract, so the ordinary plan → approval → gateway Observation → reviewed Evidence → receipt → policy path remains mandatory.

### Approve and run a planned resolver method

Resolver selection and resolver execution are separate. `approve_planned_resolution_method` checks that a persisted plan selected the exact configured method and records the application or human approval plus its cost ceiling. `execute_approved_resolution_method` then invokes the caller-owned adapter once and records a success or failure Observation. It does not interpret the result, create Evidence, record a DecisionReceipt, or mutate entity memory.

```python
from arche.runtime import ResolutionMethodApproval, ResolutionMethodExecution

approval = ResolutionMethodApproval(
    "approval_01",
    case.case_id,
    plan_event.event_id,
    selected_method.method_id,
    selected_method.configuration_pin,
    "supplier-reviewer",
    max_cost=0.15,
)
engine.approve_planned_resolution_method(
    approval,
    selected_method,
    recorded_at=datetime.now(UTC),
)

class SupplierResolver:
    def execute(self, case, method):
        # The application owns inputs, the configured library, and raw output storage.
        return ResolutionMethodExecution(
            "execution_01",
            method.method_id,
            method.configuration_pin,
            "success",
            "sha256:result-artifact",
            actual_cost=0.12,
        )

result_observation = engine.execute_approved_resolution_method(
    case.case_id,
    approval.approval_id,
    selected_method,
    SupplierResolver(),
    recorded_at=datetime.now(UTC),
)
# Derive reviewed Evidence from result_observation before creating any receipt.
```

An executor exception, an explicit failure, or an actual cost above the approved ceiling becomes a failure Observation. A new approval is required to retry, preserving the complete chain of plan, approval, execution, evidence, inference, and policy.

### Review deterministic reconcile output before using it

`record_reviewed_reconcile_artifact` is the first bridge from a successful deterministic `arche.resolve.reconcile` gateway Observation to vNext Evidence and receipts. The caller retains the raw result artifact, reviews it, supplies one Evidence ID per emitted edge, and may add existing independent Evidence such as a registry or document field. Resolver-output Evidence is retained on the receipt for provenance but does not count as an independent real-world source for `ResolutionDecisionPolicy`.

```python
artifact_evidence, run, receipts = engine.record_reviewed_reconcile_artifact(
    case.case_id,
    result_observation.observation_id,
    reviewed_reconcile_result,
    review_id="review_reconcile_01",
    reviewed_at=datetime.now(UTC),
    run_id="run_reconcile_01",
    artifact_evidence_ids_by_decision={"xwd:edge_01": "ev_reconcile_edge_01"},
    supporting_evidence_ids_by_decision={
        "xwd:edge_01": ("ev_supplier_document", "ev_registry"),
    },
)
outcome = engine.apply_resolution_decision_policy(
    case.case_id,
    receipts[0].decision_id,
    policy=ResolutionDecisionPolicy("supplier-link-v1"),
    recorded_at=datetime.now(UTC),
)
```

The bridge rejects failed outputs, unrecorded artifacts, and incomplete edge review. `record_reviewed_resolution_artifact()` gives reviewed Splink and domain-matcher output the same path: the gateway Observation must have the matching resolver and pinned configuration; every edge becomes case-linked Evidence; then the ordinary receipt and `ResolutionDecisionPolicy` path applies. No library adapter writes a decision or ledger record directly.

PDFs, scans, and image-to-text input follow the same boundary. `DocumentIngestion` is the provider-neutral, value-free parser/OCR result; `ingest_document_observation()` requires a permitted `document_extract` or `document_ocr` action and stores only artifact/text hashes, parser/OCR pins, and page count. Reviewed fields/spans can then become Evidence and proposals. OCR output is not trusted matching input merely because it is text.

`DoclingDocumentIngestionExecutor` is the opt-in caller-owned bridge for `arche.doc.parse(...)`: it accepts a local path or other caller-managed source in `DocumentIngestionRequest`, discards the parsed text after hashing, and writes a success or failure Observation through the permitted case action. The runtime never persists the path, parser exception, or document text.

### Keep entity memory revisable

`Entity` is the stable identity; the ledger records the things currently
believed about it without treating them as permanent truth. `Claim` and
`EntityRelation` records cite durable Evidence IDs, `Contradiction` records
preserve incompatible claims, `OpenQuestion` preserves material unknowns, and
`CaseEvent` preserves the resolution history. `Claim.value_ref` is intended to
be a caller-managed digest or pointer, not a raw document, person, or health
record payload.

```python
memory = engine.get_entity_memory("ent_supplier_01")
for claim in memory.claims:
    print(claim.predicate, claim.status, claim.evidence_ids)

for conflict in memory.contradictions:
    print(conflict.reason, conflict.claim_ids)
```

The same contracts support a supplier and its corporate relationships, a
person and identity-document claims, or a school or health facility and its
location, licensing, and ownership claims. Documents enter through immutable
observations and extraction evidence before they can create or revise any
ledger entry.

### Pilot a tea supply chain without declaring it true

The [Unilever Global Tea Supply Chain report](https://www.unilever.com/files/950d107a-f912-4d1d-9e3f-9387288c3512/unilever-global-tea-supply-chain.pdf) is a useful pilot source because it reports suppliers and estates, but it must be treated as a dated, untrusted document observation. It is not proof that a supplier still operates an estate, owns it, or supplied a particular shipment. Download it only where its terms permit; the runtime stores neither the PDF nor its extracted text.

```python
from arche.doc import parse
from arche.runtime import observation_from_document

parsed = parse("unilever-global-tea-supply-chain.pdf")
document_observation = observation_from_document(
    parsed,
    observation_id="obs_tea_report_2020",
    source_id="unilever_tea_supply_chain",
    recorded_at=datetime.now(UTC),
)
engine.ingest_action_observation("act_document_extract", document_observation)
```

An extraction step may then issue Evidence such as “the document reports this supplier/estate label at this location in the text.” Only that evidence may support a revisable `reported_supplier_estate` claim or a `reported_operates` relation. A current registry, shipment record, certification, or field observation is separate evidence and may contradict it.

### Propose reviewed document beliefs before asserting them

`record_reviewed_document_proposals()` is the bridge from reviewed `FieldEvidence` to vNext. It records a document Observation, one Evidence item per field (including source, confidence, page, and span), and a `reviewed_document_proposals` case event. `DocumentClaimSpec` and `DocumentRelationSpec` make the semantic mapping explicit: Arche does not infer whether a label means a supplier, estate, owner, or recipient. Proposal values are SHA-256 references, not raw document values, and no `Claim` or `EntityRelation` enters memory until a later policy or human-review step accepts it.

```python
from arche.runtime import DocumentClaimSpec, DocumentRelationSpec

proposal_set = engine.record_reviewed_document_proposals(
    case.case_id, parsed, reviewed_extraction,
    observation_id="obs_tea_report_reviewed",
    source_id="unilever_tea_supply_chain",
    recorded_at=datetime.now(UTC),
    review_id="review:tea:2020:1",
    claim_specs=(DocumentClaimSpec("ent_supplier", "display_name", "supplier_name"),),
    relation_specs=(DocumentRelationSpec("ent_supplier", "sources_from", "ent_estate", ("supplier_name", "estate_name")),),
)

assert engine.get_entity_memory("ent_supplier").claims == ()
```

### Promote only independently supported proposals

`ProposalAcceptancePolicy` is the separate policy boundary that can promote a recorded proposal. Its default requires Evidence from two distinct Observation sources; several spans from one report still count as one source. An incompatible active claim or relationship returns `review` and records the conflicting ledger IDs in case history instead of creating a contested belief.

```python
from arche.runtime import ProposalAcceptancePolicy

outcome = engine.accept_claim_proposal(
    proposal_set.claims[0],
    policy=ProposalAcceptancePolicy("tea-evidence-v1"),
    recorded_at=datetime.now(UTC),
    supplemental_evidence_ids=("ev_current_supplier_registry",),
)

if outcome.decision == "accepted":
    print(outcome.accepted_record_id)
else:
    print(outcome.reason, outcome.conflicting_record_ids)
```

The policy accepts only a proposal already present in immutable case history and all cited Evidence must retain its Observation. A `review` outcome is intentionally re-evaluable when new independent evidence arrives; an accepted proposal cannot be accepted twice.

This import path currently uses Arche's default scorer. A Splink run keeps
candidate generation in its caller-owned `SettingsCreator` until the two paths
share an evaluated candidate contract.

Three answers, not two: `same_entity`, `review`, `different`. The middle one is the point. It is Fellegi and Sunter's third region from 1969, which most production systems discard because a review queue costs money, and discarding it is where systems start asserting things they have not earned.

## From documents to decisions

Unstructured input is a first-class entry point, not a preprocessing step you bolt on.

```python
from arche import resolve_documents

candidates = [{"entity_id": "ent_supplier_17", "name": "Kijani Tea Exporters Limited"}]
report = resolve_documents("shipments/*.pdf", entity="organisation", candidates=candidates)
print(report.review())
```

That parses each file, detects the identifying data with the governing statute attached, builds a record per document, and compares it against the explicit caller-owned candidate set. Labelled commercial fields such as supplier, distributor, estate, and registration ID are proposed with spans for review; they are not claims or accepted Evidence. Candidate results are proposals. If no candidate is safe to link, `review()` returns a value-masked `ResolutionCase` with already-permitted evidence actions; the caller must review fields before they can become vNext Evidence. `max_candidate_pairs` defaults to 1,000, so callers narrow candidates rather than accidentally comparing every document against a full master table.

Persist only an unresolved case, and only into a caller-owned runtime:

```python
from arche import attach

engine = attach("duckdb:///tea-cases.duckdb")
saved = report.persist(engine)
```

`persist()` writes the hash/provenance-only document Observation, `ResolutionCase`, and already-permitted actions; it writes no document values, Evidence, receipt, claim, relationship, or entity decision. Repeating it against the same store is safe. Continue only through an approved document-ingestion or evidence-connector action.

For a persisted `registry_lookup` action, a caller can supply a policy-pinned HTTPS registry or supplier-master request without putting its query values into DuckDB or the emitted artifact:

```json
{
  "source_id": "external_registry",
  "policy_pin": "document-resolution-v1",
  "base_url": "https://supplier-master.example",
  "request": {"path": "/v1/suppliers", "query": {"registration_id": "caller-value"}},
  "estimated_cost": 0.25,
  "max_requests": 2,
  "window_seconds": 60,
  "timeout_seconds": 5
}
```

```text
arche case registry-lookup CASE_ID ACTION_ID --connector registry.json --store tea-cases.duckdb --out registry-observation.json
```

The source, action type, and policy pin must match the already-persisted action; the runtime rejects a mismatch before a request. The connector permits read-only HTTPS GET requests only, enforces its cost and rate limits, and turns either a response or a refusal/failure into one immutable Observation. The output retains a hash of the configuration, not its request values or response body.

`extraction_backend="regex"` is the deterministic, air-gapped choice; omit it to retain the model-assisted default.

## Decisions you can hand to someone who does not trust you

Every decision has a reproducible `decision_id`, hashed over the rounded evidence and the pinned versions. No timestamp, no raw float. Same inputs, same id, byte for byte.

```python
from arche.resolve.reconcile import sign_edges
from arche.sign import generate_keypair

signed = sign_edges(result, private_key=key.private_key, kid=key.did_key)
```

A recipient checks two independent things: the signature, which establishes who issued it and that nothing changed since, and the recomputed id, which establishes that the id is the honest address of *this* evidence rather than one lifted from a more favourable decision. They fail differently, which is what makes the pair useful. See [re-verify a decision](https://unpatterned-labs.github.io/arche/how-to/re-verify-a-decision/).

## What is measured

Published whichever way it falls, with the caveats attached rather than in a footnote.

| What | Baseline | arche | Read it as |
|---|---|---|---|
| **Leipzig DBLP–ACM** | out of the box, precision 0.8500, 391 false merges | precision **0.9506**, recall 0.9960 | Complete ground truth, so false merges are counted rather than estimated. The gain is not default: it needs one declared discriminator on `year` |
| **Leipzig Abt-Buy** (products) | name only, F1 0.3443 | F1 **0.7883**, precision 0.9707 | 62 false merges down to 22 |
| **Organisation lane** | token-sort F1 0.8898 | F1 **0.9493** | False merges 21 → 4. Anglophone restaurant listings, so it says nothing about African organisation names |
| **Name frequency** *(ablation)* | the same engine with the frequency signal off: precision 0.162, 7,705 false merges | precision **0.946**, 41 false merges | 1,114 real same-surname pairs from a public voter register. Recall is the cost: **48%** on same-person pairs differing by a dropped middle name |
| **Multilingual detection** | Presidio 37/48 | **47/48** | **Not re-runnable.** The 48-case set is not in this repo and nothing here computes the number. Unverified until rebuilt |

The honest ledger, in full, is in [the whole picture](https://unpatterned-labs.github.io/arche/about/the-whole-picture/), including the benchmarks that are too small, the abstention policy that is not yet precommitted, and the head-to-head against frontier models that has not been run.

For a local OpenSanctions Pairs smoke evaluation, download the CC-BY-NC-4.0 dataset under its terms and run `uv run python data/scripts/benchmark_opensanctions_pairs.py --input path/to/sample_1000.json`. The script reports only the supported person/person and organisation/organisation pairs, and reports structural or mixed-schema pairs as skipped; it does not turn an evaluation result into a runtime pack or an operational sanctions-screening policy.

## Why the calibration comes from where it does

The engine is general. The organisation frequency table is built from company registrations across 65 jurisdictions, the product work is benchmarked on US retail catalogues, and the place work runs on UK hospitals and Nigerian clinics alike.

### CLI discovery and releases

`arche` is intended to be usable without memorising a hidden command tree:

```text
arche version             # the installed arche-core version
arche list                # compare, review, schema, datasets, and version
arche datasets            # truth coverage before choosing a benchmark
arche datasets --json     # the same catalog for an application or agent
arche review template PACK outcomes.csv  # value-free IDs for human adjudication
arche resolve-documents tea-shipment.pdf --entity organisation --candidates suppliers.json --store tea-cases.duckdb --out tea-review.json
arche case open document.pdf --store arche.duckdb
arche case plan CASE_ID --enable-local-document
arche case ingest CASE_ID ACTION_ID document.pdf --approved-by reviewer-1
arche case evidence CASE_ID ACTION_ID reviewed-fields.json --review-id review-1
arche case registry-lookup CASE_ID ACTION_ID --connector registry.json --store tea-cases.duckdb
arche case review CASE_ID --out case-review.json
```

`arche datasets` never reads record values. It distinguishes complete mappings (which can measure false merges and support an evaluated-method qualification) from unlabelled review packs (which can support adjudication but cannot qualify a method). `arche review template` writes only decision IDs and empty review fields, so the reviewer can supply the outcome separately from record values.

`arche resolve-documents` is the shortest document front door: it emits a masked proposed-field/candidate review artifact and opens an unresolved case when it cannot safely link a supplied candidate. Add `--store` to persist only the value-free Observation, case, and permitted actions to a caller-owned DuckDB file; it never writes a link, claim, or entity-memory record. `arche case registry-lookup` consumes one of those persisted `registry_lookup` actions only through a caller-owned configuration whose declared source and policy pin match the action; its response or failure is an Observation. `arche case open` records only a document hash, filename hash, and a permitted extraction or OCR action. `arche case plan` records deterministic, budgeted advice and requires an explicit declaration that the caller-owned local document capability is available; it does not parse a document, invoke a resolver, or mutate entity state. `arche case ingest` requires a selected planned action and an explicit human/application approval before invoking the caller-owned Docling/OCR executor; parser output becomes an immutable Observation. `arche case evidence` accepts caller-owned reviewed field values transiently and records only value-free Evidence provenance, confidence, pages, and spans. `arche case review` writes case history, action-result Observations, and reviewed Evidence for a future review pane or another application. The release version is single-sourced in `src/arche/_version.py`; Hatch reads that value into wheel metadata, so a release bump changes one file and must be made only as part of a release commit.

What is unusual is where the defaults were tested first. Jaro-Winkler, the string comparator underneath most record linkage, pays a bonus for a shared prefix, because it was tuned on US Census surnames where clerical typos land at the end of a word. *Diallo* and *Jallow* are one Fula family name split by a colonial spelling border, and they share no prefix at all. That assumption fails identically on Arabic transliteration, on Cantonese romanisation, and on any register where one name has three spellings.

So: **general-purpose entity resolution that ships its representation data, built by people who met the defaults first where the defaults break hardest.** Six statute packs ship, covering NDPA (Nigeria), POPIA (South Africa), Kenya DPA, Ghana DPA, GDPR and HIPAA Safe Harbor, alongside a baseline floor that applies where no pack exists.

## Install

```bash
pip install arche-core                   # ~3 MB, CPU only, no ML dependencies
pip install "arche-core[doc]"            # PDF, DOCX, PPTX, XLSX, HTML
pip install "arche-core[detect]"         # GLiNER2-PII soft-PII detection
pip install "arche-core[presidio]"       # Microsoft Presidio integration
pip install "arche-core[resolve]"        # Splink + DuckDB at scale
```

Runs offline by default. Nothing leaves the machine unless you configure a backend that does, and an `EgressGuard` has to be cleared before it can.

> [!WARNING]
> `arche-core` is pre-beta. Suitable for research, prototyping, evaluation, benchmarking and contribution. APIs may change between alpha releases. Do not use it against real personal data until you have completed your own legal, privacy and security review.

## If your problem is inference, use Splink

We mean this literally. Entity resolution has two halves. The mathematics of combining evidence is solved, has a founding paper from 1969, and has excellent free software in [Splink](https://moj-analytical-services.github.io/splink/). arche is about the other half: what the records look like when they are compared, what counts as agreement, and what agreement is worth. Every gain claimed here is a gain in representation, and none of it is a better estimator.

## Source and issues

[github.com/unpatterned-labs/arche](https://github.com/unpatterned-labs/arche)

## Look at a decision

[`arche studio`](https://github.com/unpatterned-labs/arche/tree/main/tools/arche-studio) is a local reading tool. Three files, the standard library, no
framework and no install beyond `arche-core` itself.

```bash
python tools/arche-studio/serve.py     # opens http://127.0.0.1:8765
```

Five modes over one evidence panel:

| | |
|---|---|
| **Compare** | two ad-hoc records, the decision, and a plain sentence saying why it held back |
| **Spatial roles** | paste text or drop a document; origins, destinations and waypoints marked with the cue that decided each |
| **Redact** | run a record through a statute pack and see the action, the cited section, and what was written instead |
| **Verify** | check a signed decision two ways: the signature, and whether its id recomputes from its own evidence |
| **Review queue** | a dense grid over an adjudication pack, sortable and searchable, marking outcomes to a labelled copy |

It is alpha, says so on the page, binds to `127.0.0.1`, and has no
authentication. It is a tool for reading our own queues, not a product.

## Documentation

| | |
|---|---|
| [The whole picture](https://unpatterned-labs.github.io/arche/about/the-whole-picture/) | what is built, what is measured, what is not proven |
| [Quickstart](https://unpatterned-labs.github.io/arche/getting-started/quickstart/) | install, then a first result |
| [How it works](https://unpatterned-labs.github.io/arche/tutorials/how-it-works/) | the pipeline, the comparators, and how a decision is reached |
| [What matching looks like](https://unpatterned-labs.github.io/arche/tutorials/what-matching-looks-like/) | the failure modes side by side, with real verdicts |
| [Re-verify a decision](https://unpatterned-labs.github.io/arche/how-to/re-verify-a-decision/) | check a signed decision you did not issue |
| [Runnable notebooks](https://github.com/unpatterned-labs/arche/tree/main/examples/notebooks) | 14, from first call to crosswalking a national register |

## Contributing

The representation data is open on purpose. A pack that everyone corrects is a better pack, and the corrections are the point. If you know an equivalence, a vocabulary or a frequency we do not, that is the highest-value contribution there is. See [CONTRIBUTING.md](https://github.com/unpatterned-labs/arche/blob/main/CONTRIBUTING.md).

## License

Apache-2.0. The datasets carry their own licences, recorded beside them.
