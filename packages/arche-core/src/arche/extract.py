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

"""Entity extraction: a model proposes, the validators decide.

Usage:
    from arche.extract import extract
    entities = extract("Janet Okafor called from +234 803 555 7890")
    for e in entities:
        print(e.entity_type, e.text, e.confidence)

The model is optional. Without ``arche-core[detect2]`` the ``basic`` extractor
runs alone: the name lexicon, the address parser, and the identifier, phone
and email patterns with their checksums and cue gates. With it, GLiNER 2.5
proposes the fuzzy spans -- people, organisations, places -- and the same
validators run over the result; a checksummed identifier always beats a
model span for the same stretch of text (:func:`_merge_entities`).

Backend options:
    ``"auto"``         -- GLiNER 2.5 if installed, plus ``basic`` (default)
    ``"basic"``        -- lexicon + validators + patterns, no model, no download
    ``"gliner2"``      -- GLiNER 2.5 only, general labels (raises if not installed)
    ``"gliner2-pii"``  -- GLiNER2-PII only, personal-data labels (raises if not installed)
    ``"auto+llm"``     -- ``auto`` plus an LLM proposer (needs an API key)

``"regex"`` is accepted as an alias of ``"basic"`` -- the earlier name said how
the extractor worked rather than what it was. GLiNER v1 (``"gliner"``) was
removed in 0.9.0; ``"gliner2"`` is its replacement.
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


#: The backend vocabulary. One word each for what runs; ``regex`` survives as a
#: spelling of ``basic`` because the name appeared in published examples.
BACKENDS: tuple[str, ...] = ("auto", "basic", "gliner2", "gliner2-pii", "auto+llm")
BACKEND_ALIASES: dict[str, str] = {"regex": "basic"}


def canonical_backend(backend: str) -> str:
    """``regex`` -> ``basic``; everything else unchanged.

    Shared by every entry point that takes ``backend=`` so the alias means the
    same thing in :func:`extract`, ``Pipeline``, ``compare`` and the CLI.
    """
    return BACKEND_ALIASES.get(backend, backend)


def _unknown_backend(backend: str) -> ValueError:
    hint = ""
    if backend == "gliner":
        hint = (" GLiNER v1 ('gliner', the [detect] extra) was removed in 0.9.0; "
                "'gliner2' is its replacement and [detect] now installs it.")
    return ValueError(
        f"Unknown backend: {backend!r}. Use one of {', '.join(repr(b) for b in BACKENDS)} "
        f"('regex' is accepted for 'basic').{hint}"
    )


def extract(
    text: str,
    entity_types: list[str] | None = None,
    backend: str = "auto",
    llm_config: object | None = None,
    *,
    schema=None,
):
    """Extract entities from *text* -- or, with ``schema=``, one record in your own fields.

    Parameters
    ----------
    text:
        Free-form input text to scan.
    entity_types:
        Optional list of entity types to restrict extraction to.
        When ``None`` all supported types are extracted.
    schema:
        A declaration (from :func:`arche.schema`: a YAML path, a dict or a
        ``Declaration``). The call then returns an
        :class:`arche.doc.Extraction` instead of a list: the declared fields
        filled from the most trustworthy source that can answer each -- a
        validated detector, then a model asked for *your* labels -- with the
        evidence per field and the unfilled fields named. See
        :func:`arche.doc.extract`.
    backend:
        ``"auto"`` -- GLiNER 2.5 when installed, plus ``basic`` (default).
        ``"basic"`` -- lexicon, validators and patterns; no model, no download.
        ``"gliner2"`` -- GLiNER 2.5 only (raises if not installed).
        ``"gliner2-pii"`` -- GLiNER2-PII only (raises if not installed).
        ``"auto+llm"`` -- ``auto`` plus an LLM proposer (needs an API key).
        ``"regex"`` is an alias of ``"basic"``.
    llm_config:
        An :class:`~arche.llm.LLMConfig` instance.  Required when
        ``backend="auto+llm"``.  If ``None`` and the backend needs LLM,
        configuration is read from :func:`~arche.config.get_config`.

    Returns
    -------
    list[Entity]
        Extracted entities sorted by their position in the text.
    """
    backend = canonical_backend(backend)
    if schema is not None:
        from .declare import schema as _schema
        from .doc._extract import extract as _to_schema

        decl = _schema(schema)
        return _to_schema(decl, text=text, entity_backend=backend,
                          jurisdiction=decl.jurisdiction if decl.jurisdiction != "default" else "NG")
    if backend in ("auto", "auto+llm"):
        try:
            entities = _extract_gliner2(text, entity_types)
            # The validators fill in what the model has no checksum for.
            regex_entities = _extract_regex(text, entity_types)
            entities = _merge_entities(entities, regex_entities)
        except ImportError:
            warnings.warn(
                "GLiNER 2.5 is not installed, so only the basic extractor ran: "
                "identifiers, phones, emails and lexicon names, but no model-"
                "proposed people, organisations or places. Install it with: "
                "pip install 'arche-core[detect2]'",
                stacklevel=2,
            )
            entities = list(_extract_regex(text, entity_types))
        except Exception as e:
            _log.warning("GLiNER 2.5 extraction failed, falling back to basic: %s", e)
            warnings.warn(
                f"GLiNER 2.5 extraction failed ({e}); only the basic extractor ran.",
                stacklevel=2,
            )
            entities = list(_extract_regex(text, entity_types))

        # --- LLM proposer (additional, not replacement) ---
        if backend == "auto+llm":
            llm_entities = _extract_llm(text, llm_config)
            entities = _merge_entities(entities, llm_entities)

        return sorted(entities, key=lambda e: e.start)
    elif backend == "gliner2":
        return sorted(_extract_gliner2(text, entity_types), key=lambda e: e.start)
    elif backend == "gliner2-pii":
        return sorted(_extract_gliner2_pii(text, entity_types), key=lambda e: e.start)
    elif backend == "basic":
        return sorted(_extract_regex(text, entity_types), key=lambda e: e.start)
    else:
        raise _unknown_backend(backend)


# ===================================================================
# GLiNER 2 backends (optional, `arche-core[detect2]`)
# ===================================================================

# ── Identity-specific label set ──────────────────────────────────────────────
# Zero-shot labels for the general extractor: these describe what to look for.
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

# Map the model's raw labels to arche's entity type taxonomy.
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

# GLiNER2-PII's own vocabulary (42 labels) onto the same taxonomy. Labels not
# listed here still come back, uppercased, so nothing the model found is lost;
# these are the ones the rest of arche knows what to do with.
_PII_LABEL_MAP: dict[str, str] = {
    "person": "PERSON", "full_name": "PERSON", "first_name": "PERSON",
    "middle_name": "PERSON", "last_name": "PERSON",
    "email": "EMAIL",
    "phone_number": "PHONE",
    "address": "LOCATION", "street_address": "LOCATION", "city": "LOCATION",
    "state_or_region": "LOCATION", "postal_code": "LOCATION", "country": "LOCATION",
    "date_of_birth": "DATE",
    "government_id": "NATIONAL_ID", "national_id_number": "NATIONAL_ID",
    "passport_number": "NATIONAL_ID", "drivers_license_number": "NATIONAL_ID",
    "tax_id": "NATIONAL_ID", "tax_number": "NATIONAL_ID",
    "ip_address": "IP_ADDRESS",
}
_PII_LABELS = list(_PII_LABEL_MAP)


def _extract_gliner2(text: str, entity_types: list[str] | None = None) -> list[Entity]:
    """Extract entities with GLiNER 2.5, the general extractor.

    The caller's ``entity_types`` become the labels the model is asked for --
    the whole point of a zero-shot extractor -- and default to the identity
    set above. Spans come back through :func:`arche.detect._gliner2.propose`,
    the one reader of the model's label-grouped response shape.
    """
    from .config import get_config
    from .detect._gliner2 import propose

    labels = [label.lower() for label in entity_types] if entity_types else _IDENTITY_LABELS
    return [
        Entity(text=s.text, entity_type=_GLINER_LABEL_MAP.get(s.label, s.label.upper()),
               confidence=s.confidence, start=s.start, end=s.end, source="gliner2")
        for s in propose(text, labels, threshold=get_config().gliner2_threshold)
    ]


def _extract_gliner2_pii(text: str, entity_types: list[str] | None = None) -> list[Entity]:
    """Extract entities with GLiNER2-PII, the personal-data proposer.

    Asked for its own vocabulary (or the caller's), mapped onto the taxonomy
    above. Precision on names is modest by the model card's own numbers, so
    treat the output as proposals: the validators in :func:`_merge_entities`
    and the statute in ``Pipeline`` decide.
    """
    from .config import get_config
    from .detect._gliner2 import propose

    cfg = get_config()
    labels = [label.lower() for label in entity_types] if entity_types else _PII_LABELS
    return [
        Entity(text=s.text, entity_type=_PII_LABEL_MAP.get(s.label, s.label.upper()),
               confidence=s.confidence, start=s.start, end=s.end, source="gliner2-pii")
        for s in propose(text, labels, model=cfg.gliner2_pii_model,
                         threshold=cfg.gliner2_pii_threshold)
    ]


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

    # --- People, from the shipped name lexicon ---
    # Two or more adjacent lexicon names (an initial allowed between them),
    # capitalised in the text. A deterministic backend used to have no name
    # rule at all, so a text-derived person record carried an id and an email
    # and no name; the comparator then had nothing to corroborate the id with.
    if _want("PERSON"):
        try:
            from .detect.names import person_spans

            for start, end, span in person_spans(text):
                if not _overlaps(entities, start, end):
                    entities.append(
                        Entity(
                            text=span,
                            entity_type="PERSON",
                            confidence=0.70,
                            start=start,
                            end=end,
                            source="lexicon",
                        )
                    )
        except ImportError:
            pass

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
                # A span already claimed by a validated non-phone entity keeps
                # it. The case that found this: "ISBN 1806342456" -- the ten
                # digits pass the ZA tax-reference *format* (any 10 digits
                # starting 0/1/2/3/9, confidence 0.50, no checksum) while the
                # ISBN-10 check digit has actually been verified. Without this
                # guard both were emitted over the same digits, and the merge
                # in `_merge_entities` -- which trusts `source="african"`
                # unconditionally -- then dropped the ISBN in favour of the
                # weaker guess.
                if any(e.entity_type != "PHONE"
                       and nid.start < e.end and nid.end > e.start
                       for e in entities):
                    continue
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
