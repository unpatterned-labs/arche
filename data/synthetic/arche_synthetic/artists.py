# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""The artist world — real alias sets, imperfect catalogues, exact truth.

    from arche_synthetic.artists import build
    world, manifest = build(seed=42, records=10_000, out=Path("worlds/artists_v0"))

What it is for
--------------
One experiment (plan §7d): *what is a name-variant list worth to a matcher?*
`Wizkid` and `Ayodeji Ibrahim Balogun` are one person and share no letters
that matter. No edit distance, no term frequency and no phonetic key will
ever put them together; only a list that says so can. This world exists to
measure how much that list buys, and what it costs.

Where the truth comes from
--------------------------
**Not invented.** Every alias group is a real artist with the alternate names
Wikidata records for them (CC0, pulled by `datasets/pull_wikidata.py aliases`).
Filler artists -- the crowd a real catalogue has -- are real people's names
from the same Wikidata pull, one name each. The generator decides *which*
alias each source uses and *what it does to it*; it never decides what an
artist is called.

That matters for the ablation's honesty. The variant list a matcher is given
comes from **MusicBrainz**, a different editorial community, so the list and
the truth can disagree. A list derived from the truth would win by
construction and prove nothing.

The three strata a difference can fall in
-----------------------------------------
- ``representation/alias`` -- two records name the artist differently and the
  names are not string-similar (Jaro-Winkler < 0.88). The list's whole case.
- ``representation/spelling`` -- different names, string-similar (`Wiz Kid`,
  `Wizkid`). A good matcher already handles these; the list should add
  little.
- ``error/<rule>`` -- a typo, a shouting catalogue, lost diacritics, a
  truncated field. Applied on top of whichever name the source chose.

The 0.88 boundary is Splink's own second Jaro-Winkler level, so a stratum
here maps onto a comparison level there.

Collisions
----------
Two *different* artists that share a name -- exactly, after casefolding -- are
recorded in ``collisions.parquet``. Nobody invented them: they are what the
data contains (the wrong-Tyla case, two artists both called Tyla). A false
merge on a collision pair is the cost a variant list is expected to have, and
the evaluator needs to be able to find those pairs to say what the cost was.

The file contract is the supplier world's: ``observations.parquet`` with no
truth column, ``truth.parquet``, ``differences.parquet``, a schema beside
each, and a manifest with content fingerprints and provenance.
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from . import export
from .ids import difference_id, entity_id, record_id
from .observe import CORRUPTION, REPRESENTATION, Difference, Observation
from .world import Entity, State, World

_REPO = Path(__file__).resolve().parents[3]
TRUTH = _REPO / "datasets" / "data" / "wikidata_artist_aliases.jsonl"
FILLER = _REPO / "datasets" / "data" / "wikidata_name_pairs.jsonl"

WORLD_PACK = "artists_v0"
COLUMNS = ("record_id", "source", "observed_at", "name", "country")
HORIZON = (date(2015, 1, 1), date(2026, 1, 1))

#: Splink's second Jaro-Winkler level. Above it two names are "spelling";
#: below it they are "alias", and only a list can bring them together.
SPELLING_BOUNDARY = 0.88

#: Wikidata's country labels for the alias pull, as ISO codes, so the two
#: pulls agree on how a country is written.
_ISO = {"Nigeria": "NG", "South Africa": "ZA", "Ghana": "GH", "Cameroon": "CM",
        "Uganda": "UG", "Tanzania": "TZ", "Ivory Coast": "CI", "Zimbabwe": "ZW",
        "Ethiopia": "ET", "Senegal": "SN", "Kenya": "KE", "Zambia": "ZM"}


# ------------------------------------------------------------- similarity --

