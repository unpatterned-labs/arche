# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""`crosswalk(backend="splink")`: contract, not accuracy.

Accuracy lives in `datasets/names_dataops/`, where it can be measured against
labels. What is guarded here is that the backend keeps arche's contract, because
that is the whole reason it is a backend rather than a separate tool:

* the same result shape, so `review_pack`, `crosswalk_report` and the studio
  keep working
* pins that name the model, the corpus and WHO configured the scorer, since a
  trained scorer is a function of the data it saw and of the settings it was
  given
* no silent fallback, and no silently invented configuration
* the gate off unless asked for

The backend is an adapter: the caller brings a Splink `SettingsCreator`. The
derivation that used to run by default is still reachable as
`splink_settings="derive"`, warns, and is best-effort. It measured below arche's
own engine on Febrl 4, which is why it is opt-in and why the warning exists.
"""

from __future__ import annotations

import pytest

splink = pytest.importorskip("splink", reason="needs arche-core[resolve]")

import splink.comparison_library as cl  # noqa: E402
from arche.resolve import crosswalk  # noqa: E402
from arche.resolve._splink_backend import (  # noqa: E402
    SplinkBackendError,
    _column_types,
    _date_format,
    _model_blocking_sql,
    _worst_block,
)
from splink import SettingsCreator, block_on  # noqa: E402

_A = [{"id": f"a{i}", "name": n, "birth_date": d}
      for i, (n, d) in enumerate(
          [("Amara Patel", "2016-06-28"), ("Malik Okonkwo", "2017-08-18"),
           ("Ngozi Adeyemi", "1990-03-02")] * 6)]
_B = [{**r, "id": r["id"].replace("a", "b")} for r in _A]

_GEO = [{"id": f"g{i}", "name": n, "lat": lat, "lon": lon}
        for i, (n, lat, lon) in enumerate(
            [("COMMUNITY PRIMARY SCHOOL", 6.4531, 3.3958),
             ("COMMUNITY PRY SCHOOL", 6.4540, 3.3967),
             ("LGEA PRIMARY SCHOOL", 9.0765, 7.3986),
             ("LGEA PRY SCHOOL", 9.0774, 7.3995)] * 4)]


def settings() -> SettingsCreator:
    """A fresh settings object per use; Splink mutates the one it is handed."""
    return SettingsCreator(
        link_type="link_only",
        comparisons=[
            cl.NameComparison("name").configure(term_frequency_adjustments=True),
            cl.DateOfBirthComparison("birth_date", input_is_string=True,
                                     datetime_format="%Y-%m-%d"),
        ],
        blocking_rules_to_generate_predictions=[
            block_on("name"), block_on("birth_date"),
        ],
        retain_intermediate_calculation_columns=False,
    )


@pytest.fixture(scope="module")
def result():
    return crosswalk(_A, _B, entity="person", id_field="id", backend="splink",
                     splink_settings=settings(), threshold=0.99)


class TestTheResultShape:
    """`review_pack` and friends read this shape. It must not drift."""

    def test_top_level_keys(self, result):
        assert {"matches", "count", "pins"} <= set(result)

    def test_edges_carry_what_the_review_path_needs(self, result):
        assert result["matches"], "no edges produced"
        for key in ("a_id", "b_id", "score", "decision",
                    "evidence", "distinctive_max", "decision_id"):
            assert key in result["matches"][0], key

    def test_decisions_use_arche_vocabulary(self, result):
        assert {e["decision"] for e in result["matches"]} <= {"match", "review"}

    def test_a_pack_can_be_written_from_it(self, result, tmp_path):
        """The point of matching the shape."""
        from arche.report import review_pack
        manifest = review_pack(result, _A, _B, out_dir=tmp_path / "p",
                               entity="person", reveal=True)
        assert manifest["rows"] == len(result["matches"])
        assert manifest["pins"]["backend"] == "splink"


class TestThePins:

    def test_names_the_model_and_the_corpus(self, result):
        """A trained scorer is a function of the data it saw.

        arche pins a comparator set because that is what decides an arche score.
        Here the model decides it, so the model is what gets named.
        """
        pins = result["pins"]
        assert pins["backend"] == "splink"
        assert len(pins["model_sha256"]) == 64
        assert len(pins["corpus_sha256"]) == 64
        assert pins["splink_version"] and pins["duckdb_version"]

    def test_says_who_configured_the_scorer(self, result):
        """A derived run and a hand-written run are not the same decision."""
        assert result["pins"]["settings"] == "caller"
        assert result["pins"]["training"] == "default"

    def test_names_the_prior_that_sets_the_probability_scale(self, result):
        """`probability_two_random_records_match` moves every score at once.

        Two runs with different values of it are not on the same scale and
        their thresholds do not mean the same thing, so a reader has to be able
        to see it.
        """
        assert isinstance(result["pins"]["lambda"], float)

    def test_does_not_pin_a_frequency_table_it_never_used(self, result):
        """Splink applies term frequency inside its own comparisons.

        The facade builds a self-calibrated table for the default engine. If
        that provenance leaked into these pins it would name an input this
        decision never saw, which is the exact fault the tf pins were fixed for.
        """
        assert "tf" not in result["pins"]

    def test_a_different_corpus_pins_differently(self, result):
        bigger = _A + [{"id": "a99", "name": "Chidi Bakare",
                        "birth_date": "1988-01-09"}]
        other = crosswalk(bigger, _B, entity="person", id_field="id",
                          backend="splink", splink_settings=settings(),
                          threshold=0.99)
        assert (other["pins"]["corpus_sha256"]
                != result["pins"]["corpus_sha256"])

    def test_the_blocking_pin_is_stable_across_runs(self, result):
        """It used to be built from `str()` on the rule objects.

        That yields `<...BlockingRule object at 0x7f...>`, so the pin changed
        on every run and identified nothing at all. It comes out of the saved
        model's SQL now.
        """
        again = crosswalk(_A, _B, entity="person", id_field="id",
                          backend="splink", splink_settings=settings(),
                          threshold=0.99)
        assert again["pins"]["blocking_sha256"] == result["pins"]["blocking_sha256"]

    def test_blocking_sql_is_read_out_of_the_model(self):
        model = {"blocking_rules_to_generate_predictions": [
            {"blocking_rule": 'l."name" = r."name"'}, 'l."x" = r."x"']}
        assert _model_blocking_sql(model) == ['l."name" = r."name"',
                                              'l."x" = r."x"']


class TestFailureContract:

    def test_an_unknown_backend_is_refused(self):
        with pytest.raises(ValueError, match="unknown backend"):
            crosswalk(_A, _B, entity="person", id_field="id", backend="nope")

    def test_settings_are_required(self):
        """arche will not invent a Splink configuration behind the caller.

        The derivation that used to run here was measured worse than arche's
        own engine, so defaulting to it would have quietly downgraded anyone
        who asked for the better matcher.
        """
        with pytest.raises(SplinkBackendError, match="needs a Splink config"):
            crosswalk(_A, _B, entity="person", id_field="id", backend="splink")

    def test_the_error_names_both_routes(self):
        with pytest.raises(SplinkBackendError) as caught:
            crosswalk(_A, _B, entity="person", id_field="id", backend="splink")
        assert "SettingsCreator" in str(caught.value)
        assert '"derive"' in str(caught.value)

    def test_a_threshold_is_required(self):
        """A Splink probability has no portable scale.

        The 0.99 that used to be the default here is Splink's own Febrl cut,
        and on the Nigerian school register the same hand-written recipe that
        merges 190 true pairs at 0.9 merges NOTHING at 0.99. One shipped number
        cannot serve both, so the caller picks it.
        """
        with pytest.raises(SplinkBackendError, match="needs threshold="):
            crosswalk(_A, _B, entity="person", id_field="id",
                      backend="splink", splink_settings=settings())

    def test_the_threshold_error_says_why(self):
        with pytest.raises(SplinkBackendError) as caught:
            crosswalk(_A, _B, entity="person", id_field="id",
                      backend="splink", splink_settings=settings())
        assert "probability_two_random_records_match" in str(caught.value)

    def test_a_settings_string_it_does_not_understand_is_refused(self):
        with pytest.raises(SplinkBackendError, match="not understood"):
            crosswalk(_A, _B, entity="person", id_field="id",
                      backend="splink", splink_settings="auto",
                      threshold=0.99)

    def test_deriving_without_a_pack_is_refused(self):
        with pytest.raises(SplinkBackendError, match="nothing to derive"):
            crosswalk(_A, _B, id_field="id", backend="splink",
                      comparators=[], splink_settings="derive",
                      threshold=0.99)

    def test_a_pack_with_nothing_mappable_raises(self):
        """Rather than silently returning something from another algorithm."""
        with pytest.raises(SplinkBackendError, match="no comparator"):
            crosswalk(_A, _B, id_field="id", backend="splink",
                      splink_settings="derive", threshold=0.99,
                      comparators=[{"field": "name", "kind": "tftoken",
                                    "weight": 2.0}])


class TestTheDerivationIsOptIn:

    def test_it_warns(self):
        with pytest.warns(UserWarning, match="best-effort"):
            crosswalk(_A, _B, entity="person", id_field="id",
                      backend="splink", splink_settings="derive",
                      threshold=0.99)

    def test_it_says_so_in_the_pins(self):
        with pytest.warns(UserWarning):
            res = crosswalk(_A, _B, entity="person", id_field="id",
                            backend="splink", splink_settings="derive",
                            threshold=0.99)
        assert res["pins"]["settings"] == "derived"

    def test_a_name_only_product_pack_requires_caller_owned_settings(self):
        """A derived model needs independent evidence for EM training."""
        a = [
            {"id": "a1", "name": "Safavieh Heritage Rug 3 x 5 Beige"},
            {"id": "a2", "name": "Safavieh Heritage Rug 5 x 8 Green"},
            {"id": "a3", "name": "Safavieh Madison Rug 4 x 6 Blue"},
            {"id": "a4", "name": "Safavieh Madison Rug 6 x 9 Grey"},
        ] * 4
        b = [
            {"id": f"b{i}", "name": record["name"].replace("Rug", "Area Rug")}
            for i, record in enumerate(a)
        ]
        a = [{**record, "id": f"a{i}"} for i, record in enumerate(a)]

        with pytest.raises(SplinkBackendError, match="one mappable comparison"):
            crosswalk(
                a, b, entity="product_home_goods", id_field="id",
                backend="splink", splink_settings="derive",
                threshold=0.5, review_margin=0.5,
            )


class TestColumnTypes:
    """Both directions of pandas inference have already broken a run."""

    def test_coordinates_stay_numeric(self):
        """`radians(VARCHAR)` is how the place pack failed the first time."""
        types = _column_types(_GEO, _GEO, ["name", "lat", "lon"])
        assert types == {"name": "text", "lat": "number", "lon": "number"}

    def test_a_numeric_looking_string_stays_text(self):
        """A postcode is not a number and must keep its leading zero."""
        rows = [{"postcode": "01234"}, {"postcode": "05678"}]
        assert _column_types(rows, rows, ["postcode"]) == {"postcode": "text"}

    def test_a_sparse_text_column_stays_text(self):
        """Left to inference this becomes float64 and DuckDB refuses it."""
        rows = [{"note": ""}] * 40 + [{"note": "seen once"}]
        assert _column_types(rows, rows, ["note"]) == {"note": "text"}

    def test_an_all_empty_column_stays_text(self):
        rows = [{"note": None}, {"note": ""}]
        assert _column_types(rows, rows, ["note"]) == {"note": "text"}

    def test_a_geo_run_completes(self):
        """The end-to-end version of the same guard."""
        res = crosswalk(_GEO, _GEO, id_field="id", backend="splink",
                        threshold=0.5, splink_settings=SettingsCreator(
                            link_type="link_only",
                            comparisons=[
                                cl.NameComparison("name"),
                                cl.DistanceInKMAtThresholds("lat", "lon",
                                                            [0.5, 2, 10]),
                            ],
                            blocking_rules_to_generate_predictions=[
                                block_on("round(lat, 1)", "round(lon, 1)"),
                            ],
                            retain_intermediate_calculation_columns=False,
                        ))
        assert res["count"] > 0
        assert any("lat_lon_level" in e["evidence"] for e in res["matches"])


class TestBlockingCost:
    """Nothing goes in unbounded, conjunctions and SQL expressions included."""

    def test_the_commonest_value_decides(self):
        from arche.resolve._splink_backend import _exact_key
        rows = [{"k": "x"}] * 5 + [{"k": "y"}]
        assert _worst_block(rows, rows, _exact_key("k")) == 25

    def test_a_conjunction_is_costed_on_the_tuple(self):
        from arche.resolve._splink_backend import _exact_key
        rows = [{"k": "x", "j": str(i)} for i in range(5)]
        assert _worst_block(rows, rows, _exact_key("k", "j")) == 1

    def test_an_empty_value_never_forms_a_block(self):
        from arche.resolve._splink_backend import _exact_key
        rows = [{"k": ""}] * 100
        assert _worst_block(rows, rows, _exact_key("k")) == 0


class TestTheGate:

    def test_is_off_by_default(self, result):
        """Two rules over the same evidence can be worse than either alone.

        Turning it on is a decision made with a measurement in hand, not a
        default somebody inherits. See the module docstring.
        """
        assert result["pins"]["gate"] is False
        assert "distinctive_floor" not in result["pins"]

    def test_can_be_asked_for(self):
        gated = crosswalk(_A, _B, entity="person", id_field="id",
                          backend="splink", splink_settings=settings(),
                          threshold=0.99, gate=True)
        assert gated["pins"]["gate"] is True
        assert "distinctive_floor" in gated["pins"]

    def test_refuses_when_it_cannot_tell_which_column_is_a_name(self):
        """It recomputes arche's distinctiveness, so it needs the name field."""
        with pytest.raises(SplinkBackendError, match="which column holds a name"):
            crosswalk(_A, _B, id_field="id", backend="splink",
                      splink_settings=settings(), threshold=0.99, gate=True)


class TestDateFormatInference:
    """Splink parses dates with one declared format; arche accepts several.

    Only the derivation needs this: a caller writing their own settings
    declares the format themselves. Getting it wrong is not a small error.
    With an unparseable format the date comparison trains nothing and
    contributes nothing, which cost the derived path 40 points of recall on
    Febrl 4 before it was caught.
    """

    @pytest.mark.parametrize("sample,expected", [
        ("19151111", "%Y%m%d"),
        ("2016-06-28", "%Y-%m-%d"),
        ("28/06/2016", "%d/%m/%Y"),
    ])
    def test_infers_from_the_data(self, sample, expected):
        assert _date_format([sample]) == expected

    def test_falls_back_to_iso(self):
        assert _date_format([]) == "%Y-%m-%d"
