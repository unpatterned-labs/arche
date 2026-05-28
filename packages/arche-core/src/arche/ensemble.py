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

"""GliNER-first extraction ensemble — statistical + deterministic + adjudication.

Produces NVIDIA gliner-PII-quality output with rich typed labels, plus
African identity intelligence that no generic PII model carries.

Architecture: GliNER excels at fuzzy spans (persons, organisations, locations,
addresses, dates).  Deterministic regex excels at validated structured data
(SWIFT codes, account numbers, national IDs, postcodes, states).  The
adjudicator lets each layer win where it is strongest.

The extraction stages:
    Stage 1: Statistical — GliNER with PII-focused labels for persons, orgs,
             locations, addresses, dates, occupations.
    Stage 2: Deterministic — country-specific ID validators, phone/email regex,
             SWIFT codes, account numbers, postcodes, states.
    Stage 3: Adjudication — deterministic wins for validated structured types,
             higher-confidence entity wins for everything else.

Usage:
    from arche.ensemble import extract_identity_evidence, detect_sensitive_spans
    evidence = extract_identity_evidence("Dr. Jordan Wells lives at 2901 Connecticut Ave NW...")
    spans = detect_sensitive_spans("NIN 12345678901, BVN 22100987654")
"""

from __future__ import annotations

import logging
import re
import warnings

from .types import IdentityEvidence, SensitiveSpan

_log = logging.getLogger("arche")


# ═══════════════════════════════════════════════════════════════════════════════
# LABEL TAXONOMY — rich typed labels matching/exceeding NVIDIA gliner-PII
# ═══════════════════════════════════════════════════════════════════════════════

# Person
_PERSON_LABELS = {"person", "first_name", "last_name", "full_name", "title"}
# Location
_LOCATION_LABELS = {"location", "street_address", "city", "state", "postcode",
                    "country", "address"}
# Organization
_ORG_LABELS = {"organization", "company", "employer"}
# Financial
_FINANCIAL_LABELS = {"account_number", "swift_bic", "iban", "credit_card", "money", "currency"}
# Identity documents
_ID_LABELS = {"national_id", "nin", "bvn", "ghana_card", "kenya_id", "sa_id",
              "passport_number", "ssn", "tin", "pvc", "aadhaar"}
# Contact
_CONTACT_LABELS = {"phone_number", "email", "phone"}
# Temporal
_TIME_LABELS = {"date", "date_of_birth", "time"}
# Professional
_PROF_LABELS = {"occupation", "job_title"}


# ═══════════════════════════════════════════════════════════════════════════════
# STAGE 1: DETERMINISTIC EXTRACTION
# ═══════════════════════════════════════════════════════════════════════════════

# ── Rich regex patterns ──────────────────────────────────────────────────────

