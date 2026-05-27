"""Schema contracts for naming dataset DataOps v1."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

NameType = Literal["given", "family"]
CandidateStatus = Literal["pending", "approved", "rejected"]


class StrictBaseModel(BaseModel):
    """Base model with strict extra-field handling."""

    model_config = ConfigDict(extra="forbid")


class RawNameEvidenceV1(StrictBaseModel):
    """Raw name evidence from Wikidata or curated CSV sources."""

    source: str = Field(min_length=1)
    source_id: str = Field(min_length=1)
    source_license: str = Field(min_length=1)
    name_raw: str = Field(min_length=1)
    name_type: NameType
    country_iso2: str = Field(min_length=2, max_length=2)
    language_tag: str = Field(min_length=2)
    evidence_count: int = Field(ge=1)
    fetched_at: datetime

    @field_validator("country_iso2")
    @classmethod
    def _normalize_country(cls, value: str) -> str:
        return value.upper()


class NormalizedNameV1(StrictBaseModel):
    """Normalized name record used for candidate generation."""

    source: str = Field(min_length=1)
    source_id: str = Field(min_length=1)
    source_license: str = Field(min_length=1)
    name_type: NameType
    country_iso2: str = Field(min_length=2, max_length=2)
    language_tag: str = Field(min_length=2)
    evidence_count: int = Field(ge=1)
    fetched_at: datetime
    name_display: str = Field(min_length=1)
    name_nfc: str = Field(min_length=1)
    name_ascii_key: str = Field(min_length=1)
    was_trimmed: bool
    was_casefolded: bool
    had_diacritics: bool
    contains_apostrophe: bool
    contains_hyphen: bool
    script: str = Field(min_length=1)

    @field_validator("country_iso2")
    @classmethod
    def _normalize_country(cls, value: str) -> str:
        return value.upper()


class CandidateEquivalenceV1(StrictBaseModel):
    """Reviewable candidate equivalence generated from evidence."""

    candidate_id: str = Field(min_length=1)
    canonical: str = Field(min_length=1)
    variant: str = Field(min_length=1)
    name_type: NameType
    suggested_tradition: str = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)
    evidence_summary: str = Field(min_length=1)
    wikidata_qids: list[str] = Field(default_factory=list)
    countries: list[str] = Field(default_factory=list)
    languages: list[str] = Field(default_factory=list)
    status: CandidateStatus = "pending"
    source: str = Field(min_length=1)
    source_license: str = Field(min_length=1)
    conflict_flag: bool = False
    reviewer_notes: str | None = None


class CuratedContributionCSVV1(StrictBaseModel):
    """Strict contributor CSV row for curation inputs."""

    source: str = Field(min_length=1)
    source_id: str = Field(min_length=1)
    source_license: str = Field(min_length=1)
    name_raw: str = Field(min_length=1)
    name_type: NameType
    country_iso2: str = Field(min_length=2, max_length=2)
    language_tag: str = Field(min_length=2)
    evidence_count: int = Field(ge=1)
    fetched_at: datetime
    canonical: str | None = None
    suggested_tradition: str | None = None
    reviewer_notes: str | None = None

    @field_validator("country_iso2")
    @classmethod
    def _normalize_country(cls, value: str) -> str:
        return value.upper()


class PublishedEquivalenceV1(StrictBaseModel):
    """Published enriched equivalence row used downstream by models."""

    canonical: str = Field(min_length=1)
    variant: str = Field(min_length=1)
    tradition: str = Field(min_length=1)
    file: str = Field(min_length=1)
    source: str = ""
    source_ids: str = ""
    countries: str = ""
    languages: str = ""
    confidence: float = Field(ge=0.0, le=1.0)
    last_seen_at: str = ""


class AfricanNameLexiconV1(StrictBaseModel):
    """Unified African name lexicon row for downstream arche models."""

    name_display: str = Field(min_length=1)
    name_nfc: str = Field(min_length=1)
    name_ascii_key: str = Field(min_length=1)
    name_type: NameType
    countries: str = ""
    languages: str = ""
    sources: str = ""
    source_ids: str = ""
    total_evidence_count: int = Field(ge=1)
    occurrence_count: int = Field(ge=1)
    last_seen_at: str = ""
