# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Resolve layer - link mentions across documents to canonical entities.

Ships a fuzzy/Fellegi-Sunter probabilistic record
linkage implementation in ``arche.resolve.classical`` suitable for
in-memory operation up to ~100K records. African-context comparator
functions handle Yoruba/Hausa/Swahili name variants, patronymics, and
transliteration differences.

Public API::

    from arche.resolve import resolve_entities, resolve_identity_records
    from arche.resolve import ResolvedEntity

For production-scale entity resolution (millions of records), install
``arche-core[resolve]`` which pulls Splink + DuckDB. With the extra
installed, ``resolve_entities(..., use_splink=True)`` auto-engages a
Splink-backed Fellegi-Sunter pipeline at sizes >=10 entities and falls
back to the fuzzy implementation on import error.

A first-class ``SplinkResolver`` user class (CSV-in / cluster-out)
arrives in v0.3 alongside the ``arche-core[graph]`` Kuzu backend and the
``StorageBackend`` Protocol. See ``docs-site/docs/rfcs/0001-v0.3-storage.md``.

----

v0.1 backward compat: this module is also CALLABLE. The v0.1 API exposed
``from arche import resolve`` as a function (defined in
``workflow.pipeline``). To keep that surface working through the v0.2
migration without forcing every test and downstream caller to update
imports, the ``arche.resolve`` module is made callable - calling it
forwards to ``arche.workflow.pipeline.resolve``. A ``DeprecationWarning``
is emitted on call.

