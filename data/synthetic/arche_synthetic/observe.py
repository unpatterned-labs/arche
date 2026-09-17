# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Imperfect views of a known world, and why each of them differs.

This is where the world becomes a dataset a matcher can be given, and where
the one claim that makes this benchmark worth building gets made: **when two
records disagree, we know why, and the why is not always "error".**

Three causes, kept apart on purpose:

``change``
    The two records saw the entity at different times, and it moved between
    them. Both are true. The ERP holds the address from before the relocation
    because it has not refreshed; the registry holds the one from after. A
    matcher that treats this as evidence of two different suppliers will split
    the entity, and no existing benchmark can tell you whether it does.

``representation``
    Same fact, different encoding. ``Okafor Engineering Limited`` and ``Okafor
    Engineering Ltd`` are the same name written two ways, and neither source is
    wrong. Legal-suffix handling, ampersands, case, address abbreviation.

``error``
    One record is actually wrong. A typo, an OCR misread, a truncated field, a
    mutated digit.

The labels are **computed by construction, never inferred afterwards**. Every
observed value carries a note of which state it came from and which transforms
were applied to it, so a difference between two observations is explained by
comparing their provenance rather than by guessing from the strings. That is
the same discipline the constructed detection set uses for spans, and it is
what makes the ground truth trustworthy enough to score against.

