# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Tests for `refutes_below`, the declarable discriminator veto.

Some attributes refute without confirming, and a weight cannot express one
because a weight is symmetric: it rewards agreement by exactly as much as it
punishes disagreement.

The measurement that produced this feature is DBLP-ACM, where the Leipzig
mapping is complete so false merges are visible at all. Publication year agrees
on 2,224 of 2,224 true pairs and separates 213 of 391 false merges, yet raising
its weight *lowers* precision (0.850 at 0.5, 0.876 at 2.0, 0.653 at 7.0) because
thousands of unrelated papers share a year. Declared as a refutation instead,
precision goes 0.850 -> 0.951 with recall unchanged at 0.996.

Before this existed, arche had exactly two vetoes: `veto_km`, which requires
coordinates, and `id_conflict`, hardcoded to the field name `national_id`.
Neither was reachable from a declaration. This generalises the first one; the
rules it keeps are the rules the geographic veto already followed — demote to
`review` and never to `no_match`, and never refute on a missing value.
"""

from __future__ import annotations

import pytest

from arche.resolve import crosswalk

_NAME = "Zephyrine Quillfeather"

# One distinctive name, two records. Everything except `year` agrees, so the
# year is the only thing that can separate them.
_A = [{"name": _NAME, "year": "1994"}]
_SAME_YEAR = [{"name": _NAME, "year": "1994"}]
_DIFF_YEAR = [{"name": _NAME, "year": "1987"}]
_NO_YEAR = [{"name": _NAME}]

_NAME_SPEC = {"field": "name", "kind": "name", "weight": 3.0}


def _comparators(*, refutes=None, weight=0.5):
    year = {"field": "year", "kind": "date", "weight": weight}
    if refutes is not None:
        year["refutes_below"] = refutes
    return [_NAME_SPEC, year]


def _edges(B, **kw):
    return crosswalk(_A, B, comparators=_comparators(**kw))["matches"]


def _decisions(B, **kw):
    return [e["decision"] for e in _edges(B, **kw)]


class TestTheDefect:
    """What the engine did before `refutes_below` existed."""

    def test_disagreeing_year_still_merged(self):
        """Pinned. The year scores 0.0 and the pair merges anyway.

        This is the whole reason the feature exists: a comparator can be
        maximally certain the records disagree and still be outvoted.
        """
        assert _decisions(_DIFF_YEAR) == ["match"]

    def test_the_disagreement_was_visible_all_along(self):
        """The evidence recorded 0.0. Nothing acted on it."""
        assert _edges(_DIFF_YEAR)[0]["evidence"]["year"] == 0.0

    def test_raising_the_weight_overcorrects_and_loses_the_pair(self):
        """The obvious fix is worse than the bug, in both directions at once.

        A heavy year drags this pair to (3*1.0 + 25*0.0) / 28 = 0.107, under
        the floor, so the edge is **dropped entirely** rather than demoted —
        the reviewer never sees the conflict that caused it. That is strictly
        worse than `review`, which is what a refutation produces.

        And it does not even buy precision, because a weight is symmetric:
        agreement on a low-entropy field gains as much as disagreement loses,
        so on DBLP-ACM precision *fell* from 0.876 to 0.653 between weights
        2.0 and 7.0. Overcorrecting on true pairs, undercorrecting on false
        ones — a weight is the wrong instrument for this job.
        """
        assert _decisions(_DIFF_YEAR, weight=25.0) == []
        # The refutation keeps the pair and hands it to a human.
        assert _decisions(_DIFF_YEAR, refutes=0.99) == ["review"]


class TestRefutation:
    def test_disagreeing_year_is_demoted(self):
        assert _decisions(_DIFF_YEAR, refutes=0.99) == ["review"]

    def test_agreeing_year_still_matches(self):
        """Refutation must cost nothing when the discriminator agrees."""
        assert _decisions(_SAME_YEAR, refutes=0.99) == ["match"]

    def test_demotes_to_review_never_to_no_match(self):
        """The pair survives as a review edge; it is not dropped.

        A refutation says a human must look, not that the answer is no. If it
        dropped the edge the reviewer would never see the conflict, which is
        the failure mode the geographic veto was written to avoid.
        """
        edges = _edges(_DIFF_YEAR, refutes=0.99)
        assert len(edges) == 1
        assert edges[0]["decision"] == "review"

    def test_conflict_is_named_in_the_evidence(self):
        """A demotion a reviewer cannot explain is indistinguishable from a bug."""
        evidence = _edges(_DIFF_YEAR, refutes=0.99)[0]["evidence"]
        assert evidence["year_conflict"] == 0.0

    def test_no_conflict_key_when_the_discriminator_agrees(self):
        assert "year_conflict" not in _edges(_SAME_YEAR, refutes=0.99)[0]["evidence"]


class TestAbsentEvidenceRefutesNothing:
    """You cannot refute on evidence you do not have."""

    def test_missing_on_one_side_does_not_refute(self):
        assert _decisions(_NO_YEAR, refutes=0.99) == ["match"]

    def test_missing_on_both_sides_does_not_refute(self):
        res = crosswalk(
            [{"name": _NAME}], _NO_YEAR, comparators=_comparators(refutes=0.99),
        )
        assert [e["decision"] for e in res["matches"]] == ["match"]

    def test_empty_string_does_not_refute(self):
        """An empty field is missing, not a disagreement of zero."""
        assert _decisions([{"name": _NAME, "year": ""}], refutes=0.99) == ["match"]


class TestPureDiscriminator:
    """`weight: 0.0` plus `refutes_below`: refutes and never confirms."""

    def test_refutes_at_zero_weight(self):
        assert _decisions(_DIFF_YEAR, refutes=0.99, weight=0.0) == ["review"]

    def test_agreement_at_zero_weight_adds_nothing_to_the_score(self):
        """The point of weight 0.0 — agreement must not inflate the score.

        With weight 0.5 the agreeing year drags a perfect name match nowhere
        (both are 1.0), so compare against a partial name instead: the score
        must equal what `name` alone produces.
        """
        partial_a = [{"name": "Zephyrine Quillfeather", "year": "1994"}]
        partial_b = [{"name": "Zephyrine Quillfeathers", "year": "1994"}]
        with_year = crosswalk(
            partial_a, partial_b,
            comparators=_comparators(refutes=0.99, weight=0.0),
        )["matches"]
        name_only = crosswalk(
            partial_a, partial_b, comparators=[_NAME_SPEC],
        )["matches"]
        assert with_year[0]["score"] == name_only[0]["score"]


class TestThreshold:
    def test_score_equal_to_the_threshold_does_not_refute(self):
        """Strictly below. `refutes_below: 1.0` must not demote a 1.0 match."""
        assert _decisions(_SAME_YEAR, refutes=1.0) == ["match"]

    def test_score_below_the_threshold_refutes(self):
        assert _decisions(_DIFF_YEAR, refutes=1.0) == ["review"]


class TestValidation:
    """An out-of-range threshold reads as a tuning problem, so it fails loudly.

    Above 1.0 it refutes everything it touches and the run merely looks
    conservative; at or below 0.0 it can never fire and the run merely looks
    permissive. Neither is distinguishable from a deliberate choice at a glance.
    """

    @pytest.mark.parametrize("bad", [0.0, -0.5, 1.5, 2.0])
    def test_out_of_range_raises(self, bad):
        with pytest.raises(ValueError, match="refutes_below"):
            crosswalk(_A, _SAME_YEAR, comparators=_comparators(refutes=bad))

    def test_non_numeric_raises(self):
        with pytest.raises(ValueError, match="must be a number"):
            crosswalk(_A, _SAME_YEAR, comparators=_comparators(refutes="high"))

    def test_the_error_names_the_offending_comparator(self):
        with pytest.raises(ValueError, match="year"):
            crosswalk(_A, _SAME_YEAR, comparators=_comparators(refutes=9.0))

    @pytest.mark.parametrize("ok", [0.01, 0.5, 0.99, 1.0])
    def test_valid_range_is_accepted(self, ok):
        crosswalk(_A, _SAME_YEAR, comparators=_comparators(refutes=ok))


class TestGeneralisation:
    """It works on any comparator kind, which is the entire point."""

    def test_refutes_on_a_text_comparator(self):
        """Not just dates — an edition, a model number, a publisher string."""
        comparators = [
            _NAME_SPEC,
            {"field": "publisher", "kind": "name", "weight": 0.0,
             "refutes_below": 0.9},
        ]
        a = [{"name": _NAME, "publisher": "Troubador"}]
        b = [{"name": _NAME, "publisher": "Penguin Random House"}]
        res = crosswalk(a, b, comparators=comparators)
        assert [e["decision"] for e in res["matches"]] == ["review"]

    def test_packs_with_published_numbers_do_not_declare_it(self):
        """Turning refutation on for an established pack moves its published numbers.

        `place`, `person` and `artist` all have benchmark figures in the docs
        and changelog, so enabling `refutes_below` on any of them is a separate,
        separately-measured decision rather than a side effect.

        Four packs are exempt, by one principle: refutation is part of the
        identity contract they shipped with on their first release, so there is
        no earlier number for it to move.

        `product_electronics` — a purchasable variant, where a capacity or pack
        size difference means a different product.

        `product_grocery` — net contents are the identity of a supermarket
        SKU, so a 200g pack and a 500g pack of one item are two products and
        the weight has to refute. First release, first numbers, measured with
        the refutation already in them.

        `product_home_goods` — the same contract for furniture, bedding and
        rugs, and it exists *because* refutation was missing there. Pointing
        `product_electronics` at a home-goods catalogue silently disables both
        its safety mechanisms, so this pack's first published numbers are
        measured with `spec` and `rival` refutation already in them. Nothing
        earlier to move.

        `organisation` — the party as named on a document, where sameness of
        *site* is not sameness of party. `Nyeri Hill Factory` and `Nyeri Hill
        Tea Factory Co Ltd` share a name and a coordinate, so every string and
        spatial signal points the wrong way and only a declared `entity_class`
        refutes them. That pack also ships with **no published accuracy number
        at all**, deliberately, so this guard has nothing to protect there yet.
        When one is published, this exemption should be revisited rather than
        inherited.
        """
        from arche.resolve import ENTITY_PACKS

        # By list identity, so the `organization` spelling alias is covered
        # without having to remember it here.
        exempt = [ENTITY_PACKS["product_electronics"],
                  ENTITY_PACKS["product_home_goods"],
                  ENTITY_PACKS["product_grocery"],
                  ENTITY_PACKS["organisation"]]
        established = {
            name for name, specs in ENTITY_PACKS.items()
            if not any(specs is e for e in exempt)
        }
        for name in established:
            for spec in ENTITY_PACKS[name]:
                assert "refutes_below" not in spec, (
                    f"{name} pack now declares refutes_below; its benchmark "
                    "numbers must be re-measured and republished first"
                )

    def test_the_product_lane_declares_it_deliberately(self):
        from arche.resolve import ENTITY_PACKS

        assert any("refutes_below" in s
                   for s in ENTITY_PACKS["product_electronics"])
