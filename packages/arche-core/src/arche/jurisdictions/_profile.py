# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""The shape of a country pack.

One pydantic model, shared by the four shipped packs (NG, KE, ZA, GH). It
lived in ``arche.models`` beside the v0.1 evidence/record models; those went
in 0.8.0 and this is the only one anything still reads.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


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
