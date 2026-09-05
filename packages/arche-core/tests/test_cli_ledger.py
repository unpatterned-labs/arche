# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""The ledger from the shell: compare --text, then decision / explain / replay / entities /
cases / observe."""

from __future__ import annotations

import json

import pytest
from arche.cli import main

pytest.importorskip("duckdb")

T1 = "Adesola Okonkwo, NIN 12345678901, address: 123 Maple Street, adesola@example.com"
T2 = "Adesola Okonkwo, NIN 12345678901, adesola@gmail.com, address: 124 Maple Street"
T3 = "Adesola E. Okonkwo, NIN 12345678901, adesola@gmail.com, address: 231 Elim Street"


def _json(capsys) -> dict:
    return json.loads(capsys.readouterr().out)


@pytest.fixture
def store(tmp_path):
    return str(tmp_path / "people.duckdb")


@pytest.fixture
def three(store, capsys):
    """Three text comparisons recorded into one ledger; returns the 1<->2 decision id."""
    ids = []
    for a, b in ((T1, T2), (T1, T3), (T2, T3)):
        assert main(["compare", "--text", a, b, "--store", store, "--json", "-"]) == 0
        ids.append(_json(capsys)["decision_id"])
    return ids[0]


def test_compare_text_answers_and_records(store, capsys):
    assert main(["compare", "--text", T1, T2, "--store", store]) == 0
    out = capsys.readouterr().out
    assert "same_entity  merge" in out and "decision_id dec:sha256:" in out
    assert "recorded    yes" in out
    assert "12345678901" not in out, "the readable form never prints the values"


def test_compare_text_without_a_store_records_nothing(capsys):
    assert main(["compare", "--text", T1, T2, "--json", "-"]) == 0
    assert _json(capsys)["recorded"] is False


def test_the_text_form_does_not_write_a_report_file(store, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert main(["compare", "--text", T1, T2, "--store", store]) == 0
    assert not (tmp_path / "report.html").exists()


def test_entities_are_masked_by_default_and_revealed_on_request(three, store, capsys):
    assert main(["entities", "--store", store]) == 0
    out = capsys.readouterr().out
    assert "1 entity" in out and "3 records  direct" in out
    assert "12345678901" not in out and "1234***" in out

    assert main(["entities", "--store", store, "--reveal", "--json"]) == 0
    payload = _json(capsys)
    (entity,) = payload["entities"]
    assert entity["shared"] == {"national_id": "12345678901"}
    assert set(entity["conflicts"]) == {"email", "full_name"}
    assert entity["decisions"] == 3


def test_decision_explain_and_replay_by_id(three, store, capsys):
    assert main(["decision", three, "--store", store, "--json"]) == 0
    decision = _json(capsys)
    assert (decision["identity"], decision["action"]) == ("same_entity", "merge")
    assert decision["records"][0]["text"].startswith("Ades")
    assert "12345678901" not in json.dumps(decision), "masked unless --reveal"

    assert main(["explain", three, "--store", store, "--json"]) == 0
    why = _json(capsys)
    assert why["supporting"] == ["name", "name_tf", "national_id"]
    assert why["refuting"] == ["email"]

    assert main(["replay", three, "--store", store, "--json"]) == 0
    replay = _json(capsys)
    assert replay["reproduced"] is True and replay["changed"] == {}


def test_replay_reports_what_moved(three, store, capsys, monkeypatch):
    import arche

    monkeypatch.setattr(arche, "__version__", "99.0.0")
    assert main(["replay", three, "--store", store]) == 0
    out = capsys.readouterr().out
    assert "reproduced: False" in out and "pins.engine" in out


def test_unknown_id_is_an_actionable_error(store):
    main(["compare", "--text", T1, T2, "--store", store])
    with pytest.raises(SystemExit, match="no decision"):
        main(["decision", "dec:sha256:nope", "--store", store])


def test_no_store_and_no_env_is_an_actionable_error(monkeypatch):
    monkeypatch.delenv("ARCHE_LEDGER", raising=False)
    with pytest.raises(SystemExit, match="ARCHE_LEDGER"):
        main(["entities"])


def test_arche_ledger_env_names_the_default_store(three, store, monkeypatch, capsys):
    monkeypatch.setenv("ARCHE_LEDGER", store)
    assert main(["entities", "--json"]) == 0
    assert len(_json(capsys)["entities"]) == 1


def test_cases_then_observe_closes_the_case(store, tmp_path, capsys):
    suppliers = tmp_path / "suppliers.csv"
    suppliers.write_text(
        "id,name,city,registration_id\ns1,Kijani Tea Exporters Ltd,Nairobi,C.12345\n",
        encoding="utf-8",
    )
    registry = tmp_path / "registry.csv"
    registry.write_text(
        "id,name,city,registration_id\n"
        "r1,Kijani Tea Exporters Limited,Nairobi,C.12345\n"
        "r2,Kijani Coffee,Nairobi,\n",
        encoding="utf-8",
    )
    assert main(["compare", str(suppliers), str(registry), "--entity", "organisation",
                 "--store", store, "--out", str(tmp_path / "r.html")]) == 0
    capsys.readouterr()

    assert main(["cases", "--store", store, "--json"]) == 0
    cases = _json(capsys)["cases"]
    assert len(cases) == 1
    case = cases[0]
    assert (case["a"], case["b"]) == ("s1", "r2")
    assert case["would_resolve"][0] == "registration_id"

    assert main(["observe", case["record_b"], "--store", store,
                 "--evidence", '{"registration_id": "C.54321"}', "--json"]) == 0
    observed = _json(capsys)
    assert observed["decisions"][0]["identity"] == "different"
    assert observed["decisions"][0]["supersedes"] == case["decision_id"]
    assert observed["open_cases"] == 0


def test_observe_rejects_evidence_that_is_not_an_object(store):
    main(["compare", "--text", T1, T2, "--store", store])
    with pytest.raises(SystemExit, match="JSON object"):
        main(["observe", "rec:sha256:x", "--store", store, "--evidence", "[1, 2]"])


def test_list_advertises_the_ledger_commands(capsys):
    assert main(["list", "--json"]) == 0
    commands = {c["command"] for c in _json(capsys)["commands"]}
    assert {"decision", "explain", "replay", "entities", "cases", "observe"} <= commands
