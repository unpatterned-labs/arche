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

"""PII detection and redaction — wraps Microsoft Presidio with custom African ID recognizers.

Falls back to regex-based detection when Presidio is not installed.

Usage:
    from arche.protect import detect_pii, redact
    detections = detect_pii("NIN 12345678901 email me at janet@example.com")
    safe_text = redact("NIN 12345678901 email me at janet@example.com")
"""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass

_log = logging.getLogger("arche")

# Module-level Presidio engine cache (initialized on first use)
_presidio_analyzer = None


@dataclass
class PIIDetection:
    """A single PII occurrence found in the text."""

    text: str
    pii_type: str  # PERSON_NAME, PHONE_NUMBER, EMAIL, NIGERIAN_NIN, NIGERIAN_BVN, GHANA_CARD, etc.
    confidence: float
    start: int
    end: int
    country: str | None = None  # For national IDs: "NG", "GH", "KE", "ZA"

    def __repr__(self) -> str:
        masked = self.text[:3] + "***" if len(self.text) > 3 else "<REDACTED>"
        return (
            f"PIIDetection(type={self.pii_type!r}, text={masked!r}, "
            f"confidence={self.confidence:.2f})"
        )


# ===================================================================
# Public API
# ===================================================================


def detect_pii(text: str) -> list[PIIDetection]:
    """Detect all PII in *text* using Presidio + African patterns.

    Parameters
    ----------
    text:
        Free-form input text to scan for PII.

    Returns
    -------
    list[PIIDetection]
        All PII occurrences found, sorted by position.
    """
    try:
        detections = _detect_presidio(text)
    except ImportError:
        detections = _detect_regex(text)
    except Exception as e:
        _log.warning("Presidio PII detection failed, falling back to regex: %s", e)
        detections = _detect_regex(text)

    return sorted(detections, key=lambda d: d.start)


def redact(
    text: str,
    detections: list[PIIDetection] | None = None,
    strategy: str = "mask",
) -> str:
    """Redact PII from *text*.

    Parameters
    ----------
    text:
        Input text containing PII.
    detections:
        Pre-computed PII detections. If ``None`` detections are computed
        automatically via :func:`detect_pii`.
    strategy:
        ``"mask"`` — replace with ``****``.
        ``"hash"`` — replace with first 8 characters of SHA-256 hash.
        ``"remove"`` — delete the PII text entirely.
        ``"placeholder"`` — replace with ``<PII_TYPE>`` tag, e.g. ``<EMAIL>``.

    Returns
    -------
    str
        Text with PII redacted.
    """
    if detections is None:
        detections = detect_pii(text)

    if not detections:
        return text

    # Sort detections in reverse order so index shifts don't matter
    sorted_dets = sorted(detections, key=lambda d: d.start, reverse=True)

    result = text
    for det in sorted_dets:
        replacement = _make_replacement(det, strategy)
        result = result[: det.start] + replacement + result[det.end :]

    return result


# ===================================================================
# Presidio backend (optional)
# ===================================================================


