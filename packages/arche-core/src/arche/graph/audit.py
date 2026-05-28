# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""SQLite-backed audit log for arche identity workflows.

Per Stage 1 PRD §8.2 FR-AUDIT-1..7:

- Every detection, address parse, policy decision, and workflow event
  recorded with model_version, span offsets, category, confidence,
  action, statute, timestamp, document_hash.
- SQLite as the storage backend (Python standard library — no extra
  dependency).
- Append-only by convention; mutations require explicit migration API.
- **No PII values stored.** PII is recorded by category and span offset
  only, never by value (FR-AUDIT-6). Document hashes link rows to
  source documents without leaking content.
- Queryable via SQL (direct connection access) and convenience methods.
- Compliance report generation (Markdown).

Schema includes nullable ``prev_hash`` and ``signature`` columns so the
hash-chained audit (Stage 2-3) and per-row signing become additive
migrations rather than schema breaks (locked decision, 2026-06-02).

Example::

    from arche.graph.audit import AuditLog, AuditEvent

    audit = AuditLog("./arche-audit.sqlite")
    audit.emit(AuditEvent.detection(
        document_hash="...",
        category="PII-2-NIN",
        span=(30, 41),
        confidence=0.95,
        detector="rule:ng_nin",
    ))

    for evt in audit.query(category="PII-2-NIN"):
        print(evt)

    # Export signed JWS for regulator handoff:
    from arche.sign import generate_keypair
    kp = generate_keypair()
    signed = audit.export_signed(key=kp, since=datetime(2026, 1, 1))
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator, Literal

EventType = Literal[
    "detection",
    "policy",
    "address",
    "workflow_start",
    "workflow_end",
]


# ---------------------------------------------------------------------------
# AuditEvent dataclass
# ---------------------------------------------------------------------------

@dataclass
class AuditEvent:
    """One row in the audit log.

    Most fields are optional — different event types populate different
    subsets. ``timestamp`` and ``document_hash`` are the only universally
    required fields.

    PII value is **never** stored. ``span_start`` and ``span_end`` are
    character offsets only; the original substring lives in the document,
    not the audit log.
    """

    timestamp: str               # ISO 8601 UTC
    event_type: str              # detection | policy | address | workflow_start | workflow_end
    document_hash: str           # sha256 hex of the source document
    detection_id: str | None = None
    category: str | None = None
    span_start: int | None = None
    span_end: int | None = None
    confidence: float | None = None
    action: str | None = None    # mask | tokenize | drop | generalize | audit | retain
    statute_id: str | None = None
    statute_reference: str | None = None
    detector: str | None = None
    model_version: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    # Stage 2-3 forward-compat (nullable, unpopulated in v0.2).
    prev_hash: str | None = None
    signature: str | None = None

    # Convenience constructors

    @classmethod
    def detection(
        cls,
        *,
        document_hash: str,
        category: str,
        span: tuple[int, int],
        confidence: float,
        detector: str,
        detection_id: str | None = None,
        model_version: str | None = None,
        metadata: dict[str, Any] | None = None,
        timestamp: datetime | None = None,
    ) -> "AuditEvent":
        return cls(
            timestamp=(timestamp or datetime.now(timezone.utc)).isoformat(),
            event_type="detection",
            document_hash=document_hash,
            detection_id=detection_id or f"det:{span[0]}:{span[1]}",
            category=category,
            span_start=span[0],
            span_end=span[1],
            confidence=confidence,
            detector=detector,
            model_version=model_version,
            metadata=metadata or {},
        )

    @classmethod
    def policy(
        cls,
        *,
        document_hash: str,
        category: str,
        action: str,
        statute_id: str,
        statute_reference: str,
        detection_id: str | None = None,
        span: tuple[int, int] | None = None,
        metadata: dict[str, Any] | None = None,
        timestamp: datetime | None = None,
    ) -> "AuditEvent":
        return cls(
            timestamp=(timestamp or datetime.now(timezone.utc)).isoformat(),
            event_type="policy",
            document_hash=document_hash,
            detection_id=detection_id,
            category=category,
            span_start=span[0] if span else None,
            span_end=span[1] if span else None,
            action=action,
            statute_id=statute_id,
            statute_reference=statute_reference,
            metadata=metadata or {},
        )


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

