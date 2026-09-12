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

#: Real given+family pairs pulled from Wikidata (CC0) by
#: `datasets/pull_wikidata.py`. Optional: without it the generator falls back to
#: the lexicon, and says so in the manifest rather than pretending.
_PAIRS_NAME = "wikidata_name_pairs.jsonl"
_PAIRS_CANDIDATES = (
    Path(__file__).resolve().parent / "data" / _PAIRS_NAME,
    Path(__file__).resolve().parents[3] / "datasets" / "data" / _PAIRS_NAME,
)


def _pairs_path() -> Path | None:
    for candidate in _PAIRS_CANDIDATES:
        if candidate.exists():
            return candidate
    return None


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


def _cumulative(weights: list[float] | list[int]) -> list[float]:
    """Running totals, for `random.choices(cum_weights=)`.

    Precomputed on purpose: `random.choices(weights=)` rebuilds this on every
    call, measured at 1,113 us a draw against 4.3 us here.
    """
    out, running = [], 0.0
    for w in weights:
        running += w
        out.append(running)
    return out


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


#: What each world pack means. A published benchmark must not change under its
#: own name: `ng_supplier_v0` is what RESULTS.md was measured on and keeps
#: drawing from the pan-African lexicon, defect and all. N1 arrives as
#: `ng_supplier_v1`, and anyone comparing the two is comparing the fix.
WORLD_PACKS = {
    "ng_supplier_v0": {"countries": (), "names": "lexicon"},
    "ng_supplier_v1": {"countries": ("NG",), "names": "wikidata-pairs"},
    # N1b. Country conditioning cannot show up in a single-country world: a
    # Nigerian name cannot fail to predict a Nigerian city. Four countries, each
    # with its own name pool, cities, legal forms, phone shapes, banks and
    # registration identifier, is what makes "does a name predict where it is"
    # a question with an answer.
    "africa_supplier_v1": {"countries": ("NG", "KE", "GH", "ZA"),
                           "names": "wikidata-pairs"},
}


#: Zipf exponent for the surname draw. 1.0 is the classic Zipf law and gives a
#: heavy head: with 2,000 organisations over a few thousand ranked surnames,
#: the commonest surname lands on roughly 1 in 12. That is the collision rate
#: the `common_names` stratum exists to measure.
ZIPF_ALPHA = 1.0

#: Nigerian company-name furniture. Legal forms carry real weight here: the
#: suffix is the single most abbreviated, dropped and re-cased token in a
#: supplier master, which is exactly why `representation` is its own kind.
#: Used only by `ng_supplier_v0`, which predates the country profiles and must
#: keep generating exactly what RESULTS.md was measured on.
_LEGAL_FORMS = ["Limited", "Limited", "Limited", "Nigeria Limited", "Ventures Limited",
                "and Sons Limited", "Global Limited", "International Limited",
                "Enterprises", "Nigeria Enterprises"]
_V0_CITIES = {
    "Lagos": ["Ikeja", "Apapa", "Surulere", "Yaba", "Victoria Island", "Ojota"],
    "Kano": ["Fagge", "Nassarawa", "Dala", "Gwale", "Tarauni"],
    "Abuja": ["Garki", "Wuse", "Maitama", "Gwarinpa", "Utako"],
    "Port Harcourt": ["Diobu", "Trans Amadi", "GRA", "Rumuokoro"],
    "Ibadan": ["Bodija", "Dugbe", "Ring Road", "Mokola"],
    "Enugu": ["Independence Layout", "New Haven", "Ogui", "Achara Layout"],
}
_V0_STATES = {"Lagos": "Lagos", "Kano": "Kano", "Abuja": "FCT",
              "Port Harcourt": "Rivers", "Ibadan": "Oyo", "Enugu": "Enugu"}