Scope note for v0.1: only organisations are observed. People and places exist
in the world as truth and appear *inside* supplier records (a director's name,
an address), which is how they appear in a real vendor master. Observing them
as independent records is a v0.2 extension.
"""

from __future__ import annotations

import random
import unicodedata
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from .ids import difference_id, record_id
from .world import World

# ---------------------------------------------------------------- sources --


@dataclass(frozen=True)
class Source:
    """A system that observes suppliers, with its own habits and its own faults."""

    name: str
    coverage: float                 # fraction of organisations it holds at all
    lag: tuple[int, int]            # days between the truth moving and this source seeing it
    repeats: tuple[int, int]        # how many records it writes per supplier
    fields: tuple[str, ...]         # which attributes it stores
    representation: dict[str, float]
    error: dict[str, float]
    #: Fields this source is obliged to hold; `missing` never applies to them.
    never_missing: tuple[str, ...] = ()


#: The ERP is the stale one, and staleness is the point: a vendor master is
#: keyed on a record somebody typed once, and nothing makes it re-read the
#: registry. Its lag is what produces `change` differences.
ERP = Source(
    name="erp", coverage=0.85, lag=(30, 900), repeats=(1, 1),
    fields=("name", "rc_number", "phone", "address", "city", "bank",
            "account_number", "director_name"),
    representation={"legal_suffix_abbreviated": 0.45, "legal_suffix_dropped": 0.15,
                    "ampersand": 0.3, "case_upper": 0.25, "address_abbreviated": 0.4},
    error={"typo": 0.10, "truncation": 0.12, "digit_mutation": 0.04, "missing": 0.10},
    never_missing=("name",),
)

#: The registry is authoritative and fresh: the full legal name, the RC number,
#: the TIN. It is the source a matcher would most like to have and the one a
#: procurement team most often does not.
REGISTRY = Source(
    name="registry", coverage=1.0, lag=(0, 25), repeats=(1, 1),
    fields=("name", "rc_number", "tin", "address", "city", "director_name",
            "incorporated_on"),
    representation={"case_upper": 0.1},
    # The registry is the authoritative source: it does not lose the company's
    # name or its RC number. `never_missing` says which fields a source is
    # obliged to hold, so `missing` cannot quietly gut the one record a matcher
    # was supposed to be able to rely on.
    error={"typo": 0.01, "missing": 0.02},
    never_missing=("name", "rc_number"),
)

#: Invoices are read by OCR and written by whoever typed the header. Heavy
#: representation variation, heavy OCR error, and rarely an identifier.
INVOICE = Source(
    name="invoice", coverage=0.6, lag=(0, 120), repeats=(1, 3),
    # Several invoices per supplier over the horizon: that repetition is what
    # makes an observation pair straddle an event, which is what a `change`
    # difference needs to exist at all.
    fields=("name", "phone", "address", "city", "bank", "account_number"),
    representation={"legal_suffix_abbreviated": 0.5, "legal_suffix_dropped": 0.3,
                    "ampersand": 0.4, "case_upper": 0.35, "diacritic_loss": 0.5,
                    "address_abbreviated": 0.5},
    error={"ocr_confusion": 0.18, "typo": 0.08, "truncation": 0.10,
           "digit_mutation": 0.05, "missing": 0.14},
    never_missing=("name",),
)

SOURCES = {s.name: s for s in (ERP, REGISTRY, INVOICE)}


@dataclass
class Observation:
    """One record as a source holds it, plus the truth of how it got that way."""

    record_id: str
    source: str
    observed_at: date
    attributes: dict[str, str]
    # -- truth side; never written to observations.parquet --
    entity_id: str = ""
    state_index: int = 0
    #: attribute -> [(kind, cause), ...]. What was done to this value.
    applied: dict[str, list[tuple[str, str]]] = field(default_factory=dict)


@dataclass(frozen=True)
class Difference:
    """One labelled disagreement between two observations of the same entity."""

    difference_id: str
    entity_id: str
    observation_a: str
    observation_b: str
    attribute: str
    difference_kind: str  # change | representation | error
    cause: str
    event_id: str | None = None


# -------------------------------------------------- representation rules --
# Valid alternate encodings of the same fact. NOT errors: no information is
# lost that the source was obliged to keep, and no reader would call either
# form wrong.

#: Rules decided once per record rather than per field -- see `observe_one`.
_RECORD_STYLES = frozenset({"case_upper", "diacritic_loss"})

_SUFFIXES = ["Limited", "Enterprises", "Plc"]


def _legal_suffix_abbreviated(value: str, rng: random.Random) -> str | None:
    for long, short in (("Limited", "Ltd"), ("Enterprises", "Ent."), ("Nigeria", "Nig.")):
        if value.endswith(long) or f" {long} " in value:
            return value.replace(long, short)
    return None


def _legal_suffix_dropped(value: str, rng: random.Random) -> str | None:
    for suffix in _SUFFIXES:
        if value.endswith(" " + suffix):
            return value[: -len(suffix) - 1].strip()
    return None


def _ampersand(value: str, rng: random.Random) -> str | None:
    return value.replace(" and ", " & ") if " and " in value else None


def _case_upper(value: str, rng: random.Random) -> str | None:
    return value.upper() if value != value.upper() else None


def _diacritic_loss(value: str, rng: random.Random) -> str | None:
    stripped = "".join(c for c in unicodedata.normalize("NFD", value)
                       if not unicodedata.combining(c))
    return stripped if stripped != value else None


def _address_abbreviated(value: str, rng: random.Random) -> str | None:
    for long, short in (("Road", "Rd"), ("Street", "St"), ("Crescent", "Cres"),
                        ("Avenue", "Ave"), ("Way", "Wy")):
        if long in value:
            return value.replace(long, short)
    return None


REPRESENTATION = {
    "legal_suffix_abbreviated": _legal_suffix_abbreviated,
    "legal_suffix_dropped": _legal_suffix_dropped,
    "ampersand": _ampersand,
    "case_upper": _case_upper,
    "diacritic_loss": _diacritic_loss,
    "address_abbreviated": _address_abbreviated,
}

# ------------------------------------------------------- corruption rules --
# Actual error. One of the two records is wrong, and a reader shown the truth
# would say so.

_OCR = {"O": "0", "0": "O", "I": "1", "l": "1", "S": "5", "B": "8", "G": "6", "Z": "2"}


def _typo(value: str, rng: random.Random) -> str | None:
    """A slip of the finger, in the same alphabet as what it replaced.

    Substituting a lowercase letter regardless of context produced `0803 12a
    4567` as a phone number and `OKAFOR ENGINEERINg` in an all-caps vendor
    master -- neither of which anybody types, and both of which a matcher
    would find easier to spot than a real typo. So a digit is replaced by a
    digit, and a letter by a letter of the same case.
    """
    if len(value) < 4:
        return None
    i = rng.randrange(1, len(value) - 1)
    kind = rng.choice(("transpose", "delete", "substitute"))
    if kind == "transpose":
        return value[:i] + value[i + 1] + value[i] + value[i + 2:]
    if kind == "delete":
        return value[:i] + value[i + 1:]
    original = value[i]
    if original.isdigit():
        alphabet = "0123456789"
    elif original.isalpha():
        alphabet = ("ABCDEFGHIJKLMNOPQRSTUVWXYZ" if original.isupper()
                    else "abcdefghijklmnopqrstuvwxyz")
    else:
        return None  # never mangle a separator into a letter
    return value[:i] + rng.choice([c for c in alphabet if c != original]) + value[i + 1:]


def _ocr_confusion(value: str, rng: random.Random) -> str | None:
    positions = [i for i, c in enumerate(value) if c in _OCR]
    if not positions:
        return None
    i = rng.choice(positions)
    return value[:i] + _OCR[value[i]] + value[i + 1:]


def _truncation(value: str, rng: random.Random) -> str | None:
    if len(value) < 12:
        return None
    return value[: rng.randint(8, len(value) - 2)].strip()


def _digit_mutation(value: str, rng: random.Random) -> str | None:
    positions = [i for i, c in enumerate(value) if c.isdigit()]
    if not positions:
        return None
    i = rng.choice(positions)
    replacement = rng.choice([d for d in "0123456789" if d != value[i]])
    return value[:i] + replacement + value[i + 1:]


CORRUPTION = {
    "typo": _typo,
    "ocr_confusion": _ocr_confusion,
    "truncation": _truncation,
    "digit_mutation": _digit_mutation,
}

# ------------------------------------------------------------- observing --


class Observer:
    """Turns world states into source records, remembering what it did."""

    def __init__(self, world: World, seed: int) -> None:
        self.world = world
        self.rng = random.Random(seed ^ 0x0B5E4)
        self._sequence = 0

    def _flatten(self, state_attributes: dict[str, Any]) -> dict[str, str]:
        """The entity's true state as a flat record, resolving place and director."""
        place = self.world.current(state_attributes["place_id"]).attributes
        director = self.world.current(state_attributes["director_id"]).attributes
        return {
            "name": state_attributes["legal_name"],
            "rc_number": state_attributes["rc_number"],
            "tin": state_attributes["tin"],
            "phone": state_attributes["phone"],
            "email": state_attributes["email"],
            "address": f"{place['street']}, {place['area']}",
            "city": place["city"],
            "bank": state_attributes["bank"],
            "account_number": state_attributes["account_number"],
            "director_name": director["full_name"],
            "incorporated_on": state_attributes["incorporated_on"],
        }

    def observe_one(self, entity_id_: str, source: Source, when: date) -> Observation:
        """One record: what this source believed about this supplier on this date."""
        lag = timedelta(days=self.rng.randint(*source.lag))
        index, state = self.world.state_at(entity_id_, when - lag)
        truth = self._flatten(state.attributes)
        attributes: dict[str, str] = {}
        applied: dict[str, list[tuple[str, str]]] = {}
        styles = {rule for rule in source.representation
                  if rule in _RECORD_STYLES
                  and self.rng.random() < source.representation[rule]}

        for name in source.fields:
            value = truth.get(name)
            if value is None:
                continue
            notes: list[tuple[str, str]] = []

            # Representation first: a valid re-encoding of the true value.
            for rule, probability in sorted(source.representation.items()):
                # `case_upper` is a house style, decided once per record: a
                # vendor master that stores NAMES IN CAPITALS stores addresses
                # in capitals too. Rolling it per field produced records that
                # shouted one column and whispered the next, which no real
                # system does and which inflated the representation stratum
                # with differences a matcher would never see.
                if rule in _RECORD_STYLES:
                    if rule not in styles:
                        continue
                elif self.rng.random() >= probability:
                    continue
                rewritten = REPRESENTATION[rule](value, self.rng)
                if rewritten is not None and rewritten != value:
                    value = rewritten
                    notes.append(("representation", rule))

            # Then error, applied to whatever the source ended up writing.
            if (name not in source.never_missing
                    and self.rng.random() < source.error.get("missing", 0.0)):
                applied[name] = [*notes, ("error", "missing")]
                continue
            for rule, probability in sorted(source.error.items()):
                if rule == "missing" or rule not in CORRUPTION:
                    continue
                if self.rng.random() < probability:
                    broken = CORRUPTION[rule](value, self.rng)
                    if broken is not None and broken != value:
                        value = broken
                        notes.append(("error", rule))

            attributes[name] = value
            applied[name] = notes

        self._sequence += 1
        return Observation(
            record_id=record_id(self.world.world_id, source.name, self._sequence),
            source=source.name, observed_at=when, attributes=attributes,
            entity_id=entity_id_, state_index=index, applied=applied,
        )

    def run(self, start: date, end: date) -> list[Observation]:
        """Observe every supplier through every source that covers it."""
        span = (end - start).days
        out: list[Observation] = []
        for entity in sorted(e.entity_id for e in self.world.of_type("organisation")):
            for source in (ERP, REGISTRY, INVOICE):
                if self.rng.random() > source.coverage:
                    continue
                for _ in range(self.rng.randint(*source.repeats)):
                    when = start + timedelta(days=self.rng.randint(0, span))
                    out.append(self.observe_one(entity, source, when))
        self.world.observations = out
        return out


