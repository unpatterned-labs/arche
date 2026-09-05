# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Tests for the deliberately narrow SOLID resolution-assertion projection."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from arche.export import (
    SolidPodClient,
    SolidPodResponse,
    SolidPublicationApproval,
    approve_solid_publication,
    record_solid_publication,
    solid_resolution_assertion,
)
from arche.runtime import (
    CaseEvent,
    DecisionReceipt,
    Evidence,
    Observation,
    ResolutionCase,
    attach,
)


def _case_and_receipt() -> tuple[ResolutionCase, DecisionReceipt]:
    recorded_at = datetime(2026, 9, 4, 12, 0, tzinfo=UTC)
    return (
        ResolutionCase(
            "case_person_alice",
            "Does the private record for Alice Example identify this person?",
            ("obs_person_alice",),
            ("ent_person_alice",),
            recorded_at,
            uncertainty={"private_note": "Alice Example"},
        ),
        DecisionReceipt(
            "receipt_person_alice",
            "same_entity",
            "link",
            ("evidence_private_alice",),
            recorded_at,
            raw_score=0.99,
            probability=0.98,
            policy_pin="person-policy-v1",
            schema_pin="receipt-v1",
            provenance={"private_name": "Alice Example"},
        ),
    )


def _persist_case_receipt(engine, case: ResolutionCase, receipt: DecisionReceipt) -> None:
    observation = Observation(
        "obs_person_alice",
        "local-document",
        None,
        receipt.created_at,
        "sha256:document",
        provenance={"private_name": "Alice Example"},
    )
    evidence = Evidence(
        "evidence_private_alice",
        observation.observation_id,
        "reviewed_field",
        "supports",
        provenance={"private_value": "Alice Example"},
    )
    engine.store.write_observations([observation])
    engine.store.write_evidence([evidence])
    engine.store.write_resolution_cases([case])
    engine.store.write_decisions([receipt])
    engine.store.write_case_events(
        [
            CaseEvent(
                "evt_receipt",
                case.case_id,
                "resolver_decision",
                receipt.created_at,
                references=("run_private", receipt.decision_id),
            )
        ]
    )


def test_solid_projection_is_case_scoped_and_value_free():
    case, receipt = _case_and_receipt()

    result = solid_resolution_assertion(
        case,
        receipt,
        pod_base_url="https://pod.example/alice/private/",
        exported_at=datetime(2026, 9, 4, 12, 1, tzinfo=UTC),
        reference_salt=b"test-only-reference-salt-32-bytes",
        consent_record_iri="https://pod.example/alice/consents/current",
        capability_iri="https://pod.example/alice/capabilities/resolution-read",
    )

    rendered = json.dumps(result, sort_keys=True)
    assert result["@type"] == ["arche:ResolutionAssertion"]
    assert result["arche:scope"] == "case_bound_revisable_belief"
    assert result["arche:assertionStatus"] == "recorded"
    assert result["arche:identityConclusion"] == "same_entity"
    assert result["arche:recommendedAction"] == "link"
    assert result["arche:policyPin"] == "person-policy-v1"
    assert result["arche:consentRecord"] == {"@id": "https://pod.example/alice/consents/current"}
    assert result["arche:capability"] == {
        "@id": "https://pod.example/alice/capabilities/resolution-read"
    }
    assert result["arche:projectionDigest"].startswith("sha256:")
    assert "owl:sameAs" not in rendered
    assert "Alice Example" not in rendered
    assert "case_person_alice" not in rendered
    assert "receipt_person_alice" not in rendered
    assert "evidence_private_alice" not in rendered
    assert "ent_person_alice" not in rendered
    assert "0.99" not in rendered


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"pod_base_url": "http://pod.example/private"}, "pod_base_url"),
        ({"pod_base_url": "https://pod.example/private?token=secret"}, "pod_base_url"),
        ({"consent_record_iri": "http://pod.example/consent"}, "consent_record_iri"),
        ({"reference_salt": b"too-short"}, "reference_salt"),
    ],
)
def test_solid_projection_rejects_unsafe_or_weak_references(kwargs, message):
    case, receipt = _case_and_receipt()
    params = {
        "pod_base_url": "https://pod.example/private",
        "exported_at": datetime(2026, 9, 4, 12, 1, tzinfo=UTC),
        "reference_salt": b"test-only-reference-salt-32-bytes",
    }
    params.update(kwargs)

    with pytest.raises((TypeError, ValueError), match=message):
        solid_resolution_assertion(case, receipt, **params)


