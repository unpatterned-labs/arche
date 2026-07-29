# Copyright 2026 unpatterned.org
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""H3 spatial blocking — turn an O(n·m) cross-product into O(n·k).

Reconciling two lists of *places* (facilities, addresses, clinics) naively
scores every a against every b. At a few hundred records that is already tens
of thousands of pairs; at national scale it is intractable. Blocking restricts
scoring to pairs that *could* be the same place — here, records whose captured
coordinates fall in the same H3 cell or an adjacent one (a 1-ring ``grid_disk``,
so a true match split across a cell boundary by GPS noise is still compared).

Pure Python + h3 (a base dependency). Entity-agnostic: any record carrying a
lat/lon works — Nigerian PHCs, UK postcodes, US hospitals alike.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from typing import Any

import h3


def _latlng_to_cell(lat: float, lon: float, res: int) -> str:
    """H3 cell index for a point, tolerant of the h3 v4→v3 API rename.

    h3>=4 exposes ``latlng_to_cell``; the v3 line called it ``geo_to_h3``.
    We prefer v4 (the pinned base dep) and fall back so the SDK still works
    if an older h3 is resolved in a downstream environment.
    """
    try:
        return h3.latlng_to_cell(lat, lon, res)
    except AttributeError:  # pragma: no cover - v3 fallback
        return h3.geo_to_h3(lat, lon, res)


def _grid_disk(cell: str, k: int = 1) -> list[str]:
    """Cell + its ``k``-ring neighbours (v4 ``grid_disk`` / v3 ``k_ring``)."""
    try:
        return list(h3.grid_disk(cell, k))
    except AttributeError:  # pragma: no cover - v3 fallback
        return list(h3.k_ring(cell, k))


def _coords(rec: dict, lat_field: str, lon_field: str) -> tuple[float, float] | None:
    """Extract ``(lat, lon)`` from a record, or ``None`` if absent/unparseable."""
    lat, lon = rec.get(lat_field), rec.get(lon_field)
    if lat in (None, "") or lon in (None, ""):
        return None
    try:
        return float(lat), float(lon)
    except (TypeError, ValueError):
        return None


def h3_index(
    records: Iterable[dict],
    lat_field: str = "lat",
    lon_field: str = "lon",
    res: int = 7,
) -> dict[str, list[int]]:
    """Bucket record *indices* by H3 cell at resolution ``res``.

    Returns ``{cell: [i, ...]}``. Records without usable coordinates are
    omitted (they cannot be spatially blocked); callers handle them
    separately. Resolution 7 ≈ 5 km² cells — coarse enough to survive noisy
    field coordinates, fine enough to prune hard.
    """
    index: dict[str, list[int]] = {}
    for i, rec in enumerate(records):
        pt = _coords(rec, lat_field, lon_field)
        if pt is None:
            continue
        cell = _latlng_to_cell(pt[0], pt[1], res)
        index.setdefault(cell, []).append(i)
    return index


def candidate_pairs(
    list_a: list[dict],
    list_b: list[dict],
    *,
    res: int = 7,
    lat_field: str = "lat",
    lon_field: str = "lon",
) -> Iterator[tuple[int, int]]:
    """Yield ``(i, j)`` index pairs worth scoring — same cell or 1-ring adjacent.

    A record missing coordinates cannot be excluded on geography, so it is
    paired with everything (correctness over pruning): if ``a`` has no coords
    it pairs with all of ``b``; a coordless ``b`` pairs with every ``a``. When
    every record carries coordinates this is pure same-cell+ring blocking.
    """
    b_index = h3_index(list_b, lat_field, lon_field, res)
    b_nocoord = [
        j for j, rb in enumerate(list_b)
        if _coords(rb, lat_field, lon_field) is None
    ]
    all_b = range(len(list_b))

    for i, ra in enumerate(list_a):
        pt = _coords(ra, lat_field, lon_field)
        if pt is None:
            # No geography to block on -> compare against every b.
            for j in all_b:
                yield (i, j)
            continue
        cell = _latlng_to_cell(pt[0], pt[1], res)
        seen: set[int] = set()
        for ring_cell in _grid_disk(cell, 1):
            for j in b_index.get(ring_cell, ()):
                if j not in seen:
                    seen.add(j)
                    yield (i, j)
        for j in b_nocoord:  # coordless b's can't be excluded
            if j not in seen:
                seen.add(j)
                yield (i, j)


def blocking_recall(
    truth_pairs: Iterable[tuple[Any, Any]],
    candidate_pairs: Iterable[tuple[Any, Any]],
) -> float:
    """Fraction of true-match pairs the blocker kept (recall of the block step).

    The one metric that matters for a blocker: a pair the blocker drops can
    never be recovered downstream. Compares as unordered sets of ``(a, b)``
    keys (ids or indices — the caller's choice, but both arguments must use the
    same key space). Returns 1.0 when ``truth_pairs`` is empty (nothing to miss).
    """
    truth = {tuple(p) for p in truth_pairs}
    if not truth:
        return 1.0
    cands = {tuple(p) for p in candidate_pairs}
    kept = sum(1 for p in truth if p in cands)
    return kept / len(truth)
