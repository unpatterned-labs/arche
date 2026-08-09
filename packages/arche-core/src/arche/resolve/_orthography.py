# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Orthographic keys for name tokens.

The problem this solves. arche's gate will not merge two references until they
share a *distinctive* token. That is what stops "Fatima Hospital" and "Fatouma
Hospital" being fused on the strength of a person-name equivalence. But it also
means a settlement written ``Mai Tsidau`` in one registry and ``Maitsidau`` in
another shares no token at all, so a true match is dropped before scoring — and
a dropped pair is unrecoverable.

Measured on Kano State (GRID3 x OpenStreetMap), that class of variation
accounted for several of the pairs a language model correctly merged and arche
refused. This module closes the gap without loosening the gate: the tokens
still have to agree, they are just compared through an orthographic key that
knows two spellings are one word.

The rules live in ``_data/orthography.yaml`` as inspectable data, on the same
principle as the name lexicon and the type-token vocabularies — adding a
language or correcting a rule is a data edit, not a code change.

Deliberately conservative. Mechanical, documented regularities go in
``rewrites``; everything else is an explicit ``equivalents`` list a native
speaker can correct. Where we have seen variation but cannot state a rule for
it honestly, the pack records it under ``known_gaps`` rather than guessing.
"""

from __future__ import annotations

import re
from functools import lru_cache
from typing import Any

__all__ = ["OrthographyPack", "load_orthography", "orthographic_key"]


class OrthographyPack:
    """Compiled orthographic rules for one language."""

    __slots__ = ("language", "collapse_boundaries", "_rewrites", "_canon", "version")

    def __init__(self, language: str, spec: dict[str, Any], version: str) -> None:
        self.language = language
        self.version = version
        self.collapse_boundaries = bool(spec.get("collapse_word_boundaries", False))

        self._rewrites: list[tuple[re.Pattern[str], str]] = []
        for rule in spec.get("rewrites") or ():
            try:
                self._rewrites.append(
                    (re.compile(rule["pattern"]), rule.get("replace", ""))
                )
            except (KeyError, re.error):
                # A malformed rule must not take the whole pack down; skipping
                # it degrades recall, whereas raising would break resolution
                # for everyone using the pack.
                continue

        # {variant: canonical} — the first member of each group is canonical.
        self._canon: dict[str, str] = {}
        for group in spec.get("equivalents") or ():
            members = [str(m).strip().lower() for m in group if str(m).strip()]
            if len(members) < 2:
                continue
            canonical = members[0]
            for member in members:
                self._canon[member] = canonical

    def key(self, token: str) -> str:
        """The orthographic key for a single token."""
        t = (token or "").strip().lower()
        if not t:
            return ""
        t = self._canon.get(t, t)
        for pattern, replacement in self._rewrites:
            t = pattern.sub(replacement, t)
        return t

    def keys(self, tokens: list[str] | tuple[str, ...]) -> set[str]:
        """Keys for an ORDERED token sequence, plus adjacent joined pairs.

        Order matters. ``"Mai Tsidau Health Post"`` and ``"Maitsidau Health
        Post"`` are the same name, and the way to see it is to join *adjacent*
        tokens: ``mai`` + ``tsidau`` gives ``maitsidau``, which the other name
        already has as a single token.

        Joining the whole name instead would fail on exactly these pairs,
        because the type tokens differ (``centre`` vs ``center``) and would
        poison the concatenation. Adjacent pairs keep the distinctive part
        intact and leave the type tokens to be handled where they belong, by
        the type-token vocabulary.

        Joined forms are added *alongside* the single-token keys, never
        instead of them, so a partial overlap still scores.

        Returns ``{key: source tokens}``. The provenance is not decoration: a
        joined key like ``healthpost`` does not appear in any frequency table,
        so scoring it directly would treat it as an unseen — therefore rare,
        therefore distinctive — token. It would then clear the gate for *every*
        pair of facilities whose names both end "Health Post". Callers must
        score a joined key through the tokens that produced it.
        """
        seq = [t for t in tokens if t]
        out: dict[str, set[str]] = {}
        for token in seq:
            key = self.key(token)
            if key:
                out.setdefault(key, set()).add(token)
        if self.collapse_boundaries:
            for left, right in zip(seq, seq[1:]):
                joined = self.key(f"{left}{right}")
                if joined:
                    out.setdefault(joined, set()).update((left, right))
        return out


@lru_cache(maxsize=1)
def _load_raw() -> dict[str, Any]:
    try:
        from importlib.resources import files

        import yaml

        path = files("arche.resolve").joinpath("_data", "orthography.yaml")
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:
        # No pack, malformed pack, or no yaml: orthographic keying becomes a
        # no-op and the gate behaves exactly as it did before this module
        # existed. Failing open here is right — the pack adds recall, and its
        # absence must never make resolution worse than not having it.
        return {}


@lru_cache(maxsize=8)
def load_orthography(language: str = "hausa") -> OrthographyPack | None:
    """Load a compiled pack, or ``None`` when the language has no pack."""
    raw = _load_raw()
    spec = raw.get(language)
    if not isinstance(spec, dict):
        return None
    return OrthographyPack(language, spec, str(raw.get("version", "unknown")))


def orthographic_key(token: str, language: str = "hausa") -> str:
    """The orthographic key for one token, or the token itself if no pack."""
    pack = load_orthography(language)
    return pack.key(token) if pack else (token or "").strip().lower()
