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

"""G2: admin reverse geocoding (point-in-polygon) + fusion with containment."""

import pytest

pytest.importorskip("shapely")  # geo extra

from shapely.geometry import box  # noqa: E402

from arche.resolve._geo import AdminIndex, annotate_admin  # noqa: E402
from arche.resolve._matcher import compare_containment  # noqa: E402


def _index():
    # admin1: two states side by side. admin2: one LGA nested inside "Kano".
    kano = box(8.0, 11.0, 9.0, 12.0)     # (west, south, east, north)
    lagos = box(3.0, 6.0, 4.0, 7.0)
    ungogo = box(8.4, 11.9, 8.6, 12.0)   # small LGA inside Kano's north-west
    return AdminIndex({
        "admin1": [("Kano", kano), ("Lagos", lagos)],
        "admin2": [("Ungogo", ungogo)],
    })


def test_point_resolves_to_containing_state():
    path = annotate_admin(11.5, 8.5, _index())   # inside Kano only
    assert path == {"admin1": "Kano"}


def test_point_resolves_nested_lga():
    path = annotate_admin(11.95, 8.5, _index())  # inside Kano AND Ungogo
    assert path["admin1"] == "Kano"
    assert path["admin2"] == "Ungogo"


def test_point_outside_all_polygons_is_empty():
    assert annotate_admin(0.0, 0.0, _index()) == {}


def test_different_states_are_a_containment_disagreement():
    idx = _index()
    a = annotate_admin(11.5, 8.5, idx)   # Kano
    b = annotate_admin(6.5, 3.5, idx)    # Lagos
    # annotate feeds compare_containment directly; different admin1 -> veto.
    assert compare_containment(a, b) == 0.0


def test_same_state_is_positive_containment():
    idx = _index()
    a = annotate_admin(11.5, 8.5, idx)
    b = annotate_admin(11.6, 8.6, idx)   # both Kano
    assert compare_containment(a, b) == 0.3  # same admin1, no finer agreement


def test_annotate_admin_without_index_raises_cleanly(monkeypatch):
    # Simulate the geo extra missing: importing shapely fails.
    import builtins
    real_import = builtins.__import__

    def fake_import(name, *a, **k):
        if name == "shapely" or name.startswith("shapely."):
            raise ImportError("no shapely")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    with pytest.raises(ImportError, match="arche-core\\[geo\\]"):
        AdminIndex({"admin1": []})
