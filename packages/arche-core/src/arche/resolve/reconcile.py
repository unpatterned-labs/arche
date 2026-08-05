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

"""Reconcile two record lists — the place/entity crosswalk engine.

Given two independently-maintained lists (a facility registry vs a survey, two
address books, a UK gazetteer vs a delivery file) find which records refer to
the same real-world thing. This is the composable core that used to live inside
the MCP ``compare_records`` handler, lifted into ``arche-core`` so the SDK, the
API, and the MCP server share one implementation.

Three ideas make it more than a nested loop:

* **Distinctive-signal gate.** A pair can only be ``match`` if a *distinctive*
  comparator (name / id / TF-token) clears ``distinctive_floor``. Supporting
  signals (geo proximity, admin containment, address) amplify but never
  manufacture a merge — a shared coordinate with a weak name lands in
  ``review``, never ``match``.
* **Term-frequency weighting** via the ``"tftoken"`` comparator kind: agreement
  on a *rare* token counts far more than agreement on a common one
  ("Karfi" >> "Central"), computed over the lists being reconciled.
* **H3 blocking** (``block="h3"``) turns the O(n·m) cross-product into O(n·k) by
  only scoring records in the same spatial neighbourhood — with a reported
  ``reduction_ratio`` — and an optional **block-aware reranker** that lets the
  token that discriminates *within a block* decide close calls.

Entity-agnostic by construction: nothing here knows about Africa, health
facilities, or any schema. You bring the comparators.
"""

from __future__ import annotations

from typing import Any

from arche.resolve._block import candidate_pairs as _h3_candidate_pairs
from arche.resolve._gate import DISTINCTIVE_FLOOR
from arche.resolve._matcher import (
    compare_addresses,
    compare_containment,
    compare_dates,
    compare_emails,
    compare_geo,
    compare_ids,
    compare_names,
    compare_phones,
)
from arche.resolve._rerank import rerank_score
from arche.resolve._tokenfreq import TokenFrequencyTable

# Simple single-value comparators keyed by comparator ``kind``.
_FIELD_COMPARATORS = {
    "name": lambda a, b: compare_names(a, b)[0],
    "phone": compare_phones,
    "id": compare_ids,
    "email": compare_emails,
    "address": compare_addresses,
    # Same comparator pairwise and in crosswalk — a kind vocabulary that means
    # different things on two paths is exactly the confusion the declaration
    # layer exists to remove.
    "date": compare_dates,
}

# Comparator kinds whose fields carry free text worth reranking on.
_TEXT_KINDS = ("tftoken", "name", "address")

_DISTINCTIVE_KINDS = ("name", "id", "tftoken")


def _field_sim(
    spec: dict[str, Any],
    ra: dict,
    rb: dict,
    tf: TokenFrequencyTable | None,
) -> float | None:
    """One comparator's similarity for a record pair, or ``None`` if inapplicable.

    ``None`` means "this comparator has nothing to say about this pair" (a field
    is missing on either side, or a structural comparator found no data) — it is
    dropped from the weighted mean rather than scored as a disagreement.
    """
    kind = spec["kind"]
    if kind == "geo":
        lat, lon = spec.get("lat", "lat"), spec.get("lon", "lon")
        if all(k in ra and k in rb for k in (lat, lon)):
            try:
                return compare_geo(
                    float(ra[lat]), float(ra[lon]), float(rb[lat]), float(rb[lon]),
                    decay_km=float(spec.get("decay_km", 1.5)),
                )
            except (TypeError, ValueError):
                return None
        return None
    if kind == "containment":
        field = spec.get("field", "admin_path")
        return compare_containment(ra.get(field), rb.get(field))
    if kind == "tftoken":
        if tf is None:
            raise ValueError(
                "comparator kind 'tftoken' requires a TokenFrequencyTable "
                "passed as tf=; build one with "
                "TokenFrequencyTable.from_corpus(...) or pass tf=\"default\""
            )
        field = spec["field"]
        if ra.get(field) in (None, "") or rb.get(field) in (None, ""):
            return None
        return tf.weighted_token_sim(str(ra[field]), str(rb[field]))
    field = spec["field"]
    if ra.get(field) in (None, "") or rb.get(field) in (None, ""):
        return None
    fn = _FIELD_COMPARATORS.get(kind)
    if fn is None:
        return None
    return fn(str(ra[field]), str(rb[field]))


