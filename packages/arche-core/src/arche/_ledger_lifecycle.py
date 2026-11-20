# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Entity lifecycle for the ledger: assertions, re-partitioning, lineage.

The ledger used to merge and never split: once two records were one entity,
no later decision could separate them. This module makes membership a
*function* of the evidence, recomputed whenever the evidence changes:

* the **active `same` edges** -- computed linking decisions that are neither
  superseded nor withheld, plus people's current ``same_as`` assertions;
* the **cannot-links** -- people's current ``different_from`` assertions.

Precedence, strongest first: asserted ``different_from``; asserted
``same_as``; computed ``match``; ``review`` and ``cannot_tell`` never link. A
computed decision never overrides an assertion.

A component that contains a cannot-link pair is split by a minimum s-t cut,
computed edges weighted by score and asserted ``same_as`` edges infinite. When
no finite cut exists -- people asserted both that two records are one and,
through others, that they are not -- nothing is guessed: the entity stays
whole and is marked *contested*.

**Entity ids.** An entity's id is a keyed hash of its *founding record* (the
oldest member, ties by record id), with one exception: when the founding
record was already the founding record of an existing entity, that entity's
id carries over. So a merge keeps the id of the entity founded earliest, the
part of a split that keeps the founding record keeps the id, ids created
before deterministic ids existed survive, and rebuilding from the evidence
reproduces the stored ids.

Everything here is append-only except ``arche_memberships``, the current
projection. Every membership change writes one lineage event with its cause
and one membership-history row, so "what was this entity on 1 March?" has an
answer.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from arche.ids import content_hash

#: Every (decision, record pair) a decision applies to. A decision id hashes
#: the comparison and a record id the whole record, so one decision can apply
#: to several record pairs (two records differing only in a field the pack
#: does not read). The decision row names the first; the rest are here.
PAIRS = ("(SELECT decision_id, record_a, record_b FROM arche_decisions "
         "UNION SELECT decision_id, record_a, record_b FROM arche_decision_pairs)")

#: Assertion kinds a person can make about a pair.
ASSERTION_KINDS = ("same_as", "different_from", "cannot_tell")
#: Entities above this size are not split automatically; they become contested.
SPLIT_CAP = 500
#: From this many seed records, the closure reads all active edges at once.
BULK_SEEDS = 64

LIFECYCLE_SCHEMA = (
    """CREATE TABLE IF NOT EXISTS arche_assertions (
        assertion_id VARCHAR PRIMARY KEY, kind VARCHAR NOT NULL,
        record_a VARCHAR NOT NULL, record_b VARCHAR NOT NULL,
        asserted_by VARCHAR NOT NULL, reason VARCHAR NOT NULL, criterion VARCHAR NOT NULL,
        decision_id VARCHAR, asserted_at VARCHAR NOT NULL, retracts VARCHAR
    )""",
    """CREATE TABLE IF NOT EXISTS arche_lineage (
        event_id VARCHAR PRIMARY KEY, kind VARCHAR NOT NULL, entity_type VARCHAR NOT NULL,
        before_ids VARCHAR NOT NULL, after_ids VARCHAR NOT NULL,
        records_moved VARCHAR NOT NULL, cause VARCHAR NOT NULL, run_id VARCHAR,
        detail VARCHAR NOT NULL, occurred_at VARCHAR NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS arche_membership_history (
        record_id VARCHAR NOT NULL, entity_type VARCHAR NOT NULL, entity_id VARCHAR,
        recorded_at VARCHAR NOT NULL, event_id VARCHAR NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS arche_decision_pairs (
        decision_id VARCHAR NOT NULL, record_a VARCHAR NOT NULL, record_b VARCHAR NOT NULL,
        recorded_at VARCHAR NOT NULL, PRIMARY KEY (decision_id, record_a, record_b)
    )""",
    # A linking decision recorded with link=False (resolve found it ambiguous
    # or conflicting). Append-only: the latest row per decision says whether
    # it is currently withheld.
    """CREATE TABLE IF NOT EXISTS arche_withheld (
        decision_id VARCHAR NOT NULL, withheld BOOLEAN NOT NULL, marked_at VARCHAR NOT NULL
    )""",
)