_V0_STREETS = ["Zaria Road", "Awolowo Way", "Aminu Kano Crescent", "Ahmadu Bello Way",
               "Herbert Macaulay Street", "Murtala Muhammed Road", "Ikot Ekpene Road",
               "Nnamdi Azikiwe Street", "Marina Road", "Allen Avenue", "Broad Street"]
_V0_BANKS = ["Zenith Bank", "First Bank", "GTBank", "Access Bank", "UBA", "Fidelity Bank",
             "Union Bank", "Sterling Bank", "Ecobank", "Stanbic IBTC"]
_V0_TRADES = ["Engineering", "Logistics", "Supplies", "Agro", "Foods", "Petroleum",
              "Construction", "Technologies", "Pharmaceuticals", "Textiles", "Motors",
              "Chemicals", "Trading", "Farms", "Steel", "Printing", "Services", "Haulage"]
#: Widened from 18. Notebook 24 measured the generated naming vocabulary as
#: 2.8x thinner than a real register's at matched sample size, and the
#: descriptive middle -- what the company actually does -- is where the
#: shortfall sits.
_TRADES = ["Engineering", "Logistics", "Supplies", "Agro", "Foods", "Petroleum",
           "Construction", "Technologies", "Pharmaceuticals", "Textiles", "Motors",
           "Chemicals", "Trading", "Farms", "Steel", "Printing", "Services", "Haulage",
           "Fisheries", "Poultry", "Cement", "Plastics", "Packaging", "Timber",
           "Mining", "Energy", "Telecom", "Consulting", "Security", "Catering",
           "Garments", "Furniture", "Glass", "Paints", "Fertilisers", "Aluminium",
           "Beverages", "Dairy", "Milling", "Tyres", "Cables", "Roofing",
           "Plumbing", "Electricals", "Automotive", "Marine", "Aviation", "Freight",
           "Warehousing", "Refrigeration", "Irrigation", "Seeds", "Feeds", "Brewing"]



