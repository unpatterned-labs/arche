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

"""Entity extraction with multi-backend fallback: GliNER -> regex -> LLM.

Usage:
    from arche.extract import extract
    entities = extract("Janet Okafor called from +234 803 555 7890")
    for e in entities:
        print(e.entity_type, e.text, e.confidence)

GliNER is optional -- if not installed, falls back to regex patterns that always work.

LLM support is opt-in via ``backend="auto+llm"`` -- the LLM acts as an additional
proposer alongside GliNER and regex.  All three feed into the same ``_merge_entities()``
pipeline with the same deterministic validators.

Backend options:
    ``"auto"``      -- GliNER + regex + validators (default, works offline)
    ``"auto+llm"``  -- GliNER + regex + LLM + validators (best accuracy, needs API key)
    ``"regex"``     -- regex + validators only (air-gapped)
    ``"gliner"``    -- GliNER only (raises if not installed)
"""

from __future__ import annotations

import logging
import re
import warnings

_log = logging.getLogger("arche")

# PII-sensitive entity types whose text should be masked in repr/logs
_PII_TYPES = {"PHONE", "EMAIL", "NATIONAL_ID"}

def _mask_text(text: str, entity_type: str) -> str:
    """Mask PII-sensitive text for safe repr/logging."""
    if entity_type in _PII_TYPES and len(text) > 3:
        return text[:3] + "***"
    return text


# ── Entity: a MENTION (surface form) — canonical name is EntityReference ──────
# The canonical M2 vocabulary (docs/new/arche-compliance-flow.md §1) names a
# mention an :class:`~arche.canonical.EntityReference`; ``Entity`` here has
# always meant a mention (an inverted name — the *resolved* thing is the
# canonical ``arche.canonical.Entity``). To fix the vocabulary without a
# breaking rename, ``extract.Entity`` is an alias of ``EntityReference``: both
# names keep working and keep meaning "a reference". ``EntityReference`` is
# structurally identical to the historical ``Entity`` dataclass (same fields,
# defaults, and PII-masking repr), so all existing construction and
# ``isinstance`` sites are unaffected.
#
# DEPRECATION (soft, no runtime warning): new code should import
# ``EntityReference`` from ``arche.canonical``. ``extract.Entity`` stays
# supported through the v0.2.x series. No warning is emitted on use because
# ``Entity`` is constructed on every hot detection path internally; a
# per-construction warning would be noise and would break ``-W error`` runs.
from .canonical import EntityReference  # noqa: E402

Entity = EntityReference


# ===================================================================
# Public API
# ===================================================================


def extract(
    text: str,
    entity_types: list[str] | None = None,
    backend: str = "auto",
    llm_config: object | None = None,
) -> list[Entity]:
    """Extract entities from *text* using the specified backend.

    Parameters
    ----------
    text:
        Free-form input text to scan.
    entity_types:
        Optional list of entity types to restrict extraction to.
        When ``None`` all supported types are extracted.
    backend:
        ``"auto"`` -- GliNER + regex + validators (default, works offline).
        ``"auto+llm"`` -- GliNER + regex + LLM + validators (best accuracy, needs API key).
        ``"gliner"`` -- GliNER only (raises if not installed).
        ``"regex"`` -- regex + validators only (air-gapped).
    llm_config:
        An :class:`~arche.llm.LLMConfig` instance.  Required when
        ``backend="auto+llm"``.  If ``None`` and the backend needs LLM,
        configuration is read from :func:`~arche.config.get_config`.

    Returns
    -------
    list[Entity]
        Extracted entities sorted by their position in the text.
    """
    if backend in ("auto", "auto+llm"):
        try:
            entities = _extract_gliner(text, entity_types)
            # Supplement with regex patterns that GliNER may miss (phones, IDs, etc.)
            regex_entities = _extract_regex(text, entity_types)
            entities = _merge_entities(entities, regex_entities)
        except ImportError:
            warnings.warn(
                "GliNER not available. Using regex-only extraction. "
                "Person/organization/location detection is disabled. "
                "Install with: pip install arche-core[gliner]",
                stacklevel=2,
            )
            entities = list(_extract_regex(text, entity_types))
        except Exception as e:
            _log.warning("GliNER extraction failed, falling back to regex: %s", e)
            warnings.warn(
                f"GliNER extraction failed ({e}). Using regex-only extraction. "
                "Person/organization/location detection is disabled. "
                "Install with: pip install arche-core[gliner]",
                stacklevel=2,
            )
            entities = list(_extract_regex(text, entity_types))

        # --- LLM proposer (additional, not replacement) ---
        if backend == "auto+llm":
            llm_entities = _extract_llm(text, llm_config)
            entities = _merge_entities(entities, llm_entities)

        return sorted(entities, key=lambda e: e.start)
    elif backend == "gliner":
        return sorted(_extract_gliner(text, entity_types), key=lambda e: e.start)
    elif backend == "gliner2":
        return sorted(_extract_gliner2(text, entity_types), key=lambda e: e.start)
    elif backend == "regex":
        return sorted(_extract_regex(text, entity_types), key=lambda e: e.start)
    else:
        raise ValueError(
            f"Unknown backend: {backend!r}. "
            "Use 'auto', 'auto+llm', 'gliner', 'gliner2', or 'regex'."
        )


