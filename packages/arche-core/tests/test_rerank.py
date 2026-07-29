# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Block-aware distinguishing-token reranker."""

from arche.resolve._rerank import rerank_score
from arche.resolve._tokenfreq import TokenFrequencyTable


def test_shared_rare_token_beats_shared_common_token():
    # Corpus where "clinic" is ubiquitous (common) and "karfi" is rare.
    corpus = ["clinic"] * 50 + ["karfi clinic", "central clinic", "market clinic"]
    tf = TokenFrequencyTable.from_corpus(corpus)

    # Two pairs, each sharing exactly one token beyond nothing else.
    rare = rerank_score(0.5, "karfi clinic", "karfi ward", [], tf)
    common = rerank_score(0.5, "clinic house", "clinic ward", [], tf)

    # Sharing the rare "karfi" is stronger evidence than sharing "clinic".
    assert rare > common


def test_block_discriminating_token_is_punished():
    # a = "10 downing street"; candidate b_same has "10", candidate b_other is
    # "11 downing street". Against b_other, the token "10" appears in another
    # candidate (b_same) but not in b_other -> it discriminates -> punish.
    corpus = [
        "10 downing street", "10 downing street", "11 downing street",
    ]
    tf = TokenFrequencyTable.from_corpus(corpus)

    a = "10 downing street"
    b_same = "10 downing street"
    b_other = "11 downing street"

    # Score b_other WITH the discriminating "10" present in another candidate...
    with_discriminator = rerank_score(
        0.7, a, b_other, other_texts=[b_same], tf=tf,
    )
    # ...vs the same pair evaluated with no competing candidate in the block.
    no_block_context = rerank_score(
        0.7, a, b_other, other_texts=[], tf=tf,
    )
    assert with_discriminator < no_block_context

    # And the true pair (b_same) is rewarded above the discriminated pair.
    true_pair = rerank_score(0.7, a, b_same, other_texts=[b_other], tf=tf)
    assert true_pair > with_discriminator


def test_score_stays_in_unit_interval():
    tf = TokenFrequencyTable.from_corpus(["alpha beta", "gamma delta"])
    hi = rerank_score(0.99, "alpha beta", "alpha beta", [], tf)
    lo = rerank_score(0.01, "alpha", "beta", ["alpha"], tf)
    assert 0.0 <= lo <= 1.0
    assert 0.0 <= hi <= 1.0


def test_empty_tokens_returns_clamped_base():
    tf = TokenFrequencyTable.from_corpus(["something"])
    assert rerank_score(0.6, "", "anything", [], tf) == 0.6
