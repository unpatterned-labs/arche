# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Tests for arche.graph.audit — SQLite-backed audit log (PRD §8.2)."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from arche.graph.audit import AuditEvent, AuditLog
from arche.sign import VerifyExtractWorkflow, generate_keypair


# ── Construction + schema ───────────────────────────────────────────────────


def test_in_memory_audit_log_constructs_schema_lazily():
    log = AuditLog(":memory:")
    log.emit(AuditEvent.detection(
        document_hash="doc_abc",
        category="PII-2-NIN",
        span=(0, 11),
        confidence=0.9,
        detector="rule:ng_nin",
    ))
    rows = log.query()
    assert len(rows) == 1


def test_file_backed_audit_log_persists(tmp_path: Path):
    db = tmp_path / "audit.sqlite"
    log = AuditLog(db)
    log.emit(AuditEvent.detection(
        document_hash="doc1", category="PII-2-NIN", span=(0, 11),
        confidence=0.9, detector="rule:ng_nin",
    ))
    log.close()

    reopened = AuditLog(db)
    assert len(reopened.query()) == 1
    reopened.close()


# ── Append-only writes ──────────────────────────────────────────────────────


def test_emit_detection_event():
    log = AuditLog()
    row_id = log.emit(AuditEvent.detection(
        document_hash="doc_xyz",
        category="PII-2-NIN",
        span=(30, 41),
        confidence=0.85,
        detector="rule:ng_nin",
    ))
    assert row_id == 1


def test_emit_policy_event():
    log = AuditLog()
    log.emit(AuditEvent.policy(
        document_hash="doc_xyz",
        category="PII-2-NIN",
        action="mask",
        statute_id="NDPA-2023",
        statute_reference="NDPA-2023 s.30",
        span=(30, 41),
    ))
    events = log.query(event_type="policy")
    assert len(events) == 1
    assert events[0].action == "mask"
    assert events[0].statute_id == "NDPA-2023"


def test_emit_many_in_one_transaction():
    log = AuditLog()
    events = [
        AuditEvent.detection(
            document_hash="d", category=f"PII-2-{label}", span=(i, i+10),
            confidence=0.9, detector="rule:x",
        )
        for i, label in enumerate(["NIN", "BVN", "TIN"])
    ]
    ids = log.emit_many(events)
    assert ids == [1, 2, 3]
    assert log.count() == 3


# ── PII never stored (FR-AUDIT-6) ───────────────────────────────────────────


def test_pii_text_in_metadata_is_scrubbed():
    """Per PRD §8.2 FR-AUDIT-6: the audit log NEVER stores PII values.

    If a caller accidentally puts the raw text into metadata, strip it.
    """
    log = AuditLog()
    log.emit(AuditEvent.detection(
        document_hash="d",
        category="PII-2-NIN",
        span=(0, 11),
        confidence=0.9,
        detector="rule:ng_nin",
        metadata={
            "text": "12345678901",   # MUST be scrubbed
            "VALUE": "12345678901",  # case-insensitive
            "model_kind": "regex",   # non-PII metadata kept
        },
    ))
    [event] = log.query()
    assert "text" not in event.metadata
    assert "VALUE" not in event.metadata
    assert event.metadata.get("model_kind") == "regex"


def test_raw_pii_keys_scrubbed_in_emit_many():
    log = AuditLog()
    log.emit_many([AuditEvent.detection(
        document_hash="d", category="PII-2-NIN", span=(0, 11),
        confidence=0.9, detector="r", metadata={"raw": "12345678901"},
    )])
    [event] = log.query()
    assert "raw" not in event.metadata


# ── Queries ─────────────────────────────────────────────────────────────────


def test_query_filter_by_document_hash():
    log = AuditLog()
    log.emit(AuditEvent.detection(document_hash="A", category="PII-2-NIN",
                                  span=(0, 11), confidence=0.9, detector="r"))
    log.emit(AuditEvent.detection(document_hash="B", category="PII-2-NIN",
                                  span=(0, 11), confidence=0.9, detector="r"))
    assert len(log.query(document_hash="A")) == 1
    assert len(log.query(document_hash="B")) == 1
    assert len(log.query()) == 2


def test_query_filter_by_category():
    log = AuditLog()
    log.emit(AuditEvent.detection(document_hash="d", category="PII-2-NIN",
                                  span=(0, 11), confidence=0.9, detector="r"))
    log.emit(AuditEvent.detection(document_hash="d", category="PII-2-BVN",
                                  span=(20, 31), confidence=0.9, detector="r"))
    assert len(log.query(category="PII-2-NIN")) == 1
    assert len(log.query(category="PII-2-BVN")) == 1


