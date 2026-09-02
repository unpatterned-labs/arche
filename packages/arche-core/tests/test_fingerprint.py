# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Fingerprints: the keys that turn a lookup into a lookup.

A fingerprint claims exactly one thing -- two records that could be the same
share at least one key -- and it is important that it claims nothing more.
Sharing a key is an invitation to compare, not evidence of anything. Every test
here is about keeping that boundary honest, plus the one property the index has
to report about itself: what it cannot reach.

Measured on a real supplier ledger of 555,681 records: the index built in 7.8
seconds and cut 154 billion candidate pairs to 59.5 million, a 2,593x
reduction, at a cost of 38,991 records reachable under no key at all.
"""

from __future__ import annotations

import pytest

from arche.resolve import FingerprintIndex, fingerprint

_MASTER = [
    {"id": "S1", "name": "Karfi Agro Cooperative Society Ltd",
     "email": "ops@karfi.example", "city": "Kano"},
    {"id": "S2", "name": "Karfi Agro Co-operative Soc.", "city": "Kano"},
    {"id": "S3", "name": "Zenith Bank Plc", "city": "Lagos"},
    {"id": "S4", "name": "Dangote Cement Plc", "city": "Lagos"},
]


# ---------------------------------------------------------------------------
# What a key is, and what it is not
# ---------------------------------------------------------------------------


def test_identifiers_are_kept_whole():
    # An email is near-deterministic, so it is one key rather than a bag of
    # tokens. Splitting it would make `ops@a.com` and `ops@b.com` share a key.
    keys = fingerprint({"name": "Karfi Agro", "email": "ops@karfi.example"},
                       id_fields=("email",))
    assert "email=ops@karfi.example" in keys


def test_text_becomes_one_key_per_word():
    keys = fingerprint({"name": "Karfi Agro Cooperative"})
    assert set(keys) == {"t:agro", "t:cooperative", "t:karfi"}


def test_the_two_kinds_are_distinguishable():
    # A reader of a key list has to be able to tell "shares an email" from
    # "shares a word", because only one of them is nearly conclusive.
    keys = fingerprint({"name": "Karfi", "email": "a@b.example"},
                       id_fields=("email",))
    assert any(k.startswith("t:") for k in keys)
    assert any(not k.startswith("t:") for k in keys)


def test_case_and_accents_do_not_split_a_key():
    assert fingerprint({"name": "CAFÉ Lisboa"}) == fingerprint(
        {"name": "cafe  lisboa"}
    )


@pytest.mark.parametrize(
    "value", ["test", "TEST", "n/a", "unknown", "none", "-", "  "]
)
def test_placeholders_are_not_identifiers(value):
    # Measured on a real ledger: `test` alone was carried by 303 supplier
    # records across 57 countries. A key everyone shares narrows nothing, and
    # keying on one invites every placeholder record to be compared with every
    # other placeholder record.
    assert f"name={value.strip().lower()}" not in fingerprint(
        {"name": value}, id_fields=("name",)
    )


def test_a_single_character_token_is_dropped():
    assert "t:a" not in fingerprint({"name": "a Karfi"})


def test_an_absent_field_contributes_nothing():
    assert fingerprint({"name": "Karfi", "email": None}, id_fields=("email",)) == [
        "t:karfi"
    ]


def test_one_record_cannot_flood_the_index():
    # A name field holding a pasted paragraph would otherwise contribute a key
    # per word, and every one of them becomes a block someone has to search.
    keys = fingerprint({"name": " ".join(f"word{i}" for i in range(100))},
                       max_tokens=12)
    assert len(keys) == 12


# ---------------------------------------------------------------------------
# The index
# ---------------------------------------------------------------------------


def test_a_query_finds_records_sharing_a_word():
    index = FingerprintIndex(_MASTER, text_fields=("name",))
    found = index.candidates({"name": "Karfi Agro Cooperative Society Ltd"})
    assert {_MASTER[p]["id"] for p in found} == {"S1", "S2"}


def test_an_unrelated_query_finds_nothing():
    index = FingerprintIndex(_MASTER, text_fields=("name",))
    assert index.candidates({"name": "Sahel Foods Nigeria"}) == []


def test_an_identifier_reaches_across_a_name_change():
    # The case fingerprints exist for: a supplier renamed itself, so no word is
    # shared, but the contact address did not change.
    index = FingerprintIndex(_MASTER, text_fields=("name",), id_fields=("email",))
    found = index.candidates({"name": "Completely Different Ltd",
                              "email": "ops@karfi.example"})
    assert {_MASTER[p]["id"] for p in found} == {"S1"}


def test_the_index_holds_positions_not_records():
    # It carries no field values, so it can be kept, logged or shipped where
    # the records themselves could not be. On a customer table that is the
    # difference between an index and a copy of the personal data.
    index = FingerprintIndex(_MASTER, text_fields=("name",))
    stored = [p for rows in index._keys.values() for p in rows]
    assert all(isinstance(p, int) for p in stored)


def test_an_empty_list_is_indexable():
    index = FingerprintIndex([], text_fields=("name",))
    assert index.candidates({"name": "anything"}) == []
    assert index.stats()["records"] == 0


# ---------------------------------------------------------------------------
# The cost bound, and reporting what it costs
# ---------------------------------------------------------------------------


def test_an_over_common_key_is_dropped():
    # A key naming a large share of the file proposes millions of comparisons
    # and rules almost nothing out. Measured: `t:tours` was carried by 84,297
    # of 555,681 supplier records -- 15% of the ledger.
    records = [{"name": f"Tours Company {i}"} for i in range(50)]
    index = FingerprintIndex(records, text_fields=("name",), max_block=10)
    assert "t:tours" in index.dropped_keys
    assert index.dropped_keys["t:tours"] == 50


def test_dropping_a_key_is_reported_not_silent():
    # It costs recall. A recall cost you cannot see is one nobody believes
    # later, so the index states it rather than leaving it to be discovered.
    records = [{"name": f"Tours Company {i}"} for i in range(50)]
    stats = FingerprintIndex(records, text_fields=("name",),
                             max_block=10).stats()
    assert stats["dropped_keys"] >= 1
    assert stats["dropped_key_rows"] >= 50


def test_unreachable_records_are_counted():
    # THE number that caps everything downstream: a record reachable under no
    # key is one no lookup will ever return, however good the comparators are.
    records = [{"name": "Tours"} for _ in range(50)]
    stats = FingerprintIndex(records, text_fields=("name",),
                             max_block=10).stats()
    assert stats["unreachable_records"] == 50
    assert stats["reachable_records"] == 0


def test_stats_accounts_for_every_record():
    index = FingerprintIndex(_MASTER, text_fields=("name",))
    stats = index.stats()
    assert stats["reachable_records"] + stats["unreachable_records"] == len(_MASTER)


def test_block_sizes_are_reported():
    index = FingerprintIndex(_MASTER, text_fields=("name",))
    stats = index.stats()
    assert stats["largest_block"] >= stats["median_block"] >= 1


# ---------------------------------------------------------------------------
# The boundary that must not blur
# ---------------------------------------------------------------------------


def test_sharing_a_key_is_not_a_match():
    # Two different businesses in one city share their destination words. The
    # index is right to offer them for comparison and would be wrong to imply
    # anything further -- which is why `candidates` returns positions and not
    # scores, verdicts or edges.
    records = [{"id": "A", "name": "Agra Tours Guide"},
               {"id": "B", "name": "Agra Taj Tours"}]
    index = FingerprintIndex(records, text_fields=("name",))
    found = index.candidates(records[0])
    assert len(found) == 2
    assert all(isinstance(p, int) for p in found)
