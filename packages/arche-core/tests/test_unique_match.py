# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""`reconcile(unique_match=True)`, the ward level, and Nigeria's admin path.

Shapes from the Nigeria state+LGA lane (20 Nov 2026), names invented: without
coordinates, `Makera PHC` met both `Makera I PHC` and `Makera II PHC` in one
LGA and the engine matched one of them.
"""

from __future__ import annotations

import pytest
from arche.ids import edge_decision_id
from arche.jurisdictions.nigeria import admin_path, is_state
from arche.resolve import ENTITY_PACKS, reconcile
from arche.resolve._matcher import compare_containment

LGA = admin_path("Kano", "Dala")


def _run(left, right, **kw):
    return reconcile(left, right, entity="health_facility", id_field="id", **kw)


SIBLINGS_LEFT = [{"id": "g1", "name": "Kurmawa Primary Health Centre", "admin_path": LGA}]
SIBLINGS_RIGHT = [
    {"id": "o1", "name": "Kurmawa Primary Health Centre", "admin_path": LGA},
    {"id": "o2", "name": "Kurmawa Health Centre", "admin_path": LGA},
]


class TestUniqueMatch:
    def test_off_by_default_and_unpinned(self):
        out = _run(SIBLINGS_LEFT, SIBLINGS_RIGHT)
        assert "unique_match" not in out["pins"]
        assert any(m["decision"] == "match" for m in out["matches"])

    def test_two_plausible_candidates_hold_the_match(self):
        out = _run(SIBLINGS_LEFT, SIBLINGS_RIGHT, unique_match=True)
        assert out["pins"]["unique_match"] is True
        assert len(out["matches"]) >= 2, "the fixture needs two plausible candidates"
        assert all(m["decision"] == "review" for m in out["matches"])
        held = [m for m in out["matches"] if "ambiguous" in m]
        assert held and held[0]["ambiguous"] == len(out["matches"])

    def test_a_single_candidate_still_matches(self):
        out = _run(SIBLINGS_LEFT, SIBLINGS_RIGHT[:1], unique_match=True)
        assert [m["decision"] for m in out["matches"]] == ["match"]
        assert "ambiguous" not in out["matches"][0]

    def test_the_right_side_counts_too(self):
        # Two left records claiming one right record: one of them is wrong.
        left = [SIBLINGS_LEFT[0], {**SIBLINGS_LEFT[0], "id": "g2"}]
        out = _run(left, SIBLINGS_RIGHT[:1], unique_match=True)
        assert all(m["decision"] != "match" for m in out["matches"])

    def test_decision_ids_cover_the_final_decision(self):
        out = _run(SIBLINGS_LEFT, SIBLINGS_RIGHT, unique_match=True)
        for m in out["matches"]:
            assert m["decision_id"] == edge_decision_id(m, out["pins"])

    def test_it_only_demotes(self):
        plain = {(m["a_id"], m["b_id"]): m["decision"]
                 for m in _run(SIBLINGS_LEFT, SIBLINGS_RIGHT)["matches"]}
        held = {(m["a_id"], m["b_id"]): m["decision"]
                for m in _run(SIBLINGS_LEFT, SIBLINGS_RIGHT, unique_match=True)["matches"]}
        assert set(plain) == set(held)
        for pair, decision in held.items():
            assert decision == plain[pair] or (plain[pair], decision) == ("match", "review")


class TestWardLevel:
    def test_health_facility_reads_wards_and_place_does_not(self):
        def levels(pack):
            return next(s for s in ENTITY_PACKS[pack] if s["kind"] == "containment").get("levels")
        assert levels("place") is None
        assert levels("health_facility") == ["admin1", "admin2", "admin3", "settlement"]

    def test_ward_agreement_outranks_lga_and_ward_disagreement_never_refutes(self):
        same_ward = compare_containment(admin_path("Kano", "Dala", "Kabuwaya"),
                                        admin_path("Kano", "Dala", "Kabuwaya"),
                                        levels=("admin1", "admin2", "admin3", "settlement"))
        other_ward = compare_containment(admin_path("Kano", "Dala", "Kabuwaya"),
                                         admin_path("Kano", "Dala", "Gwammaja"),
                                         levels=("admin1", "admin2", "admin3", "settlement"))
        assert same_ward == 0.8 and other_ward == 0.6

    def test_default_walk_is_unchanged(self):
        a = {"admin1": "kano", "admin2": "dala", "admin3": "x", "settlement": "y"}
        b = {"admin1": "kano", "admin2": "dala", "admin3": "z", "settlement": "y"}
        assert compare_containment(a, b) == 1.0


class TestNigeriaAdminPath:
    def test_folding_and_aliases(self):
        assert admin_path("Federal Capital Territory", "AMAC", "Garki Ward") == {
            "admin1": "fct", "admin2": "amac", "admin3": "garki"}
        assert admin_path("Nassarawa State", "Lafia L.G.A") == {"admin1": "nasarawa",
                                                                 "admin2": "lafia"}
        assert admin_path("Nassarawa State", "Lafia LGA") == {"admin1": "nasarawa",
                                                               "admin2": "lafia"}

    def test_missing_levels_are_left_out(self):
        assert admin_path("Kano") == {"admin1": "kano"}
        assert admin_path(None, None, None) == {}

    def test_is_state(self):
        assert is_state("Akwa-Ibom") and is_state("abuja") and not is_state("Accra")


def test_a_deeper_unnamed_level_never_scores_below_the_one_above():
    a = {"admin1": "gauteng", "admin2": "city of johannesburg", "admin4": "ward 12"}
    levels = ("admin1", "admin2", "admin4")
    assert compare_containment(a, dict(a), levels=levels) >= 0.6


class TestFacilityTypeRefutation:
    """A clinic is never the hospital of its town; how strict to be within
    primary care depends on how a country names its tiers."""

    @staticmethod
    def _decide(a: str, b: str, pack: str) -> str:
        out = reconcile([{"id": "a", "name": a, "lat": -30.0, "lon": 25.0}],
                        [{"id": "b", "name": b, "lat": -30.0005, "lon": 25.0}],
                        entity=pack, id_field="id")
        return out["matches"][0]["decision"]

    def test_across_kinds_both_packs_hold(self):
        for pack in ("health_facility", "health_facility_za"):
            assert self._decide("Nelspoort Clinic", "Nelspoort Hospital", pack) == "review"
            assert self._decide("Umzimkhulu Clinic", "Umzimkhulu Psychiatric Hospital",
                                pack) == "review"

    def test_within_primary_care_only_the_za_pack_holds(self):
        # Nigerian lists name one facility PHC, health clinic or health centre.
        assert self._decide("Turmi Primary Health Centre", "Turmi Health Clinic",
                            "health_facility") == "match"
        assert self._decide("Ngangelizwe CHC", "Ngangelizwe Clinic",
                            "health_facility") == "match"
        assert self._decide("Ngangelizwe CHC", "Ngangelizwe Clinic",
                            "health_facility_za") == "review"

    def test_a_name_without_a_type_is_silent(self):
        for pack in ("health_facility", "health_facility_za"):
            assert self._decide("Healdtown", "Healdtown Clinic", pack) == "match"

    def test_groups_are_pinned(self):
        from arche.resolve._matcher import load_type_groups

        assert load_type_groups("health_facility")["CHC"] == "primary_care"
        assert load_type_groups("organization") == {}


BRANCHES = [
    {"id": "r1", "name": "Kanyiri Medical Centre", "address": "14 Ajala Road, Temanu"},
    {"id": "r3", "name": "Kanyiri Medical Centre", "address": "90 Ashgrove Road, Obodo"},
]
NO_ADDRESS = {"id": "r2", "name": "Kanyiri Medical Centre"}


class TestNameOnly:
    """A record with only a name agrees with every branch, and would join them."""

    def _decisions(self, left, right, mode):
        out = reconcile(left, right, entity="place", id_field="id", unique_match=mode)
        return {(m["a_id"], m["b_id"]): m["decision"] for m in out["matches"]}

    def test_the_fault_it_is_for(self):
        d = self._decisions(BRANCHES, [NO_ADDRESS], False)
        assert set(d.values()) == {"match"} and len(d) == 2

    def test_a_name_that_meets_two_branches_is_held(self):
        assert set(self._decisions(BRANCHES, [NO_ADDRESS], "name_only").values()) == {"review"}

    def test_one_branch_still_matches_on_the_name(self):
        assert self._decisions(BRANCHES[:1], [NO_ADDRESS], "name_only") == {("r1", "r2"): "match"}

    def test_a_supported_match_stands_beside_a_held_one(self):
        same = {"id": "r5", "name": "Kanyiri Medical Centre", "address": "14 Ajala Road, Temanu"}
        d = self._decisions(BRANCHES[:1], [NO_ADDRESS, same], "name_only")
        assert d == {("r1", "r2"): "review", ("r1", "r5"): "match"}

    def test_pinned_and_verifiable(self):
        out = reconcile(BRANCHES, [NO_ADDRESS], entity="place", id_field="id",
                        unique_match="name_only")
        assert out["pins"]["unique_match"] == "name_only"
        edge = dict(out["matches"][0])
        assert edge["ambiguous"] == 2
        assert edge.pop("decision_id") == edge_decision_id(edge, out["pins"])

    def test_an_unknown_mode_is_refused(self):
        with pytest.raises(ValueError, match="name_only"):
            reconcile(BRANCHES, [NO_ADDRESS], entity="place", id_field="id", unique_match="names")
