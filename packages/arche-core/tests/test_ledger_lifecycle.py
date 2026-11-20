# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Un-merging: assertions, re-partitioning, lineage, ids -- and the invariants.

The ledger used to merge and never split. These tests pin the lifecycle in
docs: precedence (asserted different > asserted same > computed match), the
minimum cut, contested entities, deterministic ids, point-in-time membership,
and the spec's invariants I1-I5 and I7 over every scenario.
"""

from __future__ import annotations

import time

import pytest
from arche.ledger import Ledger, attach

KEY = b"t" * 32


def _ledger() -> Ledger:
    return attach("duckdb:///:memory:", record_key=KEY)


def _link(ledger: Ledger, pairs: list[tuple[str, str, float]], *, link: bool = True):
    """Record synthetic `match` edges between named records; return name -> record id."""
    names = sorted({n for a, b, _ in pairs for n in (a, b)})
    rows = {n: {"id": n, "name": f"Record {n}"} for n in names}
    result = {
        "pins": {"engine": "test"},
        "matches": [{"a_id": a, "b_id": b, "decision": "match", "score": s,
                     "decision_id": f"xwd:test:{a}-{b}", "evidence": {"name": s}}
                    for a, b, s in pairs],
    }
    rows_a = [rows[n] for n in names]
    decisions = ledger.record_batch(result, rows_a, rows_a,
                                    call={"entity": "organisation", "id_field": "id"},
                                    link=link)
    ids = {}
    for d in decisions:
        a, b = d.decision_id.split(":")[-1].split("-")
        ids[a], ids[b] = d.record_a, d.record_b
    return ids


def _partition(ledger: Ledger) -> set[frozenset[str]]:
    groups: dict[str, set[str]] = {}
    for r, e in ledger._db.execute(
            "SELECT record_id, entity_id FROM arche_memberships").fetchall():
        groups.setdefault(e, set()).add(r)
    return {frozenset(v) for v in groups.values()}


def _check_invariants(ledger: Ledger) -> None:
    contested = {c["entity_id"] for c in ledger.contested()}
    import networkx as nx

    for view in ledger.entities():
        members = set(view.record_ids)
        # I1: no active different_from pair inside an entity (contested excepted)
        if view.entity_id not in contested:
            for a in ledger.assertions():
                cur = ledger._current_assertions_for([(a.record_a, a.record_b)])
                pair = (a.record_a, a.record_b)
                if pair in cur and cur[pair].kind == "different_from":
                    assert not ({a.record_a, a.record_b} <= members), "I1"
        # I2: members connected by active same edges
        edges = ledger._edges_touching(members)
        g = nx.Graph()
        g.add_nodes_from(members)
        g.add_edges_from((a, b) for a, b, *_ in [*edges["computed"], *edges["must"]]
                         if a in members and b in members)
        if view.entity_id not in contested:
            assert nx.is_connected(g), "I2"
        # I5: entity() and graph() agree
        sub = ledger.graph(view.entity_id)
        assert set(sub.nodes) == members, "I5 nodes"
        assert {d for *_, d in sub.edges(data="decision_id")} <= set(view.decision_ids), "I5"
    # I3: rebuilding reproduces the stored state
    assert ledger.rebuild()["differences"] == [], "I3"
    # I4: every history row has its lineage event
    lineage_ids = {r[0] for r in ledger._db.execute(
        "SELECT event_id FROM arche_lineage").fetchall()}
    for (event_id,) in ledger._db.execute(
            "SELECT event_id FROM arche_membership_history").fetchall():
        assert event_id in lineage_ids, "I4"


class TestSplit:
    def test_different_from_cuts_the_weakest_link(self):
        ledger = _ledger()
        ids = _link(ledger, [("A", "B", 0.95), ("B", "C", 0.71)])
        A, B, C = ids["A"], ids["B"], ids["C"]
        before = ledger.entity_of(A)
        assert _partition(ledger) == {frozenset({A, B, C})}

        ledger.assert_different(A, C, by="rev-1", reason="two sites")
        assert _partition(ledger) == {frozenset({A, B})}
        assert ledger.entity_of(C) is None
        assert ledger.entity_of(A) == before, "the part with the founding record keeps the id"
        kinds = [e.kind for e in ledger.lineage(before)]
        assert kinds[-1] == "split"
        _check_invariants(ledger)

    def test_an_asserted_same_as_is_never_cut(self):
        ledger = _ledger()
        ids = _link(ledger, [("A", "B", 0.95), ("B", "C", 0.71)])
        A, B, C = ids["A"], ids["B"], ids["C"]
        ledger.assert_same(B, C, by="rev-1", reason="same site")
        ledger.assert_different(A, C, by="rev-1", reason="different site")
        assert _partition(ledger) == {frozenset({B, C})}
        _check_invariants(ledger)

    def test_the_split_off_part_gets_its_own_deterministic_id(self):
        ledger = _ledger()
        ids = _link(ledger, [("A", "B", 0.95), ("B", "C", 0.6), ("C", "D", 0.95)])
        ledger.assert_different(ids["A"], ids["D"], by="rev-1", reason="x")
        assert _partition(ledger) == {frozenset({ids["A"], ids["B"]}),
                                      frozenset({ids["C"], ids["D"]})}
        cd = ledger.entity_of(ids["C"])
        assert cd == ledger._entity_id_for("organisation", min(
            [ids["C"], ids["D"]], key=lambda r: ledger._recorded_at([r])[r]))
        _check_invariants(ledger)


class TestContested:
    def test_contradicting_assertions_leave_the_entity_whole(self):
        ledger = _ledger()
        ids = _link(ledger, [("A", "B", 0.9), ("B", "C", 0.9)])
        A, B, C = ids["A"], ids["B"], ids["C"]
        ledger.assert_same(A, B, by="rev-1", reason="r")
        ledger.assert_same(B, C, by="rev-2", reason="r")
        different = ledger.assert_different(A, C, by="rev-3", reason="r")
        assert _partition(ledger) == {frozenset({A, B, C})}
        contested = ledger.contested()
        assert len(contested) == 1 and contested[0]["reason"] == "assertions_contradict"
        assert different.assertion_id in contested[0]["assertions"]

        ledger.retract(different.assertion_id, by="rev-3", reason="mistake")
        assert ledger.contested() == []
        _check_invariants(ledger)


class TestPrecedence:
    def test_retracting_a_different_from_lets_the_computed_link_back(self):
        ledger = _ledger()
        ids = _link(ledger, [("A", "B", 0.9)])
        d = ledger.assert_different(ids["A"], ids["B"], by="rev-1", reason="r")
        assert _partition(ledger) == set()
        ledger.retract(d.assertion_id, by="rev-1", reason="wrong")
        assert _partition(ledger) == {frozenset({ids["A"], ids["B"]})}
        _check_invariants(ledger)

    def test_cannot_tell_neither_links_nor_separates(self):
        ledger = _ledger()
        ids = _link(ledger, [("A", "B", 0.9)])
        ledger.assert_cannot_tell(ids["A"], ids["B"], by="rev-1", reason="r")
        assert _partition(ledger) == {frozenset({ids["A"], ids["B"]})}

    def test_same_as_links_records_no_decision_joined(self):
        ledger = _ledger()
        ids = _link(ledger, [("A", "B", 0.9), ("C", "D", 0.9)])
        ledger.assert_same(ids["B"], ids["C"], by="rev-1", reason="r")
        assert _partition(ledger) == {frozenset(ids.values())}
        _check_invariants(ledger)

    def test_a_newer_assertion_replaces_the_older_on_the_pair(self):
        ledger = _ledger()
        ids = _link(ledger, [("A", "B", 0.9)])
        first = ledger.assert_different(ids["A"], ids["B"], by="rev-1", reason="r")
        second = ledger.assert_same(ids["A"], ids["B"], by="rev-2", reason="r")
        assert second.retracts == first.assertion_id
        assert _partition(ledger) == {frozenset({ids["A"], ids["B"]})}

    def test_assertion_validation(self):
        ledger = _ledger()
        ids = _link(ledger, [("A", "B", 0.9)])
        with pytest.raises(KeyError):
            ledger.assert_same(ids["A"], "rec:hmac-sha256:nope", by="r", reason="r")
        with pytest.raises(ValueError):
            ledger.assert_same(ids["A"], ids["A"], by="r", reason="r")
        with pytest.raises(ValueError):
            ledger.assert_same(ids["A"], ids["B"], by="", reason="r")


class TestMergeAndIds:
    def test_a_merge_keeps_the_id_of_the_entity_founded_first(self):
        ledger = _ledger()
        first = _link(ledger, [("A", "B", 0.9)])
        time.sleep(0.002)
        second = _link(ledger, [("C", "D", 0.9)])
        older = ledger.entity_of(first["A"])
        ledger.assert_same(first["B"], second["C"], by="rev-1", reason="r")
        assert ledger.entity_of(second["D"]) == older
        assert "merge" in [e.kind for e in ledger.lineage(older)]
        _check_invariants(ledger)

    def test_same_operations_give_the_same_ids_on_another_ledger(self):
        def run():
            ledger = _ledger()
            ids = _link(ledger, [("A", "B", 0.95), ("B", "C", 0.71)])
            ledger.assert_different(ids["A"], ids["C"], by="rev-1", reason="r")
            return sorted(e for _, e in ledger._db.execute(
                "SELECT record_id, entity_id FROM arche_memberships").fetchall())
        assert run() == run()  # I7

    def test_withheld_decisions_never_link_later(self):
        ledger = _ledger()
        withheld = _link(ledger, [("A", "B", 0.9)], link=False)
        assert _partition(ledger) == set()
        _link(ledger, [("B", "C", 0.9)])
        assert withheld["A"] not in {r for g in _partition(ledger) for r in g}
        _check_invariants(ledger)


class TestHistory:
    def test_membership_at_a_past_time(self):
        ledger = _ledger()
        ids = _link(ledger, [("A", "B", 0.95), ("B", "C", 0.71)])
        entity = ledger.entity_of(ids["A"])
        time.sleep(0.002)
        from arche.ledger import _now

        before_split = _now()
        time.sleep(0.002)
        ledger.assert_different(ids["A"], ids["C"], by="rev-1", reason="r")
        assert set(ledger.entity(entity, at=before_split).record_ids) == set(ids.values())
        assert set(ledger.entity(entity).record_ids) == {ids["A"], ids["B"]}

    def test_superseding_the_decision_that_held_an_entity_splits_it(self):
        from arche.resolve import compare

        ledger = _ledger()
        a = {"name": "Adebayo Oluwaseun", "dob": "1990-01-01"}
        b = {"name": "Adebayo Oluwaseun", "dob": "1990-01-01", "national_id": "22222222222"}
        r = compare(a, b, entity="person", store=ledger)
        decision = ledger.decision(r.decision_id)
        if not decision.linked:
            pytest.skip("the engine did not link this pair")
        entity = ledger.entity_of(decision.record_a)
        fresh = ledger.observe(decision.record_a, {"national_id": "11111111111"})
        if not fresh or fresh[0].linked:
            pytest.skip("the conflicting id did not change the decision")
        assert ledger.entity_of(decision.record_b) is None
        assert ledger.lineage(entity)[-1].kind == "retire"
        _check_invariants(ledger)


def test_an_existing_ledger_gets_a_migration_history(tmp_path):
    path = tmp_path / "old.duckdb"
    with attach(f"duckdb:///{path}", record_key=KEY) as ledger:
        ids = _link(ledger, [("A", "B", 0.9)])
        entity = ledger.entity_of(ids["A"])
        ledger._db.execute("UPDATE arche_memberships SET entity_id = 'ent_legacyuuid'")
        ledger._db.execute("DELETE FROM arche_lineage")
        ledger._db.execute("DELETE FROM arche_membership_history")
    with attach(f"duckdb:///{path}", record_key=KEY) as ledger:
        assert ledger.entity_of(ids["A"]) == "ent_legacyuuid" != entity
        assert [e.kind for e in ledger.lineage("ent_legacyuuid")] == ["migration"]
        assert ledger.rebuild()["differences"] == []


@pytest.mark.parametrize("seed", range(40))
def test_invariants_hold_on_random_graphs(seed):
    import random

    rng = random.Random(seed)
    ledger = _ledger()
    names = [chr(65 + i) for i in range(rng.randint(3, 9))]
    pairs = {(a, b) for a in names for b in names if a < b and rng.random() < 0.35}
    if not pairs:
        pairs = {(names[0], names[1])}
    ids = _link(ledger, [(a, b, round(rng.uniform(0.7, 1.0), 3)) for a, b in sorted(pairs)])
    known = sorted(ids)
    made = []
    for _ in range(rng.randint(1, 6)):
        a, b = rng.sample(known, 2)
        kind = rng.choice(["same", "different", "different", "cannot", "retract"])
        if kind == "retract" and made:
            ledger.retract(rng.choice(made).assertion_id, by="rev", reason="r")
        elif kind == "same":
            made.append(ledger.assert_same(ids[a], ids[b], by="rev", reason="r"))
        elif kind == "different":
            made.append(ledger.assert_different(ids[a], ids[b], by="rev", reason="r"))
        elif kind == "cannot":
            made.append(ledger.assert_cannot_tell(ids[a], ids[b], by="rev", reason="r"))
        _check_invariants(ledger)