def test_solid_projection_requires_evidence():
    case, receipt = _case_and_receipt()
    empty = DecisionReceipt(
        receipt.decision_id,
        receipt.identity_result,
        receipt.action,
        (),
        receipt.created_at,
    )

    with pytest.raises(ValueError, match="evidence"):
        solid_resolution_assertion(
            case,
            empty,
            pod_base_url="https://pod.example/private",
            exported_at=datetime(2026, 9, 4, 12, 1, tzinfo=UTC),
        )


def test_cli_exports_only_a_receipt_recorded_for_its_case(tmp_path):
    from arche.cli import main

    case, receipt = _case_and_receipt()
    store_path = tmp_path / "solid.duckdb"
    output = tmp_path / "assertion.jsonld"
    engine = attach(f"duckdb:///{store_path}")
    _persist_case_receipt(engine, case, receipt)

    assert (
        main(
            [
                "case",
                "export-solid",
                case.case_id,
                receipt.decision_id,
                "--store",
                str(store_path),
                "--pod-base-url",
                "https://pod.example/alice/private",
                "--out",
                str(output),
            ]
        )
        == 0
    )
    rendered = output.read_text(encoding="utf-8")
    payload = json.loads(rendered)
    assert payload["arche:schema"] == "arche.solid_resolution_assertion.v1"
    assert "Alice Example" not in rendered
    assert receipt.decision_id not in rendered
    assert receipt.evidence_ids[0] not in rendered

    other_case = ResolutionCase(
        "case_other",
        "Unrelated question",
        ("obs_person_alice",),
        (),
        receipt.created_at,
    )
    engine.store.write_resolution_cases([other_case])
    with pytest.raises(SystemExit, match="not recorded for this case"):
        main(
            [
                "case",
                "export-solid",
                other_case.case_id,
                receipt.decision_id,
                "--store",
                str(store_path),
                "--pod-base-url",
                "https://pod.example/alice/private",
                "--out",
                str(output),
            ]
        )


def test_caller_owned_solid_client_requires_approval_and_records_hashes_only(tmp_path):
    case, receipt = _case_and_receipt()
    engine = attach(f"duckdb:///{tmp_path / 'solid-publish.duckdb'}")
    _persist_case_receipt(engine, case, receipt)
    approval = SolidPublicationApproval(
        "approval_solid_01",
        case.case_id,
        receipt.decision_id,
        "person-policy-v1",
        "case_bound_resolution_assertion",
        "consent-ref-01",
        "capability-ref-01",
        "reviewer-ref-01",
        receipt.created_at,
        datetime(2026, 9, 4, 13, 0, tzinfo=UTC),
    )
    approve_solid_publication(engine, approval)

    class RecordingTransport:
        def __init__(self):
            self.calls = []

        def put(self, url, body, *, headers, timeout_seconds):
            self.calls.append((url, body, headers, timeout_seconds))
            return SolidPodResponse(201, b"created")

    transport = RecordingTransport()
    result = SolidPodClient(transport, now=lambda: receipt.created_at).publish(
        case,
        receipt,
        approval,
        pod_base_url="https://pod.example/alice/private",
        reference_salt=b"test-only-reference-salt-32-bytes",
    )
    event = record_solid_publication(engine, approval, result, recorded_at=receipt.created_at)

    assert result.outcome == "published"
    assert transport.calls[0][2] == {
        "Content-Type": "application/ld+json",
        "If-None-Match": "*",
    }
    assert b"Alice Example" not in transport.calls[0][1]
    assert "pod.example" not in json.dumps(event.provenance)
    assert event.provenance["outcome"] == "published"
    assert event.provenance["assertion_sha256"].startswith("sha256:")
    with pytest.raises(ValueError, match="already has a recorded outcome"):
        record_solid_publication(engine, approval, result, recorded_at=receipt.created_at)


def test_solid_client_refuses_expired_approval_before_transport_runs():
    case, receipt = _case_and_receipt()
    approval = SolidPublicationApproval(
        "approval_expired",
        case.case_id,
        receipt.decision_id,
        "person-policy-v1",
        "case_bound_resolution_assertion",
        "consent-ref-01",
        "capability-ref-01",
        "reviewer-ref-01",
        datetime(2026, 9, 4, 10, 0, tzinfo=UTC),
        datetime(2026, 9, 4, 11, 0, tzinfo=UTC),
    )

    class UnexpectedTransport:
        def put(self, *args, **kwargs):
            raise AssertionError("expired approval must not reach a transport")

    with pytest.raises(ValueError, match="expired"):
        SolidPodClient(
            UnexpectedTransport(), now=lambda: datetime(2026, 9, 4, 12, 0, tzinfo=UTC)
        ).publish(
            case,
            receipt,
            approval,
            pod_base_url="https://pod.example/private",
            reference_salt=b"test-only-reference-salt-32-bytes",
        )
