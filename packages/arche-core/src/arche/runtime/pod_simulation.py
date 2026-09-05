# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Offline two-party consent experiment; not a SOLID authentication protocol.

Only request-scoped random IDs, a fixed purpose, and a fixed disclosure scope
cross the simulated boundary. Consent discloses permission to arrange review,
never the existence of a person or an identity conclusion. Each responder is
one ephemeral peer session; grants/revocation are in-memory, not cryptographic.
Applications must serialize calls: this simulator is deliberately single-writer.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime
from hashlib import sha256
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from ._models import CaseEvent, Observation, new_ledger_id

if TYPE_CHECKING:
    from .engine import ArcheEngine


def _time(value: datetime) -> None:
    """Require explicit time zones for consent windows."""
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("consent timestamps must have a timezone")


def _digest(value: bytes) -> str:
    """Hash the exact simulated wire bytes."""
    return "sha256:" + sha256(value).hexdigest()


@dataclass(frozen=True)
class PodReviewRequest:
    """Minimal simulation message with fresh, non-identity session identifiers."""

    request_id: str
    audience: str
    purpose: str = "resolution_evidence_review"
    disclosure: str = "review_permission_only"

    def __post_init__(self) -> None:
        for value in (self.request_id, self.audience):
            if not isinstance(value, str) or str(UUID(value)) != value:
                raise ValueError("simulation request IDs must be canonical UUIDs")
        if self.purpose != "resolution_evidence_review":
            raise ValueError("unsupported simulation purpose")
        if self.disclosure != "review_permission_only":
            raise ValueError("unsupported simulation disclosure")

    def to_bytes(self) -> bytes:
        """Return the complete request wire representation, containing no case data."""
        return json.dumps(asdict(self), sort_keys=True, separators=(",", ":")).encode()


class SimulatedPod:
    """A session-scoped responder with revocable, one-use local consent grants.

    No personal records are accepted. Consent is an application decision over
    a request, not proof of identity, WebID authentication, or a bearer credential.
    """

    def __init__(self) -> None:
        self.audience = str(uuid4())
        self._grants: dict[str, tuple[PodReviewRequest, datetime, datetime]] = {}
        self._consumed: set[str] = set()

    def grant(self, request: PodReviewRequest, *, now: datetime, expires_at: datetime) -> str:
        """Consent to this exact request; return a transient opaque grant handle.

        Raises ValueError for a different audience or an invalid consent window.
        The caller keeps the handle outside ledger/history and sends it only
        to this simulated responder when executing the approved request.
        """
        _time(now)
        _time(expires_at)
        if request.audience != self.audience or expires_at <= now:
            raise ValueError("consent needs the intended audience and a future expiry")
        grant_id = str(uuid4())
        self._grants[grant_id] = (request, now, expires_at)
        return grant_id

    def revoke(self, grant_id: str) -> None:
        """Remove a consent grant; revocation is local and immediate."""
        self._grants.pop(grant_id, None)

    def exchange(self, request: PodReviewRequest, grant_id: str, *, now: datetime) -> bytes:
        """Return only consent status; all denied grants share one response shape.

        Denied, expired, replayed, wrong-request and wrong-audience grants emit
        the same denial for a given request. No identity search is performed.
        """
        _time(now)
        grant = self._grants.get(grant_id)
        allowed = (
            grant is not None
            and grant[0] == request
            and request.audience == self.audience
            and grant[1] <= now < grant[2]
            and request.request_id not in self._consumed
        )
        if allowed:
            self._consumed.add(request.request_id)
            self._grants.pop(grant_id)
        return json.dumps(
            {"request_id": request.request_id, "status": "consented" if allowed else "denied"},
            sort_keys=True,
            separators=(",", ":"),
        ).encode()