This dual nature (package + callable) is intentional and temporary. In v0.3
the callable trick is removed and the function relocates to a clearly-named
home (likely ``arche.workflow.Pipeline.process``).
"""

from __future__ import annotations

import sys as _sys
import warnings as _warnings
from types import ModuleType as _ModuleType

from arche.resolve._tokenfreq import TokenFrequencyTable  # noqa: E402,F401
from arche.resolve.artists import artist_aliases  # noqa: E402,F401

# Re-export the v0.2 classical resolver surface so existing
# ``from arche.resolve import X`` calls keep working.
# Private symbols used internally by pipeline.py and other modules.
from arche.resolve.classical import (  # noqa: E402,F401  # noqa: E402,F401
    ResolvedEntity,
    _build_resolved,
    _single_entity_to_resolved,
    resolve_entities,
    resolve_identity_records,
)

# Place/entity crosswalk engine (list-to-list reconciliation) and the
# term-frequency table its ``tftoken`` comparator + reranker consume.
from arche.resolve.reconcile import reconcile  # noqa: E402,F401

# ---------------------------------------------------------------------------
#
# Two entry points by USE-SHAPE, sharing primitives but deliberately distinct
# combination laws:
#   pairwise(a, b)            -> "are these two the same?" (Fellegi-Sunter +
#                                gate, signable CoReferenceDecision)
#   crosswalk(list_a, list_b) -> "link two lists at scale" (weighted-mean +
#                                gate + blocking, id-only candidates)
# The scores are NOT comparable across the two (different math, on purpose).
# `coref_*` and `reconcile` remain importable, but the facade is the documented
# surface. (`compare_lists` on main: wrapper-or-deprecate at merge)
# ---------------------------------------------------------------------------

# Canned comparator specs per entity type — the "entity pack" axis. A pack is
# CONFIG over the same engine, never a fork. Records use these field names;
# bring your own comparators= for a different schema.
ENTITY_PACKS: dict[str, list[dict]] = {
    "person": [
        {"field": "name", "kind": "name", "weight": 2.0},
        {"field": "name", "kind": "tftoken", "weight": 2.0},
        {"field": "national_id", "kind": "id", "weight": 3.0},
        {"field": "phone", "kind": "phone", "weight": 1.5},
        {"field": "email", "kind": "email", "weight": 1.5},
        {"field": "address", "kind": "address", "weight": 1.0},
    ],
    # Places are calibrated as places, not people: `placename` never consults
    # the person equivalence lexicon (Fatima Hospital vs Fatouma Hospital are
    # plausibly two facilities named after two different people); `type` scores
    # the facility tier separately 
    "place": [
        {"field": "name", "kind": "placename", "weight": 2.0},
        {"field": "name", "kind": "tftoken", "weight": 2.0},
        {"field": "name", "kind": "type", "domain": "health_facility", "weight": 0.0},
        {"kind": "geo", "lat": "lat", "lon": "lon", "weight": 1.0, "decay_km": 3.0},
        {"kind": "containment", "field": "admin_path", "weight": 1.0},
        {"field": "address", "kind": "address", "weight": 1.0},
    ],
    # Artists: MBID/ISNI are the registry identifiers (a national-ID analogue);
    # alias-expand the catalog with resolve.artist_aliases() for recall.
    "artist": [
        {"field": "name", "kind": "name", "weight": 2.0},
        {"field": "name", "kind": "tftoken", "weight": 2.0},
        {"field": "mbid", "kind": "id", "weight": 3.0},
        {"field": "isni", "kind": "id", "weight": 2.0},
    ],
    # "product": roadmap — numeric-tolerance + colour-set comparators.
}

# Packs whose tftoken comparator defaults to a SHIPPED population table rather
# than self-calibration (small artist catalogs mislead a self-calibrated table
# — the toy-corpus trap the place tutorials document).
_PACK_TF_DOMAIN: dict[str, str] = {"artist": "artist"}



def pairwise(a, b, *, entity: str = "person", **kwargs):
    """Decide whether two records/documents/results refer to the same entity.

    Dispatches on input shape:

    * two Pipeline ``Result``s -> ``coref_from_pipeline`` (the compliance-aware
      path: statute citations travel; drop-actioned values are restricted);
    * two canonical ``Reference``s -> ``coref_references`` (the deterministic,
      reproducible core);
    * two strings -> ``coref_documents`` (extract-then-resolve).

    Returns a signable ``CoReferenceDecision``. Currently ``entity="person"``
    only — pairwise place/product decisions are roadmap.
    """
    if entity != "person":
        raise NotImplementedError(
            f"pairwise entity={entity!r} is not available yet; person only. "
            "Use crosswalk(...) for place lists."
        )
    from arche.resolve.coreference import (
        coref_documents,
        coref_from_pipeline,
        coref_references,
    )

    if hasattr(a, "detections") and hasattr(b, "detections"):
        return coref_from_pipeline(a, b, **kwargs)
    if hasattr(a, "attributes") and hasattr(b, "attributes"):
        return coref_references(a, b, **kwargs)
    if isinstance(a, str) and isinstance(b, str):
        return coref_documents(a, b, **kwargs)
    raise TypeError(
        f"pairwise expects two Results, two References, or two strings; "
        f"got {type(a).__name__} and {type(b).__name__}"
    )


def crosswalk(list_a, list_b, *, entity: str | None = None,
              comparators: list[dict] | None = None, tf=None, decl=None,
              **kwargs):
    """Link/dedupe two record lists at scale (blocking + gate + evidence).

    Pass ``entity=`` to use a canned comparator pack (:data:`ENTITY_PACKS`),
    or bring explicit ``comparators=`` for your own schema. When the pack uses
    a ``tftoken`` comparator and no ``tf`` is given: packs with a shipped
    population table (``artist``) load it; other packs self-calibrate a table
    over both lists' text. Pass ``tf="default"`` (person table) or a domain
    name (``tf="artist"``) to choose explicitly. Delegates to
    :func:`~arche.resolve.reconcile.reconcile`.

    Every returned edge carries a ``decision_id`` hashed over the evidence and
    the run's ``pins`` (which include the declaration pin when ``decl=`` is
    used, and the tf table's provenance); sign edges with
    :func:`arche.resolve.reconcile.sign_edges`.
    """
    extra_pins = dict(kwargs.pop("extra_pins", None) or {})
    tf_provenance: str | None = None
    if isinstance(tf, str):
        tf_provenance = f"shipped:{'person' if tf == 'default' else tf}"
    elif tf is not None:
        tf_provenance = "provided"
    if decl is not None:
        # A declaration IS a user-defined entity pack: generated comparators,
        # its own id_field and tf defaults. Explicit args still win.
        if entity is not None:
            raise ValueError("pass either decl= or entity=, not both")
        if comparators is None:
            comparators = decl.comparators()
        kwargs.setdefault("id_field", decl.id_field)
        extra_pins.setdefault("declaration", decl.pin())
        if tf is None and decl.tf is not None:
            tf = decl.tf
            tf_provenance = f"shipped:{'person' if tf == 'default' else tf}" \
                if isinstance(tf, str) else "provided"
    if comparators is None:
        if entity is None:
            raise ValueError(
                f"pass entity= (one of {sorted(ENTITY_PACKS)}), decl=, or "
                "explicit comparators="
            )
        try:
            comparators = ENTITY_PACKS[entity]
        except KeyError:
            raise ValueError(
                f"unknown entity pack {entity!r}; available: {sorted(ENTITY_PACKS)}"
            ) from None
    if tf is None and any(c.get("kind") == "tftoken" for c in comparators):
        domain = _PACK_TF_DOMAIN.get(entity or "")
        if domain is not None:
            # This pack's population is not the lists being linked (a small
            # artist catalog miscalibrates itself) — use the shipped table,
            # falling back loudly if the data asset is absent.
            try:
                tf = TokenFrequencyTable.default(domain=domain)
                tf_provenance = f"shipped:{domain}"
            except FileNotFoundError as exc:
                _warnings.warn(
                    f"shipped {domain!r} frequency table unavailable ({exc}); "
                    "self-calibrating over the two lists instead",
                    RuntimeWarning,
                    stacklevel=2,
                )
        if tf is None:
            # Self-calibrate distinctiveness over the lists being linked — the
            # designed reconcile path for a corpus-specific vocabulary.
            fields = {c["field"] for c in comparators if c.get("kind") == "tftoken"}
            texts = [str(r.get(f, "")) for r in [*list_a, *list_b] for f in fields]
            tf = TokenFrequencyTable.from_corpus(t for t in texts if t)
            tf_provenance = "self-calibrated"
    if tf_provenance is not None:
        extra_pins.setdefault("tf", tf_provenance)
    return reconcile(list_a, list_b, comparators, tf=tf,
                     extra_pins=extra_pins or None, **kwargs)


class _CallableResolveModule(_ModuleType):
    """``arche.resolve`` is both a package (for v0.2 PRD §6.1 imports) and
    callable (for v0.1 ``from arche import resolve`` backward compat).

    Removed in v0.3 once the v0.1 ``resolve()`` function is renamed.
    """

    def __call__(self, *args, **kwargs):  # type: ignore[override]
        _warnings.warn(
            "Calling arche.resolve() as a function is the v0.1 API. "
            "Use arche.Pipeline(...).process(text) or arche.workflow.RedactionWorkflow "
            "for the v0.2 composition pattern. This callable shim is removed in v0.3.",
            DeprecationWarning,
            stacklevel=2,
        )
        from arche.workflow.pipeline import resolve as _resolve_fn

        return _resolve_fn(*args, **kwargs)


_sys.modules[__name__].__class__ = _CallableResolveModule