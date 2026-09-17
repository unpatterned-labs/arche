# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""The artist world: real alias sets, labelled strata, no invented truth."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

pytest.importorskip("pyarrow")

_REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_REPO / "data" / "synthetic"))

from arche_synthetic import artists  # noqa: E402
from arche_synthetic.evaluate import Benchmark  # noqa: E402


@pytest.fixture(scope="module")
def sources(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path]:
    """A tiny truth and filler, written to disk in the pulls' own formats."""
    d = tmp_path_factory.mktemp("artists")
    truth = d / "aliases.jsonl"
    truth.write_text("\n".join(json.dumps(r) for r in [
        {"canonical": "Wizkid", "country": "Nigeria", "entity_id": "Q1",
         "variants": ["Ayodeji Ibrahim Balogun", "Wiz Kid", "StarBoy"]},
        {"canonical": "Tyla", "country": "South Africa", "entity_id": "Q2",
         "variants": ["Tyla Laura Seethal"]},
        {"canonical": "Burna Boy", "country": "Nigeria", "entity_id": "Q3",
         "variants": ["Damini Ogulu"]},
        # Only case differs: not an alias group, must be dropped.
        {"canonical": "Rema", "country": "Nigeria", "entity_id": "Q4",
         "variants": ["REMA"]},
    ]) + "\n", encoding="utf-8")
    filler = d / "pairs.jsonl"
    rows = [{"country": "NG", "given": f"Given{i}", "family": f"Family{i}"}
            for i in range(40)]
    # A filler person who shares a name with an alias artist: a real collision.
    rows.append({"country": "ZA", "given": "Tyla", "family": ""})
    filler.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    return truth, filler


class TestJaroWinkler:
    @pytest.mark.parametrize("a,b,expect", [
        ("Wizkid", "Wizkid", 1.0),
        ("Wiz Kid", "Wizkid", ">=0.88"),
        ("Wizkid", "Ayodeji Ibrahim Balogun", "<0.88"),
        ("", "x", 0.0),
    ])
    def test_boundary_matches_splinks_second_level(self, a, b, expect):
        got = artists.jaro_winkler(a, b)
        if isinstance(expect, float):
            assert got == expect
        elif expect.startswith(">="):
            assert got >= float(expect[2:])
        else:
            assert got < float(expect[1:])

    def test_symmetric_and_case_insensitive(self):
        assert artists.jaro_winkler("Burna Boy", "burna boy") == 1.0
        assert artists.jaro_winkler("Tamy Moyo", "Thamsanqa Moyo") == pytest.approx(
            artists.jaro_winkler("Thamsanqa Moyo", "Tamy Moyo"))


class TestLoading:
    def test_case_only_variants_are_not_alias_groups(self, sources):
        truth, _ = sources
        groups = artists.load_truth(truth)
        assert {g["canonical"] for g in groups} == {"Wizkid", "Tyla", "Burna Boy"}

    def test_country_labels_become_iso(self, sources):
        truth, _ = sources
        by = {g["canonical"]: g for g in artists.load_truth(truth)}
        assert by["Wizkid"]["country"] == "NG"
        assert by["Tyla"]["country"] == "ZA"


class TestWorld:
    @pytest.fixture(scope="class")
    def built(self, sources, tmp_path_factory):
        truth, filler = sources
        out = tmp_path_factory.mktemp("world")
        world, manifest = artists.build(seed=3, records=120, out=out,
                                        truth_path=truth, filler_path=filler)
        return world, manifest, out

    def test_every_alias_group_is_an_entity_and_filler_tops_up(self, built):
        world, manifest, _ = built
        kinds = [s[0].attributes["kind"] for s in world.states.values()]
        assert kinds.count("alias") == 3
        assert kinds.count("filler") > 0
        assert manifest["counts"]["entities"] == {"artist": len(world.states)}

    def test_deterministic_by_fingerprint(self, sources, tmp_path):
        truth, filler = sources
        _, a = artists.build(seed=11, records=120, out=tmp_path / "a",
                             truth_path=truth, filler_path=filler)
        _, b = artists.build(seed=11, records=120, out=tmp_path / "b",
                             truth_path=truth, filler_path=filler)
        assert a["content_fingerprints"] == b["content_fingerprints"]

    def test_observations_carry_no_truth(self, built):
        _, _, out = built
        import pyarrow.parquet as pq
        cols = set(pq.read_table(out / "observations.parquet").column_names)
        assert cols == set(artists.COLUMNS)

    def test_strata_are_labelled_by_intended_names_not_corrupted_ones(self, built):
        world, _, _ = built
        by = {o.record_id: o for o in world.observations}
        alias = [d for d in world.differences if d.cause == "alias"]
        spelling = [d for d in world.differences if d.cause == "spelling"]
        assert alias, "a world with Wizkid/Balogun must produce alias pairs"
        for d in alias:
            ia = world.states[d.entity_id][0].attributes["names"]
            # Both records belong to a multi-name artist.
            assert len(ia) >= 2
        for d in spelling:
            a, b = by[d.observation_a], by[d.observation_b]
            assert a.entity_id == b.entity_id

    def test_error_rows_name_the_rule(self, built):
        world, _, _ = built
        from arche_synthetic.observe import CORRUPTION
        errors = {d.cause for d in world.differences if d.difference_kind == "error"}
        assert errors and errors <= set(CORRUPTION)

    def test_collisions_are_found_not_made(self, built):
        world, manifest, out = built
        import pyarrow.parquet as pq
        rows = pq.read_table(out / "collisions.parquet").to_pylist()
        assert manifest["collisions"] == len(rows) >= 1
        assert any(r["shared_name"] == "tyla" for r in rows)
        for r in rows:
            assert r["entity_a"] != r["entity_b"]

    def test_loads_as_a_benchmark(self, built):
        _, _, out = built
        bench = Benchmark.load(out)
        assert bench.true_pairs
        assert "representation/alias" in bench.by_cause
