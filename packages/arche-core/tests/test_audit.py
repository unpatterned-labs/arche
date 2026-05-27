"""Tests for audit trail."""

import time

from arche.audit import AuditEntry, AuditLog, create_audit_entry, get_audit_log


def test_audit_entry_creation():
    entry = AuditEntry(
        timestamp="2026-04-06T12:00:00Z",
        action="resolve",
        input_hash="abc123",
        entity_count=5,
        resolved_count=2,
        pii_count=3,
        confidence_range=(0.85, 0.95),
        match_reasons=["name_similarity"],
        processing_time_ms=42.5,
    )
    assert entry.action == "resolve"
    assert entry.pii_count == 3


def test_audit_entry_to_dict():
    entry = AuditEntry(
        timestamp="2026-04-06T12:00:00Z", action="test",
        input_hash="xyz", entity_count=1, resolved_count=0,
        pii_count=0, confidence_range=(0.0, 0.0),
        match_reasons=[], processing_time_ms=1.0,
    )
    d = entry.to_dict()
    assert d["action"] == "test"
    assert isinstance(d["confidence_range"], list)


def test_audit_log_append():
    log = AuditLog()
    entry = AuditEntry(
        timestamp="2026-04-06T12:00:00Z", action="test",
        input_hash="xyz", entity_count=0, resolved_count=0,
        pii_count=0, confidence_range=(0.0, 0.0),
        match_reasons=[], processing_time_ms=0.0,
    )
    log.append(entry)
    assert len(log) == 1
    assert log.entries[0].action == "test"


def test_audit_log_export():
    log = AuditLog()
    log.append(AuditEntry(
        timestamp="t", action="a", input_hash="h",
        entity_count=0, resolved_count=0, pii_count=0,
        confidence_range=(0.0, 0.0), match_reasons=[],
        processing_time_ms=0.0,
    ))
    exported = log.export()
    assert len(exported) == 1
    assert exported[0]["action"] == "a"


def test_create_audit_entry_hashes_input():
    entry = create_audit_entry(
        action="test",
        input_text="sensitive PII data here",
        entity_count=1,
        start_time=time.perf_counter(),
    )
    # Input should be hashed, not stored raw
    assert "sensitive" not in entry.input_hash
    assert len(entry.input_hash) == 64  # SHA-256 hex length


def test_resolve_creates_audit_entry():
    from arche import resolve
    result = resolve("Test text for audit", backend="regex")
    assert result.audit_entry is not None
    assert result.audit_entry.action == "resolve"
    assert result.audit_entry.processing_time_ms > 0


def test_global_audit_log():
    log = get_audit_log()
    initial_len = len(log)
    from arche import resolve
    resolve("Audit log test", backend="regex")
    assert len(log) > initial_len
