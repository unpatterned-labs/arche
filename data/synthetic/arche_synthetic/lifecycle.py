# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Legitimate change: the thing this benchmark exists to measure.

Every published ER benchmark builds duplicates the same way -- take a record,
apply a transformation, call the result a corrupted copy. That model says
every difference between two records is an error. It is wrong about real data
often enough to matter: a supplier really did move, a director really did
resign, an account really was replaced. **Both records are true, at their
respective times.** A matcher tuned on data where all disagreement is noise
learns to treat legitimate change as evidence of a different entity, and then
splits entities in production.

So this module generates change, and labels it as change. An event:

1. closes the entity's current state at the event date;
2. opens a new state carrying the new values;
3. records which attributes moved, from what, to what.

:mod:`observe` then lets different sources see different states -- the ERP
still holding the pre-move address while the registry holds the new one -- and
the resulting disagreement is labelled ``change`` with this event's id, not
``error``. That is the column no public benchmark has.

Note what is *not* here: a rate model calibrated against real supplier
churn. The default rates are declared parameters, not measurements, and the
manifest says so. What matters for the benchmark is that changed pairs exist
in known quantity and are labelled; the exact hazard rate is a knob.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from .ids import event_id
from .world import Relationship, State, World

#: Per-entity probability of each event kind over the world's whole horizon.
#: Declared parameters, not measured rates -- see the module docstring.
DEFAULT_RATES = {
    # Raised from a first pass at 0.18/0.07/0.12/0.10: at that setting a rename
    # or a director change produced ONE labelled difference in a 100-supplier
    # world, because a difference needs two observations that straddle the
    # event and most events had none. A stratum with one pair in it is not a
    # stratum. Still declared parameters, not measured churn rates.
    "ORG_RELOCATED": 0.22,
    "ORG_RENAMED": 0.16,
    "DIRECTOR_CHANGED": 0.20,
    "ACCOUNT_CHANGED": 0.14,
}


@dataclass(frozen=True)
class Event:
    """One legitimate change, and exactly which attributes it moved."""

    event_id: str
    entity_id: str
    kind: str
    event_at: date
    changes: dict[str, tuple[Any, Any]] = field(default_factory=dict)  # attr -> (old, new)


class Lifecycle:
    """Applies events to a world, preserving every historical state."""

    def __init__(self, world: World, seed: int) -> None:
        self.world = world
        self.rng = random.Random(seed ^ 0xE4E17)
        self._n = 0

    def _apply(self, entity_id_: str, kind: str, when: date,
               new_values: dict[str, Any]) -> Event | None:
        """Close the current state, open a new one, and record what moved."""
        chain = self.world.states[entity_id_]
        current = chain[-1]
        if when <= current.valid_from:
            return None  # two events in one interval: keep the world monotonic
        changes = {k: (current.attributes.get(k), v)
                   for k, v in new_values.items()
                   if current.attributes.get(k) != v}
        if not changes:
            return None
        current.valid_to = when
        chain.append(State(entity_id_, when, None,
                           {**current.attributes, **new_values}))
        self._n += 1
        event = Event(event_id(self.world.world_id, self._n), entity_id_, kind, when, changes)
        self.world.events.append(event)
        return event

    # -- the four events -----------------------------------------------------

    def relocate(self, org: str, when: date, places: list[str]) -> Event | None:
        """The supplier moved. The old address stays true for its interval."""
        current = self.world.current(org).attributes["place_id"]
        options = [p for p in places if p != current]
        return self._apply(org, "ORG_RELOCATED", when,
                           {"place_id": self.rng.choice(options)})

    def rename(self, org: str, when: date) -> Event | None:
        """A rebrand or a change of legal form. Same company, new name.

        This is the hardest legitimate change for a matcher, because the name
        is usually the strongest signal it has -- and here the strongest signal
        is the one that legitimately moved.
        """
        name = self.world.current(org).attributes["legal_name"]
        head = name.rsplit(" ", 1)[0] if " " in name else name
        options = [f"{head} Nigeria Limited", f"{head} Group Limited",
                   f"{head} Holdings Limited", f"{head} Plc"]
        return self._apply(org, "ORG_RENAMED", when,
                           {"legal_name": self.rng.choice(
                               [o for o in options if o != name])})

    def change_director(self, org: str, when: date, people: list[str]) -> Event | None:
        """One director resigns, another is appointed. Both relationships stay true."""
        current = self.world.current(org).attributes["director_id"]
        options = [p for p in people if p != current]
        successor = self.rng.choice(options)
        event = self._apply(org, "DIRECTOR_CHANGED", when, {"director_id": successor})
        if event is not None:
            for rel in self.world.relationships:
                if (rel.subject == current and rel.predicate == "DIRECTOR_OF"
                        and rel.object == org and rel.valid_to is None):
                    self.world.relationships.remove(rel)
                    self.world.relationships.append(
                        Relationship(current, "DIRECTOR_OF", org, rel.valid_from, when))
                    break
            self.world.relationships.append(
                Relationship(successor, "DIRECTOR_OF", org, when))
        return event

    def change_account(self, org: str, when: date) -> Event | None:
        """A new bank account. In the real product this is the fraud-adjacent one:
        a supplier's account changing is exactly what an invoice-redirection
        attack looks like, which is why *legitimate* account change has to be
        representable before the adversarial version means anything."""
        from .world import _BANKS

        current = self.world.current(org).attributes["bank"]
        bank = self.rng.choice([b for b in _BANKS if b != current])
        return self._apply(org, "ACCOUNT_CHANGED", when, {
            "bank": bank,
            "account_number": "".join(str(self.rng.randint(0, 9)) for _ in range(10)),
        })

    # -- the run -------------------------------------------------------------

    def run(self, start: date, end: date, rates: dict[str, float] | None = None) -> list[Event]:
        """Roll events for every organisation, in entity order, over the horizon."""
        rates = {**DEFAULT_RATES, **(rates or {})}
        places = [e.entity_id for e in self.world.of_type("place")]
        people = [e.entity_id for e in self.world.of_type("person")]
        span = (end - start).days
        for org in sorted(e.entity_id for e in self.world.of_type("organisation")):
            # Sorted by date so state chains stay monotonic whatever order the
            # kinds are rolled in.
            due: list[tuple[date, str]] = []
            for kind, rate in sorted(rates.items()):
                if self.rng.random() < rate:
                    due.append((start + timedelta(days=self.rng.randint(1, span)), kind))
            for when, kind in sorted(due):
                if kind == "ORG_RELOCATED":
                    self.relocate(org, when, places)
                elif kind == "ORG_RENAMED":
                    self.rename(org, when)
                elif kind == "DIRECTOR_CHANGED":
                    self.change_director(org, when, people)
                elif kind == "ACCOUNT_CHANGED":
                    self.change_account(org, when)
        return self.world.events


def run(world: World, start: date, end: date, *, seed: int,
        rates: dict[str, float] | None = None) -> list[Event]:
    """Generate the world's lifecycle. Deterministic under ``seed``."""
    return Lifecycle(world, seed).run(start, end, rates)


__all__ = ["DEFAULT_RATES", "Event", "Lifecycle", "run"]
