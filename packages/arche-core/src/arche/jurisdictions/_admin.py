# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Shared pieces of every jurisdiction's ``admin_path``.

An admin path is ``{"admin1": ..., "admin2": ..., ...}``, coarse to fine, the
shape `compare_containment` reads. Each country decides what its levels are
(Nigeria: state, LGA, ward; South Africa: province, district, local
municipality, ward); this module holds what they share: folding a name into a
comparison key and dropping the words that only say what kind of unit it is.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any


def fold(text: Any) -> str:
    """arche's text normaliser (case, diacritics, invisible characters), then
    punctuation to spaces: ``Akwa-Ibom`` and ``Akwa Ibom`` are one key."""
    from arche.resolve._matcher import _normalise_text

    folded = re.sub(r"[^a-z0-9]+", " ", _normalise_text(str(text or "")))
    return re.sub(r"\s+", " ", folded).strip()


def strip_suffix(text: str, suffixes: Iterable[str]) -> str:
    """Drop one trailing unit word (`` lga``, `` local municipality``). Longest
    first, so `` local government area`` wins over `` area``; never strips a
    name down to nothing."""
    for suffix in sorted(suffixes, key=len, reverse=True):
        if text.endswith(suffix) and len(text) > len(suffix):
            return text[: -len(suffix)].strip()
    return text


def build(levels: Iterable[tuple[str, str]]) -> dict[str, str]:
    """``{level: value}`` keeping only levels with a value: a missing level is
    missing evidence, never a disagreement."""
    return {level: value for level, value in levels if value}
