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

"""v2 Core Types — Identity Intelligence Infrastructure.

These types standardize the SDK, API, MCP, and web interfaces.
They are a superset of the v1 types (Entity, PIIDetection, ResolvedEntity)
with added provenance, jurisdiction, and validator status.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# ── PII-sensitive labels (masked in repr/logs) ───────────────────────────────
PII_LABELS = {
    "PHONE", "EMAIL", "NATIONAL_ID", "ACCOUNT_NUMBER", "CREDIT_CARD",
    "SWIFT_BIC", "NIN", "BVN", "GHANA_CARD", "AADHAAR",
    "first_name", "last_name", "street_address", "postcode",
    "account_number", "swift_bic", "phone_number", "email",
    "date_of_birth", "ssn", "passport_number", "national_id",
}


def _safe_text(text: str, label: str) -> str:
    """Mask PII text for safe logging."""
    if label.lower() in {l.lower() for l in PII_LABELS} and len(text) > 3:
        return text[:3] + "***"
    return text


@dataclass
class IdentityEvidence:
    """An extracted identity fact with full provenance.

    This is the v2 replacement for ``Entity``, adding detector source,
    jurisdiction hints, and validator status.
    """

    text: str
    label: str              # Rich typed: first_name, last_name, street_address, city, phone_number, nin, bvn, etc.
    confidence: float
    start: int
    end: int
    detector_source: str = "regex"   # "regex", "gliner", "gliner-pii", "spacy", "fhir", "african"
    country_hint: str = ""           # ISO 3166-1 alpha-2 (from context or validator)
    validator_status: str = "unchecked"  # "valid", "invalid", "unchecked", "format_valid", "checksum_valid"
    document_id: str = ""            # Originating document or system
    metadata: dict = field(default_factory=dict)

    def __repr__(self) -> str:
        display = _safe_text(self.text, self.label)
        return (
            f"IdentityEvidence(text={display!r}, label={self.label!r}, "
            f"confidence={self.confidence:.2f}, source={self.detector_source!r})"
        )


@dataclass
class SensitiveSpan:
    """A PII/PHI span with adjudication result and redaction recommendation.

    This is the v2 replacement for ``PIIDetection``, adding multi-detector
    adjudication, validator status, and redaction recommendations.
    """

    text: str
    label: str              # NIGERIAN_NIN, PHONE_NUMBER, EMAIL, CREDIT_CARD, occupation, etc.
    confidence: float
    start: int
    end: int
    country_hint: str = ""
    validator_status: str = "unchecked"  # "checksum_valid", "format_valid", "unvalidated"
    detector_source: str = "regex"
    redaction: str = "mask"  # "mask", "hash", "remove", "review_required"

    def __repr__(self) -> str:
        display = _safe_text(self.text, self.label)
        return (
            f"SensitiveSpan(label={self.label!r}, text={display!r}, "
            f"confidence={self.confidence:.2f}, redaction={self.redaction!r})"
        )


@dataclass
class IdentityRecord:
    """A canonical resolved person profile with full evidence chain.

    This is the v2 replacement for ``ResolvedEntity``, adding structured
    fields, evidence provenance, and source system tracking.
    """

    cluster_id: str
    canonical_name: str
    names: list[str] = field(default_factory=list)
    identifiers: list[dict] = field(default_factory=list)   # [{system, value, country, type}]
    telecom: list[dict] = field(default_factory=list)        # [{system, value}]
    addresses: list[dict] = field(default_factory=list)
    demographics: dict = field(default_factory=dict)         # gender, birth_date, etc.
    source_systems: list[str] = field(default_factory=list)
    evidence: list[IdentityEvidence] = field(default_factory=list)
    confidence: float = 0.0
    match_reasons: list[str] = field(default_factory=list)

    def __repr__(self) -> str:
        return (
            f"IdentityRecord(name={self.canonical_name!r}, "
            f"sources={len(self.source_systems)}, confidence={self.confidence:.2f})"
        )


@dataclass
class MatchDecision:
    """An auditable resolution decision with factor breakdown.

    Used in the audit trail to explain WHY two records were matched.
    """

    cluster_id: str
    confidence: float
    factor_breakdown: dict = field(default_factory=dict)  # {name_similarity: 0.92, phone_match: 1.0}
    blocking_keys: list[str] = field(default_factory=list)
    evidence_summary: list[str] = field(default_factory=list)
    reviewer_explanation: str = ""  # Human-readable "why" for audit

    def __repr__(self) -> str:
        return f"MatchDecision(cluster={self.cluster_id!r}, confidence={self.confidence:.2f})"


@dataclass
class JurisdictionProfile:
    """A country pack: ID formats, validators, naming rules, phone norms.

    Shipped as versioned data + validators. Each country gets its own profile.
    """

    country_code: str       # ISO 3166-1 alpha-2
    country_name: str
    id_patterns: list[dict] = field(default_factory=list)
    phone_formats: list[dict] = field(default_factory=list)
    naming_conventions: list[dict] = field(default_factory=list)
    address_norms: dict = field(default_factory=dict)
    compliance_metadata: dict = field(default_factory=dict)  # NDPA, POPIA, GDPR applicability
    version: str = "0.1.0"

    def __repr__(self) -> str:
        return f"JurisdictionProfile(country={self.country_code!r}, v={self.version})"


# ── Adapters: v1 → v2 ────────────────────────────────────────────────────────

def entity_to_evidence(entity: Entity) -> IdentityEvidence:
    """Convert a v1 Entity to a v2 IdentityEvidence."""
    return IdentityEvidence(
        text=entity.text,
        label=entity.entity_type.lower(),
        confidence=entity.confidence,
        start=entity.start,
        end=entity.end,
        detector_source=entity.source,
        country_hint=entity.metadata.get("country", ""),
        validator_status="unchecked",
        document_id=entity.metadata.get("patient_id", ""),
        metadata=entity.metadata,
    )


def pii_to_sensitive_span(pii: PIIDetection) -> SensitiveSpan:
    """Convert a v1 PIIDetection to a v2 SensitiveSpan."""
    return SensitiveSpan(
        text=pii.text,
        label=pii.pii_type.lower(),
        confidence=pii.confidence,
        start=pii.start,
        end=pii.end,
        country_hint=pii.country or "",
        validator_status="unchecked",
        detector_source="regex",
        redaction="mask",
    )


def resolved_to_identity_record(resolved: ResolvedEntity) -> IdentityRecord:
    """Convert a v1 ResolvedEntity to a v2 IdentityRecord."""
    identifiers = []
    telecom = []
    addresses = []
    demographics: dict = {}

    for e in resolved.entities:
        if e.entity_type == "NATIONAL_ID":
            identifiers.append({
                "system": e.metadata.get("system", ""),
                "value": e.text,
                "country": e.metadata.get("country", ""),
                "type": e.metadata.get("id_type", "NATIONAL_ID"),
            })
        elif e.entity_type == "PHONE":
            telecom.append({"system": "phone", "value": e.text})
        elif e.entity_type == "EMAIL":
            telecom.append({"system": "email", "value": e.text})
        elif e.entity_type == "LOCATION":
            addresses.append({"text": e.text, **e.metadata})
        elif e.entity_type == "DATE" and e.metadata.get("date_type") == "birth":
            demographics["birth_date"] = e.text

    source_systems = list({
        e.metadata.get("patient_id", "") for e in resolved.entities
        if e.metadata.get("patient_id")
    })

    return IdentityRecord(
        cluster_id=f"cluster-{id(resolved)}",
        canonical_name=resolved.canonical_name,
        names=[resolved.canonical_name] + resolved.aliases,
        identifiers=identifiers,
        telecom=telecom,
        addresses=addresses,
        demographics=demographics,
        source_systems=source_systems,
        evidence=[entity_to_evidence(e) for e in resolved.entities],
        confidence=resolved.confidence,
        match_reasons=resolved.match_reasons,
    )
