# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""DuckDB reference store for canonical local entity state."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime
from typing import Any

from arche.runtime._models import DecisionReceipt, Entity, Evidence, Observation


class DuckDBStore:
    """A transaction-safe, local implementation of :class:`ArcheStore`."""

    def __init__(self, database: str) -> None:
        try:
            import duckdb
        except ImportError as exc:  # pragma: no cover - depends on installation
            raise ImportError(
                "Arche's DuckDB runtime requires the [runtime] extra. Install with: "
                "pip install arche-core[runtime]"
            ) from exc

        self._connection = duckdb.connect(database=database)

    def ensure_schema(self) -> None:
        """Create the M0 canonical tables if they do not yet exist."""
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS arche_entities (
                entity_id VARCHAR PRIMARY KEY,
                entity_type VARCHAR NOT NULL,
                identity_unit VARCHAR NOT NULL,
                created_at VARCHAR NOT NULL,
                status VARCHAR NOT NULL
            )
            """
        )
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS arche_observations (
                observation_id VARCHAR PRIMARY KEY,
                source_id VARCHAR NOT NULL,
                source_record_id VARCHAR,
                recorded_at VARCHAR NOT NULL,
                content_hash VARCHAR NOT NULL
            )
            """
        )
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS arche_evidence (
                evidence_id VARCHAR PRIMARY KEY,
                observation_id VARCHAR NOT NULL,
                kind VARCHAR NOT NULL,
                supports VARCHAR NOT NULL,
                provenance JSON NOT NULL
            )
            """
        )
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS arche_decisions (
                decision_id VARCHAR PRIMARY KEY,
                identity_result VARCHAR NOT NULL,
                action VARCHAR NOT NULL,
                evidence_ids JSON NOT NULL,
                raw_score DOUBLE,
                probability DOUBLE,
                policy_pin VARCHAR,
                schema_pin VARCHAR,
                created_at VARCHAR NOT NULL
            )
            """
        )

    def write_entities(self, entities: Iterable[Entity]) -> None:
        """Write stable entity identities in one transaction."""
        self._write_many(
            """
            INSERT INTO arche_entities VALUES (?, ?, ?, ?, ?)
            """,
            [
                (
                    entity.entity_id,
                    entity.entity_type,
                    entity.identity_unit,
                    _timestamp(entity.created_at),
                    entity.status,
                )
                for entity in entities
            ],
        )

    def get_entity(self, entity_id: str) -> Entity | None:
        """Load one entity without reconstructing it from claims."""
        row = self._connection.execute(
            "SELECT entity_id, entity_type, identity_unit, created_at, status "
            "FROM arche_entities WHERE entity_id = ?",
            [entity_id],
        ).fetchone()
        if row is None:
            return None
        return Entity(*row[:3], created_at=_parse_timestamp(row[3]), status=row[4])

    def write_observations(self, observations: Iterable[Observation]) -> None:
        """Write immutable observations in one transaction."""
        self._write_many(
            """
            INSERT INTO arche_observations VALUES (?, ?, ?, ?, ?)
            """,
            [
                (
                    observation.observation_id,
                    observation.source_id,
                    observation.source_record_id,
                    _timestamp(observation.recorded_at),
                    observation.content_hash,
                )
                for observation in observations
            ],
        )

    def get_observation(self, observation_id: str) -> Observation | None:
        """Load one immutable observation by identifier."""
        row = self._connection.execute(
            "SELECT observation_id, source_id, source_record_id, recorded_at, content_hash "
            "FROM arche_observations WHERE observation_id = ?",
            [observation_id],
        ).fetchone()
        if row is None:
            return None
        return Observation(*row[:3], recorded_at=_parse_timestamp(row[3]), content_hash=row[4])

    def write_evidence(self, evidence: Iterable[Evidence]) -> None:
        """Write evidence and its provenance in one transaction."""
        self._write_many(
            """
            INSERT INTO arche_evidence VALUES (?, ?, ?, ?, ?)
            """,
            [
                (
                    item.evidence_id,
                    item.observation_id,
                    item.kind,
                    item.supports,
                    _json(item.provenance),
                )
                for item in evidence
            ],
        )

    def get_evidence(self, evidence_id: str) -> Evidence | None:
        """Load one provenance-backed evidence item."""
        row = self._connection.execute(
            "SELECT evidence_id, observation_id, kind, supports, provenance "
            "FROM arche_evidence WHERE evidence_id = ?",
            [evidence_id],
        ).fetchone()
        if row is None:
            return None
        return Evidence(*row[:4], provenance=_mapping(row[4]))

    def write_decisions(self, decisions: Iterable[DecisionReceipt]) -> None:
        """Write policy-bound decisions in one transaction."""
        self._write_many(
            """
            INSERT INTO arche_decisions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    decision.decision_id,
                    decision.identity_result,
                    decision.action,
                    _json(decision.evidence_ids),
                    decision.raw_score,
                    decision.probability,
                    decision.policy_pin,
                    decision.schema_pin,
                    _timestamp(decision.created_at),
                )
                for decision in decisions
            ],
        )

    def get_decision(self, decision_id: str) -> DecisionReceipt | None:
        """Load one decision receipt by its reproducible identifier."""
        row = self._connection.execute(
            "SELECT decision_id, identity_result, action, evidence_ids, created_at, raw_score, "
            "probability, policy_pin, schema_pin FROM arche_decisions WHERE decision_id = ?",
            [decision_id],
        ).fetchone()
        if row is None:
            return None
        return DecisionReceipt(
            decision_id=row[0],
            identity_result=row[1],
            action=row[2],
            evidence_ids=tuple(_json_value(row[3])),
            created_at=_parse_timestamp(row[4]),
            raw_score=row[5],
            probability=row[6],
            policy_pin=row[7],
            schema_pin=row[8],
        )

    def close(self) -> None:
        """Close the underlying local database connection."""
        self._connection.close()

    def _write_many(self, statement: str, rows: Sequence[tuple[Any, ...]]) -> None:
        """Execute one immutable batch atomically."""
        if not rows:
            return
        self._connection.execute("BEGIN TRANSACTION")
        try:
            self._connection.executemany(statement, rows)
        except Exception:
            self._connection.execute("ROLLBACK")
            raise
        self._connection.execute("COMMIT")


def _json(value: object) -> str:
    """Encode a deterministic JSON payload for DuckDB's JSON column."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _json_value(value: object) -> object:
    """Decode DuckDB JSON values regardless of driver return representation."""
    return json.loads(value) if isinstance(value, str) else value


def _mapping(value: object) -> Mapping[str, str]:
    """Return decoded provenance as a typed mapping."""
    decoded = _json_value(value)
    if not isinstance(decoded, dict):
        raise TypeError("stored evidence provenance is not a JSON object")
    return {str(key): str(item) for key, item in decoded.items()}


def _timestamp(value: datetime) -> str:
    """Persist a timestamp without a driver-specific timezone dependency."""
    return value.isoformat()


def _parse_timestamp(value: str) -> datetime:
    """Reconstruct the timestamp representation written by :func:`_timestamp`."""
    return datetime.fromisoformat(value)
