# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Legal form as a discriminator — the ``legal_form`` comparator kind.

``strip_type`` removes the form before names are compared, which is right:
"Acme Ltd" and "Acme Limited" are one name. But it also meant the form never
took part at all, so "Zenith Bank Plc" and "Zenith Bank Limited" merged at 1.0
and "Northgate Trading Ltd" against "Northgate Trading LLP" — a company
against a partnership — merged at 0.816. This compares the stripped form as its
own field.

Forms come from the ``organization`` vocabulary in ``type_tokens.yaml``
(entries flagged ``legal_form: true``), so stripping and comparing read one
list; how two forms relate comes from ``legal_form_compat.yaml``.
"""

from __future__ import annotations

import re
from functools import cache, lru_cache
from pathlib import Path
from typing import Any

from arche.resolve._matcher import _compiled_vocab, _normalise_text

_HERE = Path(__file__).resolve().parent

#: Canonical form reported for a name carrying only a business-name marker.
BUSINESS_NAME = "BUSINESS_NAME"


@cache
def _load() -> tuple[tuple[tuple[str, str], ...], tuple[Any, ...], dict[str, Any]]:
    """``(form synonym items, compiled marker patterns, compat data)``, once."""
    import yaml

    with open(_HERE / "type_tokens.yaml", encoding="utf-8") as fh:
        vocab = (yaml.safe_load(fh) or {}).get("organization") or {}
    items: dict[str, str] = {}
    for canonical, spec in vocab.items():
        if not (spec or {}).get("legal_form"):
            continue
        for syn in spec.get("synonyms") or []:
            items[str(syn)] = str(canonical)
        items.setdefault(str(canonical).lower(), str(canonical))
    with open(_HERE / "legal_form_compat.yaml", encoding="utf-8") as fh:
        compat = yaml.safe_load(fh) or {}
    # Lookarounds rather than \b: `& sons` starts with a non-word character,
    # where \b would never match after a space.
    markers = tuple(
        re.compile(r"(?<!\w)" + re.escape(_normalise_text(str(m))) + r"(?!\w)")
        for m in sorted(compat.get("business_name_markers") or [], key=len,
                        reverse=True)
    )
    return tuple(items.items()), markers, compat


def pin() -> str:
    """A content address for the tables this module decides with.

    Both inputs are shipped data that change verdicts: the form vocabulary in
    ``type_tokens.yaml`` decides what counts as a legal form, and
    ``legal_form_compat.yaml`` decides what it means when two differ. Measured
    on 2026-10-18, editing the second moved a pair from ``review`` to ``match``
    while the run pins stayed byte-identical. A decision id that does not name
    its inputs claims a reproducibility it does not have.
    """
    from arche.ids import content_hash

    forms, _patterns, compat = _load()
    body = {"forms": [list(pair) for pair in forms], "compat": compat}
    return "legal_form@" + content_hash(body, prefix="lf").split(":")[-1][:16]


@lru_cache(maxsize=65536)
def extract_legal_form(name: str) -> str | None:
    """The legal form a name declares, ``BUSINESS_NAME``, or ``None``.

    Stacked forms resolve to the rightmost, because the form is the suffix:
    "Acme Pty Ltd" is read whole as PTY, and "Acme Ltd SARL" as SARL. Longest
    synonyms are matched
    first and masked, so "Limited Liability Partnership" is one LLP rather
    than an LLP and an LTD. A business-name marker counts only when no legal
    form is present — "Acme Enterprises Ltd" is a company.
    """
    items, markers, _ = _load()
    text = _normalise_text(name)
    best: tuple[int, str] | None = None
    for pattern, canonical, _syn in _compiled_vocab(items):
        for m in pattern.finditer(text):
            if best is None or m.end() > best[0]:
                best = (m.end(), canonical)
        # Mask what matched so a shorter synonym cannot re-match inside it.
        text = pattern.sub(lambda m: " " * len(m.group(0)), text)
    if best is not None:
        return best[1]
    if any(p.search(text) for p in markers):
        return BUSINESS_NAME
    return None


@cache
def _relations() -> dict[frozenset[str], float]:
    _, _, compat = _load()
    out: dict[frozenset[str], float] = {}
    for rel in (compat.get("relations") or {}).values():
        for a, b in rel.get("pairs") or []:
            out[frozenset((str(a), str(b)))] = (None if rel["value"] is None
                                                    else float(rel["value"]))
    return out


def compare_legal_forms(form_a: str | None, form_b: str | None) -> float | None:
    """How two extracted forms relate; ``None`` (neutral) when either is missing or when
    they agree. Legal form refutes; it never supports, because a shared form is shared
    by most of the register."""
    if form_a is None or form_b is None:
        return None
    _, _, compat = _load()
    if form_a == form_b:
        same = compat.get("same")
        return None if same is None else float(same)
    if BUSINESS_NAME in (form_a, form_b):
        return float(compat.get("business_name_vs_form", 0.0))
    rels = _relations()
    pair = frozenset((form_a, form_b))
    if pair in rels:
        return rels[pair]  # None = consistent forms, neutral
    return float(compat.get("default", 0.0))


def compare_legal_form_names(name_a: str, name_b: str) -> float | None:
    """:func:`compare_legal_forms` over two raw names."""
    return compare_legal_forms(extract_legal_form(name_a), extract_legal_form(name_b))
