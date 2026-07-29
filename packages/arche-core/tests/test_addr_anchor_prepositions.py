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

"""D1: Nigerian address relation words (off / along) extract landmark anchors."""

from arche.addr.parse import _ANCHOR_PREPOSITIONS, parse_address


def _anchor(text: str) -> str | None:
    a = parse_address(text)
    return a.components.anchor if a else None


def test_off_road_extracts_anchor():
    anchor = _anchor("Zenith Bank, off Awolowo Road, Ikeja, Lagos")
    assert anchor is not None and "awolowo" in anchor.lower()


def test_along_road_extracts_anchor():
    anchor = _anchor("Shop 5, along Airport Road, Benin City, Edo")
    assert anchor is not None and "airport" in anchor.lower()


def test_off_landmark_type_extracts_anchor():
    anchor = _anchor("off the Total filling station, Ojota, Lagos")
    assert anchor is not None and "total" in anchor.lower()


def test_off_is_a_string_not_yaml_boolean():
    # Regression guard: bare `off` (also on/yes/no) is a YAML 1.1 boolean, so it
    # must be quoted in address_tokens.yaml or it loads as False and breaks the
    # preposition list. Assert it is present AND every entry is a string.
    assert "off" in _ANCHOR_PREPOSITIONS
    assert all(isinstance(p, str) for p in _ANCHOR_PREPOSITIONS)
