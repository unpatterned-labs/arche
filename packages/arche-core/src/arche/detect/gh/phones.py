# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Ghanaian phone detection and normalization (libphonenumber-backed)."""

from __future__ import annotations

from typing import Any

from arche.detect._africa.phones import (
    PHONE_PATTERNS,
    _PHONE_RE,
    normalize_e164,
    parse_african_phone,
    validate_phone,
)

GH_SPEC: dict = PHONE_PATTERNS["GH"]


def normalize_gh_phone(number: str) -> str | None:
    """Normalize a Ghanaian phone number to E.164."""
    return normalize_e164(number, default_country="GH")


def validate_gh_phone(number: str) -> dict[str, Any]:
    """Validate and structure a Ghanaian phone number."""
    return validate_phone(number, default_country="GH")


def detect_ghanaian_phones(text: str) -> list[dict]:
    """Detect Ghanaian phone numbers in text."""
    results = []
    for match in _PHONE_RE.finditer(text):
        parsed = parse_african_phone(match.group(1), default_country="GH")
        if parsed and parsed.get("country") == "GH":
            parsed["start"] = match.start(1)
            parsed["end"] = match.end(1)
            results.append(parsed)
    return results
