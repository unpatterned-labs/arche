# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""The place world — a master sheet, requests that name places in it, exact truth.

    from arche_synthetic.places import build, PlaceBenchmark
    world, manifest = build(seed=42, sheet=500, requests=1000, out=Path("worlds/places_v0"))

    bench = PlaceBenchmark.load(Path("worlds/places_v0"))
    report = bench.score(policy=Policy())             # one policy, every request
    bench.sweep()                                     # the policy's numbers, measured

What it is for
--------------
``arche.resolve_place_request`` turns *"send it to the blue gate behind Elim
Pharmacy, 124 Elim Streat"* into a verified endpoint, one question, or a
refusal. Its :class:`~arche.addr.request.Policy` carries three numbers
(0.85 / 0.15 / 0.40) and one rule (a typo-tolerant match is a question) that
were **declared, not measured**. This world is the instrument that measures
them: a master sheet whose contents are known, requests whose endpoints are
known to be in it (or known not to be), and every endpoint labelled with
*how* the sentence rendered it.

The question the twin answers is not "is the resolver accurate". It is: at
these policy numbers, how often does a verified endpoint point at the wrong
door, and how many questions does that cost? That trade is the product.

Where the truth comes from
--------------------------
The sheet is generated -- streets, areas and cities from the supplier world's
country profiles, landmarks from the same banks and trades -- and that is a
declared assumption, stated in the manifest. What is *not* assumed is which
place a request means: every endpoint is constructed from a sheet row (or
deliberately from none), so the truth is by construction, exactly as in the
supplier and artist worlds.

Renderings (the ``cause`` column)
---------------------------------
Each endpoint is rendered one way, at a declared rate:

