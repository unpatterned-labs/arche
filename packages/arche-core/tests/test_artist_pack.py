# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""The artist entity pack: alias equivalences + shipped frequency table.

Mirrors the African-names recipe — equivalence data buys recall, the
population-scale frequency table buys precision, the gate keeps merges safe.
"""

from __future__ import annotations

import warnings

import pytest
from arche import resolve
from arche.resolve import ENTITY_PACKS, TokenFrequencyTable, artist_aliases
from arche.resolve.artists import _parse_groups


# ── alias equivalences (the recall layer) ────────────────────────────────────
def test_artist_aliases_loads_curated_groups():
    aliases = artist_aliases()
    assert len(aliases) >= 30
    assert "Damini Ogulu" in aliases["Burna Boy"]
    assert "Temilade Openiyi" in aliases["Tems"]
    # The hand-corrected group: the SA artist, not the UK name-collision.
    assert "Tyla Seethal" in aliases["Tyla"]


def test_artist_aliases_bundled_fallback(monkeypatch):
    """Without a repo checkout, the wheel's bundled copy still loads."""
    from arche.resolve import artists as mod

    monkeypatch.setattr(mod, "_dataset_dir", lambda: None)
    artist_aliases.cache_clear()
    try:
        aliases = artist_aliases()
        assert "Damini Ogulu" in aliases["Burna Boy"]
    finally:
        artist_aliases.cache_clear()


def test_parse_groups_merges_and_dedupes():
    y = """
groups:
- canonical: A
  variants: [x, y]
"""
    z = """
groups:
- canonical: A
  variants: [y, z]
- canonical: B
  variants: []
"""
    groups = _parse_groups([y, z])
    assert groups["A"] == ("x", "y", "z")
    assert groups["B"] == ()


# ── shipped artist frequency table (the precision layer) ─────────────────────
def test_default_artist_table_loads_and_is_cached():
    tf = TokenFrequencyTable.default(domain="artist")
    assert tf is TokenFrequencyTable.default(domain="artist")
    assert tf.vocabulary_size > 10_000


def test_default_domain_person_is_backward_compatible():
    assert TokenFrequencyTable.default() is TokenFrequencyTable.default(
        domain="person"
    )


def test_default_unknown_domain_raises():
    with pytest.raises(ValueError, match="artist.*person|person.*artist"):
        TokenFrequencyTable.default(domain="nope")


def test_common_catalog_token_less_distinctive_than_rare():
    tf = TokenFrequencyTable.default(domain="artist")
    assert tf.distinctiveness("dj") < tf.distinctiveness("ogulu")
    assert tf.distinctiveness("band") < tf.distinctiveness("openiyi")


def test_reconcile_accepts_tf_domain_string():
    out = resolve.reconcile(
        [{"id": "a", "name": "Burna Boy"}],
        [{"id": "b", "name": "Burna Boy"}],
        comparators=[{"field": "name", "kind": "tftoken", "weight": 1.0}],
        tf="artist",
        block=None,
    )
    assert out["matches"]


def test_reconcile_rejects_unknown_tf_string():
    with pytest.raises(ValueError, match="domain"):
        resolve.reconcile(
            [{"id": "a", "name": "x"}],
            [{"id": "b", "name": "x"}],
            comparators=[{"field": "name", "kind": "tftoken", "weight": 1.0}],
            tf="bogus",
            block=None,
        )


# ── the pack end-to-end (facade) ─────────────────────────────────────────────
def _alias_catalog(*artists: str) -> list[dict]:
    aliases = artist_aliases()
    rows = []
    for a in artists:
        for i, form in enumerate((a, *aliases[a])):
            rows.append({"id": f"{a}#{i}", "artist": a, "name": form,
                         "mbid": f"mb-{a}"})
    return rows


def test_artist_pack_exists_with_registry_id():
    kinds = {(c.get("field"), c["kind"]) for c in ENTITY_PACKS["artist"]}
    assert ("mbid", "id") in kinds
    assert ("name", "tftoken") in kinds


def test_crosswalk_artist_pack_resolves_legal_names():
    """Legal names sharing no string with the stage name resolve via aliases,
    using the SHIPPED artist table (no tf= argument)."""
    catalog = _alias_catalog("Burna Boy", "Rema", "Tems")
    statement = [
        {"id": "s1", "name": "Damini Ogulu"},
        {"id": "s2", "name": "Divine Ikubor"},
        {"id": "s3", "name": "Temilade Openiyi"},
    ]
    out = resolve.reconcile(statement, catalog, entity="artist", block=None)
    best: dict[str, dict] = {}
    for m in out["matches"]:
        if m["a_id"] not in best or m["score"] > best[m["a_id"]]["score"]:
            best[m["a_id"]] = m
    by_row = {r["id"]: r["artist"] for r in catalog}
    assert by_row[best["s1"]["b_id"]] == "Burna Boy"
    assert by_row[best["s2"]["b_id"]] == "Rema"
    assert by_row[best["s3"]["b_id"]] == "Tems"
    assert all(best[s]["decision"] == "match" for s in ("s1", "s2", "s3"))


def test_crosswalk_artist_pack_mbid_agreement_counts():
    a = [{"id": "x", "name": "WIZKID", "mbid": "mb-1"}]
    b = [{"id": "y", "name": "Wizkid", "mbid": "mb-1"}]
    out = resolve.reconcile(a, b, entity="artist", block=None)
    assert out["matches"][0]["decision"] == "match"
    assert "mbid" in out["matches"][0]["evidence"]


def test_crosswalk_artist_pack_warns_and_falls_back_without_asset(monkeypatch):
    """Fail loudly, not silently: a missing shipped table warns, then
    self-calibrates instead of crashing."""

    monkeypatch.setattr(TokenFrequencyTable, "default", classmethod(
        lambda cls, domain="person": (_ for _ in ()).throw(
            FileNotFoundError("asset missing"))))
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        out = resolve.reconcile(
            [{"id": "a", "name": "Burna Boy"}],
            [{"id": "b", "name": "Burna Boy"}],
            entity="artist",
            block=None,
        )
    assert out["matches"]
    assert any("frequency table unavailable" in str(w.message) for w in caught)
