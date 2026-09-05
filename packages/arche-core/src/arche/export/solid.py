# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Value-free JSON-LD projection for a caller-managed SOLID Pod.

This module deliberately exports a *recorded resolution assertion*, not an
``owl:sameAs`` statement. A vNext receipt is revisable, case-bound, and may
still require a later policy decision. Raw fields, values, scores, arbitrary
provenance, entity identifiers, and source-record identifiers are therefore
outside this projection.

The generated references are salted aliases. They let one exported document
refer to its case, receipt, and evidence without publishing local identifiers
or creating a cross-Pod linkage key. The salt stays with the caller; it is not
placed in the JSON-LD document.
"""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Protocol
from urllib.parse import urlsplit, urlunsplit

from arche.runtime._models import CaseEvent, DecisionReceipt, ResolutionCase, new_ledger_id

if TYPE_CHECKING:
    from arche.runtime.engine import ArcheEngine

SOLID_ASSERTION_SCHEMA = "arche.solid_resolution_assertion.v1"
_CONTEXT = {
    "arche": "urn:arche:vnext:",
    "schema": "https://schema.org/",
    "created": {
        "@id": "schema:dateCreated",
        "@type": "http://www.w3.org/2001/XMLSchema#dateTime",
    },
}


def _pod_base_url(value: str) -> str:
    """Validate a private HTTPS Pod container URL without accepting a query."""
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError(
            "pod_base_url must be an HTTPS URL without credentials, query, or fragment"
        )
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path.rstrip("/"), "", ""))


def _iri(value: str, *, name: str) -> str:
    """Accept only absolute HTTPS IRI references for consent/capability metadata."""
    parsed = urlsplit(value)
    if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
        raise ValueError(f"{name} must be an absolute HTTPS IRI without credentials")
    return value


def _salted_alias(kind: str, identifier: str, salt: bytes) -> str:
    """Return an export-local alias; it is intentionally not a linkage key."""
    digest = hashlib.sha256(salt + b"\0" + kind.encode() + b"\0" + identifier.encode()).digest()
    return base64.urlsafe_b64encode(digest).decode().rstrip("=")


def _assertion_digest(record: Mapping[str, object]) -> str:
    """Hash the safe projection, excluding its self-referential digest field."""
    encoded = json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def solid_resolution_assertion(
    case: ResolutionCase,
    receipt: DecisionReceipt,
    *,
    pod_base_url: str,
    exported_at: datetime,
    reference_salt: bytes | None = None,
    consent_record_iri: str | None = None,
    capability_iri: str | None = None,
) -> dict[str, object]:
    """Project one case-linked receipt into PII-free, case-scoped JSON-LD.

    ``reference_salt`` is caller-managed when a deterministic local rendering
    is needed. When omitted, a fresh salt prevents the aliases in two exports
    from becoming a cross-Pod correlation mechanism. It is never serialized.

    The caller must verify that the receipt belongs to ``case`` before calling
    this pure formatter. The CLI performs that store/history validation.
    """
    if not receipt.evidence_ids:
        raise ValueError("SOLID assertions require at least one evidence reference")
    if reference_salt is not None and not isinstance(reference_salt, bytes):
        raise TypeError("reference_salt must be bytes when supplied")
    if reference_salt is not None and len(reference_salt) < 16:
        raise ValueError("reference_salt must contain at least 16 bytes")
    base = _pod_base_url(pod_base_url)
    salt = reference_salt or secrets.token_bytes(32)
    case_ref = _salted_alias("case", case.case_id, salt)
    receipt_ref = _salted_alias("receipt", receipt.decision_id, salt)
    value: dict[str, object] = {
        "@context": _CONTEXT,
        "@id": f"{base}/arche/assertions/{receipt_ref}",
        "@type": ["arche:ResolutionAssertion"],
        "arche:schema": SOLID_ASSERTION_SCHEMA,
        "arche:scope": "case_bound_revisable_belief",
        "arche:assertionStatus": "recorded",
        "arche:case": {"@id": f"{base}/arche/cases/{case_ref}"},
        "arche:decisionReceipt": {"@id": f"{base}/arche/receipts/{receipt_ref}"},
        "arche:identityConclusion": receipt.identity_result,
        "arche:recommendedAction": receipt.action,
        "arche:evidence": [
            {"@id": f"{base}/arche/evidence/{_salted_alias('evidence', item, salt)}"}
            for item in receipt.evidence_ids
        ],
        "created": exported_at.isoformat(),
    }
    if receipt.policy_pin is not None:
        value["arche:policyPin"] = receipt.policy_pin
    if receipt.schema_pin is not None:
        value["arche:schemaPin"] = receipt.schema_pin
    if consent_record_iri is not None:
        value["arche:consentRecord"] = {"@id": _iri(consent_record_iri, name="consent_record_iri")}
    if capability_iri is not None:
        value["arche:capability"] = {"@id": _iri(capability_iri, name="capability_iri")}
    value["arche:projectionDigest"] = _assertion_digest(value)
    return value


@dataclass(frozen=True)
class SolidPublicationApproval:
    """A value-free, expiring caller approval to publish one case receipt.

    ``consent_reference`` and ``capability_reference`` are caller-managed
    opaque references, not bearer tokens and not remote URLs. Their real
    consent documents, credentials, and Pod authorization remain with the
    caller and never enter the Arche runtime store.
    """

    approval_id: str
    case_id: str
    decision_id: str
    policy_pin: str
    purpose: str
    consent_reference: str
    capability_reference: str
    approved_by_reference: str
    approved_at: datetime
    expires_at: datetime

    def __post_init__(self) -> None:
        if not all(
            isinstance(value, str) and value
            for value in (
                self.approval_id,
                self.case_id,
                self.decision_id,
                self.policy_pin,
                self.purpose,
                self.consent_reference,
                self.capability_reference,
                self.approved_by_reference,
            )
        ):
            raise ValueError("SOLID publication approval references must be non-empty strings")
        if self.expires_at <= self.approved_at:
            raise ValueError("SOLID publication approval expiry must be after approval")


@dataclass(frozen=True)
class SolidPodResponse:
    """A caller-owned transport response; bodies are never persisted."""

    status_code: int
    body: bytes = b""

    def __post_init__(self) -> None:
        if isinstance(self.status_code, bool) or not isinstance(self.status_code, int):
            raise ValueError("SOLID Pod response status_code must be an integer")
        if not isinstance(self.body, bytes):
            raise ValueError("SOLID Pod response body must be bytes")


class SolidPodTransport(Protocol):
    """Caller-owned authenticated HTTPS transport for one immutable JSON-LD PUT."""

    def put(
        self,
        url: str,
        body: bytes,
        *,
        headers: Mapping[str, str],
        timeout_seconds: float,
    ) -> SolidPodResponse:
        """Write an already-approved assertion to the caller's configured Pod."""