_PATTERNS: list[tuple[str, re.Pattern, str, float]] = [
    # (label, pattern, detector_source, base_confidence)

    # Emails
    ("email", re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b"),
     "regex", 0.95),

    # SWIFT/BIC codes (8 or 11 chars: XXXXCCLL or XXXXCCLLBBB)
    ("swift_bic", re.compile(r"\b[A-Z]{4}[A-Z]{2}[A-Z0-9]{2}(?:[A-Z0-9]{3})?\b"),
     "regex", 0.90),

    # Account numbers (6-12 digits, context-dependent)
    ("account_number", re.compile(
        r"(?:account|acct|a/c)\s*(?:number|no|num|#|:|\s)\s*(?:#|:|\s)\s*(\d{6,12})",
        re.IGNORECASE),
     "regex", 0.85),

    # Time patterns (HH:MM AM/PM or HH:MM:SS)
    ("time", re.compile(
        r"\b\d{1,2}:\d{2}(?::\d{2})?\s*(?:AM|PM|am|pm)?\b"),
     "regex", 0.85),

    # Dates — ISO (non-capturing groups to return full match)
    ("date", re.compile(r"\b(?:19|20)\d{2}[/\-](?:0?[1-9]|1[0-2])[/\-](?:0?[1-9]|[12]\d|3[01])\b"),
     "regex", 0.85),
    # Dates — DD/MM/YYYY
    ("date", re.compile(r"\b(?:0?[1-9]|[12]\d|3[01])[/\-](?:0?[1-9]|1[0-2])[/\-](?:19|20)\d{2}\b"),
     "regex", 0.85),
    # Dates — Month DD, YYYY
    ("date", re.compile(
        r"\b(?:January|February|March|April|May|June|July|August|September|October|November|December"
        r"|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Oct|Nov|Dec)"
        r"\s+\d{1,2}(?:,?\s+\d{4})?\b", re.IGNORECASE),
     "regex", 0.85),

    # US ZIP codes (5 or 5+4)
    ("postcode", re.compile(r"\b\d{5}(?:-\d{4})?\b"), "regex", 0.60),

    # US state abbreviations (2 uppercase letters after comma+space)
    ("state", re.compile(r"(?<=,\s)([A-Z]{2})(?=\s\d{5})"), "regex", 0.80),

    # Occupation/title patterns (common prefixes)
    ("occupation", re.compile(
        r"\b(?:Senior|Junior|Chief|Lead|Principal|Staff|Head)\s+"
        r"(?:[A-Z][a-z]+\s+){0,3}(?:Engineer|Architect|Analyst|Manager|Director|Officer|Scientist|Designer|Developer|Consultant|Administrator)\b"),
     "regex", 0.80),

    # Dr/Prof/Mr/Mrs title as indicator (helps split first/last)
    ("title", re.compile(r"\b(?:Dr|Prof|Mr|Mrs|Ms|Eng|Rev|Chief|Alhaji|Hajia)\.?\s"),
     "regex", 0.75),
]


