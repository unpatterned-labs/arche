# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Nigerian phone detection and normalization.

Per PRD §4.2 FR-DETECT-9. Uses libphonenumber for E.164 normalization and
line-type inference, falling back to the multi-country regex orchestrator
for span detection.

Public API::

    from arche.detect.ng.phones import (
        detect_nigerian_phones,
        normalize_ng_phone,
        validate_ng_phone,
    )
"""

from __future__ import annotations

from typing import Any

# Re-export the NG spec from the multi-country home so the data stays in
# one place. Full per-country phone data extraction is Week 2 cleanup work;
# for now this file exposes the PRD-shaped API surface.
from arche.detect._africa.phones import (
    PHONE_PATTERNS,
    normalize_e164,
    parse_african_phone,
    validate_phone,
)

NG_SPEC: dict = PHONE_PATTERNS["NG"]


def normalize_ng_phone(number: str) -> str | None:
    """Normalize a Nigerian phone number to E.164 (libphonenumber-backed)."""
    return normalize_e164(number, default_country="NG")


def validate_ng_phone(number: str) -> dict[str, Any]:
    """Validate and structure a Nigerian phone number."""
    return validate_phone(number, default_country="NG")


def detect_nigerian_phones(text: str) -> list[dict]:
    """Detect Nigerian phone numbers in text. Returns parse records."""
    results = []
    # parse_african_phone returns a list of dicts when called with default_country.
    # The orchestrator handles span detection across all countries; we filter to NG.
    from arche.detect._africa.phones import _PHONE_RE

    for match in _PHONE_RE.finditer(text):
        parsed = parse_african_phone(match.group(1), default_country="NG")
        if parsed and parsed.get("country") == "NG":
            parsed["start"] = match.start(1)
            parsed["end"] = match.end(1)
            results.append(parsed)
    return results
