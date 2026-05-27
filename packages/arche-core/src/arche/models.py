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

"""Pydantic v2 models — the canonical types for SDK, API, MCP, and web.

These mirror the dataclass types in ``types.py`` but use Pydantic BaseModel
for automatic validation, serialization, and OpenAPI schema generation.

Backward compatible: the dataclass types in ``types.py`` still work.
Use ``from arche.models import ...`` for Pydantic variants.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from .extract import Entity
    from .protect import PIIDetection
    from .resolve import ResolvedEntity
    from .types import IdentityEvidence, IdentityRecord, SensitiveSpan


# ── PII-safe display ────────────────────────────────────────────────────────

_PII_LABELS = {
    "phone", "email", "national_id", "account_number", "credit_card",
    "swift_bic", "nin", "bvn", "ghana_card", "aadhaar",
    "first_name", "last_name", "street_address", "postcode",
    "phone_number", "date_of_birth", "ssn", "passport_number",
}


def _mask(text: str, label: str) -> str:
    if label.lower() in _PII_LABELS and len(text) > 3:
        return text[:3] + "***"
    return text


# ═══════════════════════════════════════════════════════════════════════════════
# Core Identity Types
# ═══════════════════════════════════════════════════════════════════════════════


class IdentityEvidenceModel(BaseModel):
    """An extracted identity fact with full provenance."""

    text: str
    label: str = Field(description="Rich typed label: first_name, nin, phone_number, etc.")
    confidence: float = Field(ge=0.0, le=1.0)
    start: int = Field(ge=0)
    end: int = Field(ge=0)
    detector_source: str = Field(
        default="regex",
        description="Origin detector: regex, gliner, african, fhir, spacy",
    )
    country_hint: str = Field(default="", description="ISO 3166-1 alpha-2")
    validator_status: str = Field(
        default="unchecked",
        description="valid | invalid | unchecked | format_valid | checksum_valid",
    )
    document_id: str = Field(default="", description="Originating document or system")
    metadata: dict[str, Any] = Field(default_factory=dict)

    def __repr__(self) -> str:
        return (
            f"IdentityEvidence(text={_mask(self.text, self.label)!r}, "
            f"label={self.label!r}, confidence={self.confidence:.2f})"
        )

    model_config = {"frozen": False, "extra": "allow"}


class SensitiveSpanModel(BaseModel):
    """A PII/PHI span with adjudication and redaction recommendation."""

    text: str
    label: str
    confidence: float = Field(ge=0.0, le=1.0)
    start: int = Field(ge=0)
    end: int = Field(ge=0)
    country_hint: str = ""
    validator_status: str = "unchecked"
    detector_source: str = "regex"
    redaction: str = Field(
        default="mask",
        description="Recommended action: mask | hash | remove | review_required",
    )

    def __repr__(self) -> str:
        return (
            f"SensitiveSpan(label={self.label!r}, "
            f"text={_mask(self.text, self.label)!r}, "
            f"confidence={self.confidence:.2f})"
        )

    model_config = {"frozen": False, "extra": "allow"}


class MatchDecisionModel(BaseModel):
    """An auditable resolution decision with factor breakdown."""

    cluster_id: str
    confidence: float = Field(ge=0.0, le=1.0)
    factor_breakdown: dict[str, float] = Field(
        default_factory=dict,
        description="E.g. {name_similarity: 0.92, phone_match: 1.0}",
    )
    blocking_keys: list[str] = Field(default_factory=list)
    evidence_summary: list[str] = Field(default_factory=list)
    reviewer_explanation: str = Field(
        default="",
        description="Human-readable 'why' for audit trail",
    )

    model_config = {"frozen": False}


class IdentityRecordModel(BaseModel):
    """A canonical resolved person profile with full evidence chain."""

    cluster_id: str
    canonical_name: str
    names: list[str] = Field(default_factory=list, description="All name variants")
    identifiers: list[dict[str, Any]] = Field(
        default_factory=list,
        description="[{system, value, country, type}]",
    )
    telecom: list[dict[str, Any]] = Field(
        default_factory=list,
        description="[{system, value}]",
    )
    addresses: list[dict[str, Any]] = Field(default_factory=list)
    demographics: dict[str, Any] = Field(
        default_factory=dict,
        description="gender, birth_date, etc.",
    )
    source_systems: list[str] = Field(default_factory=list)
    evidence: list[IdentityEvidenceModel] = Field(default_factory=list)
    match_decision: MatchDecisionModel | None = Field(
        default=None,
        description="How this record was resolved — the audit trail",
    )
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    match_reasons: list[str] = Field(default_factory=list)

    def __repr__(self) -> str:
        return (
            f"IdentityRecord(name={self.canonical_name!r}, "
            f"sources={len(self.source_systems)}, confidence={self.confidence:.2f})"
        )

    model_config = {"frozen": False, "extra": "allow"}


class JurisdictionProfileModel(BaseModel):
    """A country pack: ID formats, validators, naming rules, phone norms, compliance."""

    country_code: str = Field(description="ISO 3166-1 alpha-2")
    country_name: str
    id_patterns: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Regex + checksum validators per ID type",
    )
    phone_formats: list[dict[str, Any]] = Field(default_factory=list)
    naming_conventions: list[dict[str, Any]] = Field(default_factory=list)
    address_norms: dict[str, Any] = Field(default_factory=dict)
    compliance_metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="NDPA, POPIA, GDPR applicability",
    )
    version: str = "0.1.0"

    def __repr__(self) -> str:
        return f"JurisdictionProfile(country={self.country_code!r}, v={self.version})"

    model_config = {"frozen": False}


# ═══════════════════════════════════════════════════════════════════════════════
# Adapters: dataclass ↔ Pydantic
# ═══════════════════════════════════════════════════════════════════════════════


def evidence_from_dataclass(dc: IdentityEvidence) -> IdentityEvidenceModel:
    """Convert a dataclass IdentityEvidence to a Pydantic model."""
    return IdentityEvidenceModel(
        text=dc.text,
        label=dc.label,
        confidence=dc.confidence,
        start=dc.start,
        end=dc.end,
        detector_source=dc.detector_source,
        country_hint=dc.country_hint,
        validator_status=dc.validator_status,
        document_id=dc.document_id,
        metadata=dc.metadata,
    )


def evidence_to_dataclass(model: IdentityEvidenceModel) -> IdentityEvidence:
    """Convert a Pydantic IdentityEvidenceModel to a dataclass."""
    from .types import IdentityEvidence

    return IdentityEvidence(
        text=model.text,
        label=model.label,
        confidence=model.confidence,
        start=model.start,
        end=model.end,
        detector_source=model.detector_source,
        country_hint=model.country_hint,
        validator_status=model.validator_status,
        document_id=model.document_id,
        metadata=model.metadata,
    )


def record_from_dataclass(dc: IdentityRecord) -> IdentityRecordModel:
    """Convert a dataclass IdentityRecord to a Pydantic model."""
    return IdentityRecordModel(
        cluster_id=dc.cluster_id,
        canonical_name=dc.canonical_name,
        names=dc.names,
        identifiers=dc.identifiers,
        telecom=dc.telecom,
        addresses=dc.addresses,
        demographics=dc.demographics,
        source_systems=dc.source_systems,
        evidence=[evidence_from_dataclass(e) for e in dc.evidence],
        confidence=dc.confidence,
        match_reasons=dc.match_reasons,
    )


def span_from_dataclass(dc: SensitiveSpan) -> SensitiveSpanModel:
    """Convert a dataclass SensitiveSpan to a Pydantic model."""
    return SensitiveSpanModel(
        text=dc.text,
        label=dc.label,
        confidence=dc.confidence,
        start=dc.start,
        end=dc.end,
        country_hint=dc.country_hint,
        validator_status=dc.validator_status,
        detector_source=dc.detector_source,
        redaction=dc.redaction,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Adapters: v1 types → Pydantic v2 models
# ═══════════════════════════════════════════════════════════════════════════════


def entity_to_evidence_model(entity: Entity) -> IdentityEvidenceModel:
    """Convert a v1 Entity to a Pydantic IdentityEvidenceModel."""
    return IdentityEvidenceModel(
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


def pii_to_span_model(pii: PIIDetection) -> SensitiveSpanModel:
    """Convert a v1 PIIDetection to a Pydantic SensitiveSpanModel."""
    return SensitiveSpanModel(
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


def resolved_to_record_model(resolved: ResolvedEntity) -> IdentityRecordModel:
    """Convert a v1 ResolvedEntity to a Pydantic IdentityRecordModel."""
    identifiers: list[dict] = []
    telecom: list[dict] = []
    addresses: list[dict] = []
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

    return IdentityRecordModel(
        cluster_id=f"cluster-{id(resolved)}",
        canonical_name=resolved.canonical_name,
        names=[resolved.canonical_name] + resolved.aliases,
        identifiers=identifiers,
        telecom=telecom,
        addresses=addresses,
        demographics=demographics,
        source_systems=source_systems,
        evidence=[entity_to_evidence_model(e) for e in resolved.entities],
        confidence=resolved.confidence,
        match_reasons=resolved.match_reasons,
    )
