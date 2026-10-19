# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Document address roles: which address on an invoice or supplier form is which.

All document text here is synthetic.
"""

from __future__ import annotations

import pytest
from arche.addr import (
    DOCUMENT_ROLES,
    extract_document_address_roles,
    grade_document_addresses,
    load_document_gold,
    load_document_role_pack,
)
from arche.addr.roles import RolePackError

INVOICE = """INVOICE
From:
Northwind Widgets Ltd (synthetic)
4 Mill Lane
Leeds LS1 4DL

Bill To:
Example Buyer Ltd (synthetic)
12 High Street
London EC1A 1BB

Ship To:
Unit 4, Trafford Park, Manchester M17 1AB

Invoice No: SYN-1
Please remit payment to 9 Bank Street, Bristol, BS1 2AA.
Registered office: 1 Castle Road, Cardiff CF10 3AA. Company No. 00000000
"""


def _roles(text):
    return [(m.text, m.role) for m in extract_document_address_roles(text)]


class TestRoles:
    def test_every_role_on_one_invoice(self):
        got = {m.role: m for m in extract_document_address_roles(INVOICE)}
        assert got["invoice_from"].text == "4 Mill Lane\nLeeds LS1 4DL"
        assert got["bill_to"].text == "12 High Street\nLondon EC1A 1BB"
        assert got["ship_to"].text == "Unit 4, Trafford Park, Manchester M17 1AB"
        assert got["remit_to"].text == "9 Bank Street, Bristol, BS1 2AA"
        assert got["registered_office"].text == "1 Castle Road, Cardiff CF10 3AA"

    def test_each_committed_role_names_its_cue(self):
        for m in extract_document_address_roles(INVOICE):
            assert m.role != "unknown"
            assert m.cue is not None and m.cue_rule is not None
            assert INVOICE[m.cue_span[0]:m.cue_span[1]] == m.cue
            assert m.pack.startswith("arche.document_address_roles@v1:sha256:")

    def test_multiline_blocks_keep_original_offsets_and_parse(self):
        (m,) = [m for m in extract_document_address_roles(INVOICE) if m.role == "bill_to"]
        assert INVOICE[m.span[0]:m.span[1]] == m.text
        assert m.components.postal_code == "EC1A 1BB"
        assert m.components.street == "High Street"
        assert m.jurisdiction == "GB"

    def test_label_beats_prose_confidence(self):
        got = {m.role: m for m in extract_document_address_roles(INVOICE)}
        assert got["bill_to"].cue_form == "label"
        assert got["remit_to"].cue_form == "prose"
        assert got["bill_to"].confidence > got["remit_to"].confidence

    def test_trading_and_registered_office_on_a_supplier_form(self):
        text = ("Registered office address:\n27 Hollins Lane, Marple Bridge, "
                "Stockport, SK6 5BB\nTrading address:\n3 Mill Lane, Wingerworth, "
                "Chesterfield, S42 6NG\n")
        assert _roles(text) == [
            ("27 Hollins Lane, Marple Bridge, Stockport, SK6 5BB", "registered_office"),
            ("3 Mill Lane, Wingerworth, Chesterfield, S42 6NG", "trading_address"),
        ]

    def test_nigerian_and_south_african_addresses(self):
        assert _roles("Seller: Adeola Foods Ltd, 7B Allen Avenue, Ikeja, Lagos") == [
            ("7B Allen Avenue, Ikeja, Lagos", "invoice_from")]
        assert _roles("To: Sandton Retail (Pty) Ltd, 14 Rivonia Road, Sandton, 2196") == [
            ("14 Rivonia Road, Sandton, 2196", "bill_to")]


class TestAbstention:
    def test_no_cue_is_unknown(self):
        (m,) = extract_document_address_roles(
            "Example Holdings Ltd (synthetic), 5 Market Street, Leeds LS1 6DT")
        assert m.role == "unknown"
        assert "cue:absent" in m.evidence
        assert m.confidence == 0.25

    def test_two_roles_on_one_address_is_unknown(self):
        (m,) = extract_document_address_roles(
            "Bill to / Ship to: 14 Princess Road, Moss Side, Manchester, M15 5UJ")
        assert m.role == "unknown"
        assert any(e.startswith("cue_conflict:") for e in m.evidence)

    def test_a_negated_cue_is_unknown(self):
        ms = extract_document_address_roles(
            "Do not send payment to 3 Old Road, York YO1 7HH; our new remittance "
            "address is 8 New Road, York YO1 8AA.")
        assert [(m.role, "cue:negated" in m.evidence) for m in ms] == [
            ("unknown", True), ("remit_to", False)]

    def test_label_only_words_do_not_fire_in_prose(self):
        (m,) = extract_document_address_roles(
            "Goods were returned to 6 Cranbrook Avenue, Hull HU6 7TT last week.")
        assert m.role == "unknown"

    def test_a_blank_line_breaks_the_binding(self):
        (m,) = extract_document_address_roles(
            "Ship to:\n\nNotes: see attached.\n\nOakwood Tools Ltd, 11 Oak Road, Derby DE1 1AA")
        assert m.role == "unknown"

    def test_boilerplate_lines_end_an_address_block(self):
        (m,) = extract_document_address_roles(
            "Bill to:\n12 High Street\nLondon EC1A 1BB\nVAT No GB000000000")
        assert m.text == "12 High Street\nLondon EC1A 1BB"

    def test_empty(self):
        assert extract_document_address_roles("") == []
        assert extract_document_address_roles("   \n") == []


class TestOutputShape:
    def test_masked_dict_carries_no_address_text(self):
        (m,) = [m for m in extract_document_address_roles(INVOICE) if m.role == "bill_to"]
        d = m.to_dict(reveal=False)
        assert "text" not in d and "components" not in d
        assert "postal_code" in d["components_present"]
        assert d["cue"] == "bill to"
        full = m.to_dict()
        assert full["text"] == m.text and full["cue"] == "Bill To"


class TestPack:
    def test_pin_is_stable_and_content_addressed(self):
        pack = load_document_role_pack()
        assert pack.pin == load_document_role_pack().pin
        assert set(r.role for r in pack.rules) == set(DOCUMENT_ROLES)

    def test_contradictory_pack_is_rejected(self, tmp_path):
        bad = tmp_path / "bad.yaml"
        bad.write_text(
            "pack: t\nversion: v0\nrules:\n"
            "  - {id: a, role: bill_to, cues: [x to]}\n"
            "  - {id: b, role: ship_to, cues: [x to]}\n", encoding="utf-8")
        with pytest.raises(RolePackError, match="maps to"):
            load_document_role_pack(bad)

    def test_unknown_role_is_rejected(self, tmp_path):
        bad = tmp_path / "bad2.yaml"
        bad.write_text("pack: t\nversion: v0\nrules:\n"
                       "  - {id: a, role: head_office, cues: [hq]}\n", encoding="utf-8")
        with pytest.raises(RolePackError, match="unknown role"):
            load_document_role_pack(bad)


class TestGoldAndGrader:
    def test_gold_loads_and_is_synthetic(self):
        gold = load_document_gold()
        assert len(gold) >= 20
        roles = {p.role for g in gold for p in g.places}
        assert set(DOCUMENT_ROLES) <= roles and "unknown" in roles

    def test_the_shipped_extractor_on_the_shipped_gold(self):
        """A regression floor, not a benchmark: the set was written alongside
        the extractor."""
        gold = load_document_gold()
        preds = {g.id: extract_document_address_roles(g.text) for g in gold}
        grade = grade_document_addresses(gold, preds, pack=load_document_role_pack().pin)
        assert grade.span_f1 == 1.0
        assert grade.abstentions["over_guess"] == 0
        for role in DOCUMENT_ROLES:
            assert grade.per_role[role]["f1"] == 1.0, role

    def test_over_guessing_is_priced(self):
        gold = load_document_gold()
        g = next(g for g in gold if g.id == "inv-gb-004")
        (place,) = g.places
        preds = {g.id: [{"start": place.span[0], "end": place.span[1], "role": "bill_to"}]}
        grade = grade_document_addresses([g], preds)
        assert grade.abstentions["over_guess"] == 1
        assert grade.per_role["bill_to"]["fp"] == 1

    def test_abstaining_where_gold_commits_is_a_miss_not_an_error(self):
        gold = load_document_gold()
        g = next(g for g in gold if g.id == "inv-gb-003")
        preds = {g.id: [{"start": p.span[0], "end": p.span[1], "role": "unknown"}
                        for p in g.places]}
        grade = grade_document_addresses([g], preds)
        assert grade.abstentions["missed_by_abstention"] == 2
        assert grade.per_role["remit_to"]["fp"] == 0
