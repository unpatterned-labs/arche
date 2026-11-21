# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""`arche.doc.parties`: who a document is from and who it is to, read from layout.

Synthetic invoices (invented names and addresses) on the rules backend, so the
roles are tested without a model; the doc_bench PDFs run when Docling and
GLiNER are installed."""

from __future__ import annotations

from pathlib import Path

import pytest
from arche.doc import Party, parties


def by_role(text, backend="basic"):
    out: dict[str, list[Party]] = {}
    for p in parties(text, backend=backend):
        out.setdefault(p.role, []).append(p)
    return out


FROM_TO = """From
Northwind Supplies LLC
PO Box 4410
Springfield IL 62701
Tax Number 12-3456789
To
Harbor Lane Studio LLC
Harbor Lane Studio LLC
Account - 7731
88 Elm Street
Springfield IL 62704
Summary of charges
| Item | Amount |
|------|--------|
| Paper | 10.00 |
"""


class TestCueBlocks:
    def test_from_and_to_give_issuer_and_customer(self):
        roles = by_role(FROM_TO)
        (issuer,), (customer,) = roles["issuer"], roles["customer"]
        assert issuer.name == "Northwind Supplies LLC" and issuer.kind == "organisation"
        assert issuer.address == "PO Box 4410, Springfield IL 62701"
        assert customer.name == "Harbor Lane Studio LLC"
        # A repeated name and an account label may sit between a name and its
        # address; a tax number line ends the issuer's address.
        assert customer.address == "88 Elm Street, Springfield IL 62704"
        assert customer.cue == "to" and issuer.cue == "from"

    def test_the_table_body_is_never_read_for_parties(self):
        assert all(p.end <= FROM_TO.index("| Item") for p in parties(FROM_TO, backend="basic"))

    def test_bill_to_and_ship_to(self):
        text = ("41 Quarry Road, Millbrook NY, 12545\n"
                "Bill To.:\nJordan Vale 12 Orchard Way\nMillbrook, NY, 12545\nCredit Card\n"
                "Customer No.\nShip To.:\nJordan Vale\n12 Orchard Way\nMillbrook, NY, 12545\n")
        roles = by_role(text)
        assert roles["issuer"][0].address == "41 Quarry Road, Millbrook NY, 12545"
        (bill,) = roles["customer"]
        assert (bill.name, bill.address) == ("Jordan Vale", "12 Orchard Way, Millbrook, NY, 12545")
        assert roles["ship_to"][0].address == "12 Orchard Way, Millbrook, NY, 12545"

    def test_an_empty_label_cue_is_not_a_party(self):
        # "Customer No." is a field label, not a customer block with a name.
        text = "Customer No.\nC0001\nTo\nHarbor Lane Studio LLC\n88 Elm Street\n"
        assert [p.name for p in parties(text, backend="basic")] == ["Harbor Lane Studio LLC"]


class TestLayoutWithoutCues:
    def test_an_honorific_line_is_the_addressee(self):
        text = ("MRS JORDAN VALE 12 ORCHARD WAY, MILLBROOK, NY US-12545\n"
                "Booking - Confirmation / Invoice\n"
                "Skyline Charter GmbH Hafenstrasse 12\n60311 Frankfurt\nTel. +49 69 0000\n")
        roles = by_role(text)
        (customer,) = roles["customer"]
        assert customer.name.upper() == "JORDAN VALE" and customer.cue == "addressee"
        assert customer.address.startswith("12 ORCHARD WAY")
        # The lines after the addressee's block are the letterhead.
        assert roles["issuer"][0].address.endswith("60311 Frankfurt")

    def test_a_name_alone_under_the_letterhead_is_the_customer(self):
        text = ("Lakeside Inn & Suites 300 Shore Drive Lakeview, MI 49001 United States\n"
                "Tel: 555-010-0000\nJORDAN VALE\nTax ID :\n00-0000000\n"
                "Lakeside TUSSI MAY-19-2025 03:00 9999\n| Date | Charge |\n")
        roles = by_role(text)
        (customer,) = roles["customer"]
        assert customer.name == "JORDAN VALE" and customer.cue == "named under letterhead"
        # Nothing under the guest's name reads as an address; a date line is not one.
        assert customer.address is None

    def test_an_email_elsewhere_is_attached_only_by_surname(self):
        text = ("Bill To:\nJordan Vale\n12 Orchard Way\nMillbrook, NY, 12545\n"
                "| Item | Amount |\n|---|---|\n"
                "Questions: sam@vendor.example  |  your copy: j.vale@mail.example\n")
        (customer,) = by_role(text)["customer"]
        assert customer.email == "j.vale@mail.example"
        assert "surname" in customer.evidence["email"]

    def test_no_break_spaces_keep_offsets(self):
        text = "Bill To:\nJordan Vale\n12 Orchard Way\n"
        (customer,) = by_role(text)["customer"]
        assert text[customer.start:customer.end].replace(" ", " ").startswith("Bill To")


def test_as_record_drops_missing_fields():
    p = Party(role="customer", name="Jordan Vale", kind="person", address=None, email=None,
              cue="to", start=0, end=5)
    assert p.as_record(id="d1") == {"name": "Jordan Vale", "id": "d1"}


def test_rejects_non_text():
    with pytest.raises(TypeError):
        parties(42)


# ── the four doc_bench invoices, with the models ─────────────────────────────

BENCH = Path(__file__).resolve().parents[3] / "data" / "doc_bench"


@pytest.fixture(scope="module")
def bench():
    pytest.importorskip("docling")
    pytest.importorskip("gliner2")
    from arche.doc import parse

    if not BENCH.is_dir():
        pytest.skip("data/doc_bench is not present")
    return {f.stem: parties(parse(str(f))) for f in sorted(BENCH.glob("*.pdf"))}


def test_doc_bench_customers(bench):
    customers = {k: [p for p in v if p.role == "customer"] for k, v in bench.items()}
    assert all(len(c) == 1 for c in customers.values())
    kinds = {k: c[0].kind for k, c in customers.items()}
    assert kinds == {"invoice_10": "person", "invoice_12_ak": "person",
                     "invoice_27": "organisation", "invoice_6_ak": "person"}
    # The guest folio has no customer address; the other three do, and all
    # three are the same street (the issuer's is never taken).
    assert customers["invoice_10"][0].address is None
    for k in ("invoice_12_ak", "invoice_27", "invoice_6_ak"):
        assert customers[k][0].address.upper().startswith("227 N 5TH")
    # The second traveller on the booking is not the customer.
    assert "KARL" not in customers["invoice_12_ak"][0].name.upper()
