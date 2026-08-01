# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Tests for redact-by-default rendering (`arche.render`)."""

import pytest
from arche.canonical import Reference
from arche.render import render, resolved_table, resolved_view
from arche.resolve.coreference import coref_references


def _ref():
    return Reference.from_record({
        "full_name": "Fatima Abdullahi",
        "national_id": "NIN-12345",
        "country": "NG",   # non-PII descriptor
    })


def test_masked_by_default():
    out = render(_ref())
    assert out["full_name"] == "[FULL_NAME]"
    assert out["national_id"] == "[NATIONAL_ID]"
    assert out["country"] == "NG"  # non-PII shown
    # No raw PII leaks in the default render.
    assert "Fatima" not in str(out) and "NIN-12345" not in str(out)


def test_reveal_all():
    out = render(_ref(), reveal=True)
    assert out["full_name"] == "Fatima Abdullahi"
    assert out["national_id"] == "NIN-12345"


def test_reveal_named_fields_only():
    out = render(_ref(), reveal=["national_id"])
    assert out["national_id"] == "NIN-12345"     # revealed
    assert out["full_name"] == "[FULL_NAME]"     # still masked


def test_truncate_style():
    out = render(_ref(), reveal=False, style="truncate")
    assert out["national_id"] == "NIN***"


def test_token_style_is_linkage_preserving():
    # Same value -> same token across two records, without exposing the value.
    a = render(Reference.from_record({"national_id": "NIN-1"}), style="token", key="k")
    b = render(Reference.from_record({"national_id": "NIN-1"}), style="token", key="k")
    c = render(Reference.from_record({"national_id": "NIN-2"}), style="token", key="k")
    assert a["national_id"] == b["national_id"]        # linkable
    assert a["national_id"] != c["national_id"]        # distinct values differ
    assert "NIN-1" not in a["national_id"]             # not recoverable


def test_token_style_requires_key():
    with pytest.raises(ValueError, match="key"):
        render(_ref(), style="token")


# ── resolved view: the two records joined as one entity ──────────────────────


def _same_person_decision():
    a = Reference.from_record({"full_name": "Fatima Abdullahi", "national_id": "NIN-1", "phone": "0803"})
    a.source_system = "clinic"
    b = Reference.from_record({"full_name": "Fatima Abdulahi", "national_id": "NIN-1", "address": "12 Bello"})
    b.source_system = "vaccination"
    return coref_references(a, b, jurisdiction="NG", issuer_key=b"x" * 32)


def test_resolved_view_groups_both_records_with_decision():
    view = resolved_view(_same_person_decision())
    assert view["decision"] == "same_entity" and view["action"] == "merge"
    assert view["entity_id"].startswith("ent:hmac:")   # the id that says "same person"
    assert view["score"] == 1.0
    assert len(view["records"]) == 2
    assert {r["source"] for r in view["records"]} == {"clinic", "vaccination"}
    # PII masked by default in the joined view.
    assert view["records"][0]["full_name"] == "[FULL_NAME]"
    assert "Fatima" not in str(view)


def test_resolved_view_reveal_shows_pii():
    view = resolved_view(_same_person_decision(), reveal=["national_id"])
    assert view["records"][0]["national_id"] == "NIN-1"
    assert view["records"][0]["full_name"] == "[FULL_NAME]"


def test_resolved_table_rows_share_entity_and_union_columns():
    rows = resolved_table(_same_person_decision(), reveal=True)
    assert len(rows) == 2
    # Both rows carry the SAME entity + decision — they're one resolved person.
    assert rows[0]["entity_id"] == rows[1]["entity_id"]
    assert rows[0]["decision"] == rows[1]["decision"] == "same_entity"
    # Union of attribute columns; a value absent from one record is "".
    assert "phone" in rows[0] and "address" in rows[0]
    assert rows[0]["phone"] == "0803" and rows[0]["address"] == ""      # clinic row
    assert rows[1]["address"] == "12 Bello" and rows[1]["phone"] == ""  # vaccination row


def test_render_plain_dict():
    out = render({"phone": "08031234567", "country": "NG"})
    assert out["phone"] == "[PHONE]"
    assert out["country"] == "NG"  # known safe descriptor shown


def test_unknown_attributes_are_masked_by_default():
    # H1: an attribute the vocab doesn't recognise must still be masked (allowlist).
    out = render(Reference.from_record({
        "passport": "A1234567", "kra_pin": "P051", "country": "KE",
    }))
    assert out["passport"] == "[PASSPORT]"   # not in the old denylist, now masked
    assert out["kra_pin"] == "[KRA_PIN]"     # unknown identity field, masked
    assert out["country"] == "KE"            # safe descriptor shown
    assert "A1234567" not in str(out)
