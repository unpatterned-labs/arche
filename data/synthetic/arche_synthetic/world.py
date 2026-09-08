# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""The world: known entities, their true state, and how they relate.

Everything here is *truth*. Nothing in this module is ever shown to a matcher
-- that is :mod:`observe`'s job, and it only ever shows imperfect views of
what is built here.

Two things are worth reading before changing anything.

**Frequency is modelled, and the model is declared.** A benchmark whose names
are drawn uniformly is easy in a way real data never is: no two suppliers
share a surname, so a name match is almost a key. Real populations are
Zipf-ish -- a few surnames carry a large share of the population and a long
tail carries the rest -- and that collision structure is most of what makes
entity resolution hard. So surnames are drawn Zipf, not uniformly.

But be exact about what that claims. arche's shipped lexicon
(``african_names_v1.jsonl.gz``, 13,342 names, CC-BY) carries **no frequency
data at all** -- two fields, ``name`` and ``name_type``. So the *shape* of the
distribution is modelled and the *ranking within it is arbitrary and seeded*.
This produces realistic collision rates; it does **not** claim that the names
that come out common are actually common in Nigeria. The manifest records this
as ``synthetic-assumption`` rather than ``public-data-derived``, and the data
card says it in the same words. Replacing the ranking with a real frequency
table is a drop-in change and the first thing a curator should do.

