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

import contextlib
import warnings
from typing import Any

from arche.resolve._block import blocking_recall as _blocking_recall
from arche.resolve._block import candidate_pairs as _h3_candidate_pairs
from arche.resolve._block import union_candidate_pairs as _union_candidate_pairs
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
    compare_place_names,
    haversine_km,
    load_type_vocab,
    normalize_type_token,
)
from arche.resolve._rerank import rerank_score
from arche.resolve._tokenfreq import TokenFrequencyTable

# Simple single-value comparators keyed by comparator ``kind``.
_FIELD_COMPARATORS = {
    "name": lambda a, b: compare_names(a, b)[0],
    # Place names never consult the person equivalence lexicon —
    # Fatima≡Fatouma is a fact about people, not about two facilities
    # named after them (the false-merge vector the place audit measured).
    "placename": compare_place_names,
    "phone": compare_phones,
    "id": compare_ids,
    "email": compare_emails,
    "address": compare_addresses,
    # Same comparator pairwise and in crosswalk — a kind vocabulary that means
    # different things on two paths is exactly the confusion the declaration
    # layer exists to remove.
    "date": compare_dates,
}

# Comparator kinds whose fields carry free text worth reranking on (also the
# fields rare-token union blocking keys on).
_TEXT_KINDS = ("tftoken", "name", "placename", "address")

_DISTINCTIVE_KINDS = ("name", "placename", "id", "tftoken")


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
    if kind == "type":
        # Type-token agreement ("PHC" vs "HOSPITAL") via the domain vocabulary.
        # Inapplicable (None) unless BOTH names yield a recognised type —
        # absence of a type token is not evidence of anything.
        vocab = load_type_vocab(spec.get("domain", ""))
        if not vocab:
            return None
        field = spec.get("field", "name")
        if ra.get(field) in (None, "") or rb.get(field) in (None, ""):
            return None
        type_a, _ = normalize_type_token(str(ra[field]), vocab)
        type_b, _ = normalize_type_token(str(rb[field]), vocab)
        if type_a is None or type_b is None:
            return None
        return 1.0 if type_a == type_b else 0.0
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
        if spec["kind"] == "geo":
            # Reviewers read metres, not decayed similarities: 0.136 hides
            # what "3.2 km apart" says plainly. Distance is evidence, not a
            # scored comparator — it carries no weight of its own.
            lat, lon = spec.get("lat", "lat"), spec.get("lon", "lon")
            with contextlib.suppress(KeyError, TypeError, ValueError):
                evidence["distance_km"] = round(haversine_km(
                    float(ra[lat]), float(ra[lon]), float(rb[lat]), float(rb[lon]),
                ), 2)
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
    block: str | None = "union",
    rerank: bool = False,
    truth_pairs: list[tuple[Any, Any]] | None = None,
    extra_pins: dict[str, Any] | None = None,
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
        ``"union"`` (default) ORs three candidate keys — H3 spatial (res 7 +
        a res-6 safety ring), rare-token on the text-comparator fields, and
        shared-id — so a true match whose coordinates disagree by kilometres,
        or that has no coordinates at all, still reaches the comparators.
        ``"h3"`` is spatial-only (the pre-v0.3 behaviour; coordless records
        pair with everything, loudly). ``None`` scores the full cross-product.
    rerank:
        When ``True``, apply the block-aware distinguishing-token reranker to
        each pair's score before banding (requires ``tf``).
    truth_pairs:
        Optional labelled true-match pairs as ``(a_id, b_id)`` (``id_field``
        values). When given, the blocking report includes ``recall`` — the
        fraction of true pairs the blocker kept, the ceiling on every
        downstream metric.
    extra_pins:
        Extra provenance pinned into every edge's ``decision_id`` (e.g. a
        declaration pin, an admin-boundary-layer vintage).

    Returns
    -------
    dict
        ``{"matches": [{"a_id", "b_id", "score", "decision", "evidence",
        "distinctive_max", "decision_id"}], "count": int, "pins": {...},
        "blocking": {"candidate_pairs": int, "reduction_ratio": float,
        "strategies": {...}, "recall": float?}}`` — ids and numeric evidence
        only, never raw PII. ``matches`` is sorted by descending score.
        ``decision_id`` is a content hash over the edge and the pins:
        recompute it to verify nothing changed; sign it with
        :func:`sign_edges`.
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
    strategy_info: dict[str, int] | None = None
    if block == "union":
        lat_field, lon_field = _geo_fields(comparators)
        pairs, strategy_info = _union_candidate_pairs(
            list_a, list_b,
            lat_field=lat_field, lon_field=lon_field,
            text_fields=tuple(dict.fromkeys(
                spec["field"] for spec in comparators
                if spec.get("kind") in _TEXT_KINDS and "field" in spec
            )),
            id_fields=tuple(dict.fromkeys(
                spec["field"] for spec in comparators
                if spec.get("kind") == "id" and "field" in spec
            )),
        )
        coordless = strategy_info["coordless_a"] + strategy_info["coordless_b"]
        if coordless and not (strategy_info["token"] or strategy_info["id"]):
            warnings.warn(
                f"{coordless} record(s) lack coordinates and no token/id "
                "blocking key applied — those records reached no candidate "
                "pair. Add a text or id comparator, or pass block=None.",
                RuntimeWarning,
                stacklevel=2,
            )
    elif block == "h3":
        lat_field, lon_field = _geo_fields(comparators)
        coordless = sum(
            1 for r in [*list_a, *list_b]
            if r.get(lat_field) in (None, "") or r.get(lon_field) in (None, "")
        )
        if coordless:
            warnings.warn(
                f"block='h3': {coordless} record(s) lack coordinates and are "
                "compared against every record on the other side (O(n*m) for "
                "those rows). block='union' covers them with token/id keys.",
                RuntimeWarning,
                stacklevel=2,
            )
        pairs = list(_h3_candidate_pairs(
            list_a, list_b, lat_field=lat_field, lon_field=lon_field,
        ))
    elif block is None:
        pairs = [(i, j) for i in range(n_a) for j in range(n_b)]
    else:
        raise ValueError(
            f"unknown block strategy {block!r}; use 'union', 'h3' or None"
        )

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

    # --- provenance pins (hashed into every edge's decision_id) ----------
    # Imported here, not at module level: arche.ids itself imports from
    # arche.resolve, so a module-level import is a circular-import landmine
    # whenever arche.ids is the first entry point.
    from arche.ids import content_hash

    pins: dict[str, Any] = {
        "engine": "crosswalk.v1",
        "comparators_sha256": content_hash(comparators, prefix="cmp")
        .split(":")[-1][:16],
        "block": block or "none",
        "threshold": threshold,
        "review_margin": review_margin,
        "distinctive_floor": distinctive_floor,
        "tf": "provided" if tf is not None else None,
    }
    if extra_pins:
        pins.update(extra_pins)

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
        edge = {
            "a_id": ra.get(id_field, i),
            "b_id": rb.get(id_field, j),
            "score": round(score, 4),
            "decision": decision,
            "evidence": evidence,
            "distinctive_max": round(distinctive_max, 3),
        }
        # The reproducible address of this edge: a pure function of the
        # (rounded) evidence and the pins — no timestamp, recomputable by
        # anyone holding the same inputs. This is what makes a crosswalk
        # edge citable and signable, exactly like a pairwise decision.
        edge["decision_id"] = content_hash(
            {"schema": "arche.crosswalk_edge.v1", **edge, "pins": pins},
            prefix="xwd",
        )
        matches.append(edge)

    matches.sort(key=lambda m: m["score"], reverse=True)
    blocking: dict[str, Any] = {
        "candidate_pairs": n_cand,
        "reduction_ratio": reduction_ratio,
    }
    if strategy_info is not None:
        blocking["strategies"] = strategy_info
    if truth_pairs is not None:
        id_of_a = [ra.get(id_field, i) for i, ra in enumerate(list_a)]
        id_of_b = [rb.get(id_field, j) for j, rb in enumerate(list_b)]
        blocking["recall"] = round(_blocking_recall(
            truth_pairs, ((id_of_a[i], id_of_b[j]) for i, j in pairs),
        ), 4)
    return {
        "matches": matches,
        "count": len(matches),
        "pins": pins,
        "blocking": blocking,
    }


