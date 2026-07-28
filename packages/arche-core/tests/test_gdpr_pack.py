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

"""C1-T1: the GDPR policy pack loads, validates, and cites GDPR Articles."""

from arche.policy import list_available_statutes, load_statute


def test_gdpr_is_available():
    assert "GDPR" in list_available_statutes()


def test_gdpr_loads_and_validates():
    # load_statute validates every action/tier at load time; reaching here means
    # the whole pack passed validation.
    s = load_statute("GDPR")
    assert s.statute_id == "GDPR"
    assert s.jurisdiction == "EU"
    assert s.breach_notification_window_hours == 72
    assert "EDPB" in s.authority or "European Data Protection Board" in s.authority
    assert s.policy_mappings  # non-empty


def test_gdpr_special_category_is_dropped_and_cites_art9():
    s = load_statute("GDPR")
    action, ref, rationale = s.action_for("PII-6-HEALTH")
    assert action == "drop"
    assert "Art 9" in ref
    assert rationale


def test_gdpr_name_tokenized_with_citation():
    s = load_statute("GDPR")
    action, ref, _ = s.action_for("PII-1-NAME")
    assert action == "tokenize"
    assert "GDPR" in ref


def test_gdpr_biometric_tier_is_high():
    s = load_statute("GDPR")
    assert s.tier_for("PII-6-BIOMETRIC").value == "high"


def test_gdpr_ip_is_personal_data_generalized():
    # CJEU Breyer: dynamic IPs are personal data.
    s = load_statute("GDPR")
    action, ref, _ = s.action_for("PII-8-IP_ADDRESS")
    assert action == "generalize"
    assert "Breyer" in ref or "Art 4" in ref


def test_gdpr_cross_border_bases_present():
    s = load_statute("GDPR")
    bases = s.cross_border_transfer.get("permitted_basis", [])
    assert "standard_contractual_clauses" in bases
    assert "adequacy_decision" in bases


def test_gdpr_unknown_category_falls_back_to_mask():
    s = load_statute("GDPR")
    action, ref, rationale = s.action_for("PII-9-INVENTED")
    assert action == "mask"  # default_action
    assert "GDPR" in ref
    assert rationale is None


def test_gdpr_company_registration_retained_public():
    s = load_statute("GDPR")
    action, _, _ = s.action_for("PII-2-RC")
    assert action == "retain"
