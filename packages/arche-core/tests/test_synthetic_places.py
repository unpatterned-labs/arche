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

from arche_synthetic.places import OUTCOMES, RENDERINGS, PlaceBenchmark, build  # noqa: E402


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
