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

"""Tests for the boundary-aware categorical geography comparators.

`compare_containment` (admin hierarchy) and `compare_postcodes` (postal codes)
are two readings of the same evidence (which polygon contains this point) and
share one boundary discount, `boundary_doubt`. The tests are grouped the same
way: the shared ramp, then each comparator, then the end-to-end behaviour
through `crosswalk`.
"""

import pytest
from arche.resolve import crosswalk
from arche.resolve._matcher import (
    BOUNDARY_UNCERTAINTY_KM,
    POSTCODE_BOUNDARY_UNCERTAINTY_KM,
    boundary_doubt,
    compare_containment,
    compare_postcodes,
    haversine_km,
)

# The weakest agreement `compare_containment` can award (a shared admin1). No
# discounted disagreement may ever reach it. That is the "never manufactures a
# merge" invariant, expressed as a number.
WEAKEST_AGREEMENT = 0.3


def test_same_settlement_is_near_proof():
    a = {"admin1": "Kano", "admin2": "Ungogo", "settlement": "Karfi"}
    b = {"admin1": "Kano", "admin2": "Ungogo", "settlement": "Karfi"}
    assert compare_containment(a, b) == 1.0


def test_same_lga_different_settlement():
    a = {"admin1": "Kano", "admin2": "Ungogo", "settlement": "Karfi"}
    b = {"admin1": "Kano", "admin2": "Ungogo", "settlement": "Rimin Gado"}
    assert compare_containment(a, b) == 0.6


def test_same_state_different_lga_is_weak():
    a = {"admin1": "Kano", "admin2": "Ungogo"}
    b = {"admin1": "Kano", "admin2": "Nassarawa"}
    assert compare_containment(a, b) == 0.3


def test_different_state_is_disagreement_even_if_settlement_name_matches():
    # Coarse conflict is checked first: a shared settlement NAME across states
    # is a collision, not co-location.
    a = {"admin1": "Kano", "admin2": "Ungogo", "settlement": "Karfi"}
    b = {"admin1": "Lagos", "admin2": "Ikeja", "settlement": "Karfi"}
    assert compare_containment(a, b) == 0.0


def test_missing_paths_return_none():
    assert compare_containment(None, {"admin1": "Kano"}) is None
    assert compare_containment({}, {}) is None


def test_no_agreement_no_coarse_conflict_is_weak():
    a = {"admin2": "Ungogo"}
    b = {"admin2": "Nassarawa"}  # no admin1 on either -> no coarse conflict
    assert compare_containment(a, b) == 0.2


def test_normalises_case_and_diacritics():
    a = {"admin1": "Kano", "settlement": "Kofar Mata"}
    b = {"admin1": "kano", "settlement": "kofar  mata"}
    assert compare_containment(a, b) == 1.0


# ---------------------------------------------------------------------------
# The shared boundary ramp
# ---------------------------------------------------------------------------


class TestBoundaryDoubt:
    """`boundary_doubt` is the one place distance turns into a discount."""

    @pytest.mark.parametrize(
        ("distance_km", "expected"),
        [
            (0.0, 1.0),      # same point: a categorical disagreement says nothing
            (0.25, 0.75),
            (0.5, 0.5),      # linear, not exponential
            (0.75, 0.25),
            (1.0, 0.0),      # at the band: full refutation resumes, exactly
            (5.0, 0.0),      # and stays there
            (500.0, 0.0),
        ],
    )
    def test_ramps_linearly_to_zero_at_the_band(self, distance_km, expected):
        assert boundary_doubt(distance_km, 1.0) == pytest.approx(expected)

    def test_reaches_exactly_zero_not_merely_near_it(self):
        # The conflict mechanism downstream keys off an exact 0.0, which an
        # exponential decay would never produce. Pin the exactness.
        assert boundary_doubt(1.0, 1.0) == 0.0
        assert boundary_doubt(1.0000001, 1.0) == 0.0

    @pytest.mark.parametrize(
        "distance_km",
        [None, float("nan"), float("inf"), -1.0, float("-inf")],
    )
    def test_unusable_distance_gives_no_discount(self, distance_km):
        # Missing or nonsensical evidence must never soften a disagreement.
        assert boundary_doubt(distance_km, 1.0) == 0.0

    @pytest.mark.parametrize("boundary_km", [0.0, -1.0])
    def test_non_positive_band_switches_the_discount_off(self, boundary_km):
        assert boundary_doubt(0.0, boundary_km) == 0.0

    def test_is_monotonically_non_increasing_in_distance(self):
        values = [boundary_doubt(d / 20, 1.0) for d in range(40)]
        assert all(a >= b for a, b in zip(values, values[1:], strict=False))

    def test_never_leaves_the_unit_interval(self):
        for d in (0.0, 0.001, 0.5, 0.999, 1.0, 1e9):
            assert 0.0 <= boundary_doubt(d, 1.0) <= 1.0