def _extract_deterministic(text: str) -> list[IdentityEvidence]:
    """Stage 1: Extract entities using deterministic regex patterns."""
    evidence: list[IdentityEvidence] = []
    seen_spans: set[tuple[int, int]] = set()

    # ── African national IDs (highest priority) ──────────────────────────
    try:
        from .detect._africa.ids import detect_african_ids
        for nid in detect_african_ids(text):
            span = (nid.start, nid.end)
            if _overlaps_set(seen_spans, span):
                continue
            seen_spans.add(span)
            label = nid.id_type.lower()  # nin, bvn, ghana_card, etc.
            evidence.append(IdentityEvidence(
                text=nid.text, label=label,
                confidence=nid.confidence, start=nid.start, end=nid.end,
                detector_source="african",
                country_hint=nid.country,
                validator_status="checksum_valid" if nid.metadata else "format_valid",
                metadata=nid.metadata,
            ))
    except ImportError:
        pass
    except Exception as e:
        _log.warning("African ID extraction failed: %s", e)

    # ── African phone numbers ────────────────────────────────────────────
    try:
        from .detect._africa.phones import parse_african_phone
        for hit in parse_african_phone(text):
            span = (hit["start"], hit["end"])
            if _overlaps_set(seen_spans, span):
                continue
            seen_spans.add(span)
            evidence.append(IdentityEvidence(
                text=hit["raw"], label="phone_number",
                confidence=0.92, start=hit["start"], end=hit["end"],
                detector_source="african",
                country_hint=hit.get("country", ""),
                validator_status="format_valid",
                metadata={"international": hit.get("international", "")},
            ))
    except ImportError:
        pass

    # ── Account numbers (before phone, so digit strings in bank context
    #    are not misclassified as phones) ─────────────────────────────────
    _acct_re = re.compile(
        r"(?:account|acct|a/c)\s*(?:number|no|num|#|:|\s)\s*(?:#|:|\s)\s*(\d{6,12})",
        re.IGNORECASE,
    )
    for m in _acct_re.finditer(text):
        s, e = m.start(1), m.end(1)
        span = (s, e)
        if _overlaps_set(seen_spans, span):
            continue
        seen_spans.add(span)
        evidence.append(IdentityEvidence(
            text=m.group(1), label="account_number",
            confidence=0.85, start=s, end=e,
            detector_source="regex", validator_status="context_valid",
        ))

    # ── Generic phone (fallback) ─────────────────────────────────────────
    generic_phone_re = re.compile(
        r"(?<!\d)"
        r"(?:\+?\d{1,3}[\s\-]?)?"
        r"(?:\(?\d{2,4}\)?[\s\-]?)"
        r"\d{3,4}[\s\-]?\d{3,4}"
        r"(?!\d)"
    )
    for m in generic_phone_re.finditer(text):
        span = (m.start(), m.end())
        if _overlaps_set(seen_spans, span):
            continue
        seen_spans.add(span)
        evidence.append(IdentityEvidence(
            text=m.group().strip(), label="phone_number",
            confidence=0.70, start=m.start(), end=m.end(),
            detector_source="regex", validator_status="unchecked",
        ))

    # ── African currencies ───────────────────────────────────────────────
    try:
        from .detect._money.african import detect_african_currency
        for hit in detect_african_currency(text):
            span = (hit["start"], hit["end"])
            if _overlaps_set(seen_spans, span):
                continue
            seen_spans.add(span)
            evidence.append(IdentityEvidence(
                text=hit["raw"], label="money",
                confidence=0.85, start=hit["start"], end=hit["end"],
                detector_source="african",
                metadata={"currency": hit.get("currency", ""), "amount": hit.get("amount")},
            ))
    except ImportError:
        pass

    # ── Standard money patterns ──────────────────────────────────────────
    money_re = re.compile(
        r"(?:[$\u20ac\u00a3])\s?\d[\d,]*(?:\.\d{1,2})?"
        r"|\d[\d,]*(?:\.\d{1,2})?\s?(?:USD|EUR|GBP|dollars?|euros?|pounds?)\b",
        re.IGNORECASE,
    )
    for m in money_re.finditer(text):
        span = (m.start(), m.end())
        if _overlaps_set(seen_spans, span):
            continue
        seen_spans.add(span)
        evidence.append(IdentityEvidence(
            text=m.group(), label="money",
            confidence=0.85, start=m.start(), end=m.end(),
            detector_source="regex",
        ))

    # ── Apply all generic regex patterns ─────────────────────────────────
    for label, pattern, source, conf in _PATTERNS:
        for m in pattern.finditer(text):
            # Account number pattern uses group(1) if it has a capture group
            matched_text = m.group(1) if m.lastindex and m.lastindex >= 1 else m.group()
            if label == "account_number":
                s = m.start(1) if m.lastindex else m.start()
                e = m.end(1) if m.lastindex else m.end()
                span = (s, e)
            else:
                span = (m.start(), m.end())
            if _overlaps_set(seen_spans, span):
                continue
            seen_spans.add(span)
            evidence.append(IdentityEvidence(
                text=matched_text.strip(), label=label,
                confidence=conf, start=span[0], end=span[1],
                detector_source=source,
            ))

    # ── Person name heuristics (no ML needed) ───────────────────────────
    evidence.extend(_extract_name_heuristics(text, seen_spans))

    return evidence


# ── Name heuristic patterns ─────────────────────────────────────────────────

_TITLE_PATTERN = re.compile(
    r"\b(Dr|Prof|Mr|Mrs|Ms|Miss|Eng|Rev|Chief|Alhaji|Hajia|Hon|Senator|Justice|"
    r"Barrister|Architect|Pastor|Imam|Sheikh|Dame|Sir|Malam|Mallam)"
    r"\.?\s+"
    r"((?:[A-Z][a-z]+(?:\s+|$)){1,4})",
)

_CONTEXT_PATTERN = re.compile(
    r"(?:[Pp]atient|[Nn]ame|[Cc]lient|[Bb]eneficiary|[Aa]pplicant|[Oo]wner|"
    r"[Hh]older|[Aa]ttention|[Ss]igned|[Ff]rom|[Dd]ear|[Vv]oter|[Ss]ubscriber)"
    r"\s*[:=]\s*"
    r"((?:[A-Z][a-z]*\.?\s+){1,4}[A-Z][a-z]+)"
    r"(?=[,.\s]*(?:[A-Z][a-z]*:|,|\.|$|\s*\d|\s+[a-z]))",
)

_ALLCAPS_NAME_PATTERN = re.compile(
    r"\b([A-Z]{2,}(?:\s+[A-Z]{2,}){1,3})\b"
)


