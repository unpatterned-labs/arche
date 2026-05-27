# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Resolve layer - link mentions across documents to canonical entities.

Per Stage 1 PRD §8.1. Ships a fuzzy/Fellegi-Sunter probabilistic record
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
