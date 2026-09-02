# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""reconcile(): the distinctive-signal gate, tftoken, H3 blocking, rerank, and
a UK-address generality check proving the engine is not Africa-specific."""

import json

import pytest
from arche.resolve import TokenFrequencyTable, reconcile

# ── the distinctive-signal gate (ported from the MCP handler) ────────────────

def test_gate_blocks_merge_without_distinctive_signal():
    # Same spot, orthographic name variant is a true match; a *different*
    # facility at the same spot scores above threshold but the weak name keeps
    # its distinctive signal under the floor -> review, never match.
    a = [{"id": "A1", "name": "Kigbe Dispensary",
          "address": "Ungwan Rimi, Kaduna", "lat": 10.5200, "lon": 7.4400}]
    b = [
        {"id": "B1", "name": "Kigbe Dispensary",
         "address": "Anguwan Rimi, Kaduna", "lat": 10.5205, "lon": 7.4405},
        {"id": "B2", "name": "Central Mosque",
         "address": "Anguwan Rimi, Kaduna", "lat": 10.5205, "lon": 7.4405},
    ]
    comps = [
        {"field": "name", "kind": "name", "weight": 2.0},
        {"field": "address", "kind": "address", "weight": 1.5},
        {"kind": "geo", "lat": "lat", "lon": "lon", "weight": 1.0},
    ]
    out = reconcile(a, b, comps, threshold=0.6, block="h3")
    by_pair = {(m["a_id"], m["b_id"]): m for m in out["matches"]}
    assert by_pair[("A1", "B1")]["decision"] == "match"
    assert by_pair[("A1", "B1")]["distinctive_max"] >= 0.75
    assert by_pair[("A1", "B2")]["decision"] == "review"
    assert by_pair[("A1", "B2")]["distinctive_max"] < 0.75


_CONTAINMENT_COMPS = [
    {"field": "name", "kind": "name", "weight": 2.0},
    {"kind": "geo", "lat": "lat", "lon": "lon", "weight": 1.0},
    {"kind": "containment", "field": "admin_path", "weight": 1.0},
]
_KANO_ANCHOR = [{"id": "A", "name": "General Hospital",
                 "admin_path": {"admin1": "Kano", "admin2": "Nassarawa"},
                 "lat": 12.00, "lon": 8.50}]


def test_containment_conflict_routes_to_review():
    # OTHER sits 1.2 km away, comfortably outside the 1 km boundary-uncertainty
    # band, so its state disagreement is real evidence rather than a boundary
    # artefact. Its score (0.612) clears the 0.6 threshold on name and geo
    # alone, which is the point: only the containment conflict can demote it,
    # so this test still proves the conflict is what routes it to review.
    b = [
        {"id": "SAME", "name": "General Hospital",
         "admin_path": {"admin1": "Kano", "admin2": "Nassarawa"},
         "lat": 12.001, "lon": 8.50},
        {"id": "OTHER", "name": "General Hospital",
         "admin_path": {"admin1": "Lagos", "admin2": "Ikeja"},
         "lat": 12.0108, "lon": 8.50},
    ]
    out = reconcile(_KANO_ANCHOR, b, _CONTAINMENT_COMPS, threshold=0.6,
                    block="h3")
    by_pair = {(m["a_id"], m["b_id"]): m for m in out["matches"]}
    assert by_pair[("A", "SAME")]["decision"] == "match"
    other = by_pair[("A", "OTHER")]
    assert other["score"] > 0.6           # would be a match on name+geo alone
    assert other["evidence"]["admin_path"] == 0.0
    assert other["decision"] == "review"  # the conflict is what demotes it


def test_containment_conflict_at_the_same_point_does_not_route_to_review():
    # The counterpart, and the behaviour change this pins. Two records at
    # IDENTICAL coordinates in "different states" is a statement about a
    # boundary file, not about identity: there is no distance for the
    # disagreement to be about. Refutation is withheld, so the pair is decided
    # on its other evidence rather than being demoted on the admin label.
    b = [{"id": "OTHER", "name": "General Hospital",
          "admin_path": {"admin1": "Lagos", "admin2": "Ikeja"},
          "lat": 12.00, "lon": 8.50}]
    out = reconcile(_KANO_ANCHOR, b, _CONTAINMENT_COMPS, threshold=0.6,
                    block="h3")
    edge = {(m["a_id"], m["b_id"]): m for m in out["matches"]}[("A", "OTHER")]
    assert edge["evidence"]["distance_km"] == 0.0
    # Scored as "no evidence", never as agreement: below the 0.3 a genuinely
    # shared admin1 earns, so nothing was manufactured.
    assert 0.0 < edge["evidence"]["admin_path"] < 0.3
    assert edge["decision"] == "match"


def test_evidence_carries_no_raw_values():
    a = [{"id": "A1", "name": "Fatima Abdullahi", "phone": "+2348031234567"}]
    b = [{"id": "B1", "name": "Fatima Abdullahi", "phone": "08031234567"}]
    comps = [{"field": "name", "kind": "name", "weight": 1.0},
             {"field": "phone", "kind": "phone", "weight": 1.0}]
    out = reconcile(a, b, comps, threshold=0.7, block=None)
    assert "Fatima Abdullahi" not in json.dumps(out)
    assert out["matches"][0]["decision"] == "match"


def test_external_candidates_are_scored_and_pinned_into_decisions():
    """A retriever may propose pairs, but arche still owns the decision."""
    a = [{"id": "supplier-7", "name": "Eiffel Tower Summit Tour"}]
    b = [
        {"id": "offer-1", "name": "Eiffel Tower Summit Tour"},
        {"id": "offer-2", "name": "Louvre Museum Entry"},
    ]
    candidates = [{
        "a_id": "supplier-7",
        "b_id": "offer-1",
        "route": "title-vector-v3",
        "retrieval_score": 0.981,
    }]
    pins = {
        "provider": "warehouse-vector-search",
        "index": "travel-title@sha256:abc123",
        "filters": {"city": "Paris"},
        "top_k": 20,
    }
    out = reconcile(
        a, b, [{"field": "name", "kind": "name", "weight": 1.0}],
        threshold=0.7,
        candidate_pairs=candidates,
        candidate_pins=pins,
    )

    assert out["blocking"] == {
        "candidate_pairs": 1,
        "reduction_ratio": 0.5,
        "strategies": {"external": 1},
    }
    assert out["pins"]["block"] == "external"
    assert out["pins"]["candidate_provider"] == pins
    edge = out["matches"][0]
    assert edge["candidate"] == {
        "route": "title-vector-v3", "retrieval_score": 0.981,
    }
    assert edge["decision"] == "match"
    assert edge["decision_id"].startswith("xwd:sha256:")

    changed_index = reconcile(
        a, b, [{"field": "name", "kind": "name", "weight": 1.0}],
        threshold=0.7,
        candidate_pairs=candidates,
        candidate_pins={**pins, "index": "travel-title@sha256:def456"},
    )
    assert changed_index["matches"][0]["decision_id"] != edge["decision_id"]


def test_external_candidates_require_pinned_retrieval_provenance():
    a = [{"id": "a", "name": "Karfi Clinic"}]
    b = [{"id": "b", "name": "Karfi Clinic"}]
    with pytest.raises(ValueError, match="candidate_pins"):
        reconcile(
            a, b, [{"field": "name", "kind": "name", "weight": 1.0}],
            candidate_pairs=[{"a_id": "a", "b_id": "b"}],
        )

    with pytest.raises(ValueError, match="candidate_pairs"):
        reconcile(
            a, b, [{"field": "name", "kind": "name", "weight": 1.0}],
            candidate_pins={"provider": "retriever"},
        )


# ── the tftoken comparator ───────────────────────────────────────────────────

def test_tftoken_weights_rare_overlap_over_common_and_gates_partial_merges():
    # "central" is common across the corpus, "karfi" is rare. Sharing "karfi"
    # is stronger evidence than sharing "central" (higher score); and neither
    # PARTIAL overlap manufactures an auto-merge — the distinctive-token gate
    # keeps a shared-street-name-only pair out of "match".
    corpus_names = [
        "Karfi PHC", "Central PHC", "Central Clinic", "Central Hospital",
        "Central Health Post", "Central Dispensary", "Rimi Clinic",
    ]
    tf = TokenFrequencyTable.from_corpus(corpus_names)
    a = [{"id": "A_rare", "name": "Karfi PHC"},
         {"id": "A_common", "name": "Central PHC"}]
    b = [{"id": "B_rare", "name": "Karfi Clinic"},
         {"id": "B_common", "name": "Central Clinic"}]
    comps = [{"field": "name", "kind": "tftoken", "weight": 1.0}]
    out = reconcile(a, b, comps, threshold=0.5, review_margin=0.5, tf=tf, block=None)
    by_pair = {(m["a_id"], m["b_id"]): m for m in out["matches"]}
    # TF weighting: shared rare token scores strictly higher than shared common.
    assert by_pair[("A_rare", "B_rare")]["score"] > by_pair[("A_common", "B_common")]["score"]
    # Neither partial overlap auto-merges: the gate stops a shared name fragment
    # from manufacturing a match.
    assert by_pair[("A_rare", "B_rare")]["decision"] != "match"
    assert by_pair[("A_common", "B_common")]["decision"] != "match"


def test_tftoken_exact_rare_overlap_matches():
    # A complete overlap on a distinctive name IS a match — the gate passes
    # because the tftoken similarity (distinctive) reaches the floor.
    tf = TokenFrequencyTable.from_corpus(
        ["Karfi Dispensary", "Central PHC", "Rimi Clinic", "General Hospital"]
    )
    a = [{"id": "A", "name": "Karfi Dispensary"}]
    b = [{"id": "B", "name": "Karfi Dispensary"}]
    comps = [{"field": "name", "kind": "tftoken", "weight": 1.0}]
    out = reconcile(a, b, comps, threshold=0.7, tf=tf, block=None)
    assert out["matches"][0]["decision"] == "match"
    assert out["matches"][0]["distinctive_max"] >= 0.75


def test_tftoken_requires_a_table_in_the_engine():
    # Pins the ENGINE's contract, and now says so. `arche.resolve.reconcile`
    # used to be this function; it is now the facade above it, which CAN answer
    # this case by self-calibrating a table over the two lists. The engine
    # cannot -- it has no such machinery -- so it refuses, and that refusal is
    # what this test is for. Reaching it through the module path is the
    # difference, and stating it here keeps the two contracts distinguishable.
    from arche.resolve.reconcile import reconcile as engine

    a = [{"id": "A", "name": "Karfi PHC"}]
    b = [{"id": "B", "name": "Karfi PHC"}]
    comps = [{"field": "name", "kind": "tftoken", "weight": 1.0}]
    with pytest.raises(ValueError, match="tftoken"):
        engine(a, b, comps, block=None)  # tf omitted


def test_the_facade_self_calibrates_and_says_so_in_the_pin():
    # The other half of the contract. Self-calibrating over the two lists is
    # the designed path for a corpus-specific vocabulary -- a product catalogue
    # has no population table to ship -- so the facade does it rather than
    # refusing. What makes that safe is not a guard but disclosure: the table
    # arche chose is named in the pins, and the pins are hashed into every
    # edge's `decision_id`. A reader of the receipt can see which table scored
    # it, and a different table yields a different address.
    a = [{"id": "A", "name": "Karfi PHC"}]
    b = [{"id": "B", "name": "Karfi PHC"}]
    comps = [{"field": "name", "kind": "tftoken", "weight": 1.0}]
    pins = reconcile(a, b, comps, block=None)["pins"]
    assert pins["tf"].startswith("self-calibrated@sha256:")


# ── H3 blocking ──────────────────────────────────────────────────────────────

def test_blocking_reduces_candidate_pairs_and_reports_ratio():
    # Two 3-record lists in three separated locations. Full cross-product is 9;
    # blocking should only score the co-located pairs and report the reduction.
    locs = [(6.5244, 3.3792), (9.0765, 7.3986), (-1.2921, 36.8219)]  # Lagos, Abuja, Nairobi
    a = [{"id": f"a{i}", "name": f"Site {i}", "lat": lat, "lon": lon}
         for i, (lat, lon) in enumerate(locs)]
    b = [{"id": f"b{i}", "name": f"Site {i}", "lat": lat, "lon": lon}
         for i, (lat, lon) in enumerate(locs)]
    comps = [{"field": "name", "kind": "name", "weight": 1.0},
             {"kind": "geo", "lat": "lat", "lon": "lon", "weight": 1.0}]

    blocked = reconcile(a, b, comps, threshold=0.6, block="h3")
    full = reconcile(a, b, comps, threshold=0.6, block=None)

    assert blocked["blocking"]["candidate_pairs"] == 3   # only co-located pairs
    assert full["blocking"]["candidate_pairs"] == 9      # 3 * 3
    assert blocked["blocking"]["reduction_ratio"] > 0.6
    assert full["blocking"]["reduction_ratio"] == 0.0


# ── the block-aware reranker ─────────────────────────────────────────────────

def test_rerank_sharpens_discriminated_pairs():
    # Within a block of "Karfi" candidates, the reranker should not lift the
    # wrong candidate above the right one.
    corpus = ["Karfi PHC", "Karfi PHC", "Bunkure PHC"]
    tf = TokenFrequencyTable.from_corpus(corpus)
    a = [{"id": "A", "name": "Karfi PHC", "lat": 11.5, "lon": 8.4}]
    b = [
        {"id": "B_right", "name": "Karfi PHC", "lat": 11.5001, "lon": 8.4},
        {"id": "B_wrong", "name": "Bunkure PHC", "lat": 11.5002, "lon": 8.4},
    ]
    comps = [{"field": "name", "kind": "tftoken", "weight": 1.0}]
    out = reconcile(a, b, comps, threshold=0.5, tf=tf, block="h3", rerank=True)
    by_pair = {(m["a_id"], m["b_id"]): m for m in out["matches"]}
    assert by_pair[("A", "B_right")]["score"] > by_pair.get(
        ("A", "B_wrong"), {"score": 0.0}
    )["score"]


# ── UK generality: NOT Africa-specific ───────────────────────────────────────

def test_uk_addresses_distinct_houses_do_not_merge():
    """Two houses on the same UK street must not merge without a distinctive
    match. Proves the engine is entity-/geography-agnostic: no African name
    lexicon, no NIN/BVN — just addresses and term-frequency weighting."""
    a = [{"id": "downing_10", "addr": "10 Downing Street, London, SW1A 2AA"}]
    b = [
        {"id": "downing_10b", "addr": "10 Downing Street, London SW1A 2AA"},
        {"id": "downing_11", "addr": "11 Downing Street, London, SW1A 2AA"},
    ]
    # Build the TF table over both lists so the shared street/postcode tokens
    # are seen as common and the house number carries the distinctiveness.
    tf = TokenFrequencyTable.from_corpus(
        [r["addr"] for r in a] + [r["addr"] for r in b]
    )
    comps = [{"field": "addr", "kind": "tftoken", "weight": 1.0}]
    out = reconcile(a, b, comps, threshold=0.7, tf=tf, block=None)
    by_pair = {(m["a_id"], m["b_id"]): m for m in out["matches"]}

    # Same house (number 10, minor punctuation variant) -> match.
    assert by_pair[("downing_10", "downing_10b")]["decision"] == "match"
    # Different house on the same street -> the shared street/postcode is not
    # enough; the distinctive-signal gate keeps it out of "match".
    assert by_pair[("downing_10", "downing_11")]["decision"] != "match"


def test_uk_rerank_pushes_wrong_house_below_right_house():
    a = [{"id": "d10", "addr": "10 Downing Street London SW1A 2AA"}]
    b = [
        {"id": "d10b", "addr": "10 Downing Street London SW1A 2AA"},
        {"id": "d11", "addr": "11 Downing Street London SW1A 2AA"},
    ]
    tf = TokenFrequencyTable.from_corpus(
        [r["addr"] for r in a] + [r["addr"] for r in b]
    )
    comps = [{"field": "addr", "kind": "tftoken", "weight": 1.0}]
    out = reconcile(a, b, comps, threshold=0.7, tf=tf, block=None, rerank=True)
    by_pair = {(m["a_id"], m["b_id"]): m for m in out["matches"]}
    # The block-discriminating house number "10" (present in d10b, absent in
    # d11) punishes the wrong pair below the right one.
    right = by_pair[("d10", "d10b")]["score"]
    wrong = by_pair.get(("d10", "d11"), {"score": 0.0})["score"]
    assert right > wrong
