# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Ledger integrity: keyed record ids, receipts never rewritten, erasure.

Three defects found in review (20 Nov 2026): record ids were an unkeyed hash of
the raw input, so an id shared in a receipt could be brute-forced back to a
low-entropy value; superseding a decision rewrote the receipt's row; and
`resolve` attached source text to a record after it was written.
"""

from __future__ import annotations

import hashlib

import duckdb
import pytest
from arche.ids import content_hash
from arche.ledger import Ledger, attach

A = {"id": "a", "name": "Oyono Chemicals Global Ltd", "address": "23 Zaria Road, Enugu"}
B = {"id": "b", "name": "Oyono Chemicals Global", "address": "23 Zaria Road, Enugu"}


def _batch(ledger: Ledger):
    from arche.resolve import reconcile

    result = reconcile([A], [B], entity="organisation", id_field="id")
    return ledger.record_batch(result, [A], [B],
                               call={"entity": "organisation", "id_field": "id"})


def _record_ids(ledger: Ledger) -> set[str]:
    return {r[0] for r in ledger._db.execute("SELECT record_id FROM arche_records").fetchall()}


class TestKeyedRecordIds:
    def test_a_new_ledger_keys_its_record_ids(self):
        ledger = attach("duckdb:///:memory:")
        _batch(ledger)
        ids = _record_ids(ledger)
        assert ids and all(i.startswith("rec:hmac-sha256:") for i in ids)
        unkeyed = content_hash({"entity_type": "organisation",
                                "attributes": {k: v for k, v in A.items()}}, prefix="rec")
        assert unkeyed not in ids

    def test_two_ledgers_give_one_record_different_ids(self):
        one, two = attach("duckdb:///:memory:"), attach("duckdb:///:memory:")
        _batch(one), _batch(two)
        assert not (_record_ids(one) & _record_ids(two))

    def test_a_shared_key_gives_shared_ids_and_is_not_stored(self):
        key = b"k" * 32
        one = attach("duckdb:///:memory:", record_key=key)
        two = attach("duckdb:///:memory:", record_key=key)
        _batch(one), _batch(two)
        assert _record_ids(one) == _record_ids(two)
        meta = dict(one._db.execute("SELECT key, value FROM arche_meta").fetchall())
        assert "record_key" not in meta and key.hex() not in str(meta)

    def test_reopening_keeps_the_ids(self, tmp_path):
        path = tmp_path / "l.duckdb"
        with attach(f"duckdb:///{path}") as ledger:
            _batch(ledger)
            before = _record_ids(ledger)
        with attach(f"duckdb:///{path}") as ledger:
            _batch(ledger)
            assert _record_ids(ledger) == before

    def test_a_wrong_or_missing_external_key_is_refused(self, tmp_path):
        path = tmp_path / "l.duckdb"
        attach(f"duckdb:///{path}", record_key=b"a" * 32).close()
        with pytest.raises(ValueError, match="does not match"):
            attach(f"duckdb:///{path}", record_key=b"b" * 32)
        with pytest.raises(ValueError, match="pass record_key"):
            attach(f"duckdb:///{path}")
        attach(f"duckdb:///{path}", record_key=b"a" * 32).close()

    def test_a_ledger_from_before_keyed_ids_keeps_unkeyed_ids(self, tmp_path):
        # Simulate a pre-existing ledger: records, and no arche_meta setting.
        path = tmp_path / "old.duckdb"
        with attach(f"duckdb:///{path}") as ledger:
            ledger._db.execute("DELETE FROM arche_meta")
            ledger._db.execute(
                "INSERT INTO arche_records VALUES ('rec:sha256:old', 'organisation', 's', "
                "NULL, '{}', NULL, '2026-01-01T00:00:00')")
        with attach(f"duckdb:///{path}") as ledger:
            _batch(ledger)
            new = _record_ids(ledger) - {"rec:sha256:old"}
            assert new and all(i.startswith("rec:sha256:") for i in new)
        with pytest.raises(ValueError, match="predates keyed"):
            attach(f"duckdb:///{path}", record_key=b"a" * 32)


class TestReceiptsAreNotRewritten:
    def test_superseding_writes_a_supersession_not_the_decision_row(self):
        ledger = attach("duckdb:///:memory:")
        from arche.resolve import compare

        a = {"name": "Adebayo Oluwaseun", "dob": "1990-01-01"}
        b = {"name": "Adebayo Oluwasegun", "dob": "1990-01-01"}
        r = compare(a, b, entity="person", store=ledger)
        before = ledger._db.execute(
            "SELECT * FROM arche_decisions WHERE decision_id = ?", [r.decision_id]).fetchone()
        fresh = ledger.observe(ledger.decision(r.decision_id).record_a,
                               {"national_id": "12345678901"})
        if not fresh:
            pytest.skip("observe produced no re-decision for this pair")
        after = ledger._db.execute(
            "SELECT * FROM arche_decisions WHERE decision_id = ?", [r.decision_id]).fetchone()
        assert after == before, "the receipt row changed"
        assert ledger.decision(r.decision_id).superseded_by == fresh[0].decision_id
        rows = ledger._db.execute("SELECT decision_id, superseded_by FROM arche_supersessions"
                                  ).fetchall()
        assert (r.decision_id, fresh[0].decision_id) in rows

    def test_a_legacy_superseded_by_column_is_still_read(self):
        ledger = attach("duckdb:///:memory:")
        decision = _batch(ledger)[0]
        ledger._db.execute("UPDATE arche_decisions SET superseded_by = 'legacy' "
                           "WHERE decision_id = ?", [decision.decision_id])
        assert ledger.decision(decision.decision_id).superseded_by == "legacy"


class TestResolveWritesTextOnce:
    def test_no_code_path_updates_a_record_except_forget(self):
        import inspect

        import arche.ledger as mod

        source = inspect.getsource(mod)
        updates = [line.strip() for line in source.splitlines()
                   if "UPDATE arche_records" in line]
        assert len(updates) == 1 and "SET attributes = '{}'" in updates[0]
        assert "UPDATE arche_decisions" not in source


class TestForget:
    def test_content_goes_ids_and_decisions_stay(self):
        ledger = attach("duckdb:///:memory:")
        decision = _batch(ledger)[0]
        rid = decision.record_a
        ledger.forget(rid, reason="erasure request")
        record = ledger.record(rid)
        assert record.attributes == {} and record.text is None and record.caller_id is None
        assert ledger.decision(decision.decision_id).record_a == rid
        events = [e for e in ledger.events() if e.kind == "record_forgotten"]
        assert events and events[-1].refs == {"record_id": rid}
        assert "Oyono" not in str(ledger._db.execute("SELECT * FROM arche_records "
                                                     "WHERE record_id = ?", [rid]).fetchall())

    def test_unknown_record(self):
        with pytest.raises(KeyError):
            attach("duckdb:///:memory:").forget("rec:hmac-sha256:nope")

    def test_the_raw_value_is_not_in_the_events(self):
        ledger = attach("duckdb:///:memory:")
        decision = _batch(ledger)[0]
        ledger.forget(decision.record_a)
        assert "Oyono" not in str(ledger._db.execute(
            "SELECT refs, note FROM arche_events WHERE kind = 'record_forgotten'").fetchall())


def test_fingerprint_is_not_the_key():
    from arche.ledger import _fingerprint

    key = b"s" * 32
    assert _fingerprint(key) != key.hex()
    assert _fingerprint(key) != hashlib.sha256(key).hexdigest()


def test_duckdb_is_what_we_think():
    assert duckdb.__version__


def test_entity_survives_records_disagreeing_on_a_dict_field():
    # Found by the end-to-end demo (21 Nov 2026): a mention's admin_path has no
    # ward and the reference's has one; `entity()` raised TypeError.
    from datetime import UTC, datetime

    from arche.ledger import Record, _agreement

    def rec(rid, attrs):
        return Record(rid, "place", "s", None, attrs, None, datetime.now(UTC))

    a = rec("a", {"name": "Zango", "admin_path": {"admin1": "kano", "admin2": "dala"}})
    b = rec("b", {"name": "Zango", "admin_path": {"admin2": "dala", "admin1": "kano",
                                                   "admin3": "zango"}})
    shared, conflicts = _agreement([a, b])
    assert shared == {"name": "Zango"} and len(conflicts["admin_path"]) == 2
    same_order_swapped = rec("c", {"admin_path": {"admin2": "dala", "admin1": "kano"}})
    assert "admin_path" in _agreement([a, same_order_swapped])[0]


def test_entities_survive_reconcile_with_disagreeing_dict_and_list_fields():
    # The same defect end to end: `reconcile(..., store=ledger)` writes the
    # records, then `entities()` builds the view over them.
    from arche.jurisdictions.nigeria import admin_path
    from arche.resolve import reconcile

    ledger = attach("duckdb:///:memory:")
    mention = {"id": "m", "name": "Aminu Kano Teaching Hospital",
               "admin_path": admin_path("Kano", "Tarauni"), "tags": ["tertiary"]}
    grid3 = {"id": "g", "name": "Aminu Kano Teaching Hospital",
             "admin_path": admin_path("Kano", "Tarauni", "Darmanawa"),
             "tags": ["tertiary", "teaching"]}
    reconcile([mention], [grid3], entity="health_facility", store=ledger)

    (view,) = ledger.entities("health_facility")
    assert view.shared == {"name": "Aminu Kano Teaching Hospital"}
    # The original values, one each, not their normalised keys. Member order
    # follows the keyed record ids, so compare without order.
    from arche.ids import canonical_json

    def as_set(values):
        return sorted(map(canonical_json, values))

    assert as_set(view.conflicts["admin_path"]) == as_set(
        [mention["admin_path"], grid3["admin_path"]])
    assert as_set(view.conflicts["tags"]) == as_set([["tertiary"], ["tertiary", "teaching"]])
    assert ledger.entity(view.entity_id).conflicts == view.conflicts