# ---------------------------------------------------------------------------
# Containment: boundary awareness
# ---------------------------------------------------------------------------


ADAMAWA = {"admin1": "Adamawa", "admin2": "Shelleng"}
BORNO = {"admin1": "Borno", "admin2": "Shani"}


class TestContainmentIsBoundaryAware:
    def test_without_coordinates_behaviour_is_exactly_as_before(self):
        # The regression guard for every existing caller: no distance, no
        # change. This is the same 0.0 the comparator returned before the
        # discount existed, and reconcile still raises a conflict on it.
        assert compare_containment(ADAMAWA, BORNO) == 0.0
        assert compare_containment(ADAMAWA, BORNO, distance_km=None) == 0.0

    def test_at_zero_distance_disagreement_is_uninformative(self):
        # Two points at the same coordinates in "different states" is a
        # statement about a boundary file, not about identity.
        value = compare_containment(ADAMAWA, BORNO, distance_km=0.0)
        assert value == pytest.approx(0.2)
        assert value > 0.0  # so reconcile raises no conflict

    def test_beyond_the_band_disagreement_is_full_refutation(self):
        for km in (BOUNDARY_UNCERTAINTY_KM, 8.77, 143.0, 500.0):
            assert compare_containment(ADAMAWA, BORNO, distance_km=km) == 0.0

    def test_refutation_grows_with_distance(self):
        values = [
            compare_containment(ADAMAWA, BORNO, distance_km=d / 10)
            for d in range(12)
        ]
        assert all(a >= b for a, b in zip(values, values[1:], strict=False))
        assert values[0] > values[-1] == 0.0

    @pytest.mark.parametrize("distance_km", [0.0, 0.001, 0.1, 0.5, 0.9, 0.999])
    def test_never_scores_as_well_as_the_weakest_agreement(self, distance_km):
        # The "must not manufacture a merge" invariant. However close the pair,
        # a state disagreement stays below what a genuinely shared state earns.
        assert (
            compare_containment(ADAMAWA, BORNO, distance_km=distance_km)
            < WEAKEST_AGREEMENT
        )

    def test_band_is_configurable(self):
        # 5 km is inside a 10 km band and outside a 1 km one.
        assert compare_containment(
            ADAMAWA, BORNO, distance_km=5.0, boundary_km=10.0) > 0.0
        assert compare_containment(
            ADAMAWA, BORNO, distance_km=5.0, boundary_km=1.0) == 0.0

    def test_zero_band_restores_the_old_behaviour_at_any_distance(self):
        assert compare_containment(
            ADAMAWA, BORNO, distance_km=0.0, boundary_km=0.0) == 0.0

    def test_agreement_is_untouched_by_distance(self):
        # The discount only ever applies to a disagreement. Two records in the
        # same LGA 500 km apart still agree on the LGA; it is geo's job, not
        # containment's, to notice they cannot be one place.
        same = {"admin1": "Kano", "admin2": "Ungogo", "settlement": "Karfi"}
        assert compare_containment(same, dict(same), distance_km=500.0) == 1.0
        assert compare_containment(same, dict(same), distance_km=0.0) == 1.0

    def test_mid_hierarchy_disagreement_is_deliberately_not_discounted(self):
        # A differing LGA inside an agreeing state already returns the
        # state-level score rather than 0.0, so it never refuted and has
        # nothing to withhold. Discounting it could only raise it toward an
        # agreement it did not earn.
        a = {"admin1": "Kano", "admin2": "Ungogo"}
        b = {"admin1": "Kano", "admin2": "Nassarawa"}
        assert compare_containment(a, b, distance_km=0.0) == 0.3
        assert compare_containment(a, b, distance_km=500.0) == 0.3

    def test_missing_paths_still_return_none_whatever_the_distance(self):
        assert compare_containment(None, ADAMAWA, distance_km=0.0) is None
        assert compare_containment({}, {}, distance_km=0.0) is None


