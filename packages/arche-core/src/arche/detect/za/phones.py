# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""South African phone detection and normalization (libphonenumber-backed)."""

from __future__ import annotations

from typing import Any

from arche.detect._africa.phones import (
    PHONE_PATTERNS,
    _PHONE_RE,
    normalize_e164,
    parse_african_phone,
    validate_phone,
)

ZA_SPEC: dict = PHONE_PATTERNS["ZA"]


def normalize_za_phone(number: str) -> str | None:
    """Normalize a South African phone number to E.164."""
    return normalize_e164(number, default_country="ZA")


def validate_za_phone(number: str) -> dict[str, Any]:
    """Validate and structure a South African phone number."""
    return validate_phone(number, default_country="ZA")


def detect_south_african_phones(text: str) -> list[dict]:
    """Detect South African phone numbers in text."""
    results = []
    for match in _PHONE_RE.finditer(text):
        parsed = parse_african_phone(match.group(1), default_country="ZA")
        if parsed and parsed.get("country") == "ZA":
            parsed["start"] = match.start(1)
            parsed["end"] = match.end(1)
            results.append(parsed)
    return results
