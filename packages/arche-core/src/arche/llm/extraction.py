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

"""LLM-based entity extraction -- the extraction prompt, JSON parser,
offset repair, and the key function ``extract_with_llm()``.

Design principle: LLM is a **proposer**.  It returns ``list[Entity]``
with ``source="llm"``.  These proposals then flow through the same
``_merge_entities()`` and validator pipeline as GliNER and regex
proposals.  The LLM never bypasses validation.

    LLM proposes  ->  validators check  ->  merge with GliNER + regex
"""

from __future__ import annotations

import json
import logging
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..extract import Entity
    from . import LLMConfig

_log = logging.getLogger("arche.llm")


# ═══════════════════════════════════════════════════════════════════════════════
# EXTRACTION PROMPT
# ═══════════════════════════════════════════════════════════════════════════════

SYSTEM_PROMPT = """\
You are an identity intelligence extraction engine. Your job is to extract
identity-related entities from text and return them as structured JSON.

You MUST return a JSON object with a single key "entities" containing an array.
Each entity has these fields:
- "text": the exact substring from the input (verbatim, preserve original spelling)
- "entity_type": one of the entity types listed below
- "confidence": float 0.0-1.0 (your certainty)
- "start": character offset where the entity begins in the input
- "end": character offset where the entity ends in the input

ENTITY TYPES:
  PERSON, ORGANIZATION, LOCATION, DATE, PHONE, EMAIL, NATIONAL_ID,
  MONEY, DOCUMENT, ISBN

IMPORTANT RULES:
1. Extract the EXACT text from the input. Do not paraphrase or correct spelling.
2. National IDs include: Nigerian NIN (11 digits), BVN (11 digits starting with 22),
   Ghana Card (GHA-XXXXXXXXX-X), Kenya ID (8 digits), South African ID (13 digits).
3. Phone numbers: include country code if present. Nigerian numbers start with +234 or 0.
4. Person names: African names may include day-names (Kwame, Kofi), patronymics,
   or clan names. Extract the full name span as PERSON.
5. If the same person is referred to multiple ways ("the Buyer", "Ms. Okafor"),
   extract each mention separately.
6. Return ONLY entities you are confident about. Omit rather than guess.
7. Character offsets must be exact. Count carefully from position 0.

Return ONLY the JSON object. No markdown, no explanation outside the JSON.\
"""


# ═══════════════════════════════════════════════════════════════════════════════
# VALID ENTITY TYPES (maps LLM output to arche taxonomy)
# ═══════════════════════════════════════════════════════════════════════════════

_LLM_TYPE_MAP: dict[str, str] = {
    "person": "PERSON",
    "organization": "ORGANIZATION",
    "location": "LOCATION",
    "date": "DATE",
    "phone": "PHONE",
    "phone_number": "PHONE",
    "email": "EMAIL",
    "national_id": "NATIONAL_ID",
    "money": "MONEY",
    "document": "DOCUMENT",
    "isbn": "ISBN",
    # Also accept uppercase passthrough
    "PERSON": "PERSON",
    "ORGANIZATION": "ORGANIZATION",
    "LOCATION": "LOCATION",
    "DATE": "DATE",
    "PHONE": "PHONE",
    "EMAIL": "EMAIL",
    "NATIONAL_ID": "NATIONAL_ID",
    "MONEY": "MONEY",
    "DOCUMENT": "DOCUMENT",
    "ISBN": "ISBN",
}


# ═══════════════════════════════════════════════════════════════════════════════
# PUBLIC API
# ═══════════════════════════════════════════════════════════════════════════════


def extract_with_llm(
    text: str,
    config: LLMConfig,
) -> list[Entity]:
    """Extract entities from *text* using an LLM as a proposer.

    The returned entities have ``source="llm"`` and go through the same
    ``_merge_entities()`` and validator pipeline as GliNER and regex
    entities.  LLM-proposed structured types (NIN, BVN, phone, ISBN)
    are validated by the existing deterministic validators downstream.

    Parameters
    ----------
    text:
        Free-form input text to scan.
    config:
        LLM provider configuration.

    Returns
    -------
    list[Entity]
        Entities with ``source="llm"``, sorted by position in the text.

    Raises
    ------
    RuntimeError
        If the LLM API call fails (network error, missing API key, etc.).
    """
    from .providers import complete

    messages = _build_extraction_messages(text)

    try:
        raw_response = complete(config, messages)
    except Exception as e:
        _log.error("LLM extraction failed: %s", e)
        raise RuntimeError(
            f"LLM extraction failed ({config.provider}/{config.model}): {e}. "
            "Check your API key and network connection."
        ) from e

    return _parse_llm_response(raw_response, text)