def jaro_winkler(a: str, b: str) -> float:
    """Jaro-Winkler similarity, in-module so generation needs no matcher library.

    Standard definition: Jaro with a prefix bonus of 0.1 per shared leading
    character, up to four. Casefolded, because the stratum boundary is about
    what the names are, not how a catalogue capitalises them.
    """
    a, b = a.casefold(), b.casefold()
    if a == b:
        return 1.0
    if not a or not b:
        return 0.0
    window = max(len(a), len(b)) // 2 - 1
    match_a = [False] * len(a)
    match_b = [False] * len(b)
    matches = 0
    for i, ca in enumerate(a):
        lo, hi = max(0, i - window), min(len(b), i + window + 1)
        for j in range(lo, hi):
            if not match_b[j] and b[j] == ca:
                match_a[i] = match_b[j] = True
                matches += 1
                break
    if not matches:
        return 0.0
    transpositions = 0
    k = 0
    for i, ca in enumerate(a):
        if match_a[i]:
            while not match_b[k]:
                k += 1
            if ca != b[k]:
                transpositions += 1
            k += 1
    jaro = (matches / len(a) + matches / len(b)
            + (matches - transpositions / 2) / matches) / 3
    prefix = 0
    for ca, cb in zip(a[:4], b[:4], strict=False):
        if ca != cb:
            break
        prefix += 1
    return jaro + prefix * 0.1 * (1 - jaro)


# ------------------------------------------------------------- sources -----

@dataclass(frozen=True)
class ArtistSource:
    """One catalogue, and what it habitually does to a name.

    ``alias_bias`` is how the source picks which name to write: ``stage``
    prefers the canonical (stage) name, ``legal`` prefers the longest alias
    (which for a musician is usually the legal name), ``any`` is uniform.
    A press archive writes whatever the journalist used; a rights registry
    writes the legal name; a festival line-up writes the stage name in
    capitals.
    """

    name: str
    coverage: float
    repeats: tuple[int, int]
    alias_bias: str                  # stage | legal | any
    country_missing: float
    representation: dict[str, float]
    error: dict[str, float]


CATALOGUE = ArtistSource("catalogue", 0.90, (1, 2), "stage", 0.10,
                         {"diacritic_loss": 0.05}, {"typo": 0.01})
PRESS = ArtistSource("press", 0.60, (1, 3), "any", 0.40,
                     {"case_upper": 0.05, "diacritic_loss": 0.20}, {"typo": 0.03})
LINEUP = ArtistSource("lineup", 0.50, (1, 1), "stage", 0.70,
                      {"case_upper": 0.45}, {"truncation": 0.04, "typo": 0.02})
REGISTRY = ArtistSource("registry", 0.35, (1, 1), "legal", 0.05,
                        {"diacritic_loss": 0.30, "case_upper": 0.15}, {"typo": 0.02})
SOURCES = {s.name: s for s in (CATALOGUE, PRESS, LINEUP, REGISTRY)}


# ------------------------------------------------------------- loading -----

def load_truth(path: Path = TRUTH) -> list[dict[str, Any]]:
    """Wikidata alias groups: canonical, variants, country, Wikidata id."""
    groups = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        g = json.loads(line)
        names = [g["canonical"], *g.get("variants", [])]
        # Distinct after casefolding; a variant that only differs in case is
        # not an alias, it is a representation, and the sources supply those.
        seen: dict[str, str] = {}
        for n in names:
            key = n.casefold().strip()
            if key and key not in seen:
                seen[key] = n.strip()
        if len(seen) < 2:
            continue
        groups.append({"wikidata": g["entity_id"], "canonical": g["canonical"].strip(),
                       "names": list(seen.values()),
                       "country": _ISO.get(g.get("country", ""), g.get("country"))})
    return groups


def load_filler(path: Path = FILLER) -> list[dict[str, str]]:
    """Real people's names, one each, as the crowd around the alias groups."""
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        rows.append({"name": f"{r['given']} {r['family']}", "country": r["country"]})
    return rows


# ------------------------------------------------------------- generation --

