# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""What would settle a pair the engine declined to settle.

A `review` edge says the evidence was not enough. It does not say what *would*
be enough, and that gap is the difference between an audit artifact and a next
action. A human reviewer supplies the missing step from domain knowledge. An
agent has no domain knowledge, so it either escalates everything or invents a
merge -- and the second failure is silent.

Everything needed to close the gap is already present. The pack declares which
fields it reads and what each one can do; the records show which of those
arrived. Subtract, rank by what the comparator is capable of, and the answer is
mechanical:

    would_resolve(edge, record_a, record_b, entity="place")
    -> lat/lon would settle it: beyond 10 km the pair is capped at review.

**Deliberately not part of the edge.** `decision_id` is a content hash over the
edge dict, so an extra key would change the identity of every crosswalk edge
ever issued while changing no verdict. Guidance is also not evidence: it
describes what was absent, which is a fact about the query rather than about the
records, and signing it would say otherwise.

The ranking is by what a comparator can *do*, not by its weight, because those
disagree in the way that matters. `place` geo carries weight 1.0 against name's
4.0, and it is the only field in the pack that can stop a match on its own.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ._gate import DISTINCTIVE_FLOOR

#: Ordered strongest first. An effect is what supplying the field could achieve,
#: which is the question an agent deciding whether to go and fetch it is asking.
#:
#: None of them says "refute", and the omission is deliberate. Measured on the
#: place pack: `Karfi Health Post` against itself is `match` at 90 m and
#: `review` at 530 km. The veto did not delete the pair or return `no_match` --
#: it capped the decision. arche declines to assert sameness; it never asserts
#: difference, and guidance that promised otherwise would be describing a
#: different engine.
HARD_CONSTRAINT = "hard_constraint"
DECISIVE_FOR = "decisive_for"
CAN_PREVENT_MATCH = "can_prevent_match"
INDEPENDENT_SIGNAL = "independent_signal"

_RANK = {HARD_CONSTRAINT: 0, DECISIVE_FOR: 1, CAN_PREVENT_MATCH: 2,
         INDEPENDENT_SIGNAL: 3}


def _fields_of(comparator: Mapping) -> tuple[str, ...]:
    """The record keys a comparator reads. Geo names two and neither is `field`."""
    if comparator.get("kind") == "geo":
        return (comparator.get("lat", "lat"), comparator.get("lon", "lon"))
    field = comparator.get("field")
    return (field,) if field else ()


def _label(comparator: Mapping) -> str:
    """How the field is named to a caller, matching `describe_pack`."""
    if comparator.get("kind") == "geo":
        lat, lon = _fields_of(comparator)
        return f"{lat} + {lon}"
    return str(comparator.get("field", ""))


def _supplied(record: Mapping, keys: tuple[str, ...]) -> bool:
    """Present and non-empty on *both* sides, since a comparator needs a pair.

    `0` is a legitimate coordinate and an empty string is not a value, so this
    tests emptiness rather than falsiness -- `lat=0.0` is the equator, not a
    missing field.
    """
    for key in keys:
        value = record.get(key)
        if value is None or (isinstance(value, str) and not value.strip()):
            return False
    return True


def _effect(comparator: Mapping) -> tuple[str, str]:
    """What supplying this comparator's fields could achieve, and why."""
    kind = comparator.get("kind")

    if kind == "geo" and comparator.get("veto_km") is not None:
        km = comparator["veto_km"]
        return (HARD_CONSTRAINT,
                f"coordinates more than {km} km apart cap the pair at review, "
                f"whatever the names agree on. It cannot promote a match and "
                f"it never returns no_match")

    if comparator.get("refutes_below") is not None:
        return (CAN_PREVENT_MATCH,
                "disagreement here holds the pair at review; it never "
                "promotes one")

    if kind == "id":
        return (DECISIVE_FOR,
                "an exact identifier, and the strongest single agreement the "
                "pack accepts")

    if kind == "geo":
        return (INDEPENDENT_SIGNAL,
                f"proximity, decaying over {comparator.get('decay_km')} km. "
                f"This pack sets no veto distance, so distance can only weaken "
                f"the score, never cap the decision")

    if kind == "containment":
        return (INDEPENDENT_SIGNAL,
                "administrative hierarchy: two records in different districts "
                "are usually different things")

    return (INDEPENDENT_SIGNAL,
            f"an independent signal ({kind}) carrying weight "
            f"{comparator.get('weight', 0.0)}")


