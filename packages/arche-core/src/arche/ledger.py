# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""The ledger: where a decision goes so it can be found again.

Every verb in :mod:`arche.resolve` already returns a receipt whose
``decision_id`` is a content hash over the evidence and the pinned versions.
What none of them had was somewhere to put it. This module is that place.

::

    import arche

    ledger = arche.attach("duckdb:///suppliers.duckdb")
    r = arche.compare(text_a, text_b, entity="person", jurisdiction="NG",
                      backend="regex", store=ledger)

    ledger.decision(r.decision_id)   # the receipt as recorded, plus its inputs
    ledger.replay(r.decision_id)     # re-run it: reproduced, or what moved
    ledger.explain(r.decision_id)    # supporting / refuting / missing, by field
    ledger.entities()                # records the decisions have linked together
    ledger.path(rec_a, rec_b)        # the chain of decisions that makes two records one
    ledger.cases()                   # what is still open, and what would settle it
    ledger.observe(record_id, {...}) # add evidence, re-decide, supersede
    ledger.resolve(record, entity_type="person")   # a new record against the entities
    ledger.read("suppliers")         # rows from a table or file the same DuckDB can see

A ``decision_id`` is the handle to the explanation facility. Everything above
that takes one gives back a step in the reasoning: what was compared, what
agreed, what did not, what was absent, which versions were pinned, and -- for
two records that were never compared directly -- the chain of decisions
through other records that makes them one entity. Users of a resolution
system look at what was linked and ask why; this is the answer, and it is
addressed by the id rather than by a log line.

The ledger records; it does not gate. A decision that says ``same_entity``
links two records into one entity here because the engine said so, and the
``action`` axis (``merge`` / ``hold``) is kept beside it for the caller who
decides what to do about that. Authority over side effects stays with the
caller, human or agent.

**Five tables**, all local, in the user's own DuckDB file:

``records``      the inputs as given, content-addressed. Replay needs them.
``decisions``    one row per receipt, with its pins and the call that made it.
``runs``         the two lists behind a batch verb, so an edge can be replayed.
``memberships``  record -> entity. Derived from linked decisions; rebuildable.
``events``       append-only: what was recorded, linked, merged, superseded.

Storing the inputs is a deliberate choice. The file is the caller's, on the
caller's disk, like ``decisions.json`` beside their PDFs. A hashed mode that
keeps only ids can follow when someone needs it.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from arche.ids import content_hash

#: Identity outcomes that link two records into one entity. ``compare`` says
#: ``same_entity``; the batch verbs say ``match``. ``review`` never links.
LINKED = frozenset({"same_entity", "match"})

#: Fields whose absence is worth naming when a pair is left open.
_IDENTITY_FIELDS = (
    "national_id", "registration_id", "phone", "email", "dob", "name", "address",
)

#: Call arguments that only make sense for the text path and must not reach the
#: structured path when a stored record is re-run from its attributes.
_TEXT_ONLY_ARGS = ("backend", "source_a", "source_b")


# ---------------------------------------------------------------------------
# what the ledger hands back
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Record:
    """One input as it was given: a dict, or a piece of text and what was read from it."""

    record_id: str
    entity_type: str
    source: str
    caller_id: str | None
    attributes: dict[str, Any]
    text: str | None
    recorded_at: datetime

    def as_input(self) -> Any:
        """The value to hand back to the verb that decided over this record."""
        return self.text if self.text is not None else dict(self.attributes)


@dataclass(frozen=True)
class Decision:
    """A receipt as recorded, with the call that produced it."""

    decision_id: str
    verb: str
    record_a: str
    record_b: str
    identity: str
    action: str
    score: float
    factors: dict[str, float]
    explanation: str
    evidence: dict[str, Any]
    pins: dict[str, Any]
    call: dict[str, Any]
    run_id: str | None
    recorded_at: datetime
    supersedes: str | None = None
    superseded_by: str | None = None

    @property
    def linked(self) -> bool:
        """Did this decision say the two records are one entity?"""
        return self.identity in LINKED

    @property
    def open(self) -> bool:
        """Is this the current word on the pair, and is that word ``review``?"""
        return self.identity == "review" and self.superseded_by is None


@dataclass(frozen=True)
class Replay:
    """What happened when a recorded decision was made again."""

    decision_id: str
    reproduced: bool
    then: Decision
    now: dict[str, Any]
    changed: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class EntityView:
    """The records a set of linked decisions hold together, and what they agree on."""

    entity_id: str
    entity_type: str
    records: tuple[Record, ...]
    #: attribute -> the one value every record that carries it agrees on.
    shared: dict[str, Any]
    #: attribute -> the distinct values the records disagree about.
    conflicts: dict[str, list[Any]]
    #: every linking decision between members, oldest first
    decision_ids: tuple[str, ...]
    #: ``"direct"`` when every pair of members was itself decided ``same``;
    #: ``"transitive"`` when at least one pair is linked only through a third
    #: record. A matched B and B matched C says nothing about A and C, and a
    #: transitive entity is the classic way two different things end up as one.
    #: The same word ``dedupe()`` uses for its clusters.
    held_together_by: str = "direct"
    #: Records whose removal would split the entity: the association graph's
    #: articulation points. Empty for a clique. A seventeen-record entity held
    #: together by one record is a different object from a seventeen-record
    #: clique, and this is where the difference shows.
    weak_links: tuple[str, ...] = ()
    #: Decisions whose removal would split the entity (graph bridges). One
    #: receipt carrying that much weight is the one to re-check first.
    bridges: tuple[str, ...] = ()

    @property
    def held(self) -> str:
        """Older spelling of :attr:`held_together_by`."""
        return self.held_together_by

    @property
    def record_ids(self) -> tuple[str, ...]:
        return tuple(record.record_id for record in self.records)


@dataclass(frozen=True)
class Case:
    """A pair the engine declined to settle, and what would settle it."""

    decision: Decision
    record_a: Record
    record_b: Record
    would_resolve: list[str]
    why: dict[str, Any]


@dataclass(frozen=True)
class Resolution:
    """A new record, resolved against the entities the ledger already holds.

    ``verdict`` is entity-level:

    ``found``      one entity's members matched and nothing contradicts it;
                   the record is linked into that entity.
    ``review``     nothing matched outright; the pairs that came close are
                   recorded as ``review`` and appear in :meth:`Ledger.cases`.
    ``ambiguous``  members of two or more entities matched. Either the newcomer
                   bridges entities that are really one, or something is wrong;
                   the decisions are recorded, the link is withheld.
    ``conflict``   a member matched but the record contradicts an identifier
                   the entity agrees on. Recorded, withheld.
    ``not_found``  nothing surfaced. The record is stored on its own.
    """

    verdict: str
    record_id: str
    entity: EntityView | None
    #: pairwise decisions recorded for this resolution, best first
    decisions: tuple[Decision, ...]
    #: entity_id -> the best pairwise identity and score among its members
    candidates: dict[str, dict[str, Any]]
    #: the record compared with the entity's undisputed attributes as one whole
    entity_evidence: dict[str, Any] | None
    #: identifier fields the entity shares that the record contradicts
    conflicts: dict[str, dict[str, Any]]
    would_resolve: list[str]
    note: str


@dataclass(frozen=True)
class Event:
    """One line of the append-only history."""

    event_id: str
    kind: str
    at: datetime
    refs: dict[str, Any]
    note: str