# ------------------------------------------------------------ differences --


#: A flat record field is carried by a state field: `address` and `city` both
#: come from `place_id`, `name` from `legal_name`, `director_name` from
#: `director_id`.
_CARRIER = {"address": "place_id", "city": "place_id", "name": "legal_name",
            "director_name": "director_id", "bank": "bank",
            "account_number": "account_number"}


def _index_events(world: World) -> dict[tuple[str, Any], list[Any]]:
    """Events keyed by (entity, date), built once.

    The previous version scanned `world.events` for every difference it had to
    explain. At 2,000 suppliers that is 1,435 events against 33,000
    differences and merely wasteful; at 40,000 it is the reason the generator
    stops finishing.
    """
    index: dict[tuple[str, Any], list[Any]] = {}
    for event in world.events:
        index.setdefault((event.entity_id, event.event_at), []).append(event)
    return index


def _event_for(index: dict[tuple[str, Any], list[Any]], world: World,
               entity_id_: str, attribute: str,
               state_a: int, state_b: int) -> Any | None:
    """The event that moved ``attribute`` between two states of one entity."""
    carrier = _CARRIER.get(attribute, attribute)
    low, high = sorted((state_a, state_b))
    for state in world.states[entity_id_][low + 1: high + 1]:
        for event in index.get((entity_id_, state.valid_from), ()):
            if carrier in event.changes:
                return event
    return None


