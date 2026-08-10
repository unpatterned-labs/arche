# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Place-lane hardening tests — the 2026-08-05 audit findings, pinned.

Four tickets: union blocking (the recall cliff), the place-calibrated pack
(the Fatima-Hospital false-merge vector), per-edge attestation, and the
containment top-down walk.
"""

from __future__ import annotations

import math

import pytest
from arche.resolve import ENTITY_PACKS, crosswalk
from arche.resolve._block import (
    blocking_recall,
    candidate_pairs,
    id_candidate_pairs,
    token_candidate_pairs,
    union_candidate_pairs,
)
from arche.resolve._matcher import (
    compare_containment,
    compare_geo,
    compare_names,
    compare_place_names,
    haversine_km,
)
from arche.resolve.reconcile import reconcile, sign_edges


def _offset_km(lat: float, km: float) -> float:
    """Degrees of latitude for a north-south offset of ``km``."""
    return km / 111.32


# ---------------------------------------------------------------------------
# T1 — union blocking
# ---------------------------------------------------------------------------


class TestUnionBlocking:
    def _true_pair_lists(self, offset_km: float):
        """One true match, coordinates ``offset_km`` apart, sharing a rare token."""
        a = [{"id": "a1", "name": "Karfi Health Post", "lat": 11.60, "lon": 8.55}]
        b = [{"id": "b1", "name": "Karfi Primary Health Centre",
              "lat": 11.60 + _offset_km(11.60, offset_km), "lon": 8.55}]
        return a, b

    @pytest.mark.parametrize("offset", [0.5, 3.0, 5.0, 8.0])
    def test_union_keeps_far_apart_true_pairs(self, offset):
        # The audit's cliff: H3 res-7 1-ring recall was 58%/15.5%/0% at
        # 3/4/5 km. The rare-token key must keep these pairs regardless.
        a, b = self._true_pair_lists(offset)
        pairs, info = union_candidate_pairs(
            a, b, text_fields=("name",), id_fields=(),
        )
        assert (0, 0) in pairs
        assert info["token"] >= 0  # info reports per-strategy contributions

    def test_h3_only_drops_the_5km_pair_union_does_not(self):
        a, b = self._true_pair_lists(5.0)
        h3_pairs = list(candidate_pairs(a, b))
        union_pairs, _ = union_candidate_pairs(a, b, text_fields=("name",))
        assert (0, 0) in union_pairs
        # Documents WHY union exists; if H3 alone ever keeps this pair the
        # safety net got wider and this assertion should be revisited.
        assert (0, 0) not in h3_pairs

    def test_safety_res_extends_spatial_reach(self):
        a, b = self._true_pair_lists(4.0)
        plain = list(candidate_pairs(a, b, pair_coordless_with_all=False))
        with_net = list(candidate_pairs(
            a, b, safety_res=6, pair_coordless_with_all=False,
        ))
        assert len(with_net) >= len(plain)

    def test_token_blocking_skips_common_tokens(self):
        # 60x60 records all sharing "clinic" — the cap must refuse to emit
        # 3,600 pairs off a junk token.
        a = [{"id": f"a{i}", "name": f"Clinic {i}"} for i in range(60)]
        b = [{"id": f"b{j}", "name": f"Clinic {j + 100}"} for j in range(60)]
        pairs = list(token_candidate_pairs(a, b, ("name",), pair_cap=1000))
        assert not pairs  # "clinic" over-budget; numerals don't collide

    def test_id_blocking_pairs_shared_identifier(self):
        a = [{"id": "a1", "name": "Alpha", "reg_no": "NG-00-123"}]
        b = [{"id": "b1", "name": "Totally Different", "reg_no": "ng00123"}]
        pairs = list(id_candidate_pairs(a, b, ("reg_no",)))
        assert (0, 0) in pairs

    def test_coordless_records_reach_candidates_via_tokens(self):
        a = [{"id": "a1", "name": "Gyaranya Dispensary"}]  # no coords at all
        b = [{"id": "b1", "name": "Gyaranya Dispensary",
              "lat": 11.9, "lon": 8.4}]
        pairs, info = union_candidate_pairs(a, b, text_fields=("name",))
        assert (0, 0) in pairs
        assert info["coordless_a"] == 1

    def test_reconcile_default_is_union(self):
        # A 5 km-offset true pair must survive the DEFAULT path now.
        a, b = self._true_pair_lists(5.0)
        result = reconcile(
            a, b,
            [{"field": "name", "kind": "placename", "weight": 2.0}],
        )
        assert any(
            m["a_id"] == "a1" and m["b_id"] == "b1" for m in result["matches"]
        )
        strategies = result["blocking"]["strategies"]
        # Either the res-6 safety net or the rare-token key kept the pair —
        # both are union contributions the old h3-only default lacked.
        assert strategies["h3"] + strategies["token"] >= 1

    def test_blocking_recall_reported_with_truth_pairs(self):
        a, b = self._true_pair_lists(5.0)
        result = reconcile(
            a, b,
            [{"field": "name", "kind": "placename", "weight": 2.0}],
            truth_pairs=[("a1", "b1")],
        )
        assert result["blocking"]["recall"] == 1.0

    def test_h3_coordless_warns_loudly(self):
        a = [{"id": "a1", "name": "Alpha"}]  # coordless
        b = [{"id": "b1", "name": "Beta", "lat": 9.0, "lon": 7.0}]
        with pytest.warns(RuntimeWarning, match="lack coordinates"):
            reconcile(
                a, b,
                [{"field": "name", "kind": "placename"}],
                block="h3",
            )

    def test_blocking_recall_metric(self):
        assert blocking_recall([("a", "b")], [("a", "b"), ("a", "c")]) == 1.0
        assert blocking_recall([("a", "b"), ("x", "y")], [("a", "b")]) == 0.5


# ---------------------------------------------------------------------------
# T2 — the place-calibrated pack
# ---------------------------------------------------------------------------


class TestPlacePack:
    def test_placename_never_uses_person_lexicon(self):
        # The measured false-merge vector: the person lexicon scores
        # Fatima≡Fatouma at 1.0. Two facilities named after two different
        # people must NOT get that gift.
        person_sim = compare_names("Fatima Hospital", "Fatouma Hospital")[0]
        place_sim = compare_place_names("Fatima Hospital", "Fatouma Hospital")
        assert person_sim == 1.0  # documents the vector placename closes
        assert place_sim < 1.0

    def test_placename_exact_and_reordered(self):
        assert compare_place_names("Karfi PHC", "Karfi PHC") == 1.0
        assert compare_place_names("Ikeja Lagos", "Lagos Ikeja") > 0.9

    def test_pack_uses_placename_not_name(self):
        kinds = {c["kind"] for c in ENTITY_PACKS["place"]}
        assert "placename" in kinds and "name" not in kinds
        assert "type" in kinds

    def test_pack_geo_decay_is_place_calibrated(self):
        geo = next(c for c in ENTITY_PACKS["place"] if c["kind"] == "geo")
        assert geo["decay_km"] == 3.0
        # At 2 km the place decay keeps geo meaningfully alive (~0.51),
        # where the person default 1.5 km had faded to ~0.26.
        assert compare_geo(0.0, 0.0, _offset_km(0.0, 2.0), 0.0,
                           decay_km=3.0) == pytest.approx(math.exp(-2 / 3), abs=0.02)

    def test_type_comparator_scores_tier(self):
        specs = [{"field": "name", "kind": "type", "domain": "health_facility"}]
        same = reconcile(
            [{"id": "a", "name": "Karfi Primary Health Centre"}],
            [{"id": "b", "name": "Karfi PHC"}],
            specs, block=None, threshold=0.9,
        )
        diff = reconcile(
            [{"id": "a", "name": "Karfi Primary Health Centre"}],
            [{"id": "b", "name": "Karfi General Hospital"}],
            specs, block=None, threshold=0.9, review_margin=0.9,
        )
        assert same["matches"][0]["evidence"]["name"] == 1.0
        assert diff["matches"][0]["evidence"]["name"] == 0.0

    def test_type_comparator_inapplicable_without_type_token(self):
        # No recognised type on one side -> comparator says nothing (None),
        # never a fake disagreement.
        result = reconcile(
            [{"id": "a", "name": "Karfi"}],
            [{"id": "b", "name": "Karfi PHC"}],
            [{"field": "name", "kind": "placename", "weight": 1.0},
             {"field": "name", "kind": "type", "domain": "health_facility"}],
            block=None,
        )
        assert "name_type" not in result["matches"][0]["evidence"]

    def test_distance_km_in_evidence(self):
        a = [{"id": "a", "name": "Karfi PHC", "lat": 11.60, "lon": 8.55}]
        b = [{"id": "b", "name": "Karfi PHC",
              "lat": 11.60 + _offset_km(11.60, 3.0), "lon": 8.55}]
        result = crosswalk(a, b, entity="place")
        edge = result["matches"][0]
        assert edge["evidence"]["distance_km"] == pytest.approx(3.0, abs=0.1)

    def test_fatima_fatouma_does_not_auto_merge(self):
        # End-to-end on the pack: two different facilities, same coordinates,
        # names equivalent only under the PERSON lexicon. Must not be "match".
        a = [{"id": "a", "name": "Fatima Hospital", "lat": 12.0, "lon": 8.5}]
        b = [{"id": "b", "name": "Fatouma Hospital", "lat": 12.0, "lon": 8.5}]
        result = crosswalk(a, b, entity="place")
        for m in result["matches"]:
            assert m["decision"] != "match"

    def test_notebook_scenario_both_flagship_pairs_route_to_review(self):
        # The place_lane_tour notebook's corpus, pinned: the namesake pair
        # must NOT auto-merge and the tier-upgrade pair must NOT fall below
        # the review floor — both are review, a human decides. This is the
        # regression net for the type-weight-0 calibration decision: at any
        # naive type weight one of these two breaks (measured 2026-08-05).
        registry = [
            {"id": "REG-01", "name": "Karfi Health Post",
             "lat": 11.60, "lon": 8.55},
            {"id": "REG-02", "name": "Fatima Hospital",
             "lat": 12.00, "lon": 8.50},
        ]
        survey = [
            {"id": "SVY-01", "name": "Karfi Primary Health Centre",
             "lat": 11.618, "lon": 8.55},
            {"id": "SVY-02", "name": "Fatouma Hospital",
             "lat": 12.00, "lon": 8.50},
        ]
        result = crosswalk(registry, survey, entity="place",
                           truth_pairs=[("REG-01", "SVY-01")])
        decisions = {(m["a_id"], m["b_id"]): m for m in result["matches"]}
        assert decisions[("REG-01", "SVY-01")]["decision"] == "review"
        assert decisions[("REG-02", "SVY-02")]["decision"] == "review"
        # type agreement stays VISIBLE to the reviewer even at weight 0
        assert decisions[("REG-02", "SVY-02")]["evidence"]["name_type"] == 1.0
        assert result["blocking"]["recall"] == 1.0


# ---------------------------------------------------------------------------
# T3 — place attestation
# ---------------------------------------------------------------------------


class TestEdgeAttestation:
    def _result(self, **kwargs):
        a = [{"id": "a", "name": "Karfi Primary Health Centre",
              "lat": 11.60, "lon": 8.55}]
        b = [{"id": "b", "name": "Karfi Primary Health Center",
              "lat": 11.601, "lon": 8.55}]
        return crosswalk(a, b, entity="place", **kwargs)

    def test_every_edge_carries_decision_id(self):
        result = self._result()
        assert result["matches"]
        for m in result["matches"]:
            assert m["decision_id"].startswith("xwd:sha256:")

    def test_decision_id_is_reproducible_and_pin_sensitive(self):
        r1, r2 = self._result(), self._result()
        assert r1["matches"][0]["decision_id"] == r2["matches"][0]["decision_id"]
        r3 = self._result(extra_pins={"boundary_layer": "GRID3-NGA-2024.1"})
        assert r3["matches"][0]["decision_id"] != r1["matches"][0]["decision_id"]
        assert r3["pins"]["boundary_layer"] == "GRID3-NGA-2024.1"

    def test_pins_carry_tf_provenance(self):
        # The place pack uses the SHIPPED place table, not a table
        # self-calibrated over the two lists. Distinctiveness is a claim about
        # a population — a pair of small lists cannot know that `hospital` is
        # common and `Gyaranya` is rare, and while it fell through to the
        # person table those facility words were unseen and read as *rare*.
        result = self._result()
        # The pin names the exact table, not just the domain. A rebuild changes
        # which tokens are rare, and rare tokens are both a comparator input and
        # a blocking key, so a new table can change a decision. If that were
        # invisible in the pin, every decision would keep claiming to be
        # reproducible while quietly meaning something else.
        assert result["pins"]["tf"].startswith("shipped:place@sha256:")
        assert result["pins"]["engine"] == "crosswalk.v1"

    def test_common_name_does_not_clear_the_distinctive_gate(self):
        # Two facilities called "General Hospital" 4.4 km apart are not
        # evidence of one facility, however identical the strings. The
        # distinctive residual is generic on both sides, so the pair must land
        # in `review`; an identically-shaped pair with a rare residual merges.
        common = crosswalk(
            [{"name": "General Hospital", "lat": 12.00, "lon": 8.50}],
            [{"name": "General Hospital", "lat": 12.04, "lon": 8.50}],
            entity="place",
        )["matches"]
        distinctive = crosswalk(
            [{"name": "Gyaranya Health Post", "lat": 12.00, "lon": 8.50}],
            [{"name": "Gyaranya Health Post", "lat": 12.04, "lon": 8.50}],
            entity="place",
        )["matches"]
        assert common and distinctive
        assert common[0]["decision"] == "review"
        assert distinctive[0]["decision"] == "match"
        # Same score — only the rarity of what they share differs.
        assert common[0]["score"] == pytest.approx(distinctive[0]["score"])

    def test_self_calibrated_table_does_not_gate_on_rarity(self):
        # Over a small corpus a token seen twice scores ~0.71, below the 0.75
        # floor, so consulting distinctiveness there would refuse everything.
        # A caller passing their own corpus table must keep the old behaviour.
        from arche.resolve._tokenfreq import TokenFrequencyTable

        names = ["General Hospital", "Karfi Health Post", "Tsalle Health Post"]
        tf = TokenFrequencyTable.from_corpus(names)
        assert tf.population_scale is False
        edges = crosswalk(
            [{"name": "General Hospital", "lat": 12.00, "lon": 8.50}],
            [{"name": "General Hospital", "lat": 12.04, "lon": 8.50}],
            entity="place", tf=tf,
        )["matches"]
        assert edges and edges[0]["decision"] == "match"

    def test_sign_edges_round_trip(self):
        pytest.importorskip("cryptography")
        from arche.sign import generate_keypair, verify

        result = self._result()
        kp = generate_keypair()
        signed = sign_edges(result, private_key=kp.private_key, kid=kp.did_key)
        assert signed
        outcome = verify(signed[0]["jws"], public_key=kp.public_key)
        assert outcome.valid
        payload = outcome.payload
        assert payload["schema"] == "arche.crosswalk_edge.v1"
        assert payload["decision_id"] == result["matches"][0]["decision_id"]
        assert payload["pins"] == result["pins"]

    def test_declaration_pin_enters_edge_pins(self):
        from arche.declare import Declaration

        decl = Declaration.from_dict({
            "arche_declaration": 1,
            "name": "facilities", "version": "1.0.0", "entity": "place",
            "id_field": "id",
            "fields": {
                "name": {"role": "identifies",
                         "kind": ["placename", "tftoken"]},
            },
            "tf": None,
        })
        a = [{"id": "a", "name": "Karfi Primary Health Centre"}]
        b = [{"id": "b", "name": "Karfi PHC"}]
        result = crosswalk(a, b, decl=decl, tf="default")
        assert result["pins"]["declaration"] == decl.pin()


# ---------------------------------------------------------------------------
# T4 — containment top-down walk
# ---------------------------------------------------------------------------


class TestContainmentWalk:
    def test_same_settlement_name_different_lga_is_not_coloc(self):
        # Sabon Gari repeats across Nigerian LGAs: settlement-name agreement
        # under an LGA DISAGREEMENT must cap at the state score, never 1.0.
        a = {"admin1": "Kano", "admin2": "Kura", "settlement": "Sabon Gari"}
        b = {"admin1": "Kano", "admin2": "Gwarzo", "settlement": "Sabon Gari"}
        assert compare_containment(a, b) == 0.3

    def test_consistent_hierarchy_still_awards_finest(self):
        a = {"admin1": "Kano", "admin2": "Kura", "settlement": "Karfi"}
        b = {"admin1": "Kano", "admin2": "Kura", "settlement": "Karfi"}
        assert compare_containment(a, b) == 1.0

    def test_coarsest_disagreement_still_hard_zero(self):
        a = {"admin1": "Kano", "settlement": "Sabon Gari"}
        b = {"admin1": "Kaduna", "settlement": "Sabon Gari"}
        assert compare_containment(a, b) == 0.0

    def test_missing_middle_level_does_not_block_agreement(self):
        a = {"admin1": "Kano", "settlement": "Karfi"}
        b = {"admin1": "Kano", "admin2": "Kura", "settlement": "Karfi"}
        assert compare_containment(a, b) == 1.0

    def test_no_shared_levels_stays_weak_not_conflict(self):
        assert compare_containment({"admin1": "Kano"},
                                   {"settlement": "Karfi"}) == 0.2

    def test_haversine_sanity(self):
        # One degree of latitude ~111.32 km.
        assert haversine_km(0.0, 0.0, 1.0, 0.0) == pytest.approx(111.2, abs=0.5)


# ---------------------------------------------------------------------------
# Declaration surface for the new kinds
# ---------------------------------------------------------------------------


class TestDeclaredPlaceKinds:
    def test_type_kind_requires_domain(self):
        from arche.declare import Declaration, DeclarationError

        with pytest.raises(DeclarationError, match="type_domain"):
            Declaration.from_dict({
                "arche_declaration": 1,
                "name": "f", "version": "1.0.0", "entity": "place",
                "id_field": "id",
                "fields": {"name": {"role": "identifies", "kind": ["type"]}},
            })

    def test_type_domain_flows_into_comparators_and_pin(self):
        from arche.declare import Declaration

        base = {
            "arche_declaration": 1,
            "name": "f", "version": "1.0.0", "entity": "place",
            "id_field": "id",
            "fields": {
                "name": {"role": "identifies", "kind": ["placename", "type"],
                         "type_domain": "health_facility"},
            },
        }
        decl = Declaration.from_dict(base)
        type_spec = next(
            c for c in decl.comparators() if c["kind"] == "type"
        )
        assert type_spec["domain"] == "health_facility"
        other = dict(base)
        other["fields"] = {
            "name": {"role": "identifies", "kind": ["placename", "type"],
                     "type_domain": "organization"},
        }
        assert Declaration.from_dict(other).pin() != decl.pin()
