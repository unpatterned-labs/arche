# Copyright 2026 unpatterned.org
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Admin reverse geocoding — turn a bare coordinate into a named admin path.

``annotate_admin(lat, lon, index)`` runs a point-in-polygon spatial join against
admin boundary layers (GADM / GRID3 settlement extents / Overture divisions) and
returns ``{level: name}`` for the containing polygons — enrichment that runs
*before* the comparators, so:

* ``compare_addresses`` gets real ``city`` / ``region`` / ``settlement``
  components instead of a bare lat/lon; and
* ``compare_containment`` can gate/veto on admin agreement, and admin-level
  blocking becomes possible.

The output ``{level: name}`` is exactly the shape ``compare_containment`` eats.
Needs ``shapely`` (the ``arche-core[geo]`` extra); an ``STRtree`` per level keeps
it fast on large polygon sets. This module never *stores* places — it points at
the polygon's name, resolver-not-registry.
"""

from __future__ import annotations

from typing import Any


def _require_shapely() -> Any:
    try:
        import shapely  # noqa: F401
        from shapely.geometry import Point
        from shapely.strtree import STRtree
    except ImportError as exc:  # pragma: no cover - exercised only without the extra
        raise ImportError(
            "annotate_admin needs shapely — install the geo extra: "
            "pip install arche-core[geo]"
        ) from exc
    return Point, STRtree


class _AdminLayer:
    """One admin level as an STRtree of named polygons."""

    def __init__(self, level: str, features: list[tuple[str, Any]], strtree_cls: Any) -> None:
        self.level = level
        self._names: list[str] = []
        self._geoms: list[Any] = []
        for name, geom in features:
            self._names.append(name)
            self._geoms.append(geom)
        self._tree = strtree_cls(self._geoms) if self._geoms else None

    def locate(self, point: Any) -> str | None:
        if self._tree is None:
            return None
        # STRtree.query returns indices of geometries whose bbox intersects the
        # point; confirm true containment before claiming the name.
        for idx in self._tree.query(point):
            if self._geoms[int(idx)].contains(point):
                return self._names[int(idx)]
        return None


class AdminIndex:
    """Point-in-polygon reverse geocoder over one or more admin levels.

    Build once from admin polygon layers, reuse for every coordinate::

        idx = AdminIndex({
            "admin1": [("Kano", kano_polygon), ("Lagos", lagos_polygon)],
            "admin2": [("Ungogo", ungogo_polygon), ...],
        })
        idx.annotate(12.05, 8.52)   # -> {"admin1": "Kano", "admin2": "Ungogo"}

    ``features`` values are ``(name, shapely_geometry)`` pairs.
    """

    def __init__(self, layers: dict[str, list[tuple[str, Any]]]) -> None:
        self._point_cls, strtree_cls = _require_shapely()
        # Preserve the caller's level ordering (coarse -> fine) in the output.
        self._layers = {
            level: _AdminLayer(level, list(features), strtree_cls)
            for level, features in layers.items()
        }

    def annotate(self, lat: float, lon: float) -> dict[str, str]:
        """Return ``{level: name}`` for every admin polygon containing (lat, lon)."""
        pt = self._point_cls(lon, lat)  # shapely is (x=lon, y=lat)
        path: dict[str, str] = {}
        for level, layer in self._layers.items():
            hit = layer.locate(pt)
            if hit is not None:
                path[level] = hit
        return path


def annotate_admin(lat: float, lon: float, index: AdminIndex) -> dict[str, str]:
    """Reverse-geocode a coordinate to its admin path via a prebuilt ``AdminIndex``."""
    return index.annotate(lat, lon)
