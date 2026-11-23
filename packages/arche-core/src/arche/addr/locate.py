# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Name a point the way people and indexes do: a Plus Code and an H3 cell.

A coordinate pair is exact and unreadable. Two other names for the same point
are useful when matching places:

* a **Plus Code** (Open Location Code), the short code people write where there
  is no street address, ``7F4C2H2R+VR`` for a spot in central Kano. The encoder here is
  the open algorithm, implemented in full for code lengths 2 to 10 (a 10-digit
  code is a cell about 14 by 14 metres at the equator); it needs no service.
* an **H3 cell**, a hexagon in Uber's open grid. Neighbouring cells are cheap to
  enumerate, which makes H3 a blocking key: candidates in the same cell or a
  ring around it.

Neither is evidence that two records are one place. They inherit every error in
the coordinates they are computed from, so where two registries disagree about
where a facility is, their codes disagree too. They make a location readable
and indexable; whether it can be trusted is a property of the sources.

>>> plus_code(12.0, 8.5)
'7F4C2G22+22'
>>> plus_code(12.0, 8.5, length=6)
'7F4C2G00+'
"""

from __future__ import annotations

import math

_ALPHABET = "23456789CFGHJMPQRVWX"
_SEPARATOR_AT = 8
_PAIR_RESOLUTION = 8000  # 20**3: a 10-digit code is 1/8000 of a degree on each axis


def plus_code(lat: float, lon: float, *, length: int = 10) -> str:
    """The Plus Code (Open Location Code) of a point, ``length`` digits long.

    ``length`` is 2, 4, 6, 8 or 10. Latitude is clipped to [-90, 90] and
    longitude wrapped into [-180, 180), as the specification requires.
    """
    if length not in (2, 4, 6, 8, 10):
        raise ValueError("length must be 2, 4, 6, 8 or 10")
    lat, lon = float(lat), float(lon)
    if not (math.isfinite(lat) and math.isfinite(lon)):
        raise ValueError("coordinates must be finite numbers")
    lat = min(90.0, max(-90.0, lat))
    lon = ((lon + 180.0) % 360.0) - 180.0
    # Integer arithmetic over 1/8000-degree steps, rounded at 1e-6 first so a
    # value like 20.375 is not floored to the cell below by its float error.
    lat_steps = math.floor(round((lat + 90.0) * _PAIR_RESOLUTION, 6))
    lon_steps = math.floor(round((lon + 180.0) * _PAIR_RESOLUTION, 6))
    # The north pole belongs to the cell below it.
    lat_steps = min(lat_steps, 180 * _PAIR_RESOLUTION - 1)
    pairs = []
    for _ in range(5):
        pairs.append(_ALPHABET[lat_steps % 20] + _ALPHABET[lon_steps % 20])
        lat_steps //= 20
        lon_steps //= 20
    digits = "".join(reversed(pairs))[:length]
    if length < _SEPARATOR_AT:
        return digits + "0" * (_SEPARATOR_AT - length) + "+"
    return digits[:_SEPARATOR_AT] + "+" + digits[_SEPARATOR_AT:]


def h3_cell(lat: float, lon: float, *, resolution: int = 9) -> str:
    """The H3 cell containing a point (resolution 9 is about 0.1 km² per cell)."""
    import h3

    return h3.latlng_to_cell(float(lat), float(lon), resolution)


def h3_steps(a: str, b: str) -> int | None:
    """Grid steps between two H3 cells of one resolution; None if H3 cannot say."""
    import h3

    try:
        return int(h3.grid_distance(a, b))
    except Exception:  # noqa: BLE001 - H3 raises for cells too far apart to path
        return None


def locate(lat: float, lon: float, *, resolution: int = 9) -> dict[str, str]:
    """Both names for a point: ``{"plus_code": ..., "h3": ...}``."""
    return {"plus_code": plus_code(lat, lon), "h3": h3_cell(lat, lon, resolution=resolution)}


__all__ = ["h3_cell", "h3_steps", "locate", "plus_code"]
