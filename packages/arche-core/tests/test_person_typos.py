# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""`near` on the token comparator, and the `person_typos` pack that turns it on."""

from __future__ import annotations

from arche.resolve import ENTITY_PACKS, TokenFrequencyTable, reconcile

TF = TokenFrequencyTable.from_corpus(["Temanu Ajala", "Temanu Obodo", "Kanyiri Ajala"])


def test_off_by_default():
    literal = TF.weighted_token_sim("Micheala Kanyiri", "Michaela Kanyiri")
    assert literal < 1.0
    assert TF.weighted_token_sim("Micheala Kanyiri", "Michaela Kanyiri", near=None) == literal


def test_a_misspelt_token_counts():
    assert TF.weighted_token_sim("Micheala Kanyiri", "Michaela Kanyiri", near=0.90) > 0.9


def test_never_lowers_the_literal_score():
    for a, b in [("Temanu Ajala", "Temanu Ajala"), ("Temanu Ajala", "Obodo Kanyiri"),
                 ("Ajala", "Ajala Temanu")]:
        assert TF.weighted_token_sim(a, b, near=0.90) >= TF.weighted_token_sim(a, b)


def test_an_unlike_token_does_not_count():
    assert TF.weighted_token_sim("Temanu Kanyiri", "Obodo Kanyiri", near=0.90) == \
        TF.weighted_token_sim("Temanu Kanyiri", "Obodo Kanyiri")


def test_a_token_is_used_once():
    # one "Ajala" cannot agree with both "Ajalla" and "Ajalaa"
    one = TF.weighted_token_sim("Ajala", "Ajalla Ajalaa", near=0.90)
    assert one < 0.9


def test_person_itself_is_unchanged():
    assert all("near" not in spec for spec in ENTITY_PACKS["person"])
    changed = [s for s in ENTITY_PACKS["person_typos"] if "near" in s]
    assert [s["kind"] for s in changed] == ["tftoken"]


def test_the_pack_scores_a_typo_on_the_token_comparator():
    a = [{"id": "a", "name": "Michaela Kanyiri", "birth_date": "1984-03-02",
          "address": "8 Ajala Street, Temanu"}]
    b = [{"id": "b", "name": "Micheala Kaniyri", "birth_date": "1984-03-02",
          "address": "8 Ajala Street, Temanu"}]
    evidence = {p: reconcile(a, b, entity=p, id_field="id")["matches"][0]["evidence"]
                for p in ("person", "person_typos")}
    assert evidence["person"]["name_tftoken"] == 0.0
    assert evidence["person_typos"]["name_tftoken"] > 0.9
    assert evidence["person"]["name"] == evidence["person_typos"]["name"]


def test_two_first_names_are_still_held():
    a = [{"id": "a", "name": "Adaeze Kanyiri", "birth_date": "1984-03-02"}]
    b = [{"id": "b", "name": "Obinna Kanyiri", "birth_date": "1984-03-02"}]
    edges = reconcile(a, b, entity="person_typos", id_field="id")["matches"]
    assert "match" not in [e["decision"] for e in edges]
