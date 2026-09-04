# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0
"""Build 23_agentic_tea_resolution_case.ipynb.

uv run python examples/notebooks/build_23_agentic_tea_resolution_case.py
"""

from __future__ import annotations

import json
from pathlib import Path

MD, CODE = "markdown", "code"
cells: list[tuple[str, str]] = []


def md(text: str) -> None:
    """Append a Markdown cell."""
    cells.append((MD, text.strip("\n")))


def code(text: str) -> None:
    """Append a code cell."""
    cells.append((CODE, text.strip("\n")))


md("""
# An agentic tea-supply-chain resolution case

**Messy evidence in. A reviewable, policy-controlled entity conclusion out.**

This is an end-to-end vNext walkthrough of one supplier-resolution case. It uses fictional identifiers and SHA-256 references, not a supplier's actual name, document text, registration number, or a real matching score. That is intentional: the runtime needs provenance to reason safely without becoming a store of sensitive documents.

The scenario is tea supply-chain due diligence. A scanned supplier document points to an organisation; a registry result independently corroborates a legal identifier; a caller-owned Splink run proposes a link. Arche makes each step explicit and leaves the final real-world action to the application or a human workflow.
""")

md("""
## 1. The contract before the tools

The important ordering is:

```text
document / scan / OCR -> immutable Observation -> reviewed Evidence
                                                       |
case question -> planner -> explicit approval -> resolver gateway Observation
                                                       |
reviewed resolver artifact -> DecisionReceipt -> policy -> application action
```

The planner may choose a permitted method, but cannot execute it. A resolver may produce an artifact, but cannot write a receipt or ledger record. OCR text is an observation, not ground truth.
""")

code("""
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path

import arche
from arche.runtime import (
    AgentPlanAdvice,
    DocumentIngestion,
    Evidence,
    EvidenceAction,
    EvidenceGap,
    MethodBenchmarkQualification,
    Observation,
    PolicyExecution,
    ResolutionBudget,
    ResolutionCase,
    ResolutionDecisionPolicy,
    ResolutionIntent,
    ResolutionMethod,
    ResolutionMethodApproval,
    ResolutionMethodExecution,
    ReviewedResolutionArtifact,
    ReviewedResolutionEdge,
    ToolCapability,
    observation_from_document_ingestion,
)


def digest(value: str | bytes) -> str:
    payload = value.encode("utf-8") if isinstance(value, str) else value
    return f"sha256:{sha256(payload).hexdigest()}"


recorded_at = datetime(2026, 9, 3, 14, 0, tzinfo=UTC)
engine = arche.attach("duckdb:///:memory:")
print(type(engine.store).__name__, "ready")
""")

md("""
## 2. A document is evidence about what it reported

The repository includes PDFs under `data/doc_bench`; in a production ingestion, a parser and optional OCR provider would create the provenance below from the source bytes and rendering. `DocumentIngestion` is that provider-neutral hand-off. This notebook hashes an available local PDF but deliberately does **not** extract or retain its contents. That keeps the example runnable and makes the data boundary visible.
""")

code("""
pdf_path = Path("data/doc_bench/invoice_6_ak.pdf")
pdf_bytes = pdf_path.read_bytes() if pdf_path.exists() else b"fictional scanned tea supplier document"
artifact_sha256 = digest(pdf_bytes).removeprefix("sha256:")

document_ingestion = DocumentIngestion(
    source_record_id=f"artifact:sha256:{artifact_sha256}",
    artifact_sha256=artifact_sha256,
    text_sha256=digest("caller-managed OCR text is not stored here").removeprefix("sha256:"),
    parser="caller-managed-pdf-parser",
    parser_version="pinned-by-application",
    ocr=None,  # the provider records true/false once it has parsed the scan
)
document_observation = observation_from_document_ingestion(
    document_ingestion,
    observation_id="obs_tea_document",
    source_id="document:tea_supplier_submission",
    recorded_at=recorded_at,
)
print("document bytes hashed:", len(pdf_bytes), "source values stored:", False)
print("parser/OCR pins:", document_observation.provenance["document"])
""")

md("""
## 3. Open an uncertain case, not an entity

The question contains the operational goal, while `ResolutionIntent` contains only the values the planner needs to reason about method eligibility: entity type, operation, available field names, expected candidate-pair scale, and policy pin. It does not contain the actual supplier values.
""")

code("""
intent = ResolutionIntent(
    "organisation",
    "reconcile",
    ("name", "registration_id", "country"),
    "tea-supplier-policy-v1",
    candidate_pairs=250_000,
)
case = ResolutionCase(
    "case_tea_supplier_001",
    "Which legal entity is reported by this tea supplier submission?",
    (document_observation.observation_id,),
    (),
    recorded_at,
    uncertainty={"reason": "document label and registry identifier have not been reconciled"},
    evidence_gaps=(
        EvidenceGap(
            "registration_id",
            "independently confirms the supplier proposed by the document",
            permitted_action_types=("registry_lookup",),
        ),
    ),
    intent=intent,
)
registry_action = EvidenceAction(
    "act_tea_registry_001",
    case.case_id,
    "registry_lookup",
    "supplier_registry",
    recorded_at,
    "tea-supplier-policy-v1",
    max_cost=0.05,
)
engine.store.write_observations([document_observation])
engine.store.write_resolution_cases([case])
engine.store.write_evidence_actions([registry_action])
print(case.question)
""")

