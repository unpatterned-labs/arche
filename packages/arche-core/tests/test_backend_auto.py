# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""`backend="auto"`: the engine below the floor, a shipped recipe above it, and the result says why.

The choice lives on the result, never in the pins: which scorer ran is already
pinned and hashed into every decision id, and *why it was chosen* names the
batch size, which must not move an id.
"""
from __future__ import annotations

import random

import pytest
from arche.resolve import AUTO_SPLINK_FLOOR, reconcile
from arche.resolve.recipes import PERSON, PERSON_COLUMNS


def _split_names(n: int, prefix: str) -> list[dict]:
    rng = random.Random(11)
    return [{"id": f"{prefix}{i}", "given_name": f"p{i}", "surname": f"s{i % 40}",
             "date_of_birth": f"19{50 + i % 40:02d}01{1 + i % 28:02d}",
             "street_number": str(i % 90), "address_1": f"road {i % 30}",
             "postcode": str(2000 + i % 500), "state": rng.choice(["nsw", "vic"])}
            for i in range(n)]


def _blobs(n: int, prefix: str) -> list[dict]:
    return [{"id": f"{prefix}{i}", "name": f"p{i} s{i % 40}"} for i in range(n)]


class TestTheChoiceIsNotInTheId:
    def test_the_same_decision_has_the_same_id_however_the_engine_was_chosen(self):
        rows = _split_names(40, "a")
        auto = reconcile(rows, rows, entity="person")
        explicit = reconcile(rows, rows, entity="person", backend="arche")
        assert auto["pins"] == explicit["pins"]
        assert [m["decision_id"] for m in auto["matches"]] ==                [m["decision_id"] for m in explicit["matches"]]


class TestTheFloor:
    def test_the_floor_is_the_measured_one(self):
        # bench_size_floor.py: level at 444 and 1,215, engine collapses by 3,081.
        assert AUTO_SPLINK_FLOOR == 1_000

    def test_below_the_floor_is_the_engine_and_says_so(self):
        rows = _split_names(40, "a")
        res = reconcile(rows, rows, entity="person")
        auto = res["backend"]
        assert auto["chosen"] == "arche"
        assert "below the floor" in auto["reason"]
        assert auto["records"] == 40 and auto["floor"] == AUTO_SPLINK_FLOOR
        assert res["pins"]["engine"] == "crosswalk.v1"

    def test_dedupe_counts_the_list_once(self):
        rows = _split_names(30, "a")
        res = reconcile(rows, rows, entity="person")
        assert res["backend"]["records"] == 30

    def test_link_counts_both_lists(self):
        a, b = _blobs(30, "a"), _blobs(20, "b")
        res = reconcile(a, b, entity="person")
        assert res["backend"]["records"] == 50


class TestWhyNotSplink:
    def test_an_entity_without_a_recipe_stays_on_the_engine_at_any_size(self):
        rows = _blobs(AUTO_SPLINK_FLOOR + 5, "a")
        res = reconcile(rows, rows, entity="organisation")
        assert res["backend"]["chosen"] == "arche"
        assert "no shipped Splink recipe" in res["backend"]["reason"]

    def test_a_name_blob_stays_on_the_engine_because_the_recipe_reads_two_columns(self):
        pytest.importorskip("splink")
        rows = _blobs(AUTO_SPLINK_FLOOR + 5, "a")
        res = reconcile(rows, rows, entity="person")
        auto = res["backend"]
        assert auto["chosen"] == "arche"
        assert "given_name" in auto["reason"]

    def test_external_candidates_keep_the_engine(self):
        rows = _split_names(AUTO_SPLINK_FLOOR + 5, "a")
        res = reconcile(rows, rows, entity="person",
                        candidate_pairs=[{"a_id": "a0", "b_id": "a1"}],
                        candidate_pins={"retriever": "test", "index": "none",
                                        "filters": {}, "top_k": 1})
        assert res["backend"]["chosen"] == "arche"
        assert "candidates" in res["backend"]["reason"]

    def test_explicit_arche_never_consults_auto(self):
        rows = _split_names(AUTO_SPLINK_FLOOR + 5, "a")
        res = reconcile(rows, rows, entity="person", backend="arche")
        assert "backend" not in res

    def test_an_unknown_backend_names_the_three(self):
        with pytest.raises(ValueError, match="'auto' \\(default\\), 'arche', 'splink'"):
            reconcile(_blobs(3, "a"), _blobs(3, "b"), entity="person", backend="zingg")


class TestSplinkWhenItFits:
    pytestmark = pytest.mark.skipif(
        pytest.importorskip("importlib.util").find_spec("splink") is None,
        reason="needs arche-core[resolve]")

    def test_above_the_floor_with_the_recipes_columns_is_splink_and_the_pin_names_it(self):
        a = _split_names(AUTO_SPLINK_FLOOR // 2 + 10, "a")
        b = [dict(r, id="b" + r["id"][1:]) for r in a]
        res = reconcile(a, b, entity="person")
        auto = res["backend"]
        assert auto["chosen"] == "splink"
        assert auto["recipe"] == PERSON.name
        assert res["pins"]["settings"] == f"recipe:{PERSON.name}@{PERSON.digest}"
        assert res["pins"]["threshold"] == PERSON.threshold
        assert res["pins"]["backend"] == "splink"

    def test_auto_never_derives(self):
        a = _split_names(AUTO_SPLINK_FLOOR // 2 + 10, "a")
        b = [dict(r, id="b" + r["id"][1:]) for r in a]
        res = reconcile(a, b, entity="person")
        assert res["pins"]["settings"] != "derived"

    def test_the_recipes_columns_are_the_contract(self):
        assert set(PERSON_COLUMNS) <= set(_split_names(1, "a")[0])
