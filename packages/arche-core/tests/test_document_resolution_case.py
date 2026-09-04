# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""The document front door proposes fields and opens cases conservatively."""

from __future__ import annotations

import pytest
from arche import resolve_documents

_TEA_SHIPMENT = """\
Supplier: Kijani Tea Exporters Ltd
Distributor: Nairobi Tea Trading Ltd
Estate: Kericho Highlands Estate
Registration ID: C.12345
Country: Kenya
"""


def _shipment(tmp_path):
    path = tmp_path / "tea-shipment.txt"
    path.write_text(_TEA_SHIPMENT, encoding="utf-8")
    return path


def _resolve(path, candidates, **kwargs):
    return resolve_documents(
        path,
        entity="organisation",
        candidates=candidates,
        jurisdiction="KE",
        quiet=True,
        progress=False,
        extraction_backend="regex",
        **kwargs,
    )


def test_labelled_tea_fields_are_proposed_and_match_an_explicit_candidate(tmp_path):
    report = _resolve(
        _shipment(tmp_path),
        [{"entity_id": "ent_kijani", "name": "Kijani Tea Exporters Limited", "country": "Kenya"}],
    )

    record = report.records["tea-shipment.txt"]
    assert record["supplier_name"] == "Kijani Tea Exporters Ltd"
    assert record["distributor_name"] == "Nairobi Tea Trading Ltd"
    assert record["estate_name"] == "Kericho Highlands Estate"
    assert record["registration_id"] == "C.12345"
    assert report.decisions[0]["identity"] == "same_entity"
    assert report.decisions[0]["status"] == "proposed"
    assert not report.cases

    review = report.review(reveal=True)
    supplier = next(
        field for field in review["proposed_fields"] if field["field"] == "supplier_name"
    )
    assert supplier == {
        "document": "tea-shipment.txt",
        "field": "supplier_name",
        "value": "Kijani Tea Exporters Ltd",
        "source": "document_label",
        "confidence": 0.9,
        "span": [10, 34],
    }


def test_unresolved_document_opens_value_free_case_with_permitted_actions(tmp_path):
    report = _resolve(
        _shipment(tmp_path),
        [{"entity_id": "ent_kericho", "name": "Kericho Highlands Processing", "country": "Kenya"}],
    )

    assert report.decisions[0]["identity"] == "different"
    assert len(report.cases) == 1
    case_id, case = next(iter(report.cases.items()))
    assert case.candidate_entity_ids == ("ent_kericho",)
    assert case.evidence_gaps[0].field == "registration_id"
    assert {action.action_type for action in report.permitted_actions[case_id]} == {
        "registry_lookup"
    }
    assert report.observations["tea-shipment.txt"].provenance["kind"] == "document_input"

    review = report.review(case_id)
    assert review["cases"][0]["case_id"] == case.case_id
    assert "Kijani Tea Exporters Ltd" not in str(review)
    assert "Kijani Tea Exporters Ltd" not in str(case)


def test_unresolved_document_case_persists_idempotently_to_caller_store(tmp_path):
    from arche.runtime import attach

    report = _resolve(
        _shipment(tmp_path),
        [{"entity_id": "ent_kericho", "name": "Kericho Highlands Processing"}],
    )
    case_id, case = next(iter(report.cases.items()))
    engine = attach(f"duckdb:///{tmp_path / 'tea-cases.duckdb'}")

    persisted = report.persist(engine)

    assert persisted == report.persist(engine)
    assert persisted["case_ids"] == [case_id]
    observation_id = persisted["observation_ids"][0]
    assert engine.store.get_observation(observation_id) == report.observations["tea-shipment.txt"]
    assert engine.store.get_resolution_case(case_id) == case
    assert engine.store.get_evidence_action(persisted["action_ids"][0]) is not None
    assert "Kijani Tea Exporters Ltd" not in str(persisted)


def test_document_candidate_pairs_are_bounded(tmp_path):
    with pytest.raises(ValueError, match="Narrow candidates first"):
        _resolve(
            _shipment(tmp_path),
            [
                {"entity_id": "ent_one", "name": "Kijani Tea Exporters Ltd"},
                {"entity_id": "ent_two", "name": "Kijani Tea Exporters Limited"},
            ],
            max_candidate_pairs=1,
        )


def test_missing_registration_field_permits_document_extraction_before_lookup(tmp_path):
    path = tmp_path / "tea-shipment.txt"
    path.write_text(_TEA_SHIPMENT.replace("Registration ID: C.12345\n", ""), encoding="utf-8")

    report = _resolve(path, [{"entity_id": "ent_kericho", "name": "Kericho Highlands Processing"}])

    case_id = next(iter(report.cases))
    assert {action.action_type for action in report.permitted_actions[case_id]} == {
        "document_extract",
        "registry_lookup",
    }
