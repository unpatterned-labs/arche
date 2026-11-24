# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Which words name a place: the place list the address parser consults.

The parser reads an address by its order and punctuation. Where those run out
("22 Erinje Road Okitipupa", with no comma before the town, or "Dunkwa
Atechem", a town and then an area inside it) it asks this list whether some
words name a town, and how large a one. It never overrides the address's own
order: a place list only decides where to split.

The shipped list (``arche/_data/places_v1.json.gz``) comes from GeoNames
(CC BY 4.0): towns of 5,000 people or more everywhere, every state, region,
county and province, and for Nigeria, Kenya and Ghana every populated place,
the areas within towns GeoNames records, and the districts below the state.
Each town has a rank, so a city outranks a village of the same name:

    6 capital, 5 state seat or 100,000+, 4 district seat or 10,000+,
    3 any recorded population, 2 a village, 1 an area within a town

:func:`register_places` adds names to it at run time, for a list built from
one's own data.
"""

from __future__ import annotations

import gzip
import json
import re
from dataclasses import dataclass
from functools import lru_cache
from importlib import resources
from pathlib import Path

_FILE = "places_v1.json.gz"


@dataclass(frozen=True)
class Place:
    """What the list knows about a name, across every place that bears it."""

    town_rank: int = 0      # the highest rank of a town or area with this name; 0 if none
    region: bool = False    # a state, region, county or province is called this
    district: bool = False  # a district (an LGA, a sub-county) is called this
    focus_rank: int = 0     # as town_rank, counting only where the list is full


def fold(text: str) -> str:
    """Casefolded, with everything but letters and digits as single spaces."""
    return " ".join(re.sub(r"[^0-9a-z]+", " ", text.casefold()).split())


_extra: dict[str, Place] = {}


def _with(p: Place | None, *, town: int = 0, region: bool = False,
          district: bool = False, focus: int = 0) -> Place:
    p = p or Place()
    return Place(max(p.town_rank, town, focus), p.region or region,
                 p.district or district, max(p.focus_rank, focus))


def _merge(table: dict[str, Place], name: str, kind: str, rank: int) -> None:
    """A registered name: the caller's own data, so it counts as full coverage."""
    key = fold(name)
    if not key:
        return
    if kind in ("town", "area"):
        table[key] = _with(table.get(key), focus=rank)
    elif kind == "region":
        table[key] = _with(table.get(key), region=True)
    elif kind == "district":
        table[key] = _with(table.get(key), district=True)


@lru_cache(maxsize=1)
def _shipped() -> dict[str, Place]:
    with resources.files("arche._data").joinpath(_FILE).open("rb") as raw, \
            gzip.open(raw, "rt", encoding="utf-8") as fh:
        doc = json.load(fh)
    table: dict[str, Place] = {}
    # Shared instances for the common cases, so most names hold a reference
    # rather than an object of their own.
    town = {int(r): Place(int(r)) for r in doc["towns"]}
    focus = {int(r): Place(int(r), focus_rank=int(r)) for r in doc["focus_towns"]}
    for group, shared in (("towns", town), ("focus_towns", focus)):
        for rank, names in doc[group].items():
            r = int(rank)
            for key in names.split("\n"):
                p = table.get(key)
                if p is None:
                    table[key] = shared[r]
                elif group == "towns":
                    table[key] = _with(p, town=r)
                else:
                    table[key] = _with(p, focus=r)
    for key in doc["regions"].split("\n"):
        table[key] = _with(table.get(key), region=True)
    for key in doc["districts"].split("\n"):
        table[key] = _with(table.get(key), district=True)
    return table


def lookup(name: str) -> Place | None:
    """What the place list knows about ``name``, or ``None`` if nothing."""
    key = fold(name)
    shipped = _shipped().get(key)
    extra = _extra.get(key)
    if extra is None:
        return shipped
    return _with(shipped, town=extra.town_rank, region=extra.region,
                 district=extra.district, focus=extra.focus_rank)


def town_rank(name: str) -> int:
    """The rank of the largest town or area called ``name``; 0 if none."""
    p = lookup(name)
    return p.town_rank if p else 0


def focus_rank(name: str) -> int:
    """As :func:`town_rank`, counting only countries the list covers in full
    (Nigeria, Kenya, Ghana, and any names registered). Splitting text on a
    name is only safe where the list would know the whole if it were one
    place; elsewhere it holds only towns of 5,000 or more."""
    p = lookup(name)
    return p.focus_rank if p else 0


def register_places(source: str | Path | list[list]) -> int:
    """Add names to the place list for this process; returns how many.

    ``source`` is a JSON file, or its rows, each ``[name, country, kind, rank]``
    (a fifth column is ignored). ``kind`` is ``town``, ``area``, ``region`` or
    ``district``; ``rank`` is as in the module docstring. The added names
    supplement the shipped list and never lower a rank it gives.
    """
    if isinstance(source, (str, Path)):
        doc = json.loads(Path(source).read_text(encoding="utf-8"))
        rows = doc["rows"] if isinstance(doc, dict) else doc
    else:
        rows = source
    for row in rows:
        _merge(_extra, row[0], row[2], int(row[3]))
    return len(rows)


def clear_registered_places() -> None:
    """Remove every name :func:`register_places` added."""
    _extra.clear()


__all__ = ["Place", "clear_registered_places", "focus_rank", "fold", "lookup",
           "register_places", "town_rank"]