def sign_edges(
    result: dict[str, Any],
    *,
    private_key: Any,
    kid: str,
    decisions: tuple[str, ...] = ("match", "review"),
) -> list[dict[str, str]]:
    """JWS-sign crosswalk edges — the place-decision attestation path.

    Each signed payload is the edge dict plus the run's ``pins``, under the
    ``arche.crosswalk_edge.v1`` schema — the same claim shape its
    ``decision_id`` hashes, so a verifier can recompute the id from the signed
    payload (dropping the ``decision_id`` field itself first) and confirm
    nothing was altered. Returns
    ``[{"decision_id", "jws"}, ...]`` for edges whose decision is in
    ``decisions``. Edges carry ids and numeric evidence only (never raw PII),
    so the signed artifact is as shareable as the crosswalk output itself.

    Keys come from ``arche.sign.generate_keypair()`` or your own Ed25519 key;
    verify with ``arche.sign.verify``.
    """
    from arche.sign import sign as _jws_sign

    pins = result.get("pins", {})
    signed: list[dict[str, str]] = []
    for edge in result.get("matches", ()):
        if edge.get("decision") not in decisions:
            continue
        payload = {"schema": "arche.crosswalk_edge.v1", **edge, "pins": pins}
        signed.append({
            "decision_id": edge.get("decision_id", ""),
            "jws": _jws_sign(
                payload=payload, private_key=private_key, kid=kid,
                typ="arche+jws",
            ),
        })
    return signed


# Re-exported so ``from arche.resolve.reconcile import TokenFrequencyTable``
# gives callers the table builder alongside the function that consumes it.
__all__ = ["reconcile", "sign_edges", "TokenFrequencyTable"]
