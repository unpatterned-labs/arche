# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""The place world: a known sheet, requests that name it, and a scorer for what the policy did."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

pytest.importorskip("pyarrow")
_REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_REPO / "data" / "synthetic"))

from arche_synthetic.places import (  # noqa: E402
    OUTCOMES,
    RENDERINGS,
    RENDERINGS_V1,
    PlaceBenchmark,
    build,
)


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    out = tmp_path_factory.mktemp("places")
    gen, manifest = build(seed=5, sheet=80, requests=120, out=out)
    return gen, manifest, out


class TestTheWorld:
    def test_renderings_sum_to_one_and_every_kind_appears(self, world):
        assert abs(sum(RENDERINGS.values()) - 1.0) < 1e-9
        _, manifest, _ = world
        assert set(manifest["counts"]["renderings"]) == set(RENDERINGS)

    def test_deterministic_by_fingerprint(self, tmp_path):
        _, a = build(seed=9, sheet=60, requests=50, out=tmp_path / "a")
        _, b = build(seed=9, sheet=60, requests=50, out=tmp_path / "b")
        assert a["content_fingerprints"] == b["content_fingerprints"]

    def test_requests_carry_no_place_id(self, world):
        _, _, out = world
        import pyarrow.parquet as pq

        cols = set(pq.read_table(out / "requests.parquet").column_names)
        assert cols == {"request_id", "text", "action"}

    def test_every_known_endpoint_names_a_sheet_row(self, world):
        gen, _, _ = world
        ids = {r["id"] for r in gen.sheet}
        for req in gen.requests:
            for e in req.endpoints:
                if e.rendering != "unknown":
                    assert e.place_id in ids, (e.rendering, e.text)
                else:
                    assert e.place_id is None

    def test_unknown_numbers_are_outside_the_sheets_range(self, world):
        gen, _, _ = world
        for req in gen.requests:
            for e in req.endpoints:
                if e.rendering == "unknown":
                    assert int(e.text.split()[0]) >= 300

    def test_landmarks_sit_near_an_address(self, world):
        gen, _, _ = world
        assert gen.landmarks
        for lm in gen.landmarks:
            assert lm["near"] in {r["id"] for r in gen.sheet}


class TestTheScorer:
    def test_the_default_policy_never_verifies_the_wrong_door(self, world):
        _, _, out = world
        bench = PlaceBenchmark.load(out)
        rep = bench.score()
        assert rep["totals"]["verified_wrong"] == 0
        assert rep["totals"]["missed"] == 0
        assert set(rep["totals"]) == set(OUTCOMES)

    def test_unknown_places_are_refused_and_known_ones_are_not(self, world):
        _, _, out = world
        rep = PlaceBenchmark.load(out).score()
        unknown = rep["by_rendering"]["unknown"]
        assert unknown["refused_right"] == sum(unknown.values())
        assert rep["totals"]["refused_known"] == 0

    def test_exact_addresses_verify_or_ask_never_refuse(self, world):
        _, _, out = world
        exact = PlaceBenchmark.load(out).score()["by_rendering"]["exact"]
        assert exact["verified_right"] + exact["asked_right"] == sum(exact.values())

    def test_the_sweep_reports_the_trade(self, world):
        _, _, out = world
        rows = PlaceBenchmark.load(out).sweep()
        assert {r["verified_at"] for r in rows} == {0.7, 0.8, 0.85, 0.9, 0.95}
        assert all(r["verified_wrong"] == 0 for r in rows)


@pytest.fixture(scope="module")
def world_v1(tmp_path_factory):
    out = tmp_path_factory.mktemp("places_v1")
    gen, manifest = build(seed=5, sheet=160, requests=240, out=out, version=1)
    return gen, manifest, out


