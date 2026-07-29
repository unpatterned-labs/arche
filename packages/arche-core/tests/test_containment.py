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

"""Tests for the admin-containment comparator (`compare_containment`)."""

from arche.resolve._matcher import compare_containment


def test_same_settlement_is_near_proof():
    a = {"admin1": "Kano", "admin2": "Ungogo", "settlement": "Karfi"}
    b = {"admin1": "Kano", "admin2": "Ungogo", "settlement": "Karfi"}
    assert compare_containment(a, b) == 1.0


def test_same_lga_different_settlement():
    a = {"admin1": "Kano", "admin2": "Ungogo", "settlement": "Karfi"}
    b = {"admin1": "Kano", "admin2": "Ungogo", "settlement": "Rimin Gado"}
    assert compare_containment(a, b) == 0.6


def test_same_state_different_lga_is_weak():
    a = {"admin1": "Kano", "admin2": "Ungogo"}
    b = {"admin1": "Kano", "admin2": "Nassarawa"}
    assert compare_containment(a, b) == 0.3


def test_different_state_is_disagreement_even_if_settlement_name_matches():
    # Coarse conflict is checked first: a shared settlement NAME across states
    # is a collision, not co-location.
    a = {"admin1": "Kano", "admin2": "Ungogo", "settlement": "Karfi"}
    b = {"admin1": "Lagos", "admin2": "Ikeja", "settlement": "Karfi"}
    assert compare_containment(a, b) == 0.0


def test_missing_paths_return_none():
    assert compare_containment(None, {"admin1": "Kano"}) is None
    assert compare_containment({}, {}) is None


def test_no_agreement_no_coarse_conflict_is_weak():
    a = {"admin2": "Ungogo"}
    b = {"admin2": "Nassarawa"}  # no admin1 on either -> no coarse conflict
    assert compare_containment(a, b) == 0.2


def test_normalises_case_and_diacritics():
    a = {"admin1": "Kano", "settlement": "Kofar Mata"}
    b = {"admin1": "kano", "settlement": "kofar  mata"}
    assert compare_containment(a, b) == 1.0