# ===================================================================
# GliNER backend (optional)
# ===================================================================


def _get_gliner_model():
    """Load the GliNER model via the shared registry (cached, offline-aware)."""
    from ._models import get_gliner

    return get_gliner()  # uses config model name, checks ARCHE_MODEL_DIR


# ── Identity-specific GliNER label set ───────────────────────────────────────
# These labels are tuned for identity resolution use cases (DPI, KYC, health).
# GliNER performs zero-shot NER — these labels describe what to extract.

_IDENTITY_LABELS = [
    "person",
    "organization",
    "location",
    "address",
    "date of birth",
    "date",
    "national identification number",
    "phone number",
    "money",
]

# Map GliNER's raw labels to our normalised entity type taxonomy
_GLINER_LABEL_MAP: dict[str, str] = {
    "person": "PERSON",
    "organization": "ORGANIZATION",
    "location": "LOCATION",
    "address": "LOCATION",
    "date of birth": "DATE",
    "date": "DATE",
    "national identification number": "NATIONAL_ID",
    "phone number": "PHONE",
    "money": "MONEY",
    "product": "PRODUCT",
    "email": "EMAIL",
    "medical record number": "DOCUMENT",
}

def _extract_gliner(text: str, entity_types: list[str] | None = None) -> list[Entity]:
    """Extract entities using the GliNER zero-shot NER model.

    Uses identity-specific labels by default for better precision on
    person names, national IDs, addresses, and phone numbers.

    The confidence threshold is read from ``get_config().gliner_threshold``
    so callers can tune it via ``configure(gliner_threshold=0.4)`` without
    touching this module.
    """
    from .config import get_config

    model = _get_gliner_model()

    if entity_types:
        # User-specified labels — normalise to lowercase for GliNER
        labels = [l.lower() for l in entity_types]
    else:
        labels = _IDENTITY_LABELS

    raw = model.predict_entities(text, labels, threshold=get_config().gliner_threshold)

    entities: list[Entity] = []
    for ent in raw:
        raw_label = ent["label"].lower()
        entity_type = _GLINER_LABEL_MAP.get(raw_label, raw_label.upper())

        entities.append(
            Entity(
                text=ent["text"],
                entity_type=entity_type,
                confidence=float(ent["score"]),
                start=ent["start"],
                end=ent["end"],
                source="gliner",
            )
        )
    return entities


# ===================================================================
# Regex backend (always available)
# ===================================================================

# --- Pattern definitions ---

_EMAIL_RE = re.compile(
    r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b"
)

_URL_RE = re.compile(
    r"https?://[^\s<>\"']+|www\.[^\s<>\"']+"
)

_DATE_PATTERNS = [
    # DD/MM/YYYY or DD-MM-YYYY
    re.compile(r"\b(0?[1-9]|[12]\d|3[01])[/\-](0?[1-9]|1[0-2])[/\-](19|20)\d{2}\b"),
    # YYYY-MM-DD (ISO)
    re.compile(r"\b(19|20)\d{2}[/\-](0?[1-9]|1[0-2])[/\-](0?[1-9]|[12]\d|3[01])\b"),
    # Month DD, YYYY  or  Month DD YYYY
    re.compile(
        r"\b(?:January|February|March|April|May|June|July|August|September|October|November|December"
        r"|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Oct|Nov|Dec)"
        r"\s+\d{1,2}(?:,?\s+\d{4})?\b",
        re.IGNORECASE,
    ),
    # DD Month YYYY
    re.compile(
        r"\b\d{1,2}\s+(?:January|February|March|April|May|June|July|August|September"
        r"|October|November|December|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Oct|Nov|Dec)"
        r"(?:\s+\d{4})?\b",
        re.IGNORECASE,
    ),
]

