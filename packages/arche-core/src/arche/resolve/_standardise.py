# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0
"""Token standardisation before names are compared: the ``standardise`` comparator key.

``Marks & Spencer PLC`` and ``MARKS AND SPENCER P.L.C.`` are one company written two
ways. Without this they shared too few tokens to match (0.686, review): ``&`` is not
``and``, and ``P.L.C.`` was not read as a legal form at all. The table in
``_data/name_standards.yaml`` says which spellings are one token; this applies it.

Opt-in per comparator, like ``strip_type``, because it changes what agreement means and
therefore every decision a pack has published. The table is content-addressed into the
run's pins (``name_standards``).
"""

from __future__ import annotations

import re
from functools import cache, lru_cache
from pathlib import Path
from typing import Any

_TABLE = Path(__file__).resolve().parent / "_data" / "name_standards.yaml"
# Single letters each followed by a full stop, two or more, not followed by a letter.
# "P.L.C." joins to "PLC" because that is a legal form; "O.A." becomes "O A", which is how
# "O A Taylor" is written and how the tokens were always read. "P.J.MARTINELLI" is left
# alone, because a letter follows.
_DOTTED = re.compile(r"(?<![A-Za-z])((?:[A-Za-z]\.){2,})(?![A-Za-z])")


@cache
def _load() -> dict[str, Any]:
    import yaml

    with _TABLE.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


@cache
def _compiled(domain: str) -> tuple[tuple[re.Pattern[str], str], ...]:
    spec = _load().get(domain)
    if spec is None:
        raise ValueError(f"unknown standardise domain {domain!r}; known: {sorted(_load())}")
    rules: list[tuple[re.Pattern[str], str]] = []
    for sym, word in (spec.get("symbols") or {}).items():
        # Only between two words of two letters or more: "Mine & Yours" is "Mine and
        # Yours", but "M & S" and "C & P" are initials, and stay as they were read.
        rules.append((re.compile(rf"(?<=\w\w\s){re.escape(sym)}(?=\s\w\w)"), f"{word}"))
    for short, long in (spec.get("words") or {}).items():
        # A hyphen or apostrophe joins words: "Co-operative" and "Co-op" are not "Co".
        word = rf"(?<![\w'\-]){re.escape(short)}\.?(?![\w'\-])"
        rules.append((re.compile(word, re.IGNORECASE), long))
    return tuple(rules)


@cache
def _forms() -> frozenset[str]:
    """Legal forms and type words, so a dotted run that spells one is joined."""
    from arche.resolve._matcher import load_type_vocab

    return frozenset(k.replace(" ", "") for k in load_type_vocab("organization"))


def _dotted(m: re.Match[str]) -> str:
    letters = m.group(1).replace(".", "")
    return letters if letters.lower() in _forms() else " ".join(letters)


@lru_cache(maxsize=65536)
def standardise(text: str, domain: str = "organisation") -> str:
    """``text`` with the domain's standard forms applied. Pure; casing elsewhere is kept."""
    if not text:
        return text
    out = text
    if (_load().get(domain) or {}).get("join_dotted_initials"):
        out = _DOTTED.sub(_dotted, out)
    for pattern, repl in _compiled(domain):
        out = pattern.sub(repl, out)
    return out


def pin(domain: str = "organisation") -> str:
    """Content address of one domain's table, so a receipt names it."""
    from arche.ids import content_hash

    _compiled(domain)
    return "name_standards@" + content_hash(_load()[domain], prefix="ns").split(":")[-1]
