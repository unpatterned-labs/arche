# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Tests for orthographic keying (`arche.resolve._orthography`).

The pack exists to recover true matches the distinctiveness gate was dropping:
a settlement written "Mai Tsidau" in one registry and "Maitsidau" in another
shares no token, so the gate never fired. Measured on Kano State against
OpenStreetMap, that class of variation was a real source of missed matches.

The tests that matter most here are the NEGATIVE ones. A pack that recovers
true matches while also merging distinct facilities is worse than no pack, and
the first implementation did exactly that: joined keys like "healthpost" are
absent from every frequency table, so they read as unseen-therefore-rare and
cleared the gate for any two facilities both ending "Health Post".
"""

from __future__ import annotations

import pytest
from arche.resolve import TokenFrequencyTable
from arche.resolve._gate import (
    DISTINCTIVE_FLOOR,
    ordered_name_tokens,
    shared_name_distinctiveness,
)
from arche.resolve._orthography import load_orthography, orthographic_key


@pytest.fixture(scope="module")
def tf() -> TokenFrequencyTable:
    """A table where type tokens are common and place names are rare.

    Proportions matter more than realism: "health"/"post"/"centre" must be
    common enough that a joined form built from them cannot look distinctive.
    """
    corpus = (
        ["Health Post"] * 2000
        + ["Primary Health Centre"] * 2000
        + ["Central Dispensary"] * 300
        + ["Maitsidau", "Mai Tsidau", "Sambauna", "Kurugu", "Alfindi"]
    )
    return TokenFrequencyTable.from_corpus(corpus)


class TestPack:
    def test_hausa_pack_loads(self):
        pack = load_orthography("hausa")
        assert pack is not None
        assert pack.collapse_boundaries is True

    def test_unknown_language_is_none_not_an_error(self):
        assert load_orthography("not-a-language") is None

    def test_unknown_language_key_is_the_token_itself(self):
        assert orthographic_key("Maitsidau", "not-a-language") == "maitsidau"

    def test_nasal_assimilation_before_labials(self):
        # n -> m before b/p. Sanbauna == Sambauna.
        assert orthographic_key("sanbauna") == orthographic_key("sambauna")
        assert orthographic_key("kanbari") == orthographic_key("kambari")

    def test_nasal_rule_does_not_fire_elsewhere(self):
        # Only before b/p — "kano" and "kamo" are different words.
        assert orthographic_key("kano") != orthographic_key("kamo")

    def test_curated_equivalents_are_bidirectional(self):
        assert orthographic_key("mallam") == orthographic_key("malam")
        assert orthographic_key("ahmadu") == orthographic_key("amadu")
        assert orthographic_key("ungwar") == orthographic_key("unguwar")

    def test_unrelated_tokens_do_not_collide(self):
        assert orthographic_key("kurugu") != orthographic_key("alfindi")


class TestAdjacentJoining:
    def test_split_compound_meets_joined_compound(self):
        pack = load_orthography("hausa")
        joined = pack.keys(ordered_name_tokens("Maitsidau Health Post"))
        split = pack.keys(ordered_name_tokens("Mai Tsidau Health Post"))
        assert "maitsidau" in joined.keys() & split.keys()

    def test_joined_keys_record_their_source_tokens(self):
        """Provenance is load-bearing, not decoration — see the class below."""
        pack = load_orthography("hausa")
        keys = pack.keys(["mai", "tsidau"])
        assert keys["maitsidau"] == {"mai", "tsidau"}

    def test_only_adjacent_tokens_join(self):
        # "mai ... tsidau" with a word between them is not the compound.
        pack = load_orthography("hausa")
        assert "maitsidau" not in pack.keys(["mai", "gari", "tsidau"])


class TestGateRecovery:
    """The pairs the pack exists for."""

    @pytest.mark.parametrize(
        ("a", "b"),
        [
            ("Maitsidau Primary Health Centre", "Mai Tsidau Primary Health Center"),
            ("Sambauna Primary Health Centre", "Sanbauna Primary Health Center"),
            ("Unguwar Malam Amadu Health Post", "Ungwar Mallam Ahmadu Health Post"),
        ],
    )
    def test_variation_is_recovered(self, tf, a, b):
        without = shared_name_distinctiveness(a, b, tf)
        with_pack = shared_name_distinctiveness(a, b, tf, orthography="hausa")
        assert with_pack > without


class TestNoFalseMerges:
    """The tests that would have caught the first implementation."""

    def test_shared_type_tokens_never_clear_the_gate(self, tf):
        """The bug: "healthpost" is in no frequency table, so scoring the
        joined key directly read as rare and cleared the gate for every pair
        of facilities whose names both end "Health Post"."""
        score = shared_name_distinctiveness(
            "Kurugu Health Post", "Alfindi Health Post", tf, orthography="hausa"
        )
        assert score < DISTINCTIVE_FLOOR

    def test_a_common_compound_is_not_distinctive(self, tf):
        """A compound is only as distinctive as its most COMMON part."""
        score = shared_name_distinctiveness(
            "Primary Health Centre", "Primary Health Center", tf, orthography="hausa"
        )
        assert score < DISTINCTIVE_FLOOR

    @pytest.mark.parametrize(
        ("a", "b"),
        [
            ("Kurugu Health Post", "Alfindi Health Post"),
            ("Fatima Hospital", "Fatouma Hospital"),
            ("Dorayi Babba Health Post", "Dorayi Karama Health Clinic"),
            ("Sarigarin Health Post", "Sari Girin Health Post"),
            ("Ririwai Primary Health Centre", "Riruwai Primary Health Center"),
        ],
    )
    def test_pack_never_changes_a_negative_case(self, tf, a, b):
        """Enabling the pack must be purely additive.

        The last two are the pack's declared `known_gaps` — vowel alternations
        we deliberately do NOT handle, because resolving them needs a Hausa
        speaker rather than a pattern. If a future rule starts clearing these,
        that is a decision to make deliberately, not to discover.
        """
        assert shared_name_distinctiveness(
            a, b, tf, orthography="hausa"
        ) == shared_name_distinctiveness(a, b, tf)

    def test_orthography_is_off_by_default(self, tf):
        a, b = "Maitsidau Health Post", "Mai Tsidau Health Post"
        assert shared_name_distinctiveness(a, b, tf) < shared_name_distinctiveness(
            a, b, tf, orthography="hausa"
        )


class TestPurelyAdditive:
    """Enabling a pack must never lower a score.

    Learned the hard way. The first wiring computed the TF-weighted Jaccard
    over orthographic keys *instead of* literal tokens, which restructures the
    denominator: on the real Kano crosswalk it recovered 13 pairs and demoted
    79. Taking the max of the literal and keyed scores means a pack can only
    ever recover a pair that was being dropped.
    """

    @pytest.mark.parametrize(
        ("a", "b"),
        [
            ("Tagwaye Health Post", "Tagwaye Primary Health Center"),
            ("Yakanawa Primary Health Centre", "Yakanawa Health Post"),
            ("Koya Health Post", "Koya (Dambatta) Health Post"),
            ("Tsalle Health Post", "Tsalle Primary Health Care Center"),
            ("Kurugu Health Post", "Alfindi Health Post"),
            ("Central Dispensary", "Central Dispensary"),
        ],
    )
    def test_token_sim_never_falls(self, tf, a, b):
        assert tf.weighted_token_sim(
            a, b, orthography="hausa"
        ) >= tf.weighted_token_sim(a, b)

    @pytest.mark.parametrize(
        ("a", "b"),
        [
            ("Yangwarzo Health Post", "Yan Gwarzo Health Post"),
            ("Kafinmaiko Health Post", "Kafin Maiko Health Post"),
            ("Sambauna Primary Health Centre", "Sanbauna Primary Health Center"),
        ],
    )
    def test_token_sim_rises_for_the_target_class(self, tf, a, b):
        assert tf.weighted_token_sim(a, b, orthography="hausa") > tf.weighted_token_sim(a, b)

    def test_a_join_that_bridges_nothing_is_ignored(self, tf):
        """Both names already share "health" and "post" individually, so the
        joined "healthpost" carries no new agreement and must not be counted
        again — that is double-counting a shared type."""
        a, b = "Kurugu Health Post", "Alfindi Health Post"
        assert tf.weighted_token_sim(a, b, orthography="hausa") == pytest.approx(
            tf.weighted_token_sim(a, b)
        )


class TestReachableFromACrosswalkSpec:
    """Wired into `crosswalk` via the comparator spec, not just callable.

    `orthography` was opt-in on `shared_name_distinctiveness` and
    `weighted_token_sim` and defaulted to None on both, so no pack ever
    reached a `crosswalk` call. The measured gain in the place benchmark came
    from binding the comparator by hand, which meant the shipped path did not
    have it. Declaring it on the comparator spec is what closes that.
    """

    A = "Muhammadu Bello Clinic"
    B = "Muhammad Bello Clinic"

    def _spec(self, orthography):
        tftoken = {"field": "name", "kind": "tftoken", "weight": 2.0}
        if orthography:
            tftoken["orthography"] = orthography
        return [{"field": "name", "kind": "placename", "weight": 2.0}, tftoken]

    def _edge(self, orthography):
        from arche.resolve import crosswalk
        res = crosswalk([{"id": "a", "name": self.A}], [{"id": "b", "name": self.B}],
                        id_field="id", comparators=self._spec(orthography))
        return res["matches"][0] if res["matches"] else None

    def test_the_pack_changes_the_token_score(self):
        plain, folded = self._edge(None), self._edge("hausa")
        assert plain["evidence"]["name_tftoken"] < folded["evidence"]["name_tftoken"]

    def test_and_that_is_enough_to_change_the_decision(self):
        """`Muhammadu` and `Muhammad` are one name spelled two ways."""
        assert self._edge(None)["decision"] == "review"
        assert self._edge("hausa")["decision"] == "match"

    def test_absent_by_default(self):
        """Every published pack number was measured without it."""
        from arche.resolve import ENTITY_PACKS
        for name, pack in ENTITY_PACKS.items():
            assert not any("orthography" in spec for spec in pack), name