# ---------------------------------------------------------------------------
# the ledger
# ---------------------------------------------------------------------------


class Ledger:
    """A local, content-addressed store of decisions and the records behind them."""

    def __init__(self, database: str) -> None:
        try:
            import duckdb
        except ImportError as exc:  # pragma: no cover - depends on installation
            raise ImportError(
                "arche.attach needs DuckDB. Install with: pip install 'arche-core[ledger]'"
            ) from exc
        self._db = duckdb.connect(database=database)
        self.ensure_schema()

    # ------------------------------------------------------------ lifecycle

    def ensure_schema(self) -> None:
        """Create the five tables if absent. Safe to call any number of times."""
        for statement in _SCHEMA:
            self._db.execute(statement)

    def close(self) -> None:
        self._db.close()

    def __enter__(self) -> Ledger:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # ------------------------------------------------------------ recording

    def record_compare(
        self,
        receipt: Any,
        a: Any,
        b: Any,
        *,
        call: Mapping[str, Any],
        source: str = "compare",
        caller_ids: tuple[str | None, str | None] = (None, None),
        supersedes: str | None = None,
        record_ids: tuple[str | None, str | None] = (None, None),
    ) -> Decision:
        """Record one pairwise receipt and the two inputs it was made from.

        Idempotent on ``decision_id``: recording the same receipt twice writes
        nothing new and returns the existing row. ``record_ids`` names a side
        whose record the ledger already holds, so a re-decision over a stored
        record's attributes joins the record it came from rather than minting
        a second one with a different content address.
        """
        call_record, unreplayable = _call_record(call)
        entity_type = str(call_record.get("entity") or "person")
        record_a = (self.record(record_ids[0]) if record_ids[0]
                    else self._record(entity_type, a, receipt.reference_a, source, caller_ids[0]))
        record_b = (self.record(record_ids[1]) if record_ids[1]
                    else self._record(entity_type, b, receipt.reference_b, source, caller_ids[1]))
        existing = self._decision_or_none(receipt.decision_id)
        if existing is not None:
            return existing
        if unreplayable:
            call_record["_unreplayable"] = unreplayable
        evidence = {
            "basis": receipt.basis,
            "gate": dict(receipt.gate),
            "vetoes": dict(receipt.vetoes),
            "field_weights": dict(receipt.field_weights),
            "reference_id_a": receipt.reference_id_a,
            "reference_id_b": receipt.reference_id_b,
            "entity_id": receipt.entity_id,
            "jurisdiction": receipt.jurisdiction,
        }
        decision = Decision(
            decision_id=receipt.decision_id,
            verb="compare",
            record_a=record_a.record_id,
            record_b=record_b.record_id,
            identity=receipt.identity,
            action=receipt.action,
            score=float(receipt.score),
            factors={k: float(v) for k, v in dict(receipt.factors).items()
                     if isinstance(v, (int, float))},
            explanation=receipt.explanation,
            evidence=evidence,
            pins=dict(receipt.pins),
            call=call_record,
            run_id=None,
            recorded_at=_now(),
            supersedes=supersedes,
        )
        self._write_decision(decision)
        return decision

    def record_batch(
        self,
        result: Mapping[str, Any],
        list_a: list[Mapping[str, Any]],
        list_b: list[Mapping[str, Any]],
        *,
        call: Mapping[str, Any],
        verb: str = "reconcile",
        link: bool = True,
    ) -> list[Decision]:
        """Record every edge of a ``reconcile`` / ``dedupe`` / ``find`` result.

        ``link=False`` records the decisions exactly as the engine issued them
        but does not union any records: the caller has an entity-level reason
        to withhold, and says so in an event of its own.

        The two lists are stored as a *run* so any edge can later be replayed
        against exactly the lists it was scored within: a self-calibrated
        frequency table is a property of the batch, not of the pair.

        Written in bulk. A DuckDB statement costs about a millisecond here and
        the per-edge path issued seven of them: 9 ms an edge, 21-28 s for a
        3,000-edge batch. This path does one existence query and one multi-row
        insert per table and resolves memberships with an in-memory union-find
        before writing them once: 0.8 ms an edge, 2.4 s for the same batch.
        """
        call_record, unreplayable = _call_record(call)
        if unreplayable:
            call_record["_unreplayable"] = unreplayable
        entity_type = str(call_record.get("entity") or "record")
        id_field = str(call_record.get("id_field", "id"))
        now = _now()

        def rows_for(records: list[Mapping[str, Any]], label: str) -> dict[str, Record]:
            out: dict[str, Record] = {}
            for position, row in enumerate(records):
                caller_id = str(row.get(id_field, position))
                if caller_id.startswith("rec:sha256:"):
                    # A row carrying a ledger record id as its id is that stored
                    # record, handed back to a verb: re-hashing it with the id
                    # inside would mint a second copy outside its entity.
                    existing = self._record_or_none(caller_id)
                    if existing is not None:
                        out[caller_id] = existing
                        continue
                attributes = _json_clean(dict(row))
                record_id = content_hash(
                    {"entity_type": entity_type, "attributes": attributes}, prefix="rec"
                )
                out[caller_id] = Record(record_id, entity_type, f"{verb}:{label}", caller_id,
                                        attributes, None, now)
            return out

        by_a = rows_for(list_a, "a")
        by_b = by_a if list_b is list_a else rows_for(list_b, "b")
        records = {r.record_id: r for r in [*by_a.values(), *by_b.values()]}
        pins = dict(result.get("pins", {}))
        run_id = f"run_{uuid4().hex}"

        # Build every decision first; nothing below touches the database until
        # the shape of the whole batch is known.
        built: list[Decision] = []
        for edge in result.get("matches", ()):
            a_id, b_id = str(edge["a_id"]), str(edge["b_id"])
            record_a, record_b = by_a[a_id].record_id, by_b[b_id].record_id
            if record_a == record_b:
                continue  # a record against itself says nothing about identity
            identity = str(edge["decision"])
            built.append(Decision(
                decision_id=str(edge["decision_id"]),
                verb=verb,
                record_a=record_a,
                record_b=record_b,
                identity=identity,
                action="merge" if identity == "match" else "hold",
                score=float(edge.get("score", 0.0)),
                factors={k: float(v) for k, v in dict(edge.get("evidence", {})).items()
                         if isinstance(v, (int, float))},
                explanation=_explain_edge(edge),
                evidence={
                    "a_id": a_id, "b_id": b_id,
                    "distinctive_max": edge.get("distinctive_max"),
                    **{k: v for k, v in edge.items()
                       if k in ("route", "retrieval_score", "refuted_by", "capped_by")},
                },
                pins=pins,
                call=call_record,
                run_id=run_id,
                recorded_at=now,
            ))

        self._db.execute("BEGIN TRANSACTION")
        try:
            known_records = self._existing("arche_records", "record_id", list(records))
            self._insert_rows("arche_records", [
                [r.record_id, r.entity_type, r.source, r.caller_id, _dump(r.attributes),
                 r.text, r.recorded_at.isoformat()]
                for rid, r in records.items() if rid not in known_records
            ])
            self._db.execute(
                "INSERT INTO arche_runs VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                [run_id, verb, _dump(call_record), _dump([r.record_id for r in by_a.values()]),
                 _dump([r.record_id for r in by_b.values()]), _dump(pins),
                 _dump(dict(result.get("blocking", {}))), now.isoformat()],
            )
            events = [_event_row("run_recorded", {"run_id": run_id, "verb": verb,
                                                  "edges": len(built)})]

            existing = {
                row[0]: _decision_from_row(row)
                for row in self._fetch_in("arche_decisions", "decision_id",
                                          [d.decision_id for d in built])
            }
            fresh = [d for d in built if d.decision_id not in existing]
            self._insert_rows("arche_decisions", [
                [d.decision_id, d.verb, d.record_a, d.record_b, d.identity, d.action, d.score,
                 _dump(d.factors), d.explanation, _dump(d.evidence), _dump(d.pins),
                 _dump(d.call), d.run_id, d.recorded_at.isoformat(), d.supersedes, None]
                for d in fresh
            ])
            events += [
                _event_row("decision_recorded", {
                    "decision_id": d.decision_id, "identity": d.identity,
                    "action": d.action, "verb": d.verb,
                })
                for d in fresh
            ]
            if link:
                events += self._link_many([d for d in fresh if d.linked], entity_type, now)
            self._insert_rows("arche_events", events)
        except Exception:
            self._db.execute("ROLLBACK")
            raise
        self._db.execute("COMMIT")
        return [existing.get(d.decision_id, d) for d in built]

    def _link_many(self, linked: list[Decision], entity_type: str, now: datetime) -> list[list]:
        """Union the records of many linking decisions at once; return the events.

        Same rules as :meth:`_link`, one query in and one write out: an entity
        that already exists in the store survives a merge with one created in
        this batch, and among two existing ones the first seen survives.
        """
        if not linked:
            return []
        involved = sorted({rid for d in linked for rid in (d.record_a, d.record_b)})
        member: dict[str, str] = {
            row[0]: row[1]
            for row in self._fetch_in("arche_memberships", "record_id", involved,
                                      columns="record_id, entity_id")
        }
        stored_entities = set(member.values())
        parent: dict[str, str] = {}

        def find(entity: str) -> str:
            while parent.get(entity, entity) != entity:
                entity = parent[entity]
            return entity

        new_members: dict[str, tuple[str, str]] = {}   # record -> (entity, decision_id)
        events: list[list] = []

        def current(record_id: str) -> str | None:
            entity = member.get(record_id) or (new_members.get(record_id) or (None,))[0]
            return find(entity) if entity else None

        for d in linked:
            a, b = current(d.record_a), current(d.record_b)
            if a is None and b is None:
                entity_id = f"ent_{uuid4().hex}"
                new_members[d.record_a] = (entity_id, d.decision_id)
                new_members[d.record_b] = (entity_id, d.decision_id)
                events.append(_event_row("entity_created", {
                    "entity_id": entity_id, "decision_id": d.decision_id,
                    "records": [d.record_a, d.record_b],
                }))
            elif a is None or b is None:
                entity_id = a or b
                newcomer = d.record_a if a is None else d.record_b
                new_members[newcomer] = (entity_id, d.decision_id)
                events.append(_event_row("record_linked", {
                    "entity_id": entity_id, "record_id": newcomer,
                    "decision_id": d.decision_id,
                }))
            elif a != b:
                kept, absorbed = (b, a) if (b in stored_entities and a not in stored_entities) \
                    else (a, b)
                parent[absorbed] = kept
                events.append(_event_row("entities_merged", {
                    "kept": kept, "absorbed": absorbed, "decision_id": d.decision_id,
                }, "two entities turned out to be one"))

        self._insert_rows("arche_memberships", [
            [record_id, find(entity), entity_type, decision_id, now.isoformat()]
            for record_id, (entity, decision_id) in new_members.items()
        ])
        for absorbed in stored_entities:
            kept = find(absorbed)
            if kept != absorbed:
                self._db.execute(
                    "UPDATE arche_memberships SET entity_id = ? WHERE entity_id = ?",
                    [kept, absorbed],
                )
        return events

    # -- bulk helpers ---------------------------------------------------------

    _CHUNK = 500

    def _existing(self, table: str, key: str, ids: list[str]) -> set[str]:
        return {row[0] for row in self._fetch_in(table, key, ids, columns=key)}

    def _fetch_in(self, table: str, key: str, ids: list[str], *,
                  columns: str = "*") -> list[tuple]:
        rows: list[tuple] = []
        for i in range(0, len(ids), self._CHUNK):
            chunk = ids[i:i + self._CHUNK]
            marks = ", ".join("?" for _ in chunk)
            rows += self._db.execute(
                f"SELECT {columns} FROM {table} WHERE {key} IN ({marks})", chunk
            ).fetchall()
        return rows

    def _insert_rows(self, table: str, rows: list[list]) -> None:
        if not rows:
            return
        width = len(rows[0])
        one = "(" + ", ".join("?" for _ in range(width)) + ")"
        for i in range(0, len(rows), self._CHUNK):
            chunk = rows[i:i + self._CHUNK]
            self._db.execute(
                f"INSERT INTO {table} VALUES " + ", ".join([one] * len(chunk)),
                [value for row in chunk for value in row],
            )

    # ------------------------------------------------------------ reading

    def decision(self, decision_id: str) -> Decision:
        """The receipt as recorded. Raises ``KeyError`` if the ledger never saw it."""
        found = self._decision_or_none(decision_id)
        if found is None:
            raise KeyError(f"no decision {decision_id!r} in this ledger")
        return found

    def record(self, record_id: str) -> Record:
        row = self._db.execute(
            "SELECT * FROM arche_records WHERE record_id = ?", [record_id]
        ).fetchone()
        if row is None:
            raise KeyError(f"no record {record_id!r} in this ledger")
        return _record_from_row(row)

    def history(self, record_id: str) -> tuple[Decision, ...]:
        """Every decision that touched a record, newest first."""
        rows = self._db.execute(
            "SELECT * FROM arche_decisions WHERE record_a = ? OR record_b = ? "
            "ORDER BY recorded_at DESC",
            [record_id, record_id],
        ).fetchall()
        return tuple(_decision_from_row(row) for row in rows)

    def explain(self, decision_id: str) -> dict[str, Any]:
        """Why a decision came out as it did, field by field.

        ``supporting`` are the fields that agreed, ``refuting`` the ones that
        disagreed or vetoed, ``missing`` the identifying fields neither record
        supplied. ``shared`` carries the agreed values themselves, because "the
        national id matched" is the claim and the id is the evidence.
        """
        decision = self.decision(decision_id)
        record_a, record_b = self.record(decision.record_a), self.record(decision.record_b)
        return _why(decision, record_a, record_b)

    def replay(self, decision_id: str) -> Replay:
        """Make the decision again with the engine installed now.

        ``reproduced`` is true when the new receipt carries the same
        ``decision_id`` byte for byte. When it does not, ``changed`` names every
        factor, pin and outcome that moved, which is the difference between
        "something changed" and knowing what.
        """
        then = self.decision(decision_id)
        if then.call.get("_unreplayable"):
            raise ValueError(
                f"decision {decision_id!r} was made with arguments the ledger could not "
                f"store ({', '.join(then.call['_unreplayable'])}); it can be re-verified "
                "from its signed receipt but not re-run from here"
            )
        now = self._rerun(then)
        changed = _diff(then, now)
        return Replay(
            decision_id=decision_id,
            reproduced=now["decision_id"] == decision_id,
            then=then,
            now=now,
            changed=changed,
        )

    def entity(self, entity_id: str) -> EntityView:
        rows = self._db.execute(
            "SELECT record_id, entity_type, decision_id FROM arche_memberships "
            "WHERE entity_id = ? ORDER BY linked_at",
            [entity_id],
        ).fetchall()
        if not rows:
            raise KeyError(f"no entity {entity_id!r} in this ledger")
        records = tuple(self.record(row[0]) for row in rows)
        shared, conflicts = _agreement(records)
        member_ids = [record.record_id for record in records]
        marks = ", ".join("?" for _ in member_ids)
        linked = self._db.execute(
            f"SELECT decision_id, record_a, record_b FROM arche_decisions "
            f"WHERE identity IN ('same_entity', 'match') "
            f"AND record_a IN ({marks}) AND record_b IN ({marks}) ORDER BY recorded_at",
            [*member_ids, *member_ids],
        ).fetchall()
        decided_pairs = {frozenset((row[1], row[2])) for row in linked}
        n = len(member_ids)
        weak_links: tuple[str, ...] = ()
        bridges: tuple[str, ...] = ()
        if len(decided_pairs) < n * (n - 1) // 2 and n > 2:
            import networkx as nx

            graph = nx.Graph()
            graph.add_nodes_from(member_ids)
            for decision_id, a, b in linked:
                graph.add_edge(a, b, decision_id=decision_id)
            weak_links = tuple(sorted(nx.articulation_points(graph)))
            bridges = tuple(sorted(graph.edges[a, b]["decision_id"] for a, b in nx.bridges(graph)))
        return EntityView(
            entity_id=entity_id,
            entity_type=rows[0][1],
            records=records,
            shared=shared,
            conflicts=conflicts,
            decision_ids=tuple(row[0] for row in linked),
            held_together_by="direct" if len(decided_pairs) >= n * (n - 1) // 2 else "transitive",
            weak_links=weak_links,
            bridges=bridges,
        )

    def entities(self, entity_type: str | None = None) -> list[EntityView]:
        """Every entity the linked decisions have built, largest first."""
        sql = "SELECT entity_id, COUNT(*) AS n FROM arche_memberships"
        params: list[Any] = []
        if entity_type is not None:
            sql += " WHERE entity_type = ?"
            params.append(entity_type)
        sql += " GROUP BY entity_id ORDER BY n DESC, entity_id"
        return [self.entity(row[0]) for row in self._db.execute(sql, params).fetchall()]

    def entity_of(self, record_id: str) -> str | None:
        """Which entity a record currently belongs to, if any decision linked it."""
        row = self._db.execute(
            "SELECT entity_id FROM arche_memberships WHERE record_id = ?", [record_id]
        ).fetchone()
        return row[0] if row else None

    def graph(self, entity_id: str | None = None):
        """The association graph: records as nodes, linking decisions as edges.

        A :class:`networkx.Graph`. Node attributes are ``caller_id`` and
        ``entity_type``; edge attributes are ``decision_id``, ``score`` and
        ``identity``. ``review`` decisions are not edges -- they never link --
        so a connected component of this graph is exactly one entity. Pass an
        ``entity_id`` for that entity's subgraph.
        """
        import networkx as nx

        if entity_id is None:
            member_rows = self._db.execute(
                "SELECT record_id, entity_id FROM arche_memberships"
            ).fetchall()
        else:
            member_rows = self._db.execute(
                "SELECT record_id, entity_id FROM arche_memberships WHERE entity_id = ?",
                [entity_id],
            ).fetchall()
        record_ids = [row[0] for row in member_rows]
        graph = nx.Graph()
        for row in self._fetch_in("arche_records", "record_id", record_ids,
                                  columns="record_id, caller_id, entity_type"):
            graph.add_node(row[0], caller_id=row[1], entity_type=row[2])
        if not record_ids:
            return graph
        marks = ", ".join("?" for _ in record_ids)
        edges = self._db.execute(
            f"SELECT decision_id, record_a, record_b, score, identity FROM arche_decisions "
            f"WHERE identity IN ('same_entity', 'match') AND superseded_by IS NULL "
            f"AND record_a IN ({marks}) AND record_b IN ({marks})",
            [*record_ids, *record_ids],
        ).fetchall()
        for decision_id, a, b, score, identity in edges:
            graph.add_edge(a, b, decision_id=decision_id, score=float(score), identity=identity)
        return graph

    def path(self, record_a: str, record_b: str) -> list[Decision]:
        """The chain of decisions that makes two records one entity.

        Empty when they are not in the same entity. One decision when they were
        compared and matched directly. Longer when they are linked only through
        other records -- the answer to "these two were never compared; why are
        they one thing?" Shortest chain first, ties broken by the highest
        scores along it, so the explanation offered is the strongest one.
        """
        import networkx as nx

        entity = self.entity_of(record_a)
        if entity is None or entity != self.entity_of(record_b):
            return []
        graph = self.graph(entity)
        try:
            # 1 - score as length: shortest in hops, then strongest in evidence.
            for _a, _b, data in graph.edges(data=True):
                data["length"] = 1.0 + (1.0 - data["score"]) * 1e-3
            nodes = nx.shortest_path(graph, record_a, record_b, weight="length")
        except nx.NetworkXNoPath:
            return []
        hops = zip(nodes, nodes[1:], strict=False)
        return [self.decision(graph.edges[a, b]["decision_id"]) for a, b in hops]

    def resolve(
        self,
        record: Mapping[str, Any] | str,
        *,
        entity_type: str,
        jurisdiction: str = "default",
        backend: str = "regex",
    ) -> Resolution:
        """Resolve a new record against the entities this ledger already holds.

        Transitive matching, as opposed to the transitive *equivalence* that
        ``entities()`` already provides: the record is compared with every
        stored record of its type (blocking applies), the pairwise decisions
        are grouped by the entity each candidate belongs to, and the verdict is
        made at the entity level. Two things the entity adds that a single
        pair cannot:

        * ``entity_evidence`` compares the record with the entity taken as a
          whole -- its attributes that no member disputes -- so an id one
          member holds and a phone another holds both count;
        * ``conflicts`` names identifier fields (``kind: id`` in the pack) the
          entity agrees on and the record contradicts. One member's name
          agreeing does not outweigh a different national id. Emails and
          addresses never block: people change them, which is the whole point
          of resolving across records.

        ``record`` is a dict, or text for the ``person`` pack, extracted with
        ``backend``. The decisions are recorded either way; the link is made
        only on ``found``.
        """
        from arche.resolve import ENTITY_PACKS, compare, reconcile

        if entity_type not in ENTITY_PACKS:
            raise ValueError(
                f"no entity pack named {entity_type!r}; have {', '.join(sorted(ENTITY_PACKS))}"
            )
        text: str | None = None
        if isinstance(record, str):
            text = record
            attrs = _extract_record(record, backend=backend)
        else:
            attrs = _json_clean(dict(record))
        attrs.pop("id", None)
        newcomer = _pack_fields(attrs)

        rows = self._db.execute(
            "SELECT record_id, attributes FROM arche_records WHERE entity_type = ?",
            [entity_type],
        ).fetchall()
        # Stored records keep the vocabulary they arrived in (`full_name` from a
        # text extraction, `name` from a spreadsheet); the pack reads one. Map,
        # and hand each row back under its own record id so nothing is re-stored.
        within = [{**_pack_fields(_load(row[1])), "id": row[0]} for row in rows]
        call = {"entity": entity_type, "id_field": "id"}
        if not within:
            stored = self._record(entity_type, attrs, None, "resolve", None)
            self._set_text(stored.record_id, text)
            return Resolution("not_found", stored.record_id, None, (), {}, None, {}, [],
                              "no records of this type in the ledger yet")

        result = reconcile([newcomer], within, **call)
        by_entity: dict[str, list[dict]] = {}
        loose: list[dict] = []
        for edge in result["matches"]:
            entity_id = self.entity_of(str(edge["b_id"]))
            (by_entity.setdefault(entity_id, []) if entity_id else loose).append(edge)

        candidates: dict[str, dict[str, Any]] = {}
        for entity_id, edges in by_entity.items():
            best = max(edges, key=lambda e: (e["decision"] == "match", e["score"]))
            candidates[entity_id] = {
                "identity": best["decision"], "score": float(best["score"]),
                "matched": sum(e["decision"] == "match" for e in edges),
                "review": sum(e["decision"] == "review" for e in edges),
                "members": len(edges),
            }
        matched = [e for e, c in candidates.items() if c["identity"] == "match"]
        loose_match = [e for e in loose if e["decision"] == "match"]

        id_fields = {c["field"] for c in ENTITY_PACKS[entity_type]
                     if c.get("kind") == "id" and c.get("field")}
        conflicts: dict[str, dict[str, Any]] = {}
        entity_evidence = None
        target: EntityView | None = None
        nearest = matched[0] if len(matched) == 1 else (
            max(candidates, key=lambda e: candidates[e]["score"])
            if candidates and not matched else None
        )
        if nearest is not None:
            target = self.entity(nearest)
            shared = _pack_fields(target.shared)
            for field_name in id_fields & set(shared):
                mine = newcomer.get(field_name)
                if mine not in (None, "") and _norm(mine) != _norm(shared[field_name]):
                    conflicts[field_name] = {"entity": shared[field_name], "record": mine}
            profile = _pack_fields(_entity_profile(target))
            if profile:
                receipt = compare(newcomer, profile, entity=entity_type)
                entity_evidence = {
                    "identity": receipt.identity, "action": receipt.action,
                    "score": float(receipt.score), "explanation": receipt.explanation,
                    "factors": {k: float(v) for k, v in dict(receipt.factors).items()
                                if isinstance(v, (int, float))},
                    "profile_fields": sorted(profile),
                }

        if len(matched) > 1:
            verdict, note = "ambiguous", (
                f"members of {len(matched)} entities matched; the record may bridge entities "
                "that are one thing, or one match is wrong. Link withheld."
            )
        elif conflicts:
            verdict, note = "conflict", (
                f"the nearest entity agrees on {', '.join(sorted(conflicts))} and this record "
                "contradicts it" + (". Link withheld." if matched else "; nothing was linked.")
            )
        elif len(matched) == 1 or loose_match:
            verdict, note = "found", (
                f"matched {candidates[matched[0]]['matched']} member(s) of one entity"
                if matched else "matched a stored record that was not yet in any entity"
            )
        elif result["matches"]:
            verdict, note = "review", "no member matched outright; the nearest pairs are open cases"
        else:
            verdict, note = "not_found", "no stored record came close"

        decisions = self.record_batch(result, [attrs], within, call=call, verb="resolve",
                                      link=(verdict == "found"))
        record_id = self._db.execute(
            "SELECT side_a FROM arche_runs WHERE run_id = ?", [decisions[0].run_id]
        ).fetchone()[0] if decisions else None
        if record_id is not None:
            record_id = _load(record_id)[0]
        else:
            record_id = self._record(entity_type, attrs, None, "resolve", None).record_id
        self._set_text(record_id, text)
        if verdict in ("ambiguous", "conflict"):
            self._event("link_withheld", {"record_id": record_id, "verdict": verdict,
                                          "entities": matched, "conflicts": sorted(conflicts)},
                        note)

        entity = self.entity(self.entity_of(record_id)) if verdict == "found" else target
        ordered = sorted(decisions, key=lambda d: (d.linked, d.score), reverse=True)
        would: list[str] = []
        if verdict in ("review", "ambiguous") and ordered:
            first = ordered[0]
            why = _why(first, self.record(first.record_a), self.record(first.record_b))
            would = _would_resolve(first, self.record(first.record_a),
                                   self.record(first.record_b), why)
        return Resolution(verdict, record_id, entity, tuple(ordered), candidates,
                          entity_evidence, conflicts, would, note)

    def _set_text(self, record_id: str, text: str | None) -> None:
        if text is not None:
            self._db.execute("UPDATE arche_records SET text = ? WHERE record_id = ?",
                             [text, record_id])

    def read(self, source: str, *, limit: int | None = None) -> list[dict[str, Any]]:
        """Rows from a table, a file, or a query the same DuckDB can see.

        ``source`` is a table name in this ledger's database, a path to a
        ``.csv`` / ``.parquet`` / ``.json`` file, or a ``SELECT`` statement.
        Returns plain dicts keyed by column, ready for ``reconcile``::

            ledger = arche.attach("duckdb:///suppliers.duckdb")
            result = arche.reconcile(ledger.read("suppliers"), ledger.read("registry.parquet"),
                                     entity="organisation", store=ledger)

        The ledger's own tables are ``arche_*``; everything else in the file is
        the caller's. Attaching is the door to the data as well as to the
        decisions, and the URI scheme is where other stores will hang later.
        """
        text = source.strip()
        lower = text.lower()
        if lower.startswith(("select ", "with ", "from ")):
            query = text
        elif lower.endswith(".csv"):
            query = f"SELECT * FROM read_csv_auto('{text}')"
        elif lower.endswith((".parquet", ".pq")):
            query = f"SELECT * FROM read_parquet('{text}')"
        elif lower.endswith((".json", ".jsonl", ".ndjson")):
            query = f"SELECT * FROM read_json_auto('{text}')"
        elif text.replace("_", "").replace(".", "").isalnum():
            query = f"SELECT * FROM {text}"
        else:
            raise ValueError(
                f"read() takes a table name, a .csv/.parquet/.json path or a SELECT; got {source!r}"
            )
        if limit is not None:
            query = f"SELECT * FROM ({query}) AS q LIMIT {int(limit)}"
        cursor = self._db.execute(query)
        columns = [col[0] for col in cursor.description]
        return [dict(zip(columns, row, strict=False)) for row in cursor.fetchall()]

    def cases(self, entity_type: str | None = None) -> list[Case]:
        """Pairs still at ``review``: the uncertain tail, with what would settle each."""
        rows = self._db.execute(
            "SELECT * FROM arche_decisions WHERE identity = 'review' "
            "AND superseded_by IS NULL ORDER BY recorded_at"
        ).fetchall()
        cases: list[Case] = []
        for row in rows:
            decision = _decision_from_row(row)
            record_a, record_b = self.record(decision.record_a), self.record(decision.record_b)
            if entity_type is not None and record_a.entity_type != entity_type:
                continue
            why = _why(decision, record_a, record_b)
            cases.append(Case(
                decision=decision,
                record_a=record_a,
                record_b=record_b,
                would_resolve=_would_resolve(decision, record_a, record_b, why),
                why=why,
            ))
        return cases

    def events(self, limit: int | None = None) -> tuple[Event, ...]:
        sql = "SELECT * FROM arche_events ORDER BY occurred_at, event_id"
        if limit is not None:
            sql += f" LIMIT {int(limit)}"
        return tuple(
            Event(row[0], row[1], datetime.fromisoformat(row[2]), _load(row[3]), row[4])
            for row in self._db.execute(sql).fetchall()
        )

    # ------------------------------------------------------------ acting

    def observe(self, record_id: str, evidence: Mapping[str, Any]) -> list[Decision]:
        """Add evidence about a record and decide its open pairs again.

        ``evidence`` is a ``{field: value}`` mapping -- a registry row, a value a
        reviewer confirmed, a field read from another document. A new record is
        written with the merged attributes; every decision that still names the
        old record and is not itself superseded is made again; each new receipt
        records which decision it supersedes. Nothing is overwritten.

        This is the act → observe → update step. Which evidence to fetch is the
        caller's call; ``cases()`` says what would help.
        """
        from arche.resolve import compare

        old = self.record(record_id)
        merged = {**old.attributes, **{k: v for k, v in evidence.items() if v not in (None, "")}}
        self._event(
            "observation_recorded",
            {"record_id": record_id, "fields": sorted(str(k) for k in evidence)},
            "new evidence about a record",
        )
        superseded: list[Decision] = []
        for prior in self.history(record_id):
            if prior.superseded_by is not None:
                continue
            other_id = prior.record_b if prior.record_a == record_id else prior.record_a
            other = self.record(other_id)
            if prior.verb == "compare":
                call = {k: v for k, v in prior.call.items()
                        if k not in _TEXT_ONLY_ARGS and not k.startswith("_")}
                entity = call.pop("entity", old.entity_type)
            else:
                # A batch edge is re-decided as one pair through the same pack.
                # The score is the pack engine's for a pair, not the batch's:
                # the frequency table was calibrated over two lists that are
                # not here. The new receipt's pins say which engine issued it.
                entity = prior.call.get("entity")
                if entity is None:
                    self._event("observe_skipped", {"decision_id": prior.decision_id},
                                "batch decision with bespoke comparators; re-run the batch")
                    continue
                call = {}
            a_in = merged if prior.record_a == record_id else dict(other.attributes)
            b_in = merged if prior.record_b == record_id else dict(other.attributes)
            receipt = compare(a_in, b_in, entity=entity, **call)
            observed_is_a = prior.record_a == record_id
            keep = (None, other.record_id) if observed_is_a else (other.record_id, None)
            fresh = self.record_compare(
                receipt, a_in, b_in,
                call={"entity": entity, **call},
                source=f"observe:{record_id}",
                supersedes=prior.decision_id,
                record_ids=keep,
            )
            self._db.execute(
                "UPDATE arche_decisions SET superseded_by = ? WHERE decision_id = ?",
                [fresh.decision_id, prior.decision_id],
            )
            self._event(
                "decision_superseded",
                {
                    "was": prior.decision_id, "now": fresh.decision_id,
                    "identity": f"{prior.identity} -> {fresh.identity}",
                },
            )
            superseded.append(fresh)
        return superseded

    # ------------------------------------------------------------ internals

    def _record(
        self,
        entity_type: str,
        given: Any,
        reference: Any,
        source: str,
        caller_id: str | None,
    ) -> Record:
        text: str | None = None
        if isinstance(given, str):
            text = given
            attributes = _attributes_of(reference) if reference is not None else {}
        elif isinstance(given, Mapping):
            attributes = _json_clean(dict(given))
        elif hasattr(given, "as_record"):
            attributes = _json_clean(given.as_record(include_restricted=True))
        elif hasattr(given, "detections"):
            raise TypeError(
                "a Pipeline Result cannot be stored in the ledger; pass the text or a "
                "record so the decision can be replayed"
            )
        else:
            raise TypeError(f"cannot store an input of type {type(given).__name__}")
        payload = {"entity_type": entity_type, "text": text} if text is not None \
            else {"entity_type": entity_type, "attributes": attributes}
        record_id = content_hash(payload, prefix="rec")
        existing = self._db.execute(
            "SELECT * FROM arche_records WHERE record_id = ?", [record_id]
        ).fetchone()
        if existing is not None:
            return _record_from_row(existing)
        record = Record(record_id, entity_type, source, caller_id, attributes, text, _now())
        self._db.execute(
            "INSERT INTO arche_records VALUES (?, ?, ?, ?, ?, ?, ?)",
            [record.record_id, entity_type, source, caller_id, _dump(attributes), text,
             record.recorded_at.isoformat()],
        )
        return record

    def _record_or_none(self, record_id: str) -> Record | None:
        row = self._db.execute(
            "SELECT * FROM arche_records WHERE record_id = ?", [record_id]
        ).fetchone()
        return _record_from_row(row) if row else None

    def _decision_or_none(self, decision_id: str) -> Decision | None:
        row = self._db.execute(
            "SELECT * FROM arche_decisions WHERE decision_id = ?", [decision_id]
        ).fetchone()
        return _decision_from_row(row) if row else None

    def _write_decision(self, decision: Decision, *, entity_type: str | None = None,
                        transaction: bool = True) -> None:
        if transaction:
            self._db.execute("BEGIN TRANSACTION")
        try:
            self._db.execute(
                "INSERT INTO arche_decisions VALUES "
                "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [decision.decision_id, decision.verb, decision.record_a, decision.record_b,
                 decision.identity, decision.action, decision.score, _dump(decision.factors),
                 decision.explanation, _dump(decision.evidence), _dump(decision.pins),
                 _dump(decision.call), decision.run_id, decision.recorded_at.isoformat(),
                 decision.supersedes, None],
            )
            self._event(
                "decision_recorded",
                {"decision_id": decision.decision_id, "identity": decision.identity,
                 "action": decision.action, "verb": decision.verb},
            )
            if decision.linked:
                self._link(decision, entity_type)
        except Exception:
            if transaction:
                self._db.execute("ROLLBACK")
            raise
        if transaction:
            self._db.execute("COMMIT")

    def _link(self, decision: Decision, entity_type: str | None = None) -> None:
        """Union the two records' entities. Merges keep the older id and log it."""
        if entity_type is None:
            entity_type = self.record(decision.record_a).entity_type
        a = self.entity_of(decision.record_a)
        b = self.entity_of(decision.record_b)
        if a is None and b is None:
            entity_id = f"ent_{uuid4().hex}"
            for record_id in (decision.record_a, decision.record_b):
                self._member(record_id, entity_id, entity_type, decision.decision_id)
            self._event("entity_created", {
                "entity_id": entity_id, "decision_id": decision.decision_id,
                "records": [decision.record_a, decision.record_b],
            })
        elif a is None or b is None:
            entity_id = a or b
            newcomer = decision.record_a if a is None else decision.record_b
            self._member(newcomer, entity_id, entity_type, decision.decision_id)
            self._event("record_linked", {"entity_id": entity_id, "record_id": newcomer,
                                          "decision_id": decision.decision_id})
        elif a != b:
            oldest = self._db.execute(
                "SELECT entity_id FROM arche_memberships WHERE entity_id IN (?, ?) "
                "ORDER BY linked_at LIMIT 1", [a, b],
            ).fetchone()[0]
            absorbed = b if oldest == a else a
            self._db.execute(
                "UPDATE arche_memberships SET entity_id = ? WHERE entity_id = ?",
                [oldest, absorbed],
            )
            self._event("entities_merged", {"kept": oldest, "absorbed": absorbed,
                                            "decision_id": decision.decision_id},
                        "two entities turned out to be one")

    def _member(self, record_id: str, entity_id: str, entity_type: str, decision_id: str) -> None:
        self._db.execute(
            "INSERT INTO arche_memberships VALUES (?, ?, ?, ?, ?)",
            [record_id, entity_id, entity_type, decision_id, _now().isoformat()],
        )

    def _event(self, kind: str, refs: Mapping[str, Any], note: str = "") -> None:
        self._db.execute("INSERT INTO arche_events VALUES (?, ?, ?, ?, ?)",
                         _event_row(kind, refs, note))

    def _rerun(self, then: Decision) -> dict[str, Any]:
        from arche.resolve import compare, reconcile

        call = {k: v for k, v in then.call.items() if not k.startswith("_")}
        if then.verb == "compare":
            record_a, record_b = self.record(then.record_a), self.record(then.record_b)
            a_in, b_in = record_a.as_input(), record_b.as_input()
            if not (isinstance(a_in, str) and isinstance(b_in, str)):
                call = {k: v for k, v in call.items() if k not in _TEXT_ONLY_ARGS}
            entity = call.pop("entity", record_a.entity_type)
            receipt = compare(a_in, b_in, entity=entity, **call)
            return {
                "decision_id": receipt.decision_id, "identity": receipt.identity,
                "action": receipt.action, "score": float(receipt.score),
                "factors": {k: float(v) for k, v in dict(receipt.factors).items()
                            if isinstance(v, (int, float))},
                "pins": dict(receipt.pins),
            }
        run = self._db.execute(
            "SELECT side_a, side_b FROM arche_runs WHERE run_id = ?", [then.run_id]
        ).fetchone()
        if run is None:
            raise ValueError(f"decision {then.decision_id!r} has no stored run to replay against")
        # A batch ran over dict rows; rebuild them from attributes, not text,
        # exactly as the verb saw them. `resolve` mapped its rows to the pack's
        # vocabulary and handed the stored side back under record ids.
        if then.verb == "resolve":
            list_a = [_pack_fields(self.record(rid).attributes) for rid in _load(run[0])]
            list_b = [{**_pack_fields(self.record(rid).attributes), "id": rid}
                      for rid in _load(run[1])]
        else:
            list_a = [dict(self.record(rid).attributes) for rid in _load(run[0])]
            list_b = [dict(self.record(rid).attributes) for rid in _load(run[1])]
        result = reconcile(list_a, list_b, **call)
        a_id, b_id = then.evidence.get("a_id"), then.evidence.get("b_id")
        edge = next((e for e in result["matches"]
                     if str(e["a_id"]) == a_id and str(e["b_id"]) == b_id), None)
        if edge is None:
            return {"decision_id": None, "identity": "unsurfaced", "action": "no_op",
                    "score": 0.0, "factors": {}, "pins": dict(result["pins"])}
        return {
            "decision_id": edge["decision_id"], "identity": edge["decision"],
            "action": "merge" if edge["decision"] == "match" else "hold",
            "score": float(edge["score"]),
            "factors": {k: float(v) for k, v in dict(edge.get("evidence", {})).items()
                        if isinstance(v, (int, float))},
            "pins": dict(result["pins"]),
        }


