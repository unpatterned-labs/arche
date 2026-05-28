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

"""Governance and compliance module — assess PII handling against jurisdiction rules.

Generates compliance reports that answer: What PII was found? What law applies?
What consent, retention, and transfer rules govern this data? What actions
are required?

Works with jurisdiction packs (e.g., Nigeria NDPA) and falls back to
conservative defaults for unknown jurisdictions.

Usage:
    from arche.governance import assess_compliance, ComplianceReport
    report = assess_compliance(evidence, pii_detections, jurisdiction="NG")
    print(report.summary)
    print(report.required_actions)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class PIIFinding:
    """A PII item found in the data with its compliance classification."""

    text_masked: str  # masked for safe logging
    pii_type: str
    sensitivity: str  # "high", "medium", "low"
    applicable_law: str
    consent_required: bool
    retention_limit: str
    cross_border_restriction: str
    recommended_action: str  # "encrypt", "redact", "flag_for_review", "ok"


@dataclass
class ComplianceReport:
    """Full compliance assessment for a set of identity evidence and PII."""

    jurisdiction: str
    law_name: str
    regulator: str
    total_pii_found: int
    high_sensitivity_count: int
    medium_sensitivity_count: int
    low_sensitivity_count: int
    findings: list[PIIFinding] = field(default_factory=list)
    required_actions: list[str] = field(default_factory=list)
    consent_status: str = "unknown"  # "obtained", "required", "not_applicable", "unknown"
    dpia_required: bool = False
    breach_notification_window: str = ""
    data_retention_summary: str = ""
    cross_border_summary: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def summary(self) -> str:
        """Human-readable compliance summary."""
        lines = [
            f"Compliance Report — {self.jurisdiction} ({self.law_name})",
            f"Regulator: {self.regulator}",
            f"PII found: {self.total_pii_found} "
            f"(high: {self.high_sensitivity_count}, "
            f"medium: {self.medium_sensitivity_count}, "
            f"low: {self.low_sensitivity_count})",
        ]
        if self.dpia_required:
            lines.append("DPIA: REQUIRED (high-risk processing detected)")
        if self.consent_status == "required":
            lines.append("Consent: REQUIRED before processing")
        if self.breach_notification_window:
            lines.append(f"Breach notification: {self.breach_notification_window}")
        if self.required_actions:
            lines.append(f"Required actions: {len(self.required_actions)}")
            for action in self.required_actions:
                lines.append(f"  - {action}")
        return "\n".join(lines)

    @property
    def is_compliant(self) -> bool:
        """Quick check: are there any outstanding required actions?"""
        return len(self.required_actions) == 0


# ═══════════════════════════════════════════════════════════════════════════════
# Sensitivity classification per jurisdiction
# ═══════════════════════════════════════════════════════════════════════════════

# Default sensitivity map (conservative — when jurisdiction unknown)
_DEFAULT_SENSITIVITY: dict[str, str] = {
    "nin": "high", "bvn": "high", "national_id": "high",
    "ghana_card": "high", "sa_id": "high", "kenya_id": "high",
    "aadhaar": "high", "ssn": "high", "passport_number": "high",
    "biometric": "high", "health_data": "high",
    "phone_number": "medium", "phone": "medium",
    "email": "medium", "date_of_birth": "medium",
    "address": "medium", "street_address": "medium",
    "account_number": "medium", "bank_account": "medium",
    "tin": "medium", "pvc": "medium",
    "person": "low", "first_name": "low", "last_name": "low",
    "full_name": "low", "gender": "low", "occupation": "low",
    "location": "low", "city": "low",
}

_DEFAULT_LAW = "General data protection principles"
_DEFAULT_REGULATOR = "National data protection authority"


def _mask_text(text: str) -> str:
    """Mask PII for safe logging."""
    if len(text) <= 4:
        return "***"
    return text[:3] + "*" * (len(text) - 3)


def _load_jurisdiction_compliance(jurisdiction: str) -> dict[str, Any]:
    """Load compliance metadata from a jurisdiction pack."""
    try:
        from .jurisdictions import get_profile
        profile = get_profile(jurisdiction)
        return profile.compliance_metadata
    except (ValueError, ImportError):
        return {}


def assess_compliance(
    evidence: list | None = None,
    pii_detections: list | None = None,
    *,
    jurisdiction: str = "auto",
    consent_obtained: bool = False,
) -> ComplianceReport:
    """Assess compliance of detected PII against jurisdiction rules.

    Parameters
    ----------
    evidence:
        List of IdentityEvidence or dicts with 'label' and 'text' keys.
    pii_detections:
        List of PIIDetection or dicts with 'pii_type' and 'text' keys.
    jurisdiction:
        ISO 3166-1 alpha-2 country code. "auto" infers from evidence.
    consent_obtained:
        Whether data subject consent has been obtained.

    Returns
    -------
    ComplianceReport
        Full compliance assessment with findings and required actions.
    """
    evidence = evidence or []
    pii_detections = pii_detections or []

    # Infer jurisdiction from evidence
    resolved_jurisdiction = jurisdiction.upper() if jurisdiction != "auto" else ""
    if not resolved_jurisdiction:
        for item in evidence:
            hint = (
                item.country_hint if hasattr(item, "country_hint")
                else item.get("country_hint", "") if isinstance(item, dict)
                else ""
            )
            if hint:
                resolved_jurisdiction = hint.upper()
                break

    # Load jurisdiction compliance rules
    compliance = _load_jurisdiction_compliance(resolved_jurisdiction)
    law_name = compliance.get("law", _DEFAULT_LAW)
    regulator = compliance.get("regulator", _DEFAULT_REGULATOR)
    breach_window = compliance.get(
        "key_requirements", {},
    ).get("breach_notification", "Report to authority without undue delay")

    # Sensitivity map from jurisdiction or default
    sensitivity_map = dict(_DEFAULT_SENSITIVITY)
    pii_cats = compliance.get("pii_categories", {})
    for level in ("high_sensitivity", "medium_sensitivity", "low_sensitivity"):
        cat_level = level.split("_")[0]
        for pii_type in pii_cats.get(level, []):
            sensitivity_map[pii_type.lower()] = cat_level

    # Retention rules
    retention = compliance.get("retention_limits", {})
    retention_summary = retention.get("default", "Retain only as long as necessary")

    # Cross-border rules
    cross_border = compliance.get(
        "key_requirements", {},
    ).get("cross_border_transfer", "Assess adequacy before transfer")

    # Classify all PII items
    findings: list[PIIFinding] = []
    high_count = 0
    medium_count = 0
    low_count = 0

    # From evidence
    for item in evidence:
        label = (
            item.label if hasattr(item, "label")
            else item.get("label", "") if isinstance(item, dict)
            else ""
        ).lower()
        text = (
            item.text if hasattr(item, "text")
            else item.get("text", "") if isinstance(item, dict)
            else ""
        )

        sensitivity = sensitivity_map.get(label, "")
        if not sensitivity:
            continue  # Not a PII type

        if sensitivity == "high":
            high_count += 1
        elif sensitivity == "medium":
            medium_count += 1
        else:
            low_count += 1

        # Determine recommended action
        if sensitivity == "high":
            action = "encrypt" if consent_obtained else "redact"
        elif sensitivity == "medium":
            action = "flag_for_review"
        else:
            action = "ok"

        # Retention for this type
        type_retention = retention_summary
        if label in ("account_number", "bank_account", "bvn"):
            type_retention = retention.get("financial_records", retention_summary)
        elif label in ("nin", "national_id"):
            type_retention = retention.get("kyc_records", retention_summary)
        elif label in ("health_data",):
            type_retention = retention.get("health_records", retention_summary)

        findings.append(PIIFinding(
            text_masked=_mask_text(text),
            pii_type=label,
            sensitivity=sensitivity,
            applicable_law=law_name,
            consent_required=sensitivity in ("high", "medium"),
            retention_limit=type_retention,
            cross_border_restriction=cross_border if sensitivity == "high" else "",
            recommended_action=action,
        ))

    # From PII detections
    for det in pii_detections:
        pii_type = (
            det.pii_type if hasattr(det, "pii_type")
            else det.get("pii_type", "") if isinstance(det, dict)
            else ""
        ).lower()
        text = (
            det.text if hasattr(det, "text")
            else det.get("text", "") if isinstance(det, dict)
            else ""
        )

        # Skip if already covered by evidence
        if any(f.pii_type == pii_type and f.text_masked == _mask_text(text) for f in findings):
            continue

        sensitivity = sensitivity_map.get(pii_type, "medium")
        if sensitivity == "high":
            high_count += 1
        elif sensitivity == "medium":
            medium_count += 1
        else:
            low_count += 1

        findings.append(PIIFinding(
            text_masked=_mask_text(text),
            pii_type=pii_type,
            sensitivity=sensitivity,
            applicable_law=law_name,
            consent_required=sensitivity in ("high", "medium"),
            retention_limit=retention_summary,
            cross_border_restriction=cross_border if sensitivity == "high" else "",
            recommended_action="encrypt" if sensitivity == "high" else "flag_for_review",
        ))

    total_pii = high_count + medium_count + low_count

    # Determine required actions
    required_actions: list[str] = []

    if high_count > 0 and not consent_obtained:
        required_actions.append(
            f"Obtain explicit consent: {high_count} high-sensitivity PII item(s) detected"
        )

    if high_count >= 3:
        required_actions.append(
            "Conduct Data Protection Impact Assessment (DPIA): "
            "large-scale high-sensitivity processing"
        )

    if any(f.sensitivity == "high" and f.recommended_action == "redact" for f in findings):
        required_actions.append(
            "Redact or encrypt high-sensitivity PII before storage/transfer"
        )

    if any(f.cross_border_restriction for f in findings):
        required_actions.append(
            f"Cross-border transfer restriction: {cross_border}"
        )

    # Build report
    return ComplianceReport(
        jurisdiction=resolved_jurisdiction or "UNKNOWN",
        law_name=law_name,
        regulator=regulator,
        total_pii_found=total_pii,
        high_sensitivity_count=high_count,
        medium_sensitivity_count=medium_count,
        low_sensitivity_count=low_count,
        findings=findings,
        required_actions=required_actions,
        consent_status="obtained" if consent_obtained else (
            "required" if high_count > 0 else "not_applicable"
        ),
        dpia_required=high_count >= 3,
        breach_notification_window=breach_window,
        data_retention_summary=retention_summary,
        cross_border_summary=cross_border,
    )
