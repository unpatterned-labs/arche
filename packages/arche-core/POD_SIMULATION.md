# Two-Pod consent simulation and the entity-intelligence path

This offline experiment connects an actual Arche `ResolutionCase` plan to a local consent exchange. The requester is an Arche runtime backed by DuckDB; the responder is an ephemeral `SimulatedPod`. No SOLID server, personal records, credential issuer, network request, matching protocol, or identity proof is involved.

## Run the two stages

From the repository root, in the configured development environment:

```powershell
uv run --no-sync python examples/two_pod_review.py
uv run --no-sync python examples/two_pod_review.py --consent
```

The first command prints the supplier-resolution question, the reason for requesting an external review, its simulated cost, and `awaiting_both_parties_consent`. Only a plan is recorded. The second command explicitly simulates both owners' approvals, exchanges consent metadata and records `consented` as an immutable Observation. The output says `identity_evidence: false` and asks for separately approved, reviewed source evidence. It does not claim the supplier has been resolved.

The example uses an in-memory requester store and synthetic identifiers; nothing is uploaded or retained after it exits. Real documents in `data/docs` are not needed for testing this permission boundary.

The Python sequence is:

```python
from arche.runtime.pod_simulation import approve_pod_review, execute_pod_review
request = approve_pod_review(engine, action_id, plan_event_id, pod, approved_at=now, expires_at=expiry)
grant = pod.grant(request, now=now, expires_at=expiry)  # responder owner's explicit consent
observation = execute_pod_review(engine, action_id, request, pod, grant, now=now)
```

Here `engine`, the permitted action and the recorded plan are caller-owned. `pod` is a `SimulatedPod` for one peer session. The action must be `pod_review_request`, have zero simulated cost, and match the case intent's policy. Approval fails unless the selected action occurs in the persisted plan. Both approval and grant have explicit timezone-aware windows. A new request/action is necessary after any execution attempt; there is no automatic retry.

## What is disclosed

| Surface | Allowed metadata | Intentionally absent |
|---|---|---|
| Request body | Fresh random request ID, random peer-session audience, fixed purpose, fixed disclosure scope | Case question/ID, local policy/source/action IDs, names, NINs, fields, document hashes, candidates, scores |
| Transient grant | Random handle known to the responder and requester | Credentials, stable person IDs, ledger retention |
| Response body | Request ID and `consented` or `denied` | Person existence, match outcome, record counts, denial details, arbitrary metadata |
| Local ledger | Local action/plan references, approval window, request/response hashes, attempt and Observation records | Grant handle, wire request ID, peer-session audience, raw response or exception text |

Consent therefore reveals willingness to arrange review. An observer could still learn that a session happened, its purpose, timing, message size and response status. Peers can correlate messages within a session through its audience/request IDs. Fresh sessions receive new aliases. Tests assert schema and value exclusions; they do not prove anonymity, constant-time behaviour or resistance to traffic analysis. Hashes and random aliases are not a claim of legal anonymisation.

The responder stores grants and revocations in memory and checks the exact request, audience, expiry and use status. All denied grants have the same response shape for a given request. The requester writes an attempt before exchange, so a restarted requester cannot silently replay a possibly completed action. Callers must serialize execution; distributed concurrency, durable responder consent, identity authentication and revocation across devices are outside this simulation.

## Verify the boundary

```powershell
uv run --no-sync pytest packages/arche-core/tests/test_pod_simulation.py -q
uv run --no-sync pytest packages/arche-core/tests/test_runtime.py packages/arche-core/tests/test_solid_export.py packages/arche-core/tests/test_report_cli.py -q
```

The tests cover planning without execution, no capable action, missing or altered local approval, expired approval, wrong audience, missing/revoked/expired/replayed remote grants, future consent, exact wire fields, raw-value exclusions, invalid responses, exception redaction, durable attempt recovery and prevention of treating consent as independent identity corroboration. The runtime also excludes simulated consent sources when counting support for claim/relation promotion.