# ISBN patterns — ISBN-10 and ISBN-13
_ISBN_RE = re.compile(
    r"\bISBN[-:\s]*"
    r"((?:97[89][-\s]?)?(?:\d[-\s]?){9}[\dXx])"  # ISBN-13 or ISBN-10 after prefix
    r"\b"
    r"|"
    r"\b(97[89][-\s]?(?:\d[-\s]?){9}\d)\b"  # Bare ISBN-13 without "ISBN" prefix
, re.IGNORECASE)


def _validate_isbn(raw: str) -> tuple[str, str]:
    """Validate and classify an ISBN string.

    Returns (normalised_isbn, isbn_type) where isbn_type is "ISBN-13",
    "ISBN-10", or "" if invalid.
    """
    digits = re.sub(r"[^0-9Xx]", "", raw)

    if len(digits) == 13:
        # ISBN-13: alternating weights 1 and 3, sum mod 10 == 0
        total = 0
        for i, ch in enumerate(digits):
            d = int(ch)
            total += d if i % 2 == 0 else d * 3
        if total % 10 == 0:
            return digits, "ISBN-13"

    elif len(digits) == 10:
        # ISBN-10: weights 10..1, last digit may be X (=10), sum mod 11 == 0
        total = 0
        for i, ch in enumerate(digits):
            if ch.upper() == "X":
                total += 10
            else:
                total += int(ch) * (10 - i)
        if total % 11 == 0:
            return digits.upper(), "ISBN-10"

    return digits, ""


# Standard (non-African) currency patterns — African ones come from african.currencies
_STANDARD_MONEY_RE = re.compile(
    r"(?:[$\u20ac\u00a3])\s?\d[\d,]*(?:\.\d{1,2})?"  # $100, €1,000.50, £20
    r"|"
    r"\d[\d,]*(?:\.\d{1,2})?\s?(?:USD|EUR|GBP|dollars?|euros?|pounds?)\b",
    re.IGNORECASE,
)