**Identifiers are valid by construction.** Every RC number and TIN is checked
against arche's own validator at build time, the way the constructed detection
set is. That discipline has already earned itself once: it caught a generator
bug (Kenyan phone lengths) before the data shipped, and a benchmark whose
identifiers fail the validator measures the generator, not the detector.
"""

from __future__ import annotations

import gzip
import json
import random
import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from .ids import entity_id

#: A local copy, if one has been vendored in. Checked first so this package
#: keeps working when it moves to its own repository and arche is not present.
_LOCAL_LEXICON = Path(__file__).resolve().parent / "data" / "african_names_v1.jsonl.gz"


def _lexicon_path() -> Path:
    """Where the name pool lives.

    Vendored into this package (CC-BY-4.0, 13,342 entries, from arche's
    `african_names_v1`, itself built from Wikidata/ParaNames) so a world can be
    generated with nothing else installed. Falls back to a copy inside an
    installed arche, which keeps the two in step during development.

    Attribution and the caveat that ~5.8% of the entries are not names at all
    are in `DATACARD.md`; `_usable` filters them.
    """
    if _LOCAL_LEXICON.exists():
        return _LOCAL_LEXICON
    import arche  # pragma: no cover - the vendored copy is normally present

    return Path(arche.__file__).resolve().parent / "_data" / "african_names_v1.jsonl.gz"

#: Entries in the shipped lexicon that are not names, and must never become one.
#: Measured 2026-09-08 on `african_names_v1.jsonl.gz`: 770 of 13,342 (5.8%) --
#: 514 raw Wikidata blank-node URLs (`http://www.wikidata.org/.well-known/genid/…`),
#: 153 property labels in various languages (`Abas (nom de famille)`,
#: `Akinfenwa (aha ezinụlọ)`, `njirimara ezinụlọ` = Igbo for "family identifier"),
#: and a tail of titles and full person names filed as surnames. Drawing from an
#: unfiltered pool produced the company `njirimara ezinụlọnjirimara ezinụlọ Steel
#: Global`, which is how this was found. The lexicon itself needs fixing at
#: source; until then this filter is not optional, and a generator that silently
#: emits junk names measures nothing.
_NOT_A_NAME = re.compile(r"https?://|[()\d]|[^\w\s'\-.]", re.UNICODE)


def _usable(name: str) -> bool:
    """A name pool entry: one or two tokens, no markup, no metadata.

    The uppercase requirement is doing more work than it looks. A further 139
    entries survive every other check while being obvious rubbish --
    `almaerifaa.com`, and the Wikidata concept labels `femme blanche`, `homme
    blanc`, `pessoa branca`, `humano branco` in four languages. They are all
    lowercase, and names in this lexicon are capitalised. But the test cannot
    be "the first character is uppercase": `d'Arboussier` and `de Sardan` are
    real surname forms that start lowercase, and `Ba`, `Ka`, `Sy` and `Ly` are
    real Senegalese and Malian surnames that a length cut would delete. So the
    rule is that a name must contain an uppercase letter *somewhere*, which
    keeps the particles and the two-letter surnames and drops the concept
    labels.
    """
    return (2 <= len(name) <= 24
            and name.count(" ") <= 1
            and any(c.isupper() for c in name)
            and not _NOT_A_NAME.search(name))


# -- identifier formats -------------------------------------------------------
# Held locally so this package generates a valid world with nothing else
# installed. arche has the same two validators, and
# `test_synthetic_world.py::test_the_local_validators_agree_with_arches` asserts
# the pair still agree -- which is stronger than depending on either alone,
# because it catches a drift that a one-sided import would hide.

_RC = re.compile(r"^(RC|BN)\d{5,8}$")


def valid_rc(text: str) -> bool:
    """A Nigerian CAC registration number: `RC`/`BN` then 5-8 digits."""
    return bool(_RC.match(text.upper().replace(" ", "")))


def valid_tin(text: str) -> bool:
    """A Nigerian FIRS tax identification number: 10 digits, or 14 with a branch."""
    cleaned = re.sub(r"[\s-]", "", text)
    return cleaned.isdigit() and len(cleaned) in (10, 14)


#: Zipf exponent for the surname draw. 1.0 is the classic Zipf law and gives a
#: heavy head: with 2,000 organisations over a few thousand ranked surnames,
#: the commonest surname lands on roughly 1 in 12. That is the collision rate
#: the `common_names` stratum exists to measure.
ZIPF_ALPHA = 1.0

#: Nigerian company-name furniture. Legal forms carry real weight here: the
#: suffix is the single most abbreviated, dropped and re-cased token in a
#: supplier master, which is exactly why `representation` is its own kind.
_LEGAL_FORMS = ["Limited", "Limited", "Limited", "Nigeria Limited", "Ventures Limited",
                "and Sons Limited", "Global Limited", "International Limited",
                "Enterprises", "Nigeria Enterprises"]
_TRADES = ["Engineering", "Logistics", "Supplies", "Agro", "Foods", "Petroleum",
           "Construction", "Technologies", "Pharmaceuticals", "Textiles", "Motors",
           "Chemicals", "Trading", "Farms", "Steel", "Printing", "Services", "Haulage"]
_CITIES = {
    "Lagos": ["Ikeja", "Apapa", "Surulere", "Yaba", "Victoria Island", "Ojota"],
    "Kano": ["Fagge", "Nassarawa", "Dala", "Gwale", "Tarauni"],
    "Abuja": ["Garki", "Wuse", "Maitama", "Gwarinpa", "Utako"],
    "Port Harcourt": ["Diobu", "Trans Amadi", "GRA", "Rumuokoro"],
    "Ibadan": ["Bodija", "Dugbe", "Ring Road", "Mokola"],
    "Enugu": ["Independence Layout", "New Haven", "Ogui", "Achara Layout"],
}
_STREETS = ["Zaria Road", "Awolowo Way", "Aminu Kano Crescent", "Ahmadu Bello Way",
            "Herbert Macaulay Street", "Murtala Muhammed Road", "Ikot Ekpene Road",
            "Nnamdi Azikiwe Street", "Marina Road", "Allen Avenue", "Broad Street"]
_BANKS = ["Zenith Bank", "First Bank", "GTBank", "Access Bank", "UBA", "Fidelity Bank",
          "Union Bank", "Sterling Bank", "Ecobank", "Stanbic IBTC"]


@dataclass(frozen=True)
class Entity:
    """A synthetic real-world thing. Identity persists; state does not."""

    entity_id: str
    entity_type: str  # organisation | person | place


@dataclass
class State:
    """What was true about an entity over one interval.

    An entity with three states moved twice. ``valid_to is None`` marks the
    current state. A source that observed the entity during an earlier interval
    and never refreshed is *stale*, not wrong -- the distinction the whole
    benchmark exists to measure.
    """

    entity_id: str
    valid_from: date
    valid_to: date | None
    attributes: dict[str, Any]

    def covers(self, when: date) -> bool:
        return self.valid_from <= when and (self.valid_to is None or when < self.valid_to)


@dataclass(frozen=True)
class Relationship:
    subject: str
    predicate: str  # DIRECTOR_OF | LOCATED_AT
    object: str
    valid_from: date
    valid_to: date | None = None


@dataclass
class World:
    """A generated world, and the only object that holds truth."""

    world_id: str
    seed: int
    entities: dict[str, Entity] = field(default_factory=dict)
    states: dict[str, list[State]] = field(default_factory=dict)
    relationships: list[Relationship] = field(default_factory=list)
    events: list[Any] = field(default_factory=list)  # filled by lifecycle
    observations: list[Any] = field(default_factory=list)  # filled by observe
    differences: list[Any] = field(default_factory=list)  # filled by observe
    provenance: list[dict[str, Any]] = field(default_factory=list)

    def of_type(self, entity_type: str) -> list[Entity]:
        return [e for e in self.entities.values() if e.entity_type == entity_type]

    def state_at(self, entity_id: str, when: date) -> tuple[int, State]:
        """The state true at ``when``, with its index. Falls back to the earliest."""
        chain = self.states[entity_id]
        for i, s in enumerate(chain):
            if s.covers(when):
                return i, s
        return (0, chain[0]) if when < chain[0].valid_from else (len(chain) - 1, chain[-1])

    def current(self, entity_id: str) -> State:
        return self.states[entity_id][-1]


class Names:
    """Frequency-weighted draws from the shipped lexicon.

    The ranking is a seeded shuffle, so it is stable for a given seed and
    arbitrary in the sense that matters: it is not a claim about which
    Nigerian surnames are actually common. What it does reproduce is the
    *shape* -- and the shape is what creates the name collisions a matcher has
    to survive.
    """

    def __init__(self, rng: random.Random) -> None:
        with gzip.open(_lexicon_path(), "rt", encoding="utf-8") as handle:
            rows = [json.loads(line) for line in handle]
        self.family = [r["name"] for r in rows
                       if r.get("name_type") == "family" and _usable(r["name"])]
        self.given = [r["name"] for r in rows
                      if r.get("name_type") != "family" and _usable(r["name"])]
        self.dropped = len(rows) - len(self.family) - len(self.given)
        rng.shuffle(self.family)
        rng.shuffle(self.given)
        self._family_w = self._zipf(len(self.family))
        self._given_w = self._zipf(len(self.given))
        self._rng = rng

    @staticmethod
    def _zipf(n: int) -> list[float]:
        return [1.0 / ((i + 1) ** ZIPF_ALPHA) for i in range(n)]

    def surname(self) -> str:
        return self._rng.choices(self.family, weights=self._family_w, k=1)[0]

    def given_name(self) -> str:
        return self._rng.choices(self.given, weights=self._given_w, k=1)[0]

    def person(self) -> str:
        return f"{self.given_name()} {self.surname()}"


class Generator:
    """Seeded construction of a Nigerian supplier world."""

    def __init__(self, world_id: str, seed: int) -> None:
        self.rng = random.Random(seed)
        self.names = Names(random.Random(seed ^ 0x5EED))
        self.world = World(world_id=world_id, seed=seed)
        self._n = {"organisation": 0, "person": 0, "place": 0}
        self.start = date(2019, 1, 1)

    # -- identifiers, valid by construction ---------------------------------

    def rc_number(self) -> str:
        """A CAC company registration number: RC or BN, then 5-8 digits."""
        while True:
            candidate = f"RC{self.rng.randint(100000, 99999999)}"
            if valid_rc(candidate):
                return candidate

    def tin(self) -> str:
        """A FIRS TIN: 10 digits, or 14 with a branch suffix. Format-only --
        FIRS publishes no check-digit specification."""
        while True:
            candidate = "".join(str(self.rng.randint(0, 9)) for _ in range(10))
            if valid_tin(candidate):
                return candidate

    def phone(self) -> str:
        prefix = self.rng.choice(["0803", "0805", "0806", "0703", "0810", "0813", "0814",
                                  "0816", "0701", "0902", "0903", "0905", "0704"])
        rest = "".join(str(self.rng.randint(0, 9)) for _ in range(7))
        return f"{prefix} {rest[:3]} {rest[3:]}"

    def account(self) -> tuple[str, str]:
        return (self.rng.choice(_BANKS),
                "".join(str(self.rng.randint(0, 9)) for _ in range(10)))

    # -- entities ------------------------------------------------------------

    def _new(self, entity_type: str, attributes: dict[str, Any], when: date) -> str:
        self._n[entity_type] += 1
        eid = entity_id(self.world.world_id, entity_type, self._n[entity_type])
        self.world.entities[eid] = Entity(eid, entity_type)
        self.world.states[eid] = [State(eid, when, None, attributes)]
        return eid

    def place(self) -> str:
        city = self.rng.choice(list(_CITIES))
        return self._new("place", {
            "street": f"{self.rng.randint(1, 240)} {self.rng.choice(_STREETS)}",
            "area": self.rng.choice(_CITIES[city]),
            "city": city,
            "state": {"Lagos": "Lagos", "Kano": "Kano", "Abuja": "FCT",
                      "Port Harcourt": "Rivers", "Ibadan": "Oyo",
                      "Enugu": "Enugu"}[city],
            "country": "NG",
        }, self.start)

    def person(self) -> str:
        full = self.names.person()
        return self._new("person", {
            "full_name": full,
            "phone": self.phone(),
            "email": (full.lower().replace(" ", ".")
                      + "@" + self.rng.choice(["gmail.com", "yahoo.com", "outlook.com"])),
        }, self.start)

    def organisation(self, places: list[str], people: list[str]) -> str:
        """One supplier, with a director, a registered place and an account.

        The legal name is built from a Zipf-drawn surname, so common surnames
        produce genuinely colliding company names -- ``Okafor Engineering
        Limited`` twice, owned by different people, in different cities. That
        pair is the false-merge trap the benchmark needs, and it is generated
        rather than hoped for.
        """
        surname = self.names.surname()
        trade = self.rng.choice(_TRADES)
        form = self.rng.choice(_LEGAL_FORMS)
        place = self.rng.choice(places)
        director = self.rng.choice(people)
        bank, account = self.account()
        incorporated = self.start - timedelta(days=self.rng.randint(200, 5000))
        oid = self._new("organisation", {
            "legal_name": f"{surname} {trade} {form}",
            "rc_number": self.rc_number(),
            "tin": self.tin(),
            "phone": self.phone(),
            "email": f"info@{surname.lower()}{trade.lower()}.com.ng",
            "place_id": place,
            "director_id": director,
            "bank": bank,
            "account_number": account,
            "incorporated_on": incorporated.isoformat(),
        }, self.start)
        self.world.relationships.append(
            Relationship(director, "DIRECTOR_OF", oid, self.start))
        self.world.relationships.append(
            Relationship(oid, "LOCATED_AT", place, self.start))
        return oid

    def build(self, organisations: int, people: int, places: int) -> World:
        """Generate the world in a fixed order, so the seed fully determines it."""
        place_ids = [self.place() for _ in range(places)]
        people_ids = [self.person() for _ in range(people)]
        for _ in range(organisations):
            self.organisation(place_ids, people_ids)
        self.world.provenance.append({
            "asset": "given and family names",
            "source": "arche african_names_v1 lexicon (Wikidata/ParaNames, CC-BY-4.0)",
            "method": f"seeded rank shuffle, Zipf weighting alpha={ZIPF_ALPHA}",
            "class": "synthetic-assumption",
            "filtered": (f"{self.names.dropped} lexicon entries excluded as not-names "
                         "(Wikidata blank-node URLs, property labels, titles); see "
                         "world._NOT_A_NAME"),
            "note": ("the lexicon carries no frequency data; the distribution SHAPE is "
                     "modelled and the ranking is arbitrary. Collision rates are "
                     "realistic; the specific common names are not a claim about "
                     "Nigeria."),
        })
        self.world.provenance.append({
            "asset": "RC numbers and TINs",
            "source": "arche.detect.ng.ids validators",
            "method": "generate-and-validate; every identifier passes at build time",
            "class": "public-data-derived",
        })
        return self.world


def generate(world_id: str, seed: int, *, organisations: int, people: int,
             places: int) -> World:
    """Build a world. Same arguments and seed produce the same world."""
    return Generator(world_id, seed).build(organisations, people, places)


__all__ = ["Entity", "Generator", "Names", "Relationship", "State", "World",
           "ZIPF_ALPHA", "generate", "valid_rc", "valid_tin"]