def approve_pod_review(
    engine: ArcheEngine,
    action_id: str,
    plan_event_id: str,
    pod: SimulatedPod,
    *,
    approved_at: datetime,
    expires_at: datetime,
) -> PodReviewRequest:
    """Record the requesting application's approval of one planned Pod action.

    Call only after the human/application approves the plan. This creates a
    request but performs no exchange. The remote Pod owner must separately
    call ``pod.grant(request, now=..., expires_at=...)`` before execution.

    Raises ValueError for unplanned, completed, non-zero-cost or non-Pod work.
    """
    _time(approved_at)
    _time(expires_at)
    action = engine.store.get_evidence_action(action_id)
    if action is None or action.action_type != "pod_review_request" or action.max_cost != 0:
        raise ValueError("simulation requires a permitted zero-cost pod_review_request action")
    case = engine.store.get_resolution_case(action.case_id)
    if case is None or case.intent is None or case.intent.policy_pin != action.policy_pin:
        raise ValueError("Pod action requires the case intent's policy pin")
    history = engine.get_case_history(action.case_id)
    if not any(
        event.event_id == plan_event_id
        and event.event_type == "evidence_plan"
        and action_id in event.references
        for event in history
    ):
        raise ValueError("record a plan selecting this action before approval")
    if approved_at < action.permitted_at or expires_at <= approved_at:
        raise ValueError("approval requires a valid window after action permission")
    if engine.store.get_action_observation(action_id) is not None or any(
        event.event_type == "pod_review_approval" and action_id in event.references
        for event in history
    ):
        raise ValueError("action already approved or completed; permit a new action for a retry")
    request = PodReviewRequest(str(uuid4()), pod.audience)
    engine.store.write_case_events([
        CaseEvent(
            new_ledger_id("evt"), action.case_id, "pod_review_approval", approved_at,
            references=(action_id, plan_event_id),
            provenance={
                "request_sha256": _digest(request.to_bytes()),
                "policy_pin": action.policy_pin,
                "source_id": action.source_id,
                "expires_at": expires_at.isoformat(),
            },
        )
    ])
    return request


def execute_pod_review(
    engine: ArcheEngine,
    action_id: str,
    request: PodReviewRequest,
    pod: SimulatedPod,
    grant_id: str,
    *,
    now: datetime,
) -> Observation:
    """Exchange an exactly approved request and persist a non-identity Observation.

    Approval, source, policy, audience, expiry and replay checks precede exchange.
    A persisted attempt prevents automatic retries, including after restart.
    A transport exception becomes a failure Observation with no exception text.
    No Evidence, receipt, claim, or entity is created by this function.

    Raises ValueError if local approval is absent, mismatched, stale or consumed.
    """
    _time(now)
    action = engine.store.get_evidence_action(action_id)
    if action is None or action.action_type != "pod_review_request" or action.max_cost != 0:
        raise ValueError("simulation requires a permitted zero-cost Pod action")
    request_hash = _digest(request.to_bytes())
    history = engine.get_case_history(action.case_id)
    approval = next((event for event in history if (
        event.event_type == "pod_review_approval"
        and action_id in event.references
        and event.provenance.get("request_sha256") == request_hash
        and event.provenance.get("policy_pin") == action.policy_pin
        and event.provenance.get("source_id") == action.source_id
    )), None)
    if approval is None:
        raise ValueError("record approval for this exact request before exchanging")
    expiry = datetime.fromisoformat(str(approval.provenance["expires_at"]))
    if not approval.recorded_at <= now < expiry:
        raise ValueError("approval is expired or not yet valid")
    if request.audience != pod.audience:
        raise ValueError("request audience differs from approved Pod")
    if engine.store.get_action_observation(action_id) is not None or any(
        event.event_type == "pod_review_attempt" and action_id in event.references
        for event in history
    ):
        raise ValueError("action already attempted; permit a new action for a retry")
    engine.store.write_case_events([
        CaseEvent(new_ledger_id("evt"), action.case_id, "pod_review_attempt", now,
                  references=(action_id,), provenance={"request_sha256": request_hash})
    ])
    response_hash = None
    try:
        response = pod.exchange(request, grant_id, now=now)
        response_hash = _digest(response)
        payload = json.loads(response)
        if (
            set(payload) != {"request_id", "status"}
            or payload["request_id"] != request.request_id
            or payload["status"] not in {"consented", "denied"}
        ):
            raise ValueError("invalid simulated response")
        status = payload["status"]
    except Exception:
        status = "failed"
    observation = Observation(
        new_ledger_id("obs"), action.source_id, None, now,
        _digest(json.dumps([request_hash, response_hash, status]).encode()),
        provenance={
            "kind": "simulated_pod_consent", "simulation": True,
            "outcome": status, "request_sha256": request_hash,
            "response_sha256": response_hash, "identity_evidence": False,
        },
    )
    engine.ingest_action_observation(action_id, observation)
    engine.store.write_case_events([
        CaseEvent(new_ledger_id("evt"), action.case_id, "pod_review_result", now,
                  references=(action_id, observation.observation_id),
                  provenance={"outcome": status, "simulation": True})
    ])
    return observation