# ---------------------------------------------------------------------------
# The two real Nigeria state-border pairs (notebook 14), pinned
# ---------------------------------------------------------------------------


class TestNigeriaStateBorderRegressions:
    """The two pairs `14_nigeria_schools.ipynb` reports arche merging wrongly.

    Both share a name exactly and sit in different states, so the notebook's
    label rule ("two schools in different states are not one school") calls
    both errors. Both are also on a state border, which is exactly where that
    rule is least trustworthy. Coordinates are the register's own, so these are
    the real pairs and not a reconstruction.
    """

    TUMBU_A = (10.0526960000204, 12.0342689997146)     # Adamawa / Shelleng
    TUMBU_B = (10.0591621875849, 12.0346929626102)     # Borno / Shani
    ABLE_GOD_A = (6.71490279982442, 3.24637149984488)  # Ogun / Ado Odo/Ota
    ABLE_GOD_B = (6.64189999998507, 3.2764199996833)   # Lagos / Alimosho

    def _record(self, rid, name, point, admin1, admin2):
        return {"id": rid, "name": name,
                "lat": str(point[0]), "lon": str(point[1]),
                "admin_path": {"admin1": admin1, "admin2": admin2}}

    def test_tumbu_pair_is_720_metres_apart(self):
        assert haversine_km(*self.TUMBU_A, *self.TUMBU_B) == pytest.approx(
            0.72, abs=0.01)

    def test_able_god_pair_is_8_8_km_apart(self):
        assert haversine_km(*self.ABLE_GOD_A, *self.ABLE_GOD_B) == pytest.approx(
            8.77, abs=0.01)

    def test_tumbu_720m_apart_withholds_refutation(self):
        # 720 m across a state line is the boundary artefact the discount
        # exists for: a boundary file's precision, or a GPS fix taken at the
        # gate rather than the road. arche declines to call this a difference.
        value = compare_containment(
            {"admin1": "Adamawa", "admin2": "Shelleng"},
            {"admin1": "Borno", "admin2": "Shani"},
            distance_km=haversine_km(*self.TUMBU_A, *self.TUMBU_B),
        )
        assert 0.0 < value < WEAKEST_AGREEMENT

    def test_able_god_8_8km_apart_still_refutes_in_full(self):
        # 8.8 km is not a boundary artefact under any boundary layer.
        assert compare_containment(
            {"admin1": "Ogun", "admin2": "Ado Odo/Ota"},
            {"admin1": "Lagos", "admin2": "Alimosho"},
            distance_km=haversine_km(*self.ABLE_GOD_A, *self.ABLE_GOD_B),
        ) == 0.0

    def test_able_god_pair_is_held_for_review_end_to_end(self):
        # The pair that SHOULD be caught by an admin disagreement still is,
        # through the shipped place pack, with no configuration.
        edge = crosswalk(
            [self._record("a", "Able God Group Of School", self.ABLE_GOD_A,
                          "Ogun", "Ado Odo/Ota")],
            [self._record("b", "Able God Group Of School", self.ABLE_GOD_B,
                          "Lagos", "Alimosho")],
            entity="place", id_field="id",
        )["matches"][0]
        assert edge["evidence"]["admin_path"] == 0.0
        assert edge["decision"] == "review"

    def test_tumbu_pair_reaches_match_and_says_why_in_the_evidence(self):
        # Documenting the trade honestly: withholding refutation at 720 m lets
        # this pair through as a match. The evidence names the discounted
        # containment value, so a reviewer can see the pair was judged on a
        # near-boundary admin disagreement rather than on agreement.
        edge = crosswalk(
            [self._record("a", "Tumbu Primary School", self.TUMBU_A,
                          "Adamawa", "Shelleng")],
            [self._record("b", "Tumbu Primary School", self.TUMBU_B,
                          "Borno", "Shani")],
            entity="place", id_field="id",
        )["matches"][0]
        assert 0.0 < edge["evidence"]["admin_path"] < WEAKEST_AGREEMENT
        assert edge["evidence"]["distance_km"] == pytest.approx(0.72, abs=0.01)
        assert edge["decision"] == "match"

    def test_the_discount_lowers_the_score_it_does_not_raise_it(self):
        # A near-boundary admin disagreement is still worse evidence than no
        # admin data at all. Withholding refutation must not become a bonus.
        with_admin = crosswalk(
            [self._record("a", "Tumbu Primary School", self.TUMBU_A,
                          "Adamawa", "Shelleng")],
            [self._record("b", "Tumbu Primary School", self.TUMBU_B,
                          "Borno", "Shani")],
            entity="place", id_field="id",
        )["matches"][0]
        without = crosswalk(
            [{"id": "a", "name": "Tumbu Primary School",
              "lat": str(self.TUMBU_A[0]), "lon": str(self.TUMBU_A[1])}],
            [{"id": "b", "name": "Tumbu Primary School",
              "lat": str(self.TUMBU_B[0]), "lon": str(self.TUMBU_B[1])}],
            entity="place", id_field="id",
        )["matches"][0]
        assert with_admin["score"] < without["score"]