def attach(uri: str) -> Ledger:
    """Open a ledger. ``duckdb:///:memory:`` for scratch, ``duckdb:///file.duckdb`` to keep."""
    if not uri.startswith("duckdb:///"):
        raise ValueError(
            f"unsupported ledger URI {uri!r}; use duckdb:///:memory: or duckdb:///arche.duckdb"
        )
    database = uri.removeprefix("duckdb:///")
    if not database:
        raise ValueError(
            "the ledger URI needs a database path; use duckdb:///:memory: or duckdb:///arche.duckdb"
        )
    return Ledger(database)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

_SCHEMA = (
    """CREATE TABLE IF NOT EXISTS arche_records (
        record_id VARCHAR PRIMARY KEY, entity_type VARCHAR NOT NULL, source VARCHAR NOT NULL,
        caller_id VARCHAR, attributes VARCHAR NOT NULL, text VARCHAR, recorded_at VARCHAR NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS arche_decisions (
        decision_id VARCHAR PRIMARY KEY, verb VARCHAR NOT NULL,
        record_a VARCHAR NOT NULL, record_b VARCHAR NOT NULL,
        identity VARCHAR NOT NULL, action VARCHAR NOT NULL, score DOUBLE NOT NULL,
        factors VARCHAR NOT NULL, explanation VARCHAR NOT NULL, evidence VARCHAR NOT NULL,
        pins VARCHAR NOT NULL, call VARCHAR NOT NULL, run_id VARCHAR,
        recorded_at VARCHAR NOT NULL, supersedes VARCHAR, superseded_by VARCHAR
    )""",
    """CREATE TABLE IF NOT EXISTS arche_runs (
        run_id VARCHAR PRIMARY KEY, verb VARCHAR NOT NULL, call VARCHAR NOT NULL,
        side_a VARCHAR NOT NULL, side_b VARCHAR NOT NULL, pins VARCHAR NOT NULL,
        blocking VARCHAR NOT NULL, recorded_at VARCHAR NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS arche_memberships (
        record_id VARCHAR PRIMARY KEY, entity_id VARCHAR NOT NULL, entity_type VARCHAR NOT NULL,
        decision_id VARCHAR NOT NULL, linked_at VARCHAR NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS arche_events (
        event_id VARCHAR PRIMARY KEY, kind VARCHAR NOT NULL, occurred_at VARCHAR NOT NULL,
        refs VARCHAR NOT NULL, note VARCHAR NOT NULL
    )""",
)


