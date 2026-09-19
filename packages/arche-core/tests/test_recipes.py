# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Shipped Splink recipes: a declared schema, a stable id, a run whose pin names the recipe."""
from __future__ import annotations

import pytest
from arche.resolve.recipes import PERSON, PERSON_COLUMNS, RECIPES, Recipe


class TestTheDeclaration:
    def test_person_is_registered_under_both_names(self):
        assert RECIPES["person"] is PERSON
        assert RECIPES[PERSON.name] is PERSON

    def test_the_schema_is_two_name_columns_not_one_blob(self):
        assert "given_name" in PERSON.columns and "surname" in PERSON.columns
        assert "name" not in PERSON.columns

    def test_the_digest_is_stable_and_declaration_only(self):
        assert PERSON.digest == Recipe(
            name=PERSON.name, entity=PERSON.entity, columns=PERSON.columns,
            settings=lambda: None, train=lambda ln, s: None,
            threshold=PERSON.threshold, review_margin=PERSON.review_margin,
            benchmark=PERSON.benchmark).digest
        assert PERSON.digest.startswith("sha256:")

    def test_the_digest_moves_with_the_threshold(self):
        other = Recipe(name=PERSON.name, entity=PERSON.entity, columns=PERSON.columns,
                       settings=PERSON.settings, train=PERSON.train,
                       threshold=0.5, review_margin=PERSON.review_margin,
                       benchmark=PERSON.benchmark)
        assert other.digest != PERSON.digest

    def test_a_recipe_carries_its_operating_point(self):
        assert 0 < PERSON.threshold <= 1
        assert PERSON.review_margin < PERSON.threshold
        assert "bench_splink_febrl" in PERSON.benchmark


class TestTheSchemaIsAContract:
    def test_records_with_the_columns_pass(self):
        rows = [{c: "x" for c in PERSON_COLUMNS}]
        PERSON.check(rows)

    def test_a_column_absent_from_every_record_is_refused_by_name(self):
        rows = [{c: "x" for c in PERSON_COLUMNS if c != "date_of_birth"}]
        with pytest.raises(ValueError, match="date_of_birth"):
            PERSON.check(rows, side="list_a")

    def test_a_column_present_on_some_records_is_enough(self):
        rows = [{c: "x" for c in PERSON_COLUMNS},
                {"given_name": "y"}]
        PERSON.check(rows)

    def test_a_name_blob_is_refused_because_it_is_not_the_schema(self):
        rows = [{"name": "Ada Lovelace", "address": "1 Street"}]
        with pytest.raises(ValueError, match="given_name"):
            PERSON.check(rows)

    def test_empty_input_is_not_an_error(self):
        PERSON.check([])


@pytest.mark.skipif(
    pytest.importorskip("importlib.util").find_spec("splink") is None,
    reason="needs arche-core[resolve]")
class TestThroughTheAdapter:
    @pytest.fixture(scope="class")
    def rows(self):
        base = [
            {"given_name": "ada", "surname": "lovelace", "date_of_birth": "18151210",
             "street_number": "1", "address_1": "st james square", "postcode": "2000",
             "state": "nsw"},
            {"given_name": "alan", "surname": "turing", "date_of_birth": "19120623",
             "street_number": "7", "address_1": "wilmslow road", "postcode": "3000",
             "state": "vic"},
            {"given_name": "grace", "surname": "hopper", "date_of_birth": "19061209",
             "street_number": "9", "address_1": "navy street", "postcode": "4000",
             "state": "qld"},
        ]
        # Enough distinct people that u-sampling and EM have something to see.
        import random

        rng = random.Random(7)
        fill = [{"given_name": f"p{i}", "surname": f"s{i % 40}",
                 "date_of_birth": f"19{50 + i % 40:02d}01{1 + i % 28:02d}",
                 "street_number": str(i % 90), "address_1": f"road {i % 30}",
                 "postcode": str(2000 + i % 500), "state": rng.choice(["nsw", "vic"])}
                for i in range(300)]
        a = [{"id": f"a{i}", **r} for i, r in enumerate(base + fill)]
        b = [{"id": f"b{i}", **r} for i, r in enumerate(base + fill)]
        b[0]["surname"] = "lovelase"          # one typo on a true pair
        return a, b

    def test_a_recipe_runs_and_the_pin_names_it(self, rows):
        from arche.resolve import reconcile

        a, b = rows
        res = reconcile(a, b, id_field="id", backend="splink", splink_settings=PERSON)
        assert res["pins"]["settings"] == f"recipe:{PERSON.name}@{PERSON.digest}"
        assert res["pins"]["training"] == "recipe"
        assert res["pins"]["threshold"] == PERSON.threshold
        matched = {(e["a_id"], e["b_id"]) for e in res["matches"] if e["decision"] == "match"}
        assert ("a0", "b0") in matched or ("a1", "b1") in matched

    def test_the_recipe_refuses_records_without_its_columns(self):
        from arche.resolve import reconcile

        a = [{"id": "1", "name": "Ada Lovelace"}]
        with pytest.raises(ValueError, match="given_name"):
            reconcile(a, a, id_field="id", backend="splink", splink_settings=PERSON)

    def test_a_caller_threshold_overrides_the_recipes(self, rows):
        from arche.resolve import reconcile

        a, b = rows
        res = reconcile(a, b, id_field="id", backend="splink", splink_settings=PERSON,
                        threshold=0.5)
        assert res["pins"]["threshold"] == 0.5


class TestTheOtherTwo:
    def test_place_reads_name_and_coordinates(self):
        from arche.resolve.recipes import PLACE

        assert PLACE.columns == ("name", "lat", "lon")
        assert PLACE.threshold == 0.9 and PLACE.auto is True

    def test_place_prepare_makes_coordinates_numeric(self):
        from arche.resolve.recipes import PLACE

        rows = PLACE.prepare([{"name": "x", "lat": "53.8", "lon": "-1.5"},
                              {"name": "y", "lat": None, "lon": "bad"}])
        assert rows[0]["lat"] == 53.8 and rows[0]["lon"] == -1.5
        assert rows[1]["lat"] is None and rows[1]["lon"] is None

    def test_product_requires_a_name_and_reads_derived_columns(self):
        from arche.resolve.recipes import PRODUCT

        assert PRODUCT.requires == ("name",)
        assert set(PRODUCT.columns) == {"code1", "codes", "brand", "specs"}
        assert PRODUCT.auto is False

    def test_product_prepare_withholds_the_title(self):
        from arche.resolve.recipes import PRODUCT

        (row,) = PRODUCT.prepare([{"id": "1", "name": "Sony Turntable - PSLX350H"}])
        assert row["code1"] == "pslx350h" and row["brand"] == "sony"
        assert "name" not in row and row["id"] == "1"

    def test_the_registry_answers_by_entity_and_by_name(self):
        from arche.resolve.recipes import PLACE, PRODUCT, RECIPES

        assert RECIPES["place"] is PLACE and RECIPES["product_electronics"] is PRODUCT
        assert RECIPES[PLACE.name] is PLACE