# ---------------------------------------------------------------------------
# Postal codes
# ---------------------------------------------------------------------------


class TestPostcodeAgreement:
    @pytest.mark.parametrize(
        ("a", "b"),
        [
            ("SW1A 1AA", "SW1A 1AA"),
            ("SW1A 1AA", "sw1a1aa"),      # case and whitespace
            ("SW1A 1AA", "SW1A-1AA"),     # hyphen
            ("  sw1a 1aa  ", "SW1A1AA"),
            ("10001", "10001"),
            ("900211", "900211"),         # NG 6-digit
        ],
    )
    def test_same_code_is_full_agreement(self, a, b):
        assert compare_postcodes(a, b) == 1.0

    @pytest.mark.parametrize(
        ("a", "b"),
        [
            ("SW1A 1AA", "SW1A 2BB"),      # GB: same outward, different unit
            ("EC2A 3AR", "EC2A 4XY"),
            ("10001-1234", "10001-5678"),  # ZIP+4: same ZIP, different +4
            ("SW1A", "SW1A 1AA"),          # partial against full
        ],
    )
    def test_same_district_different_unit_is_partial_agreement(self, a, b):
        assert compare_postcodes(a, b) == 0.5

    @pytest.mark.parametrize(
        ("a", "b"),
        [("", "SW1A 1AA"), ("SW1A 1AA", ""), ("", ""), ("   ", "SW1A 1AA")],
    )
    def test_a_missing_code_is_missing_evidence_not_disagreement(self, a, b):
        assert compare_postcodes(a, b) is None

    def test_different_districts_without_coordinates_refute_in_full(self):
        assert compare_postcodes("SW1A 1AA", "EC2A 3AR") == 0.0
        assert compare_postcodes("100001", "900211") == 0.0


class TestPostcodeIsBoundaryAware:
    def test_at_zero_distance_a_different_postcode_says_nothing(self):
        value = compare_postcodes("SW1A 1AA", "EC2A 3AR", distance_km=0.0)
        assert value == pytest.approx(0.2)
        assert value > 0.0

    def test_fifty_metres_apart_is_a_postcode_boundary(self):
        # A UK unit postcode covers ~15 delivery points, often one side of one
        # street, so two different units 50 m apart routinely straddle a line.
        assert compare_postcodes(
            "SW1A 1AA", "EC2A 3AR", distance_km=0.05) > 0.0

    def test_thirty_km_apart_is_a_different_place(self):
        assert compare_postcodes("SW1A 1AA", "EC2A 3AR", distance_km=30.0) == 0.0

    def test_default_band_is_much_tighter_than_the_admin_one(self):
        # A postal unit is far smaller than a state, so its boundary
        # uncertainty is far smaller too. Guard against the two defaults being
        # accidentally unified.
        assert POSTCODE_BOUNDARY_UNCERTAINTY_KM < BOUNDARY_UNCERTAINTY_KM

    @pytest.mark.parametrize("distance_km", [0.0, 0.01, 0.05, 0.099])
    def test_never_scores_as_well_as_a_shared_district(self, distance_km):
        assert compare_postcodes(
            "SW1A 1AA", "EC2A 3AR", distance_km=distance_km) < 0.5

    def test_band_is_configurable(self):
        assert compare_postcodes(
            "SW1A 1AA", "EC2A 3AR", distance_km=1.5, boundary_km=2.0) > 0.0
        assert compare_postcodes(
            "SW1A 1AA", "EC2A 3AR", distance_km=1.5, boundary_km=0.1) == 0.0

    def test_agreement_is_untouched_by_distance(self):
        assert compare_postcodes("SW1A 1AA", "SW1A 1AA", distance_km=900.0) == 1.0

    @pytest.mark.parametrize("distance_km", [None, float("nan"), -3.0])
    def test_unusable_distance_falls_back_to_full_refutation(self, distance_km):
        assert compare_postcodes(
            "SW1A 1AA", "EC2A 3AR", distance_km=distance_km) == 0.0

    def test_formats_are_not_reconciled_across_countries(self):
        # A GB code against a ZIP is simply a disagreement; the distance ramp
        # then decides. Nothing pretends they share a hierarchy.
        assert compare_postcodes("SW1A 1AA", "10001") == 0.0
        assert compare_postcodes("SW1A 1AA", "10001", distance_km=0.0) > 0.0


