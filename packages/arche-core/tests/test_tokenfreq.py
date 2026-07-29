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

"""corpus term-frequency token weighting (`TokenFrequencyTable`)."""

from arche.resolve._tokenfreq import TokenFrequencyTable

# A facility-name corpus where "central" / "general" / "phc" are COMMON and
# "karfi" / "gyaranya" / "kofar" / "mata" are RARE (appear once).
_CORPUS = [
    "Karfi PHC", "Central PHC", "Central Hospital", "General Hospital",
    "General Dispensary", "Gyaranya Clinic", "Central Clinic", "PHC Central",
    "Kofar Mata Dispensary", "Central Primary Health Centre",
]


def _tf() -> TokenFrequencyTable:
    return TokenFrequencyTable.from_corpus(_CORPUS)


def test_common_token_more_frequent_than_rare():
    tf = _tf()
    assert tf.rel_freq("central") > tf.rel_freq("karfi")


def test_rare_token_is_more_distinctive_than_common():
    tf = _tf()
    assert tf.distinctiveness("karfi") > tf.distinctiveness("central")
    assert 0.0 <= tf.distinctiveness("central") <= tf.distinctiveness("karfi") <= 1.0


def test_unseen_token_uses_floor_and_is_highly_distinctive():
    tf = _tf()
    assert tf.rel_freq("zzznovel") == tf._floor
    assert tf.distinctiveness("zzznovel") > 0.5


def test_shared_rare_token_beats_shared_common_token():
    # The core property: agreeing on a rare name is stronger evidence than
    # agreeing on a common one, even with the same non-shared remainder.
    tf = _tf()
    rare = tf.weighted_token_sim("Karfi PHC", "Karfi Clinic")       # share "karfi"
    common = tf.weighted_token_sim("Central PHC", "Central Clinic")  # share "central"
    assert rare > common


def test_normalisation_case_and_diacritics():
    tf = _tf()
    assert tf.weighted_token_sim("KARFI phc", "Kárfi  PHC") == 1.0


def test_empty_side_is_zero():
    tf = _tf()
    assert tf.weighted_token_sim("", "Karfi") == 0.0


def test_common_u_map_returns_frequent_tokens_only():
    # min_freq scales with corpus size; in this tiny corpus a single-occurrence
    # token is still ~0.02, so use a threshold that separates common from rare.
    tf = _tf()
    common = tf.common_u_map(min_freq=0.1)
    assert "central" in common          # frequent (~0.22)
    assert "gyaranya" not in common     # rare (single occurrence, ~0.02)


def test_u_for_frequent_is_higher_than_rare():
    # u = P(agree | non-match): frequent token -> weak evidence -> higher u.
    tf = _tf()
    assert tf.u_for("central") > tf.u_for("karfi")