#: What differs by country, and it is more than the city list. A South African
#: company is a `(Pty) Ltd` and a Ghanaian one is not; a Kenyan supplier carries
#: a KRA PIN where a Nigerian one carries an RC number. Those are the signals a
#: matcher can learn from, and a world that shares them across countries teaches
#: nothing about where a record came from.
COUNTRY_PROFILES = {
    "NG": {
        "name": "Nigeria",
        "cities": {
            "Lagos": (["Ikeja", "Apapa", "Surulere", "Yaba", "Victoria Island"], "Lagos"),
            "Kano": (["Fagge", "Nassarawa", "Dala", "Gwale"], "Kano"),
            "Abuja": (["Garki", "Wuse", "Maitama", "Gwarinpa"], "FCT"),
            "Port Harcourt": (["Diobu", "Trans Amadi", "GRA"], "Rivers"),
            "Ibadan": (["Bodija", "Dugbe", "Ring Road"], "Oyo"),
            "Enugu": (["Independence Layout", "New Haven", "Ogui"], "Enugu"),
        },
        "streets": ["Zaria Road", "Awolowo Way", "Aminu Kano Crescent",
                    "Ahmadu Bello Way", "Herbert Macaulay Street", "Marina Road"],
        "forms": ["Limited", "Limited", "Nigeria Limited", "Ventures Limited",
                  "and Sons Limited", "Enterprises", "Plc"],
        "phones": ["0803", "0805", "0806", "0703", "0810", "0813", "0816", "0902"],
        "banks": ["Zenith Bank", "First Bank", "GTBank", "Access Bank", "UBA",
                  "Fidelity Bank", "Union Bank", "Sterling Bank"],
    },
    "KE": {
        "name": "Kenya",
        "cities": {
            "Nairobi": (["Westlands", "Karen", "Industrial Area", "Kilimani"], "Nairobi"),
            "Mombasa": (["Nyali", "Likoni", "Changamwe"], "Mombasa"),
            "Kisumu": (["Milimani", "Nyalenda", "Mamboleo"], "Kisumu"),
            "Nakuru": (["Lanet", "Naka", "Section 58"], "Nakuru"),
            "Eldoret": (["Langas", "Kapsoya", "Huruma"], "Uasin Gishu"),
        },
        "streets": ["Moi Avenue", "Kenyatta Avenue", "Ngong Road", "Thika Road",
                    "Haile Selassie Avenue", "Waiyaki Way"],
        "forms": ["Limited", "Limited", "Company Limited", "Ltd", "Enterprises",
                  "Holdings Limited"],
        "phones": ["0722", "0733", "0710", "0720", "0740", "0790"],
        "banks": ["Equity Bank", "KCB Bank", "Co-operative Bank", "NCBA Bank",
                  "Absa Bank Kenya", "Stanbic Bank Kenya"],
    },
    "GH": {
        "name": "Ghana",
        "cities": {
            "Accra": (["Osu", "Adabraka", "East Legon", "Dansoman"], "Greater Accra"),
            "Kumasi": (["Adum", "Asokwa", "Bantama"], "Ashanti"),
            "Takoradi": (["Market Circle", "Effia", "Anaji"], "Western"),
            "Tamale": (["Lamashegu", "Sagnarigu", "Vittin"], "Northern"),
        },
        "streets": ["Liberation Road", "Independence Avenue", "Ring Road Central",
                    "Oxford Street", "Spintex Road", "Kwame Nkrumah Avenue"],
        "forms": ["Limited", "Company Limited", "Limited", "Ltd", "Enterprise",
                  "Ventures Limited"],
        "phones": ["024", "054", "055", "059", "020", "050"],
        "banks": ["GCB Bank", "Ecobank Ghana", "Absa Bank Ghana",
                  "Fidelity Bank Ghana", "Stanbic Bank Ghana", "CalBank"],
    },
    "ZA": {
        "name": "South Africa",
        "cities": {
            "Johannesburg": (["Sandton", "Braamfontein", "Randburg", "Midrand"],
                             "Gauteng"),
            "Cape Town": (["Woodstock", "Claremont", "Bellville", "Century City"],
                          "Western Cape"),
            "Durban": (["Umhlanga", "Pinetown", "Westville"], "KwaZulu-Natal"),
            "Pretoria": (["Hatfield", "Centurion", "Arcadia"], "Gauteng"),
            "Gqeberha": (["Newton Park", "Walmer", "Summerstrand"], "Eastern Cape"),
        },
        "streets": ["Commissioner Street", "Long Street", "West Street",
                    "Church Street", "Rivonia Road", "Voortrekker Road"],
        # The distinctive one: a South African company is a (Pty) Ltd.
        "forms": ["(Pty) Ltd", "(Pty) Ltd", "Proprietary Limited",
                  "Holdings (Pty) Ltd", "CC", "Limited"],
        "phones": ["082", "083", "072", "074", "076", "084"],
        "banks": ["Standard Bank", "ABSA", "FNB", "Nedbank", "Capitec Bank",
                  "Investec"],
    },
}


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
    #: The countries this world was built for. Empty for `ng_supplier_v0`,
    #: which predates the country profiles: its places say `country: NG`, but
    #: it must draw from the original flat lists, not from NG's profile. Code
    #: downstream asks the world rather than inferring from a place, because
    #: inferring is exactly what silently changed every v0 world once.
    countries: tuple[str, ...] = ()
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
    """Names drawn from a country's own pool, with the frequencies it really has.

    **What changed, and why it was needed.** The first version drew a given name
    and a family name independently from one pan-African lexicon of 12,369
    entries, ranked by a seeded shuffle and weighted Zipf. That produced
    `Zubeyde Saliou` -- a Turkish given name on a West African surname -- and,
    measured against 51,022 real Nigerian facility names, **0.0% of generated
    name tokens carried regional signal against 90.4% of real ones**. Robin
    Linacre named the defect from the design; the notebook measured it.

    Now both halves come from the **same country's** pool, built from real
    given+family pairs on real people (Wikidata, CC0), and weighted by the
    frequency each name actually has in that pool rather than by an invented
    rank. Two things improve at once: a generated name is one a person from
    that country plausibly has, and the frequency distribution is
    `public-data-derived` instead of `synthetic-assumption`.

    **What it still does not do.** Nigeria's naming is Yoruba, Igbo, Hausa,
    Efik and more, and this conditions only on the country. Measured on the
    931 Nigerian pairs: 548 distinct given names and 653 distinct family names,
    with **zero repeated pairs** against 0.9 expected under independence -- the
    sample is too sparse to learn sub-national structure from, and its
    commonest given names (Joseph, Henry, John, Samuel) are Anglophone
    Christian names that genuinely cross Nigerian ethnic lines. So a Hausa
    given name can still meet an Igbo surname here. Conditioning at that level
    needs data this pull does not contain, and the world being single-country
    means country conditioning cannot show up in a name-predicts-city test
    either. Both are open; see the plan.
    """

    def __init__(self, rng: random.Random, country: str | None = None,
                 countries: tuple[str, ...] = ()) -> None:
        # A multi-country world needs one pool per country, so that a name can
        # carry information about where its owner is. `countries` builds those;
        # `country` is the single-country form v1 uses.
        self.pools: dict[str, Names] = {}
        if countries:
            for iso in countries:
                self.pools[iso] = Names(random.Random(rng.random() * 1e9), country=iso)
            self.country = countries[0]
            self.source = "wikidata:" + "+".join(countries)
            self.dropped = 0
            first = self.pools[countries[0]]
            self.given, self.family = first.given, first.family
            self._given_cw, self._family_cw = first._given_cw, first._family_cw
            self._rng = rng
            return
        self.country = country
        self.source = "lexicon"
        self.dropped = 0
        pairs = _pairs_path()
        if country and pairs is not None:
            given_counts: dict[str, int] = {}
            family_counts: dict[str, int] = {}
            with pairs.open(encoding="utf-8") as handle:
                for line in handle:
                    row = json.loads(line)
                    if row.get("country") != country:
                        continue
                    for value, counts in ((row["given"], given_counts),
                                          (row["family"], family_counts)):
                        if _usable(value):
                            counts[value] = counts.get(value, 0) + 1
            # A pool too thin to draw from would produce a handful of names
            # repeated thousands of times, which is worse than the defect it
            # was meant to fix.
            if len(given_counts) >= 100 and len(family_counts) >= 100:
                self.source = f"wikidata:{country}"
                # Two separate claims, and they need separate treatment.
                #
                # WHICH names exist and go together comes from real people, and
                # is `public-data-derived`. HOW CONCENTRATED the distribution is
                # cannot come from this sample: Wikidata holds *notable* people,
                # where almost every name occurs once or twice, and drawing on
                # those raw counts made the world far too easy -- 2.8% duplicate
                # company names at 4,000 suppliers against 12.0% in the real
                # register. A population is much more concentrated than its
                # celebrities.
                #
                # So the real counts decide the ORDER (which names are commoner)
                # and a Zipf curve supplies the SHAPE. The ordering is evidence;
                # the shape stays a declared assumption, and the manifest says
                # so on its own line.
                self.given = sorted(given_counts, key=lambda n: (-given_counts[n], n))
                self.family = sorted(family_counts, key=lambda n: (-family_counts[n], n))
                self._given_cw = self._zipf_cumulative(len(self.given))
                self._family_cw = self._zipf_cumulative(len(self.family))
                self._rng = rng
                return

        with gzip.open(_lexicon_path(), "rt", encoding="utf-8") as handle:
            rows = [json.loads(line) for line in handle]
        self.family = [r["name"] for r in rows
                       if r.get("name_type") == "family" and _usable(r["name"])]
        self.given = [r["name"] for r in rows
                      if r.get("name_type") != "family" and _usable(r["name"])]
        self.dropped = len(rows) - len(self.family) - len(self.given)
        rng.shuffle(self.family)
        rng.shuffle(self.given)
        # `cum_weights`, not `weights`. `random.choices(weights=...)` rebuilds
        # the cumulative distribution on EVERY call, which is O(12,369) per
        # name: measured at 1,113 us a draw against 4.3 us when the cumulative
        # weights are precomputed -- 257x, and the difference between a world
        # of 2,000 suppliers and one of 100,000.
        self._family_cw = self._zipf_cumulative(len(self.family))
        self._given_cw = self._zipf_cumulative(len(self.given))
        self._rng = rng

    @staticmethod
    def _zipf_cumulative(n: int) -> list[float]:
        return _cumulative([1.0 / ((i + 1) ** ZIPF_ALPHA) for i in range(n)])

    def _pool(self, country: str | None) -> Names:
        return self.pools.get(country, self) if country else self

    def surname(self, country: str | None = None) -> str:
        pool = self._pool(country)
        return pool._rng.choices(pool.family, cum_weights=pool._family_cw, k=1)[0]

    def given_name(self, country: str | None = None) -> str:
        pool = self._pool(country)
        return pool._rng.choices(pool.given, cum_weights=pool._given_cw, k=1)[0]

    def person(self, country: str | None = None) -> str:
        return f"{self.given_name(country)} {self.surname(country)}"