_SCHEMA = """
CREATE TABLE IF NOT EXISTS audit_events (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp       TEXT NOT NULL,
    event_type      TEXT NOT NULL,
    document_hash   TEXT NOT NULL,
    detection_id    TEXT,
    category        TEXT,
    span_start      INTEGER,
    span_end        INTEGER,
    confidence      REAL,
    action          TEXT,
    statute_id      TEXT,
    statute_reference TEXT,
    detector        TEXT,
    model_version   TEXT,
    metadata        TEXT,
    prev_hash       TEXT,
    signature       TEXT
);
CREATE INDEX IF NOT EXISTS idx_audit_doc_hash    ON audit_events(document_hash);
CREATE INDEX IF NOT EXISTS idx_audit_timestamp   ON audit_events(timestamp);
CREATE INDEX IF NOT EXISTS idx_audit_category    ON audit_events(category);
CREATE INDEX IF NOT EXISTS idx_audit_event_type  ON audit_events(event_type);
"""


# ---------------------------------------------------------------------------
# AuditLog
# ---------------------------------------------------------------------------

class AuditLog:
    """SQLite-backed audit log.

    Parameters
    ----------
    path:
        Path to the SQLite database. ``":memory:"`` for ephemeral logs
        (the Pipeline default when no path is configured). Recommended:
        a stable file path under the deployment's data directory.

    The connection is opened lazily on first write/read and reused.
    The schema is created if absent (idempotent).
    """

    def __init__(self, path: str | Path = ":memory:"):
        self.path = str(path)
        self._conn: sqlite3.Connection | None = None

    # -----------------------------------------------------------------------
    # Connection lifecycle
    # -----------------------------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(
                self.path,
                isolation_level=None,  # autocommit; we control transactions
                check_same_thread=False,
            )
            self._conn.executescript(_SCHEMA)
            self._conn.row_factory = sqlite3.Row
        return self._conn

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        conn = self._connect()
        conn.execute("BEGIN")
        try:
            yield conn
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise

    # -----------------------------------------------------------------------
    # Writes (append-only)
    # -----------------------------------------------------------------------

    def emit(self, event: AuditEvent) -> int:
        """Append an event to the log. Returns the row id."""
        # Guard against accidental PII leakage: refuse to write if the
        # caller stuffed the raw text into metadata under a "text" key.
        _scrub_pii_value(event)

        with self._transaction() as conn:
            cur = conn.execute(
                """
                INSERT INTO audit_events (
                    timestamp, event_type, document_hash, detection_id,
                    category, span_start, span_end, confidence, action,
                    statute_id, statute_reference, detector, model_version,
                    metadata, prev_hash, signature
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    event.timestamp, event.event_type, event.document_hash,
                    event.detection_id, event.category,
                    event.span_start, event.span_end, event.confidence,
                    event.action, event.statute_id, event.statute_reference,
                    event.detector, event.model_version,
                    json.dumps(event.metadata or {}, sort_keys=True),
                    event.prev_hash, event.signature,
                ),
            )
            return int(cur.lastrowid)

    def emit_many(self, events: Iterable[AuditEvent]) -> list[int]:
        """Append many events in one transaction. Returns row ids."""
        ids: list[int] = []
        with self._transaction() as conn:
            for event in events:
                _scrub_pii_value(event)
                cur = conn.execute(
                    """
                    INSERT INTO audit_events (
                        timestamp, event_type, document_hash, detection_id,
                        category, span_start, span_end, confidence, action,
                        statute_id, statute_reference, detector, model_version,
                        metadata, prev_hash, signature
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        event.timestamp, event.event_type, event.document_hash,
                        event.detection_id, event.category,
                        event.span_start, event.span_end, event.confidence,
                        event.action, event.statute_id, event.statute_reference,
                        event.detector, event.model_version,
                        json.dumps(event.metadata or {}, sort_keys=True),
                        event.prev_hash, event.signature,
                    ),
                )
                ids.append(int(cur.lastrowid))
        return ids

    # -----------------------------------------------------------------------
    # Queries
    # -----------------------------------------------------------------------

    def query(
        self,
        *,
        document_hash: str | None = None,
        category: str | None = None,
        event_type: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int | None = None,
    ) -> list[AuditEvent]:
        """Convenience SELECT with the common filters.

        For more complex queries, access ``log.connection`` directly.
        """
        conn = self._connect()
        clauses: list[str] = []
        args: list[Any] = []
        if document_hash is not None:
            clauses.append("document_hash = ?")
            args.append(document_hash)
        if category is not None:
            clauses.append("category = ?")
            args.append(category)
        if event_type is not None:
            clauses.append("event_type = ?")
            args.append(event_type)
        if since is not None:
            clauses.append("timestamp >= ?")
            args.append(since.isoformat())
        if until is not None:
            clauses.append("timestamp <= ?")
            args.append(until.isoformat())

        sql = "SELECT * FROM audit_events"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY id"
        if limit is not None:
            sql += f" LIMIT {int(limit)}"

        rows = conn.execute(sql, args).fetchall()
        return [_row_to_event(r) for r in rows]

    def count(self, **filters: Any) -> int:
        """Count events matching filters (same kwargs as ``query``)."""
        events = self.query(**filters)
        return len(events)

    @property
    def connection(self) -> sqlite3.Connection:
        """Direct SQLite connection for ad-hoc SQL.

        Use sparingly. Convention is append-only; arbitrary UPDATE/DELETE
        breaks the audit log's evidentiary value.
        """
        return self._connect()

    # -----------------------------------------------------------------------
    # Reporting
    # -----------------------------------------------------------------------

    def compliance_report_markdown(
        self,
        *,
        document_hash: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> str:
        """Render a human-readable Markdown compliance report.

        Rows are summarised by (jurisdiction, statute, category, action)
        with counts and statute references. Designed for handing to a
        regulator or compliance officer.
        """
        events = self.query(
            document_hash=document_hash, since=since, until=until
        )
        if not events:
            return "# arche compliance report\n\nNo audit events in scope.\n"

        from collections import Counter
        action_counts: Counter[tuple[str, str, str]] = Counter()
        statute_refs: dict[tuple[str, str, str], str] = {}
        documents: set[str] = set()

        for e in events:
            documents.add(e.document_hash)
            if e.event_type == "policy" and e.category and e.action and e.statute_id:
                key = (e.statute_id, e.category, e.action)
                action_counts[key] += 1
                if e.statute_reference:
                    statute_refs.setdefault(key, e.statute_reference)

        lines: list[str] = [
            "# arche compliance report",
            "",
            f"Generated: {datetime.now(timezone.utc).isoformat()}  ",
            f"Audit log: `{self.path}`  ",
            f"Total events: {len(events)}  ",
            f"Distinct documents: {len(documents)}",
            "",
            "## Policy actions taken",
            "",
            "| Statute | Category | Action | Count | Reference |",
            "|---|---|---|---:|---|",
        ]
        for (statute_id, category, action), count in sorted(action_counts.items()):
            ref = statute_refs.get((statute_id, category, action), "")
            lines.append(f"| {statute_id} | {category} | {action} | {count} | {ref} |")

        lines.append("")
        lines.append("## Event-type breakdown")
        lines.append("")
        lines.append("| Event type | Count |")
        lines.append("|---|---:|")
        type_counts = Counter(e.event_type for e in events)
        for t, c in sorted(type_counts.items()):
            lines.append(f"| {t} | {c} |")

        lines.append("")
        lines.append(
            "_Generated by arche-core.  PII values are never stored in the "
            "audit log; only category labels and character span offsets._"
        )
        return "\n".join(lines) + "\n"

    # -----------------------------------------------------------------------
    # Export — JSON, optionally signed
    # -----------------------------------------------------------------------

    def export(
        self,
        *,
        document_hash: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> dict[str, Any]:
        """Return a dict suitable for serialization.

        The export bundle structure is::

            {
              "schema": "arche+audit-export/v1",
              "exported_at": "<ISO 8601>",
              "events": [<AuditEvent-as-dict>, ...],
              "summary": {"count": N, "documents": ["...", ...]}
            }
        """
        events = self.query(
            document_hash=document_hash, since=since, until=until
        )
        return {
            "schema": "arche+audit-export/v1",
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "events": [asdict(e) for e in events],
            "summary": {
                "count": len(events),
                "documents": sorted({e.document_hash for e in events}),
            },
        }

    def export_signed(
        self,
        *,
        key,
        document_hash: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        purpose: str = "audit_export",
    ) -> str:
        """Export and sign the bundle as a JWS compact string.

        The signed envelope is the right artifact to hand to a regulator
        or to attach to a DSAR response: tamper-evident, offline-
        verifiable, and recovers the structured event list intact.

        Parameters
        ----------
        key:
            ``arche.sign.Keypair`` or raw ``Ed25519PrivateKey``.
        purpose:
            Free-form purpose tag carried in the JWS payload.
        """
        from arche.sign import Keypair, encode_did_key, sign
        from cryptography.hazmat.primitives.asymmetric.ed25519 import (
            Ed25519PrivateKey,
        )

        if isinstance(key, Keypair):
            private_key = key.private_key
            did = key.did_key
        elif isinstance(key, Ed25519PrivateKey):
            private_key = key
            did = encode_did_key(key.public_key())
        else:
            raise TypeError(
                f"Expected Keypair or Ed25519PrivateKey, got {type(key).__name__}"
            )

        bundle = self.export(
            document_hash=document_hash, since=since, until=until
        )
        bundle["purpose"] = purpose
        bundle["issuer"] = did
        return sign(bundle, private_key, kid=did, typ="arche+audit-export")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _row_to_event(row: sqlite3.Row) -> AuditEvent:
    """Turn a sqlite3.Row back into an AuditEvent."""
    metadata = row["metadata"]
    if metadata:
        try:
            metadata = json.loads(metadata)
        except json.JSONDecodeError:
            metadata = {"_raw": metadata}
    else:
        metadata = {}
    return AuditEvent(
        timestamp=row["timestamp"],
        event_type=row["event_type"],
        document_hash=row["document_hash"],
        detection_id=row["detection_id"],
        category=row["category"],
        span_start=row["span_start"],
        span_end=row["span_end"],
        confidence=row["confidence"],
        action=row["action"],
        statute_id=row["statute_id"],
        statute_reference=row["statute_reference"],
        detector=row["detector"],
        model_version=row["model_version"],
        metadata=metadata,
        prev_hash=row["prev_hash"],
        signature=row["signature"],
    )


_PII_LEAK_KEYS = {"text", "value", "raw", "content"}


def _scrub_pii_value(event: AuditEvent) -> None:
    """Defensive guard: refuse to persist metadata that smells like PII.

    Per PRD §8.2 FR-AUDIT-6 and NFR-SEC-3, the audit log never stores
    PII values. If a caller accidentally puts the raw detected text into
    ``metadata["text"]`` (or similar), strip it.
    """
    if not event.metadata:
        return
    for key in list(event.metadata.keys()):
        if key.lower() in _PII_LEAK_KEYS:
            del event.metadata[key]