def differences(world: World) -> list[Difference]:
    """Explain every disagreement between two observations of the same entity.

    One row per (pair, attribute, kind): an attribute that differs for two
    reasons -- the supplier moved *and* the invoice OCR mangled the new address
    -- produces two rows, so the evaluator can put that pair in both strata
    rather than having to choose one.
    """
    by_entity: dict[str, list[Observation]] = {}
    for observation in world.observations:
        by_entity.setdefault(observation.entity_id, []).append(observation)
    index = _index_events(world)

    out: list[Difference] = []
    for entity_id_, group in sorted(by_entity.items()):
        for i, a in enumerate(group):
            for b in group[i + 1:]:
                for attribute in sorted(set(a.attributes) & set(b.attributes)):
                    if a.attributes[attribute] == b.attributes[attribute]:
                        continue
                    kinds: list[tuple[str, str, str | None]] = []

                    if a.state_index != b.state_index:
                        event = _event_for(index, world, entity_id_, attribute,
                                           a.state_index, b.state_index)
                        if event is not None:
                            kinds.append(("change", event.kind, event.event_id))

                    seen: set[tuple[str, str]] = set()
                    for note in (*a.applied.get(attribute, ()),
                                 *b.applied.get(attribute, ())):
                        if note not in seen:
                            seen.add(note)
                            kinds.append((note[0], note[1], None))

                    for kind, cause, event_ref in kinds:
                        out.append(Difference(
                            difference_id(a.record_id, b.record_id, attribute, kind),
                            entity_id_, a.record_id, b.record_id, attribute,
                            kind, cause, event_ref))
    world.differences = out
    return out


def run(world: World, start: date, end: date, *,
        seed: int) -> tuple[list[Observation], list[Difference]]:
    """Observe the world, then explain every disagreement it produced."""
    observations = Observer(world, seed).run(start, end)
    return observations, differences(world)


__all__ = ["CORRUPTION", "Difference", "ERP", "INVOICE", "Observation", "Observer",
           "REGISTRY", "REPRESENTATION", "SOURCES", "Source", "differences", "run"]