def _score_pair(
    ra: dict,
    rb: dict,
    comparators: list[dict],
    tf: TokenFrequencyTable | None,
    distinctive_kinds: tuple[str, ...],
) -> tuple[float, float, bool, dict[str, float]] | None:
    """Weighted-mean similarity for one pair.

    Returns ``(score, distinctive_max, containment_conflict, evidence)`` or
    ``None`` when no comparator applied (nothing to compare).
    """
    num = den = 0.0
    distinctive_max = 0.0
    containment_conflict = False
    evidence: dict[str, float] = {}
    for spec in comparators:
        sim = _field_sim(spec, ra, rb, tf)
        if sim is None:
            continue
        weight = float(spec.get("weight", 1.0))
        num += weight * sim
        den += weight
        # Unique evidence keys: two comparators on one field (e.g. name +
        # tftoken) must not overwrite each other — that hid the fuzzy name
        # similarity behind the tftoken value in place-pack output.
        key = spec.get("field", spec["kind"])
        if key in evidence:
            key = f"{key}_{spec['kind']}"
        evidence[key] = round(sim, 3)
        if spec["kind"] in distinctive_kinds:
            distinctive_max = max(distinctive_max, sim)
        if spec["kind"] == "containment" and sim == 0.0:
            containment_conflict = True
    if den == 0:
        return None
    return num / den, distinctive_max, containment_conflict, evidence


def _geo_fields(comparators: list[dict]) -> tuple[str, str]:
    """Lat/lon field names for blocking, taken from the geo comparator if any."""
    for spec in comparators:
        if spec.get("kind") == "geo":
            return spec.get("lat", "lat"), spec.get("lon", "lon")
    return "lat", "lon"


def _rerank_text(record: dict, text_fields: tuple[str, ...]) -> str:
    """Concatenate a record's text-comparator field values for reranking."""
    return " ".join(str(record[f]) for f in text_fields if record.get(f))


