# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Shared types and helpers for the detection layer.

This module exists to break the circular dependency between per-country
detector modules (``detect.ng.ids``, etc.) and the multi-country
orchestrator (``detect._africa.ids``).

Both sides import ``NationalID``, ``_luhn_check``, and ``_always_valid``
from here. Neither imports from the other through this module, so there
is no cycle.

Lexicon-based detectors (``arche.detect.names``, ``arche.detect.locations``)
share :func:`_lexicon_detect` defined below. The shared helper compiles
lexicon strings into a single alternation regex once, then runs
``finditer`` to emit canonical :class:`~arche.workflow._primitive.Detection`
objects. Per the 2026-05-22 eng review §2 issue 7 locked decision.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from arche.workflow._primitive import Detection


@dataclass
class NationalID:
    """A national ID detected in text.

    Attributes
    ----------
    text:
        The literal matched text.
    country:
        ISO 3166-1 alpha-2 country code (e.g. ``"NG"``, ``"ZA"``).
    id_type:
        Short identifier for the ID scheme (e.g. ``"NIN"``, ``"BVN"``,
        ``"GHANA_CARD"``).
    confidence:
        Confidence in [0, 1].  1.0 means the pattern matched AND the
        check-digit / structural validation passed.
    start:
        Character offset of the first character of the match.
    end:
        Character offset one past the last character of the match.
    metadata:
        Optional dict with extracted info (e.g. date of birth, gender).
    """

    text: str
    country: str
    id_type: str
    confidence: float
    start: int
    end: int
    metadata: dict = field(default_factory=dict)


def _luhn_check(digits: str) -> bool:
    """Validate a digit string using the Luhn algorithm (mod 10)."""
    total = 0
    for i, ch in enumerate(reversed(digits)):
        n = int(ch)
        if i % 2 == 1:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return total % 10 == 0


def _always_valid(text: str) -> tuple[bool, dict]:
    """Fallback validator that only checks the regex matched."""
    return True, {}


def _compile_lexicon(terms: list[str], *, case_insensitive: bool = True) -> re.Pattern[str]:
    """Compile a list of lexicon terms into a single word-boundary alternation regex.

    Sorted by length descending so the longest match wins for overlapping
    terms (e.g. "Cape Town" matches before "Cape"). Word boundaries
    (``\\b``) prevent partial-word matches.

    Args:
        terms: List of literal strings to match (e.g. names or city names).
            Must be non-empty.
        case_insensitive: If True (default), compiled with ``re.IGNORECASE``.

    Returns:
        A compiled :class:`re.Pattern`.

    Raises:
        ValueError: If ``terms`` is empty.
    """
    if not terms:
        raise ValueError("lexicon term list must be non-empty")
    # Sort longest-first so 'Cape Town' wins over 'Cape' on overlap
    sorted_terms = sorted(set(terms), key=len, reverse=True)
    escaped = [re.escape(t) for t in sorted_terms]
    pattern = r"\b(?:" + "|".join(escaped) + r")\b"
    flags = re.IGNORECASE if case_insensitive else 0
    return re.compile(pattern, flags)


def _lexicon_detect(
    text: str,
    pattern: re.Pattern[str],
    *,
    category: str,
    detector_name: str,
    identity_class: str = "inferred",
    confidence: float = 0.9,
    metadata_factory: Callable[[re.Match[str]], dict[str, Any]] | None = None,
) -> list[Detection]:
    """Find lexicon matches in ``text`` and emit canonical Detection objects.

    Shared by ``arche.detect.names`` and ``arche.detect.locations`` (and
    any future lexicon-based detector). Per the 2026-05-22 eng review
    §2 issue 7 DRY extraction.

    Args:
        text: Free-form input to scan.
        pattern: Pre-compiled regex from :func:`_compile_lexicon`.
        category: Pan-African PII Taxonomy label (e.g. ``"PII-1-NAME"``).
        detector_name: Short detector identifier for ``Detection.detector``
            (e.g. ``"rule:names_lexicon"``).
        identity_class: One of ``"foundational"`` / ``"functional"`` /
            ``"federated"`` / ``"inferred"``. Default ``"inferred"``.
        confidence: Default confidence in [0, 1]. Callers may post-process
            (e.g. ``arche.detect.names`` applies context-aware adjustments).
        metadata_factory: Optional callable that receives the regex Match
            and returns per-detection metadata. When ``None``, metadata
            is the empty dict.

    Returns:
        List of Detection objects ordered by character offset (regex
        ``finditer`` returns matches in document order).
    """
    # Lazy-import to avoid a hard arche.detect._base → arche.workflow
    # dependency at module-import time (the workflow module imports the
    # detector packages via its dispatch loop).
    from arche.workflow._primitive import Detection

    detections: list[Detection] = []
    for match in pattern.finditer(text):
        meta = metadata_factory(match) if metadata_factory else {}
        detections.append(Detection(
            id=f"det:{match.start()}:{match.end()}",
            category=category,
            text=match.group(0),
            start=match.start(),
            end=match.end(),
            confidence=confidence,
            detector=detector_name,
            identity_class=identity_class,
            metadata=meta,
        ))
    return detections
