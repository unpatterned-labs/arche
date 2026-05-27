"""Normalization utilities for personal names."""

from __future__ import annotations

import re
import unicodedata

from .schemas import NormalizedNameV1, RawNameEvidenceV1

_WHITESPACE_RE = re.compile(r"\s+")
_PUNCT_EDGE_RE = re.compile(r"^[\s'\".,;:!?\[\]{}]+|[\s'\".,;:!?\[\]{}]+$")
_DESCRIPTOR_SUFFIX_RE = re.compile(
    r"\s*\((?:family\s+name|given\s+name|first\s+name|last\s+name|surname|name)\)?\s*$",
    flags=re.IGNORECASE,
)
_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")


def normalize_name(raw: RawNameEvidenceV1) -> NormalizedNameV1:
    """Normalize one raw evidence row into a stable form."""
    original = raw.name_raw
    trimmed = _PUNCT_EDGE_RE.sub("", original.strip())
    collapsed = _WHITESPACE_RE.sub(" ", trimmed)
    cleaned = _DESCRIPTOR_SUFFIX_RE.sub("", collapsed).strip()
    cleaned = _WHITESPACE_RE.sub(" ", cleaned)
    nfc = unicodedata.normalize("NFC", cleaned)
    casefolded = nfc.casefold()
    ascii_fold = _to_ascii(casefolded)
    ascii_key = _NON_ALNUM_RE.sub("", ascii_fold)
    script = _infer_script(nfc)

    return NormalizedNameV1(
        source=raw.source,
        source_id=raw.source_id,
        source_license=raw.source_license,
        name_type=raw.name_type,
        country_iso2=raw.country_iso2,
        language_tag=raw.language_tag,
        evidence_count=raw.evidence_count,
        fetched_at=raw.fetched_at,
        name_display=cleaned,
        name_nfc=nfc,
        name_ascii_key=ascii_key or "unknown",
        was_trimmed=cleaned != original,
        was_casefolded=casefolded != nfc,
        had_diacritics=_has_diacritics(nfc),
        contains_apostrophe="'" in nfc,
        contains_hyphen="-" in nfc,
        script=script,
    )


def _to_ascii(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    return "".join(c for c in normalized if not unicodedata.combining(c))


def _has_diacritics(value: str) -> bool:
    return value != _to_ascii(value)


def _infer_script(value: str) -> str:
    # v1 intentionally keeps this simple: names are expected to be mostly Latin.
    has_non_ascii = any(ord(ch) > 127 for ch in value if ch.isalpha())
    return "latin_extended" if has_non_ascii else "latin"
