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

"""The HIPAA Safe Harbor pack loads, de-identifies the covered subset,
and cites § 164.514."""

from arche.policy import list_available_statutes, load_statute


def test_hipaa_available_and_loads():
    assert "HIPAA-SAFE-HARBOR" in list_available_statutes()
    s = load_statute("HIPAA-SAFE-HARBOR")
    assert s.statute_id == "HIPAA-SAFE-HARBOR"
    assert s.jurisdiction == "US"
    assert "164.514" in s.authority
    assert s.policy_mappings


def test_names_removed_and_cite_safe_harbor():
    s = load_statute("HIPAA-SAFE-HARBOR")
    action, ref, _ = s.action_for("PII-1-NAME")
    assert action == "mask"  # removed
    assert "164.514" in ref


def test_ip_is_removed_not_generalized():
    # Safe Harbor requires removal of IPs, unlike GDPR which generalises them.
    s = load_statute("HIPAA-SAFE-HARBOR")
    action, ref, _ = s.action_for("PII-8-IP_ADDRESS")
    assert action == "mask"
    assert "164.514" in ref


def test_biometric_and_face_dropped_high_tier():
    s = load_statute("HIPAA-SAFE-HARBOR")
    for cat in ("PII-6-BIOMETRIC", "PII-7-FACE_TEMPLATE"):
        action, _, _ = s.action_for(cat)
        assert action == "drop"
        assert s.tier_for(cat).value == "high"


def test_account_number_masked():
    s = load_statute("HIPAA-SAFE-HARBOR")
    action, _, _ = s.action_for("PII-5-BANK_ACCOUNT")
    assert action == "mask"


def test_unmapped_category_defaults_to_mask():
    # De-identification-safe default: mask everything unmapped.
    s = load_statute("HIPAA-SAFE-HARBOR")
    action, ref, rationale = s.action_for("PII-9-INVENTED")
    assert action == "mask"
    assert "164.514" in ref
    assert rationale is None


def test_covers_a_meaningful_subset():
    # Honesty gate: the pack must map a meaningful subset (>= 8 categories) or it
    # cannot credibly carry the HIPAA name (C1-T2 kill criterion).
    s = load_statute("HIPAA-SAFE-HARBOR")
    assert len(s.policy_mappings) >= 8