def _extract_name_heuristics(
    text: str, seen_spans: set[tuple[int, int]],
) -> list[IdentityEvidence]:
    """Heuristic person name detection for the base package (no GliNER).

    Three strategies:
    1. Title-context: "Dr. Fatima Abdullahi" -> person
    2. Document-context: "Patient: Fatima Abdullahi" -> person
    3. Cultural name dictionary: consecutive tokens in NAME_EQUIVALENCES -> person
    """
    names: list[IdentityEvidence] = []

    # 1. Title-context names (highest confidence heuristic)
    for m in _TITLE_PATTERN.finditer(text):
        name_text = m.group(2).strip()
        if len(name_text) < 3:
            continue
        span = (m.start(2), m.start(2) + len(name_text))
        if _overlaps_set(seen_spans, span):
            continue
        seen_spans.add(span)
        names.append(IdentityEvidence(
            text=name_text, label="person",
            confidence=0.60, start=span[0], end=span[1],
            detector_source="heuristic",
        ))

    # 2. Document-context names
    for m in _CONTEXT_PATTERN.finditer(text):
        name_text = m.group(1).strip()
        if len(name_text) < 3:
            continue
        span = (m.start(1), m.start(1) + len(name_text))
        if _overlaps_set(seen_spans, span):
            continue
        seen_spans.add(span)
        names.append(IdentityEvidence(
            text=name_text, label="person",
            confidence=0.55, start=span[0], end=span[1],
            detector_source="heuristic",
        ))

    # 3. Cultural name dictionary lookup
    try:
        from .detect._names.lexicon import KNOWN_AFRICAN_NAMES, NAME_EQUIVALENCES, _strip_diacritics

        _name_dict_extract(
            text,
            seen_spans,
            names,
            NAME_EQUIVALENCES,
            KNOWN_AFRICAN_NAMES,
            _strip_diacritics,
        )
    except ImportError:
        pass

    return names


def _name_dict_extract(
    text: str,
    seen_spans: set[tuple[int, int]],
    names: list[IdentityEvidence],
    name_equivalences: dict[str, set[str]],
    known_name_tokens: set[str],
    strip_fn: callable,
) -> None:
    """Detect person names using the cultural naming dictionary.

    If 2+ consecutive capitalized tokens are in NAME_EQUIVALENCES,
    flag the span as a person name.
    """
    # Find sequences of capitalized words
    cap_words = list(re.finditer(r"\b[A-Z][a-z]{2,}\b", text))
    if len(cap_words) < 2:
        return

    i = 0
    while i < len(cap_words) - 1:
        w1 = cap_words[i]
        w2 = cap_words[i + 1]

        # Must be adjacent (separated by only whitespace/punctuation, max 3 chars gap)
        gap = w2.start() - w1.end()
        if gap > 3:
            i += 1
            continue

        t1 = strip_fn(w1.group().lower())
        t2 = strip_fn(w2.group().lower())

        t1_known = t1 in known_name_tokens
        t2_known = t2 in known_name_tokens
        if t1_known or t2_known:
            confidence = 0.55 if (t1 in name_equivalences or t2 in name_equivalences) else 0.52
            method = (
                "cultural_name_dictionary"
                if (t1 in name_equivalences or t2 in name_equivalences)
                else "cultural_name_lexicon"
            )
            # Check if a third word also matches
            end_idx = w2.end()
            if i + 2 < len(cap_words):
                w3 = cap_words[i + 2]
                if w3.start() - w2.end() <= 3:
                    end_idx = w3.end()
                    i += 1  # skip the third word

            name_text = text[w1.start():end_idx].strip()
            span = (w1.start(), end_idx)
            if not _overlaps_set(seen_spans, span) and len(name_text) >= 4:
                seen_spans.add(span)
                names.append(IdentityEvidence(
                    text=name_text, label="person",
                    confidence=confidence, start=span[0], end=span[1],
                    detector_source="heuristic",
                    metadata={"method": method},
                ))
            i += 2
        else:
            i += 1


# ═══════════════════════════════════════════════════════════════════════════════
# STAGE 2: STATISTICAL EXTRACTION (GliNER)
# ═══════════════════════════════════════════════════════════════════════════════




_GLINER_LABELS = [
    "person", "first_name", "last_name",
    "organization", "location", "city",
    "street_address", "occupation",
    "date", "date_of_birth",
    "money",
]

