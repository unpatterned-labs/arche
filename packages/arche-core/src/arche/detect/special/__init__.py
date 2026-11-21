# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Special-category content (health, religion, race/ethnicity, sexual
orientation, political affiliation, trade-union membership), cue-anchored and
precision first. See :mod:`arche.detect.special.rules` for every rule."""

from __future__ import annotations

from arche.detect.special.rules import (
    HEALTH,
    POLITICAL,
    RACE,
    RELIGION,
    SEXUAL_ORIENTATION,
    TRADE_UNION,
    detect_special_categories,
)

__all__ = [
    "HEALTH", "POLITICAL", "RACE", "RELIGION", "SEXUAL_ORIENTATION", "TRADE_UNION",
    "detect_special_categories",
]
