# Copyright 2026 unpatterned.org
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""R1: corpus term-frequency token weighting (`TokenFrequencyTable`)."""

from arche.resolve._tokenfreq import TokenFrequencyTable

# A facility-name corpus where "central" / "general" / "phc" are COMMON and
# "karfi" / "gyaranya" / "kofar" / "mata" are RARE (appear once).
_CORPUS = [
    "Karfi PHC", "Central PHC", "Central Hospital", "General Hospital",
    "General Dispensary", "Gyaranya Clinic", "Central Clinic", "PHC Central",
    "Kofar Mata Dispensary", "Central Primary Health Centre",
]


def _tf() -> TokenFrequencyTable:
    return TokenFrequencyTable.from_corpus(_CORPUS)


def test_common_token_more_frequent_than_rare():
    tf = _tf()
    assert tf.rel_freq("central") > tf.rel_freq("karfi")


def test_rare_token_is_more_distinctive_than_common():
    tf = _tf()
    assert tf.distinctiveness("karfi") > tf.distinctiveness("central")
    assert 0.0 <= tf.distinctiveness("central") <= tf.distinctiveness("karfi") <= 1.0


def test_unseen_token_uses_floor_and_is_highly_distinctive():
    tf = _tf()
    assert tf.rel_freq("zzznovel") == tf._floor
    assert tf.distinctiveness("zzznovel") > 0.5


def test_shared_rare_token_beats_shared_common_token():
    # The core R1 property: agreeing on a rare name is stronger evidence than
    # agreeing on a common one, even with the same non-shared remainder.
    tf = _tf()
    rare = tf.weighted_token_sim("Karfi PHC", "Karfi Clinic")       # share "karfi"
    common = tf.weighted_token_sim("Central PHC", "Central Clinic")  # share "central"
    assert rare > common


def test_normalisation_case_and_diacritics():
    tf = _tf()
    assert tf.weighted_token_sim("KARFI phc", "Kárfi  PHC") == 1.0


def test_empty_side_is_zero():
    tf = _tf()
    assert tf.weighted_token_sim("", "Karfi") == 0.0


def test_common_u_map_returns_frequent_tokens_only():
    # min_freq scales with corpus size; in this tiny corpus a single-occurrence
    # token is still ~0.02, so use a threshold that separates common from rare.
    tf = _tf()
    common = tf.common_u_map(min_freq=0.1)
    assert "central" in common          # frequent (~0.22)
    assert "gyaranya" not in common     # rare (single occurrence, ~0.02)


def test_u_for_frequent_is_higher_than_rare():
    # u = P(agree | non-match): frequent token -> weak evidence -> higher u.
    tf = _tf()
    assert tf.u_for("central") > tf.u_for("karfi")


# ── ingest a precomputed national frequency list (from_counts) ───────────────


def test_from_counts_ingests_precomputed_frequencies():
    # A national list: "ibrahim" is common, "gyaranya" is rare.
    tf = TokenFrequencyTable.from_counts(
        {"ibrahim": 900_000, "musa": 400_000, "gyaranya": 12}
    )
    assert tf.rel_freq("ibrahim") > tf.rel_freq("gyaranya")
    assert tf.distinctiveness("gyaranya") > tf.distinctiveness("ibrahim")


def test_from_counts_tokenises_multi_token_names():
    # A list keyed by full name credits the count to each token.
    tf = TokenFrequencyTable.from_counts({"Fatima Abdullahi": 500, "Fatima Bello": 300})
    # "fatima" appears in both -> 800; "abdullahi" only 500.
    assert tf.rel_freq("fatima") > tf.rel_freq("abdullahi")


# ── persistence: save / load round-trip ──────────────────────────────────────


def test_save_load_roundtrip_gzip(tmp_path):
    tf = TokenFrequencyTable.from_counts({"ibrahim": 900, "gyaranya": 3})
    path = tmp_path / "freq.json.gz"
    tf.save(path)
    assert path.exists()
    loaded = TokenFrequencyTable.load(path)
    assert loaded.rel_freq("ibrahim") == tf.rel_freq("ibrahim")
    assert loaded.distinctiveness("gyaranya") == tf.distinctiveness("gyaranya")
    assert loaded.total_count == tf.total_count


def test_save_load_roundtrip_plain_json(tmp_path):
    tf = TokenFrequencyTable.from_corpus(_CORPUS)
    path = tmp_path / "freq.json"
    tf.save(path)
    loaded = TokenFrequencyTable.load(path)
    assert loaded.weighted_token_sim("Karfi PHC", "Karfi Clinic") == tf.weighted_token_sim(
        "Karfi PHC", "Karfi Clinic"
    )


def test_to_dict_from_dict_preserves_counts():
    tf = TokenFrequencyTable.from_counts({"a": 10, "b": 1})
    rt = TokenFrequencyTable.from_dict(tf.to_dict())
    assert rt.total_count == tf.total_count
    assert rt.most_common(1) == tf.most_common(1)


# ── composition: merge two sources ───────────────────────────────────────────


def test_merge_sums_counts():
    a = TokenFrequencyTable.from_counts({"smith": 1000, "musa": 5})
    b = TokenFrequencyTable.from_counts({"musa": 1000, "smith": 5})
    merged = a.merge(b)
    # After merging, both tokens are equally common.
    assert merged.rel_freq("musa") == merged.rel_freq("smith")
    assert merged.total_count == a.total_count + b.total_count


def test_merge_weight_lets_one_source_dominate():
    western = TokenFrequencyTable.from_counts({"john": 1000})
    african = TokenFrequencyTable.from_counts({"chidi": 1000})
    # Trust the African table 3x: "chidi" ends up more frequent than "john".
    merged = western.merge(african, weight=1.0, other_weight=3.0)
    assert merged.rel_freq("chidi") > merged.rel_freq("john")


# ── introspection ────────────────────────────────────────────────────────────


def test_stats_and_most_common():
    tf = TokenFrequencyTable.from_counts({"ibrahim": 900, "musa": 400, "rare": 1})
    assert tf.vocabulary_size == 3
    assert len(tf) == 3
    assert tf.total_count == 1301
    assert tf.most_common(1)[0][0] == "ibrahim"


# ── the shipped default table (moat asset) ───────────────────────────────────


def test_default_table_loads_and_ranks_common_below_rare():
    tf = TokenFrequencyTable.default()
    assert tf.vocabulary_size > 10_000  # population-scale, not a toy corpus
    # A common surname/given name is less distinctive than a rare African name.
    assert tf.distinctiveness("smith") < tf.distinctiveness("adebayo")
    assert tf.distinctiveness("ibrahim") < tf.distinctiveness("adebayo")


def test_default_table_is_cached():
    assert TokenFrequencyTable.default() is TokenFrequencyTable.default()


def test_reconcile_tf_default_common_name_is_weak_evidence():
    from arche.resolve import reconcile

    # Same rare full name -> confident match.
    rare = reconcile(
        [{"id": "A", "name": "Gyaranya Adewale"}],
        [{"id": "B", "name": "Gyaranya Adewale"}],
        [{"field": "name", "kind": "tftoken", "weight": 1.0}],
        tf="default", block=None,
    )
    assert any(m["decision"] == "match" for m in rare["matches"])

    # Two people sharing only a common given name -> not auto-matched.
    common = reconcile(
        [{"id": "A", "name": "Ibrahim Musa"}],
        [{"id": "B", "name": "Ibrahim Bello"}],
        [{"field": "name", "kind": "tftoken", "weight": 1.0}],
        tf="default", block=None,
    )
    assert not any(m["decision"] == "match" for m in common["matches"])


def test_rel_only_table_roundtrips_and_merges():
    # A legacy rel-only table (constructed directly, no raw counts).
    rel = TokenFrequencyTable({"ada": 0.7, "obi": 0.3})
    assert rel.total_count == 0.0  # unknown for a rel-only table
    rt = TokenFrequencyTable.from_dict(rel.to_dict())
    assert rt.rel_freq("ada") == rel.rel_freq("ada")
    # ...and it can still be merged (pseudo-counts reconstructed) without crashing.
    merged = rel.merge(TokenFrequencyTable.from_counts({"obi": 100}))
    assert merged.rel_freq("obi") > 0


def test_merge_handles_zero_frequency_entry():
    # A rel-only table with a 0.0 entry must not divide-by-zero on merge.
    rel = TokenFrequencyTable({"ada": 0.5, "ghost": 0.0})
    merged = rel.merge(TokenFrequencyTable.from_counts({"ada": 10}))
    assert merged.rel_freq("ada") > 0


def test_merge_propagates_min_floor():
    a = TokenFrequencyTable.from_counts({"x": 1}, unknown_floor=1e-3)
    b = TokenFrequencyTable.from_counts({"y": 1}, unknown_floor=1e-6)
    assert a.merge(b)._floor == 1e-6


def test_reconcile_rejects_unknown_tf_string():
    import pytest

    from arche.resolve import reconcile

    with pytest.raises(ValueError, match="unknown frequency-table domain"):
        reconcile(
            [{"id": "A", "name": "x"}], [{"id": "B", "name": "y"}],
            [{"field": "name", "kind": "tftoken", "weight": 1.0}],
            tf="bogus", block=None,
        )
