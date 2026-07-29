# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""H3 spatial blocking: indexing, candidate generation, reduction, recall."""

import math

from arche.resolve._block import (
    blocking_recall,
    candidate_pairs,
    h3_index,
)


def test_h3_index_buckets_nearby_points_together():
    # Two points ~20 m apart (same res-7 cell) and one ~far away.
    recs = [
        {"lat": 6.5244, "lon": 3.3792},   # Lagos
        {"lat": 6.5246, "lon": 3.3794},   # Lagos, next door
        {"lat": -1.2921, "lon": 36.8219},  # Nairobi
    ]
    index = h3_index(recs, "lat", "lon", res=7)
    cells = list(index.values())
    # Lagos pair share a cell; Nairobi is alone.
    assert any(sorted(c) == [0, 1] for c in cells)
    assert any(c == [2] for c in cells)


def test_h3_index_skips_records_without_coords():
    recs = [{"lat": 6.5, "lon": 3.3}, {"name": "no coords"}]
    index = h3_index(recs, "lat", "lon", res=7)
    kept = [i for members in index.values() for i in members]
    assert kept == [0]


def test_candidate_pairs_prunes_far_apart_records():
    # a near Lagos, b split between Lagos and Nairobi. Only the Lagos b is a
    # candidate; the Nairobi b is pruned.
    a = [{"id": "a", "lat": 6.5244, "lon": 3.3792}]
    b = [
        {"id": "b_lagos", "lat": 6.5246, "lon": 3.3794},
        {"id": "b_nairobi", "lat": -1.2921, "lon": 36.8219},
    ]
    pairs = list(candidate_pairs(a, b, res=7))
    assert (0, 0) in pairs           # a vs b_lagos kept
    assert (0, 1) not in pairs       # a vs b_nairobi pruned


def test_candidate_pairs_keeps_boundary_neighbours_via_ring():
    # Points a few hundred metres apart may land in adjacent cells; the 1-ring
    # grid_disk must still pair them (GPS noise across a cell boundary).
    a = [{"lat": 6.5244, "lon": 3.3792}]
    b = [{"lat": 6.5290, "lon": 3.3840}]  # ~700 m away
    pairs = list(candidate_pairs(a, b, res=7))
    assert (0, 0) in pairs


def test_candidate_pairs_coordless_record_pairs_with_all():
    # A record without coordinates can't be excluded on geography.
    a = [{"name": "no coords"}]
    b = [{"lat": 6.5, "lon": 3.3}, {"lat": -1.2, "lon": 36.8}]
    pairs = list(candidate_pairs(a, b, res=7))
    assert set(pairs) == {(0, 0), (0, 1)}


def test_candidate_pairs_reduction_on_scale_set():
    # SCALE STORY: 300 records per side across 30 well-separated clusters.
    # Blocking must cut the 90,000-pair cross-product by an order of magnitude.
    n_clusters = 30
    per_cluster = 10
    # Spread cluster centres across a wide lat/lon grid so no two clusters
    # share an H3 res-7 cell or ring.
    centers = [(-30.0 + 4.0 * k, -20.0 + 5.0 * k) for k in range(n_clusters)]
    list_a, list_b = [], []
    for c, (clat, clon) in enumerate(centers):
        for p in range(per_cluster):
            # jitter ~10 m so members of a cluster share a cell
            jit = 0.0001 * p
            list_a.append({"id": f"a{c}_{p}", "lat": clat + jit, "lon": clon + jit})
            list_b.append({"id": f"b{c}_{p}", "lat": clat + jit, "lon": clon - jit})

    full = len(list_a) * len(list_b)  # 300 * 300 = 90_000
    pairs = list(candidate_pairs(list_a, list_b, res=7))
    reduction = 1.0 - len(pairs) / full

    assert full == 90_000
    # Cross-cluster pairs are pruned; only within-cluster pairs survive.
    # Ideal is ~30 clusters * 10*10 = 3_000 pairs -> ~0.967 reduction.
    assert len(pairs) < 6_000
    assert reduction > 0.9


def test_blocking_recall_reports_missed_pairs():
    truth = [("a", "b1"), ("a", "b2"), ("a", "b3")]
    kept = [("a", "b1"), ("a", "b3"), ("a", "b99")]
    assert blocking_recall(truth, kept) == 2 / 3
    assert blocking_recall([], kept) == 1.0
    assert blocking_recall(truth, []) == 0.0


def test_blocking_recall_on_scale_set_is_perfect_for_true_matches():
    # The same-cluster same-index pairs are the true matches; blocking keeps
    # every one of them (recall 1.0) while pruning the cross-cluster noise.
    n_clusters, per_cluster = 20, 5
    centers = [(-20.0 + 5.0 * k, 0.0 + 6.0 * k) for k in range(n_clusters)]
    list_a, list_b = [], []
    truth = []
    for c, (clat, clon) in enumerate(centers):
        for p in range(per_cluster):
            jit = 0.0001 * p
            ai, bi = len(list_a), len(list_b)
            list_a.append({"id": f"a{c}_{p}", "lat": clat + jit, "lon": clon})
            list_b.append({"id": f"b{c}_{p}", "lat": clat + jit, "lon": clon})
            truth.append((ai, bi))
    pairs = list(candidate_pairs(list_a, list_b, res=7))
    assert math.isclose(blocking_recall(truth, pairs), 1.0)
