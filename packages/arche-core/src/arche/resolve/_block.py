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

"""Blocking — turn an O(n·m) cross-product into O(n·k) without dropping truths.

Reconciling two lists naively scores every a against every b. Blocking
restricts scoring to pairs that *could* co-refer. A dropped true pair is
unrecoverable downstream, so recall is the only metric a blocker is judged on
(:func:`blocking_recall`).

Three OR-able strategies (union them — each catches what the others miss):

* **H3 spatial** (:func:`candidate_pairs`): same cell or 1-ring adjacent at
  res 7 (~5 km² cells), plus a coarser ``safety_res`` ring so a true match
  whose field-captured coordinates sit kilometres apart is still compared.
* **Rare-token** (:func:`token_candidate_pairs`): records sharing an
  uncommon text token ("Karfi", a plot number) are compared regardless of
  distance — the recall channel for GPS-discordant true matches and for
  records with no coordinates at all. Common tokens ("clinic") are skipped
  via a hard pair-budget cap, so cost stays bounded.
* **Shared-id** (:func:`id_candidate_pairs`): exact normalised agreement on
  an identifier field always earns a comparison.

Pure Python + h3 (a base dependency). Entity-agnostic: any record carrying a
lat/lon or text works — Nigerian PHCs, UK postcodes, US hospitals alike.
"""

from __future__ import annotations

import re
import unicodedata
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
    safety_res: int | None = None,
    pair_coordless_with_all: bool = True,
) -> Iterator[tuple[int, int]]:
    """Yield ``(i, j)`` index pairs worth scoring — same cell or 1-ring adjacent.

    ``safety_res`` adds a second, coarser ring (e.g. 6): pairs adjacent at
    *either* resolution are kept. Res-7 1-ring recall on true pairs collapses
    beyond ~2 km of GPS offset; the res-6 net holds it to roughly 10 km.

    A record missing coordinates cannot be excluded on geography. With
    ``pair_coordless_with_all=True`` (the standalone default) it is paired
    with everything — correctness over pruning, at O(n·m) cost for those
    records. Union blocking passes ``False`` and covers coordless records via
    the token/id keys instead; callers report the coordless count loudly
    either way.
    """
    resolutions = [res] if safety_res is None else [res, safety_res]
    b_indexes = {r: h3_index(list_b, lat_field, lon_field, r) for r in resolutions}
    b_nocoord = [
        j for j, rb in enumerate(list_b)
        if _coords(rb, lat_field, lon_field) is None
    ]
    all_b = range(len(list_b))

    for i, ra in enumerate(list_a):
        pt = _coords(ra, lat_field, lon_field)
        if pt is None:
            if pair_coordless_with_all:
                # No geography to block on -> compare against every b.
                for j in all_b:
                    yield (i, j)
            continue
        seen: set[int] = set()
        for r in resolutions:
            cell = _latlng_to_cell(pt[0], pt[1], r)
            for ring_cell in _grid_disk(cell, 1):
                for j in b_indexes[r].get(ring_cell, ()):
                    if j not in seen:
                        seen.add(j)
                        yield (i, j)
        if pair_coordless_with_all:
            for j in b_nocoord:  # coordless b's can't be excluded
                if j not in seen:
                    seen.add(j)
                    yield (i, j)


_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _norm_tokens(text: Any) -> set[str]:
    """Lowercased, diacritics-folded word tokens of a value."""
    folded = unicodedata.normalize("NFKD", str(text).lower())
    folded = "".join(c for c in folded if not unicodedata.combining(c))
    return set(_TOKEN_RE.findall(folded))


def _token_index(records: list[dict], fields: Iterable[str]) -> dict[str, list[int]]:
    index: dict[str, list[int]] = {}
    for i, rec in enumerate(records):
        tokens: set[str] = set()
        for f in fields:
            value = rec.get(f)
            if value not in (None, ""):
                tokens |= _norm_tokens(value)
        for tok in tokens:
            index.setdefault(tok, []).append(i)
    return index


def _cooccurrence_index(
    records: list[dict], fields: Iterable[str], tokens: set[str]
) -> dict[tuple[str, str], list[int]]:
    """Index records by every unordered pair of their *over-common* tokens.

    Only tokens in ``tokens`` participate, because a record holding even one
    token under the cost bound is already reachable through it and does not need
    a second key. Sorted, so ``jackson|nicholas`` is one key however the name
    was written.
    """
    fields = tuple(fields)
    index: dict[tuple[str, str], list[int]] = {}
    for i, rec in enumerate(records):
        present: set[str] = set()
        for f in fields:
            value = rec.get(f)
            if value not in (None, ""):
                present |= _norm_tokens(value) & tokens
        if len(present) < 2:
            continue
        ordered = sorted(present)
        for x in range(len(ordered)):
            for y in range(x + 1, len(ordered)):
                index.setdefault((ordered[x], ordered[y]), []).append(i)
    return index


