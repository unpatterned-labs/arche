# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Phone number detection — multi-country, libphonenumber-aware.

Public API per the cross-cutting detector convention (mirrors
:mod:`arche.detect.ip` and :mod:`arche.detect.digital_id`)::

    from arche.detect.phones import detect_phones

    detections = detect_phones(
        "Call +234 803 555 7890 or 0712 345 678", default_country="NG"
    )

This is the Pipeline-facing detector. It wraps the parsing / normalization
primitives in :mod:`arche.detect._africa.phones` (prefix tables for 30+
African networks plus E.164 normalization) and emits canonical
:class:`arche.workflow._primitive.Detection` objects with category
``PII-3-PHONE`` (Pan-African PII Taxonomy v0.1). The Pipeline routes its
``core`` detector package here (PRD FR-DETECT-9).

A number is only emitted when it matches a known country's mobile / landline
prefix, so bare identifiers without a valid dialling prefix (account numbers,
reference codes) are not misclassified as phones. One inherent ambiguity
remains: a bare 11-digit NG mobile (``08012345678``) shares its shape with an
11-digit NIN, so both detectors may emit for that span — disambiguation is the
caller's job (give the number a ``+234`` prefix or a "phone:" label to make it
unambiguous).

Returns :class:`Detection` directly so the Pipeline normalization step is a
passthrough — no ``NationalID`` conversion in between.

Confidence is 0.9: the country-prefix tables are specific, but prefix matching
(unlike a checksum) can't fully rule out a coincidental digit run. The E.164
``international`` form and ISO ``country`` are carried in metadata.
"""

from __future__ import annotations

from arche.workflow._primitive import Detection

# Prefix-validated (not checksum-validated), so below the 1.0 of structurally
# validated IDs but high because the per-country prefix tables are specific.
_PHONE_CONFIDENCE = 0.9


def detect_phones(text: str, *, default_country: str = "NG") -> list[Detection]:
    """Find phone numbers in free text.

    Args:
        text: Free-form input.
        default_country: ISO 3166-1 alpha-2 code used to interpret
            local-format numbers (those starting with ``0``). International
            numbers (``+CC...``) are matched regardless of this value, and a
            local number that doesn't fit ``default_country`` still falls back
            to matching against every known African prefix table. Unknown /
            non-African codes therefore just lose first-guess disambiguation.

    Returns:
        List of :class:`Detection` objects with category ``PII-3-PHONE``,
        sorted by character offset. ``metadata`` carries the E.164
        ``international`` form and the ISO ``country`` it was matched against.
    """
    from arche.detect._africa.phones import parse_african_phone

    detections = [
        Detection(
            id=f"det:{hit['start']}:{hit['end']}",
            category="PII-3-PHONE",
            text=hit["raw"],
            start=hit["start"],
            end=hit["end"],
            confidence=_PHONE_CONFIDENCE,
            detector="rule:phone_libphonenumber",
            identity_class="inferred",
            metadata={
                "international": hit.get("international"),
                "country": hit.get("country"),
            },
        )
        for hit in parse_african_phone(text, default_country=default_country)
    ]
    detections.sort(key=lambda d: d.start)
    return detections


__all__ = ["detect_phones"]
