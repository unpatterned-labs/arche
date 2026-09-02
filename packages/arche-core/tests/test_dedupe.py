# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""The third verb: which records in ONE list are the same thing?

``compare`` answers it for two records, ``reconcile`` for two lists, and until
now nothing answered it for one list of plain records. ``resolve_entities``
comes closest but works on extracted ``Entity`` objects through the classical
path, not on dict records through the comparator packs; ``group_by_identity``
is a different job entirely (it groups mentions by proximity within one
document).

The obvious shortcut is wrong, which is most of why this function exists.
``reconcile(records, records)`` joins a list to itself and reports ``n``
self-pairs -- every record matching itself at 1.000 -- plus a mirrored edge for
every real pair. On three records that is five edges where one is true.
"""

from __future__ import annotations

import pytest

from arche.resolve import dedupe, reconcile

_ORGS = [
    {"id": "1", "name": "Karfi Agro Cooperative Society Ltd",
     "address": "12 Zaria Road, Kano"},
    {"id": "2", "name": "Karfi Agro Co-operative Soc.",
     "address": "12 Zaria Rd, Kano State"},
    {"id": "3", "name": "Zenith Bank Plc", "address": "Victoria Island, Lagos"},
]

#: Neighbours are close, the ends are not: A matches B, B matches C at a
#: loosened threshold, and A against C scores 0.000. The shape that makes a
#: transitive cluster, and the reason `held_together_by` is reported.
_CHAIN = [
    {"id": "A", "name": "Kano Central Trading Company Limited"},
    {"id": "B", "name": "Kano Central Trading Co"},
    {"id": "C", "name": "Central Trading Co Lagos"},
]


# ---------------------------------------------------------------------------
# The shortcut this replaces
# ---------------------------------------------------------------------------


def test_the_self_join_really_is_wrong():
    # Pinned rather than asserted in prose, so the justification for a separate
    # verb stays true. If reconcile ever stops emitting self-pairs and mirrors,
    # this fails and dedupe's rationale needs rereading.
    self_join = reconcile(_ORGS, _ORGS, entity="organisation", id_field="id",
                          block=None)
    pairs = [(m["a_id"], m["b_id"]) for m in self_join["matches"]]
    assert ("1", "1") in pairs, "expected a self-pair"
    assert ("1", "2") in pairs and ("2", "1") in pairs, "expected mirrors"


def test_dedupe_drops_self_pairs_and_mirrors():
    run = dedupe(_ORGS, entity="organisation", block=None)
    pairs = [(m["a_id"], m["b_id"]) for m in run["matches"]]
    assert pairs == [("1", "2")]
    assert run["count"] == 1


def test_no_edge_is_a_record_against_itself():
    for m in dedupe(_ORGS, entity="organisation", block=None)["matches"]:
        assert m["a_id"] != m["b_id"]


def test_each_pair_is_reported_once():
    run = dedupe(_ORGS, entity="organisation", block=None)
    seen = [frozenset((m["a_id"], m["b_id"])) for m in run["matches"]]
    assert len(seen) == len(set(seen))


# ---------------------------------------------------------------------------
# Clusters
# ---------------------------------------------------------------------------


def test_duplicates_cluster_and_singletons_survive():
    clusters = dedupe(_ORGS, entity="organisation", block=None)["clusters"]
    assert [c["members"] for c in clusters] == [["1", "2"], ["3"]]
    # The singleton is a finding, not noise: it is the answer "this one is
    # unique". Dropping it would leave the output impossible to line up
    # against the input.
    assert sum(c["size"] for c in clusters) == len(_ORGS)


def test_a_fully_compared_cluster_is_direct():
    clusters = dedupe(_ORGS, entity="organisation", block=None)["clusters"]
    assert all(c["held_together_by"] == "direct" for c in clusters)


def test_a_chained_cluster_says_it_is_transitive():
    # THE honesty property. A matched B and B matched C, so all three group --
    # but A against C scored 0.000 and was never a match. Every dedupe tool
    # does this closure; the failure mode is doing it silently, because that is
    # how two genuinely different records end up merged into one entity.
    run = dedupe(_CHAIN, entity="organisation", block=None, threshold=0.6)
    matched = {frozenset((m["a_id"], m["b_id"]))
               for m in run["matches"] if m["decision"] == "match"}
    assert matched == {frozenset(("A", "B")), frozenset(("B", "C"))}
    assert frozenset(("A", "C")) not in matched, (
        "fixture no longer chains; this test proves nothing"
    )
    [cluster] = run["clusters"]
    assert cluster["members"] == ["A", "B", "C"]
    assert cluster["held_together_by"] == "transitive"


def test_review_never_merges():
    # Abstention has to cost something, or it is decoration. At the shipped
    # threshold B against C is `review`, so C stays out of the cluster and
    # lands in the queue instead.
    run = dedupe(_CHAIN, entity="organisation", block=None)
    assert [c["members"] for c in run["clusters"]] == [["A", "B"], ["C"]]
    assert [(m["a_id"], m["b_id"]) for m in run["review"]] == [("B", "C")]


def test_a_list_with_nothing_in_common_is_all_singletons():
    records = [
        {"id": "x", "name": "Zenith Bank Plc"},
        {"id": "y", "name": "Dangote Cement Plc"},
        {"id": "z", "name": "Karfi Agro Cooperative Society Ltd"},
    ]
    run = dedupe(records, entity="organisation", block=None)
    assert run["cluster_count"] == 3
    assert all(c["size"] == 1 for c in run["clusters"])


def test_an_empty_list_is_answerable():
    run = dedupe([], entity="organisation", block=None)
    assert run["count"] == 0
    assert run["clusters"] == []


def test_one_record_is_its_own_cluster():
    run = dedupe([_ORGS[0]], entity="organisation", block=None)
    assert run["clusters"] == [
        {"members": ["1"], "size": 1, "held_together_by": "direct"}
    ]


# ---------------------------------------------------------------------------
# Ids
# ---------------------------------------------------------------------------


def test_duplicate_ids_are_refused_by_name():
    # Two records sharing an id is not a duplicate to be found -- it is a list
    # that cannot say which record an edge refers to. Failing loudly beats
    # emitting clusters whose members are ambiguous.
    records = [
        {"id": "same", "name": "Zenith Bank Plc"},
        {"id": "same", "name": "Dangote Cement Plc"},
    ]
    with pytest.raises(ValueError, match="duplicate id"):
        dedupe(records, entity="organisation", block=None)


def test_records_without_ids_fall_back_to_position():
    # The engine identifies a record by position when the id field is absent,
    # and dedupe has to resolve identity the same way or its ordering would
    # refer to different things than its edges do.
    records = [{"name": n} for n in (
        "Karfi Agro Cooperative Society Ltd",
        "Karfi Agro Co-operative Soc.",
        "Zenith Bank Plc",
    )]
    run = dedupe(records, entity="organisation", block=None)
    assert [c["members"] for c in run["clusters"]] == [[0, 1], [2]]


def test_an_unhashable_id_is_refused():
    records = [{"id": ["not", "hashable"], "name": "Zenith Bank Plc"}]
    with pytest.raises(ValueError, match="unhashable"):
        dedupe(records, entity="organisation", block=None)


# ---------------------------------------------------------------------------
# Provenance carries through
# ---------------------------------------------------------------------------


def test_edges_keep_their_addresses_and_the_run_keeps_its_pins():
    run = dedupe(_ORGS, entity="organisation", block=None)
    assert run["matches"][0]["decision_id"].startswith("xwd:")
    assert run["pins"]["engine"] == "crosswalk.v1"
    assert "blocking" in run


def test_dedupe_reproduces():
    first = dedupe(_ORGS, entity="organisation", block=None)
    second = dedupe(_ORGS, entity="organisation", block=None)
    assert first == second


def test_a_hand_written_comparator_list_works_positionally():
    # Same calling convention as `reconcile`, so the three verbs stay learnable
    # as one surface rather than three dialects.
    comparators = [{"field": "name", "kind": "placename", "weight": 2.0}]
    run = dedupe(_ORGS, comparators, block=None, threshold=0.6)
    assert run["count"] >= 1