class Generator:
    """Seeded construction of a Nigerian supplier world."""

    def __init__(self, world_id: str, seed: int, country: str | None = None) -> None:
        pack = WORLD_PACKS.get(world_id, WORLD_PACKS["ng_supplier_v0"])
        self.countries = pack["countries"] if country is None else (country,)
        self.country = self.countries[0] if self.countries else None
        self.multi = len(self.countries) > 1
        self.rng = random.Random(seed)
        self.world = World(world_id=world_id, seed=seed, countries=self.countries)
        self.names = Names(random.Random(seed ^ 0x5EED),
                           country=None if self.multi else self.country,
                           countries=self.countries if self.multi else ())
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

    def phone(self, country: str | None = None) -> str:
        prefixes = (COUNTRY_PROFILES[country]["phones"] if country and self.multi
                    else ["0803", "0805", "0806", "0703", "0810", "0813", "0814",
                          "0816", "0701", "0902", "0903", "0905", "0704"])
        prefix = self.rng.choice(prefixes)
        rest = "".join(str(self.rng.randint(0, 9)) for _ in range(7))
        return f"{prefix} {rest[:3]} {rest[3:]}"

    def account(self, country: str | None = None) -> tuple[str, str]:
        banks = (COUNTRY_PROFILES[country]["banks"] if country and self.multi
                 else _V0_BANKS)
        return (self.rng.choice(banks),
                "".join(str(self.rng.randint(0, 9)) for _ in range(10)))

    # -- entities ------------------------------------------------------------

    def _new(self, entity_type: str, attributes: dict[str, Any], when: date) -> str:
        self._n[entity_type] += 1
        eid = entity_id(self.world.world_id, entity_type, self._n[entity_type])
        self.world.entities[eid] = Entity(eid, entity_type)
        self.world.states[eid] = [State(eid, when, None, attributes)]
        return eid

    def place(self) -> str:
        if not self.multi:
            city = self.rng.choice(list(_V0_CITIES))
            return self._new("place", {
                "street": f"{self.rng.randint(1, 240)} {self.rng.choice(_V0_STREETS)}",
                "area": self.rng.choice(_V0_CITIES[city]),
                "city": city,
                "state": _V0_STATES[city],
                "country": "NG",
            }, self.start)
        iso = self.rng.choice(self.countries)
        profile = COUNTRY_PROFILES[iso]
        city = self.rng.choice(list(profile["cities"]))
        areas, region = profile["cities"][city]
        return self._new("place", {
            "street": f"{self.rng.randint(1, 240)} {self.rng.choice(profile['streets'])}",
            "area": self.rng.choice(areas),
            "city": city,
            "state": region,
            "country": iso,
        }, self.start)

    def person(self, country: str | None = None) -> str:
        full = self.names.person(country)
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
        # The place is chosen first, and everything else follows from where it
        # is: the surname comes from that country's pool, the legal form from
        # its company law, the phone from its numbering plan, the bank from its
        # banks. That chain is the whole point of N1b -- it is what lets a name
        # carry information about where a record is from, which is what the
        # single-country world could not express.
        if self.multi:
            place = self.rng.choice(places)
            iso = self.world.current(place).attributes.get("country")
            profile = COUNTRY_PROFILES[iso]
            surname = self.names.surname(iso)
            trade = self.rng.choice(_TRADES)
            form = self.rng.choice(profile["forms"])
        else:
            # v0's original order, preserved exactly. Drawing the place first --
            # which the multi-country path must do, because the place decides
            # the country and the country decides the name -- consumes the
            # random stream differently and changes every v0 world.
            iso = None
            surname = self.names.surname()
            trade = self.rng.choice(_V0_TRADES)
            form = self.rng.choice(_LEGAL_FORMS)
            place = self.rng.choice(places)
        director = self.rng.choice(people)
        bank, account = self.account(iso)
        incorporated = self.start - timedelta(days=self.rng.randint(200, 5000))
        domain = {"NG": "com.ng", "KE": "co.ke", "GH": "com.gh",
                  "ZA": "co.za"}.get(iso or "NG", "com.ng")
        oid = self._new("organisation", {
            "legal_name": f"{surname} {trade} {form}",
            "rc_number": self.rc_number(),
            "tin": self.tin(),
            "phone": self.phone(iso),
            "email": f"info@{surname.lower()}{trade.lower()}.{domain}",
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
        people_ids = [self.person(self.rng.choice(self.countries) if self.multi else None)
                      for _ in range(people)]
        for _ in range(organisations):
            self.organisation(place_ids, people_ids)
        from_wikidata = self.names.source.startswith("wikidata")
        self.world.provenance.append({
            "asset": "given and family names",
            "source": ("Wikidata given+family pairs (CC0) for "
                       f"{'+'.join(self.countries)}, via datasets/pull_wikidata.py"
                       if from_wikidata else
                       "arche african_names_v1 lexicon (Wikidata/ParaNames, CC-BY-4.0)"),
            "method": ("pool and pairing from one country's real names; names "
                       "ordered by the frequency they have in that sample, then "
                       f"weighted Zipf alpha={ZIPF_ALPHA} for concentration"
                       if from_wikidata else
                       f"seeded rank shuffle, Zipf weighting alpha={ZIPF_ALPHA}"),
            "class": ("public-data-derived (which names exist and co-occur); "
                      "synthetic-assumption (how concentrated the distribution is)"
                      if from_wikidata else "synthetic-assumption"),
            "pool": f"{len(self.names.given):,} given, {len(self.names.family):,} family",
            "limitation": ("conditions on country only; Nigeria's Yoruba, Igbo and "
                           "Hausa naming are not separated, because the pull has "
                           "931 Nigerian pairs with zero repeats and cannot support it"
                           if from_wikidata else
                           "given and family names are drawn independently, so the "
                           "two halves of a name need not belong together"),
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
             places: int, country: str | None = None) -> World:
    """Build a world. Same arguments and seed produce the same world.

    ``country`` is normally left to the world pack; pass it only to override.
    """
    return Generator(world_id, seed, country=country).build(
        organisations, people, places)


__all__ = ["WORLD_PACKS", "Entity", "Generator", "Names", "Relationship",
           "State", "World",
           "ZIPF_ALPHA", "generate", "valid_rc", "valid_tin"]