def _now() -> datetime:
    return datetime.now(UTC)


def _event_row(kind: str, refs: Mapping[str, Any], note: str = "") -> list:
    return [f"evt_{uuid4().hex}", kind, _now().isoformat(), _dump(dict(refs)), note]


def _dump(value: Any) -> str:
    return json.dumps(value, sort_keys=True, default=str)


def _load(value: str | None) -> Any:
    return json.loads(value) if value else {}


def _json_clean(mapping: Mapping[str, Any]) -> dict[str, Any]:
    """A dict that survives ``json.dumps``; anything that does not becomes its ``str``."""
    return json.loads(json.dumps(dict(mapping), default=str))


def _attributes_of(reference: Any) -> dict[str, Any]:
    if hasattr(reference, "as_record"):
        return _json_clean(reference.as_record(include_restricted=True))
    return {}


def _call_record(call: Mapping[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Split a verb's arguments into what can be stored and what cannot.

    A declaration object, an issuer key or a frequency table are real inputs to
    the decision and cannot be serialised; their names are kept so ``replay``
    can say exactly why it must decline.
    """
    stored: dict[str, Any] = {}
    unreplayable: list[str] = []
    for key, value in call.items():
        if value is None:
            continue
        try:
            json.dumps(value)
        except (TypeError, ValueError):
            unreplayable.append(str(key))
            continue
        stored[str(key)] = value
    return stored, unreplayable


def _record_from_row(row: tuple) -> Record:
    return Record(row[0], row[1], row[2], row[3], _load(row[4]), row[5],
                  datetime.fromisoformat(row[6]))


def _decision_from_row(row: tuple) -> Decision:
    return Decision(
        decision_id=row[0], verb=row[1], record_a=row[2], record_b=row[3],
        identity=row[4], action=row[5], score=float(row[6]), factors=_load(row[7]),
        explanation=row[8], evidence=_load(row[9]), pins=_load(row[10]), call=_load(row[11]),
        run_id=row[12], recorded_at=datetime.fromisoformat(row[13]),
        supersedes=row[14], superseded_by=row[15],
    )


def _explain_edge(edge: Mapping[str, Any]) -> str:
    agreeing = sorted(k for k, v in dict(edge.get("evidence", {})).items()
                      if isinstance(v, (int, float)) and v >= 0.85)
    if edge.get("decision") == "match":
        return "agrees on " + ", ".join(agreeing) if agreeing else "matched"
    return ("review: agrees on " + ", ".join(agreeing)) if agreeing \
        else "review: no field agreed strongly"


def _norm(value: Any) -> str:
    return " ".join(str(value).split()).casefold()


def _agreement(records: Iterable[Record]) -> tuple[dict[str, Any], dict[str, list[Any]]]:
    """What a set of records agree on, and where they disagree.

    Only attributes at least two records carry can be shared or conflicting; a
    value one record alone supplies is neither.
    """
    values: dict[str, list[Any]] = {}
    for record in records:
        for key, value in record.attributes.items():
            if key == "id" or key.startswith("_") or value in (None, ""):
                continue
            values.setdefault(key, []).append(value)
    shared: dict[str, Any] = {}
    conflicts: dict[str, list[Any]] = {}
    for key, seen in values.items():
        if len(seen) < 2:
            continue
        distinct = list(dict.fromkeys(_norm(v) for v in seen))
        if len(distinct) == 1:
            shared[key] = seen[0]
        else:
            conflicts[key] = list(dict.fromkeys(seen))
    return shared, conflicts


def _why(decision: Decision, record_a: Record, record_b: Record) -> dict[str, Any]:
    supporting = sorted(k for k, v in decision.factors.items() if v >= 0.85)
    refuting = sorted(k for k, v in decision.factors.items() if v < 0.5)
    vetoes = decision.evidence.get("vetoes") or {}
    refuting += sorted(f"veto:{k}" for k, v in dict(vetoes).items() if v)
    present = set(_pack_fields(record_a.attributes)) | set(_pack_fields(record_b.attributes))
    missing = [f for f in _IDENTITY_FIELDS if f not in present and f not in decision.factors]
    shared: dict[str, Any] = {}
    for factor in supporting:
        # A factor is named for the comparison (`name`); the attribute it read
        # may carry the record's own spelling of that (`full_name`).
        for key in (factor, f"full_{factor}"):
            if (key in record_a.attributes and key in record_b.attributes
                    and _norm(record_a.attributes[key]) == _norm(record_b.attributes[key])):
                shared[factor] = record_a.attributes[key]
                break
    return {
        "identity": decision.identity,
        "action": decision.action,
        "basis": decision.evidence.get("basis", ""),
        "explanation": decision.explanation,
        "supporting": supporting,
        "refuting": refuting,
        "missing": missing,
        "shared": shared,
        "gate": decision.evidence.get("gate", {}),
    }


def _would_resolve(decision: Decision, record_a: Record, record_b: Record,
                   why: Mapping[str, Any]) -> list[str]:
    """Fields that would settle an open pair: the pack's answer when it has one."""
    entity = str(decision.call.get("entity") or record_a.entity_type)
    try:
        from arche.resolve import ENTITY_PACKS
        from arche.resolve._unresolved import would_resolve

        if entity in ENTITY_PACKS:
            edge = {"decision": "review", "evidence": decision.factors,
                    "score": decision.score,
                    "distinctive_max": decision.evidence.get("distinctive_max")}
            threshold = decision.pins.get("threshold")
            guidance = would_resolve(edge, _pack_fields(record_a.attributes),
                                     _pack_fields(record_b.attributes),
                                     entity=entity, threshold=threshold)
            fields = [item.get("field", item) if isinstance(item, Mapping) else str(item)
                      for item in guidance.get("would_resolve", [])]
            if fields:
                return [str(f) for f in fields]
    except Exception:  # guidance is advice; never let it break the listing
        pass
    return list(why.get("missing", []))


def _extract_record(text: str, *, backend: str) -> dict[str, Any]:
    """The record ``compare`` would build from a piece of text, as a dict."""
    from arche.canonical import Reference
    from arche.extract import extract

    reference = Reference.from_mentions(extract(text, backend=backend))
    return _json_clean(reference.as_record(include_restricted=True))


def _pack_fields(attributes: Mapping[str, Any]) -> dict[str, Any]:
    """Attributes under the field names an entity pack reads.

    ``full_name`` -> ``name``, ``phone_number`` -> ``phone`` and so on: the same
    map the person engine applies to a reference. A field already in the
    pack's vocabulary is left alone, and the first spelling wins.
    """
    from arche.resolve.coreference import _FIELD_MAP

    out: dict[str, Any] = {}
    for key, value in attributes.items():
        if key == "id" or key.startswith("_") or value in (None, ""):
            continue
        out.setdefault(_FIELD_MAP.get(key, key), value)
    return out


def _entity_profile(view: EntityView) -> dict[str, Any]:
    """The entity as one record: every attribute its members do not dispute.

    Shared attributes, plus attributes only one member supplied. Anything in
    ``conflicts`` is left out rather than picked; a profile that chose a
    surname for Mary would be asserting the thing it exists to test.
    """
    profile: dict[str, Any] = dict(view.shared)
    seen: dict[str, Any] = {}
    for record in view.records:
        for key, value in record.attributes.items():
            if key == "id" or key.startswith("_") or value in (None, ""):
                continue
            if key in view.conflicts or key in profile:
                continue
            seen.setdefault(key, value)
    profile.update(seen)
    return profile


def _flatten(prefix: str, value: Any, out: dict[str, Any]) -> None:
    if isinstance(value, Mapping):
        for k, v in value.items():
            _flatten(f"{prefix}.{k}" if prefix else str(k), v, out)
    else:
        out[prefix] = value


def _diff(then: Decision, now: Mapping[str, Any]) -> dict[str, Any]:
    changed: dict[str, Any] = {}
    for key in ("identity", "action"):
        if getattr(then, key) != now.get(key):
            changed[key] = {"then": getattr(then, key), "now": now.get(key)}
    if round(then.score, 4) != round(float(now.get("score", 0.0)), 4):
        changed["score"] = {"then": then.score, "now": now.get("score")}
    for name, before, after in (("factors", then.factors, now.get("factors", {})),
                                ("pins", then.pins, now.get("pins", {}))):
        flat_before: dict[str, Any] = {}
        flat_after: dict[str, Any] = {}
        _flatten("", before, flat_before)
        _flatten("", after, flat_after)
        for key in sorted(set(flat_before) | set(flat_after)):
            if flat_before.get(key) != flat_after.get(key):
                changed[f"{name}.{key}"] = {
                    "then": flat_before.get(key), "now": flat_after.get(key),
                }
    return changed


__all__ = [
    "Case",
    "Decision",
    "EntityView",
    "Event",
    "LINKED",
    "Ledger",
    "Record",
    "Replay",
    "Resolution",
    "attach",
]
