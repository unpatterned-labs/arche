# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Unit labels, country words, specialty types and `operated_by`.

Every case below is a pair the 18 November 2026 UK and Nigeria runs decided
wrongly or ambiguously. The discriminators are refute-only: each test of a
true pair checks nothing was held that should not be.
"""

from __future__ import annotations

import pytest
from arche.resolve import reconcile
from arche.resolve._name_markers import (
    compare_countries,
    compare_designators,
    name_countries,
    name_designators,
)

_AT = {"lat": 51.5, "lon": -0.12}


def _decide(a: str, b: str, entity: str = "organisation", **kw) -> str:
    result = reconcile([{"id": "a", "name": a, **_AT}], [{"id": "b", "name": b, **_AT}],
                       entity=entity, id_field="id", block=None, **kw)
    return result["matches"][0]["decision"] if result["matches"] else "none"


class TestDesignators:
    @pytest.mark.parametrize("name,expected", [
        ("Ark Data Centres (UK) Cody Park A103", {"a103"}),
        ("Spring Park P4", {"p4"}),
        ("Geregu II power station", {"2"}),
        ("Geregu 2 power station", {"2"}),
        ("Weetabix Corby 2", {"2"}),
        ("Pure DC LON01 London", {"lon01"}),
        ("2nd Avenue Clinic", {"2"}),
        ("I Love Food Ltd", set()),
        ("Geregu Power Plant", set()),
        ("One Stop Shop", set()),
    ])
    def test_extraction(self, name, expected):
        assert name_designators(name) == frozenset(expected)

    def test_roman_and_digits_agree(self):
        assert compare_designators("Geregu II", "Geregu 2") == 1.0

    def test_absence_is_not_disagreement(self):
        assert compare_designators("Geregu I power station", "Geregu Power Plant") is None

    def test_different_units_refute(self):
        assert compare_designators("Cody Park A103", "Cody Park A102") == 0.0

    def test_different_units_are_held_not_merged(self):
        assert _decide("Ark Data Centres (UK) Cody Park A103",
                       "Ark Data Centres (UK) Cody Park A102") != "match"

    def test_same_unit_still_matches(self):
        assert _decide("Weetabix Ltd Corby 2", "Weetabix Corby 2") == "match"


class TestCountries:
    @pytest.mark.parametrize("name,expected", [
        ("Birds Eye Ltd. UK (Invoicing Only)", {"GB"}),
        ("Birds Eye Ireland Ltd. (Invoicing Only)", {"IE"}),
        ("Premier Seeds Nigeria Limited", {"NG"}),
        ("South African Breweries", {"ZA"}),
        ("Iceland Foods Ltd", set()),          # a supermarket, not a country
        ("Malta Guinness Depot", set()),       # a drink
        ("Jersey Knitwear", set()),
    ])
    def test_extraction(self, name, expected):
        assert name_countries(name) == frozenset(expected)

    def test_parts_do_not_contradict_the_whole(self):
        assert compare_countries("Acme Scotland", "Acme UK") == 1.0
        assert compare_countries("Acme UK & Ireland", "Acme Ireland") is None

    def test_two_countries_two_companies(self):
        assert _decide("Birds Eye Ltd. UK (Invoicing Only)",
                       "Birds Eye Ireland Ltd. (Invoicing Only)") != "match"

    def test_same_country_still_matches(self):
        assert _decide("Premier Seeds Nigeria Limited", "Premier Seeds Nigeria Ltd") == "match"

    def test_the_lexicon_is_pinned(self):
        result = reconcile([{"id": "a", "name": "Acme UK", **_AT}],
                           [{"id": "b", "name": "Acme UK", **_AT}],
                           entity="organisation", id_field="id", block=None)
        assert result["pins"]["data_assets"]["country_markers"].startswith("country_markers@")


class TestSpecialtyTypes:
    def test_shared_specialty_with_different_names_is_held(self):
        assert _decide("Impro Vision Eye Clinic", "Dupsnl Vision Eye Clinic",
                       entity="health_facility") != "match"

    @pytest.mark.parametrize("a,b", [
        ("St Joseph Eye Clinic", "St Joseph Eye Clinic"),
        ("Sabon Gari Dental Clinic", "Sabon Gari Dental Clinic"),
        ("Lere Primary Health Centre", "Lere Primary Health Center"),
        ("Pantami Primary Health Centre", "Pantami Primary Health Centre"),
    ])
    def test_true_pairs_still_match(self, a, b):
        assert _decide(a, b, entity="health_facility") == "match"

    def test_the_place_pack_is_unchanged(self):
        # Its published numbers predate these discriminators.
        from arche.resolve import ENTITY_PACKS

        kinds = {s["kind"] for s in ENTITY_PACKS["place"]}
        assert not kinds & {"rival", "designator", "country"}


class TestOperatedBy:
    _SITE = [{"id": "s", "name": "Samworth Brothers Leicester", **_AT}]
    _CO = [{"id": "c", "name": "Samworth Brothers Leicester", **_AT}]

    def test_relation_is_pinned_only_when_declared(self):
        plain = reconcile(self._SITE, self._CO, entity="organisation", id_field="id")
        assert "relation" not in plain["pins"]
        rel = reconcile(self._SITE, self._CO, entity="organisation", id_field="id",
                        relation="operated_by")
        assert rel["pins"]["relation"] == "operated_by"
        assert rel["matches"][0]["decision_id"] != plain["matches"][0]["decision_id"]

    def test_unknown_relation_is_refused(self):
        with pytest.raises(ValueError, match="relation"):
            reconcile(self._SITE, self._CO, entity="organisation", id_field="id",
                      relation="owns")

    def test_the_ledger_relates_and_never_merges(self, tmp_path):
        from arche.ledger import Ledger

        ledger = Ledger(str(tmp_path / "l.duckdb"))
        result = reconcile(self._SITE, self._CO, entity="organisation", id_field="id",
                           relation="operated_by", store=ledger)
        decision = ledger.decision(result["matches"][0]["decision_id"])
        assert decision.identity == "operated_by"
        assert decision.action == "relate"
        assert not decision.linked
        assert not ledger.entities()


def test_the_splink_backend_does_not_swallow_the_relation():
    # `splink_crosswalk` takes `**_ignored`; a relation landing there would be
    # dropped and the ledger would merge a site with its operator.
    import inspect

    pytest.importorskip("splink")
    from arche.resolve._splink_backend import splink_crosswalk

    assert "relation" in inspect.signature(splink_crosswalk).parameters


class TestWrongHoldsFromTheFirstRerun:
    """Pairs the first version held that it should not have (18 Nov rerun)."""

    @pytest.mark.parametrize("a,b", [
        ("Orchard House Foods Factory 1 & 2", "Orchard House Food Factory 2"),
        ("Weetabix - Corby 1 & 2", "Weetabix Corby 2"),
        ("Pure DC LON01 London Brent Cross Data Center",
         "Pure DC LON01 London Brent Cross Data Center (Building 1)"),
        ("D 2 Staff Clinic", "D2 Staff Clinic"),
        ("Prestige Medical Clinic 6 A Aina Obembe Street",
         "Prestige Medical Clinic 6a Aina Obembe Street"),
    ])
    def test_a_site_and_its_part_or_one_label_written_twice(self, a, b):
        assert compare_designators(a, b) is None or compare_designators(a, b) == 1.0

    def test_two_buildings_still_refute(self):
        assert compare_designators(
            "Pure DC LON01 London Brent Cross Data Center (Building 1)",
            "Pure DC LON01 London Brent Cross Data Center (Building 2)") == 0.0

    @pytest.mark.parametrize("a,b", [
        ("Okparavero Memorial Hospital", "Akparavero Memorial Hospital"),
        ("Mount Harmon Hospital", "Mount Hermon Hospital"),
        ("Braithweith Memorial Specialist Hospital", "Braitwait Memorial Specialist Hospital"),
        ("Abdulaziz Memorial Hospital And Maternity", "Abdulazeez Memorial Clinic and Maternity"),
        ("Kadija Memorial Hospital", "Khadija Memorial Hospital"),
        ("Dan Itace Health Post", "Dan Itache Health Post"),
        ("Unguwar Mallam Ahmadu Health Post", "Unguwar Malam Amadu Health Post"),
    ])
    def test_transliterated_spellings_are_not_rivals(self, a, b):
        from arche.resolve._gate import rival_distinctive_tokens
        from arche.resolve._tokenfreq import TokenFrequencyTable
        from arche.resolve.reconcile import _strip_type_cached

        tf = TokenFrequencyTable.default(domain="place")
        sa = _strip_type_cached(a, "health_facility")
        sb = _strip_type_cached(b, "health_facility")
        assert rival_distinctive_tokens(sa, sb, tf, near=0.85) is None

    @pytest.mark.parametrize("a,b", [
        ("University Of Ibadan Teaching Hospital", "University of Ilorin Teaching Hospital"),
        ("Ellymedix Medical Diagnostic Laboratory", "Calvary Medical Diagnostic Laboratory"),
    ])
    def test_different_names_still_held(self, a, b):
        assert _decide(a, b, entity="health_facility") != "match"


class TestCompassWords:
    def test_different_directions_refute(self):
        from arche.resolve._name_markers import compare_designators

        assert compare_designators("Sarkin Yamma Health Post", "Sarkin Kudu Health Post") == 0.0
        assert compare_designators("Dala North Clinic", "Dala South Clinic") == 0.0
        assert compare_designators("Ikeja Ariwa PHC", "Ikeja North PHC") == 1.0

    def test_one_side_without_a_direction_is_silent(self):
        from arche.resolve._name_markers import compare_designators

        assert compare_designators("Sarkin Yamma Health Post", "Sarkin Health Post") is None

    def test_the_vocabulary_is_pinned(self):
        from arche.resolve import reconcile

        out = reconcile([{"id": "a", "name": "Sarkin Yamma Health Post"}],
                        [{"id": "b", "name": "Sarkin Kudu Health Post"}],
                        entity="health_facility", id_field="id")
        assert out["pins"]["data_assets"]["designator_markers"].startswith("designator_markers@")
