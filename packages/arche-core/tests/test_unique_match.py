# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""`reconcile(unique_match=True)`, the ward level, and Nigeria's admin path.

Shapes from the Nigeria state+LGA lane (20 Nov 2026), names invented: without
coordinates, `Makera PHC` met both `Makera I PHC` and `Makera II PHC` in one
LGA and the engine matched one of them.
"""

from __future__ import annotations

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