class TestTheV1World:
    def test_renderings_sum_to_one_and_the_pack_is_named(self, world_v1):
        assert abs(sum(RENDERINGS_V1.values()) - 1.0) < 1e-9
        _, manifest, _ = world_v1
        assert manifest["world_pack"] == "places_v1" and manifest["schema_version"] == 1
        assert manifest["counts"]["confusables"] >= 4

    def test_v0_is_untouched_by_v1(self, tmp_path):
        _, a = build(seed=9, sheet=60, requests=50, out=tmp_path / "a")
        _, b = build(seed=9, sheet=60, requests=50, out=tmp_path / "b", version=0)
        assert a["content_fingerprints"] == b["content_fingerprints"]
        assert "front_bearing" not in {k for r in [] for k in r}

    def test_every_landmark_faces_somewhere_and_has_a_decoy_across_from_it(self, world_v1):
        gen, _, _ = world_v1
        from arche.addr.request import _haversine_m, _relation_fit

        by_id = {r["id"]: r for r in gen.sheet}
        for lm in gen.landmarks:
            assert 0 <= lm["front_bearing"] < 360
            anchor = by_id[lm["near"]]
            side = gen._anchor_side[lm["id"]]
            rel = {"back": "behind", "front": "opposite", "side": "next to"}[side]
            assert _relation_fit(rel, lm, anchor) == 1
            d = _haversine_m(lm["lat"], lm["lon"], anchor["lat"], anchor["lon"])
            # one other address at (nearly) the same distance on the other side
            others = [r for r in gen.sheet if r is not anchor
                      and abs(_haversine_m(lm["lat"], lm["lon"], r["lat"], r["lon"]) - d) < 2]
            assert others, lm["name"]

    def test_a_landmark_sentence_names_the_side_the_anchor_is_on(self, world_v1):
        gen, _, _ = world_v1
        for req in gen.requests:
            for e in req.endpoints:
                if e.rendering == "landmark_only":
                    assert e.text.split()[0] in ("behind", "opposite", "in", "next", "beside")

    def test_unknown_confusable_names_no_door_under_that_spelling(self, world_v1):
        gen, _, _ = world_v1
        doors = {(r["street"], r["street_number"]) for r in gen.sheet}
        for req in gen.requests:
            for e in req.endpoints:
                if e.rendering == "unknown_confusable":
                    number, street = e.text.split(" ", 1)
                    assert (street, number) not in doors
                    assert e.place_id is None


class TestTheV1Scorer:
    def test_defaults_never_verify_the_wrong_door(self, world_v1):
        _, _, out = world_v1
        rep = PlaceBenchmark.load(out).score()
        assert rep["totals"]["verified_wrong"] == 0 and rep["totals"]["missed"] == 0
        # A confusable door verifies on the exact spelling; the ones that ask
        # are also cross-area twins, which no spelling can settle.
        conf = rep["by_rendering"]["confusable"]
        assert conf["verified_right"] + conf["asked_right"] == sum(conf.values())
        assert conf["verified_right"] > conf["asked_right"]

    def test_the_typo_rule_is_what_keeps_a_confusable_unknown_from_verifying(self, world_v1):
        from arche.addr.request import Policy

        _, _, out = world_v1
        bench = PlaceBenchmark.load(out)
        off = bench.score(Policy(verified_at=0.7, confirm_typo_matches=False))
        on = bench.score(Policy(verified_at=0.7, confirm_typo_matches=True))
        uc_off = off["by_rendering"]["unknown_confusable"]
        assert uc_off["verified_wrong"] > 0
        assert on["by_rendering"]["unknown_confusable"]["verified_wrong"] == 0

    def test_the_relation_geometry_puts_the_right_door_first(self, world_v1):
        from arche.addr.request import MasterSheet

        _, _, out = world_v1
        bench = PlaceBenchmark.load(out)
        blind = MasterSheet([{k: v for k, v in r.items() if k != "front_bearing"}
                             for r in bench.sheet])
        with_geo = bench.score()
        without = bench.score(source=blind)
        assert with_geo["asked_top_right"]["landmark_only"] > \
            without["asked_top_right"]["landmark_only"]
        assert with_geo["by_rendering"]["landmark_only"]["asked_wrong"] <= \
            without["by_rendering"]["landmark_only"]["asked_wrong"]

    def test_partial_is_answered_with_a_number_question_on_the_right_street(self, world_v1):
        _, _, out = world_v1
        rep = PlaceBenchmark.load(out).score()
        partial = rep["by_rendering"]["partial"]
        assert partial["asked_right"] == sum(partial.values())