def _detect_presidio(text: str) -> list[PIIDetection]:
    """Detect PII using Microsoft Presidio with custom African recognizers."""
    global _presidio_analyzer

    if _presidio_analyzer is None:
        from presidio_analyzer import AnalyzerEngine, Pattern, PatternRecognizer

        # Try to create with a small spaCy model first, fall back gracefully.
        # The default AnalyzerEngine tries to download en_core_web_lg (700MB)
        # which blocks on first run. Use en_core_web_sm if available.
        try:
            import spacy
            _available_model = None
            for model_name in ("en_core_web_sm", "en_core_web_md", "en_core_web_lg"):
                try:
                    spacy.load(model_name)
                    _available_model = model_name
                    break
                except OSError:
                    continue
            if _available_model is None:
                raise ImportError("No spaCy model available — falling back to regex PII")
            from presidio_analyzer.nlp_engine import (
                NlpEngineProvider,
                SpacyNlpEngine,  # noqa: F401 — imported to assert spaCy support is available
            )
            provider = NlpEngineProvider(nlp_configuration={
                "nlp_engine_name": "spacy",
                "models": [{"lang_code": "en", "model_name": _available_model}],
            })
            _presidio_analyzer = AnalyzerEngine(nlp_engine=provider.create_engine())
        except (ImportError, OSError):
            raise ImportError("Presidio NLP engine not available")

        # Register African ID recognizers (one-time setup) ----------------
        try:
            from .african.ids import ID_PATTERNS

            for id_key, pattern_info in ID_PATTERNS.items():
                patterns_list = pattern_info if isinstance(pattern_info, list) else [pattern_info]
                presidio_patterns = []
                for pat in patterns_list:
                    pat_str = pat.pattern if hasattr(pat, "pattern") else str(pat)
                    presidio_patterns.append(
                        Pattern(name=f"{id_key}_pattern", regex=pat_str, score=0.85)
                    )
                recognizer = PatternRecognizer(
                    supported_entity=id_key.upper(),
                    patterns=presidio_patterns,
                )
                _presidio_analyzer.registry.add_recognizer(recognizer)
        except (ImportError, Exception):
            pass

        # Register African phone recognizers (one-time setup) -------------
        try:
            from .detect._africa.phones import PHONE_PATTERNS

            for country_code, phone_pats in PHONE_PATTERNS.items():
                pats_list = phone_pats if isinstance(phone_pats, list) else [phone_pats]
                presidio_patterns = []
                for pat in pats_list:
                    pat_str = pat.pattern if hasattr(pat, "pattern") else str(pat)
                    presidio_patterns.append(
                        Pattern(name=f"phone_{country_code}", regex=pat_str, score=0.80)
                    )
                recognizer = PatternRecognizer(
                    supported_entity=f"PHONE_{country_code.upper()}",
                    patterns=presidio_patterns,
                )
                _presidio_analyzer.registry.add_recognizer(recognizer)
        except (ImportError, Exception):
            pass

    analyzer = _presidio_analyzer

    # Run analysis -----------------------------------------------------
    results = analyzer.analyze(text=text, language="en")

    detections: list[PIIDetection] = []
    for r in results:
        country = _infer_country_from_entity_type(r.entity_type)
        detections.append(
            PIIDetection(
                text=text[r.start : r.end],
                pii_type=r.entity_type,
                confidence=round(r.score, 4),
                start=r.start,
                end=r.end,
                country=country,
            )
        )
    return detections


# ===================================================================
# Regex fallback (always available)
# ===================================================================

_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b")

_PHONE_GENERIC_RE = re.compile(
    r"(?<!\d)"
    r"(?:\+?\d{1,3}[\s\-]?)?"
    r"(?:\(?\d{2,4}\)?[\s\-]?)"
    r"\d{3,4}[\s\-]?\d{3,4}"
    r"(?!\d)"
)

_CREDIT_CARD_RE = re.compile(
    r"\b(?:\d{4}[\s\-]?){3}\d{4}\b"
)