class ArtistGenerator:
    """Builds a world of artists, observes it, and labels every disagreement."""

    def __init__(self, seed: int, *, records: int, world_id: str = WORLD_PACK,
                 truth_path: Path = TRUTH, filler_path: Path = FILLER) -> None:
        self.rng = random.Random(seed)
        self.world = World(world_id=world_id, seed=seed)
        self.records_target = records
        self.groups = load_truth(truth_path)
        self.filler = load_filler(filler_path)
        self._n = 0
        self._seq = 0
        # Truth-side memory of which name each record was *meant* to carry,
        # before any corruption. Never exported; it is what decides whether a
        # pair is an alias difference or a spelling one.
        self._intended: dict[str, str] = {}

    # -- entities ------------------------------------------------------------

    def _add(self, names: list[str], country: str | None, *, kind: str,
             wikidata: str | None = None) -> str:
        eid = entity_id(self.world.world_id, "artist", self._n)
        self._n += 1
        self.world.entities[eid] = Entity(eid, "artist")
        self.world.states[eid] = [State(eid, HORIZON[0], None, {
            "names": names, "canonical": names[0], "country": country,
            "kind": kind, "wikidata": wikidata})]
        return eid

    def populate(self) -> None:
        """Every alias group, then enough filler to reach the record target."""
        for g in self.groups:
            self._add(g["names"], g["country"], kind="alias", wikidata=g["wikidata"])
        # How many records the alias groups will produce, on average, decides
        # how much filler is needed. Estimated from the source parameters so
        # the target is approximately met rather than hit by trial.
        per_entity = sum(s.coverage * (s.repeats[0] + s.repeats[1]) / 2
                         for s in SOURCES.values())
        need = max(0, int(self.records_target / per_entity) - len(self.groups))
        pool = list(self.filler)
        self.rng.shuffle(pool)
        for row in pool[:need]:
            self._add([row["name"]], row["country"], kind="filler")

    # -- observation ---------------------------------------------------------

    def _choose_name(self, names: list[str], source: ArtistSource) -> str:
        if len(names) == 1 or source.alias_bias == "any":
            return self.rng.choice(names)
        if source.alias_bias == "legal":
            longest = max(names, key=len)
            return longest if self.rng.random() < 0.75 else self.rng.choice(names)
        # stage: the canonical most of the time, any alias otherwise
        return names[0] if self.rng.random() < 0.75 else self.rng.choice(names)

    def observe_one(self, eid: str, source: ArtistSource, when: date) -> Observation:
        state = self.world.states[eid][0]
        intended = self._choose_name(state.attributes["names"], source)
        value = intended
        applied: dict[str, list[tuple[str, str]]] = {"name": []}
        for rule, p in sorted(source.representation.items()):
            if self.rng.random() < p:
                out = REPRESENTATION[rule](value, self.rng)
                if out is not None and out != value:
                    value = out
                    applied["name"].append(("representation", rule))
        for rule, p in sorted(source.error.items()):
            if self.rng.random() < p:
                out = CORRUPTION[rule](value, self.rng)
                if out is not None and out != value:
                    value = out
                    applied["name"].append(("error", rule))
        attributes = {"name": value}
        if self.rng.random() >= source.country_missing and state.attributes["country"]:
            attributes["country"] = state.attributes["country"]
        rid = record_id(self.world.world_id, source.name, self._seq)
        self._seq += 1
        self._intended[rid] = intended
        return Observation(rid, source.name, when, attributes,
                           entity_id=eid, state_index=0, applied=applied)

    def observe(self) -> None:
        start, end = HORIZON
        span = (end - start).days
        out: list[Observation] = []
        for eid in sorted(self.world.entities):
            for source in SOURCES.values():
                if self.rng.random() >= source.coverage:
                    continue
                for _ in range(self.rng.randint(*source.repeats)):
                    when = start + timedelta(days=self.rng.randrange(span))
                    out.append(self.observe_one(eid, source, when))
        # Shuffle so record order carries nothing about entity membership.
        self.rng.shuffle(out)
        self.world.observations = out

    # -- labelling -----------------------------------------------------------

    def differences(self) -> None:
        """One row per (pair, kind): alias or spelling from the intended
        names, plus every corruption either record carries."""
        by_entity: dict[str, list[Observation]] = {}
        for o in self.world.observations:
            by_entity.setdefault(o.entity_id, []).append(o)
        out: list[Difference] = []
        for eid, group in sorted(by_entity.items()):
            group = sorted(group, key=lambda o: o.record_id)
            for i, a in enumerate(group):
                for b in group[i + 1:]:
                    if a.attributes["name"] == b.attributes["name"]:
                        continue
                    kinds: list[tuple[str, str]] = []
                    ia, ib = self._intended[a.record_id], self._intended[b.record_id]
                    if ia.casefold() != ib.casefold():
                        sim = jaro_winkler(ia, ib)
                        kinds.append(("representation",
                                      "spelling" if sim >= SPELLING_BOUNDARY else "alias"))
                    seen: set[tuple[str, str]] = set()
                    for note in (*a.applied.get("name", ()), *b.applied.get("name", ())):
                        if note not in seen:
                            seen.add(note)
                            kinds.append(note)
                    for kind, cause in kinds:
                        out.append(Difference(
                            difference_id(a.record_id, b.record_id, "name", kind),
                            eid, a.record_id, b.record_id, "name", kind, cause, None))
        self.world.differences = out

    def collisions(self) -> list[dict[str, Any]]:
        """Distinct entities that share a name exactly. Found, not made."""
        by_name: dict[str, set[str]] = {}
        for eid, chain in self.world.states.items():
            for n in chain[0].attributes["names"]:
                by_name.setdefault(n.casefold().strip(), set()).add(eid)
        rows = []
        for name, owners in sorted(by_name.items()):
            if len(owners) < 2:
                continue
            owners_sorted = sorted(owners)
            for i, a in enumerate(owners_sorted):
                for b in owners_sorted[i + 1:]:
                    rows.append({"entity_a": a, "entity_b": b, "shared_name": name,
                                 "kind_a": self.world.states[a][0].attributes["kind"],
                                 "kind_b": self.world.states[b][0].attributes["kind"]})
        return rows

    def build(self) -> World:
        self.populate()
        self.observe()
        self.differences()
        alias_entities = sum(1 for s in self.world.states.values()
                             if s[0].attributes["kind"] == "alias")
        self.world.provenance.append({
            "asset": "artist alias groups (the truth)",
            "source": ("Wikidata skos:altLabel for African musicians (CC0), via "
                       "datasets/pull_wikidata.py aliases"),
            "method": ("every alias group is a real artist; the generator chooses "
                       "which alias each source writes and what it does to it, never "
                       "what the artist is called"),
            "class": "public-data-derived",
            "pool": f"{alias_entities:,} artists with 2+ names",
            "limitation": ("Wikidata's alias coverage is uneven: well-known artists "
                           "carry legal names and stage names, lesser-known ones a "
                           "single spelling variant"),
        })
        self.world.provenance.append({
            "asset": "filler artists",
            "source": "Wikidata given+family pairs (CC0), via datasets/pull_wikidata.py names",
            "method": "one real name each, no aliases; only corruptions apply",
            "class": "public-data-derived",
            "pool": f"{len(self.world.states) - alias_entities:,} names",
        })
        self.world.provenance.append({
            "asset": "the variant list a matcher may be given",
            "source": "MusicBrainz alias sets (CC0), via datasets/artists_dataops/pull_musicbrainz.py",
            "method": ("joined to the truth by Wikidata P434, never by name; a "
                       "different editorial community from the one that supplied "
                       "the truth, so the two can disagree"),
            "class": "public-data-derived",
            "note": ("NOT used to build this world. It is the ablation's independent "
                     "variable and lives beside the world, not inside it"),
        })
        return self.world


# ------------------------------------------------------------- entry -------

def build(*, seed: int = 42, records: int = 10_000, out: Path | None = None,
          truth_path: Path = TRUTH, filler_path: Path = FILLER,
          generator_version: str = "0.0.1") -> tuple[World, dict[str, Any]]:
    """Generate the artist world and, with ``out``, write it."""
    gen = ArtistGenerator(seed, records=records, truth_path=truth_path,
                          filler_path=filler_path)
    world = gen.build()
    manifest: dict[str, Any] = {}
    if out is not None:
        collisions = gen.collisions()
        manifest = export.write(
            world, out, generator_version=generator_version, world_pack=WORLD_PACK,
            columns=COLUMNS, entity_type="artist",
            extra_tables={"collisions": (collisions,
                                         ["entity_a", "entity_b", "shared_name"])},
            notes={"horizon": [d.isoformat() for d in HORIZON],
                   "spelling_boundary": SPELLING_BOUNDARY,
                   "collisions": len(collisions)})
    return world, manifest


__all__ = ["COLUMNS", "HORIZON", "SOURCES", "SPELLING_BOUNDARY", "WORLD_PACK",
           "ArtistGenerator", "ArtistSource", "build", "jaro_winkler",
           "load_filler", "load_truth"]