_GLINER_LABEL_MAP = {
    "person": "person", "first_name": "first_name", "last_name": "last_name",
    "organization": "organization", "location": "location", "city": "city",
    "street_address": "street_address", "occupation": "occupation",
    "date": "date", "date_of_birth": "date_of_birth", "money": "money",
}


def _extract_statistical(text: str) -> list[IdentityEvidence]:
    """Stage 2: Extract entities using GliNER zero-shot NER.

    Uses the shared model registry for caching and offline support.
    The model name and confidence threshold are read from ``ArcheConfig``.
    """
    from .config import get_config  # local import to avoid circular deps

    try:
        from ._models import get_gliner
        model = get_gliner()  # uses config model name, cached

        raw = model.predict_entities(text, _GLINER_LABELS, threshold=get_config().gliner_threshold)
        evidence: list[IdentityEvidence] = []
        for ent in raw:
            label = _GLINER_LABEL_MAP.get(ent["label"].lower(), ent["label"].lower())
            evidence.append(IdentityEvidence(
                text=ent["text"], label=label,
                confidence=float(ent["score"]),
                start=ent["start"], end=ent["end"],
                detector_source="gliner",
            ))
        return evidence
    except ImportError:
        warnings.warn(
            "GliNER not available. Ensemble statistical layer is disabled. "
            "Person/organization/location detection will use heuristics only. "
            "Install with: pip install arche-core[gliner]",
            stacklevel=2,
        )
        return []
    except Exception as e:
        _log.warning("GliNER extraction failed: %s", e)
        warnings.warn(
            f"GliNER extraction failed ({e}). Statistical layer disabled for this call. "
            "Person/organization/location detection will use heuristics only.",
            stacklevel=2,
        )
        return []


# ═══════════════════════════════════════════════════════════════════════════════
# STAGE 3: ADJUDICATION — merge, deduplicate, validate
# ═══════════════════════════════════════════════════════════════════════════════

def _adjudicate(
    deterministic: list[IdentityEvidence],
    statistical: list[IdentityEvidence],
) -> list[IdentityEvidence]:
    """Merge deterministic + statistical evidence with adjudication rules.

    GliNER-first architecture — each layer wins where it is strongest:

    Rules:
    1. **Deterministic always wins** for validated structured types:
       national IDs, SWIFT/BIC, account numbers, postcodes, states,
       and African-sourced phone numbers (checksum/format-validated).
    2. **Higher confidence wins** for everything else (persons, orgs,
       locations, addresses, dates, occupations, money).  This means
       GliNER's person detection (typ. 0.90+) beats heuristic name
       detection (typ. 0.55-0.60) on overlapping spans.
    3. Non-overlapping spans from both layers are always kept.
    4. Validator-confirmed spans (``checksum_valid``, ``format_valid``)
       always outrank model-only spans regardless of confidence.
    """
    # Labels where deterministic always wins on overlap
    det_wins_labels = {
        "national_id", "nin", "bvn", "ghana_card", "kenya_id", "sa_id",
        "passport_number", "ssn", "tin", "pvc", "aadhaar",
        "swift_bic", "iban", "credit_card",
        "account_number",
        "postcode", "state",
    }

    # Build a list of (evidence, is_deterministic) for overlap resolution
    all_evidence: list[tuple[IdentityEvidence, bool]] = []
    for ev in deterministic:
        all_evidence.append((ev, True))
    for ev in statistical:
        all_evidence.append((ev, False))

    # Sort by start position, then by confidence descending so that when
    # we sweep left-to-right the highest-confidence span at each position
    # is encountered first.
    all_evidence.sort(key=lambda pair: (pair[0].start, -pair[0].confidence))

    final: list[IdentityEvidence] = []

    for ev, _is_det in all_evidence:
        if not final:
            final.append(ev)
            continue

        prev = final[-1]

        # Non-overlapping — always keep
        if ev.start >= prev.end:
            final.append(ev)
            continue

        # Overlapping — apply adjudication rules
        # Rule 4: Validator-confirmed spans always win
        prev_validated = prev.validator_status in ("checksum_valid", "format_valid")
        ev_validated = ev.validator_status in ("checksum_valid", "format_valid")
        if prev_validated and not ev_validated:
            continue  # keep prev
        if ev_validated and not prev_validated:
            final[-1] = ev
            continue

        # Rule 1: Deterministic wins for structured ID types
        prev_is_det_wins = prev.label in det_wins_labels
        ev_is_det_wins = ev.label in det_wins_labels

        # Also treat African-sourced phone_number as det-wins
        prev_is_det_wins = prev_is_det_wins or (
            prev.label == "phone_number" and prev.detector_source == "african"
        )
        ev_is_det_wins = ev_is_det_wins or (
            ev.label == "phone_number" and ev.detector_source == "african"
        )

        if prev_is_det_wins and not ev_is_det_wins:
            continue  # keep prev
        if ev_is_det_wins and not prev_is_det_wins:
            final[-1] = ev
            continue

        # Rule 2: Higher confidence wins
        if ev.confidence > prev.confidence:
            final[-1] = ev
        # else keep prev (equal or lower confidence)

    return final


