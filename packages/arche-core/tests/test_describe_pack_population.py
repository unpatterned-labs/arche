# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""`describe_pack` says which population rarity is measured against.

It did not, and the omission was not neutral -- it actively taught the wrong
model. The `tftoken` note read "how rare the shared words are **in these two
lists**", which is true only for a pack with no shipped table. For `place`,
`organisation` and `artist` the population is a shipped corpus, and that is the
entire reason the same pair lands differently under different packs:

    compare_records([{"name": "General Hospital"}],
                    [{"name": "General Hospital"}], entity="organisation")
    -> {"decision": "match", "score": 1.0, "distinctive_max": 0.862}

    ... the same call with entity="place"
    -> {"decision": "review", "score": 1.0, "distinctive_max": 0.564}

`hospital` is 1-in-57 tokens in a facility gazetteer and 11-in-223,842 in a
registry of legal entities that participate in financial markets. Both numbers
are correct about their own corpus. Neither is a fact about hospitals.

A caller told that rarity came from their own two lists cannot predict any of
that, and has no reason to go looking. So the note now names the reference
population and `frequency_table` reports it.
"""

from __future__ import annotations

import pytest
from arche.resolve import ENTITY_PACKS, describe_pack, describe_packs


class TestItNamesThePopulation:

    @pytest.mark.parametrize("entity,domain", [
        ("place", "place"),
        ("organisation", "organisation"),
        ("organization", "organisation"),
        ("artist", "artist"),
    ])
    def test_packs_with_a_shipped_table_say_which(self, entity, domain):
        assert describe_pack(entity)["frequency_table"] == domain

    def test_a_self_calibrating_pack_reports_none(self):
        """`None` means "built from the two lists you passed", not "no rarity
        check". A small pair cannot know any of its own tokens are ordinary, so
        everything in it reads as rare."""
        assert describe_pack("person")["frequency_table"] is None

    def test_every_pack_answers_the_question(self):
        """Present on all of them, including the ones where the answer is None.
        A missing key and a null are different claims, and only one of them is
        true here."""
        for entity, described in describe_packs().items():
            assert "frequency_table" in described, entity

    def test_both_spellings_agree(self):
        """They are the same list object; they must not describe differently."""
        assert (describe_pack("organisation")["frequency_table"]
                == describe_pack("organization")["frequency_table"])

    def test_it_matches_what_crosswalk_actually_loads(self):
        """Description tracking behaviour, not a second place to maintain it.

        Read from the same mapping `crosswalk` dispatches on, so a pack given a
        table without a description update cannot drift.
        """
        from arche.resolve import _PACK_TF_DOMAIN

        for entity in ENTITY_PACKS:
            assert (describe_pack(entity)["frequency_table"]
                    == _PACK_TF_DOMAIN.get(entity))


class TestTheNoteNoLongerMisleads:

    def _tftoken_note(self, entity):
        for field in describe_pack(entity)["fields"]:
            if "tftoken" in field["kinds"]:
                for note in field["notes"]:
                    if "rare" in note:
                        return note
        raise AssertionError(f"no tftoken note on {entity}")

    @pytest.mark.parametrize("entity", ["place", "organisation", "artist", "person"])
    def test_it_does_not_claim_the_two_lists_are_the_population(self, entity):
        """The regression. True for `person`, false for the other three, and
        stated unconditionally for all of them."""
        assert "in these two lists" not in self._tftoken_note(entity)

    @pytest.mark.parametrize("entity", ["place", "organisation", "artist", "person"])
    def test_it_points_at_the_field_that_answers_it(self, entity):
        assert "frequency_table" in self._tftoken_note(entity)


class TestTheBehaviourItDescribes:
    """The description is only worth anything if the packs really do differ.

    Pinned with the pair from the docs, so a table rebuild that moved these
    across the floor fails here rather than silently changing what merges.
    """

    def test_the_same_name_is_review_as_a_place_and_match_as_an_organisation(self):
        from arche.resolve import reconcile

        a = [{"id": "1", "name": "General Hospital"}]
        b = [{"id": "2", "name": "General Hospital"}]

        place = reconcile(a, b, entity="place", id_field="id")["matches"][0]
        org = reconcile(a, b, entity="organisation", id_field="id")["matches"][0]

        assert place["decision"] == "review", place
        assert org["decision"] == "match", org
        # Agreement is identical. Only the population moved.
        assert place["score"] == org["score"] == pytest.approx(1.0)
        assert place["distinctive_max"] < org["distinctive_max"]

    def test_the_pin_records_which_population_scored_it(self):
        """Two runs pinning different tables were scored against different
        vocabularies and are not expected to agree."""
        from arche.resolve import reconcile

        a = [{"id": "1", "name": "General Hospital"}]
        b = [{"id": "2", "name": "General Hospital"}]

        assert reconcile(a, b, entity="place",
                         id_field="id")["pins"]["tf"].startswith("shipped:place")
        assert reconcile(a, b, entity="person",
                         id_field="id")["pins"]["tf"].startswith("self-calibrated")
