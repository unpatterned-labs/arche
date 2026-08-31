# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Similarity and distinctiveness disagree, and the disagreement is the product.

Pins the worked examples in
`docs-site/docs/concepts/probabilistic-linkage-vs-representation.md`, which
argues that representation similarity structurally cannot answer an identity
question. The argument rests on four measured pairs, so if the numbers move the
document becomes wrong and nothing else would say so -- `concepts/` is excluded
from `mkdocs.yml`, so `test_docs_examples.py` never executes its code blocks.

The load-bearing observation is the first three rows: **identical strings, three
different correct answers.** Any function of the two strings alone returns its
maximum for all three, so no encoder, however good, separates them. The
separating fact -- how many other facilities carry this name -- is not present
in either string.

A table rebuild is the thing most likely to break these. That is the point: it
should break them, loudly, rather than leave a document asserting numbers the
engine no longer produces.
"""

from __future__ import annotations

import pytest
from arche.resolve import compare_names, reconcile


def probe(name_a: str, name_b: str, entity: str = "place"):
    a = [{"id": "a", "name": name_a}]
    b = [{"id": "b", "name": name_b}]
    edges = reconcile(a, b, entity=entity, id_field="id")["matches"]
    assert edges, f"{name_a!r} vs {name_b!r} was not surfaced as a candidate"
    edge = edges[0]
    return edge["score"], edge["distinctive_max"], edge["decision"]


class TestIdenticalStringsThreeAnswers:
    """The core claim. Same comparison, same score, different verdicts."""

    @pytest.mark.parametrize("name,distinctive,decision", [
        ("General Hospital", 0.564, "review"),
        ("Karfi Health Post", 0.927, "match"),
        ("Gyaranya Health Post", 0.860, "match"),
    ])
    def test_a_name_against_itself(self, name, distinctive, decision):
        score, got_distinctive, got_decision = probe(name, name)
        assert score == 1.0
        assert got_distinctive == pytest.approx(distinctive, abs=5e-4)
        assert got_decision == decision

    def test_similarity_is_constant_where_the_decision_is_not(self):
        """Stated as one assertion because it is one argument.

        If this ever passes with the scores differing, the document's central
        claim -- that similarity cannot separate these -- has stopped being
        true and the page needs rewriting, not the test relaxing.
        """
        names = ["General Hospital", "Karfi Health Post", "Gyaranya Health Post"]
        results = [probe(n, n) for n in names]

        assert {score for score, _, _ in results} == {1.0}
        assert len({decision for _, _, decision in results}) > 1
        assert len({distinctive for _, distinctive, _ in results}) == 3


class TestSemanticNeighboursAreNotTheSameThing:
    """The complementary failure: relatedness pushing up where identity needs down.

    `General Hospital` and `General Clinic` are close in any semantic sense --
    same domain, same modifier, same institutional category -- and are different
    facilities. arche scores them 0.637 on name similarity. A semantic encoder
    would plausibly score them higher, which is the direction that produces a
    false match.
    """

    def test_they_do_not_match(self):
        score, distinctive, decision = probe("General Hospital", "General Clinic")
        assert score == pytest.approx(0.6373, abs=5e-4)
        assert decision == "review"

    def test_the_generic_token_is_set_aside_rather_than_credited(self):
        """Both names share `General`. The distinctiveness of the pair is the
        same as for two identical `General Hospital` records -- the shared token
        buys nothing either way."""
        _, pair_distinctive, _ = probe("General Hospital", "General Clinic")
        _, self_distinctive, _ = probe("General Hospital", "General Hospital")
        assert pair_distinctive == self_distinctive


class TestAliasesComeFromATableNotAModel:
    """Quoted in the document to make a narrower point: for an enumerable
    phenomenon, a curated equivalence table beats a model, because a domain
    expert can inspect and correct it."""

    @pytest.mark.parametrize("a,b,expected", [
        ("Diallo", "Jallow", 0.9111),
        ("Mohammed", "Muhammad", 0.94),
    ])
    def test_orthographic_variants_are_recognised(self, a, b, expected):
        similarity, _ = compare_names(a, b)
        assert similarity == pytest.approx(expected, abs=5e-4)

    def test_an_unrelated_pair_is_not(self):
        """Guards the above against a table so permissive it matches anything."""
        similarity, _ = compare_names("Diallo", "Okonkwo")
        assert similarity < 0.5


class TestAnUnseenTokenIsAssumedRare:
    """The sharpest limitation of a frequency gate, pinned so it stays visible.

    A token absent from the table falls to the unknown floor and is treated as
    maximally distinctive. That default is usually right -- a name a gazetteer
    of 1.25M records has never seen is usually genuinely unusual -- but it is an
    assumption, not a measurement, and a misspelling satisfies it just as well.

    Measured on the place pack:

        General Hospital  vs itself -> distinctive_max 0.564 -> review
        Genrel Hopsital   vs itself -> distinctive_max 0.860 -> match

    **The same two records auto-merge once both sides carry the same OCR
    error**, because nothing in the gazetteer says `hopsital` is ordinary. This
    matters most in exactly the setting the gate exists for: scanned invoices
    and certificates, where one systematic error lands on both documents.

    Not a bug to fix here -- the fix is normalisation upstream, and changing the
    floor would break the case it is right about. It is recorded so that anyone
    relying on `distinctive_max` knows to ask whether the agreeing token was
    measured-rare or merely unseen.
    """

    def test_the_correctly_spelled_pair_is_refused(self):
        assert probe("General Hospital", "General Hospital")[2] == "review"

    def test_the_identically_misspelled_pair_is_not(self):
        score, distinctive, decision = probe("Genrel Hopsital", "Genrel Hopsital")
        assert score == 1.0
        assert distinctive == pytest.approx(0.860, abs=5e-4)
        assert decision == "match"

    def test_the_typo_scores_as_more_distinctive_than_the_real_name(self):
        """Stated as the comparison, because the comparison is the problem."""
        _, real, _ = probe("General Hospital", "General Hospital")
        _, typo, _ = probe("Genrel Hopsital", "Genrel Hopsital")
        assert typo > real