# ═══════════════════════════════════════════════════════════════════════════════
# NAME SPLITTING — extract first_name, last_name from person spans
# ═══════════════════════════════════════════════════════════════════════════════

_TITLES = {"dr", "prof", "mr", "mrs", "ms", "eng", "rev", "chief", "alhaji", "hajia", "hon"}


def _split_person_name(evidence: list[IdentityEvidence]) -> list[IdentityEvidence]:
    """Post-process: split 'person' labels into first_name + last_name."""
    expanded: list[IdentityEvidence] = []

    for ev in evidence:
        if ev.label != "person" or " " not in ev.text.strip():
            expanded.append(ev)
            continue

        parts = ev.text.strip().split()
        # Remove titles
        clean_parts = [p for p in parts if p.lower().rstrip(".") not in _TITLES]
        if not clean_parts:
            expanded.append(ev)
            continue

        if len(clean_parts) >= 2:
            first = clean_parts[0]
            last = clean_parts[-1]
            # middle parts available: clean_parts[1:-1]

            # Add the full person span
            expanded.append(ev)

            # Add first_name
            first_start = ev.text.find(first)
            if first_start >= 0:
                expanded.append(IdentityEvidence(
                    text=first, label="first_name",
                    confidence=ev.confidence * 0.95,
                    start=ev.start + first_start,
                    end=ev.start + first_start + len(first),
                    detector_source=ev.detector_source,
                    metadata={"derived_from": "person_split"},
                ))

            # Add last_name
            last_start = ev.text.rfind(last)
            if last_start >= 0:
                expanded.append(IdentityEvidence(
                    text=last, label="last_name",
                    confidence=ev.confidence * 0.95,
                    start=ev.start + last_start,
                    end=ev.start + last_start + len(last),
                    detector_source=ev.detector_source,
                    metadata={"derived_from": "person_split"},
                ))
        else:
            expanded.append(ev)

    return expanded


# ═══════════════════════════════════════════════════════════════════════════════
# PUBLIC API
# ═══════════════════════════════════════════════════════════════════════════════


def extract_identity_evidence(
    text: str,
    *,
    jurisdiction: str = "auto",
    split_names: bool = True,
    backend: str = "auto",
) -> list[IdentityEvidence]:
    """Extract identity evidence using the three-layer ensemble.

    Produces rich typed labels (first_name, last_name, street_address,
    city, state, postcode, account_number, swift_bic, occupation, time)
    plus African identity intelligence (NIN, BVN, Ghana Card, cultural naming).

    Parameters
    ----------
    text:
        Input text to extract from.
    jurisdiction:
        ISO 3166-1 alpha-2 country code (e.g., ``"NG"``, ``"GH"``, ``"KE"``).
        When set, boosts confidence for IDs from that country, applies
        country-specific phone normalization, and annotates evidence with
        the country hint.  ``"auto"`` infers jurisdiction from detected IDs.
    split_names:
        If True, split "person" spans into first_name + last_name.
    backend:
        "auto" (deterministic + GliNER), "deterministic" (regex only),
        "gliner" (GliNER only).
    """
    if backend == "deterministic":
        evidence = _extract_deterministic(text)
    elif backend == "gliner":
        evidence = _extract_statistical(text)
    else:
        # Auto: both layers run, adjudicator picks the winner per span
        det = _extract_deterministic(text)
        stat = _extract_statistical(text)
        evidence = _adjudicate(det, stat)

    if split_names:
        evidence = _split_person_name(evidence)

    # ── Jurisdiction enrichment ─────────────────────────────────────────
    evidence = _apply_jurisdiction(evidence, text, jurisdiction)

    return sorted(evidence, key=lambda e: e.start)