md("""
## 4. Let the planner explain its choice

Two methods are offered. The deterministic method is deliberately ineligible because its approved scale limit is too small. The Splink method declares an evaluated review-pack requirement, so the plan can select it only after an exact qualified evaluation is supplied. The plan still cannot execute either tool. An optional caller-owned agent can then advise over this bounded plan; its free-form reasoning is retained outside Arche as a hash reference.
""")

code("""
methods = (
    ResolutionMethod(
        "arche_small",
        "arche.resolve.reconcile",
        ("organisation",),
        ("reconcile",),
        "tea-supplier-policy-v1",
        "arche.resolve.reconcile@crosswalk.v1",
        required_fields=("name",),
        max_candidate_pairs=100_000,
        estimated_cost=0.02,
    ),
    ResolutionMethod(
        "splink_tea_supplier",
        "splink",
        ("organisation",),
        ("reconcile",),
        "tea-supplier-policy-v1",
        "splink-settings@sha256:tea-v1",
        required_fields=("name", "registration_id"),
        estimated_cost=0.15,
        priority=1,
        benchmark_id="tea-supplier-review-pack-v1",
    ),
)
splink_qualification = MethodBenchmarkQualification(
    "qualification_tea_splink_001",
    "splink_tea_supplier",
    "splink",
    "splink-settings@sha256:tea-v1",
    "tea-supplier-review-pack-v1",
    "tea-supplier-review-pack",
    "benchmark-runner@v1",
    digest("caller-managed complete benchmark result"),
    qualified=True,
)
plan = engine.plan_case(
    case.case_id,
    capabilities=(
        ToolCapability("supplier_registry", ("registry_lookup",), "tea-supplier-policy-v1"),
    ),
    budget=ResolutionBudget(max_actions=1, max_cost=0.25),
    methods=methods,
    benchmark_qualifications=(splink_qualification,),
)
plan_event = engine.record_case_plan(plan, recorded_at=recorded_at)
agent_advice = AgentPlanAdvice(
    "advice_tea_supplier_001",
    case.case_id,
    plan_event.event_id,
    "caller-owned-planner",
    "proceed",
    recommended_action_ids=(registry_action.action_id,),
    recommended_method_ids=("splink_tea_supplier",),
    uncertainty_targets=("registration_id",),
    reason_codes=("independent_identifier_needed", "configured_method_eligible"),
    reasoning_hash=digest("caller-managed agent reasoning"),
)
advice_event = engine.record_agent_plan_advice(agent_advice, recorded_at=recorded_at)

for assessment in plan.assessment.method_assessments:
    print(f"{assessment.method_id:<22} eligible={assessment.eligible:<5} {assessment.reason}")
print("planned methods:", [method.method_id for method in plan.methods])
print("benchmark qualification:", plan.methods[0].benchmark_qualification_id)
print("agent advice:", advice_event.provenance["recommendation"], advice_event.provenance["reason_codes"])
""")

md("""
## 5. Evidence acquisition remains an Observation

Here an application has already performed the permitted registry lookup and returns only a hash-addressed result. A real connector can hold request values privately; Arche records the resulting Observation and later Evidence, not a mutable lookup row.
""")

code("""
registry_observation = Observation(
    "obs_tea_registry",
    "supplier_registry",
    "registry-result:caller-managed",
    recorded_at,
    digest("registry result bytes"),
    provenance={"kind": "evidence_action", "result": "reviewed externally"},
)
engine.ingest_action_observation(registry_action.action_id, registry_observation)

supporting_evidence = (
    Evidence("ev_tea_document_field", document_observation.observation_id, "reviewed_document_field", "supports"),
    Evidence("ev_tea_registry_id", registry_observation.observation_id, "registry_identifier", "supports"),
)
engine.store.write_evidence(supporting_evidence)
print("independent sources:", [document_observation.source_id, registry_observation.source_id])
""")

md("""
## 6. Approval and execution are separate from planning

The application or a named human approves the exact planned method and its configuration pin. The fake executor below stands in for caller-owned Splink code: Arche receives only an execution id, configuration pin, cost, and artifact hash.
""")

