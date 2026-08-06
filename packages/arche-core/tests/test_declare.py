# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""The declaration layer: users say what their fields mean.

Verifies the design record (docs/ARCHE_DECLARATION_LAYER_DESIGN.md):
fail-loud validation, the pin, generated packs, role assignment,
kind→slot pairwise mapping, declaration-aware rendering — and above all
that the no-declaration paths behave exactly as before (the acceptance
test for the whole lane is the existing suite, unchanged).
"""

from __future__ import annotations

import warnings

import pytest
from arche import resolve
from arche.canonical import IdentityAttribute, Reference
from arche.declare import Declaration, DeclarationError
from arche.render import render
from arche.resolve import ENTITY_PACKS

FISHERIES = {
    "arche_declaration": 1,
    "name": "fisheries-landings",
    "version": "1.2.0",
    "entity": "catch_lot",
    "id_field": "lot_id",
    "geo": {"lat": "landing_lat", "lon": "landing_lon", "weight": 1.0},
    "fields": {
        "supplier_name": {"role": "identifies", "kind": ["name", "tftoken"],
                          "weight": 2.0,
                          "description": "Trading name of the supplier."},
        "vessel_id": {"role": "identifies", "kind": "id", "id_family": "imo",
                      "weight": 3.0},
        "quota_licence": {"role": "identifies", "kind": "id",
                          "id_family": "ng_quota", "restricted": True},
        "port": {"role": "describes", "kind": "name", "pii": False},
        "landed_kg": {"role": "ignore"},
    },
}


def _decl(**overrides) -> Declaration:
    raw = {**FISHERIES, **overrides}
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return Declaration.from_dict(raw)


# ── T1: validation is fail-loud with a closed vocabulary ─────────────────────
def test_loads_and_names_fields():
    d = _decl()
    assert d.pin().startswith("fisheries-landings@1.2.0:sha256:")
    assert d.fields["vessel_id"].id_family == "imo"


@pytest.mark.parametrize("mutation, needle", [
    ({"arche_declaration": 2}, "arche_declaration"),
    ({"on_unknown": "explode"}, "on_unknown"),
    ({"geo": {"lat": "x"}}, "lon"),
    ({"typo_key": 1}, "typo_key"),
])
def test_top_level_errors_name_the_offender(mutation, needle):
    with pytest.raises(DeclarationError, match=needle):
        _decl(**mutation)


@pytest.mark.parametrize("spec, needle", [
    ({"role": "restricted"}, "not a role"),
    ({"role": "identifies"}, "requires a kind"),
    ({"role": "identifies", "kind": "vibes"}, "vibes"),
    ({"role": "describes", "kind": "name", "id_family": "x"}, "id_family"),
    ({"role": "identifies", "kind": "id", "id_family": "nin"}, "reserved"),
    ({"role": "identifies", "kind": "id", "restrcited": True}, "restrcited"),
])
def test_field_errors_name_the_offender(spec, needle):
    fields = {**FISHERIES["fields"], "bad_field": spec}
    with pytest.raises(DeclarationError, match=needle):
        _decl(fields=fields)


def test_pin_stable_across_formatting_sensitive_to_weights():
    a = _decl().pin()
    # Same content, different key order (YAML reformat equivalent).
    reordered = {k: FISHERIES[k] for k in reversed(list(FISHERIES))}
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        assert Declaration.from_dict(reordered).pin() == a
    changed = {**FISHERIES,
               "fields": {**FISHERIES["fields"],
                          "vessel_id": {"role": "identifies", "kind": "id",
                                        "id_family": "imo", "weight": 4.0}}}
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        assert Declaration.from_dict(changed).pin() != a


def test_person_pack_round_trips_from_yaml_shape():
    person = {
        "arche_declaration": 1, "name": "person",
        "fields": {
            "name": {"role": "identifies", "kind": ["name", "tftoken"],
                     "weight": 2.0},
            "national_id": {"role": "identifies", "kind": "id", "weight": 3.0},
            "phone": {"role": "identifies", "kind": "phone", "weight": 1.5},
            "email": {"role": "identifies", "kind": "email", "weight": 1.5},
            "address": {"role": "identifies", "kind": "address", "weight": 1.0},
        },
    }
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        d = Declaration.from_dict(person)
    assert d.comparators() == ENTITY_PACKS["person"]


def test_statute_resolution_attaches_citations_and_unions_restriction():
    d = _decl(statute="NDPA-2023",
              fields={**FISHERIES["fields"],
                      "skipper_nin": {"role": "identifies", "kind": "id",
                                      "id_family": "skipper_nin_family",
                                      "statute_class": "PII-2-NIN"}})
    f = d.fields["skipper_nin"]
    assert f.citation                      # e.g. "NDPA-2023 s.30, NIMC Act s.27"
    assert f.restricted is (f.action == "drop") or f.restricted
    with pytest.raises(DeclarationError, match="never be overridden downward"):
        _decl(statute="NDPA-2023",
              fields={**FISHERIES["fields"],
                      "biometric_hash": {"role": "describes",
                                         "statute_class": "PII-6-BIOMETRIC",
                                         "restricted": False}})
    # Defaulted (unwritten) restriction silently unions UP, no error:
    d2 = _decl(statute="NDPA-2023",
               fields={**FISHERIES["fields"],
                       "biometric_hash": {"role": "describes",
                                          "statute_class": "PII-6-BIOMETRIC"}})
    assert d2.fields["biometric_hash"].restricted is True
    # A typo'd statute_class must never silently mean "default action":
    with pytest.raises(DeclarationError, match="not in statute"):
        _decl(statute="NDPA-2023",
              fields={**FISHERIES["fields"],
                      "x": {"role": "describes", "statute_class": "PII-6-BIOMETRC"}})


# ── T2: role assignment in from_record ───────────────────────────────────────
def test_from_record_declaration_wins_over_conventions():
    d = _decl()
    ref = Reference.from_record(
        {"lot_id": "L-9", "vessel_id": "V-99", "supplier_name": "Acme",
         "port": "Lagos", "landed_kg": "12.5"},
        decl=d,
    )
    by_name = {a.name: a for a in ref.attributes}
    assert ref.record_id == "L-9"                       # decl id_field
    assert isinstance(by_name["vessel_id"], IdentityAttribute)
    assert "landed_kg" not in by_name                   # role: ignore
    assert by_name["quota_licence"].restricted if "quota_licence" in by_name \
        else d.fields["quota_licence"].restricted


def test_from_record_on_unknown_error_names_the_field():
    d = _decl(on_unknown="error")
    with pytest.raises(DeclarationError, match="mystery_col"):
        Reference.from_record({"lot_id": "1", "mystery_col": "x"}, decl=d)


def test_validate_record_reports_undeclared_fields():
    d = _decl()
    ref, violations = d.validate_record(
        {"lot_id": "1", "vessel_id": "V-1", "hallucinated": "zzz"})
    assert violations == ["undeclared field 'hallucinated'"]
    assert ref.record_id == "1"


# ── T3: crosswalk with a declaration ─────────────────────────────────────────
def test_crosswalk_links_on_declared_identifier():
    d = _decl()
    a = [{"lot_id": "a1", "supplier_name": "Acme Fisheries",
          "vessel_id": "IMO-9074729"}]
    b = [{"lot_id": "b1", "supplier_name": "ACME Fisheries Ltd",
          "vessel_id": "IMO-9074729"}]
    out = resolve.crosswalk(a, b, decl=d, block=None)
    assert out["matches"][0]["decision"] == "match"
    assert "vessel_id" in out["matches"][0]["evidence"]


def test_crosswalk_rejects_decl_plus_entity():
    with pytest.raises(ValueError, match="not both"):
        resolve.crosswalk([], [], decl=_decl(), entity="person")


def test_date_kind_scores_in_crosswalk():
    out = resolve.crosswalk(
        [{"id": "a", "d": "1985-03-15"}], [{"id": "b", "d": "1985-03-15"}],
        comparators=[{"field": "d", "kind": "date", "weight": 1.0},
                     {"field": "d", "kind": "name", "weight": 0.1}],
        block=None,
    )
    assert out["matches"], "date agreement should surface the pair"


# ── T4: pairwise via declared kind → person-shaped slot ──────────────────────
def test_pairwise_exact_declared_id_reaches_same_entity():
    d = _decl()
    ra = Reference.from_record(
        {"lot_id": "a", "supplier_name": "Acme Fisheries",
         "vessel_id": "IMO-9074729"}, decl=d)
    rb = Reference.from_record(
        {"lot_id": "b", "supplier_name": "Acme Fisheries Limited",
         "vessel_id": "IMO-9074729"}, decl=d)
    key = b"declaration-tests-issuer-key-32b"
    decision = resolve.pairwise(ra, rb, issuer_key=key, decl=d)
    assert decision.identity == "same_entity"
    assert decision.pins["declaration"] == d.pin()


def test_pairwise_declared_id_conflict_vetoes():
    d = _decl()
    ra = Reference.from_record(
        {"lot_id": "a", "supplier_name": "Acme Fisheries",
         "vessel_id": "IMO-9074729"}, decl=d)
    rb = Reference.from_record(
        {"lot_id": "b", "supplier_name": "Acme Fisheries",
         "vessel_id": "IMO-1111111"}, decl=d)
    key = b"declaration-tests-issuer-key-32b"
    decision = resolve.pairwise(ra, rb, issuer_key=key, decl=d)
    assert decision.identity == "different"


def test_decision_id_moves_with_the_declaration():
    base = _decl()
    heavier = _decl(fields={**FISHERIES["fields"],
                            "vessel_id": {"role": "identifies", "kind": "id",
                                          "id_family": "imo", "weight": 4.0}})
    key = b"declaration-tests-issuer-key-32b"
    rec = {"lot_id": "a", "supplier_name": "Acme", "vessel_id": "IMO-1"}
    ra1 = Reference.from_record(rec, decl=base)
    ra2 = Reference.from_record(rec, decl=heavier)
    d1 = resolve.pairwise(ra1, ra1, issuer_key=key, decl=base)
    d2 = resolve.pairwise(ra2, ra2, issuer_key=key, decl=heavier)
    assert d1.decision_id != d2.decision_id


# ── T5: declaration-aware rendering ──────────────────────────────────────────
def test_render_pii_false_is_the_only_route_to_clear_text():
    d = _decl()
    rec = {"supplier_name": "Acme Fisheries", "port": "Lagos",
           "quota_licence": "Q-778"}
    out = render(rec, decl=d)
    assert out["supplier_name"] == "[SUPPLIER_NAME]"
    assert out["port"] == "Lagos"                          # declared pii: false
    assert out["quota_licence"] == "[RESTRICTED:QUOTA_LICENCE]"
    revealed = render(rec, decl=d, reveal=True)
    assert revealed["quota_licence"] == "[RESTRICTED:QUOTA_LICENCE]"  # always
    assert revealed["supplier_name"] == "Acme Fisheries"


# ── T6: the CLI surface ──────────────────────────────────────────────────────
def test_cli_schema_validate_and_gen(tmp_path, capsys):
    import yaml
    from arche.cli import main
    decl_path = tmp_path / "d.yaml"
    decl_path.write_text(yaml.safe_dump(FISHERIES), encoding="utf-8")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        assert main(["schema", "validate", str(decl_path)]) == 0
    out = capsys.readouterr().out
    assert "fisheries-landings@1.2.0:sha256:" in out

    bad = tmp_path / "bad.yaml"
    bad.write_text("arche_declaration: 1\nname: x\nfields:\n  f: {role: nope}\n",
                   encoding="utf-8")
    assert main(["schema", "validate", str(bad)]) == 1

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        assert main(["schema", "gen", str(decl_path), "--format", "openai"]) == 0
    tool = capsys.readouterr().out
    assert '"strict": true' in tool
    assert '"additionalProperties": false' in tool
    assert "landed_kg" not in tool                       # role: ignore excluded


def test_cli_compare_with_schema_end_to_end(tmp_path):
    import json as _json

    import yaml
    from arche.cli import main
    decl_path = tmp_path / "d.yaml"
    decl_path.write_text(yaml.safe_dump(FISHERIES), encoding="utf-8")
    a = tmp_path / "a.csv"
    b = tmp_path / "b.csv"
    a.write_text("lot_id,supplier_name,vessel_id,port\n"
                 "L1,Acme Fisheries,IMO-9074729,Lagos\n", encoding="utf-8")
    b.write_text("lot_id,supplier_name,vessel_id,port\n"
                 "R1,ACME Fisheries Ltd,IMO-9074729,Lagos\n", encoding="utf-8")
    out = tmp_path / "r.html"
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        rc = main(["compare", str(a), str(b), "--schema", str(decl_path),
                   "--block", "none", "--out", str(out)])
    assert rc == 0
    html = out.read_text(encoding="utf-8")
    assert "fisheries-landings@1.2.0:sha256:" in html    # pin on the artifact
    assert "Acme Fisheries" not in html                  # masked by default
    assert "Lagos" in html                               # declared pii: false
    sidecar = _json.loads((tmp_path / "r.json").read_text(encoding="utf-8"))
    assert sidecar["result"]["matches"][0]["decision"] == "match"


def test_shipped_example_declarations_load_and_round_trip():
    from pathlib import Path

    root = Path(__file__).resolve().parents[3]
    examples = root / "examples" / "declarations"
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        person = Declaration.from_yaml(examples / "person.decl.yaml")
        artist = Declaration.from_yaml(examples / "artist.decl.yaml")
        fisheries = Declaration.from_yaml(examples / "fisheries.decl.yaml")
    assert person.comparators() == ENTITY_PACKS["person"]
    assert artist.comparators() == ENTITY_PACKS["artist"]
    assert fisheries.fields["skipper_phone"].citation   # statute resolved