def _apply_jurisdiction(
    evidence: list[IdentityEvidence],
    text: str,
    jurisdiction: str,
) -> list[IdentityEvidence]:
    """Enrich evidence with jurisdiction-specific context.

    1. If jurisdiction is "auto", infer from the most-detected country_hint.
    2. Boost confidence for IDs matching the jurisdiction.
    3. Apply phone code normalization metadata.
    4. Stamp country_hint on evidence that lacks one.
    """
    if not evidence:
        return evidence

    # ── Infer jurisdiction from evidence ────────────────────────────────
    resolved_jurisdiction = jurisdiction.upper() if jurisdiction != "auto" else ""
    if not resolved_jurisdiction:
        country_votes: dict[str, int] = {}
        for ev in evidence:
            if ev.country_hint:
                country_votes[ev.country_hint] = country_votes.get(ev.country_hint, 0) + 1
        if country_votes:
            resolved_jurisdiction = max(country_votes, key=country_votes.get)  # type: ignore[arg-type]

    if not resolved_jurisdiction:
        # Try to detect from text keywords
        resolved_jurisdiction = _infer_country_from_text(text)

    if not resolved_jurisdiction:
        return evidence

    # ── Load jurisdiction metadata ─────────────────────────────────────
    phone_code = ""
    # Try full jurisdiction pack first
    try:
        from .jurisdictions import get_profile
        profile = get_profile(resolved_jurisdiction)
        # Extract phone code from pack
        if profile.phone_formats:
            for pf in profile.phone_formats:
                if pf.get("prefixes"):
                    break
    except (ValueError, ImportError):
        pass

    # Fallback: restcountries for phone code
    if not phone_code:
        try:
            from .jurisdictions.restcountries import get_phone_code
            phone_code = get_phone_code(resolved_jurisdiction) or ""
        except Exception:
            pass

    # ── Enrich evidence ────────────────────────────────────────────────
    for ev in evidence:
        # Stamp country_hint on evidence without one
        if not ev.country_hint and ev.label in (
            "phone_number", "email", "first_name", "last_name",
            "person", "street_address", "city", "occupation",
        ):
            ev.country_hint = resolved_jurisdiction

        # Boost confidence for IDs matching the jurisdiction
        if ev.country_hint == resolved_jurisdiction and ev.label in _ID_LABELS:
            ev.confidence = min(ev.confidence + 0.05, 1.0)

        # Add phone_code to phone metadata
        if ev.label == "phone_number" and phone_code:
            ev.metadata = {**ev.metadata, "expected_phone_code": phone_code}

    return evidence


# Country detection keywords for auto-inference
_COUNTRY_KEYWORDS: dict[str, list[str]] = {
    "NG": ["nigeria", "nigerian", "nimc", "nibss", "inec", "firs", "naira", "lagos", "abuja"],
    "GH": ["ghana", "ghanaian", "nia ghana", "cedi", "accra"],
    "KE": ["kenya", "kenyan", "huduma", "safaricom", "nairobi"],
    "ZA": [
        "south africa", "south african", "popia",
        "south african rand", "johannesburg", "cape town",
    ],
    "RW": ["rwanda", "rwandan", "kigali"],
    "TZ": ["tanzania", "tanzanian", "nida", "dar es salaam"],
    "UG": ["uganda", "ugandan", "nira", "kampala"],
    "ET": ["ethiopia", "ethiopian", "kebele", "addis ababa"],
    "SN": ["senegal", "senegalese", "dakar"],
    "CI": ["ivory coast", "cote d'ivoire", "ivorian", "abidjan"],
    "CM": ["cameroon", "cameroonian", "douala", "yaounde"],
    "EG": ["egypt", "egyptian", "cairo"],
    "MA": ["morocco", "moroccan", "rabat", "casablanca"],
}