code("""
selected_method = plan.methods[0]
approval = ResolutionMethodApproval(
    "approval_tea_splink_001",
    case.case_id,
    plan_event.event_id,
    selected_method.method_id,
    selected_method.configuration_pin,
    "tea-resolution-reviewer",
    max_cost=0.15,
)
engine.approve_planned_resolution_method(approval, selected_method, recorded_at=recorded_at)


class CallerOwnedSplinkExecutor:
    def execute(self, requested_case, requested_method):
        assert requested_case.case_id == case.case_id
        return ResolutionMethodExecution(
            "exec_tea_splink_001",
            requested_method.method_id,
            requested_method.configuration_pin,
            "success",
            digest("caller-managed reviewed Splink artifact"),
            actual_cost=0.14,
        )


resolver_observation = engine.execute_approved_resolution_method(
    case.case_id,
    approval.approval_id,
    selected_method,
    CallerOwnedSplinkExecutor(),
    recorded_at=recorded_at,
)
print(resolver_observation.source_id, resolver_observation.provenance["outcome"])
""")

md("""
## 7. Review the resolver artifact before creating a receipt

Scores from Splink, a domain matcher, and deterministic Arche are not portable thresholds. A reviewer normalizes each proposed edge into the vNext outcome vocabulary. The adapter retains the original score/probability for provenance but never interprets it as policy.
""")

code("""
reviewed_artifact = ReviewedResolutionArtifact(
    "splink",
    "splink-settings@sha256:tea-v1",
    candidate_pairs=250_000,
    edges=(
        ReviewedResolutionEdge(
            "splink:tea-supplier-edge-001",
            "same_entity",
            "link",
            probability=0.98,
        ),
    ),
)
artifact_evidence, run, receipts = engine.record_reviewed_resolution_artifact(
    case.case_id,
    resolver_observation.observation_id,
    reviewed_artifact,
    review_id="review_tea_splink_001",
    reviewed_at=recorded_at,
    run_id="run_tea_splink_001",
    artifact_evidence_ids_by_decision={"splink:tea-supplier-edge-001": "ev_tea_splink_edge"},
    supporting_evidence_ids_by_decision={
        "splink:tea-supplier-edge-001": tuple(item.evidence_id for item in supporting_evidence),
    },
)
receipt = receipts[0]
print("run candidates:", run.candidate_pairs)
print("receipt evidence:", receipt.evidence_ids)
""")

md("""
## 8. Policy, then a caller-controlled action

The default decision policy needs two independent real-world sources for a `link`. The resolver artifact itself remains in the receipt for auditability but does not count as independent corroboration. Only after policy release does a caller-owned executor receive the action.
""")

code("""
decision = engine.apply_resolution_decision_policy(
    case.case_id,
    receipt.decision_id,
    policy=ResolutionDecisionPolicy("tea-supplier-link-v1"),
    recorded_at=recorded_at,
)


class ApplicationLinkExecutor:
    def execute(self, released_decision):
        return PolicyExecution(
            "policy_exec_tea_001",
            released_decision.decision_id,
            released_decision.case_id,
            released_decision.policy_id,
            released_decision.action,
            "tea-due-diligence-application",
            "applied",
            digest("application-side link result"),
        )


execution = engine.execute_released_policy_decision(
    decision,
    ApplicationLinkExecutor(),
    recorded_at=recorded_at,
)
print("policy:", decision.action, decision.reason)
print("independent sources:", decision.independent_source_ids)
print("application execution:", execution.outcome)
""")

md("""
## 9. Inspect the durable case history

The outcome is explainable without retaining raw supplier data. The history contains the plan, explicit approval, gateway execution, reviewed evidence, receipt, policy decision, and application result. Entity-memory claims or relationships remain a separate later promotion step, with their own evidence and contradiction policy.
""")

code("""
for event in engine.get_case_history(case.case_id):
    print(f"{event.event_type:<28} refs={len(event.references)}  provenance={sorted(event.provenance)}")

print("\\nNo entity claim was created by the resolver or policy:")
print("  resolver output -> Evidence -> receipt -> policy -> application outcome")
engine.store.close()
""")

md("""
## 10. Where this becomes genuinely agentic

The next controlled extension is an optional planner that can reason over the same structured case assessment: it can choose among permitted deterministic, Splink, domain, document-extraction, or external-evidence actions and explain why the expected uncertainty reduction justifies the cost. It must still output a proposed plan, never call a tool or mutate identity directly.

For unstructured inputs, add OCR/parser adapters as optional, benchmark-gated integrations. Each should emit a provenance-pinned document Observation (artifact hash, text hash, parser and OCR versions, page/span references), then require reviewed field Evidence before matching or proposing supplier/estate relationships. This keeps a misread scan visible as uncertain evidence rather than silently converting it into a false merge.
""")

nb = {
    "cells": [
        {
            "id": f"vnext-{index:02d}",
            "cell_type": cell_type,
            "metadata": {},
            "source": (source + "\n").splitlines(True),
            **({"execution_count": None, "outputs": []} if cell_type == CODE else {}),
        }
        for index, (cell_type, source) in enumerate(cells, start=1)
    ],
    "metadata": {
        "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
        "language_info": {"name": "python"},
    },
    "nbformat": 4,
    "nbformat_minor": 5,
}

out = Path(__file__).with_name("23_agentic_tea_resolution_case.ipynb")
out.write_text(json.dumps(nb, indent=1), encoding="utf-8")
print(f"wrote {out.name}: {len(cells)} cells")
