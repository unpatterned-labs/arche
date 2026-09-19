# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""`arche serve`: the document verbs — `/documents`, `/places`, `/extract`, warm start.

Everything here runs on the basic backend and plain-text documents, so the
suite needs neither a model nor docling; what it checks is the socket in front
of `resolve_documents`, not the extractor behind it.
"""
from __future__ import annotations

import pytest

fastapi = pytest.importorskip("fastapi")
pytest.importorskip("httpx")
pytest.importorskip("multipart")
from arche._service import create_app, warm  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

INVOICE_A = (
    "INVOICE\nSupplier: Bello Freight Nigeria Limited\nRC 1234567\n"
    "Contact: Adesola Okonkwo, adesola@example.com, 08031234567\n"
    "Address: 12 Aminu Kano Crescent, Wuse, Abuja\n"
)
INVOICE_B = (
    "PURCHASE ORDER\nVendor: Bello Freight Nigeria Ltd\nRC No 1234567\n"
    "Attn: Adesola E. Okonkwo, adesola@example.com\n"
    "Wuse, Abuja\n"
)


@pytest.fixture(scope="module")
def client():
    return TestClient(create_app(ledger=None, warm_start=False))


class TestCapabilities:
    def test_the_new_endpoints_are_advertised(self, client):
        caps = client.get("/capabilities").json()
        for path in ("/documents", "/places", "/extract"):
            assert path in caps["endpoints"]

    def test_parsers_are_reported_and_plain_text_is_always_one(self, client):
        parsers = client.get("/capabilities").json()["parsers"]
        assert parsers["text"] is True
        assert set(parsers) >= {"text", "pdf", "docx", "docling", "ocr"}

    def test_livez_reports_warm_only_when_asked(self, client):
        assert client.get("/livez").json()["warm"] is None
        warmed = TestClient(create_app(ledger=None, warm_start=True))
        with warmed:
            assert warmed.get("/livez").json()["warm"] in (True, False)


class TestWarm:
    def test_warm_reports_what_it_could_load_and_never_raises(self):
        loaded = warm()
        assert isinstance(loaded, dict)
        for value in loaded.values():
            assert value is True or isinstance(value, str)


class TestDocuments:
    def test_two_text_documents_come_back_as_two_masked_records(self, client):
        files = [("files", ("invoice_a.txt", INVOICE_A, "text/plain")),
                 ("files", ("po_b.txt", INVOICE_B, "text/plain"))]
        r = client.post("/documents", files=files,
                        data={"entity": "organisation", "jurisdiction": "NG",
                              "backend": "basic"})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["entity"] == "organisation"
        assert {d["document"] for d in body["documents"]} == {"invoice_a.txt", "po_b.txt"}
        # The caller's names, everywhere: the temp layout never leaks.
        names = {"invoice_a.txt", "po_b.txt"}
        for d in body["decisions"]:
            assert {d["a"], d["b"]} <= names
        assert set(body["jurisdictions"]) == names
        assert body["recorded"] is False

    def test_two_documents_about_one_supplier_are_the_same_entity(self, client):
        files = [("files", ("invoice_a.txt", INVOICE_A, "text/plain")),
                 ("files", ("po_b.txt", INVOICE_B, "text/plain"))]
        body = client.post("/documents", files=files,
                           data={"entity": "organisation", "jurisdiction": "NG",
                                 "backend": "basic"}).json()
        (decision,) = body["decisions"]
        # `Supplier:` on the invoice and `Vendor:` on the order name one
        # company; the organisation pack compares that, not the contact.
        assert decision["identity"] == "same_entity", decision

    def test_two_files_with_the_same_name_are_refused_not_merged(self, client):
        files = [("files", ("doc.txt", INVOICE_A, "text/plain")),
                 ("files", ("doc.txt", INVOICE_B, "text/plain"))]
        r = client.post("/documents", files=files, data={"jurisdiction": "NG", "backend": "basic"})
        # The report is keyed by file name; a silent overwrite would be worse
        # than a refusal that names the file.
        assert r.status_code == 400
        assert "doc.txt" in r.text

    def test_values_are_masked_unless_reveal(self, client):
        files = [("files", ("a.txt", INVOICE_A, "text/plain"))]
        masked = client.post("/documents", files=files,
                             data={"jurisdiction": "NG", "backend": "basic"}).json()
        shown = client.post("/documents", files=files,
                            data={"jurisdiction": "NG", "backend": "basic",
                                  "reveal": "true"}).json()
        joined_masked = " ".join(str(v) for v in masked["documents"][0].values())
        joined_shown = " ".join(str(v) for v in shown["documents"][0].values())
        assert "adesola@example.com" not in joined_masked
        assert "adesola@example.com" in joined_shown

    def test_an_unparseable_file_is_reported_not_fatal(self, client):
        files = [("files", ("a.txt", INVOICE_A, "text/plain")),
                 ("files", ("bad.xyz", b"\x00\x01\x02", "application/octet-stream"))]
        r = client.post("/documents", files=files,
                        data={"jurisdiction": "NG", "backend": "basic"})
        # Either docling is absent (a 400 naming the extra) or present and
        # the bad file lands in `errors`; both are the honest answer.
        if r.status_code == 200:
            assert "bad.xyz" in r.json()["errors"]
        else:
            assert r.status_code == 400
            assert "docling" in r.text

    def test_no_files_is_a_422(self, client):
        assert client.post("/documents", data={"jurisdiction": "NG"}).status_code == 422


class TestPlaces:
    def test_mentions_carry_a_role_and_a_span(self, client):
        r = client.post("/places", json={"text": "Deliver to the depot in Ikeja, Lagos, "
                                                 "from the warehouse at Apapa."})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["count"] == len(body["mentions"]) >= 1
        for m in body["mentions"]:
            assert "role" in m and "text" in m


class TestExtract:
    def test_basic_backend_returns_serialisable_entities(self, client):
        r = client.post("/extract", json={"text": "Adesola Okonkwo lives in Lagos",
                                          "backend": "basic"})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["count"] == len(body["entities"])
        assert any(e["text"] == "Adesola Okonkwo" for e in body["entities"])