def _detect_regex(text: str) -> list[PIIDetection]:
    """Detect PII using regex patterns — always available, no dependencies."""
    detections: list[PIIDetection] = []

    # --- African national IDs ---
    try:
        from .detect._africa.ids import detect_african_ids

        for nid in detect_african_ids(text):
            start = nid.start if hasattr(nid, "start") else text.index(nid.text)
            end = nid.end if hasattr(nid, "end") else start + len(nid.text)
            country = nid.country if hasattr(nid, "country") else None
            id_type = nid.id_type if hasattr(nid, "id_type") else "NATIONAL_ID"

            # Map id_type to specific PII type (e.g. NIGERIAN_NIN, GHANA_CARD)
            pii_type = _map_african_id_type(id_type, country)
            detections.append(
                PIIDetection(
                    text=nid.text,
                    pii_type=pii_type,
                    confidence=nid.confidence if hasattr(nid, "confidence") else 0.90,
                    start=start,
                    end=end,
                    country=country,
                )
            )
    except ImportError:
        pass
    except Exception as e:
        _log.warning("African ID detection failed: %s", e)

    # --- African phone numbers ---
    try:
        from .detect._africa.phones import PHONE_PATTERNS

        for country_code, patterns in PHONE_PATTERNS.items():
            pats = patterns if isinstance(patterns, list) else [patterns]
            for pat in pats:
                compiled = re.compile(pat) if isinstance(pat, str) else pat
                for m in compiled.finditer(text):
                    if not _overlaps_detections(detections, m.start(), m.end()):
                        detections.append(
                            PIIDetection(
                                text=m.group(),
                                pii_type="PHONE_NUMBER",
                                confidence=0.85,
                                start=m.start(),
                                end=m.end(),
                                country=country_code.upper(),
                            )
                        )
    except (ImportError, Exception):
        pass

    # Generic phone fallback
    for m in _PHONE_GENERIC_RE.finditer(text):
        if not _overlaps_detections(detections, m.start(), m.end()):
            detections.append(
                PIIDetection(
                    text=m.group().strip(),
                    pii_type="PHONE_NUMBER",
                    confidence=0.70,
                    start=m.start(),
                    end=m.end(),
                )
            )

    # --- Emails ---
    for m in _EMAIL_RE.finditer(text):
        detections.append(
            PIIDetection(
                text=m.group(),
                pii_type="EMAIL",
                confidence=0.95,
                start=m.start(),
                end=m.end(),
            )
        )

    # --- Credit cards ---
    for m in _CREDIT_CARD_RE.finditer(text):
        digits = re.sub(r"\D", "", m.group())
        if len(digits) == 16 and _luhn_check(digits):
            detections.append(
                PIIDetection(
                    text=m.group(),
                    pii_type="CREDIT_CARD",
                    confidence=0.90,
                    start=m.start(),
                    end=m.end(),
                )
            )

    return detections


# ===================================================================
# Helpers
# ===================================================================


def _make_replacement(det: PIIDetection, strategy: str) -> str:
    """Generate a replacement string for a PII detection."""
    if strategy == "mask":
        return "****"
    elif strategy == "hash":
        return hashlib.sha256(det.text.encode()).hexdigest()[:8]
    elif strategy == "remove":
        return ""
    elif strategy == "placeholder":
        return f"<{det.pii_type}>"
    else:
        raise ValueError(
            f"Unknown redaction strategy: {strategy!r}. "
            "Use 'mask', 'hash', 'remove', or 'placeholder'."
        )


def _overlaps_detections(detections: list[PIIDetection], start: int, end: int) -> bool:
    """Check whether a span overlaps any existing detection."""
    for d in detections:
        if start < d.end and end > d.start:
            return True
    return False


def _luhn_check(number: str) -> bool:
    """Validate a number string using the Luhn algorithm."""
    digits = [int(d) for d in number]
    odd_digits = digits[-1::-2]
    even_digits = digits[-2::-2]
    total = sum(odd_digits)
    for d in even_digits:
        total += sum(divmod(d * 2, 10))
    return total % 10 == 0


def _infer_country_from_entity_type(entity_type: str) -> str | None:
    """Infer country code from a Presidio / custom entity type string."""
    mapping = {
        "NIGERIAN_NIN": "NG",
        "NIGERIAN_BVN": "NG",
        "NIGERIA_NIN": "NG",
        "NIGERIA_BVN": "NG",
        "GHANA_CARD": "GH",
        "KENYA_ID": "KE",
        "SA_ID": "ZA",
        "SOUTH_AFRICA_ID": "ZA",
    }
    upper = entity_type.upper()
    for key, country in mapping.items():
        if key in upper:
            return country
    return None


def _map_african_id_type(id_type: str, country: str | None) -> str:
    """Map an African ID type to a human-readable PII type label."""
    id_type_upper = (id_type or "").upper()
    country_upper = (country or "").upper()

    # Try direct mapping
    type_map = {
        "NIN": "NIGERIAN_NIN" if country_upper in ("NG", "NIGERIA", "") else f"{country_upper}_NIN",
        "BVN": "NIGERIAN_BVN",
        "GHANA_CARD": "GHANA_CARD",
        "KENYA_ID": "KENYA_ID",
        "SA_ID": "SOUTH_AFRICA_ID",
    }

    for key, label in type_map.items():
        if key in id_type_upper:
            return label

    # Fallback
    if country_upper:
        return f"{country_upper}_NATIONAL_ID"
    return "NATIONAL_ID"