def _infer_country_from_text(text: str) -> str:
    """Infer country code from text keywords. Returns alpha-2 or empty string."""
    text_lower = text.lower()
    best_country = ""
    best_count = 0
    for code, keywords in _COUNTRY_KEYWORDS.items():
        count = sum(1 for kw in keywords if kw in text_lower)
        if count > best_count:
            best_count = count
            best_country = code
    return best_country if best_count >= 1 else ""


def detect_sensitive_spans(
    text: str,
    *,
    jurisdiction: str = "auto",
    backend: str = "auto",
) -> list[SensitiveSpan]:
    """Detect PII/PHI spans with adjudication and redaction recommendations.

    Uses the three-layer ensemble, then classifies each evidence as
    sensitive or not based on label type.

    Parameters
    ----------
    text:
        Input text to scan.
    jurisdiction:
        Country hint for ID validation.
    backend:
        Extraction backend passed to ``extract_identity_evidence``.
    """
    evidence = extract_identity_evidence(
        text,
        jurisdiction=jurisdiction,
        split_names=False,
        backend=backend,
    )

    # Also run existing PII detection for credit cards and other patterns
    try:
        from .protect import detect_pii
        pii_detections = detect_pii(text)
    except Exception:
        pii_detections = []

    spans: list[SensitiveSpan] = []
    seen: set[tuple[int, int]] = set()

    # Convert evidence to sensitive spans where applicable
    sensitive_labels = (
        _ID_LABELS | _CONTACT_LABELS | _FINANCIAL_LABELS |
        {"first_name", "last_name", "date_of_birth", "street_address", "postcode"}
    )

    for ev in evidence:
        if ev.label not in sensitive_labels:
            continue
        span_key = (ev.start, ev.end)
        if span_key in seen:
            continue
        seen.add(span_key)

        # Determine redaction recommendation
        if ev.validator_status in ("checksum_valid", "format_valid"):
            redaction = "mask"  # High confidence — safe to auto-redact
        elif ev.confidence >= 0.85:
            redaction = "mask"
        elif ev.confidence >= 0.60:
            redaction = "review_required"
        else:
            redaction = "review_required"

        spans.append(SensitiveSpan(
            text=ev.text, label=ev.label,
            confidence=ev.confidence,
            start=ev.start, end=ev.end,
            country_hint=ev.country_hint,
            validator_status=ev.validator_status,
            detector_source=ev.detector_source,
            redaction=redaction,
        ))

    # Add PII detections not already covered.
    # The `sensitive_labels` filter above gates the GLiNER / arche evidence
    # path; we apply an equivalent guard to the protect.detect_pii path so
    # non-sensitive labels (organization, location, occupation) that
    # Presidio surfaces don't slip in via this back door.
    _non_sensitive_pii_labels = {
        "organization", "company", "employer",
        "location", "city", "state", "country",
        "occupation", "title", "url",
        "date_time", "date", "time",
    }
    from .types import pii_to_sensitive_span
    for pii in pii_detections:
        span_key = (pii.start, pii.end)
        if span_key in seen:
            continue
        span = pii_to_sensitive_span(pii)
        if span.label in _non_sensitive_pii_labels:
            continue
        seen.add(span_key)
        spans.append(span)

    return sorted(spans, key=lambda s: s.start)


def format_tagged_text(text: str, evidence: list[IdentityEvidence]) -> str:
    """Produce XML-tagged text like NVIDIA gliner-PII output.

    Example output:
        <first_name>Jordan</first_name> <last_name>Wells</last_name>
    """
    # Sort evidence by start position, reversed for safe insertion
    sorted_ev = sorted(evidence, key=lambda e: e.start, reverse=True)
    result = text
    for ev in sorted_ev:
        tag = ev.label
        result = result[:ev.start] + f"<{tag}>{ev.text}</{tag}>" + result[ev.end:]
    return result


# ═══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════════════════════

def _overlaps_set(seen: set[tuple[int, int]], span: tuple[int, int]) -> bool:
    return any(span[0] < s[1] and span[1] > s[0] for s in seen)
