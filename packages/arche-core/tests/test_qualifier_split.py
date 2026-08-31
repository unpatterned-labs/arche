# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Tests for place-name qualifier splitting.

Sources disambiguate places by appending the containing region, and they do not
agree on how. Measured on the Leipzig Geographic Settlements benchmark, four
sources describe the same settlements four ways:

    NYTimes   Petra (Jordan)      99.7% qualified
    DBpedia   Cordoba, Spain      36.8% qualified
    Freebase  savannah             0.0% qualified
    GeoNames  Split                0.0% qualified

A name comparator reads the qualifier as part of the identifying string, so
`Marseille (France)` against `Marseille` scored 0.661 — under the threshold —
while the distinctiveness gate was clearing comfortably at 0.90. The failure was
representation, not thresholds, and no floor change fixes it.

Splitting moves the review queue from 1,732 edges to 676 (61% less human
adjudication) at a cost of 1.3 points of pooled precision.

It is **opt-in**, and the measurement is why: on Kano it changes nothing at all
(facility names carry no qualifiers) and on London it recovers nothing while
adding two more unlabelled auto-matches. The qualifier convention is a property
of the *source*, not of places.
"""

from __future__ import annotations

import copy

import pytest

from arche.resolve import ENTITY_PACKS, reconcile
from arche.resolve._matcher import compare_place_qualifiers, split_place_name


class TestSplitPlaceName:
    @pytest.mark.parametrize(("name", "core", "qual"), [
        ("Petra (Jordan)", "Petra", "Jordan"),
        ("Prague (Czech Republic)", "Prague", "Czech Republic"),
        ("Cordoba, Spain", "Cordoba", "Spain"),
        ("San Jose, California", "San Jose", "California"),
        ("Split", "Split", ""),
        ("savannah", "savannah", ""),
    ])
    def test_the_four_source_conventions(self, name, core, qual):
        assert split_place_name(name) == (core, qual)

    def test_a_parenthetical_beats_a_comma(self):
        """`Milford (New Haven, Conn)` is one qualifier, not two splits."""
        assert split_place_name("Milford (New Haven, Conn)") == (
            "Milford", "New Haven, Conn",
        )

    def test_only_the_first_comma_splits(self):
        """Multi-comma names keep the remainder together rather than losing it."""
        assert split_place_name("Paris, Texas, USA") == ("Paris", "Texas, USA")

    def test_a_trailing_parenthetical_wins_over_an_earlier_one(self):
        assert split_place_name("Moorfields (City Road) (campus)") == (
            "Moorfields (City Road)", "campus",
        )

    @pytest.mark.parametrize("name", [
        "(Jordan)",       # no core would remain
        "Petra ()",       # no qualifier inside
        ", Spain",        # no core before the comma
        "Cordoba,",       # nothing after the comma
    ])
    def test_a_degenerate_split_leaves_the_name_whole(self, name):
        """Never manufacture an anonymous qualifier out of a malformed name."""
        core, qual = split_place_name(name)
        assert qual == ""
        assert core == name.strip()

    @pytest.mark.parametrize("name", ["", "   ", None])
    def test_empty_input(self, name):
        assert split_place_name(name) == ("", "")

    def test_surrounding_whitespace_is_stripped(self):
        assert split_place_name("  Petra  (  Jordan  )  ") == ("Petra", "Jordan")


class TestCompareQualifiers:
    def test_identical_qualifiers(self):
        assert compare_place_qualifiers("Paris (France)", "Paris, France") == 1.0

    def test_different_qualifiers_score_low(self):
        """Two different Oxfords must not be confirmed by their qualifiers."""
        assert compare_place_qualifiers(
            "Oxford (England)", "Oxford, Mississippi",
        ) < 0.75

    @pytest.mark.parametrize(("a", "b"), [
        ("Marseille (France)", "Marseille"),   # missing on the right
        ("Marseille", "Marseille (France)"),   # missing on the left
        ("Split", "savannah"),                 # missing on both
    ])
    def test_a_missing_qualifier_is_None_not_zero(self, a, b):
        """Absence is missing evidence, not disagreement.

        Scoring it 0.0 would punish exactly the cross-source pairs this
        comparator exists to help: three of the four benchmark sources leave
        most or all names unqualified.
        """
        assert compare_place_qualifiers(a, b) is None

    def test_abbreviations_are_fuzzy_not_exact(self):
        """`NY` vs `New York` is why this is scored, not a refutation.

        As a `refutes_below` discriminator the qualifier removed 13 false
        merges but cost 17 true ones — a trade a fuzzy field cannot make
        reliably. It stays a weighted signal.
        """
        score = compare_place_qualifiers("Cutchogue (NY)", "Cutchogue, New York")
        assert score is not None
        assert score < 1.0


def _pack(strip: bool):
    pack = copy.deepcopy(ENTITY_PACKS["place"])
    if not strip:
        return pack
    for spec in pack:
        if spec.get("kind") in ("placename", "tftoken"):
            spec["strip_qualifier"] = True
    return pack + [{"field": "name", "kind": "qualifier", "weight": 1.0}]


# Real records from the benchmark, not invented ones — a synthetic pair with
# identical coordinates does not reproduce the defect, because geo then scores
# 1.0 and carries the pair over the threshold on its own.
#
# NYTimes id=3150 against DBpedia id=6941. Their centroids sit 2.46 km apart,
# which is ordinary disagreement between two sources about where a city *is*.
_A = [{"name": "Marseille (France)", "lat": 43.3, "lon": 5.4}]
_B = [{"name": "Marseille", "lat": 43.2964, "lon": 5.36995}]

# NYTimes id=873 against DBpedia id=7487. DBpedia carries no coordinates on
# 42.5% of its records, so geography frequently cannot rescue the pair at all.
_NOGEO_A = [{"name": "Cutchogue (NY)", "lat": 41.0107, "lon": -72.4851}]
_NOGEO_B = [{"name": "Cutchogue, New York"}]


class TestStripQualifierFlag:
    def test_the_defect_pinned(self):
        """Without the flag, one settlement written two ways does not merge.

        Scores 0.661 against a 0.70 threshold: `placename` 0.900 and `tftoken`
        0.533, both diluted by a country name that is not part of the identity.
        """
        res = reconcile(_A, _B, comparators=_pack(False), tf="place")
        assert [e["decision"] for e in res["matches"]] == ["review"]

    def test_splitting_recovers_it(self):
        res = reconcile(_A, _B, comparators=_pack(True), tf="place")
        edge = res["matches"][0]
        assert edge["decision"] == "match"
        # The qualifier was the entire obstacle: both name comparators go to 1.0.
        assert edge["evidence"]["name"] == 1.0
        assert edge["evidence"]["name_tftoken"] == 1.0

    def test_it_works_when_one_side_has_no_coordinates(self):
        """The case geography cannot rescue, which is 42.5% of DBpedia."""
        plain = reconcile(_NOGEO_A, _NOGEO_B, comparators=_pack(False), tf="place")
        split = reconcile(_NOGEO_A, _NOGEO_B, comparators=_pack(True), tf="place")
        assert plain["matches"][0]["decision"] == "review"
        assert split["matches"][0]["decision"] == "match"

    @pytest.mark.parametrize("records", [(_A, _B), (_NOGEO_A, _NOGEO_B)])
    def test_the_gate_was_never_the_problem(self, records):
        """`distinctive_max` clears the 0.75 floor in BOTH configurations.

        This is the finding that stops the next person 'fixing' this by
        lowering DISTINCTIVE_FLOOR. That constant is shared with the person
        lane, where 0.70 lets two different people both named Ibrahim Musa
        auto-merge — see `test_coreference.test_s3_common_name_only_is_review`.
        The floor was never binding here; the representation was wrong.
        """
        a, b = records
        for strip in (False, True):
            res = reconcile(a, b, comparators=_pack(strip), tf="place")
            assert res["matches"][0]["distinctive_max"] >= 0.75

    def test_qualifier_comparator_is_not_itself_stripped(self):
        """Stripping the qualifier kind would leave it nothing to compare."""
        comps = [
            {"field": "name", "kind": "placename", "weight": 2.0,
             "strip_qualifier": True},
            {"field": "name", "kind": "qualifier", "weight": 1.0,
             "strip_qualifier": True},
        ]
        res = reconcile(
            [{"name": "Oxford (England)"}], [{"name": "Oxford, England"}],
            comparators=comps,
        )
        assert res["matches"][0]["evidence"]["name_qualifier"] == 1.0

    def test_different_qualifiers_still_separate_two_places(self):
        """Splitting must not merge every Oxford into one Oxford."""
        a = [{"name": "Oxford (England)", "lat": "51.75", "lon": "-1.26"}]
        b = [{"name": "Oxford, Mississippi", "lat": "34.37", "lon": "-89.52"}]
        res = reconcile(a, b, comparators=_pack(True), tf="place")
        assert "match" not in [e["decision"] for e in res["matches"]]

    def test_unqualified_names_are_unaffected(self):
        """Kano is the evidence: no qualifiers, so nothing may change."""
        a = [{"name": "Karfi Health Post", "lat": "11.62", "lon": "8.49"}]
        b = [{"name": "Karfi Health Post", "lat": "11.62", "lon": "8.49"}]
        plain = reconcile(a, b, comparators=_pack(False), tf="place")
        split = reconcile(a, b, comparators=_pack(True), tf="place")
        assert ([e["decision"] for e in plain["matches"]]
                == [e["decision"] for e in split["matches"]] == ["match"])


class TestShippedPacksUnchanged:
    def test_no_pack_enables_the_split(self):
        """Opt-in, and a test enforces it.

        Measured: enabling it changes Kano not at all, and on London recovers
        nothing while adding two unlabelled auto-matches. It is a large win on
        settlement-style corpora and a small risk on facility corpora, so it
        ships as a capability rather than a default. Turning it on for a pack
        moves that pack's published numbers.
        """
        for name, pack in ENTITY_PACKS.items():
            for spec in pack:
                assert "strip_qualifier" not in spec, f"{name} pack enables it"
                assert spec.get("kind") != "qualifier", f"{name} pack declares it"
