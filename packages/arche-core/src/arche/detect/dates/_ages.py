# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""A person's stated age: ``aged 93``, ``93-year-old``, ``93 y/o``, ``age: 93``.

The span is the number alone, so a policy can write ``aged 90+`` in its place.
Only the phrase makes a number an age; a bare ``93`` is never one, and a
duration (``for 12 years``, ``over 20 yrs``) is not either.
"""

from __future__ import annotations

import re

from arche.workflow._primitive import Detection

_MAX_AGE = 125

#: Cue first: "aged 93", "age 93", "age: 93", "Age - 93".
_CUE_FIRST = re.compile(r"(?i)\b(?:aged|age)\s*[:=-]?\s*(\d{1,3})(?![\d.,/:]\d|\d)")
#: Number first: "93-year-old", "93 years old", "93 years of age", "93 yrs", "93 yo",
#: "93yo", "93 y/o", "93 y.o.".
_NUM_FIRST = re.compile(
    r"(?i)(?<![\w.,/:-])(\d{1,3})(?:"
    r"(?P<old>[\s-]*(?:years?|yrs?)[\s-]*(?:old|of\s+age)\b)"
    r"|(?P<yrs>\s*yrs?\b\.?)"
    r"|(?P<yo>\s*(?:y/o|y\.o\.?|yo)(?![\w/]))"
    r")"
)
#: "for 12 yrs", "over 20 yrs": a span of time, not a person's age. Only checked
#: for the bare "yrs" form; "12 years old" is an age whatever precedes it.
_DURATION = re.compile(
    r"(?i)\b(?:for|over|past|last|in|within|after|than|about|nearly|almost|since|ago"
    r"|spent|served|worked|lived|employed|experience)\s*(?:the\s+)?$"
)


def detect_ages(text: str) -> list[Detection]:
    """Stated ages as ``PII-1-AGE``; ``metadata["over_89"]`` marks those HIPAA
    requires aggregated to "90 or older" (45 CFR 164.514(b)(2)(i)(C))."""
    hits: dict[tuple[int, int], tuple[int, str]] = {}
    for m in _CUE_FIRST.finditer(text):
        hits.setdefault((m.start(1), m.end(1)), (int(m.group(1)), "age N"))
    for m in _NUM_FIRST.finditer(text):
        if m.group("yrs") and _DURATION.search(text[max(0, m.start() - 20):m.start()]):
            continue
        fmt = "N years old" if m.group("old") else ("N yrs" if m.group("yrs") else "N y/o")
        hits.setdefault((m.start(1), m.end(1)), (int(m.group(1)), fmt))
    out: list[Detection] = []
    for (start, end), (age, fmt) in sorted(hits.items()):
        if age > _MAX_AGE:
            continue
        out.append(Detection(
            id=f"det:age:{start}:{end}",
            category="PII-1-AGE",
            text=text[start:end],
            start=start,
            end=end,
            confidence=0.9,
            detector="rule:age",
            identity_class="inferred",
            metadata={"kind": "age", "age": age, "over_89": age > 89, "format": fmt},
        ))
    return out
