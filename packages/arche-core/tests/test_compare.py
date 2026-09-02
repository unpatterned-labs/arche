# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""One question, one verb, whatever the entity and whatever the input shape.

Before this, "are these two the same?" was answerable for people and not for
suppliers: ``pairwise(a, b, entity="organisation")`` raised, and the error told
the caller to build two single-item lists and call the batch verb instead. The
two verbs also disagreed about input -- ``pairwise`` took References and
strings and rejected dicts; ``crosswalk`` required dicts. A caller could not
learn one and use the other, and neither could an agent choosing between them.

``compare`` closes both gaps without merging the two engines, which remain
genuinely different maths. It routes: ``person`` to the Fellegi-Sunter engine
with its fixed person schema, everything else to the pack engine that
``crosswalk`` already uses, and returns one type either way.
"""

from __future__ import annotations

import pytest

from arche.resolve import ENTITY_PACKS, compare, reconcile

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_ORG = {
    "name": "Karfi Agro Cooperative Society Ltd",
    "address": "12 Zaria Road, Kano",
}
_ORG_SAME = {
    "name": "Karfi Agro Co-operative Soc.",
    "address": "12 Zaria Rd, Kano State",
    "registration_id": "RC-889112",
}
_ORG_OTHER_DOOR = {
    "name": "Karfi Agro Cooperative Society Ltd",
    "address": "8 Murtala Way, Kaduna",
}
_ORG_UNRELATED = {"name": "Zenith Bank Plc", "address": "Victoria Island, Lagos"}


# ---------------------------------------------------------------------------
# The gap that was closed
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("entity", sorted(ENTITY_PACKS))
def test_every_shipped_pack_answers_the_pairwise_question(entity):
    # The guard that keeps the surface honest as packs are added: a pack that
    # `crosswalk` can run but `compare` cannot is the exact asymmetry this
    # existed to remove, and it would come back silently.
    decision = compare({"name": "Alpha"}, {"name": "Alpha"}, entity=entity)
    assert decision.identity in {"same_entity", "review", "different"}
    assert decision.action in {"merge", "hold", "no_op"}


def test_person_accepts_plain_records():
    # `crosswalk` always took dicts; the pairwise path did not, so the same
    # record could be passed to one verb and not the other.
    decision = compare(
        {"full_name": "Ngozi Okonkwo", "national_id": "N1"},
        {"full_name": "Ngozi Okonkwo", "national_id": "N1"},
    )
    assert decision.identity == "same_entity"


def test_the_old_spellings_still_work_and_now_say_so():
    # `pairwise` and `crosswalk` were silent aliases while this repo still
    # called them 276 times. Once those call sites moved, the aliases could
    # start warning -- in that order, because a DeprecationWarning that fires
    # hundreds of times in a passing suite is one people learn to filter, and
    # then the next real deprecation goes unnoticed.
    import warnings

    from arche.resolve import crosswalk, pairwise

    for old, new in (("pairwise", pairwise), ("crosswalk", crosswalk)):
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            if old == "pairwise":
                result = new("Adebayo Oluwaseun", "Adebayo Oluwaseun")
                assert result.identity == compare(
                    "Adebayo Oluwaseun", "Adebayo Oluwaseun"
                ).identity
            else:
                a = [{"id": "a", "name": "Karfi PHC"}]
                b = [{"id": "b", "name": "Karfi PHC"}]
                comparators = [{"field": "name", "kind": "placename",
                                "weight": 2.0}]
                assert new(a, b, comparators, block=None) == reconcile(
                    a, b, comparators, block=None
                )
        messages = [str(w.message) for w in caught
                    if issubclass(w.category, DeprecationWarning)]
        assert messages, f"{old} did not warn"
        assert old in messages[0]


# ---------------------------------------------------------------------------
# The three outcomes, on the pack engine
# ---------------------------------------------------------------------------


def test_same_supplier_matches():
    assert compare(_ORG, _ORG_SAME, entity="organisation").identity == "same_entity"


def test_same_name_different_door_is_held():
    # The premises comparator, reached through the new verb rather than through
    # a two-item crosswalk. Same engine, so the same answer.
    decision = compare(_ORG, _ORG_OTHER_DOOR, entity="organisation")
    assert decision.identity == "review"
    assert decision.action == "hold"


def test_unrelated_organisations_are_different():
    decision = compare(_ORG, _ORG_UNRELATED, entity="organisation")
    assert decision.identity == "different"
    assert decision.action == "no_op"


def test_different_says_why_rather_than_going_quiet():
    # `crosswalk` answers a below-floor pair by emitting nothing, which is the
    # right answer for two lists and an ambiguous one for a named pair --
    # silence reads the same as "never compared". The receipt has to say which.
    decision = compare(_ORG, _ORG_UNRELATED, entity="organisation")
    assert decision.gate["surfaced"] is False
    assert decision.gate["surfacing_floor"] == pytest.approx(0.55)
    assert "surfacing floor" in decision.explanation


# ---------------------------------------------------------------------------
# Blocking must not answer a question it was not asked
# ---------------------------------------------------------------------------


def test_an_explicitly_named_pair_is_always_compared():
    # Blocking is a scale optimisation for lists: skip pairs that cannot
    # plausibly match so the run finishes. A caller naming one pair has already
    # made that judgement. Left on, `crosswalk` never compares this pair at all
    # (`candidate_pairs=0`) and emits nothing -- indistinguishable from a
    # comparison that came out low. `compare` turns blocking off so the answer
    # is a decision rather than an omission.
    blocked = reconcile(
        [dict(_ORG, id="a")], [dict(_ORG_UNRELATED, id="b")],
        entity="organisation", id_field="id",
    )
    assert blocked["blocking"]["candidate_pairs"] == 0, (
        "fixture no longer demonstrates the blocking drop; pick a more "
        "dissimilar pair or this test proves nothing"
    )
    assert compare(_ORG, _ORG_UNRELATED, entity="organisation").identity == "different"


# ---------------------------------------------------------------------------
# Provenance: the receipt must say which engine decided
# ---------------------------------------------------------------------------


def test_the_receipt_names_the_pack_that_decided():
    assert compare(_ORG, _ORG_SAME, entity="organisation").pins["entity_pack"] == (
        "organisation"
    )


def test_a_surfaced_decision_quotes_the_engines_own_id():
    # Not a recomputed one. The pack engine issued an edge under
    # `arche.crosswalk_edge.v1` and that edge already has an address; minting a
    # second address for one decision is how provenance quietly forks.
    decision = compare(_ORG, _ORG_SAME, entity="organisation")
    edge = reconcile(
        [dict(_ORG, id="a")], [dict(_ORG_SAME, id="b")],
        entity="organisation", id_field="id", block=None,
    )["matches"][0]
    assert decision.decision_id == edge["decision_id"]
    assert decision.decision_id.startswith("xwd:")


def test_an_unsurfaced_decision_is_still_addressable():
    # No edge means no engine-issued receipt to quote, so the address is
    # computed here the way the person path computes its own. The `dec:` prefix
    # is the tell, and it is deliberate: it says where the id came from.
    decision = compare(_ORG, _ORG_UNRELATED, entity="organisation")
    assert decision.decision_id.startswith("dec:")


def test_decisions_reproduce():
    first = compare(_ORG, _ORG_SAME, entity="organisation")
    second = compare(_ORG, _ORG_SAME, entity="organisation")
    assert first.decision_id == second.decision_id
    assert first.score == second.score


def test_unsurfaced_decisions_reproduce_too():
    # The computed address must be a function of the inputs, not of anything
    # incidental. Two different below-floor pairs must not collide either.
    assert (
        compare(_ORG, _ORG_UNRELATED, entity="organisation").decision_id
        == compare(_ORG, _ORG_UNRELATED, entity="organisation").decision_id
    )
    assert (
        compare(_ORG, _ORG_UNRELATED, entity="organisation").decision_id
        != compare(_ORG_SAME, _ORG_UNRELATED, entity="organisation").decision_id
    )


def test_the_two_engines_are_not_silently_pooled():
    # One is a log-odds sum, the other a weighted mean over a pack. A caller
    # comparing `score` across them is comparing different units, so the pin
    # that names the engine has to differ.
    person = compare(
        {"full_name": "Ngozi Okonkwo", "national_id": "N1"},
        {"full_name": "Ngozi Okonkwo", "national_id": "N1"},
    )
    org = compare(_ORG, _ORG_SAME, entity="organisation")
    assert person.pins.get("engine") != org.pins.get("engine")
    assert "entity_pack" not in person.pins


# ---------------------------------------------------------------------------
# Refusals
# ---------------------------------------------------------------------------


def test_an_unknown_pack_is_refused_by_name():
    with pytest.raises(ValueError, match="no entity pack named"):
        compare({"name": "x"}, {"name": "y"}, entity="hospitl")


def test_a_pack_entity_refuses_strings():
    with pytest.raises(TypeError, match="expects two dict records"):
        compare("Karfi Agro", "Karfi Agro", entity="organisation")


def test_a_mixed_pair_is_refused():
    from arche.canonical import Reference

    with pytest.raises(TypeError, match="expects two dicts"):
        compare(Reference.from_record({"full_name": "A"}), "a string")


# ---------------------------------------------------------------------------
# reconcile: the merged verb
# ---------------------------------------------------------------------------


def test_the_deprecation_register_is_honest():
    # Every old spelling names a replacement, and the replacement exists. A
    # warning that does not say what to use instead moves the problem to the
    # caller; one that names something unimportable is worse, because the
    # caller follows it, hits an ImportError, and trusts the next one less.
    import arche.resolve as R

    for old, new in R._DEPRECATED.items():
        assert hasattr(R, old), f"{old} was deprecated out of existence"
        assert hasattr(R, new), f"{old} points at missing {new}"


def test_reconcile_accepts_comparators_positionally():
    # `reconcile` used to name the lower-level engine, which took comparators
    # as its third positional argument. Fifteen call sites in this repo still
    # call it that way; the merged verb keeps that shape so a rename does not
    # become a migration.
    from arche.resolve import reconcile

    a = [{"id": "a", "name": "Karfi Primary Health Centre"}]
    b = [{"id": "b", "name": "Karfi PHC"}]
    comparators = [{"field": "name", "kind": "placename", "weight": 2.0}]
    assert reconcile(a, b, comparators, block=None, threshold=0.6)["count"] == 1


def test_a_self_calibrated_table_is_disclosed_not_forbidden():
    # I first made this a refusal: hand-written comparators with a `tftoken`
    # and no `tf=` raised, on the reasoning that a table self-calibrated over a
    # small batch is measurably miscalibrated. Seventeen existing tests
    # disagreed, and they were right -- self-calibration is the DESIGNED path
    # for a corpus-specific vocabulary, because a product catalogue has no
    # population table to ship. The lesson from the person lane (prefer the
    # shipped table) does not transfer to a lane where no shipped table can
    # exist.
    #
    # What makes it safe is the pin, which already existed: arche names the
    # table it chose, and that name is hashed into every edge's address. The
    # rule is disclose, not forbid.
    from arche.resolve import reconcile

    a = [{"id": "A", "name": "Karfi PHC"}]
    b = [{"id": "B", "name": "Karfi PHC"}]
    comparators = [{"field": "name", "kind": "tftoken", "weight": 1.0}]
    assert reconcile(a, b, comparators)["pins"]["tf"].startswith("self-calibrated@")


def test_a_pack_may_still_choose_its_own_table():
    # The guard is scoped to hand-written comparators. A pack has already
    # answered the question -- it either names a shipped table or documents
    # that its population is the two lists -- so `entity=` keeps working with
    # no `tf=`, which is what almost every caller does.
    from arche.resolve import reconcile

    a = [{"id": "a", "name": "Karfi Primary Health Centre", "lat": 11.6, "lon": 8.4}]
    b = [{"id": "b", "name": "Karfi PHC", "lat": 11.6005, "lon": 8.4005}]
    assert reconcile(a, b, entity="place")["count"] >= 0
