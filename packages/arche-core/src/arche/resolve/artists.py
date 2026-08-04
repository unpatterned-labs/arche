# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Artist alias equivalences — the recall layer of the artist entity pack.

The artist counterpart of the African name-equivalence lexicon: a stage name,
a legal name, and a catalog alias form are the same artist ("Damini Ogulu" ↔
"Burna Boy" is music's "Diallo" ↔ "Jallow"). Equivalence data buys recall;
the artist frequency table (``TokenFrequencyTable.default(domain="artist")``)
buys precision; the gate keeps merges safe.

Data is loaded from ``datasets/artist_equivalences/*.yaml`` when a repo
checkout is discoverable (same discovery rules as the person lexicon:
``ARCHE_DATASET_DIR`` env var, then cwd/ancestor walk), falling back to the
bundled copy shipped in the wheel.
"""

from __future__ import annotations

import os
from functools import cache
from pathlib import Path

__all__ = ["artist_aliases"]


def _dataset_dir() -> Path | None:
    """Locate ``datasets/artist_equivalences/`` (mirrors the person lexicon)."""
    env_dir = os.environ.get("ARCHE_DATASET_DIR")
    if env_dir:
        p = Path(env_dir) / "artist_equivalences"
        if p.is_dir() and list(p.glob("*.yaml")):
            return p
    cwd = Path.cwd()
    candidates = [cwd / "datasets" / "artist_equivalences",
                  cwd.parent / "datasets" / "artist_equivalences"]
    this_dir = Path(__file__).resolve().parent
    candidates += [
        ancestor / "datasets" / "artist_equivalences"
        for ancestor in (this_dir.parents[4], this_dir.parents[3], this_dir.parents[2])
    ]
    for candidate in candidates:
        if candidate.is_dir() and list(candidate.glob("*.yaml")):
            return candidate
    return None


def _parse_groups(texts: list[str]) -> dict[str, tuple[str, ...]]:
    import yaml

    groups: dict[str, list[str]] = {}
    for text in texts:
        data = yaml.safe_load(text)
        if not data or "groups" not in data:
            continue
        for group in data["groups"]:
            canonical = group.get("canonical", "")
            if not canonical:
                continue
            variants = [v for v in group.get("variants", []) if v]
            groups.setdefault(canonical, []).extend(variants)
    return {c: tuple(dict.fromkeys(v)) for c, v in groups.items()}


@cache
def artist_aliases() -> dict[str, tuple[str, ...]]:
    """``{canonical stage name: (alias forms...)}`` from the datasets, cached.

    Prefers the full ``datasets/artist_equivalences/`` files of a repo
    checkout; falls back to the bundled copy in the wheel. Use it to
    alias-expand a catalog before :func:`arche.resolve.crosswalk`, so legal
    names and catalog variants *count as agreement*::

        rows = [{"id": f"{aid}#{i}", "artist": aid, "name": form}
                for aid, forms in artist_aliases().items()
                for i, form in enumerate((aid, *forms))]
    """
    dataset_dir = _dataset_dir()
    if dataset_dir is not None:
        texts = [p.read_text(encoding="utf-8")
                 for p in sorted(dataset_dir.glob("*.yaml"))]
        return _parse_groups(texts)
    from importlib.resources import files

    bundled = files("arche.resolve").joinpath("_data", "artist_equivalences.yaml")
    return _parse_groups([bundled.read_text(encoding="utf-8")])