def _extract_regex(text: str, entity_types: list[str] | None = None) -> list[Entity]:
    """Extract entities using regex patterns. Always available, no dependencies."""
    entities: list[Entity] = []
    allowed = {t.upper() for t in entity_types} if entity_types else None

    def _want(etype: str) -> bool:
        return allowed is None or etype in allowed

    # --- ISBNs (run before phones to avoid ISBN digits being grabbed as phone) ---
    if _want("ISBN"):
        for m in _ISBN_RE.finditer(text):
            raw = m.group(1) or m.group(2)
            if raw and not _overlaps(entities, m.start(), m.end()):
                normalised, isbn_type = _validate_isbn(raw)
                if isbn_type:
                    entities.append(
                        Entity(
                            text=m.group().strip(),
                            entity_type="ISBN",
                            confidence=0.95,
                            start=m.start(),
                            end=m.end(),
                            source="regex",
                            metadata={
                                "isbn_normalised": normalised,
                                "isbn_type": isbn_type,
                            },
                        )
                    )

    # --- African phone numbers ---
    if _want("PHONE"):
        try:
            from .detect._africa.phones import parse_african_phone

            for hit in parse_african_phone(text):
                if not _overlaps(entities, hit["start"], hit["end"]):
                    entities.append(
                        Entity(
                            text=hit["raw"],
                            entity_type="PHONE",
                            confidence=0.90,
                            start=hit["start"],
                            end=hit["end"],
                            source="african",
                            metadata={"country": hit["country"], "international": hit["international"]},
                        )
                    )
        except ImportError:
            pass

        # Fallback generic international phone pattern
        generic_phone_re = re.compile(
            r"(?<!\d)"
            r"(?:\+?\d{1,3}[\s\-]?)?"  # optional country code
            r"(?:\(?\d{2,4}\)?[\s\-]?)"  # area code
            r"\d{3,4}[\s\-]?\d{3,4}"
            r"(?!\d)"
        )
        for m in generic_phone_re.finditer(text):
            # Skip if overlaps with an already-found phone entity
            if not _overlaps(entities, m.start(), m.end()):
                entities.append(
                    Entity(
                        text=m.group().strip(),
                        entity_type="PHONE",
                        confidence=0.70,
                        start=m.start(),
                        end=m.end(),
                        source="regex",
                    )
                )

    # --- Emails ---
    if _want("EMAIL"):
        for m in _EMAIL_RE.finditer(text):
            entities.append(
                Entity(
                    text=m.group(),
                    entity_type="EMAIL",
                    confidence=0.95,
                    start=m.start(),
                    end=m.end(),
                    source="regex",
                )
            )

    # --- National IDs (African) ---
    if _want("NATIONAL_ID"):
        try:
            from .detect._africa.ids import detect_african_ids

            for nid in detect_african_ids(text):
                # Validated IDs replace any overlapping PHONE guess at the same span
                entities = [
                    e for e in entities
                    if not (
                        e.entity_type == "PHONE"
                        and nid.start < e.end and nid.end > e.start
                    )
                ]
                entities.append(
                    Entity(
                        text=nid.text,
                        entity_type="NATIONAL_ID",
                        confidence=nid.confidence,
                        start=nid.start,
                        end=nid.end,
                        source="african",
                        metadata={"country": nid.country, "id_type": nid.id_type},
                    )
                )
        except (ImportError, Exception):
            pass

    # --- Money / Currency (African + standard) ---
    if _want("MONEY"):
        # African currencies
        try:
            from .detect._money.african import detect_african_currency

            for hit in detect_african_currency(text):
                entities.append(
                    Entity(
                        text=hit["raw"],
                        entity_type="MONEY",
                        confidence=0.85,
                        start=hit["start"],
                        end=hit["end"],
                        source="african",
                        metadata={"currency": hit["currency"], "amount": hit.get("amount")},
                    )
                )
        except (ImportError, Exception):
            pass

        # Standard currencies ($, EUR, GBP)
        for m in _STANDARD_MONEY_RE.finditer(text):
            if not _overlaps(entities, m.start(), m.end()):
                entities.append(
                    Entity(
                        text=m.group(),
                        entity_type="MONEY",
                        confidence=0.85,
                        start=m.start(),
                        end=m.end(),
                        source="regex",
                    )
                )

    # --- Dates ---
    if _want("DATE"):
        for pattern in _DATE_PATTERNS:
            for m in pattern.finditer(text):
                if not _overlaps(entities, m.start(), m.end()):
                    entities.append(
                        Entity(
                            text=m.group(),
                            entity_type="DATE",
                            confidence=0.80,
                            start=m.start(),
                            end=m.end(),
                            source="regex",
                        )
                    )

    # --- URLs ---
    if _want("URL"):
        for m in _URL_RE.finditer(text):
            entities.append(
                Entity(
                    text=m.group(),
                    entity_type="URL",
                    confidence=0.95,
                    start=m.start(),
                    end=m.end(),
                    source="regex",
                )
            )

    return entities


# ===================================================================
# Helpers
# ===================================================================


def _overlaps(entities: list[Entity], start: int, end: int) -> bool:
    """Check whether a span overlaps any existing entity."""
    for e in entities:
        if start < e.end and end > e.start:
            return True
    return False


def _extract_llm(text: str, llm_config: object | None) -> list[Entity]:
    """Run the LLM proposer and return entities with source="llm".

    If no ``llm_config`` is provided, builds one from the global
    :class:`~arche.config.ArcheConfig` LLM fields.  Failures are logged
    and return an empty list (LLM is best-effort, never blocks the pipeline).
    """
    from .config import get_config

    # Resolve config: explicit > global config > error
    config = llm_config
    if config is None:
        cfg = get_config()
        if cfg.llm_provider:
            from .llm import LLMConfig
            config = LLMConfig(
                provider=cfg.llm_provider,
                model=cfg.llm_model,
                api_key=cfg.llm_api_key,
                base_url=cfg.llm_base_url,
                temperature=cfg.llm_temperature,
                timeout=cfg.llm_timeout,
            )
        else:
            _log.warning(
                "backend='auto+llm' but no llm_config provided and no "
                "LLM defaults configured via configure(). Skipping LLM extraction."
            )
            return []

    try:
        from .llm.extraction import extract_with_llm
        return extract_with_llm(text, config)
    except Exception as exc:
        _log.warning("LLM extraction failed, continuing without LLM: %s", exc)
        return []


