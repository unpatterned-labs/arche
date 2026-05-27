# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Kenyan phone detection and normalization (libphonenumber-backed)."""

from __future__ import annotations

from typing import Any

from arche.detect._africa.phones import (
    PHONE_PATTERNS,
    _PHONE_RE,
    normalize_e164,
    parse_african_phone,
    validate_phone,
)

KE_SPEC: dict = PHONE_PATTERNS["KE"]


def normalize_ke_phone(number: str) -> str | None:
    """Normalize a Kenyan phone number to E.164."""
    return normalize_e164(number, default_country="KE")


def validate_ke_phone(number: str) -> dict[str, Any]:
    """Validate and structure a Kenyan phone number."""
    return validate_phone(number, default_country="KE")


def detect_kenyan_phones(text: str) -> list[dict]:
    """Detect Kenyan phone numbers in text."""
    results = []
    for match in _PHONE_RE.finditer(text):
        parsed = parse_african_phone(match.group(1), default_country="KE")
        if parsed and parsed.get("country") == "KE":
            parsed["start"] = match.start(1)
            parsed["end"] = match.end(1)
            results.append(parsed)
    return results
