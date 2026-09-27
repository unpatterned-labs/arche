# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""One way to open a world, whichever family it is.

Three world families ship with three different shapes, and before `load()`
each had its own loader. Asking the wrong one for the wrong world produced
`FileNotFoundError: places_v0/observations.parquet`, which says nothing about
what to call instead. Worse, the one column this whole project exists for,
*why* two records disagree, was unreachable through the public API:
`Benchmark.load` folds all 32,596 labelled rows into two sets of pairs and
drops `attribute`, `entity_id` and `event_id`.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

pytest.importorskip("pyarrow")
_REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_REPO / "data" / "synthetic"))

from arche_synthetic import available, load, worlds_dir  # noqa: E402
from arche_synthetic.places import build as build_places  # noqa: E402

_WORLDS = _REPO / "data" / "synthetic" / "worlds"
_SHIPPED = pytest.mark.skipif(not (_WORLDS / "ng_supplier_v0").is_dir(),
                              reason="the shipped worlds are not in this checkout")


def test_the_package_is_imported_from_the_tree_not_a_copy():
    """`import arche_synthetic` must mean the source.

    It resolved to a non-editable copy in the virtualenv that nothing tracked:
    absent from the lock, so a clean `uv sync` deleted it, and frozen at
    whatever the last install copied, so editing the generator did not change
    what a notebook reading its output imported.
    """
    import arche_synthetic

    where = Path(arche_synthetic.__file__).resolve().parent
    assert where == (_REPO / "data" / "synthetic" / "arche_synthetic").resolve(), (
        f"arche_synthetic imported from {where}, not from the tree. Run "
        "`uv sync --group dev`; it is an editable dependency of the workspace.")


@_SHIPPED
class TestTheShippedWorlds:

    def test_one_call_opens_every_family(self):
        kinds = {name: load(_WORLDS / name).kind
                 for name in ("ng_supplier_v0", "artists_v0", "places_v0", "places_v1")}
        assert kinds == {"ng_supplier_v0": "records", "artists_v0": "records",
                         "places_v0": "places", "places_v1": "places"}

    def test_the_labelled_disagreements_are_readable_whole(self):
        w = load(_WORLDS / "ng_supplier_v0")
        assert len(w.differences) == len(w.tables["differences"]) > 30_000
        row = w.differences[0]
        # the columns Benchmark drops, which are the point of the dataset
        assert {"attribute", "difference_kind", "cause", "entity_id"} <= set(row)
        by_kind = w.difference_counts()
        assert set(by_kind) == {"change", "representation", "error"}
        assert sum(by_kind.values()) == len(w.differences)
        assert "ORG_RELOCATED" in w.difference_counts("cause")

    def test_one_entity_through_a_change(self):
        w = load(_WORLDS / "ng_supplier_v0")
        moved = next(r for r in w.differences if r["cause"] == "ORG_RELOCATED")
        records = w.records_of(moved["entity_id"])
        assert len(records) > 1
        observed = [r["observed_at"] for r in records]
        assert observed == sorted(observed)
        reasons = w.why(moved["observation_a"], moved["observation_b"])
        assert "change" in {r["difference_kind"] for r in reasons}
        assert "address" in {r["attribute"] for r in reasons}

    def test_it_says_what_a_matcher_may_see(self):
        assert load(_WORLDS / "ng_supplier_v0").given_to_a_matcher == "observations"
        assert load(_WORLDS / "places_v1").given_to_a_matcher == "requests"

    def test_describe_names_the_pack_the_seed_and_the_strata(self, capsys):
        assert load(_WORLDS / "ng_supplier_v0").describe() is None   # prints, does not return
        text = capsys.readouterr().out
        assert "ng_supplier_v0" in text and "seed 42" in text
        assert "everything else is truth" in text
        assert "change" in text

    def test_it_hands_back_the_scoring_api_for_its_family(self):
        assert type(load(_WORLDS / "ng_supplier_v0").benchmark()).__name__ == "Benchmark"
        assert type(load(_WORLDS / "places_v1").benchmark()).__name__ == "PlaceBenchmark"

    def test_an_unknown_table_says_which_ones_exist(self):
        w = load(_WORLDS / "artists_v0")
        with pytest.raises(AttributeError, match="has no table 'events'"):
            _ = w.events                                  # artists have no lifecycle
        assert "collisions" in w.tables                   # but they do have these

    def test_frame_is_the_same_rows_as_the_list(self):
        pytest.importorskip("pandas")
        w = load(_WORLDS / "artists_v0")
        assert w.frame("observations").shape[0] == len(w.observations)
        with pytest.raises(KeyError, match="has no table 'nope'"):
            w.frame("nope")


def test_a_freshly_generated_world_reads_the_same_way(tmp_path):
    build_places(seed=7, sheet=40, requests=60, out=tmp_path / "w", version=1)
    w = load(tmp_path / "w")
    assert w.kind == "places" and w.seed == 7
    assert len(w.requests) == 60 and w.given_to_a_matcher == "requests"
    # TypeError on purpose: an AttributeError from a property is swallowed by
    # `__getattr__`, which would then hand back the raw truth table instead.
    with pytest.raises(TypeError, match=r"per \(request_id, role\)"):
        _ = w.truth


def test_a_directory_that_is_not_a_world_says_how_to_make_one(tmp_path):
    with pytest.raises(FileNotFoundError, match="no manifest.yaml"):
        load(tmp_path)


# ── naming a world instead of pathing it ─────────────────────────────────────
# `load("artists_v0")` has to work from any directory, or the published
# documentation cannot show it: `test_docs_examples` runs every Python block
# from a temporary directory, and a repo-relative path fails there.


@_SHIPPED
class TestNamingAWorld:
    def test_a_bare_name_finds_a_shipped_world(self, monkeypatch, tmp_path):
        monkeypatch.chdir(tmp_path)                      # nowhere near the repo
        assert load("artists_v0").pack == "artists_v0"

    def test_available_lists_what_can_be_named(self):
        names = available()
        assert "artists_v0" in names and "ng_supplier_v0" in names
        assert all((worlds_dir() / n / "manifest.yaml").is_file() for n in names)

    def test_a_local_path_wins_over_a_shipped_name_of_the_same_name(self, tmp_path):
        """A world you generated is the one you meant, not the one we ship."""
        mine = tmp_path / "artists_v0"
        build_places(seed=3, sheet=20, requests=20, out=mine, version=1)
        w = load(mine)
        assert w.kind == "places", "the shipped artists world shadowed a local one"

    def test_an_unknown_name_lists_the_known_ones(self, monkeypatch, tmp_path):
        monkeypatch.chdir(tmp_path)
        with pytest.raises(FileNotFoundError, match="Shipped worlds:.*artists_v0"):
            load("ng_supplier_v9")
