# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Tests for the date comparator and its place in the `person` pack.

Before this, `compare_dates` compared digit strings, so `6/28/2016` scored 0.0
against `2016-06-28`: the same day, written the way two different systems write
it. That is the failure mode that matters, because two sources agreeing on a
date format is the exception.

The pack gap it closes was measured on the Parrish linkage set (294 true pairs,
8 true non-matches). The shipped `person` pack declared name, tftoken,
`national_id`, `phone`, `email` and `address`, and those files carry none of the
last four, so the pack was a name-only matcher that never looked at the birth
date it was handed. It produced 14 false merges, every one of them two different
children with the same name and different birthdays.
"""

from __future__ import annotations

import pytest
from arche.resolve import ENTITY_PACKS, crosswalk
from arche.resolve._matcher import compare_dates, parse_date_value

_NAME = "Zephyrine Quillfeather"


class TestFormatIsNotDisagreement:
    """The reason the comparator was rewritten."""

    @pytest.mark.parametrize("a,b", [
        ("6/28/2016", "2016-06-28"),     # US against ISO
        ("28/6/2016", "2016-06-28"),     # day-first against ISO
        ("2016-28-06", "2016-06-28"),    # day and month transposed
        ("20160628", "2016-06-28"),      # packed against ISO
        ("2016/06/28", "28.06.2016"),    # separators differ too
    ])
    def test_same_day_written_differently_agrees(self, a, b):
        assert compare_dates(a, b) == 1.0

    def test_the_old_behaviour_would_have_refuted_these(self):
        """Pinned so the regression is visible if anyone reverts the parser.

        Digit-string equality is what the comparator used to do. Every pair
        above survives it only by accident of formatting.
        """
        digits = lambda s: "".join(c for c in s if c.isdigit())  # noqa: E731
        assert digits("6/28/2016") != digits("2016-06-28")


class TestAmbiguityWithholdsRefutation:
    """`6/7/2016` does not say whether it means June or July."""

    def test_both_readings_are_kept(self):
        assert parse_date_value("6/7/2016") == (3, {(2016, 6, 7), (2016, 7, 6)})

    def test_two_ambiguous_dates_that_could_agree_do_agree(self):
        assert compare_dates("6/7/2016", "7/6/2016") == 1.0

    def test_a_day_above_twelve_resolves_it(self):
        assert parse_date_value("6/28/2016") == (3, {(2016, 6, 28)})

    def test_no_four_digit_year_is_unreadable(self):
        """`03/04/05` has six meanings. Declining beats guessing one."""
        assert parse_date_value("03/04/05") is None


class TestPrecision:
    """The same kind serves a birth date and a publication year."""

    def test_a_bare_year_reads_as_a_year(self):
        assert parse_date_value("1994") == (1, {(1994,)})

    def test_years_compare_as_years(self):
        assert compare_dates("1994", "1994") == 1.0
        assert compare_dates("1994", "1987") == 0.0

    def test_a_year_against_a_full_date_compares_at_year_precision(self):
        """A difference in what was recorded is not a disagreement."""
        assert compare_dates("1994", "1994-03-02") == 1.0
        assert compare_dates("1994", "1987-03-02") == 0.0

    def test_year_and_month(self):
        assert compare_dates("2016-06", "2016-06-28") == 1.0
        assert compare_dates("2016-07", "2016-06-28") == 0.0

    def test_coarse_precision_gets_no_near_miss_credit(self):
        """"One out" means nothing when you only have the year."""
        assert compare_dates("1994", "1995") == 0.0


class TestOneKeyingSlip:
    """Date errors are not random, so they should not score as random."""

    @pytest.mark.parametrize("a,b,why", [
        ("2017-01-01", "2016-12-31", "one day apart, across a year boundary"),
        ("2018-11-18", "2018-10-18", "month off by one"),
        ("2018-04-10", "2016-04-10", "year off by two"),
        ("2017-06-13", "2017-11-13", "month differs"),
    ])
    def test_near_misses_are_graded_not_zeroed(self, a, b, why):
        assert compare_dates(a, b) == pytest.approx(0.35), why

    def test_a_near_miss_scores_below_agreement(self):
        assert compare_dates("2017-01-01", "2016-12-31") < compare_dates(
            "2017-01-01", "2017-01-01")

    @pytest.mark.parametrize("a,b", [
        ("2016-06-28", "2019-01-02"),
        ("2017-08-30", "2018-08-16"),    # a real Parrish false merge
        ("2016-02-23", "2020-09-16"),    # another
    ])
    def test_unrelated_dates_still_score_zero(self, a, b):
        assert compare_dates(a, b) == 0.0


class TestMissingEvidenceNeverRefutes:
    """The rule the geographic veto already followed."""

    _SPEC = [
        {"field": "name", "kind": "name", "weight": 2.0},
        {"field": "birth_date", "kind": "date", "weight": 3.0,
         "refutes_below": 0.5},
    ]

    def _edge(self, da, db):
        res = crosswalk([{"id": "x", "name": _NAME, "birth_date": da}],
                        [{"id": "x", "name": _NAME, "birth_date": db}],
                        comparators=self._SPEC, id_field="id")
        return res["matches"][0] if res["matches"] else None

    @pytest.mark.parametrize("da,db", [
        ("", "2016-06-28"), ("2016-06-28", ""), ("", ""),
    ])
    def test_an_absent_date_drops_out_rather_than_refuting(self, da, db):
        edge = self._edge(da, db)
        assert edge is not None
        assert "birth_date" not in edge["evidence"]
        assert "birth_date_conflict" not in edge["evidence"]
        assert edge["decision"] == "match"

    def test_an_unreadable_date_also_drops_out(self):
        """`compare_dates` returns 0.0 for these; the comparator kind must not.

        A field written in a form we cannot parse is missing evidence, not
        evidence against. Scoring it 0.0 under `refutes_below` would punish a
        record for a format nobody promised.
        """
        edge = self._edge("not a date", "2016-06-28")
        assert edge is not None
        assert "birth_date" not in edge["evidence"]
        assert edge["decision"] == "match"

    def test_a_readable_disagreement_still_refutes(self):
        """The abstain path must not have disarmed refutation."""
        assert self._edge("2016-06-28", "2019-01-02") is None


class TestThePersonPack:

    def test_declares_a_birth_date(self):
        spec = [c for c in ENTITY_PACKS["person"] if c["kind"] == "date"]
        assert spec == [{"field": "birth_date", "kind": "date", "weight": 2.0}]

    def test_does_not_declare_refutation(self):
        """Guarded in `test_discriminator_veto.py` as a separate decision.

        A date is exactly the asymmetric signal `refutes_below` was built for,
        and turning it on here measured precision 1.0000 against 0.9962. It is
        still not declared, because established packs do not acquire refutation
        as a side effect of an unrelated change.
        """
        spec = [c for c in ENTITY_PACKS["person"] if c["kind"] == "date"]
        assert "refutes_below" not in spec[0]

    def test_the_pack_now_separates_same_name_different_birthday(self):
        """The 14 false merges, in miniature.

        Two children share a name and nothing else. Before the pack could see
        a date, this merged at score 1.0.
        """
        res = crosswalk(
            [{"id": "a", "name": "Angel Gonzalez", "birth_date": "2018-08-16"}],
            [{"id": "b", "name": "Angel Gonzalez", "birth_date": "2017-08-30"}],
            entity="person", id_field="id")
        assert [e["decision"] for e in res["matches"]] != ["match"]

    def test_the_same_child_across_two_date_formats_still_merges(self):
        """And the reason format tolerance had to come first."""
        res = crosswalk(
            [{"id": "a", "name": "Angel Gonzalez", "birth_date": "8/30/2017"}],
            [{"id": "b", "name": "Angel Gonzalez", "birth_date": "2017-08-30"}],
            entity="person", id_field="id")
        assert [e["decision"] for e in res["matches"]] == ["match"]
        assert res["matches"][0]["evidence"]["birth_date"] == 1.0