The existing full suite has a previously observed memory/progress stall. Focused test success is not a full-suite pass. Retain logs and enforce a memory/time ceiling when running the release suite; resolve that operational issue before declaring the package release-ready.

## Where the agentic behaviour stands

| Stage | Current implementation | Remaining product work |
|---|---|---|
| Understand the task | `ResolutionIntent` describes entity type, operation and available fields; the planner assesses explicit gaps | Interpret a user's free-form task into reviewable intent/gaps, with ambiguity surfaced |
| Reason about methods/actions | Deterministic eligibility, policy/configuration pins, declared evidence gaps, budget and rationale | Evaluate action value and actual uncertainty reduction on held-out cases |
| Recommend an external tool | Plan lists the permitted action, reason and cost; the demo exposes the consent requirement | A unified CLI/notebook review interaction for real connector permissions |
| Execute | Existing approved executors and read-only connectors; this simulation adds exact bilateral consent checks | Integrate a concrete supplier-master provider and its caller-managed credentials |
| Learn from the result | Tool output becomes an Observation; reviewed Evidence flows to inference and policy | One bounded controller that re-assesses after evidence, tracks remaining budget and stops on review/abstention/resolution |
| Optional agent | `AgentPlanAdvice` can recommend items within an existing persisted plan | Evaluate an actual model-backed intent/advice adapter, including wrong-tool and missing-match cases |

This is an entity-resolution runtime with an emerging agentic control loop. There is no evaluated autonomous agent or automatic semantic understanding of every document yet. The present example tests requesting permission; it intentionally stops before evidence acquisition or a new identity conclusion.

The earlier `SolidPodClient.publish()` remains a lower-level application adapter: it validates the supplied approval's identifiers, policy and expiry, but does not itself verify that the approval was persisted, bind an approved destination, or reject repeat transport calls. Its separate history helper detects duplicate recorded outcomes only after a call. Those requirements must be integrated before live publication is presented as enforced by the ledger. The new simulation checks its own persisted approval before any exchange and does not invoke that publisher.

## Keep the next milestone tied to customer value

Use supplier onboarding/reconciliation as the working PoC: document → proposed fields → explicit supplier candidates → uncertain case → permission → real supplier-master evidence → reviewed Evidence → re-resolution → policy → operator review. Hold out ambiguous names, missing registrations, contradictory IDs and a genuine no-match supplier. Acceptance should require the correct next step and defensible outcome for each scenario, including honest abstention.

Keep distinct labels for distinct questions. Same legal supplier, same trading brand and same estate are different identity units. Same sellable product, similar substitute and membership of a product family need separate labels and metrics. Food traceability additionally needs time- and batch-specific relationship evidence; entity matching alone cannot prove a chain of custody.

For matching quality, use complete mappings such as local Abt-Buy or DBLP-ACM. Compare pinned Arche, Splink and RecordLinkage configurations on identical inputs, truth, candidate budgets and declared tuning splits. Record automatic precision/false merges, automatic recall, surfaced recall, true blocking recall, review workload, elapsed time and memory. The current vNext benchmark script derives `blocking_true_pair_count` from surfaced output edges; this cannot establish pre-threshold blocking recall and needs an evaluator correction before that metric is reported as such. A missing result bundle is an incomplete run, not a quality result.

For product value, measure time to first useful result against the five-line/two-minute target in a configured environment, minutes of reviewer work per case, provenance completeness and improvement after one evidence action. Source reviews from `data/docs` and facility/person review packs support workflow evaluation; unlabelled rows do not become negative ground truth.

A PoC demonstrates this loop on controlled scenarios. An MVP additionally requires a representative, independently adjudicated customer set, agreed error/review/cost limits, reliable cold start and execution, failure recovery and repeatable regression tests. Prioritize this evidence-to-decision loop before expanding Pod features or cryptographic protocols.