def _merge_entities(primary: list[Entity], secondary: list[Entity]) -> list[Entity]:
    """Merge two entity lists with smart conflict resolution.

    Used to merge GliNER + regex, or (GliNER + regex) + LLM proposals.

    Priority order for overlapping spans:
    1. **Trusted validated** entities (``source="african"``) always win.
       These have checksum/format validation and are deterministic.
    2. **Primary** entities (first argument -- typically GliNER or the
       already-merged GliNER+regex set) keep priority.
    3. **Secondary** entities (second argument -- typically regex or LLM
       proposals) fill non-overlapping gaps.

    This means LLM proposals for structured types (NIN, BVN, phone) that
    overlap with regex-validated entities are correctly discarded.  LLM
    proposals for fuzzy types (PERSON, ORG, LOCATION) that fill gaps
    missed by GliNER are kept.
    """
    # Start with all entities that have structural validation -- these are
    # high-trust and should not be overridden by statistical/LLM guesses.
    trusted = [e for e in secondary if e.source == "african"]
    other_secondary = [e for e in secondary if e.source != "african"]

    merged: list[Entity] = list(trusted)

    # Add primary entities that do not conflict with trusted spans.
    for g in primary:
        if not _overlaps(merged, g.start, g.end):
            merged.append(g)

    # Add remaining secondary entities that fill gaps.
    for r in other_secondary:
        if not _overlaps(merged, r.start, r.end):
            merged.append(r)

    return merged


# ===================================================================
# GLiNER 2.5 backend (optional, `arche-core[detect2]`)
# ===================================================================


def _extract_gliner2(text: str, entity_types: list[str] | None = None) -> list[Entity]:
    """Extract entities with GLiNER 2.5.

    The output shape differs from v1 and the difference matters. v1 returns a
    flat list of spans each carrying its own label; 2.5 returns spans grouped
    BY label::

        {"entities": {"organization": [{"text": ..., "confidence": ...,
                                        "start": ..., "end": ...}],
                      "person": []}}

    ``include_confidence`` and ``include_spans`` are both requested because
    without them the model returns bare strings, and a mention with no offsets
    cannot be cited back to the document it came from -- which is the whole
    point of an arche :class:`Entity`.
    """
    from ._models import get_gliner2
    from .config import get_config

    model = get_gliner2()
    labels = [label.lower() for label in entity_types] if entity_types \
        else _IDENTITY_LABELS

    result = model.extract_entities(
        text, labels,
        threshold=get_config().gliner2_threshold,
        include_confidence=True,
        include_spans=True,
    )

    out: list[Entity] = []
    for label, spans in (result or {}).get("entities", {}).items():
        entity_type = _GLINER_LABEL_MAP.get(label.lower(), label.upper())
        for span in spans or []:
            # A bare string means the model answered without offsets despite
            # being asked for them. Skipping is right: an uncitable mention is
            # worse than a missing one, because it looks like evidence.
            if not isinstance(span, dict):
                continue
            start, end = span.get("start"), span.get("end")
            if start is None or end is None:
                continue
            out.append(Entity(
                text=span.get("text", text[start:end]),
                entity_type=entity_type,
                confidence=float(span.get("confidence", 0.0)),
                start=int(start),
                end=int(end),
                source="gliner2",
            ))
    return out


# ===================================================================
# `arche.extract` is a module AND callable
# ===================================================================
# Without this, the name is ambiguous in a way that fails at a distance:
#
#     from arche import extract
#     extract(text)                     # fine
#
#     from arche.extract import Entity  # anywhere in the process
#     extract(text)                     # TypeError: not callable
#
# Importing any name out of the submodule rebinds `arche.extract` from the
# lazily-resolved function to the module object, and a plain module is not
# callable. Two files in this repo's own test suite do that, which is how the
# breakage was found: tests that passed alone failed in the suite.
#
# The fix is the one `arche.detect` already uses and documents (decision
# 2026-08-07): make the module itself callable, so it stops mattering which of
# the two the name resolved to first. Both spellings work, in any import order.
import sys as _sys
from types import ModuleType as _ModuleType


class _CallableExtractModule(_ModuleType):
    """``arche.extract`` — the module, and the verb, under one name."""

    def __call__(self, *args, **kwargs):  # type: ignore[override]
        return extract(*args, **kwargs)


_sys.modules[__name__].__class__ = _CallableExtractModule