@dataclass(frozen=True)
class SolidPublicationResult:
    """Hash-only outcome from attempting one caller-approved Pod publication."""

    approval_id: str
    case_id: str
    decision_id: str
    outcome: str
    assertion_id: str
    assertion_hash: str
    target_sha256: str
    response_sha256: str | None = None
    response_status: int | None = None

    def __post_init__(self) -> None:
        if self.outcome not in {"published", "rejected", "failed"}:
            raise ValueError("SOLID publication outcome must be published, rejected, or failed")
        if not all(
            isinstance(value, str) and value
            for value in (
                self.approval_id,
                self.case_id,
                self.decision_id,
                self.assertion_id,
                self.assertion_hash,
                self.target_sha256,
            )
        ):
            raise ValueError("SOLID publication result references must be non-empty strings")
        if self.response_status is not None and (
            isinstance(self.response_status, bool) or not isinstance(self.response_status, int)
        ):
            raise ValueError("SOLID publication response_status must be an integer")


@dataclass
class SolidPodClient:
    """Publish an approved PII-free assertion through caller-owned transport.

    The client intentionally ships without OAuth, DPoP, WebID, or a default
    HTTP transport. The caller owns those credentials and supplies a transport
    implementation, which makes network egress explicit and testable.
    """

    transport: SolidPodTransport
    timeout_seconds: float = 10.0
    now: Callable[[], datetime] = lambda: datetime.now(UTC)

    def __post_init__(self) -> None:
        if self.timeout_seconds <= 0:
            raise ValueError("SOLID Pod timeout_seconds must be positive")

    def publish(
        self,
        case: ResolutionCase,
        receipt: DecisionReceipt,
        approval: SolidPublicationApproval,
        *,
        pod_base_url: str,
        reference_salt: bytes,
        consent_record_iri: str | None = None,
        capability_iri: str | None = None,
    ) -> SolidPublicationResult:
        """PUT one approved assertion and return only hashes/status metadata."""
        if (case.case_id, receipt.decision_id) != (approval.case_id, approval.decision_id):
            raise ValueError(
                "SOLID publication approval does not match the supplied case and receipt"
            )
        if receipt.policy_pin != approval.policy_pin:
            raise ValueError("SOLID publication approval policy pin does not match the receipt")
        if self.now() >= approval.expires_at:
            raise ValueError("SOLID publication approval has expired")
        assertion = solid_resolution_assertion(
            case,
            receipt,
            pod_base_url=pod_base_url,
            exported_at=self.now(),
            reference_salt=reference_salt,
            consent_record_iri=consent_record_iri,
            capability_iri=capability_iri,
        )
        assertion_id = assertion["@id"]
        if not isinstance(assertion_id, str):
            raise ValueError("SOLID assertion needs a string @id")
        body = json.dumps(assertion, sort_keys=True, separators=(",", ":")).encode()
        assertion_hash = _hash(body)
        target_hash = _hash(assertion_id.encode())
        try:
            response = self.transport.put(
                assertion_id,
                body,
                headers={"Content-Type": "application/ld+json", "If-None-Match": "*"},
                timeout_seconds=self.timeout_seconds,
            )
        except (OSError, TimeoutError):
            return SolidPublicationResult(
                approval.approval_id,
                case.case_id,
                receipt.decision_id,
                "failed",
                assertion_id,
                assertion_hash,
                target_hash,
            )
        response_hash = _hash(response.body)
        return SolidPublicationResult(
            approval.approval_id,
            case.case_id,
            receipt.decision_id,
            "published" if 200 <= response.status_code < 300 else "rejected",
            assertion_id,
            assertion_hash,
            target_hash,
            response_hash,
            response.status_code,
        )


