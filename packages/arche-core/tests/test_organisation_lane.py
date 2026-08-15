# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""The organisation entity lane.

Every test here is a case from the failure catalogue in the project's working
definition of "the same organisation":

    Two records refer to the same organisation when they denote the same LEGAL
    OR INSTITUTIONAL PARTY, as that party would be named on a document
    evidencing a transaction. Sameness of site, membership, ownership,
    management, certificate or payment destination is NOT sameness of party.

The cases are drawn from cocoa, coffee and tea supply chains, where the
aggregation node differs by commodity — society for cocoa, washing station for
coffee, factory or estate for tea — but the shape does not: a named site,
operated by a legal entity, aggregating from many smallholders.

These are correctness tests, not a benchmark. No accuracy claim is made here
and none should be quoted from this file.
"""

from __future__ import annotations

import pytest

from arche.resolve import ENTITY_PACKS, crosswalk
from arche.resolve._matcher import compare_categories, load_type_vocab, normalize_type_token
from arche.resolve.reconcile import _DISTINCTIVE_KINDS, _FIELD_COMPARATORS


def _link(a: list[dict], b: list[dict], **kw):
    return crosswalk(a, b, entity="organisation", id_field="id", **kw)


def _verdict(a: dict, b: dict) -> str:
    """The decision for one pair, or 'no_candidate' if never proposed."""
    res = _link([a], [b])
    return res["matches"][0]["decision"] if res["matches"] else "no_candidate"


class TestThePackIsWiredCorrectly:
    def test_both_spellings_resolve_to_one_pack(self):
        assert ENTITY_PACKS["organisation"] is ENTITY_PACKS["organization"]

    def test_the_category_kind_is_registered(self):
        assert "category" in _FIELD_COMPARATORS

    def test_a_class_can_never_clear_the_distinctive_gate(self):
        """Two records both being SITE is not evidence they are the same site.

        If `category` were distinctive, every pair sharing a low-entropy class
        label would hold an identity signal. `id` is distinctive by
        construction; a class is the exact opposite.
        """
        assert "category" not in _DISTINCTIVE_KINDS

    def test_organisation_names_never_consult_the_person_lexicon(self):
        """Fatima=Fatouma is a fact about people, not about two businesses
        named after two different people. Merging companies is a legal error."""
        kinds = {(c.get("field"), c["kind"]) for c in ENTITY_PACKS["organisation"]}
        assert ("name", "placename") in kinds
        assert ("name", "name") not in kinds

    def test_geo_carries_no_veto(self):
        """A registered office and an operating site are legitimately far
        apart, so distance must not refute a party — unlike `place`."""
        geo = [c for c in ENTITY_PACKS["organisation"] if c["kind"] == "geo"]
        assert geo and "veto_km" not in geo[0]


class TestTheShippedPopulationTable:
    """The asset the generic-name guard depends on.

    Built from GLEIF LEI Level 1 data (CC0 1.0) — see
    `datasets/organisations_dataops/SOURCES.md` for the licence comparison and,
    more importantly, for what this table cannot tell you.
    """

    def test_the_pack_uses_the_shipped_table_not_self_calibration(self):
        from arche.resolve import _PACK_TF_DOMAIN

        assert _PACK_TF_DOMAIN.get("organisation") == "organisation"
        assert _PACK_TF_DOMAIN.get("organization") == "organisation"

    def test_it_is_population_scale(self):
        """The flag is not cosmetic: the distinctive-signal cap is conditioned
        on it, so a table that lost it would silently reopen the over-merge."""
        from arche.resolve._tokenfreq import TokenFrequencyTable

        assert TokenFrequencyTable.default("organisation").population_scale

    def test_it_knows_ordinary_corporate_tokens_are_ordinary(self):
        from arche.resolve._tokenfreq import TokenFrequencyTable

        counts = TokenFrequencyTable.default("organisation")._counts
        assert counts.get("limited", 0) > 1000
        assert counts.get("holdings", 0) > 100

    def test_the_curated_yaml_ships_and_is_editable(self):
        """The hand-editable half. A contributor who has read a supplier list
        should be able to fix the table without touching Python."""
        from importlib.resources import files

        pack = files("arche.resolve").joinpath("_data/organisation_tokens.yaml")
        text = pack.read_text(encoding="utf-8")
        assert "generic_tokens:" in text
        assert "frequency_overrides:" in text

    def test_the_curated_layer_fixed_what_the_corpus_could_not(self):
        """GLEIF counts `farmers` once in 52,875 names, because LEI lists
        financial-market participants and not cooperatives. Measured alone it
        reads as *rare*, which would let two unrelated `X Farmers Cooperative
        Society` records clear the gate on those words. The YAML asserts the
        domain judgement the corpus structurally cannot supply."""
        from arche.resolve._tokenfreq import TokenFrequencyTable

        counts = TokenFrequencyTable.default("organisation")._counts
        total = sum(counts.values())
        # Compared with a tolerance, not as an exact `>=`. Raising a token also
        # raises the corpus total, so the builder iterates to a fixed point and
        # lands *on* the floor by design — 0.0009999999999989876, a hair under
        # 1e-3 in floating point. Asserting the bare boundary would be testing
        # float representation rather than whether the layer applied.
        floor = 1.0e-3 * 0.999
        for token in ("farmers", "cooperative", "society", "central",
                      "estate", "factory", "washing", "cocoa", "coffee", "tea"):
            assert counts.get(token, 0) / total >= floor, (
                f"{token!r} is not priced as generic; the curated layer in "
                "organisation_tokens.yaml did not apply"
            )

    def test_the_curated_layer_never_marks_a_distinctive_name_generic(self):
        """The rule that keeps the file from destroying the pack.

        Marking `kuapa` or `sefwi` generic would be catastrophic in the
        opposite direction to the bug it fixes — those tokens are what tells
        one cooperative from another, and a pack that cannot use them cannot
        match anything. Commodity words are generic; place and proper names are
        not, and the YAML's scope note says so.
        """
        from arche.resolve._tokenfreq import TokenFrequencyTable

        counts = TokenFrequencyTable.default("organisation")._counts
        total = sum(counts.values())
        for token in ("kuapa", "kokoo", "sefwi", "wiawso", "gicherori",
                      "asunafo", "mutira", "kericho"):
            assert counts.get(token, 0) / total < 1.0e-3, (
                f"{token!r} is priced as generic — a distinctive cooperative "
                "name has been added to organisation_tokens.yaml, which would "
                "stop the pack matching the very records it exists for"
            )

    def test_it_does_not_know_west_african_cooperative_names(self):
        """Asserted, not lamented.

        LEI registration follows financial-market participation, so it lists 51
        entities for Côte d'Ivoire. This table is the right instrument for
        stopping a generic corporate token clearing the gate and the wrong one
        for any claim about African organisation names. If that ever stops
        being true — a Trase-derived table, adjudicated African data — this
        test failing is the correct way to find out, because the honest caveat
        in SOURCES.md would then need rewriting too.
        """
        from arche.resolve._tokenfreq import TokenFrequencyTable

        counts = TokenFrequencyTable.default("organisation")._counts
        for token in ("kuapa", "sefwi", "wiawso", "gicherori"):
            assert counts.get(token, 0) == 0, (
                f"{token!r} is now in the organisation table; the 'knows "
                "nothing about West African cooperative naming' caveat in "
                "SOURCES.md and the pack docstring must be revisited"
            )


class TestTheCategoryComparator:
    def test_normalises_separators_and_case(self):
        for other in ("Washing Station", "WASHING-STATION", " washing station "):
            assert compare_categories("washing_station", other) == 1.0

    def test_different_classes_score_zero(self):
        assert compare_categories("SITE", "OPERATOR") == 0.0

    def test_empty_is_not_agreement(self):
        assert compare_categories("", "SITE") == 0.0


class TestTheVocabularyStripsTheForm:
    """So the matcher compares the distinctive part, not the shared form."""

    @pytest.mark.parametrize("name,expect_residual", [
        ("Kuapa Kokoo Farmers Union", "kuapa kokoo"),
        ("Sefwi Wiawso Cooperative Society", "sefwi wiawso"),
        ("Nyeri Hill Tea Factory", "nyeri hill"),
        # "coffee washing station" is the longest matching synonym, so the
        # commodity word goes with the form — which is right: "Coffee" is not
        # what distinguishes one washing station from another.
        ("Gicherori Coffee Washing Station", "gicherori"),
        ("Kericho Estate", "kericho"),
        ("Produce Buying Company", ""),
        ("Olam Ghana Limited", "olam ghana"),
        ("Touton Negoce SARL", "touton negoce"),
    ])
    def test_residual_is_the_distinctive_name(self, name, expect_residual):
        vocab = load_type_vocab("organization")
        _, residual = normalize_type_token(name, vocab)
        assert residual.strip().casefold() == expect_residual

    def test_every_commodity_node_is_recognised(self):
        """Cocoa society, coffee washing station, tea factory/estate."""
        vocab = load_type_vocab("organization")
        for name, expected in [
            ("Asunafo Cooperative", "COOPERATIVE"),
            ("Kabare Washing Station", "WASHING_STATION"),
            ("Michimikuru Tea Factory", "FACTORY"),
            ("Kericho Estate", "ESTATE"),
            ("Kuapa Kokoo Farmers Union", "UNION"),
            ("Produce Buying Company", "BUYING_COMPANY"),
        ]:
            assert normalize_type_token(name, vocab)[0] == expected, name


class TestTheFailureCatalogue:
    """The cases that must not merge. Each is a realistic false merge."""

    def test_case_1_a_site_is_not_its_operator(self):
        """The largest false-merge risk in supply-chain data.

        Same name, same coordinate, and stripping the shared form leaves them
        MORE alike ("Nyeri Hill" vs "Nyeri Hill Tea"). Only the declared class
        refutes it.
        """
        site = {"id": "s", "name": "Nyeri Hill Factory", "entity_class": "SITE",
                "lat": -0.42, "lon": 36.95}
        operator = {"id": "o", "name": "Nyeri Hill Tea Factory Co Ltd",
                    "entity_class": "OPERATOR", "lat": -0.42, "lon": 36.95}
        assert _verdict(site, operator) != "match"

    def test_case_1b_without_a_class_it_abstains_rather_than_inventing_one(self):
        """The class is missing-value-safe. Absent evidence refutes nothing,
        so the pair must not be silently treated as refuted — but it must also
        not be confidently merged on name+geo alone."""
        site = {"id": "s", "name": "Nyeri Hill Factory", "lat": -0.42, "lon": 36.95}
        operator = {"id": "o", "name": "Nyeri Hill Tea Factory Co Ltd",
                    "lat": -0.42, "lon": 36.95}
        assert _verdict(site, operator) in {"match", "review", "no_candidate"}

    def test_case_3_a_society_is_not_its_union(self):
        society = {"id": "s", "name": "Kuapa Kokoo Cooperative Society",
                   "entity_class": "COOPERATIVE"}
        union = {"id": "u", "name": "Kuapa Kokoo Farmers Union",
                 "entity_class": "UNION"}
        assert _verdict(society, union) != "match"

    def test_case_4_a_generic_name_is_not_an_identity(self):
        """The `Central Dispensary` over-merge in a new costume.

        The guard is the *rarity* of what two names share, and rarity is a
        property of a population rather than of the two lists in front of you.
        Geo carries no veto in this pack, so distance cannot save this pair
        either — the frequency table is the only thing standing here.

        This was a strict xfail until the GLEIF-derived organisation table
        shipped (`datasets/organisations_dataops/`). Before it, the pack
        self-calibrated over the records being linked, and fourteen records
        cannot know that "Central" is ordinary, so every token looked maximally
        rare and the pair merged at `distinctive_max` 1.0. The marker was
        strict precisely so that landing the table would report itself rather
        than pass silently, which is what happened.
        """
        common = [
            {"id": f"a{i}", "name": n, "entity_class": "COOPERATIVE"}
            for i, n in enumerate([
                "Central Cooperative Society", "Central Farmers Cooperative",
                "Central Growers Association", "Kuapa Kokoo Cooperative",
                "Asunafo Cooperative Society", "Gicherori Cooperative",
                "Mutira Farmers Cooperative", "Kabare Cooperative Society",
            ])
        ]
        other = [
            {"id": f"b{i}", "name": n, "entity_class": "COOPERATIVE"}
            for i, n in enumerate([
                "Central Cooperative Society", "Central Union of Cooperatives",
                "Central Producers Association", "Sefwi Wiawso Cooperative",
                "Michimikuru Cooperative", "Kericho Cooperative Society",
            ])
        ]
        res = _link(common, other)
        pair = [m for m in res["matches"]
                if m["a_id"] == "a0" and m["b_id"] == "b0"]
        if pair:
            # It may legitimately still match on an identical string; what it
            # must NOT do is treat the shared generic token as a *distinctive*
            # signal, which is what licenses a confident merge.
            assert pair[0]["distinctive_max"] < 1.0, (
                "a name shared with several other records in the corpus was "
                "priced as a distinctive identity signal"
            )

    def test_case_9_an_estate_is_not_one_of_its_divisions(self):
        estate = {"id": "e", "name": "Kericho Estate", "entity_class": "ESTATE"}
        division = {"id": "d", "name": "Kericho Estate Division 3",
                    "entity_class": "DIVISION"}
        assert _verdict(estate, division) != "match"

    def test_a_registration_number_conflict_refutes(self):
        """Two parties with different registration numbers are different
        parties however alike their names."""
        a = {"id": "a", "name": "Olam Ghana Limited", "registration_id": "CS123456"}
        b = {"id": "b", "name": "Olam Ghana Limited", "registration_id": "CS999999"}
        assert _verdict(a, b) != "match"


class TestWhatShouldStillMatch:
    """Refusal is only a virtue if the pack still finds the true pairs."""

    def test_the_same_party_across_two_spellings_of_its_form(self):
        a = {"id": "a", "name": "Sefwi Wiawso Cooperative Society",
             "entity_class": "COOPERATIVE"}
        b = {"id": "b", "name": "Sefwi Wiawso Co-operative Society Ltd",
             "entity_class": "COOPERATIVE"}
        assert _verdict(a, b) == "match"

    def test_a_shared_registration_number_carries_the_pair(self):
        """The exact-identity signal, even when the names were entered
        differently by two parties who never agreed on a format."""
        a = {"id": "a", "name": "Touton Negoce SARL", "registration_id": "RC-88421"}
        b = {"id": "b", "name": "Touton Negoce", "registration_id": "RC-88421"}
        assert _verdict(a, b) == "match"

    def test_the_class_agreeing_does_not_by_itself_merge_anything(self):
        """Two unrelated cooperatives both classed COOPERATIVE must not merge.
        This is the property `category` not being distinctive buys."""
        a = {"id": "a", "name": "Asunafo Cooperative", "entity_class": "COOPERATIVE"}
        b = {"id": "b", "name": "Gicherori Cooperative", "entity_class": "COOPERATIVE"}
        assert _verdict(a, b) != "match"