def token_candidate_pairs(
    list_a: list[dict],
    list_b: list[dict],
    fields: Iterable[str],
    *,
    pair_cap: int = 1000,
) -> Iterator[tuple[int, int]]:
    """Yield pairs sharing a *rare* token in any of ``fields``.

    Rarity is enforced as a cost bound, not a frequency guess: a token whose
    occurrences would contribute more than ``pair_cap`` pairs (``count_a x
    count_b``) is too common to block on ("clinic", "primary") and is skipped.
    Distance never enters — this is the recall channel for true matches whose
    coordinates disagree by kilometres, and for records with no coordinates.
    May yield duplicates across tokens; union callers dedupe.
    """
    fields = tuple(fields)
    index_a = _token_index(list_a, fields)
    index_b = _token_index(list_b, fields)
    too_common: set[str] = set()
    for tok, a_ids in index_a.items():
        b_ids = index_b.get(tok)
        if not b_ids:
            continue
        if len(a_ids) * len(b_ids) > pair_cap:
            too_common.add(tok)
            continue
        for i in a_ids:
            for j in b_ids:
                yield (i, j)

    # Conjunctions, for the records the loop above cannot key at all.
    #
    # A token over the cost bound is skipped, which is right on its own: no one
    # wants to block on "clinic". But a record whose tokens are *all* over the
    # bound then gets no key, and is never compared with anything. On a register
    # of 50k UK people that silently dropped 27,055 true pairs whose names were
    # character-for-character identical: `nicholas jackson` twice over, same date
    # of birth, never proposed, because `nicholas` and `jackson` are each too
    # common to block on. The rare-token blocker was discarding exactly the
    # common-name case the rest of the engine exists to adjudicate.
    #
    # Two common tokens together are not common. `nicholas`+`jackson` is rare
    # even where both halves are ordinary, which is why every mature blocking
    # scheme keys on conjunctions. The same cost bound then applies to the pair
    # key, so nothing unbounded is admitted.
    if not too_common:
        return
    pair_a = _cooccurrence_index(list_a, fields, too_common)
    pair_b = _cooccurrence_index(list_b, fields, too_common)
    for key, a_ids in pair_a.items():
        b_ids = pair_b.get(key)
        if not b_ids or len(a_ids) * len(b_ids) > pair_cap:
            continue
        for i in a_ids:
            for j in b_ids:
                yield (i, j)


def _norm_id_value(value: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value).lower())


def id_candidate_pairs(
    list_a: list[dict],
    list_b: list[dict],
    fields: Iterable[str],
) -> Iterator[tuple[int, int]]:
    """Yield pairs agreeing exactly (normalised) on any identifier field.

    A shared registry id is the strongest possible blocking key: such a pair
    must always reach the comparators, whatever the map says.
    """
    fields = tuple(fields)
    index_b: dict[str, list[int]] = {}
    for j, rec in enumerate(list_b):
        for f in fields:
            value = rec.get(f)
            if value in (None, ""):
                continue
            key = _norm_id_value(value)
            if key:
                index_b.setdefault(key, []).append(j)
    for i, rec in enumerate(list_a):
        for f in fields:
            value = rec.get(f)
            if value in (None, ""):
                continue
            for j in index_b.get(_norm_id_value(value), ()):
                yield (i, j)


def union_candidate_pairs(
    list_a: list[dict],
    list_b: list[dict],
    *,
    lat_field: str = "lat",
    lon_field: str = "lon",
    text_fields: Iterable[str] = (),
    id_fields: Iterable[str] = (),
    res: int = 7,
    safety_res: int | None = 6,
    pair_cap: int = 1000,
) -> tuple[list[tuple[int, int]], dict[str, int]]:
    """OR of the three blocking keys, deduped: H3 ∪ rare-token ∪ shared-id.

    Returns ``(pairs, info)`` where ``info`` reports how many *new* pairs each
    strategy contributed (in application order: h3, token, id) plus the
    coordless record counts — the honesty numbers a run report needs. Coordless
    records are covered by the token/id keys here, never by a silent
    cross-product.
    """
    seen: set[tuple[int, int]] = set()

    def _absorb(pairs: Iterator[tuple[int, int]]) -> int:
        added = 0
        for p in pairs:
            if p not in seen:
                seen.add(p)
                added += 1
        return added

    n_h3 = _absorb(candidate_pairs(
        list_a, list_b, res=res, lat_field=lat_field, lon_field=lon_field,
        safety_res=safety_res, pair_coordless_with_all=False,
    ))
    text_fields = tuple(text_fields)
    id_fields = tuple(id_fields)
    n_token = _absorb(token_candidate_pairs(
        list_a, list_b, text_fields, pair_cap=pair_cap,
    )) if text_fields else 0
    n_id = _absorb(id_candidate_pairs(list_a, list_b, id_fields)) if id_fields else 0

    info = {
        "h3": n_h3,
        "token": n_token,
        "id": n_id,
        "coordless_a": sum(
            1 for r in list_a if _coords(r, lat_field, lon_field) is None
        ),
        "coordless_b": sum(
            1 for r in list_b if _coords(r, lat_field, lon_field) is None
        ),
    }
    return sorted(seen), info


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