def approve_solid_publication(
    engine: ArcheEngine,
    approval: SolidPublicationApproval,
) -> CaseEvent:
    """Persist a policy-pinned publication approval before any Pod transport runs."""
    if engine.store.get_resolution_case(approval.case_id) is None:
        raise ValueError(f"resolution case {approval.case_id!r} does not exist")
    receipt = engine.store.get_decision(approval.decision_id)
    if receipt is None:
        raise ValueError(f"decision receipt {approval.decision_id!r} does not exist")
    history = engine.get_case_history(approval.case_id)
    if not any(
        event.event_type == "resolver_decision" and approval.decision_id in event.references
        for event in history
    ):
        raise ValueError("SOLID publication requires a receipt recorded for this case")
    if receipt.policy_pin != approval.policy_pin:
        raise ValueError("SOLID publication approval policy pin does not match the receipt")
    if any(
        event.event_type == "solid_publication_approval"
        and approval.approval_id in event.references
        for event in history
    ):
        raise ValueError(f"SOLID publication approval {approval.approval_id!r} is already recorded")
    event = CaseEvent(
        new_ledger_id("evt"),
        approval.case_id,
        "solid_publication_approval",
        approval.approved_at,
        references=(approval.approval_id, approval.decision_id),
        provenance={
            "policy_pin": approval.policy_pin,
            "purpose": approval.purpose,
            "consent_reference": approval.consent_reference,
            "capability_reference": approval.capability_reference,
            "approved_by_reference": approval.approved_by_reference,
            "expires_at": approval.expires_at.isoformat(),
        },
    )
    engine.store.write_case_events([event])
    return event


def record_solid_publication(
    engine: ArcheEngine,
    approval: SolidPublicationApproval,
    result: SolidPublicationResult,
    *,
    recorded_at: datetime,
) -> CaseEvent:
    """Record one publication outcome without retaining its Pod URL or response body."""
    if (
        result.approval_id != approval.approval_id
        or result.case_id != approval.case_id
        or result.decision_id != approval.decision_id
    ):
        raise ValueError("SOLID publication result does not match the approved publication")
    history = engine.get_case_history(approval.case_id)
    if not any(
        event.event_type == "solid_publication_approval"
        and approval.approval_id in event.references
        for event in history
    ):
        raise ValueError("SOLID publication outcome requires a recorded approval")
    if any(
        event.event_type == "solid_publication" and approval.approval_id in event.references
        for event in history
    ):
        raise ValueError("SOLID publication approval already has a recorded outcome")
    event = CaseEvent(
        new_ledger_id("evt"),
        approval.case_id,
        "solid_publication",
        recorded_at,
        references=(approval.approval_id, approval.decision_id),
        provenance={
            "outcome": result.outcome,
            "assertion_sha256": result.assertion_hash,
            "target_sha256": result.target_sha256,
            "response_sha256": result.response_sha256,
            "response_status": result.response_status,
        },
    )
    engine.store.write_case_events([event])
    return event


def _hash(value: bytes) -> str:
    """Return the hash shape used in value-free publication history."""
    return "sha256:" + hashlib.sha256(value).hexdigest()
