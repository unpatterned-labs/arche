# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Tests for the geographic veto on the crosswalk gate.

Distance is a physical constraint, not a preference. As a weighted signal geo
was outvoted 4:1 by name+tftoken, so two Kano facilities sharing a common Hausa
name merged 143 km apart with geo scoring 0.000. `veto_km` makes distance
capable of refusing.
"""

from __future__ import annotations

import copy

from arche.resolve import ENTITY_PACKS, crosswalk


def _pack(veto_km):
    p = copy.deepcopy(ENTITY_PACKS["place"])
    for spec in p:
        if spec["kind"] == "geo":
            if veto_km is None:
                spec.pop("veto_km", None)
            else:
                spec["veto_km"] = veto_km
    return p


# Same name, ~150 km apart: the real failure this veto exists for.
_FAR_A = [{"name": "Yan Bawa Health Post", "lat": "11.5", "lon": "8.0"}]
_FAR_B = [{"name": "Yan Bawa Health Post", "lat": "12.5", "lon": "9.0"}]

_NEAR_A = [{"name": "Karfi Health Post", "lat": "11.62", "lon": "8.49"}]
_NEAR_B = [{"name": "Karfi Health Post", "lat": "11.62", "lon": "8.49"}]


def _decisions(A, B, veto_km):
    res = crosswalk(A, B, comparators=_pack(veto_km))
    return [m["decision"] for m in res["matches"]]


class TestVeto:
    def test_identical_name_far_apart_is_matched_without_the_veto(self):
        """The bug, pinned. Without a veto an identical name merges at 150 km."""
        assert "match" in _decisions(_FAR_A, _FAR_B, None)

    def test_identical_name_far_apart_is_demoted_by_the_veto(self):
        assert "match" not in _decisions(_FAR_A, _FAR_B, 10.0)

    def test_demoted_to_review_not_dropped(self):
        """A veto says a human must look, not that the answer is no.

        Dropping the pair would lose the facility silently; `review` keeps it
        in front of an adjudicator with the distance as evidence.
        """
        assert _decisions(_FAR_A, _FAR_B, 10.0) == ["review"]

    def test_nearby_pairs_are_untouched(self):
        assert _decisions(_NEAR_A, _NEAR_B, 10.0) == ["match"]

    def test_a_generous_veto_does_not_fire(self):
        assert "match" in _decisions(_FAR_A, _FAR_B, 500.0)


class TestEvidence:
    def test_conflict_distance_is_recorded_for_the_reviewer(self):
        res = crosswalk(_FAR_A, _FAR_B, comparators=_pack(10.0))
        ev = res["matches"][0]["evidence"]
        assert "geo_conflict_km" in ev
        assert ev["geo_conflict_km"] > 10.0

    def test_no_conflict_key_when_the_veto_does_not_fire(self):
        res = crosswalk(_NEAR_A, _NEAR_B, comparators=_pack(10.0))
        assert "geo_conflict_km" not in res["matches"][0]["evidence"]


class TestMissingCoordinates:
    """Absent evidence refutes nothing."""

    def test_records_without_coordinates_are_never_vetoed(self):
        A = [{"name": "Karfi Health Post"}]
        B = [{"name": "Karfi Health Post"}]
        assert _decisions(A, B, 10.0) == ["match"]

    def test_one_sided_coordinates_are_never_vetoed(self):
        A = [{"name": "Karfi Health Post", "lat": "11.62", "lon": "8.49"}]
        B = [{"name": "Karfi Health Post"}]
        assert _decisions(A, B, 10.0) == ["match"]

    def test_unparseable_coordinates_do_not_raise(self):
        A = [{"name": "Karfi Health Post", "lat": "not-a-number", "lon": "8.49"}]
        B = [{"name": "Karfi Health Post", "lat": "11.62", "lon": "8.49"}]
        assert _decisions(A, B, 10.0)  # no exception, some decision returned


class TestShippedDefault:
    def test_place_pack_ships_a_veto(self):
        geo = [s for s in ENTITY_PACKS["place"] if s["kind"] == "geo"][0]
        assert geo["veto_km"] == 10.0

    def test_shipped_pack_refuses_the_143km_merge(self):
        res = crosswalk(_FAR_A, _FAR_B, entity="place")
        assert [m["decision"] for m in res["matches"]] == ["review"]
