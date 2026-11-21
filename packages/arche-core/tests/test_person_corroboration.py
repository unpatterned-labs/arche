# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""A name alone never links two people.

`reconcile()` scores a pair as a weighted mean over the fields both records
carry, so two person records that share nothing but a name scored 1.0 and were
linked -- by `reconcile`, and so by `Ledger.resolve()`, which decides through
it -- while `arche.compare()` held the same pair for review. The person pack
now declares `needs_support` on its name comparators: another weighted field
must agree at 0.5 or better before a match stands."""

from __future__ import annotations

import arche
from arche.ids import edge_decision_id
from arche.resolve import ENTITY_PACKS, reconcile

NAME = "Jordan Okafor-Vale"


def edge(a, b, entity="person", **kwargs):
    res = reconcile([{"id": "a", **a}], [{"id": "b", **b}], entity=entity, block=None,
                    **kwargs)
    (e,) = res["matches"]
    return e, res["pins"]


class TestReconcile:
    def test_a_name_only_pair_is_held(self):
        e, _ = edge({"name": NAME}, {"name": NAME})
        assert e["score"] == 1.0          # the name does agree; the score says so
        assert e["decision"] == "review" and e["uncorroborated"] == 1

    def test_one_side_without_the_other_field_is_still_name_only(self):
        e, _ = edge({"name": NAME, "birth_date": "1990-04-02"}, {"name": NAME})
        assert e["decision"] == "review" and e["uncorroborated"] == 1

    def test_an_agreeing_second_field_lets_the_match_stand(self):
        for extra in ({"birth_date": "1990-04-02"}, {"phone": "+44 7700 900123"},
                      {"email": "j.vale@mail.example"}):
            e, _ = edge({"name": NAME, **extra}, {"name": NAME, **extra})
            assert e["decision"] == "match" and "uncorroborated" not in e, extra

    def test_a_disagreeing_second_field_is_not_support(self):
        e, _ = edge({"name": NAME, "birth_date": "1990-04-02"},
                    {"name": NAME, "birth_date": "1971-11-30"})
        assert e["decision"] == "review"

    def test_the_rule_is_in_the_decision_id(self):
        e, pins = edge({"name": NAME}, {"name": NAME})
        assert e["decision_id"] == edge_decision_id(e, pins)
        no_rule = [{k: v for k, v in s.items() if k != "needs_support"}
                   for s in ENTITY_PACKS["person"]]
        res = reconcile([{"id": "a", "name": NAME}], [{"id": "b", "name": NAME}],
                        comparators=no_rule, block=None)
        (old,) = res["matches"]
        assert old["decision"] == "match"
        assert res["pins"]["comparators_sha256"] != pins["comparators_sha256"]
        assert old["decision_id"] != e["decision_id"]

    def test_organisations_still_match_on_a_name(self):
        # Companies are identified by name in most supplier files; the rule is
        # declared on the person pack only.
        e, _ = edge({"name": "Harbor Lane Studio LLC"}, {"name": "Harbor Lane Studio LLC"},
                    entity="organisation")
        assert e["decision"] == "match"


class TestLedger:
    def test_resolve_holds_a_name_only_newcomer(self):
        from arche.ledger import Ledger

        ledger = Ledger(":memory:")
        first = ledger.resolve({"name": NAME, "address": "12 Orchard Way, Millbrook NY 12545"},
                               entity_type="person")
        second = ledger.resolve({"name": NAME, "address": "12 Orchard Way, Millbrook, NY 12545"},
                                entity_type="person")
        assert (first.verdict, second.verdict) == ("not_found", "found")
        third = ledger.resolve({"name": NAME}, entity_type="person")
        assert third.verdict == "review"
        assert ledger.entity_of(third.record_id) is None
        assert len(ledger.entity(second.entity.entity_id).records) == 2

    def test_resolve_and_compare_agree(self):
        from arche.ledger import Ledger

        ledger = Ledger(":memory:")
        ledger.resolve({"name": NAME, "email": "j.vale@mail.example"}, entity_type="person")
        held = ledger.resolve({"name": NAME}, entity_type="person")
        pair = arche.compare({"name": NAME, "email": "j.vale@mail.example"}, {"name": NAME},
                             entity="person")
        assert held.verdict == "review" and pair.identity == "review"

    def test_the_held_decision_says_why(self):
        from arche.ledger import Ledger

        ledger = Ledger(":memory:")
        ledger.resolve({"name": NAME, "email": "j.vale@mail.example"}, entity_type="person")
        held = ledger.resolve({"name": NAME}, entity_type="person")
        (decision,) = held.decisions
        assert "no other field" in decision.explanation
        assert decision.evidence["uncorroborated"] == 1