# ═══════════════════════════════════════════════════════════════════════════════
# INTERNALS
# ═══════════════════════════════════════════════════════════════════════════════


def _build_extraction_messages(text: str) -> list[dict[str, str]]:
    """Build the chat messages for identity extraction."""
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": text},
    ]


def _parse_llm_response(raw_response: str, text: str) -> list[Entity]:
    """Parse the LLM JSON response into Entity objects.

    Handles:
    - Valid JSON with ``{"entities": [...]}``
    - JSON wrapped in markdown code blocks
    - Malformed JSON (returns empty list)
    - Invalid entity types (dropped with warning)
    - Wrong offsets (repaired via ``_repair_offsets``)
    - Entity text not found in input (dropped)

    Parameters
    ----------
    raw_response:
        Raw string returned by the LLM.
    text:
        Original input text (used for offset repair).

    Returns
    -------
    list[Entity]
        Valid entities sorted by position.
    """
    from ..extract import Entity

    # Parse JSON response
    try:
        data = json.loads(raw_response)
    except json.JSONDecodeError:
        # Try to extract JSON from markdown code blocks
        match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw_response, re.DOTALL)
        if match:
            try:
                data = json.loads(match.group(1))
            except json.JSONDecodeError:
                _log.warning("LLM returned unparseable JSON in code block")
                return []
        else:
            _log.warning("LLM returned non-JSON response, returning empty results")
            return []

    if not isinstance(data, dict):
        _log.warning("LLM response is not a JSON object, returning empty results")
        return []

    entities_raw = data.get("entities", [])
    if not isinstance(entities_raw, list):
        _log.warning("LLM 'entities' field is not a list, returning empty results")
        return []

    entities: list[Entity] = []
    for ent in entities_raw:
        if not isinstance(ent, dict):
            continue

        # Resolve entity type
        raw_type = str(ent.get("entity_type", ent.get("label", ent.get("type", "")))).strip()
        entity_type = _LLM_TYPE_MAP.get(raw_type, _LLM_TYPE_MAP.get(raw_type.lower()))
        if entity_type is None:
            _log.debug("Dropping entity with unrecognised type: %s", raw_type)
            continue

        ent_text = str(ent.get("text", "")).strip()
        if not ent_text:
            continue

        # Validate or repair character offsets
        claimed_start = ent.get("start")
        claimed_end = ent.get("end")
        start, end = _repair_offsets(text, ent_text, claimed_start, claimed_end)
        if start is None:
            _log.debug("Could not locate entity text %r in input, dropping", ent_text[:50])
            continue

        confidence = _clamp_confidence(ent.get("confidence", 0.70))

        metadata: dict = {"source_provider": "llm"}
        if ent.get("reasoning"):
            metadata["llm_reasoning"] = ent["reasoning"]

        entities.append(Entity(
            text=ent_text,
            entity_type=entity_type,
            confidence=confidence,
            start=start,
            end=end,
            source="llm",
            metadata=metadata,
        ))

    return sorted(entities, key=lambda e: e.start)


def _repair_offsets(
    text: str,
    entity_text: str,
    claimed_start: int | None,
    claimed_end: int | None,
) -> tuple[int | None, int | None]:
    """Validate LLM-provided offsets and repair if wrong.

    LLMs frequently get character offsets wrong.  We verify by checking
    whether ``text[start:end]`` matches ``entity_text``.  If not, we
    search for the entity text in the input.

    Returns ``(start, end)`` or ``(None, None)`` if the text cannot be
    found in the input at all.
    """
    # Check claimed offsets first
    if (
        claimed_start is not None
        and claimed_end is not None
        and isinstance(claimed_start, (int, float))
        and isinstance(claimed_end, (int, float))
    ):
        cs = int(claimed_start)
        ce = int(claimed_end)
        if 0 <= cs < ce <= len(text):
            if text[cs:ce] == entity_text:
                return cs, ce

    # Fallback: find the entity text in the input (exact match)
    idx = text.find(entity_text)
    if idx >= 0:
        return idx, idx + len(entity_text)

    # Case-insensitive fallback
    idx = text.lower().find(entity_text.lower())
    if idx >= 0:
        return idx, idx + len(entity_text)

    return None, None


def _clamp_confidence(value: object) -> float:
    """Clamp a confidence value to [0.0, 1.0], defaulting to 0.70."""
    try:
        f = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.70
    return max(0.0, min(1.0, f))