class TestPostcodeThroughCrosswalk:
    """The `postcode` kind end-to-end, including its opt-in refutation.

    Deliberately declared with NO geo comparator: the postcode comparator reads
    the record's own `lat`/`lon` for its distance, so boundary awareness does
    not require a geo comparator to be declared alongside it. Name weight is
    high enough that every pair below would be a `match` on the name alone,
    which makes the refutation the only thing that can demote one.
    """

    COMPARATORS = [
        {"field": "name", "kind": "placename", "weight": 4.0},
        {"field": "postcode", "kind": "postcode", "weight": 1.0,
         "refutes_below": 0.1},
    ]

    def _run(self, postcode_b, lat_b, lon_b):
        return crosswalk(
            [{"id": "a", "name": "Rosewood Clinic", "postcode": "SW1A 1AA",
              "lat": "51.5010", "lon": "-0.1416"}],
            [{"id": "b", "name": "Rosewood Clinic", "postcode": postcode_b,
              "lat": str(lat_b), "lon": str(lon_b)}],
            comparators=self.COMPARATORS, id_field="id", block=None,
        )["matches"][0]

    def test_a_distant_postcode_disagreement_refutes(self):
        # ~28 km east of Westminster.
        edge = self._run("EC2A 3AR", 51.5010, 0.2600)
        assert edge["evidence"]["postcode"] == 0.0
        assert "postcode_conflict" in edge["evidence"]
        assert edge["decision"] == "review"

    def test_a_postcode_disagreement_across_the_street_does_not_refute(self):
        # ~22 m away: the same building's far side, a different postcode unit.
        edge = self._run("EC2A 3AR", 51.5012, -0.1416)
        assert edge["evidence"]["postcode"] > 0.0
        assert "postcode_conflict" not in edge["evidence"]
        assert edge["decision"] == "match"

    def test_a_missing_postcode_never_refutes(self):
        edge = crosswalk(
            [{"id": "a", "name": "Rosewood Clinic", "postcode": "SW1A 1AA",
              "lat": "51.5010", "lon": "-0.1416"}],
            [{"id": "b", "name": "Rosewood Clinic",
              "lat": "51.5010", "lon": "0.2600"}],
            comparators=self.COMPARATORS, id_field="id", block=None,
        )["matches"][0]
        assert "postcode" not in edge["evidence"]
        assert "postcode_conflict" not in edge["evidence"]
        assert edge["decision"] == "match"

    def test_records_without_coordinates_refute_on_the_postcode_alone(self):
        # No coordinates means no discount, which is the safe direction.
        edge = crosswalk(
            [{"id": "a", "name": "Rosewood Clinic", "postcode": "SW1A 1AA"}],
            [{"id": "b", "name": "Rosewood Clinic", "postcode": "EC2A 3AR"}],
            comparators=self.COMPARATORS, id_field="id", block=None,
        )["matches"][0]
        assert edge["evidence"]["postcode"] == 0.0
        assert edge["decision"] == "review"


def test_postcode_is_a_declarable_kind():
    from arche.declare import _KINDS
    assert "postcode" in _KINDS
