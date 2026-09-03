# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""DuckDB reference store for canonical local entity state."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime
from typing import Any

from arche.runtime._models import (
    ActionObservation,
    CaseEvent,
    Claim,
    Contradiction,
    DecisionReceipt,
    Entity,
    EntityRelation,
    Evidence,
    EvidenceAction,
    EvidenceGap,
    Observation,
    OpenQuestion,
    ResolutionCase,
    ResolutionIntent,
    ResolutionRun,
)


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
                content_hash VARCHAR NOT NULL,
                provenance JSON NOT NULL DEFAULT '{}'
            )
            """
        )
        self._connection.execute(
            "ALTER TABLE arche_observations ADD COLUMN IF NOT EXISTS provenance JSON DEFAULT '{}'"
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
                provenance JSON NOT NULL DEFAULT '{}',
                created_at VARCHAR NOT NULL
            )
            """
        )
        self._connection.execute(
            "ALTER TABLE arche_decisions ADD COLUMN IF NOT EXISTS provenance JSON DEFAULT '{}'"
        )
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS arche_resolution_runs (
                run_id VARCHAR PRIMARY KEY,
                resolver VARCHAR NOT NULL,
                created_at VARCHAR NOT NULL,
                candidate_pairs INTEGER NOT NULL,
                emitted_decisions INTEGER NOT NULL,
                match_count INTEGER NOT NULL,
                review_count INTEGER NOT NULL,
                unsurfaced_pairs INTEGER NOT NULL,
                provenance JSON NOT NULL
            )
            """
        )
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS arche_resolution_cases (
                case_id VARCHAR PRIMARY KEY,
                question VARCHAR NOT NULL,
                observation_ids JSON NOT NULL,
                candidate_entity_ids JSON NOT NULL,
                opened_at VARCHAR NOT NULL,
                status VARCHAR NOT NULL,
                uncertainty JSON NOT NULL,
                evidence_gaps JSON NOT NULL DEFAULT '[]',
                intent JSON DEFAULT 'null'
            )
            """
        )
        self._connection.execute(
            "ALTER TABLE arche_resolution_cases "
            "ADD COLUMN IF NOT EXISTS evidence_gaps JSON DEFAULT '[]'"
        )
        self._connection.execute(
            "ALTER TABLE arche_resolution_cases ADD COLUMN IF NOT EXISTS intent JSON DEFAULT 'null'"
        )
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS arche_evidence_actions (
                action_id VARCHAR PRIMARY KEY,
                case_id VARCHAR NOT NULL,
                action_type VARCHAR NOT NULL,
                source_id VARCHAR NOT NULL,
                permitted_at VARCHAR NOT NULL,
                policy_pin VARCHAR NOT NULL,
                max_cost DOUBLE,
                provenance JSON NOT NULL
            )
            """
        )
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS arche_action_observations (
                action_id VARCHAR PRIMARY KEY,
                observation_id VARCHAR NOT NULL,
                recorded_at VARCHAR NOT NULL
            )
            """
        )
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS arche_claims (
                claim_id VARCHAR PRIMARY KEY,
                entity_id VARCHAR NOT NULL,
                predicate VARCHAR NOT NULL,
                value_ref VARCHAR NOT NULL,
                evidence_ids JSON NOT NULL,
                asserted_at VARCHAR NOT NULL,
                status VARCHAR NOT NULL,
                provenance JSON NOT NULL
            )
            """
        )
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS arche_contradictions (
                contradiction_id VARCHAR PRIMARY KEY,
                entity_id VARCHAR NOT NULL,
                claim_ids JSON NOT NULL,
                reason VARCHAR NOT NULL,
                detected_at VARCHAR NOT NULL,
                status VARCHAR NOT NULL
            )
            """
        )
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS arche_relations (
                relation_id VARCHAR PRIMARY KEY,
                subject_entity_id VARCHAR NOT NULL,
                predicate VARCHAR NOT NULL,
                object_entity_id VARCHAR NOT NULL,
                evidence_ids JSON NOT NULL,
                asserted_at VARCHAR NOT NULL,
                status VARCHAR NOT NULL
            )
            """
        )
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS arche_open_questions (
                question_id VARCHAR PRIMARY KEY,
                entity_id VARCHAR NOT NULL,
                question VARCHAR NOT NULL,
                opened_at VARCHAR NOT NULL,
                case_id VARCHAR,
                status VARCHAR NOT NULL
            )
            """
        )
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS arche_case_events (
                event_id VARCHAR PRIMARY KEY,
                case_id VARCHAR NOT NULL,
                event_type VARCHAR NOT NULL,
                recorded_at VARCHAR NOT NULL,
                reference_ids JSON NOT NULL,
                provenance JSON NOT NULL
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
            INSERT INTO arche_observations VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    observation.observation_id,
                    observation.source_id,
                    observation.source_record_id,
                    _timestamp(observation.recorded_at),
                    observation.content_hash,
                    _json(observation.provenance),
                )
                for observation in observations
            ],
        )

    def get_observation(self, observation_id: str) -> Observation | None:
        """Load one immutable observation by identifier."""
        row = self._connection.execute(
            "SELECT observation_id, source_id, source_record_id, recorded_at, content_hash, "
            "provenance "
            "FROM arche_observations WHERE observation_id = ?",
            [observation_id],
        ).fetchone()
        if row is None:
            return None
        return Observation(
            *row[:3],
            recorded_at=_parse_timestamp(row[3]),
            content_hash=row[4],
            provenance=_mapping(row[5]),
        )

    def write_evidence(self, evidence: Iterable[Evidence]) -> None:
        """Write evidence and its provenance in one transaction."""
        evidence_list = list(evidence)
        for item in evidence_list:
            if self.get_observation(item.observation_id) is None:
                raise ValueError(
                    f"observation {item.observation_id!r} does not exist; persist "
                    "an Observation before deriving Evidence from it"
                )
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
                for item in evidence_list
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
        decision_list = list(decisions)
        for decision in decision_list:
            for evidence_id in decision.evidence_ids:
                if self.get_evidence(evidence_id) is None:
                    raise ValueError(
                        f"evidence {evidence_id!r} does not exist; persist Evidence "
                        "before writing a decision receipt"
                    )
        self._write_many(
            """
            INSERT INTO arche_decisions (
                decision_id, identity_result, action, evidence_ids, raw_score,
                probability, policy_pin, schema_pin, provenance, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    _json(decision.provenance),
                    _timestamp(decision.created_at),
                )
                for decision in decision_list
            ],
        )

    def get_decision(self, decision_id: str) -> DecisionReceipt | None:
        """Load one decision receipt by its reproducible identifier."""
        row = self._connection.execute(
            "SELECT decision_id, identity_result, action, evidence_ids, created_at, raw_score, "
            "probability, policy_pin, schema_pin, provenance "
            "FROM arche_decisions WHERE decision_id = ?",
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
            provenance=_mapping(row[9]),
        )

    def write_resolution_runs(self, runs: Iterable[ResolutionRun]) -> None:
        """Write resolver-run metrics in one transaction."""
        self._write_many(
            """
            INSERT INTO arche_resolution_runs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    run.run_id,
                    run.resolver,
                    _timestamp(run.created_at),
                    run.candidate_pairs,
                    run.emitted_decisions,
                    run.match_count,
                    run.review_count,
                    run.unsurfaced_pairs,
                    _json(run.provenance),
                )
                for run in runs
            ],
        )

    def get_resolution_run(self, run_id: str) -> ResolutionRun | None:
        """Load one resolver-run metric record by identifier."""
        row = self._connection.execute(
            "SELECT run_id, resolver, created_at, candidate_pairs, emitted_decisions, "
            "match_count, review_count, unsurfaced_pairs, provenance "
            "FROM arche_resolution_runs WHERE run_id = ?",
            [run_id],
        ).fetchone()
        if row is None:
            return None
        return ResolutionRun(
            run_id=row[0],
            resolver=row[1],
            created_at=_parse_timestamp(row[2]),
            candidate_pairs=row[3],
            emitted_decisions=row[4],
            match_count=row[5],
            review_count=row[6],
            unsurfaced_pairs=row[7],
            provenance=_mapping(row[8]),
        )

    def write_resolution_cases(self, cases: Iterable[ResolutionCase]) -> None:
        """Write unresolved cases in one transaction."""
        case_list = list(cases)
        for case in case_list:
            for observation_id in case.observation_ids:
                if self.get_observation(observation_id) is None:
                    raise ValueError(
                        f"observation {observation_id!r} does not exist; persist "
                        "case observations before opening a resolution case"
                    )
        self._write_many(
            """
            INSERT INTO arche_resolution_cases (
                case_id, question, observation_ids, candidate_entity_ids, opened_at,
                status, uncertainty, evidence_gaps, intent
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    case.case_id,
                    case.question,
                    _json(case.observation_ids),
                    _json(case.candidate_entity_ids),
                    _timestamp(case.opened_at),
                    case.status,
                    _json(case.uncertainty),
                    _json(
                        [
                            {
                                "field": gap.field,
                                "reason": gap.reason,
                                "candidate_entity_ids": gap.candidate_entity_ids,
                                "priority": gap.priority,
                                "permitted_action_types": gap.permitted_action_types,
                            }
                            for gap in case.evidence_gaps
                        ]
                    ),
                    _intent(case.intent),
                )
                for case in case_list
            ],
        )

    def get_resolution_case(self, case_id: str) -> ResolutionCase | None:
        """Load one unresolved case by identifier."""
        row = self._connection.execute(
            "SELECT case_id, question, observation_ids, candidate_entity_ids, opened_at, "
            "status, uncertainty, evidence_gaps, intent "
            "FROM arche_resolution_cases WHERE case_id = ?",
            [case_id],
        ).fetchone()
        if row is None:
            return None
        return ResolutionCase(
            case_id=row[0],
            question=row[1],
            observation_ids=tuple(_json_value(row[2])),
            candidate_entity_ids=tuple(_json_value(row[3])),
            opened_at=_parse_timestamp(row[4]),
            status=row[5],
            uncertainty=_mapping(row[6]),
            evidence_gaps=_evidence_gaps(row[7]),
            intent=_resolution_intent(row[8]),
        )

    def write_evidence_actions(self, actions: Iterable[EvidenceAction]) -> None:
        """Write case-bound policy permissions in one transaction."""
        action_list = list(actions)
        for action in action_list:
            if self.get_resolution_case(action.case_id) is None:
                raise ValueError(
                    f"resolution case {action.case_id!r} does not exist; persist "
                    "the case before permitting an evidence action"
                )
        self._write_many(
            """
            INSERT INTO arche_evidence_actions VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    action.action_id,
                    action.case_id,
                    action.action_type,
                    action.source_id,
                    _timestamp(action.permitted_at),
                    action.policy_pin,
                    action.max_cost,
                    _json(action.provenance),
                )
                for action in action_list
            ],
        )

    def get_evidence_action(self, action_id: str) -> EvidenceAction | None:
        """Load one permitted evidence action by identifier."""
        row = self._connection.execute(
            "SELECT action_id, case_id, action_type, source_id, permitted_at, policy_pin, "
            "max_cost, provenance FROM arche_evidence_actions WHERE action_id = ?",
            [action_id],
        ).fetchone()
        if row is None:
            return None
        return EvidenceAction(
            action_id=row[0],
            case_id=row[1],
            action_type=row[2],
            source_id=row[3],
            permitted_at=_parse_timestamp(row[4]),
            policy_pin=row[5],
            max_cost=row[6],
            provenance=_mapping(row[7]),
        )

    def list_evidence_actions(self, case_id: str) -> tuple[EvidenceAction, ...]:
        """Load policy-permitted actions for one case in stable order."""
        rows = self._connection.execute(
            "SELECT action_id, case_id, action_type, source_id, permitted_at, policy_pin, "
            "max_cost, provenance FROM arche_evidence_actions WHERE case_id = ? "
            "ORDER BY action_id",
            [case_id],
        ).fetchall()
        return tuple(
            EvidenceAction(
                action_id=row[0],
                case_id=row[1],
                action_type=row[2],
                source_id=row[3],
                permitted_at=_parse_timestamp(row[4]),
                policy_pin=row[5],
                max_cost=row[6],
                provenance=_mapping(row[7]),
            )
            for row in rows
        )

    def write_action_observations(self, links: Iterable[ActionObservation]) -> None:
        """Write permitted action outputs in one transaction."""
        link_list = list(links)
        for link in link_list:
            action = self.get_evidence_action(link.action_id)
            if action is None:
                raise ValueError(
                    f"evidence action {link.action_id!r} is not permitted; persist "
                    "the action before linking its output"
                )
            observation = self.get_observation(link.observation_id)
            if observation is None:
                raise ValueError(
                    f"observation {link.observation_id!r} does not exist; tool "
                    "results must be recorded as Observations first"
                )
            if observation.source_id != action.source_id:
                raise ValueError(
                    f"observation source {observation.source_id!r} does not match "
                    f"permitted action source {action.source_id!r}"
                )
        self._write_many(
            """
            INSERT INTO arche_action_observations VALUES (?, ?, ?)
            """,
            [
                (link.action_id, link.observation_id, _timestamp(link.recorded_at))
                for link in link_list
            ],
        )

    def get_action_observation(self, action_id: str) -> ActionObservation | None:
        """Load the Observation yielded by one evidence action, if recorded."""
        row = self._connection.execute(
            "SELECT action_id, observation_id, recorded_at "
            "FROM arche_action_observations WHERE action_id = ?",
            [action_id],
        ).fetchone()
        if row is None:
            return None
        return ActionObservation(
            action_id=row[0],
            observation_id=row[1],
            recorded_at=_parse_timestamp(row[2]),
        )

    def write_claims(self, claims: Iterable[Claim]) -> None:
        """Write evidence-backed entity claims in one transaction."""
        claim_list = list(claims)
        for claim in claim_list:
            self._require_entity(claim.entity_id)
            self._require_evidence(claim.evidence_ids)
        self._write_many(
            """
            INSERT INTO arche_claims VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    claim.claim_id,
                    claim.entity_id,
                    claim.predicate,
                    claim.value_ref,
                    _json(claim.evidence_ids),
                    _timestamp(claim.asserted_at),
                    claim.status,
                    _json(claim.provenance),
                )
                for claim in claim_list
            ],
        )

    def list_claims(self, entity_id: str) -> tuple[Claim, ...]:
        """Load one entity's claims in assertion order."""
        rows = self._connection.execute(
            "SELECT claim_id, entity_id, predicate, value_ref, evidence_ids, asserted_at, "
            "status, provenance FROM arche_claims WHERE entity_id = ? "
            "ORDER BY asserted_at, claim_id",
            [entity_id],
        ).fetchall()
        return tuple(
            Claim(
                claim_id=row[0],
                entity_id=row[1],
                predicate=row[2],
                value_ref=row[3],
                evidence_ids=tuple(_json_value(row[4])),
                asserted_at=_parse_timestamp(row[5]),
                status=row[6],
                provenance=_mapping(row[7]),
            )
            for row in rows
        )

    def write_contradictions(self, contradictions: Iterable[Contradiction]) -> None:
        """Write unresolved claim conflicts in one transaction."""
        contradiction_list = list(contradictions)
        for contradiction in contradiction_list:
            self._require_entity(contradiction.entity_id)
            for claim_id in contradiction.claim_ids:
                claim = self._connection.execute(
                    "SELECT entity_id FROM arche_claims WHERE claim_id = ?", [claim_id]
                ).fetchone()
                if claim is None or claim[0] != contradiction.entity_id:
                    raise ValueError(
                        f"claim {claim_id!r} does not belong to entity {contradiction.entity_id!r}"
                    )
        self._write_many(
            """
            INSERT INTO arche_contradictions VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    item.contradiction_id,
                    item.entity_id,
                    _json(item.claim_ids),
                    item.reason,
                    _timestamp(item.detected_at),
                    item.status,
                )
                for item in contradiction_list
            ],
        )

    def list_contradictions(self, entity_id: str) -> tuple[Contradiction, ...]:
        """Load one entity's contradictions in detection order."""
        rows = self._connection.execute(
            "SELECT contradiction_id, entity_id, claim_ids, reason, detected_at, status "
            "FROM arche_contradictions WHERE entity_id = ? ORDER BY detected_at, contradiction_id",
            [entity_id],
        ).fetchall()
        return tuple(
            Contradiction(
                contradiction_id=row[0],
                entity_id=row[1],
                claim_ids=tuple(_json_value(row[2])),
                reason=row[3],
                detected_at=_parse_timestamp(row[4]),
                status=row[5],
            )
            for row in rows
        )

    def write_relations(self, relations: Iterable[EntityRelation]) -> None:
        """Write evidence-backed relations in one transaction."""
        relation_list = list(relations)
        for relation in relation_list:
            self._require_entity(relation.subject_entity_id)
            self._require_entity(relation.object_entity_id)
            self._require_evidence(relation.evidence_ids)
        self._write_many(
            """
            INSERT INTO arche_relations VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    relation.relation_id,
                    relation.subject_entity_id,
                    relation.predicate,
                    relation.object_entity_id,
                    _json(relation.evidence_ids),
                    _timestamp(relation.asserted_at),
                    relation.status,
                )
                for relation in relation_list
            ],
        )

    def list_relations(self, entity_id: str) -> tuple[EntityRelation, ...]:
        """Load relations incident to one entity in assertion order."""
        rows = self._connection.execute(
            "SELECT relation_id, subject_entity_id, predicate, object_entity_id, evidence_ids, "
            "asserted_at, status FROM arche_relations "
            "WHERE subject_entity_id = ? OR object_entity_id = ? ORDER BY asserted_at, relation_id",
            [entity_id, entity_id],
        ).fetchall()
        return tuple(
            EntityRelation(
                relation_id=row[0],
                subject_entity_id=row[1],
                predicate=row[2],
                object_entity_id=row[3],
                evidence_ids=tuple(_json_value(row[4])),
                asserted_at=_parse_timestamp(row[5]),
                status=row[6],
            )
            for row in rows
        )

    def write_open_questions(self, questions: Iterable[OpenQuestion]) -> None:
        """Write unresolved entity questions in one transaction."""
        question_list = list(questions)
        for question in question_list:
            self._require_entity(question.entity_id)
            if question.case_id is not None and self.get_resolution_case(question.case_id) is None:
                raise ValueError(
                    f"resolution case {question.case_id!r} does not exist; persist "
                    "the case before linking an entity open question"
                )
        self._write_many(
            """
            INSERT INTO arche_open_questions VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    question.question_id,
                    question.entity_id,
                    question.question,
                    _timestamp(question.opened_at),
                    question.case_id,
                    question.status,
                )
                for question in question_list
            ],
        )

    def list_open_questions(self, entity_id: str) -> tuple[OpenQuestion, ...]:
        """Load currently open questions for one entity."""
        rows = self._connection.execute(
            "SELECT question_id, entity_id, question, opened_at, case_id, status "
            "FROM arche_open_questions WHERE entity_id = ? AND status = 'open' "
            "ORDER BY opened_at, question_id",
            [entity_id],
        ).fetchall()
        return tuple(
            OpenQuestion(
                question_id=row[0],
                entity_id=row[1],
                question=row[2],
                opened_at=_parse_timestamp(row[3]),
                case_id=row[4],
                status=row[5],
            )
            for row in rows
        )

    def write_case_events(self, events: Iterable[CaseEvent]) -> None:
        """Write immutable case history events in one transaction."""
        event_list = list(events)
        for event in event_list:
            if self.get_resolution_case(event.case_id) is None:
                raise ValueError(
                    f"resolution case {event.case_id!r} does not exist; persist "
                    "the case before recording its history"
                )
        self._write_many(
            """
            INSERT INTO arche_case_events VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    event.event_id,
                    event.case_id,
                    event.event_type,
                    _timestamp(event.recorded_at),
                    _json(event.references),
                    _json(event.provenance),
                )
                for event in event_list
            ],
        )

    def list_case_events(self, case_id: str) -> tuple[CaseEvent, ...]:
        """Load one case's immutable event history in recorded order."""
        rows = self._connection.execute(
            "SELECT event_id, case_id, event_type, recorded_at, reference_ids, provenance "
            "FROM arche_case_events WHERE case_id = ? ORDER BY recorded_at, event_id",
            [case_id],
        ).fetchall()
        return tuple(
            CaseEvent(
                event_id=row[0],
                case_id=row[1],
                event_type=row[2],
                recorded_at=_parse_timestamp(row[3]),
                references=tuple(_json_value(row[4])),
                provenance=_mapping(row[5]),
            )
            for row in rows
        )

    def _require_entity(self, entity_id: str) -> None:
        """Require a stable entity before writing a dependent ledger record."""
        if self.get_entity(entity_id) is None:
            raise ValueError(
                f"entity {entity_id!r} does not exist; persist the entity before "
                "writing dependent ledger records"
            )

    def _require_evidence(self, evidence_ids: tuple[str, ...]) -> None:
        """Require all provenance evidence before writing a belief record."""
        for evidence_id in evidence_ids:
            if self.get_evidence(evidence_id) is None:
                raise ValueError(
                    f"evidence {evidence_id!r} does not exist; persist Evidence "
                    "before writing a ledger record"
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


def _mapping(value: object) -> Mapping[str, object]:
    """Return decoded provenance as a typed mapping."""
    decoded = _json_value(value)
    if not isinstance(decoded, dict):
        raise TypeError("stored evidence provenance is not a JSON object")
    return {str(key): item for key, item in decoded.items()}


def _evidence_gaps(value: object) -> tuple[EvidenceGap, ...]:
    """Decode persisted case gaps without accepting ambiguous control records."""
    decoded = _json_value(value)
    if not isinstance(decoded, list):
        raise TypeError("stored case evidence gaps are not a JSON array")
    gaps: list[EvidenceGap] = []
    for raw_gap in decoded:
        if not isinstance(raw_gap, dict):
            raise TypeError("stored case evidence gap is not a JSON object")
        field = raw_gap.get("field")
        reason = raw_gap.get("reason")
        candidate_ids = raw_gap.get("candidate_entity_ids", [])
        priority = raw_gap.get("priority", 0)
        action_types = raw_gap.get("permitted_action_types", [])
        if not isinstance(field, str) or not field:
            raise TypeError("stored case evidence gap field is not a non-empty string")
        if not isinstance(reason, str) or not reason:
            raise TypeError("stored case evidence gap reason is not a non-empty string")
        if isinstance(candidate_ids, (str, bytes)) or not isinstance(candidate_ids, list):
            raise TypeError("stored case evidence gap candidate IDs are not an array")
        if not all(isinstance(candidate_id, str) for candidate_id in candidate_ids):
            raise TypeError("stored case evidence gap candidate IDs are not strings")
        if isinstance(action_types, (str, bytes)) or not isinstance(action_types, list):
            raise TypeError("stored case evidence gap action types are not an array")
        if not all(isinstance(action_type, str) for action_type in action_types):
            raise TypeError("stored case evidence gap action types are not strings")
        if isinstance(priority, bool) or not isinstance(priority, int):
            raise TypeError("stored case evidence gap priority is not an integer")
        gaps.append(EvidenceGap(field, reason, tuple(candidate_ids), priority, tuple(action_types)))
    return tuple(gaps)


def _intent(value: ResolutionIntent | None) -> str:
    """Encode a value-free case intent for durable planning."""
    if value is None:
        return "null"
    return _json(
        {
            "entity_type": value.entity_type,
            "operation": value.operation,
            "available_fields": value.available_fields,
            "policy_pin": value.policy_pin,
            "candidate_pairs": value.candidate_pairs,
        }
    )


def _resolution_intent(value: object) -> ResolutionIntent | None:
    """Decode a persisted structured intent without accepting raw records."""
    decoded = _json_value(value)
    if decoded is None:
        return None
    if not isinstance(decoded, dict):
        raise TypeError("stored case intent is not a JSON object")
    entity_type = decoded.get("entity_type")
    operation = decoded.get("operation")
    available_fields = decoded.get("available_fields")
    policy_pin = decoded.get("policy_pin")
    candidate_pairs = decoded.get("candidate_pairs")
    if not all(isinstance(item, str) and item for item in (entity_type, operation, policy_pin)):
        raise TypeError("stored case intent needs entity type, operation, and policy pin")
    if isinstance(available_fields, (str, bytes)) or not isinstance(available_fields, list):
        raise TypeError("stored case intent available fields are not an array")
    if not all(isinstance(field, str) and field for field in available_fields):
        raise TypeError("stored case intent available fields are not non-empty strings")
    if candidate_pairs is not None and (
        isinstance(candidate_pairs, bool) or not isinstance(candidate_pairs, int)
    ):
        raise TypeError("stored case intent candidate pairs are not an integer")
    return ResolutionIntent(
        entity_type,
        operation,
        tuple(available_fields),
        policy_pin,
        candidate_pairs,
    )


def _timestamp(value: datetime) -> str:
    """Persist a timestamp without a driver-specific timezone dependency."""
    return value.isoformat()


def _parse_timestamp(value: str) -> datetime:
    """Reconstruct the timestamp representation written by :func:`_timestamp`."""
    return datetime.fromisoformat(value)