- ``exact``          the address as the sheet has it
- ``typo``           a misspelt street or suffix (the supplier world's corruptions)
- ``landmark``       relation + reference + access hint + the address
                     ("the blue gate behind Elim Pharmacy, 124 Elim Street")
- ``landmark_only``  relation + reference, no street ("behind Elim Pharmacy")
- ``partial``        the street without its number
- ``ambiguous``      a number on a street name the sheet has in two areas
- ``unknown``        an address that is not in the sheet at all -- the right
                     answer is a refusal, and a verification is the failure

``places_v1`` adds what ``places_v0`` could not measure:

- ``confusable``       the exact address on a street that has a near-twin in
                       the same area (`124 Elim Street` where `124 Elm Street`
                       also exists) -- the right answer is verified; the
                       margin between an exact and a typo-tolerant match is
                       what keeps it so
- ``confusable_typo``  a misspelling on such a street -- the right answer is
                       a question naming both
- ``unknown_confusable``  a number the sheet holds on `Elm Street` written
                       against `Elim Street`, where it holds no such number:
                       a door that is not in the sheet, one slip from one that
                       is. The right answer is a question or a refusal; with
                       the typo rule off and ``verified_at`` low, this is where
                       a wrong door gets verified
- landmarks that say which way they **face** (``front_bearing``), placed with
  one address on the side the sentence names and a decoy at the same
  distance on the other side, so *behind Elim Pharmacy* is only decidable
  by using the relation, not by proximity
- ``partial`` scored against the *which number?* question: right when the
  street the number is asked for is the street the sentence meant

The evaluator scores what the policy did against what it should have done,
per rendering, and sweeps the policy's numbers to show the trade.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from . import export
from .ids import content_fingerprint, record_id
from .observe import _typo
from .world import COUNTRY_PROFILES, Names, World

WORLD_PACK = "places_v0"
WORLD_PACK_V1 = "places_v1"
WORLD_PACKS = (WORLD_PACK, WORLD_PACK_V1)
COUNTRIES = ("NG", "KE")

#: How often each rendering is used. Declared, and the first thing to change
#: when a real request log says otherwise.
RENDERINGS: dict[str, float] = {
    "exact": 0.35, "typo": 0.15, "landmark": 0.15, "landmark_only": 0.08,
    "partial": 0.07, "ambiguous": 0.10, "unknown": 0.10,
}
RENDERINGS_V1: dict[str, float] = {
    "exact": 0.30, "typo": 0.12, "landmark": 0.13, "landmark_only": 0.08,
    "partial": 0.07, "ambiguous": 0.10, "unknown": 0.06,
    "confusable": 0.05, "confusable_typo": 0.05, "unknown_confusable": 0.04,
}
RENDERINGS_BY_VERSION = {0: RENDERINGS, 1: RENDERINGS_V1}
# Which relations name which side of a landmark, for a v1 sentence whose
# relation is chosen from where the address actually is.
_SIDE_RELATIONS = {"back": ("behind",), "front": ("opposite", "in front of"),
                   "side": ("next to", "beside")}

_LANDMARK_KINDS = {
    "pharmacy": ("{surname} Pharmacy", "{area} Pharmacy", "Elim Pharmacy", "Grace Pharmacy"),
    "bank": None,                       # from the country profile
    "church": ("{surname} Memorial Church", "St {given}'s Church", "Redeemed Church, {area}"),
    "mosque": ("{area} Central Mosque", "{surname} Mosque"),
    "filling station": ("{surname} Filling Station", "Total Filling Station, {area}",
                        "Mobil Filling Station"),
    "school": ("{area} Primary School", "{surname} College"),
    "market": ("{area} Market",),
}
_RELATIONS = ("behind", "opposite", "next to", "beside", "in front of", "after", "near")
_ACCESS = ("the blue gate", "the green door", "the side entrance", "the black gate",
           "the shop", "the kiosk", "the first gate", "the reception")
_VERBS = ("Send my package", "Deliver the parcel", "Pick up the goods", "Send it",
          "Ship the order", "Dispatch the box", "Bring the documents")
_TIMES = ("tomorrow", "today", "on Monday", "on Friday", "next Tuesday", "", "", "")


@dataclass(frozen=True)
class Endpoint:
    role: str                 # origin | destination
    place_id: str | None      # None for `unknown`
    rendering: str
    text: str


@dataclass(frozen=True)
class Request:
    request_id: str
    text: str
    action: str
    endpoints: tuple[Endpoint, ...]
    time_phrase: str


class PlaceGenerator:
    def __init__(self, seed: int, *, sheet: int, requests: int,
                 world_id: str | None = None, version: int = 0) -> None:
        self.version = version
        self.renderings = RENDERINGS_BY_VERSION[version]
        world_id = world_id or (WORLD_PACK if version == 0 else WORLD_PACK_V1)
        self.rng = random.Random(seed)
        self.world = World(world_id=world_id, seed=seed, countries=COUNTRIES)
        self.names = Names(random.Random(seed ^ 0x5EED), countries=COUNTRIES)
        self.n_sheet, self.n_requests = sheet, requests
        self.sheet: list[dict[str, Any]] = []
        self.landmarks: list[dict[str, Any]] = []
        self.requests: list[Request] = []
        self._seq = 0
        # streets that exist in two areas of one city, for `ambiguous`
        self._twins: list[tuple[dict, dict]] = []
        # rows on a street with a near-twin spelling in the same area (v1)
        self._confusables: list[dict] = []
        # (a row on the near-twin street, the original street's spelling) for
        # a door that exists only under the other spelling (v1)
        self._confusable_unknowns: list[tuple[dict, str]] = []
        # landmark id -> the side its anchor sits on (v1)
        self._anchor_side: dict[str, str] = {}

    # -- the sheet ---------------------------------------------------------------

    def _coords(self, city: str, area: str) -> tuple[float, float]:
        base = {"Lagos": (6.52, 3.38), "Kano": (12.0, 8.52), "Abuja": (9.06, 7.49),
                "Port Harcourt": (4.82, 7.03), "Ibadan": (7.38, 3.9), "Enugu": (6.45, 7.5),
                "Nairobi": (-1.29, 36.82), "Mombasa": (-4.04, 39.67), "Kisumu": (-0.09, 34.77),
                "Nakuru": (-0.30, 36.07), "Eldoret": (0.51, 35.27)}
        lat, lon = base.get(city, (0.0, 0.0))
        # A stable hash: Python's str hash is salted per process, and a
        # coordinate that moved between runs would break the fingerprint.
        import hashlib
        h = int(hashlib.sha256(f"{city}|{area}".encode()).hexdigest()[:6], 16) % 1000 / 1000.0
        return (round(lat + (h - 0.5) * 0.08 + self.rng.uniform(-0.004, 0.004), 5),
                round(lon + ((h * 7) % 1 - 0.5) * 0.08 + self.rng.uniform(-0.004, 0.004), 5))

    def _add_place(self, country: str, city: str, area: str, street: str,
                   number: str, *, kind: str = "address", name: str | None = None) -> dict:
        pid = f"gci:{kind}:{self._seq:05d}"
        self._seq += 1
        lat, lon = self._coords(city, area)
        display = name or f"{number} {street}"
        row = {"id": pid, "kind": kind, "name": display,
               "address": f"{display}, {area}, {city}" if kind == "address"
               else f"{street}, {area}, {city}",
               "street_number": number if kind == "address" else None,
               "street": street, "area": area, "city": city, "country": country,
               "lat": lat, "lon": lon}
        if self.version >= 1:
            row["front_bearing"] = None      # every row carries the column
        (self.sheet if kind == "address" else self.landmarks).append(row)
        return row

    @staticmethod
    def _offset(lat: float, lon: float, bearing_deg: float, metres: float) -> tuple[float, float]:
        import math

        b = math.radians(bearing_deg)
        dlat = metres * math.cos(b) / 111_320
        dlon = metres * math.sin(b) / (111_320 * math.cos(math.radians(lat)))
        return round(lat + dlat, 6), round(lon + dlon, 6)

    def _confusable_name(self, street: str) -> str | None:
        """A street one slip away from ``street`` that still reads as a street name."""
        from arche.resolve._matcher import _jaro_winkler

        head, _, suffix = street.rpartition(" ")
        if not head or len(head) < 4:
            return None
        for _ in range(8):
            bad = _typo(head, self.rng)
            if (bad and bad != head and all(w[:1].isupper() for w in bad.split())
                    and _jaro_winkler(bad.casefold(), head.casefold()) >= 0.85):
                return f"{bad} {suffix}"
        return None

    def _add_confusables(self) -> None:
        """A near-twin street beside some real ones: `Elim Street` gets an
        `Elim Street`-shaped neighbour, with the same number on it."""
        n = max(4, self.n_sheet // 40)
        for row in self.rng.sample(self.sheet, n):
            sibling = self._confusable_name(row["street"])
            if not sibling:
                continue
            same = self._add_place(row["country"], row["city"], row["area"], sibling,
                                   row["street_number"])
            for _ in range(2):
                number = str(self.rng.randint(1, 250))
                # The sentence carries no city: the number must be absent from
                # the original street *anywhere* in the sheet, or the door
                # exists after all.
                if any(r["street"] in (row["street"], sibling)
                       and r["street_number"] == number for r in self.sheet):
                    continue
                other = self._add_place(row["country"], row["city"], row["area"], sibling,
                                        number)
                # `other` exists on the sibling only; written against the
                # original spelling it names a door the sheet does not hold.
                self._confusable_unknowns.append((other, row["street"]))
            self._confusables.extend((row, same))

    def _place_landmark_v1(self, country: str, city: str, area: str, name: str,
                           anchor: dict) -> None:
        """A landmark that faces somewhere, an anchor on one side of it and a
        decoy at the same distance on the other, so the relation decides."""
        side = self.rng.choice(("back", "front", "side"))
        distance = self.rng.uniform(35, 70)
        to_anchor = self.rng.uniform(0, 360)
        lm_lat, lm_lon = self._offset(anchor["lat"], anchor["lon"], (to_anchor + 180) % 360,
                                      distance)
        facing = {"back": to_anchor - 180, "front": to_anchor,
                  "side": to_anchor - self.rng.choice((90, -90))}[side] % 360
        lm = self._add_place(country, city, area, anchor["street"],
                             str(int(anchor["street_number"]) + self.rng.choice((-2, 2))),
                             kind="landmark", name=name)
        lm["lat"], lm["lon"] = lm_lat, lm_lon
        lm["front_bearing"] = round(facing)
        lm["near"] = anchor["id"]
        self._anchor_side[lm["id"]] = side
        streets = [r["street"] for r in self.sheet if r["area"] == area and r["city"] == city]
        decoy = self._add_place(country, city, area, self.rng.choice(streets),
                                str(self.rng.randint(1, 250)))
        decoy["lat"], decoy["lon"] = self._offset(lm_lat, lm_lon, (to_anchor + 180) % 360,
                                                  distance)

    def populate(self) -> None:
        cities = [(c, city, areas, region)
                  for c in COUNTRIES for city, (areas, region) in
                  COUNTRY_PROFILES[c]["cities"].items()]
        # A few street names appear in two areas of one city on purpose.
        for _ in range(self.n_sheet):
            country, city, areas, _region = self.rng.choice(cities)
            area = self.rng.choice(areas)
            street = self.rng.choice(COUNTRY_PROFILES[country]["streets"])
            number = str(self.rng.randint(1, 250))
            if self.version >= 1 and any(
                    r["city"] == city and r["area"] == area and r["street"] == street
                    and r["street_number"] == number for r in self.sheet):
                continue                 # v1: no accidental duplicate doors
            self._add_place(country, city, area, street, number)
        # Twins on purpose: the same number on the same street in two areas of
        # one city. Real cities have them (every Nigerian city has an Awolowo
        # Way); the ambiguous rendering needs enough of them to measure.
        for row in self.rng.sample(self.sheet, min(30, len(self.sheet) // 10)):
            c_areas = COUNTRY_PROFILES[row["country"]]["cities"][row["city"]][0]
            others = [a for a in c_areas if a != row["area"]]
            if others:
                self._add_place(row["country"], row["city"], self.rng.choice(others),
                                row["street"], row["street_number"])
        by_key: dict[tuple[str, str, str], list[dict]] = {}
        for r in self.sheet:
            by_key.setdefault((r["city"], r["street"], r["street_number"]), []).append(r)
        for rows in by_key.values():
            areas = {r["area"] for r in rows}
            if len(areas) >= 2:
                a, b = sorted(rows, key=lambda r: r["area"])[:2]
                self._twins.append((a, b))
        # Landmarks: one or two per area, near an address row so `behind X`
        # is evidence for it.
        seen_areas = sorted({(r["country"], r["city"], r["area"]) for r in self.sheet})
        for country, city, area in seen_areas:
            for _ in range(self.rng.randint(1, 2)):
                kind = self.rng.choice(list(_LANDMARK_KINDS))
                if kind == "bank":
                    name = self.rng.choice(COUNTRY_PROFILES[country]["banks"])
                else:
                    tmpl = self.rng.choice(_LANDMARK_KINDS[kind])
                    name = tmpl.format(surname=self.names.surname(country),
                                       given=self.names.given_name(country), area=area)
                anchor = self.rng.choice([r for r in self.sheet if r["area"] == area
                                          and r["city"] == city])
                if self.version >= 1:
                    self._place_landmark_v1(country, city, area, name, anchor)
                    continue
                lm = self._add_place(country, city, area, anchor["street"],
                                     str(int(anchor["street_number"]) + self.rng.choice((-2, 2))),
                                     kind="landmark", name=name)
                # Within ~60 m of its anchor.
                lm["lat"] = round(anchor["lat"] + self.rng.uniform(-0.0004, 0.0004), 5)
                lm["lon"] = round(anchor["lon"] + self.rng.uniform(-0.0004, 0.0004), 5)
                lm["near"] = anchor["id"]
        if self.version >= 1:
            self._add_confusables()

    # -- rendering an endpoint -----------------------------------------------------

    def _render(self, row: dict, rendering: str) -> tuple[str, str | None]:
        """The endpoint text, and the place id it means (None for unknown)."""
        exact = f"{row['street_number']} {row['street']}"
        if rendering == "exact":
            return exact, row["id"]
        if rendering in ("typo", "confusable_typo"):
            street = row["street"]
            if self.rng.random() < 0.5:
                # misspell the suffix: Street -> Streat, Road -> Raod
                head, _, suffix = street.rpartition(" ")
                bad = _typo(suffix, self.rng) or suffix
                return f"{row['street_number']} {head} {bad}".strip(), row["id"]
            streets = {r["street"] for r in self.sheet} if self.version >= 1 else set()
            for _ in range(8):
                bad = _typo(street, self.rng) or street
                # A slip that lands on another real street is not a typo, it
                # is the other street; v1 does not call that one.
                if bad not in streets:
                    break
            return f"{row['street_number']} {bad}", row["id"]
        if rendering == "confusable":
            return exact, row["id"]        # the row has a near-twin street beside it
        if rendering == "unknown_confusable":
            other, original = self.rng.choice(self._confusable_unknowns)
            return f"{other['street_number']} {original}", None
        if rendering in ("landmark", "landmark_only"):
            near = [lm for lm in self.landmarks if lm.get("near") == row["id"]]
            if not near:
                return exact, row["id"]
            lm = self.rng.choice(near)
            side = self._anchor_side.get(lm["id"])
            rel = self.rng.choice(_SIDE_RELATIONS[side] if side else _RELATIONS)
            access = self.rng.choice(_ACCESS)
            if rendering == "landmark_only":
                return f"{rel} {lm['name']}", row["id"]
            return f"{access} {rel} {lm['name']}, {exact}", row["id"]
        if rendering == "partial":
            return row["street"], row["id"]
        if rendering == "ambiguous":
            return exact, row["id"]        # the row is one of a twin pair
        if rendering == "unknown":
            street = self.rng.choice(COUNTRY_PROFILES[row["country"]]["streets"])
            number = str(self.rng.randint(300, 999))   # sheet numbers stop at 250
            return f"{number} {street}", None
        raise ValueError(rendering)

    def _pick(self, rendering: str) -> dict:
        if rendering == "ambiguous" and self._twins:
            return self.rng.choice(self.rng.choice(self._twins))
        if rendering.startswith("confusable") and self._confusables:
            return self.rng.choice(self._confusables)
        if rendering in ("landmark", "landmark_only"):
            near = {lm.get("near") for lm in self.landmarks}
            anchored = [r for r in self.sheet if r["id"] in near]
            if anchored:
                return self.rng.choice(anchored)
        return self.rng.choice(self.sheet)

    def _rendering(self) -> str:
        return self.rng.choices(list(self.renderings),
                                weights=list(self.renderings.values()))[0]

    def make_requests(self) -> None:
        for _ in range(self.n_requests):
            o_r, d_r = self._rendering(), self._rendering()
            if not self._confusable_unknowns:      # a tiny sheet may have none
                o_r = "unknown" if o_r == "unknown_confusable" else o_r
                d_r = "unknown" if d_r == "unknown_confusable" else d_r
            o_row, d_row = self._pick(o_r), self._pick(d_r)
            if o_row is d_row:
                d_row = self._pick(d_r)
            o_text, o_id = self._render(o_row, o_r)
            d_text, d_id = self._render(d_row, d_r)
            when = self.rng.choice(_TIMES)
            verb = self.rng.choice(_VERBS)
            # The time phrase sits before the endpoints or after them, half
            # and half; either way it must not be read as part of a place.
            early = bool(when) and self.rng.random() < 0.5
            text = (f"{verb} {when if early else ''} from {o_text} to {d_text}"
                    f" {'' if early else when}.")
            text = " ".join(text.split()).replace(" .", ".")
            rid = record_id(self.world.world_id, "request", len(self.requests))
            self.requests.append(Request(
                rid, text, "create_delivery",
                (Endpoint("origin", o_id, o_r, o_text), Endpoint("destination", d_id, d_r, d_text)),
                when))

    def build(self) -> None:
        self.populate()
        self.make_requests()
        self.world.provenance.append({
            "asset": "the master sheet",
            "source": "generated: streets, areas and cities from the supplier world's "
                      "country profiles (NG, KE); landmark names from the same banks, "
                      "trades and name pools",
            "class": "synthetic-assumption (which places exist); public-data-derived "
                     "(the vocabulary they are made of)",
            "note": "no real address is in this sheet; coordinates are city-centred "
                    "jitter, landmarks sit within ~60 m of one address row",
        })
        self.world.provenance.append({
            "asset": "requests and their endpoints",
            "source": "generated from templates; every endpoint is a sheet row "
                      "rendered one declared way, or deliberately none",
            "class": "synthetic-assumption",
            "renderings": dict(self.renderings),
        })
        if self.version >= 1:
            self.world.provenance.append({
                "asset": "confusable streets, facing landmarks and decoys",
                "source": "generated: a near-twin spelling of some streets with the same "
                          "number on it; every landmark faces a declared bearing with its "
                          "anchor on one side and a decoy address at the same distance on "
                          "the other",
                "class": "synthetic-assumption",
                "note": "the relation in a landmark sentence is chosen from where the "
                        "anchor actually sits, so it is true by construction",
            })


# --------------------------------------------------------------- writing ------

def build(*, seed: int = 42, sheet: int = 500, requests: int = 1000,
          out: Path | None = None, generator_version: str = "0.0.1", version: int = 0,
          ) -> tuple[PlaceGenerator, dict[str, Any]]:
    gen = PlaceGenerator(seed, sheet=sheet, requests=requests, version=version)
    gen.build()
    manifest: dict[str, Any] = {}
    if out is not None:
        out.mkdir(parents=True, exist_ok=True)
        (out / "schema").mkdir(exist_ok=True)
        sheet_rows = [{k: v for k, v in r.items() if k != "near"}
                      for r in gen.sheet + gen.landmarks]
        request_rows = [{"request_id": r.request_id, "text": r.text, "action": r.action}
                        for r in gen.requests]
        truth_rows = [{"request_id": r.request_id, "role": e.role, "place_id": e.place_id,
                       "rendering": e.rendering, "endpoint_text": e.text,
                       "time_phrase": r.time_phrase}
                      for r in gen.requests for e in r.endpoints]
        tables = {"sheet": (sheet_rows, ["id", "kind", "name"]),
                  "requests": (request_rows, ["request_id", "text", "action"]),
                  "truth": (truth_rows, ["request_id", "role", "rendering"])}
        fingerprints = {}
        for name, (rows, required) in tables.items():
            export._write_parquet(out / f"{name}.parquet", rows)
            import json
            (out / "schema" / f"{name}.json").write_text(
                json.dumps(export._schema(name, rows, required), indent=2) + "\n",
                encoding="utf-8", newline="\n")
            fingerprints[name] = content_fingerprint(rows)
        import yaml
        counts = {}
        for e in truth_rows:
            counts[e["rendering"]] = counts.get(e["rendering"], 0) + 1
        manifest = {
            "world_id": gen.world.world_id, "world_pack": gen.world.world_id, "seed": seed,
            "generator_version": generator_version, "schema_version": version,
            "counts": {"sheet_addresses": len(gen.sheet), "landmarks": len(gen.landmarks),
                       "requests": len(gen.requests), "endpoints": len(truth_rows),
                       "twins": len(gen._twins), "confusables": len(gen._confusables) // 2,
                       "confusable_unknowns": len(gen._confusable_unknowns),
                       "renderings": dict(sorted(counts.items()))},
            "content_fingerprints": fingerprints,
            "provenance": gen.world.provenance,
            "invariants": [
                "requests.parquet carries no place id; the endpoint text is all a "
                "resolver sees",
                "every non-unknown endpoint names a row of sheet.parquet by construction",
                "unknown endpoints use street numbers above the sheet's range, so no "
                "accidental collision is possible",
            ] + (["unknown_confusable endpoints name a number the sheet holds only under "
                  "the near-twin spelling of the street, checked at generation"]
                 if version >= 1 else []),
        }
        (out / "manifest.yaml").write_text(
            yaml.safe_dump(manifest, sort_keys=False, allow_unicode=True),
            encoding="utf-8", newline="\n")
    return gen, manifest


# --------------------------------------------------------------- scoring ------

OUTCOMES = ("verified_right", "verified_wrong", "asked_right", "asked_wrong",
            "refused_known", "refused_right", "asked_unknown", "missed")


@dataclass
class PlaceBenchmark:
    world: Path
    sheet: list[dict[str, Any]]
    requests: list[dict[str, Any]]
    truth: dict[tuple[str, str], dict[str, Any]]     # (request_id, role) -> row

    @classmethod
    def load(cls, world: Path) -> PlaceBenchmark:
        import pyarrow.parquet as pq

        sheet = [{k: v for k, v in r.items() if v is not None}
                 for r in pq.read_table(world / "sheet.parquet").to_pylist()]
        requests = pq.read_table(world / "requests.parquet").to_pylist()
        truth = {(r["request_id"], r["role"]): r
                 for r in pq.read_table(world / "truth.parquet").to_pylist()}
        return cls(world, sheet, requests, truth)

    def _street(self, place_id: str | None) -> str | None:
        if not hasattr(self, "_by_id"):
            self._by_id = {r["id"]: r for r in self.sheet}
        row = self._by_id.get(place_id or "")
        return row.get("street") if row else None

    def outcome(self, endpoint: Any, truth: dict[str, Any]) -> str:
        want = truth["place_id"]
        status = endpoint.status
        cands = [c.place_id for c in endpoint.candidates]
        if want is None:
            return {"refused": "refused_right", "verified": "verified_wrong",
                    "clarification_required": "asked_unknown", "missing": "missed"}[status]
        if status == "verified":
            return "verified_right" if endpoint.chosen.place_id == want else "verified_wrong"
        if status == "clarification_required":
            if getattr(endpoint, "question_kind", None) == "number":
                # *Which number on Awolowo Way?* is right when the street the
                # number is asked for is the one the sentence meant.
                streets = {self._street(c) for c in cands}
                return "asked_right" if self._street(want) in streets else "asked_wrong"
            return "asked_right" if want in cands else "asked_wrong"
        if status == "refused":
            return "refused_known"
        return "missed"

    def top_is_right(self, endpoint: Any, truth: dict[str, Any]) -> bool:
        """For a question: is the place the sentence meant the first candidate?"""
        if endpoint.status != "clarification_required" or not endpoint.candidates:
            return False
        first = endpoint.candidates[0].place_id
        if getattr(endpoint, "question_kind", None) == "number":
            return self._street(first) == self._street(truth["place_id"])
        return first == truth["place_id"]

    def score(self, policy: Any = None, *, source: Any = None) -> dict[str, Any]:
        from arche.addr.request import MasterSheet, Policy, resolve_place_request

        policy = policy or Policy()
        source = source or MasterSheet(self.sheet)
        by_rendering: dict[str, dict[str, int]] = {}
        top_right: dict[str, int] = {}
        totals = dict.fromkeys(OUTCOMES, 0)
        questions = 0
        for req in self.requests:
            r = resolve_place_request(req["text"], action=req["action"], sources=[source],
                                      policy=policy, now=date(2026, 9, 13))
            for role in ("origin", "destination"):
                t = self.truth[(req["request_id"], role)]
                ep = r.endpoints.get(role)
                o = self.outcome(ep, t) if ep else "missed"
                by_rendering.setdefault(t["rendering"], dict.fromkeys(OUTCOMES, 0))[o] += 1
                totals[o] += 1
                questions += ep is not None and ep.status == "clarification_required"
                if ep is not None and self.top_is_right(ep, t):
                    top_right[t["rendering"]] = top_right.get(t["rendering"], 0) + 1
        n = sum(totals.values())
        return {
            "policy": {k: v for k, v in vars(policy).items()},
            "endpoints": n,
            "totals": totals,
            "verified_wrong_rate": round(totals["verified_wrong"] / n, 4),
            "verified_right_rate": round(totals["verified_right"] / n, 4),
            "question_rate": round(questions / n, 4),
            "by_rendering": {k: by_rendering[k] for k in sorted(by_rendering)},
            # Of the questions asked per rendering, how many had the right
            # place first: what the relation's geometry buys.
            "asked_top_right": {k: top_right.get(k, 0) for k in sorted(by_rendering)},
        }

    def sweep(self) -> list[dict[str, Any]]:
        """The trade the policy makes, across its numbers."""
        from arche.addr.request import Policy

        out = []
        for verified_at in (0.7, 0.8, 0.85, 0.9, 0.95):
            for typo in (True, False):
                rep = self.score(Policy(verified_at=verified_at, confirm_typo_matches=typo))
                out.append({"verified_at": verified_at, "confirm_typo_matches": typo,
                            "verified_right": rep["verified_right_rate"],
                            "verified_wrong": rep["verified_wrong_rate"],
                            "questions": rep["question_rate"]})
        return out


__all__ = ["COUNTRIES", "OUTCOMES", "RENDERINGS", "RENDERINGS_V1", "WORLD_PACK",
           "WORLD_PACKS", "WORLD_PACK_V1", "Endpoint", "PlaceBenchmark", "PlaceGenerator",
           "Request", "build"]
