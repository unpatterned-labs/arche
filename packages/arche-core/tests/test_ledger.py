# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""The ledger: record, look up, replay, link, observe.

Three pieces of text about one person are the running example. Two of them
share a national id and disagree on an email; the third agrees with the second
on both. Pairwise the engine says ``same_entity`` three times, twice with
``hold``; the ledger's job is to notice that those three verdicts describe one
entity, keep the receipts, and make any of them again on request.
"""

from __future__ import annotations

import subprocess
import sys

import arche
import pytest

duckdb = pytest.importorskip("duckdb")

T1 = "Adesola Okonkwo, NIN 12345678901, address: 123 Maple Street, adesola@example.com"
T2 = "Adesola Okonkwo, NIN 12345678901, adesola@gmail.com, address: 124 Maple Street"
T3 = "Adesola E. Okonkwo, NIN 12345678901, adesola@gmail.com, address: 231 Elim Street"
PERSON = dict(entity="person", jurisdiction="NG", backend="regex")

SUPPLIERS = [
    {"id": "s1", "name": "Kijani Tea Exporters Ltd", "city": "Nairobi"},
    {"id": "s2", "name": "Zenith Bank Plc", "city": "Lagos"},
]
REGISTRY = [
    {"id": "r1", "name": "Kijani Tea Exporters Limited", "city": "Nairobi"},
    {"id": "r2", "name": "Kijani Coffee", "city": "Nairobi"},
]


@pytest.fixture
def ledger():
    with arche.attach("duckdb:///:memory:") as book:
        yield book


# ── opening ──────────────────────────────────────────────────────────────────


def test_attach_opens_a_ledger_and_schema_is_idempotent(ledger):
    ledger.ensure_schema()
    ledger.ensure_schema()
    assert ledger.entities() == []
    assert ledger.events() == ()


def test_attach_rejects_anything_but_duckdb():
    with pytest.raises(ValueError, match="duckdb:///"):
        arche.attach("sqlite:///arche.db")
    with pytest.raises(ValueError, match="database path"):
        arche.attach("duckdb:///")


def test_importing_arche_does_not_import_duckdb():
    result = subprocess.run(
        [sys.executable, "-c", "import sys, arche; assert 'duckdb' not in sys.modules"],
        check=False, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr


# ── recording a pairwise decision ────────────────────────────────────────────


def test_store_does_not_change_the_receipt(ledger):
    with_store = arche.compare(T1, T2, store=ledger, **PERSON)
    without = arche.compare(T1, T2, **PERSON)
    assert with_store.decision_id == without.decision_id
    assert (with_store.identity, with_store.action) == (without.identity, without.action)


def test_a_decision_can_be_found_by_its_id(ledger):
    receipt = arche.compare(T1, T2, store=ledger, **PERSON)

    found = ledger.decision(receipt.decision_id)

    assert found.verb == "compare"
    assert (found.identity, found.action) == ("same_entity", "hold")
    assert found.factors["national_id"] == 1.0
    assert found.pins == receipt.pins
    assert found.call == {"entity": "person", "jurisdiction": "NG", "backend": "regex"}
    # the inputs are kept, as given, so the decision can be made again
    assert ledger.record(found.record_a).text == T1
    assert ledger.record(found.record_b).text == T2
    assert ledger.record(found.record_a).attributes["national_id"] == "12345678901"


def test_recording_the_same_receipt_twice_writes_nothing_new(ledger):
    arche.compare(T1, T2, store=ledger, **PERSON)
    before = len(ledger.events())
    arche.compare(T1, T2, store=ledger, **PERSON)
    assert len(ledger.events()) == before


def test_unknown_decision_raises_key_error(ledger):
    with pytest.raises(KeyError, match="no decision"):
        ledger.decision("dec:sha256:nope")


def test_a_pipeline_result_cannot_be_stored(ledger):
    a = arche.Pipeline(jurisdiction="NG").process(T1)
    b = arche.Pipeline(jurisdiction="NG").process(T2)
    with pytest.raises(TypeError, match="cannot be stored"):
        arche.compare(a, b, store=ledger)


# ── linking: three receipts, one person ──────────────────────────────────────


def test_three_texts_become_one_entity_with_shared_and_conflicting_attributes(ledger):
    arche.compare(T1, T2, store=ledger, **PERSON)
    arche.compare(T1, T3, store=ledger, **PERSON)
    arche.compare(T2, T3, store=ledger, **PERSON)

    entities = ledger.entities()

    assert len(entities) == 1
    person = entities[0]
    assert person.entity_type == "person"
    assert len(person.records) == 3
    assert person.shared == {"national_id": "12345678901"}
    assert set(person.conflicts) == {"email"}
    assert set(person.conflicts["email"]) == {"adesola@example.com", "adesola@gmail.com"}
    assert len(person.decision_ids) == 3
    kinds = [event.kind for event in ledger.events()]
    assert kinds.count("entity_created") == 1
    assert "record_linked" in kinds


def test_separate_entities_merge_when_a_later_decision_links_them(ledger):
    # 1↔2 and 3↔4 first: two entities. Then 2↔3: one.
    t4 = "Adesola Okonkwo, NIN 12345678901, adesola@gmail.com, phone 08035557890"
    arche.compare(T1, T2, store=ledger, **PERSON)
    arche.compare(T3, t4, store=ledger, **PERSON)
    assert len(ledger.entities()) == 2

    arche.compare(T2, T3, store=ledger, **PERSON)

    assert len(ledger.entities()) == 1
    assert len(ledger.entities()[0].records) == 4
    assert any(event.kind == "entities_merged" for event in ledger.events())


def test_review_does_not_link(ledger):
    result = arche.reconcile(SUPPLIERS, REGISTRY, entity="organisation", store=ledger)
    review = [m for m in result["matches"] if m["decision"] == "review"]
    assert review, "fixture must produce a review edge"
    decision = ledger.decision(review[0]["decision_id"])
    assert not decision.linked
    assert ledger.entity_of(decision.record_b) is None


# ── explain ──────────────────────────────────────────────────────────────────


def test_explain_separates_supporting_refuting_and_missing(ledger):
    receipt = arche.compare(T1, T2, store=ledger, **PERSON)

    why = ledger.explain(receipt.decision_id)

    assert why["identity"] == "same_entity"
    assert why["action"] == "hold"
    assert why["supporting"] == ["national_id"]
    assert why["refuting"] == ["email"]
    assert "name" in why["missing"] and "phone" in why["missing"]
    assert why["shared"] == {"national_id": "12345678901"}


# ── replay ───────────────────────────────────────────────────────────────────


def test_replay_reproduces_a_fresh_decision(ledger):
    receipt = arche.compare(T1, T2, store=ledger, **PERSON)

    replay = ledger.replay(receipt.decision_id)

    assert replay.reproduced is True
    assert replay.changed == {}
    assert replay.now["decision_id"] == receipt.decision_id


def test_replay_names_the_pin_that_moved(ledger, monkeypatch):
    receipt = arche.compare(T1, T2, store=ledger, **PERSON)
    monkeypatch.setattr(arche, "__version__", "99.0.0")

    replay = ledger.replay(receipt.decision_id)

    assert replay.reproduced is False
    assert set(replay.changed) == {"pins.engine"}
    assert replay.changed["pins.engine"]["now"] == "arche-core@99.0.0"
    assert replay.then.identity == replay.now["identity"]


def test_replay_of_a_batch_edge_reruns_the_whole_batch(ledger):
    result = arche.reconcile(SUPPLIERS, REGISTRY, entity="organisation", store=ledger)

    for edge in result["matches"]:
        replay = ledger.replay(edge["decision_id"])
        assert replay.reproduced is True, (edge["a_id"], edge["b_id"], replay.changed)
        assert replay.then.verb == "reconcile"
        assert replay.then.run_id is not None


def test_replay_refuses_when_an_input_could_not_be_stored(ledger):
    from arche.declare import Declaration

    decl = Declaration.from_dict({
        "arche_declaration": 1, "name": "supplier", "entity": "organisation",
        "id_field": "id",
        "fields": {
            "name": {"role": "identifies", "kind": ["name", "tftoken"], "weight": 2.0},
            "city": {"role": "describes", "kind": "name", "pii": False},
        },
    })
    result = arche.reconcile(SUPPLIERS, REGISTRY, decl=decl, store=ledger)
    edge = result["matches"][0]
    assert ledger.decision(edge["decision_id"]).call["_unreplayable"] == ["decl"]
    with pytest.raises(ValueError, match="decl"):
        ledger.replay(edge["decision_id"])


# ── batch verbs ──────────────────────────────────────────────────────────────


def test_reconcile_records_every_edge_and_both_lists(ledger):
    result = arche.reconcile(SUPPLIERS, REGISTRY, entity="organisation", store=ledger)

    for edge in result["matches"]:
        decision = ledger.decision(edge["decision_id"])
        assert decision.identity == edge["decision"]
        assert decision.evidence["a_id"] == edge["a_id"]
        assert ledger.record(decision.record_a).caller_id == edge["a_id"]
        assert ledger.record(decision.record_a).attributes["id"] == edge["a_id"]
    match = next(m for m in result["matches"] if m["decision"] == "match")
    entity = ledger.entities("organisation")[0]
    assert {r.caller_id for r in entity.records} == {match["a_id"], match["b_id"]}
    assert "name" in entity.conflicts  # Ltd vs Limited: same thing, not the same string


def test_dedupe_records_no_self_pairs_and_no_mirrors(ledger):
    records = [*SUPPLIERS, {"id": "s3", "name": "Kijani Tea Exporters", "city": "Nairobi"}]
    result = arche.dedupe(records, entity="organisation", store=ledger)

    recorded = [d for d in ledger.history(ledger.entities()[0].records[0].record_id)]
    assert all(d.record_a != d.record_b for d in recorded)
    assert len({d.decision_id for d in recorded}) == len(recorded)
    assert len(ledger.entities()) == result["cluster_count"] - 1  # the singleton is no entity


def test_find_records_its_candidates(ledger):
    result = arche.find(REGISTRY[0], SUPPLIERS, entity="organisation", store=ledger)
    assert result["verdict"] == "found"
    decision = ledger.decision(result["match"]["decision_id"])
    assert decision.verb == "find"
    assert decision.linked


# ── cases and observe ────────────────────────────────────────────────────────


def test_cases_list_open_review_pairs_with_guidance(ledger):
    arche.reconcile(SUPPLIERS, REGISTRY, entity="organisation", store=ledger)

    cases = ledger.cases()

    assert len(cases) == 1
    case = cases[0]
    assert case.decision.identity == "review"
    assert case.record_a.caller_id == "s1" and case.record_b.caller_id == "r2"
    assert case.would_resolve, "an open pair must say what would settle it"
    assert case.why["identity"] == "review"


def test_observe_adds_evidence_and_supersedes_the_open_decisions(ledger):
    r13 = arche.compare(T1, T3, store=ledger, **PERSON)
    r23 = arche.compare(T2, T3, store=ledger, **PERSON)
    third = ledger.decision(r13.decision_id).record_b
    assert ledger.record(third).text == T3

    fresh = ledger.observe(third, {"name": "Adesola Okonkwo"})

    assert {d.supersedes for d in fresh} == {r13.decision_id, r23.decision_id}
    assert all(d.identity == "same_entity" for d in fresh)
    assert ledger.decision(r13.decision_id).superseded_by in {d.decision_id for d in fresh}
    assert ledger.decision(r13.decision_id).open is False
    prior = ledger.decision(fresh[0].supersedes)
    new_side = fresh[0].record_b if fresh[0].record_a == prior.record_a else fresh[0].record_a
    assert ledger.record(new_side).attributes["name"] == "Adesola Okonkwo"
    kinds = [event.kind for event in ledger.events()]
    assert "observation_recorded" in kinds and kinds.count("decision_superseded") == 2
    # The enriched record joins the entity its predecessor was in; the untouched
    # side is not stored a second time under a different content address.
    assert len(ledger.entities()) == 1
    assert ledger.entity_of(new_side) == ledger.entity_of(ledger.decision(r13.decision_id).record_a)
    assert kinds.count("entity_created") == 1


def test_history_is_newest_first_and_covers_both_sides(ledger):
    r12 = arche.compare(T1, T2, store=ledger, **PERSON)
    r13 = arche.compare(T1, T3, store=ledger, **PERSON)
    first = ledger.decision(r12.decision_id).record_a

    history = ledger.history(first)

    assert [d.decision_id for d in history] == [r13.decision_id, r12.decision_id]


# ── documents ────────────────────────────────────────────────────────────────


def test_resolve_documents_records_into_the_ledger(ledger, tmp_path):
    for name, text in (("a.txt", T1), ("b.txt", T2), ("c.txt", T3)):
        (tmp_path / name).write_text(text, encoding="utf-8")

    report = arche.resolve_documents(
        str(tmp_path / "*.txt"), jurisdiction="NG", extraction_backend="regex",
        progress=False, store=ledger,
    )

    assert len(report.decisions) == 3
    assert report.unlinked() == []
    entity = ledger.entities("person")[0]
    assert {r.caller_id for r in entity.records} == {"a.txt", "b.txt", "c.txt"}
    assert entity.shared == {"national_id": "12345678901"}
    replay = ledger.replay(report.decisions[0]["decision_id"])
    assert replay.reproduced is True, replay.changed
