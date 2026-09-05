# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Run a synthetic supplier review handshake locally, with explicit consent.

    uv run --no-sync python examples/two_pod_review.py
    uv run --no-sync python examples/two_pod_review.py --consent

This exercises the actual planner and durable Observation boundary. The two
parties are a requester runtime and an in-memory responder, not live SOLID Pods.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import UTC, datetime, timedelta

from arche.runtime import (
    EvidenceAction,
    EvidenceGap,
    Observation,
    ResolutionBudget,
    ResolutionCase,
    ResolutionIntent,
    ToolCapability,
    attach,
)
from arche.runtime.pod_simulation import (
    SimulatedPod,
    approve_pod_review,
    execute_pod_review,
)


def run_demo(*, consent: bool = False) -> dict[str, object]:
    """Return a synthetic plan/review summary; consent opts into the local exchange."""
    now = datetime.now(UTC)
    engine = attach("duckdb:///:memory:")
    try:
        case = ResolutionCase(
            "case_demo", "Which registered supplier does this document describe?",
            ("obs_document",), (), now,
            evidence_gaps=(EvidenceGap(
                "independent_supplier_evidence",
                "Document fields alone do not establish the supplier's registered identity. "
                "Ask a second data holder whether a review can be arranged.",
                permitted_action_types=("pod_review_request",),
            ),),
            intent=ResolutionIntent("organisation", "reconcile", ("name",), "demo-policy"),
        )
        action = EvidenceAction(
            "act_pod_review", case.case_id, "pod_review_request", "supplier-master",
            now, "demo-policy", max_cost=0,
        )
        engine.store.write_observations([
            Observation("obs_document", "local-document", None, now, "sha256:synthetic")
        ])
        engine.store.write_resolution_cases([case])
        engine.store.write_evidence_actions([action])
        plan = engine.plan_case(
            case.case_id,
            capabilities=(
                ToolCapability(action.source_id, (action.action_type,), action.policy_pin),
            ),
            budget=ResolutionBudget(1, 0),
        )
        event = engine.record_case_plan(plan, recorded_at=now)
        summary = {
            "simulation": True,
            "question": case.question,
            "reason_for_external_action": plan.actions[0].rationale,
            "estimated_cost": plan.total_estimated_cost,
            "status": "awaiting_both_parties_consent",
            "next_step": "Review the plan, then rerun with --consent to simulate both approvals.",
        }
        if consent:
            pod = SimulatedPod()
            expires = now + timedelta(minutes=5)
            request = approve_pod_review(
                engine, action.action_id, event.event_id, pod,
                approved_at=now, expires_at=expires,
            )
            grant = pod.grant(request, now=now, expires_at=expires)
            result = execute_pod_review(engine, action.action_id, request, pod, grant, now=now)
            summary.update({
                "status": result.provenance["outcome"],
                "next_step": "Obtain separately approved source evidence, review it, then "
                "re-run inference and policy. Consent has not resolved this supplier.",
                "observation_recorded": engine.store.get_observation(result.observation_id)
                is not None,
                "identity_evidence": False,
                "wire_field_names": sorted(json.loads(request.to_bytes())),
            })
        summary["history_event_counts"] = dict(Counter(
            item.event_type for item in engine.get_case_history(case.case_id)
        ))
        return summary
    finally:
        engine.store.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--consent", action="store_true", help="simulate explicit consent by both owners"
    )
    args = parser.parse_args()
    print(json.dumps(run_demo(consent=args.consent), indent=2))
