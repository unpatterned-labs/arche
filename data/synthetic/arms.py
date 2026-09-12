# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""The matchers under test, each answering in its own vocabulary.

Four arms, in increasing order of what they are allowed to know:

``exact``
    Normalise the name, join on equality with the city. This is the
    rule-baseline shape that scores 1.000 on SPIDER, and **its result on the
    `legitimate_change` stratum is the headline of the whole benchmark**: a
    supplier that moved has a different city, and one that was renamed has a
    different name, so the rule that looks strong overall should collapse
    there. If it does not, the generator is producing changes too small to
    matter and S1 needs revisiting before anything else is worth running.

``jaro_winkler``
    Name similarity over a cheap block. The classic weak baseline.

``arche/pack``
    ``dedupe(entity="organisation")`` -- what a user gets today.

``arche/custom``
    The same engine with every field mapped. The shipped ``organisation`` pack
    reads ``name``, ``registration_id``, ``address``, ``lat``/``lon`` and
    ``entity_class`` and declares ``ignores_everything_else``, so it is
    structurally blind to phone, director, account and TIN -- where 371 of the
    1,763 labelled `change` differences live. The gap between these two arms
    measures what the pack does not read, which is a finding about arche
    rather than about the data.

Each arm returns the positive set **it** stands behind. Nothing here re-derives
a decision from a score: arche's gate demotes a pair to ``review`` without
lowering its score, so a score cut would report false merges the engine
explicitly refused to make.
"""

from __future__ import annotations

import re
import time
from typing import Any

from arche_synthetic.evaluate import Predictions, pair

#: Legal-form words to set aside before an exact join. Without this the `exact`
#: arm would be beaten by `Ltd` vs `Limited` alone, which measures the
#: normaliser rather than the matcher.
_FORMS = {"limited", "ltd", "plc", "enterprises", "ent", "nigeria", "nig",
          "ventures", "global", "international", "group", "holdings", "and", "sons"}
_PUNCT = re.compile(r"[^\w\s]", re.UNICODE)


def normalise(name: str | None) -> str:
    """Case, punctuation and legal form removed -- the fair floor for a join."""
    if not name:
        return ""
    tokens = _PUNCT.sub(" ", name).lower().split()
    kept = [t for t in tokens if t not in _FORMS]
    return " ".join(kept or tokens)


def _pairs_within(groups: dict[Any, list[str]], cap: int = 400) -> set[tuple[str, str]]:
    """All pairs inside each group.

    ``cap`` guards against a degenerate block: a group of 3,000 records is
    4.5M pairs and says nothing except that the blocking key was useless. A
    capped group is recorded in the arm's notes rather than silently dropped.
    """
    out: set[tuple[str, str]] = set()
    for members in groups.values():
        if len(members) > cap:
            continue
        members = sorted(members)
        for i, a in enumerate(members):
            for b in members[i + 1:]:
                out.add(pair(a, b))
    return out


def _oversized(groups: dict[Any, list[str]], cap: int = 400) -> int:
    return sum(1 for m in groups.values() if len(m) > cap)


# ------------------------------------------------------------------ arms --


def exact(observations: list[dict[str, Any]]) -> Predictions:
    """Normalised name plus city, joined on equality."""
    started = time.perf_counter()
    groups: dict[tuple[str, str], list[str]] = {}
    for o in observations:
        key = (normalise(o.get("name")), (o.get("city") or "").upper())
        if not key[0]:
            continue
        groups.setdefault(key, []).append(o["record_id"])
    pairs = _pairs_within(groups)
    return Predictions(
        arm="exact", pairs=pairs, candidates=pairs,
        seconds=time.perf_counter() - started,
        notes={"rule": "normalised name + city, exact",
               # For a pure equality join the blocker and the matcher are the
               # same operation, so blocking recall equals recall here -- that
               # is a property of the arm, not the reporting bug it resembles.
               "blocking_note": "candidates == claims; a join blocks by deciding",
               "oversized_blocks": _oversized(groups)})


def jaro_winkler(observations: list[dict[str, Any]], threshold: float = 0.92) -> Predictions:
    """Name similarity above a threshold, blocked on the first three characters."""
    import jellyfish

    started = time.perf_counter()
    blocks: dict[str, list[tuple[str, str]]] = {}
    for o in observations:
        name = normalise(o.get("name"))
        if not name:
            continue
        blocks.setdefault(name[:3], []).append((o["record_id"], name))

    candidates: set[tuple[str, str]] = set()
    pairs: set[tuple[str, str]] = set()
    for members in blocks.values():
        if len(members) > 400:
            continue
        members = sorted(members)
        for i, (ida, na) in enumerate(members):
            for idb, nb in members[i + 1:]:
                key = pair(ida, idb)
                candidates.add(key)
                if jellyfish.jaro_winkler_similarity(na, nb) >= threshold:
                    pairs.add(key)
    return Predictions(
        arm="jaro_winkler", pairs=pairs, candidates=candidates,
        seconds=time.perf_counter() - started,
        notes={"threshold": threshold, "block": "first 3 chars of normalised name",
               "oversized_blocks": sum(1 for m in blocks.values() if len(m) > 400)})


#: The generator's columns, in the vocabulary the `organisation` pack reads.
def _as_arche_record(o: dict[str, Any]) -> dict[str, Any]:
    address = ", ".join(x for x in (o.get("address"), o.get("city")) if x)
    return {
        "id": o["record_id"],
        "name": o.get("name") or "",
        "registration_id": o.get("rc_number") or "",
        "address": address,
        # read by `arche/custom` only; the shipped pack ignores these
        "phone": o.get("phone") or "",
        "tin": o.get("tin") or "",
        "account_number": o.get("account_number") or "",
        "director_name": o.get("director_name") or "",
        "email": o.get("email") or "",
    }


#: The shipped pack, plus the four fields it does not read. Weights are chosen
#: to be defensible rather than tuned: an account number and a TIN are exact
#: identifiers and rank with the RC number; a phone is strong but shared
#: between businesses; a director's name is weak evidence on its own.
def _custom_comparators() -> list[dict[str, Any]]:
    from arche.resolve import ENTITY_PACKS

    return [
        *[c for c in ENTITY_PACKS["organisation"] if c.get("kind") != "geo"],
        {"field": "tin", "kind": "id", "weight": 2.5},
        {"field": "account_number", "kind": "id", "weight": 2.0},
        {"field": "phone", "kind": "phone", "weight": 1.5},
        {"field": "email", "kind": "email", "weight": 1.0},
        {"field": "director_name", "kind": "name", "weight": 1.0},
    ]


def _arche(observations: list[dict[str, Any]], *, arm: str,
           entity: str | None = None,
           comparators: list[dict[str, Any]] | None = None,
           truth_pairs: list[tuple[str, str]] | None = None) -> Predictions:
    from arche.resolve import dedupe

    records = [_as_arche_record(o) for o in observations]
    started = time.perf_counter()
    kwargs: dict[str, Any] = {"id_field": "id", "tf": "default"}
    if entity:
        kwargs["entity"] = entity
    else:
        kwargs["comparators"] = comparators
    if truth_pairs is not None:
        kwargs["truth_pairs"] = truth_pairs
    result = dedupe(records, **kwargs)
    seconds = time.perf_counter() - started

    # arche's own vocabulary: `match` is the claim, `review` is the refusal.
    pairs = {pair(e["a_id"], e["b_id"]) for e in result["matches"]
             if e.get("decision") == "match"}
    abstentions = {pair(e["a_id"], e["b_id"]) for e in result["matches"]
                   if e.get("decision") == "review"}
    abstentions |= {pair(e["a_id"], e["b_id"]) for e in result.get("review", [])}
    clusters = [c["members"] for c in result.get("clusters", [])] or None
    blocking = result.get("blocking", {})
    return Predictions(
        arm=arm, pairs=pairs, abstentions=abstentions, clusters=clusters,
        seconds=seconds,
        notes={"engine": result.get("pins", {}).get("engine"),
               "candidate_pairs": blocking.get("candidate_pairs"),
               "blocking_recall_reported_by_arche": blocking.get("recall")})


def arche_pack(observations, truth_pairs=None) -> Predictions:
    """`dedupe(entity="organisation")` -- the shipped pack, unmodified."""
    return _arche(observations, arm="arche/pack", entity="organisation",
                  truth_pairs=truth_pairs)


def arche_custom(observations, truth_pairs=None) -> Predictions:
    """The same engine with phone, TIN, account and director mapped in."""
    return _arche(observations, arm="arche/custom",
                  comparators=_custom_comparators(), truth_pairs=truth_pairs)


def splink(observations, truth_pairs=None) -> Predictions:
    """Splink 4, Fellegi-Sunter with EM-estimated parameters. See `arm_splink`."""
    from arm_splink import splink_arm

    return splink_arm(observations)


def arche_ledger(observations, truth_pairs=None) -> Predictions:
    """Incremental resolution in arrival order. See `arm_ledger`."""
    from arm_ledger import arche_ledger as run

    return run(observations)


def arche_ledger_observe(observations, truth_pairs=None) -> Predictions:
    """The same, plus the operator's registry lookup. See `arm_ledger`."""
    from arm_ledger import arche_ledger_observe as run

    return run(observations)


ARMS = {
    "exact": exact,
    "jaro_winkler": jaro_winkler,
    "splink": splink,
    "arche/pack": arche_pack,
    "arche/custom": arche_custom,
    "arche/ledger": arche_ledger,
    "arche/ledger+observe": arche_ledger_observe,
}

__all__ = ["ARMS", "arche_custom", "arche_ledger", "arche_ledger_observe",
           "arche_pack", "exact", "jaro_winkler", "normalise", "splink"]
