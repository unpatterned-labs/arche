# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""African name detection via the bundled name lexicon.

Public surface per the 2026-05-22 detection-scope expansion::

    from arche.detect.names import detect_names

    detections = detect_names(
        "Met Adesola Okonkwo and Fatima Abdullahi today."
    )
    # → [Detection(category='PII-1-NAME', text='Adesola', ...),
    #    Detection(category='PII-1-NAME', text='Fatima', ...)]

Cross-cutting (not country-specific). Public module name per the
v0.2.0a2 convention (matches ``arche.detect.ip``, ``arche.detect.digital_id``).

Returns canonical :class:`~arche.workflow._primitive.Detection` objects
with ``category="PII-1-NAME"``. The Pipeline routing wires this into
the default detector set for every jurisdiction so v0.1's "African
names just work out of box" experience is restored.

Detection rules:

-   Lexicon-backed exact-match (case-insensitive) against the 114-group
    African name equivalence dataset (or 20-group bundled starter when
    the YAML dataset is unavailable).
-   Word-boundary anchored — ``mark`` does NOT match inside ``marker``.
-   Longest-match wins for overlapping terms.
-   Default confidence: 0.7 (the "name appears in our lexicon" floor;
    context-aware adjustments are a v0.2.0a2-cherry-pick Lane A9
    follow-up).

Limitations:

-   Western and Eastern names rely on ``arche-core[detect]`` GLiNER2-PII
    for multilingual NER. See the cookbook at
    ``docs-site/docs/cookbooks/web-to-detection.md`` and
    ``notebooks/cookbook-gliner-ner.ipynb`` for the upgrade path.
-   Common-word collisions (e.g. "Mark" the verb vs. the name) ship at
    confidence 0.7 in v0.2.0a2; the context-aware confidence dial lands
    in a follow-up commit.

The full lexicon-load + regex-compile happens on the FIRST call to
:func:`detect_names`. ``import arche.detect.names`` itself is cheap —
no I/O or heavy work at module load time, preserving the PRD
NFR-PERF-1 <1s cold-import budget.
"""

from __future__ import annotations

import re
from threading import Lock

from arche.detect._base import _compile_lexicon, _lexicon_detect
from arche.workflow._primitive import Detection

# Lazy-init state. Compiled on first detect_names() call.
_PATTERN: re.Pattern[str] | None = None
_PATTERN_LOCK = Lock()


#: Minimum length for a lexicon term to be searchable. Two-character
#: "names" like "Ba" (a Senegalese / Fulani surname) collide with
#: function words in Hausa / Swahili / Pidgin too often to be useful
#: without context-aware filtering. Pure-rule lexicon detection caps
#: at 3 chars; context-aware confidence (Lane A9 cherry-pick) will
#: surface them with lowered confidence in a follow-up commit.
_MIN_LEXICON_TERM_LEN = 3


def _build_pattern() -> re.Pattern[str]:
    """Compile the lexicon-backed name pattern.

    Calls into the existing ``arche.detect._names.lexicon._load_all_groups``
    which returns the full 114-group dataset when available, else the
    20-group bundled starter set. Each group is a list of canonical +
    variants; we flatten ALL of them into the searchable lexicon.

    Terms shorter than :data:`_MIN_LEXICON_TERM_LEN` are filtered out
    (see the constant's docstring for rationale).
    """
    from arche.detect._names.lexicon import _load_all_groups

    groups = _load_all_groups()
    # Flatten + length-filter: each group contributes all its variants
    # that pass the minimum-length gate. ~110-440 terms total depending
    # on dataset.
    terms = [
        variant
        for group in groups
        for variant in group
        if len(variant) >= _MIN_LEXICON_TERM_LEN
    ]
    return _compile_lexicon(terms, case_insensitive=True)


def _get_pattern() -> re.Pattern[str]:
    """Lazy-compile the lexicon pattern. Thread-safe via double-checked lock."""
    global _PATTERN
    if _PATTERN is None:
        with _PATTERN_LOCK:
            if _PATTERN is None:
                _PATTERN = _build_pattern()
    return _PATTERN


def detect_names(text: str, *, confidence: float = 0.7) -> list[Detection]:
    """Find African names in ``text`` via the bundled lexicon.

    Args:
        text: Free-form input.
        confidence: Base confidence for matches. Default 0.7. The
            "matched our lexicon, but common-word collision is possible"
            floor. The context-aware confidence cherry-pick (v0.2.0a2
            Lane A9) refines this per-match.

    Returns:
        List of :class:`Detection` objects with category ``PII-1-NAME``.
        Ordered by character offset.
    """
    pattern = _get_pattern()
    return _lexicon_detect(
        text,
        pattern,
        category="PII-1-NAME",
        detector_name="rule:names_lexicon",
        identity_class="inferred",
        confidence=confidence,
    )


__all__ = ["detect_names"]