def reconcile(
    list_a: list[dict],
    list_b: list[dict],
    comparators: list[dict],
    *,
    threshold: float = 0.7,
    review_margin: float = 0.15,
    id_field: str = "id",
    distinctive_kinds: tuple[str, ...] = _DISTINCTIVE_KINDS,
    distinctive_floor: float = DISTINCTIVE_FLOOR,
    tf: TokenFrequencyTable | str | None = None,
    block: str | None = "h3",
    rerank: bool = False,
) -> dict[str, Any]:
    """Reconcile two record lists into scored, decisioned match candidates.

    Parameters
    ----------
    list_a, list_b:
        The two record lists (dicts). Records are identified by ``id_field``
        (falling back to positional index when absent).
    comparators:
        Comparator specs, e.g.::

            [{"field": "name", "kind": "name", "weight": 2.0},
             {"field": "name", "kind": "tftoken", "weight": 2.0},
             {"field": "address", "kind": "address", "weight": 1.0},
             {"kind": "geo", "lat": "lat", "lon": "lon", "weight": 1.0},
             {"kind": "containment", "field": "admin_path", "weight": 1.0}]

        Kinds: ``name``, ``phone``, ``id``, ``email``, ``address`` (field
        comparators); ``geo`` and ``containment`` (structural); ``tftoken``
        (TF-weighted token overlap — **requires** ``tf``).
    threshold:
        Score at/above which a pair is a ``match`` (subject to the gate).
    review_margin:
        Pairs scoring in ``[threshold - review_margin, threshold)`` are
        ``review``; below that floor they are dropped entirely.
    distinctive_kinds:
        Comparator kinds that count as *distinctive* identity evidence.
    distinctive_floor:
        A ``match`` requires some distinctive comparator to reach this — the
        gate that stops a shared location from manufacturing a merge.
    tf:
        A :class:`TokenFrequencyTable` (required iff a ``tftoken`` comparator
        or ``rerank`` is used). Pass ``tf="default"`` for the population-scale
        person name table shipped with arche (US Census surnames + African
        names), or a shipped domain name (e.g. ``tf="artist"`` for the
        MusicBrainz catalog table), so distinctiveness weighting works without
        building one.
    block:
        ``"h3"`` (default) restricts scoring to spatial neighbours when records
        carry lat/lon — O(n·k) not O(n·m). ``None`` scores the full
        cross-product (the original ``compare_records`` behaviour).
    rerank:
        When ``True``, apply the block-aware distinguishing-token reranker to
        each pair's score before banding (requires ``tf``).

    Returns
    -------
    dict
        ``{"matches": [{"a_id", "b_id", "score", "decision", "evidence",
        "distinctive_max"}], "count": int, "blocking": {"candidate_pairs": int,
        "reduction_ratio": float}}`` — ids and numeric evidence only, never raw
        PII. ``matches`` is sorted by descending score.
    """
    if isinstance(tf, str):
        # "default" keeps its historical meaning (the person table); any other
        # string names a shipped domain ("artist", ...) — unknown domains raise
        # a ValueError listing what is available.
        tf = TokenFrequencyTable.default(
            domain="person" if tf == "default" else tf
        )
    if rerank and tf is None:
        raise ValueError("rerank=True requires a TokenFrequencyTable passed as tf= "
                         '(or tf="default")')

    n_a, n_b = len(list_a), len(list_b)
    full = n_a * n_b

    # --- candidate generation (blocking) ---------------------------------
    if block == "h3":
        lat_field, lon_field = _geo_fields(comparators)
        pairs = list(_h3_candidate_pairs(
            list_a, list_b, lat_field=lat_field, lon_field=lon_field,
        ))
    elif block is None:
        pairs = [(i, j) for i in range(n_a) for j in range(n_b)]
    else:
        raise ValueError(f"unknown block strategy {block!r}; use 'h3' or None")

    n_cand = len(pairs)
    reduction_ratio = round(1.0 - (n_cand / full), 4) if full else 0.0

    # --- rerank block context: for each a, the b's blocked with it --------
    text_fields: tuple[str, ...] = tuple(
        spec["field"] for spec in comparators
        if spec.get("kind") in _TEXT_KINDS and "field" in spec
    )
    block_of_a: dict[int, list[int]] = {}
    if rerank:
        for i, j in pairs:
            block_of_a.setdefault(i, []).append(j)

    # --- score + band -----------------------------------------------------
    matches: list[dict[str, Any]] = []
    floor = threshold - review_margin
    for i, j in pairs:
        ra, rb = list_a[i], list_b[j]
        scored = _score_pair(ra, rb, comparators, tf, distinctive_kinds)
        if scored is None:
            continue
        score, distinctive_max, containment_conflict, evidence = scored

        if rerank:
            a_text = _rerank_text(ra, text_fields)
            b_text = _rerank_text(rb, text_fields)
            other_texts = [
                _rerank_text(list_b[k], text_fields)
                for k in block_of_a.get(i, ())
                if k != j
            ]
            score = rerank_score(score, a_text, b_text, other_texts, tf)

        if score < floor:
            continue
        decision = "match" if score >= threshold else "review"
        # Distinctive-signal gate + soft containment-conflict flag: a shared
        # location can never auto-merge two records without a distinctive
        # signal clearing the floor and no admin-unit disagreement.
        if decision == "match" and (
            distinctive_max < distinctive_floor or containment_conflict
        ):
            decision = "review"
        matches.append({
            "a_id": ra.get(id_field, i),
            "b_id": rb.get(id_field, j),
            "score": round(score, 4),
            "decision": decision,
            "evidence": evidence,
            "distinctive_max": round(distinctive_max, 3),
        })

    matches.sort(key=lambda m: m["score"], reverse=True)
    return {
        "matches": matches,
        "count": len(matches),
        "blocking": {
            "candidate_pairs": n_cand,
            "reduction_ratio": reduction_ratio,
        },
    }


# Re-exported so ``from arche.resolve.reconcile import TokenFrequencyTable``
# gives callers the table builder alongside the function that consumes it.
__all__ = ["reconcile", "TokenFrequencyTable"]