@dataclass(frozen=True)
class Assertion:
    assertion_id: str
    kind: str
    record_a: str
    record_b: str
    asserted_by: str
    reason: str
    criterion: str
    decision_id: str | None
    asserted_at: str
    retracts: str | None


@dataclass(frozen=True)
class LineageEvent:
    event_id: str
    kind: str
    entity_type: str
    before_ids: tuple[str, ...]
    after_ids: tuple[str, ...]
    records_moved: tuple[str, ...]
    cause: str
    run_id: str | None
    detail: dict[str, Any]
    occurred_at: str


def _pair(a: str, b: str) -> tuple[str, str]:
    return (a, b) if a <= b else (b, a)


class LifecycleMixin:
    """Mixed into :class:`arche.ledger.Ledger`; relies on its ``_db`` and key."""

    _db: Any
    _record_key: bytes | None
    _CHUNK: int

    # ------------------------------------------------------------ public

    def assert_same(self, record_a: str, record_b: str, *, by: str, reason: str,
                    criterion: str = "", decision_id: str | None = None) -> Assertion:
        """A person's judgement that two records are one entity (a must-link)."""
        return self._assert("same_as", record_a, record_b, by, reason, criterion, decision_id)

    def assert_different(self, record_a: str, record_b: str, *, by: str, reason: str,
                         criterion: str = "", decision_id: str | None = None) -> Assertion:
        """A person's judgement that two records are not one entity (a cannot-link)."""
        return self._assert("different_from", record_a, record_b, by, reason, criterion,
                            decision_id)

    def assert_cannot_tell(self, record_a: str, record_b: str, *, by: str, reason: str,
                           criterion: str = "", decision_id: str | None = None) -> Assertion:
        """Recorded; never links and never separates. Replaces an earlier judgement."""
        return self._assert("cannot_tell", record_a, record_b, by, reason, criterion,
                            decision_id)

    def retract(self, assertion_id: str, *, by: str, reason: str) -> Assertion:
        """Withdraw an assertion. The history keeps both; membership is recomputed."""
        row = self._db.execute("SELECT * FROM arche_assertions WHERE assertion_id = ?",
                               [assertion_id]).fetchone()
        if row is None:
            raise KeyError(f"no assertion {assertion_id!r} in this ledger")
        target = Assertion(*row)
        return self._write_assertion("retract", target.record_a, target.record_b, by, reason,
                                     target.criterion, target.decision_id, retracts=assertion_id)

    def assertions(self, record_id: str | None = None) -> list[Assertion]:
        """Every assertion, oldest first, optionally those naming one record."""
        sql, params = "SELECT * FROM arche_assertions", []
        if record_id is not None:
            sql += " WHERE record_a = ? OR record_b = ?"
            params = [record_id, record_id]
        return [Assertion(*r) for r in self._db.execute(
            sql + " ORDER BY asserted_at, assertion_id", params).fetchall()]

    def lineage(self, entity_id: str) -> list[LineageEvent]:
        """The partition changes that shaped an entity, oldest first."""
        rows = self._db.execute(
            "SELECT * FROM arche_lineage WHERE before_ids LIKE ? OR after_ids LIKE ? "
            "ORDER BY occurred_at, event_id", [f'%"{entity_id}"%', f'%"{entity_id}"%']
        ).fetchall()
        return [_lineage_from_row(r) for r in rows]

    def contested(self) -> list[dict[str, Any]]:
        """Entities left whole because people's assertions contradict each other."""
        rows = self._db.execute(
            "SELECT after_ids, kind, detail FROM arche_lineage "
            "WHERE kind IN ('contested', 'settled') ORDER BY occurred_at, event_id"
        ).fetchall()
        state: dict[str, dict[str, Any]] = {}
        for after_ids, kind, detail in rows:
            entity_id = json.loads(after_ids)[0]
            if kind == "contested":
                state[entity_id] = {"entity_id": entity_id, **json.loads(detail)}
            else:
                state.pop(entity_id, None)
        live = {r[0] for r in self._db.execute(
            "SELECT DISTINCT entity_id FROM arche_memberships").fetchall()}
        return [v for k, v in sorted(state.items()) if k in live]

    def rebuild(self) -> dict[str, Any]:
        """Recompute every entity from the evidence and compare with what is stored.

        Writes nothing. ``differences`` should be empty (invariant I3): any
        entry is a membership or id the stored state holds that the evidence
        does not produce.
        """
        members = dict(self._db.execute(
            "SELECT record_id, entity_id FROM arche_memberships").fetchall())
        nodes = set(members)
        edges = self._edges_touching(nodes, all_edges=True)
        for e in edges["computed"] + edges["must"]:
            nodes.update(e[:2])
        computed = self._compute_partition(nodes, edges, old_members={})
        legacy = self._legacy_ids()
        stored_sets: dict[str, set[str]] = {}
        for r, e in members.items():
            stored_sets.setdefault(e, set()).add(r)
        differences: list[dict[str, Any]] = []
        produced = {frozenset(c["records"]): c for c in computed}
        for entity_id, recs in sorted(stored_sets.items()):
            c = produced.get(frozenset(recs))
            if c is None:
                differences.append({"entity_id": entity_id, "issue": "membership"})
            elif c["entity_id"] != entity_id and entity_id not in legacy:
                differences.append({"entity_id": entity_id, "issue": "id",
                                    "expected": c["entity_id"]})
        stored_frozen = {frozenset(v) for v in stored_sets.values()}
        for recs, c in produced.items():
            if recs not in stored_frozen:
                differences.append({"entity_id": c["entity_id"], "issue": "not stored"})
        return {"entities": len(stored_sets), "differences": differences}

    # ------------------------------------------------------------ assertions

    def _assert(self, kind, a, b, by, reason, criterion, decision_id) -> Assertion:
        if a == b:
            raise ValueError("an assertion needs two different records")
        for record_id in (a, b):
            self.record(record_id)  # type: ignore[attr-defined]  # KeyError if unknown
        if not str(by).strip() or not str(reason).strip():
            raise ValueError("an assertion needs `by` (a pseudonymous reviewer id) and `reason`")
        prior = self._current_assertions_for([_pair(a, b)]).get(_pair(a, b))
        return self._write_assertion(kind, a, b, by, reason, criterion, decision_id,
                                     retracts=prior.assertion_id if prior else None)

    def _write_assertion(self, kind, a, b, by, reason, criterion, decision_id, *,
                         retracts) -> Assertion:
        from arche.ledger import _now

        a, b = _pair(a, b)
        at = _now().isoformat()
        body = {"kind": kind, "record_a": a, "record_b": b, "asserted_by": by,
                "reason": reason, "criterion": criterion, "decision_id": decision_id,
                "asserted_at": at, "retracts": retracts}
        assertion = Assertion(content_hash(body, prefix="asr"), kind, a, b, by, reason,
                              criterion, decision_id, at, retracts)
        self._db.execute("BEGIN TRANSACTION")
        try:
            self._db.execute("INSERT INTO arche_assertions VALUES (?,?,?,?,?,?,?,?,?,?)",
                             list(assertion.__dict__.values()))
            self._event("assertion_recorded",  # type: ignore[attr-defined]
                        {"assertion_id": assertion.assertion_id, "kind": kind})
            self._repartition({a, b}, cause=assertion.assertion_id)
        except Exception:
            self._db.execute("ROLLBACK")
            raise
        self._db.execute("COMMIT")
        return assertion

    def _current_assertions_for(self, pairs: Iterable[tuple[str, str]]
                                ) -> dict[tuple[str, str], Assertion]:
        """The assertion in force on each pair: the newest one not retracted."""
        wanted = set(pairs)
        if not wanted:
            return {}
        rows: list[tuple] = []
        records = sorted({r for p in wanted for r in p})
        for i in range(0, len(records), self._CHUNK):
            chunk = records[i:i + self._CHUNK]
            marks = ", ".join("?" for _ in chunk)
            rows += self._db.execute(
                f"SELECT * FROM arche_assertions WHERE record_a IN ({marks})", chunk
            ).fetchall()
        by_pair: dict[tuple[str, str], list[Assertion]] = {}
        for row in rows:
            a = Assertion(*row)
            if (a.record_a, a.record_b) in wanted:
                by_pair.setdefault((a.record_a, a.record_b), []).append(a)
        return {pair: cur for pair, items in by_pair.items()
                if (cur := _in_force(items)) is not None}

    # ------------------------------------------------------------ edges

    def _edges_touching(self, records: set[str], *, all_edges: bool = False
                        ) -> dict[str, list]:
        """Active computed `same` edges and assertions touching ``records``.

        ``computed``: (a, b, score, decision_id) for linking decisions that are
        neither superseded nor withheld nor contradicted by an assertion.
        ``must`` / ``cannot``: (a, b, assertion) from assertions in force.
        """
        where_withheld = (
            "decision_id NOT IN (SELECT decision_id FROM ("
            " SELECT decision_id, withheld, row_number() OVER ("
            "  PARTITION BY decision_id ORDER BY marked_at DESC) AS n FROM arche_withheld)"
            " WHERE n = 1 AND withheld)")
        base = (f"SELECT p.decision_id, p.record_a, p.record_b, d.score FROM {PAIRS} p "
                "JOIN arche_decisions_v d ON d.decision_id = p.decision_id "
                "WHERE d.identity IN ('same_entity', 'match') AND d.superseded_by IS NULL "
                f"AND p.{where_withheld}")
        rows: list[tuple] = []
        assertion_rows: list[tuple] = []
        if all_edges:
            rows = self._db.execute(base).fetchall()
            assertion_rows = self._db.execute("SELECT * FROM arche_assertions").fetchall()
        else:
            ids = sorted(records)
            for i in range(0, len(ids), self._CHUNK):
                chunk = ids[i:i + self._CHUNK]
                marks = ", ".join("?" for _ in chunk)
                rows += self._db.execute(
                    f"{base} AND (p.record_a IN ({marks}) OR p.record_b IN ({marks}))",
                    [*chunk, *chunk]).fetchall()
                assertion_rows += self._db.execute(
                    f"SELECT * FROM arche_assertions WHERE record_a IN ({marks}) "
                    f"OR record_b IN ({marks})", [*chunk, *chunk]).fetchall()
        by_pair: dict[tuple[str, str], list[Assertion]] = {}
        for row in {r[0]: r for r in assertion_rows}.values():
            a = Assertion(*row)
            by_pair.setdefault((a.record_a, a.record_b), []).append(a)
        in_force = {p: cur for p, items in by_pair.items()
                    if (cur := _in_force(items)) is not None}
        must = sorted((p[0], p[1], a) for p, a in in_force.items() if a.kind == "same_as")
        cannot = sorted(((p[0], p[1], a) for p, a in in_force.items()
                         if a.kind == "different_from"),
                        key=lambda t: (t[2].asserted_at, t[2].assertion_id))
        blocked = {(p[0], p[1]) for p, a in in_force.items() if a.kind == "different_from"}
        computed = sorted({(min(a, b), max(a, b), float(s), d)
                           for d, a, b, s in rows if _pair(a, b) not in blocked},
                          key=lambda t: (t[0], t[1], t[3]))
        return {"computed": computed, "must": must, "cannot": cannot}

    # ------------------------------------------------------------ partition

    def _closure(self, seeds: set[str]) -> tuple[set[str], dict[str, list]]:
        """Every record whose membership could change: seeds, their entity-mates,
        and everything reachable from them over active `same` edges."""
        if len(seeds) >= BULK_SEEDS:
            return self._closure_in_memory(seeds)
        seen: set[str] = set()
        frontier = set(seeds)
        edges: dict[str, dict] = {"computed": {}, "must": {}, "cannot": {}}
        while frontier:
            seen |= frontier
            mates = set(self._entity_mates(frontier))
            found = self._edges_touching(frontier)
            for e in found["computed"]:
                # Keyed by decision AND pair: one decision can apply to several
                # record pairs (see PAIRS), and keying on the id alone dropped
                # all but one of them.
                edges["computed"][(e[3], e[0], e[1])] = e
            for key in ("must", "cannot"):
                for e in found[key]:
                    edges[key][e[2].assertion_id] = e
            reach = {r for e in found["computed"] + found["must"] for r in e[:2]}
            frontier = (mates | reach) - seen
        return seen, {k: sorted(v.values(), key=lambda t: (t[0], t[1], str(t[-1])))
                      for k, v in edges.items()}

    def _closure_in_memory(self, seeds: set[str]) -> tuple[set[str], dict[str, list]]:
        """The same closure, from one read of every active edge and membership.

        For a batch: hundreds of chunked queries per frontier cost ~60 s on a
        3,000-edge batch, one read of the active edges costs milliseconds.
        Linear in the ledger's size, so used only when the seeds are many.
        """
        everything = self._edges_touching(set(), all_edges=True)
        adjacency: dict[str, set[str]] = {}
        for a, b, *_ in [*everything["computed"], *everything["must"]]:
            adjacency.setdefault(a, set()).add(b)
            adjacency.setdefault(b, set()).add(a)
        by_entity: dict[str, set[str]] = {}
        entity_of: dict[str, str] = {}
        for r, e in self._db.execute(
                "SELECT record_id, entity_id FROM arche_memberships").fetchall():
            by_entity.setdefault(e, set()).add(r)
            entity_of[r] = e
        seen: set[str] = set()
        stack = list(seeds)
        while stack:
            r = stack.pop()
            if r in seen:
                continue
            seen.add(r)
            stack.extend(adjacency.get(r, ()))
            if r in entity_of:
                stack.extend(by_entity[entity_of[r]])
        return seen, {k: [e for e in v if e[0] in seen and e[1] in seen]
                      for k, v in everything.items()}

    def _entity_mates(self, records: set[str]) -> list[str]:
        ids = sorted(records)
        out: list[str] = []
        for i in range(0, len(ids), self._CHUNK):
            chunk = ids[i:i + self._CHUNK]
            marks = ", ".join("?" for _ in chunk)
            out += [r[0] for r in self._db.execute(
                "SELECT m2.record_id FROM arche_memberships m1 JOIN arche_memberships m2 "
                f"USING (entity_id) WHERE m1.record_id IN ({marks})", chunk).fetchall()]
        return out

    def _current_members(self, records: Iterable[str]) -> dict[str, str]:
        ids = sorted(set(records))
        out: dict[str, str] = {}
        for i in range(0, len(ids), self._CHUNK):
            chunk = ids[i:i + self._CHUNK]
            marks = ", ".join("?" for _ in chunk)
            out.update(dict(self._db.execute(
                f"SELECT record_id, entity_id FROM arche_memberships "
                f"WHERE record_id IN ({marks})", chunk).fetchall()))
        return out

    def _recorded_at(self, records: Iterable[str]) -> dict[str, tuple[str, str, str]]:
        """record -> (recorded_at, record_id, entity_type), the founding order."""
        ids = sorted(set(records))
        out: dict[str, tuple[str, str, str]] = {}
        for i in range(0, len(ids), self._CHUNK):
            chunk = ids[i:i + self._CHUNK]
            marks = ", ".join("?" for _ in chunk)
            for rid, at, et in self._db.execute(
                    f"SELECT record_id, recorded_at, entity_type FROM arche_records "
                    f"WHERE record_id IN ({marks})", chunk).fetchall():
                out[rid] = (at, rid, et)
        return out

    def _entity_id_for(self, entity_type: str, founding: str) -> str:
        msg = f"arche.entity.v1|{entity_type}|{founding}".encode()
        digest = (hmac.new(self._record_key, msg, hashlib.sha256).hexdigest()
                  if self._record_key else hashlib.sha256(msg).hexdigest())
        return "ent_" + digest[:32]

    def _compute_partition(self, nodes: set[str], edges: Mapping[str, list],
                           old_members: Mapping[str, str]) -> list[dict[str, Any]]:
        """Components of the active edges, cut apart at cannot-links, with ids."""
        import networkx as nx

        parent = {n: n for n in nodes}

        def find(x: str) -> str:
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        for a, b, *_ in [*edges["computed"], *edges["must"]]:
            if a in parent and b in parent:
                ra, rb = find(a), find(b)
                if ra != rb:
                    parent[max(ra, rb)] = min(ra, rb)
        groups: dict[str, set[str]] = {}
        for n in sorted(nodes):
            groups.setdefault(find(n), set()).add(n)

        order = self._recorded_at(nodes)
        old_sets: dict[str, set[str]] = {}
        for r, e in old_members.items():
            old_sets.setdefault(e, set()).add(r)
        old_founding = {e: min(rs, key=lambda r: order.get(r, ("", r, "")))
                        for e, rs in old_sets.items()}

        out: list[dict[str, Any]] = []
        for group in groups.values():
            if len(group) < 2:
                continue
            cannots = [c for c in edges["cannot"] if c[0] in group and c[1] in group]
            parts: list[set[str]] = [group]
            contested: dict[str, Any] | None = None
            if cannots and len(group) > SPLIT_CAP:
                contested = {"reason": "too_large_to_split_automatically",
                             "assertions": [c[2].assertion_id for c in cannots]}
            elif cannots:
                g = nx.Graph()
                g.add_nodes_from(sorted(group))
                for a, b, score, _d in edges["computed"]:
                    if a in group and b in group:
                        cap = max(score, g.edges[a, b]["capacity"]) if g.has_edge(a, b) \
                            else score
                        g.add_edge(a, b, capacity=cap)
                for a, b, _asr in edges["must"]:
                    if a in group and b in group:
                        if g.has_edge(a, b):
                            g.remove_edge(a, b)
                        g.add_edge(a, b)  # no capacity attribute: infinite
                for a, b, asr in cannots:
                    if not nx.has_path(g, a, b):
                        continue
                    try:
                        _value, (side, _other) = nx.minimum_cut(g, a, b)
                    except nx.NetworkXUnbounded:
                        contested = {"reason": "assertions_contradict",
                                     "assertions": sorted({asr.assertion_id, *(
                                         m[2].assertion_id for m in edges["must"]
                                         if m[0] in group and m[1] in group)})}
                        break
                    g.remove_edges_from([(u, v) for u, v in list(g.edges)
                                         if (u in side) != (v in side)])
                if contested is None:
                    parts = [set(c) for c in nx.connected_components(g)]
            for part in parts:
                if len(part) < 2:
                    continue
                founding = min(part, key=lambda r: order.get(r, ("", r, "")))
                old = old_members.get(founding)
                entity_id = (old if old is not None and old_founding.get(old) == founding
                             else self._entity_id_for(order[founding][2], founding))
                out.append({"entity_id": entity_id, "records": frozenset(part),
                            "entity_type": order[founding][2], "contested": contested})
        return out

    def _repartition(self, seeds: set[str], *, cause: str, run_id: str | None = None,
                     triggers: Mapping[str, str] | None = None) -> None:
        """Recompute membership around ``seeds`` and write what changed.

        ``triggers`` maps a record to the decision that brought it into this
        call; a lineage event names the first trigger among its moved records,
        else ``cause``. Runs inside the caller's transaction.
        """
        from arche.ledger import _now

        nodes, edges = self._closure(set(seeds))
        old = self._current_members(nodes)
        parts = self._compute_partition(nodes, edges, old)
        new: dict[str, str] = {}
        types: dict[str, str] = {}
        for p in parts:
            for r in p["records"]:
                new[r] = p["entity_id"]
                types[r] = p["entity_type"]
        moved = sorted(r for r in nodes if old.get(r) != new.get(r))
        now = _now().isoformat()
        order = self._recorded_at(nodes)

        def cause_for(records: Iterable[str]) -> str:
            hits = sorted((triggers or {}).get(r, "") for r in records)
            hits = [h for h in hits if h]
            return hits[0] if hits else cause

        events: list[list] = []
        history_event: dict[str, str] = {}

        def event(kind, et, before, after, recs, why, detail=None) -> str:
            eid = f"lin_{uuid4().hex}"
            events.append([eid, kind, et, json.dumps(sorted(before)), json.dumps(sorted(after)),
                           json.dumps(sorted(recs)), why, run_id,
                           json.dumps(detail or {}, sort_keys=True), now])
            for r in recs:
                history_event[r] = eid
            return eid

        old_ids = sorted({old[r] for r in moved if r in old})
        new_ids_before = set(old.values())
        for entity_id in old_ids:
            members = [r for r, e in old.items() if e == entity_id]
            dest = {new.get(r) for r in members}
            leaving = [r for r in members if new.get(r) != entity_id]
            et = order.get(members[0], ("", "", "record"))[2]
            if dest == {entity_id}:
                continue
            if entity_id not in dest and len(dest) == 1 and None not in dest:
                event("merge", et, [entity_id, *dest], dest, leaving, cause_for(leaving))
            elif dest == {None}:
                event("retire", et, [entity_id], [], leaving, cause_for(leaving))
            else:
                event("split", et, [entity_id], [d for d in dest if d], leaving,
                      cause_for(leaving))
        fresh: dict[str, list[str]] = {}
        for r in moved:
            if r not in old and new.get(r):
                fresh.setdefault(new[r], []).append(r)
        for entity_id, recs in sorted(fresh.items()):
            et = types[recs[0]]
            kind = "absorb" if entity_id in new_ids_before else "create"
            event(kind, et, [entity_id] if kind == "absorb" else [], [entity_id], recs,
                  cause_for(recs))

        previously = {c["entity_id"] for c in self.contested()}
        for p in parts:
            if p["contested"] and p["entity_id"] not in previously:
                event("contested", p["entity_type"], [p["entity_id"]], [p["entity_id"]], [],
                      cause, p["contested"])
            elif not p["contested"] and p["entity_id"] in previously:
                event("settled", p["entity_type"], [p["entity_id"]], [p["entity_id"]], [],
                      cause)

        if moved:
            for i in range(0, len(moved), self._CHUNK):
                chunk = moved[i:i + self._CHUNK]
                marks = ", ".join("?" for _ in chunk)
                self._db.execute(
                    f"DELETE FROM arche_memberships WHERE record_id IN ({marks})", chunk)
            self._insert_rows("arche_memberships", [  # type: ignore[attr-defined]
                [r, new[r], types[r], self._link_cause(r, new, edges, cause), now]
                for r in moved if new.get(r)])
            self._insert_rows("arche_membership_history", [  # type: ignore[attr-defined]
                [r, order.get(r, ("", "", "record"))[2], new.get(r), now, history_event[r]]
                for r in moved])
        self._insert_rows("arche_lineage", events)  # type: ignore[attr-defined]
        # The general event stream keeps the names it has always used.
        from arche.ledger import _event_row

        legacy_kind = {"create": "entity_created", "absorb": "record_linked",
                       "merge": "entities_merged", "split": "entity_split",
                       "retire": "entity_retired", "contested": "entity_contested",
                       "settled": "entity_settled"}
        self._insert_rows("arche_events", [  # type: ignore[attr-defined]
            _event_row(legacy_kind[e[1]], {"lineage_event": e[0], "before": json.loads(e[3]),
                                           "after": json.loads(e[4]),
                                           "records": json.loads(e[5]), "cause": e[6]})
            for e in events])

    @staticmethod
    def _link_cause(record: str, new: Mapping[str, str], edges: Mapping[str, list],
                    fallback: str) -> str:
        """The first active edge joining ``record`` to its entity: its membership's cause."""
        for a, b, *rest in [*edges["must"], *edges["computed"]]:
            if record in (a, b) and new.get(a) == new.get(b):
                tag = rest[-1]
                return tag.assertion_id if isinstance(tag, Assertion) else str(tag)
        return fallback

    def _legacy_ids(self) -> set[str]:
        return {json.loads(r[0])[0] for r in self._db.execute(
            "SELECT after_ids FROM arche_lineage WHERE kind = 'migration'").fetchall()}

    def _migrate_lifecycle(self) -> None:
        """First open after lineage existed: give existing entities a history.

        Existing ids are kept. An entity its active edges no longer hold
        together (a decision superseded since it was linked) is marked
        contested rather than split silently.
        """
        from arche.ledger import _now

        if self._db.execute("SELECT count(*) FROM arche_lineage").fetchone()[0]:
            return
        rows = self._db.execute(
            "SELECT record_id, entity_id, entity_type, linked_at FROM arche_memberships "
            "ORDER BY entity_id, linked_at, record_id").fetchall()
        if not rows:
            return
        import networkx as nx

        now = _now().isoformat()
        by_entity: dict[str, list[tuple]] = {}
        for row in rows:
            by_entity.setdefault(row[1], []).append(row)
        edges = self._edges_touching({r[0] for r in rows}, all_edges=True)
        lineage, history = [], []
        for entity_id, members in by_entity.items():
            recs = [m[0] for m in members]
            eid = f"lin_{uuid4().hex}"
            lineage.append([eid, "migration", members[0][2], "[]", json.dumps([entity_id]),
                            json.dumps(sorted(recs)), "migration", None, "{}", now])
            history += [[m[0], m[2], entity_id, m[3], eid] for m in members]
            g = nx.Graph()
            g.add_nodes_from(recs)
            g.add_edges_from((a, b) for a, b, *_ in [*edges["computed"], *edges["must"]]
                             if a in g and b in g)
            if len(recs) > 1 and not nx.is_connected(g):
                lineage.append([f"lin_{uuid4().hex}", "contested", members[0][2],
                                json.dumps([entity_id]), json.dumps([entity_id]), "[]",
                                "migration", None,
                                json.dumps({"reason": "no_longer_held_together"}), now])
        self._insert_rows("arche_lineage", lineage)  # type: ignore[attr-defined]
        self._insert_rows("arche_membership_history", history)  # type: ignore[attr-defined]


def _in_force(items: list[Assertion]) -> Assertion | None:
    retracted = {a.retracts for a in items if a.kind == "retract" and a.retracts}
    live = [a for a in items if a.kind != "retract" and a.assertion_id not in retracted]
    return max(live, key=lambda a: (a.asserted_at, a.assertion_id)) if live else None


def _lineage_from_row(row: tuple) -> LineageEvent:
    return LineageEvent(row[0], row[1], row[2], tuple(json.loads(row[3])),
                        tuple(json.loads(row[4])), tuple(json.loads(row[5])), row[6], row[7],
                        json.loads(row[8]), row[9])
