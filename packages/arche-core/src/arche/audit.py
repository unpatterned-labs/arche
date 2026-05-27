# Copyright 2026 unpatterned.org
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Audit trail for DPI compliance — tracks every resolution decision.

Every call to resolve() generates an AuditEntry containing metadata about
the operation (timing, counts, confidence) without any PII. The input is
hashed (SHA-256), never stored raw.

Usage:
    from arche.audit import get_audit_log
    log = get_audit_log()
    for entry in log.entries:
        print(entry.timestamp, entry.action, entry.entity_count)
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass
from datetime import UTC, datetime


@dataclass
class AuditEntry:
    """A single audit record for an identity resolution operation.

    Contains NO PII — the input is represented only by its SHA-256 hash.
    """

    timestamp: str  # ISO 8601
    action: str  # "resolve", "detect_pii"
    input_hash: str  # SHA-256 of input text (not the text itself)
    entity_count: int
    resolved_count: int
    pii_count: int
    confidence_range: tuple[float, float]  # (min, max) of resolved confidences
    match_reasons: list[str]
    processing_time_ms: float

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "action": self.action,
            "input_hash": self.input_hash,
            "entity_count": self.entity_count,
            "resolved_count": self.resolved_count,
            "pii_count": self.pii_count,
            "confidence_range": list(self.confidence_range),
            "match_reasons": self.match_reasons,
            "processing_time_ms": round(self.processing_time_ms, 2),
        }


class AuditLog:
    """Append-only audit log for resolution operations."""

    def __init__(self) -> None:
        self._entries: list[AuditEntry] = []

    def append(self, entry: AuditEntry) -> None:
        self._entries.append(entry)

    @property
    def entries(self) -> list[AuditEntry]:
        return list(self._entries)

    def export(self) -> list[dict]:
        """Export all entries as plain dicts (JSON-serializable)."""
        return [e.to_dict() for e in self._entries]

    def clear(self) -> None:
        self._entries.clear()

    def __len__(self) -> int:
        return len(self._entries)


# Module-level singleton
_audit_log = AuditLog()


def get_audit_log() -> AuditLog:
    """Return the global audit log instance."""
    return _audit_log


def create_audit_entry(
    *,
    action: str,
    input_text: str,
    entity_count: int = 0,
    resolved_count: int = 0,
    pii_count: int = 0,
    confidences: list[float] | None = None,
    match_reasons: list[str] | None = None,
    start_time: float,
) -> AuditEntry:
    """Create an audit entry and append it to the global log.

    Parameters
    ----------
    action:
        What operation was performed.
    input_text:
        The raw input (will be hashed, not stored).
    start_time:
        Result of ``time.perf_counter()`` at the start of the operation.
    """
    elapsed_ms = (time.perf_counter() - start_time) * 1000
    input_hash = hashlib.sha256(input_text.encode("utf-8", errors="replace")).hexdigest()

    conf_range = (0.0, 0.0)
    if confidences:
        conf_range = (min(confidences), max(confidences))

    entry = AuditEntry(
        timestamp=datetime.now(UTC).isoformat(),
        action=action,
        input_hash=input_hash,
        entity_count=entity_count,
        resolved_count=resolved_count,
        pii_count=pii_count,
        confidence_range=conf_range,
        match_reasons=match_reasons or [],
        processing_time_ms=elapsed_ms,
    )
    _audit_log.append(entry)
    return entry
