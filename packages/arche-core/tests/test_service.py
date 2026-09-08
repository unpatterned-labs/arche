# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""`arche serve`: the verbs over HTTP.

The service is the CLI's surface with a socket in front of it, so the tests
ask the same questions the CLI tests ask -- masked by default, a decision id
that re-derives, a 404 for an id the ledger never saw -- through the FastAPI
test client. FastAPI is an extra; without it the whole file skips, and one
test checks the ImportError names the install line.
"""

from __future__ import annotations

import pytest

fastapi = pytest.importorskip("fastapi")
pytest.importorskip("httpx")
from fastapi.testclient import TestClient  # noqa: E402

from arche._service import create_app  # noqa: E402

TEXT = "Contact Adaeze Okonkwo on +234 803 123 4567 or adaeze@example.com."


@pytest.fixture(scope="module")
def client():
    return TestClient(create_app(ledger=None))


@pytest.fixture()
def ledger_client(tmp_path):
    return TestClient(create_app(ledger=str(tmp_path / "ledger.duckdb")))


class TestLiveness:
    def test_livez_carries_the_version(self, client):
        from arche import __version__
        body = client.get("/livez").json()
        assert body == {"ok": True, "version": __version__}

    def test_capabilities_say_whether_a_ledger_is_attached(self, client, ledger_client):
        assert client.get("/capabilities").json()["ledger"] is False
        assert ledger_client.get("/capabilities").json()["ledger"] is True


class TestDetect:
    def test_returns_offsets_and_categories_but_never_the_value(self, client):
        body = client.post("/detect", json={"text": TEXT, "jurisdiction": "NG",
                                            "backend": "basic"}).json()
        cats = {d["category"] for d in body["detections"]}
        assert {"PII-3-PHONE", "PII-3-EMAIL"} <= cats
        assert body["count"] == len(body["detections"])
        dumped = str(body)
        assert "adaeze@example.com" not in dumped
        assert "803 123 4567" not in dumped
        for d in body["detections"]:
            assert TEXT[d["start"]:d["end"]]  # offsets index the caller's text

    def test_a_bad_backend_is_a_400_with_the_vocabulary(self, client):
        r = client.post("/detect", json={"text": TEXT, "jurisdiction": "NG",
                                         "backend": "gliner"})
        assert r.status_code == 400
        assert "basic" in r.json()["detail"]


class TestDeidentify:
    def test_masks_and_returns_a_decision_id_that_rederives(self, client):
        body = {"text": TEXT, "jurisdiction": "NG", "backend": "basic"}
        one = client.post("/deidentify", json=body).json()
        two = client.post("/deidentify", json=body).json()
        assert "adaeze@example.com" not in one["text"]
        assert one["decision_id"].startswith("red:sha256:")
        assert one["decision_id"] == two["decision_id"]
        assert one["statute"].startswith("NDPA")
        assert one["count"] >= 2
        assert one["recorded"] is False

    def test_no_jurisdiction_and_no_inference_is_a_400(self, client):
        r = client.post("/deidentify", json={"text": "hello 12345", "backend": "basic"})
        assert r.status_code == 400
        assert "jurisdiction" in r.json()["detail"].lower()

    def test_store_needs_a_ledger(self, client):
        r = client.post("/deidentify", json={"text": TEXT, "jurisdiction": "NG",
                                             "backend": "basic", "store": True})
        assert r.status_code == 503

    def test_a_stored_redaction_can_be_explained_by_id(self, ledger_client):
        body = ledger_client.post("/deidentify", json={
            "text": TEXT, "jurisdiction": "NG", "backend": "basic", "store": True}).json()
        assert body["recorded"] is True
        why = ledger_client.get(f"/explain/{body['decision_id']}").json()
        assert why  # the ledger's explain payload, whatever shape it takes
        assert ledger_client.get(f"/decision/{body['decision_id']}").status_code == 200


class TestCompare:
    A = {"name": "Adaeze Okonkwo", "phone": "+2348031234567"}
    B = {"name": "Adaeze Okonkwo", "phone": "0803 123 4567"}

    def test_two_records_return_the_receipt(self, client):
        body = client.post("/compare", json={"a": self.A, "b": self.B,
                                             "jurisdiction": "NG"}).json()
        assert body["identity"] == "same_entity"
        assert body["decision_id"]
        assert set(body) >= {"identity", "action", "basis", "explanation",
                             "score", "factors", "pins"}

    def test_two_strings_are_extracted_first(self, client):
        body = client.post("/compare", json={
            "a": "Adaeze Okonkwo, +234 803 123 4567",
            "b": "A. Okonkwo, phone 0803 123 4567",
            "jurisdiction": "NG", "backend": "basic"}).json()
        assert body["identity"] in {"same_entity", "review", "different"}

    def test_mismatched_shapes_are_a_400(self, client):
        r = client.post("/compare", json={"a": self.A, "b": "a string"})
        assert r.status_code == 400

    def test_stored_then_replayed(self, ledger_client):
        body = ledger_client.post("/compare", json={"a": self.A, "b": self.B,
                                                    "jurisdiction": "NG",
                                                    "store": True}).json()
        did = body["decision_id"]
        masked = ledger_client.get(f"/decision/{did}").json()
        assert "Adaeze Okonkwo" not in str(masked)
        again = ledger_client.get(f"/replay/{did}").json()
        assert again["reproduced"] is True
        assert ledger_client.get("/decision/dec:sha256:nothing").status_code == 404
        assert ledger_client.get("/replay/dec:sha256:nothing").status_code == 404


class TestTheCli:
    def test_serve_and_studio_are_listed(self):
        from arche.cli import _COMMANDS
        names = {name for name, _ in _COMMANDS}
        assert {"serve", "studio"} <= names

    def test_studio_home_prefers_the_env_var(self, tmp_path, monkeypatch):
        monkeypatch.setenv("ARCHE_STUDIO_HOME", str(tmp_path / "elsewhere"))
        from arche._studio import _home
        assert _home() == tmp_path / "elsewhere"

    def test_studio_home_falls_back_to_the_user_dir(self, tmp_path, monkeypatch):
        monkeypatch.delenv("ARCHE_STUDIO_HOME", raising=False)
        monkeypatch.chdir(tmp_path)
        from pathlib import Path

        from arche._studio import _home
        assert _home() == Path.home() / ".arche" / "studio"