def test_query_filter_by_time_range():
    log = AuditLog()
    base = datetime(2026, 6, 1, tzinfo=timezone.utc)
    log.emit(AuditEvent.detection(
        document_hash="d", category="X", span=(0, 1), confidence=1.0,
        detector="r", timestamp=base,
    ))
    log.emit(AuditEvent.detection(
        document_hash="d", category="X", span=(0, 1), confidence=1.0,
        detector="r", timestamp=base + timedelta(days=10),
    ))
    in_window = log.query(
        since=base + timedelta(days=5),
        until=base + timedelta(days=15),
    )
    assert len(in_window) == 1


def test_query_respects_limit():
    log = AuditLog()
    for i in range(5):
        log.emit(AuditEvent.detection(
            document_hash="d", category="X", span=(i, i+1),
            confidence=1.0, detector="r",
        ))
    assert len(log.query(limit=2)) == 2


# ── Compliance report ──────────────────────────────────────────────────────


def test_compliance_report_summarises_actions():
    log = AuditLog()
    for _ in range(3):
        log.emit(AuditEvent.policy(
            document_hash="d", category="PII-2-NIN", action="mask",
            statute_id="NDPA-2023", statute_reference="NDPA-2023 s.30",
        ))
    log.emit(AuditEvent.policy(
        document_hash="d", category="PII-3-PHONE", action="tokenize",
        statute_id="NDPA-2023", statute_reference="NDPA-2023 s.30",
    ))

    report = log.compliance_report_markdown()
    assert "arche compliance report" in report
    assert "PII-2-NIN" in report
    assert "mask" in report
    assert "| 3 |" in report  # the count column for NIN
    assert "PII-3-PHONE" in report
    assert "NDPA-2023 s.30" in report


def test_compliance_report_handles_empty_log():
    log = AuditLog()
    report = log.compliance_report_markdown()
    assert "No audit events" in report


# ── Export (unsigned) ──────────────────────────────────────────────────────


def test_export_returns_serializable_bundle():
    log = AuditLog()
    log.emit(AuditEvent.detection(document_hash="d", category="PII-2-NIN",
                                  span=(0, 11), confidence=0.9, detector="r"))
    bundle = log.export()
    assert bundle["schema"] == "arche+audit-export/v1"
    assert len(bundle["events"]) == 1
    assert bundle["summary"]["count"] == 1
    assert bundle["summary"]["documents"] == ["d"]
    json.dumps(bundle)


# ── Signed export (JWS) ────────────────────────────────────────────────────


def test_export_signed_produces_verifiable_jws():
    """The headline FR-AUDIT capability: hand a regulator a tamper-evident,
    offline-verifiable audit bundle."""
    log = AuditLog()
    log.emit(AuditEvent.detection(document_hash="d", category="PII-2-NIN",
                                  span=(0, 11), confidence=0.95, detector="rule:ng_nin"))
    log.emit(AuditEvent.policy(document_hash="d", category="PII-2-NIN",
                               action="mask", statute_id="NDPA-2023",
                               statute_reference="NDPA-2023 s.30"))

    kp = generate_keypair()
    signed = log.export_signed(key=kp)
    assert signed.count(".") == 2  # JWS compact form

    # Verify offline (kid embeds did:key)
    verifier = VerifyExtractWorkflow(strict=False)
    result = verifier.process(signed)
    assert result.signature_valid is True
    assert result.issuer_did == kp.did_key


def test_export_signed_filters_propagate():
    log = AuditLog()
    log.emit(AuditEvent.detection(document_hash="A", category="PII-2-NIN",
                                  span=(0, 11), confidence=0.9, detector="r"))
    log.emit(AuditEvent.detection(document_hash="B", category="PII-2-NIN",
                                  span=(0, 11), confidence=0.9, detector="r"))

    kp = generate_keypair()
    signed = log.export_signed(key=kp, document_hash="A")

    # Decode the JWS payload to confirm the filter applied
    import base64
    _, payload_b64, _ = signed.split(".")
    payload_b64 += "=" * ((-len(payload_b64)) % 4)
    bundle = json.loads(base64.urlsafe_b64decode(payload_b64))
    assert bundle["summary"]["count"] == 1
    assert bundle["summary"]["documents"] == ["A"]
