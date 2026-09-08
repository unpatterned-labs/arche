# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""`arche.schema` and `extract(text, schema=)`: your fields, once.

The declaration a user writes for matching is the schema a model is asked to
extract into: its field names are the labels, its descriptions the
disambiguation, its kinds say which validator outranks the model. These
tests stand the model in with a fake that answers in GLiNER 2's label-keyed
shape, so they run without the extra and without a download; the real model
was run on the same text while this was built.
"""

from __future__ import annotations

import warnings

import arche
import pytest
from arche.declare import Declaration
from arche.doc import _extract as extract_module

TEXT = ("Landing report. Supplier: Kijani Fisheries Cooperative. Vessel IMO 9074729 under "
        "skipper Amina Wanjiru, phone +254 722 123456, landed 1,200 kg of yellowfin at Kilifi "
        "on 3 March 2026. Quota licence KQ-2026-0417.")

DECL = {
    "entity": "catch_lot",
    "id_field": "lot_id",
    "fields": {
        "supplier_name": {"role": "identifies", "kind": ["name", "tftoken"],
                          "description": "Trading name of the landing supplier."},
        "vessel_id": {"role": "identifies", "kind": "id", "id_family": "imo",
                      "description": "IMO vessel number, e.g. IMO-9074729."},
        "skipper_phone": {"role": "identifies", "kind": "phone"},
        "quota_licence": {"role": "identifies", "kind": "id", "id_family": "ng_quota"},
        "port": {"role": "describes", "kind": "name", "pii": False},
        "landing_date": {"role": "describes", "kind": "date"},
        "landed_kg": {"role": "ignore"},
    },
}


def _span(needle, confidence=1.0, text=TEXT):
    start = text.index(needle)
    return {"text": needle, "confidence": confidence, "start": start, "end": start + len(needle)}


RESPONSE = {"entities": {
    "supplier_name": [_span("Kijani Fisheries Cooperative")],
    "vessel_id": [_span("IMO 9074729"), _span("KQ-2026-0417", 0.41)],
    "skipper_phone": [_span("+254 722 123456", 0.97)],
    "quota_licence": [_span("KQ-2026-0417")],
    "port": [_span("Kilifi")],
    "landing_date": [_span("3 March 2026")],
}}


class _FakeExtractor:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def extract_entities(self, text, labels, **kwargs):
        self.calls.append({"text": text, "labels": labels, **kwargs})
        return self.response


@pytest.fixture
def schema():
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return arche.schema(DECL)


@pytest.fixture
def fake_model(monkeypatch):
    model = _FakeExtractor(RESPONSE)
    monkeypatch.setattr("arche._models.get_gliner2", lambda *a, **k: model)
    monkeypatch.setattr(extract_module, "_warned_no_model", False)
    return model


@pytest.fixture
def no_model(monkeypatch):
    def missing(*a, **k):
        raise ImportError("not installed")
    monkeypatch.setattr("arche._models.get_gliner2", missing)
    monkeypatch.setattr(extract_module, "_warned_no_model", False)


# ---------------------------------------------------------------------------
# arche.schema
# ---------------------------------------------------------------------------


def test_schema_loads_a_file_a_dict_or_passes_a_declaration_through(schema):
    from_file = arche.schema("examples/declarations/fisheries.decl.yaml")
    assert isinstance(from_file, Declaration) and from_file.name == "fisheries-landings"
    assert isinstance(schema, Declaration) and schema.entity == "catch_lot"
    assert arche.schema(schema) is schema
    with pytest.raises(TypeError, match="declaration file path, a dict or a Declaration"):
        arche.schema(42)


def test_a_dict_may_omit_the_format_version_and_name(schema):
    # A dict written in code is not the versioned file the format check is for.
    assert schema.name == "catch_lot" and schema.pin().startswith("catch_lot@0:sha256:")


def test_the_labels_are_the_users_fields_with_their_descriptions(schema):
    labels = schema.labels()
    assert labels["vessel_id"] == "IMO vessel number, e.g. IMO-9074729."
    assert labels["skipper_phone"] == "a phone number"          # from the kind
    assert "landed_kg" not in labels                               # role: ignore


def test_the_model_has_every_declared_field_and_none_required(schema):
    model = schema.model()
    assert set(model.model_fields) == set(schema.labels())
    instance = model()                                             # nothing required
    assert instance.vessel_id is None
    assert schema.model() is model                                 # cached by pin


# ---------------------------------------------------------------------------
# extract(text, schema=)
# ---------------------------------------------------------------------------


def test_the_model_is_asked_for_the_declared_labels(schema, fake_model):
    arche.extract(TEXT, schema=schema, backend="auto")
    call = fake_model.calls[-1]
    assert call["labels"] == schema.labels()
    assert call["include_spans"] is True and call["include_confidence"] is True


def test_the_model_proposes_straight_into_the_users_fields(schema, fake_model):
    ex = arche.extract(TEXT, schema=schema, backend="auto")
    assert ex.unresolved == []
    assert ex.record["vessel_id"] == "IMO 9074729"
    assert ex.record["quota_licence"] == "KQ-2026-0417"
    assert ex.fields["vessel_id"].detail == "proposed by the model for vessel_id"
    assert ex.fields["vessel_id"].span == (TEXT.index("IMO 9074729"), TEXT.index("IMO 9074729") + 11)
    assert ex.model == "fastino/gliner2.5-base-v1" and ex.backend == "auto"


def test_a_validator_outranks_the_model_for_the_same_field(schema, fake_model):
    ex = arche.extract(TEXT, schema=schema, backend="auto")
    phone = ex.fields["skipper_phone"]
    assert phone.source == "detector" and phone.detail == "PHONE"
    assert phone.value == "+254 722 123456"


def test_the_highest_confidence_proposal_wins_a_field(schema, fake_model):
    # The model offered the quota code for vessel_id too, at 0.41.
    ex = arche.extract(TEXT, schema=schema, backend="auto")
    assert ex.record["vessel_id"] == "IMO 9074729"


def test_without_a_model_the_validators_answer_and_the_rest_is_named(schema, no_model):
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        ex = arche.extract(TEXT, schema=schema, backend="basic")
    assert ex.record["skipper_phone"] == "+254 722 123456"
    assert "vessel_id" in ex.unresolved and "quota_licence" in ex.unresolved
    assert ex.model is None and ex.pins()["extraction"]["reproducible"] is True
    assert not [w for w in caught if "detect2" in str(w.message)]  # basic asked for no model


def test_auto_without_the_extra_warns_once_and_says_which_extra(schema, no_model):
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        arche.extract(TEXT, schema=schema, backend="auto")
        arche.extract(TEXT, schema=schema, backend="auto")
    # The generic extractor warns on every call (that is `extract()`'s own
    # notice); the schema-specific one -- "no model to ask for your fields" --
    # is said once, and both name the extra.
    schema_said = [w for w in caught if "your fields" in str(w.message)]
    assert len(schema_said) == 1
    assert all("arche-core[detect2]" in str(w.message) for w in schema_said)


def test_an_explicit_model_backend_without_the_extra_raises(schema, no_model):
    with pytest.raises(ImportError):
        arche.extract(TEXT, schema=schema, backend="gliner2")


def test_two_fields_of_one_kind_are_not_both_filled_with_the_same_person(schema, no_model):
    # `supplier_name` and `port` are both `kind: name`. The lexicon finds one
    # PERSON; the generic extractor cannot say which field it belongs to, so
    # neither is filled from it. Two unresolved fields beat one wrong answer
    # written twice.
    ex = arche.extract(TEXT, schema=schema, backend="basic")
    assert "supplier_name" in ex.unresolved and "port" in ex.unresolved


def test_a_suppliers_name_is_never_the_person_who_signed_the_email(no_model):
    # Tried on an onboarding email: `supplier_name` came back as the finance
    # contact, from the lexicon, at a confident 0.70. The declaration says
    # the entity is an organisation; the basic extractor finds no
    # organisations, so the honest answer is unresolved.
    decl = arche.schema({"entity": "organisation", "fields": {
        "supplier_name": {"role": "identifies", "kind": "name"},
        "contact_email": {"role": "describes", "kind": "email"},
    }})
    ex = arche.extract("Please onboard Kijani Tea Exporters Ltd. Contact Amina Wanjiru, "
                       "amina@kijani.co.ke.", schema=decl, backend="basic")
    assert "supplier_name" in ex.unresolved
    assert ex.record["contact_email"] == "amina@kijani.co.ke"


def test_a_lone_field_of_its_kind_may_fall_back_to_the_generic_extractor(no_model):
    decl = arche.schema({"entity": "contact", "fields": {
        "full_name": {"role": "identifies", "kind": "name"},
        "phone": {"role": "identifies", "kind": "phone"},
    }})
    ex = arche.extract("Reach Amina Wanjiru on +254 722 123456.", schema=decl, backend="basic")
    assert ex.record["full_name"] == "Amina Wanjiru" and ex.fields["full_name"].source == "extractor"


def test_doc_extract_and_arche_extract_are_one_function(schema, fake_model):
    from arche.doc import extract as doc_extract

    a = arche.extract(TEXT, schema=schema, backend="auto")
    b = doc_extract(schema, text=TEXT, entity_backend="auto")
    assert a.record == b.record and a.pins() == b.pins()


def test_the_typed_instance_is_the_declaration_model(schema, fake_model):
    ex = arche.extract(TEXT, schema=schema, backend="auto")
    assert ex.data is not None and type(ex.data) is schema.model()
    assert ex.data.vessel_id == "IMO 9074729"
    assert ex.to_dict()["data"]["vessel_id"] == "IMO *******"   # masked by default


# ---------------------------------------------------------------------------
# the same declaration decides
# ---------------------------------------------------------------------------


def test_the_extraction_feeds_compare_under_the_same_schema(schema, fake_model):
    ex_a = arche.extract(TEXT, schema=schema, backend="auto")
    other = ("Catch lot from Kijani Fisheries Co-op, vessel IMO 9074729 (skipper A. Wanjiru, "
             "+254722123456), 1.1 t yellowfin, Kilifi, 3 Mar 2026.")
    fake_model.response = {"entities": {
        "supplier_name": [_span("Kijani Fisheries Co-op", text=other)],
        "vessel_id": [_span("IMO 9074729", text=other)],
        "port": [_span("Kilifi", text=other)],
        "landing_date": [_span("3 Mar 2026", text=other)],
    }}
    ex_b = arche.extract(other, schema=schema, backend="auto")
    receipt = arche.compare(ex_a.reference("lot-1"), ex_b.reference("lot-2"),
                            schema=schema, extra_pins=ex_a.pins())
    assert receipt.identity == "same_entity"
    assert receipt.factors["national_id"] == 1.0                   # vessel_id, declared kind id
    assert receipt.pins["extraction"]["reproducible"] is False
    assert receipt.pins["declaration"] == schema.pin()


def test_schema_and_decl_are_one_argument(schema):
    a = {"lot_id": "1", "vessel_id": "IMO 9074729", "supplier_name": "Kijani Fisheries"}
    b = {"lot_id": "2", "vessel_id": "IMO 9074729", "supplier_name": "Kijani Fisheries Coop"}
    via_schema = arche.compare(a, b, schema=schema)
    via_decl = arche.compare(a, b, decl=schema)
    assert via_schema.decision_id == via_decl.decision_id
    with pytest.raises(ValueError, match="either schema= or decl="):
        arche.compare(a, b, schema=schema, decl=schema)
    result = arche.reconcile([a], [b], schema=schema)
    assert result["matches"][0]["decision"] == "match"


def test_reference_needs_a_declaration():
    from pydantic import BaseModel

    class Contact(BaseModel):
        email: str | None = None

    from arche.doc import extract as doc_extract

    ex = doc_extract(Contact, text="Contact amara@example.com.", entity_backend="basic")
    with pytest.raises(ValueError, match="declaration"):
        ex.reference()


def test_schema_is_on_the_package():
    assert "schema" in arche.__all__ and callable(arche.schema)