def would_resolve(edge: Mapping, record_a: Mapping, record_b: Mapping, *,
                  entity: str, threshold: float | None = None) -> dict[str, Any]:
    """Which fields would settle this pair, ranked by what they can achieve.

    ``threshold`` is the run's match threshold (``result["pins"]["threshold"]``).
    With it, a pair whose distinctiveness cleared the floor but whose *score*
    fell short is recognised for what it is -- partial agreement, not a
    conflict -- and the missing fields are listed. Without it the function
    keeps its older reading, in which the only demotion above the floor is a
    hard constraint; that reading is wrong for a pair like ``Kijani Tea
    Exporters`` against ``Kijani Coffee``, which agrees distinctively on one
    token and on nothing else.

    Returns the reason the pair is unresolved, the fields the pack could have
    used and did not receive, and the fields that are already present and
    cannot help. `would_resolve` is empty for a decided pair -- a `match` needs
    nothing, and saying so is more useful than an empty list with no comment.

    The `will_not_help` list matters more than it looks. When a pair is held
    back by low distinctiveness, more of the *same* signal cannot rescue it: two
    records agreeing harder on `General Hospital` is still an agreement on
    `General Hospital`. An agent that does not know this will fetch a longer
    name and try again.
    """
    from . import ENTITY_PACKS

    if entity not in ENTITY_PACKS:
        raise ValueError(
            f"unknown entity pack {entity!r}; available: "
            f"{', '.join(sorted(ENTITY_PACKS))}")

    decision = edge.get("decision")
    distinctive = edge.get("distinctive_max")

    if decision == "match":
        return {"decision": decision, "why": "already resolved",
                "fields_present": [], "would_resolve": [], "will_not_help": []}

    # `conflict` is not carried on the edge. It does not need to be: a pair held
    # at review with distinctiveness above the floor was held by something else,
    # and the only other demotion is a conflict.
    score = edge.get("score")
    by_score = (threshold is not None and score is not None
                and float(score) < float(threshold))
    by_conflict = (distinctive is not None
                   and distinctive >= DISTINCTIVE_FLOOR
                   and not by_score)

    if by_score:
        why = (f"the records agree on something distinctive but on little else "
               f"(score {score} < threshold {threshold}). What is present "
               f"agrees only in part; a field that is absent could settle it")
    elif by_conflict:
        why = ("the records agree distinctively, and a hard constraint "
               "contradicts them -- an administrative-unit disagreement or a "
               "geographic impossibility. More evidence will not settle this; "
               "the contradiction has to be resolved")
    else:
        why = (f"the records agree, and what they agree on is ordinary in this "
               f"pack's reference population (distinctive_max "
               f"{distinctive} < floor {DISTINCTIVE_FLOOR}). Agreement on a "
               f"common token is not evidence of identity")

    present: list[str] = []
    missing: list[dict[str, Any]] = []
    useless: list[dict[str, Any]] = []
    seen: set[str] = set()

    for comparator in ENTITY_PACKS[entity]:
        keys = _fields_of(comparator)
        if not keys:
            continue
        label = _label(comparator)
        if label in seen:
            # `name` carries several comparators in every pack. One entry.
            continue

        have = (_supplied(record_a, keys) and _supplied(record_b, keys))
        if have:
            if label not in present:
                present.append(label)
            continue

        seen.add(label)
        effect, reason = _effect(comparator)
        missing.append({"field": label, "effect": effect, "why": reason,
                        "weight": float(comparator.get("weight", 0.0) or 0.0)})

    if not by_conflict and not by_score:
        for label in present:
            useless.append({
                "field": label,
                "why": "already supplied and already agreeing. More similarity "
                       "here cannot raise distinctiveness -- rarity is a fact "
                       "about the population, not about how well the strings "
                       "match",
            })

    missing.sort(key=lambda entry: (_RANK[entry["effect"]], -entry["weight"],
                                    entry["field"]))
    for entry in missing:
        entry.pop("weight")

    return {
        "decision": decision,
        "why": why,
        "fields_present": present,
        "would_resolve": [] if by_conflict else missing,
        "will_not_help": useless,
    }


__all__ = ["would_resolve", "HARD_CONSTRAINT", "DECISIVE_FOR",
           "CAN_PREVENT_MATCH", "INDEPENDENT_SIGNAL"]
