# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Detection layer - find PII and identifiers in unstructured text.

Composed of per-country detector packages (ng/, ke/, za/,
gh/) for government identifiers with check-digit validation, plus optional
backends (gliner/, presidio/) for soft-PII detection in multiple languages.

The base install ships rule-based detectors for all four launch jurisdictions.
GLiNER2-PII and Microsoft Presidio are opt-in via `arche-core[detect]` and
`arche-core[presidio]` respectively.

Public API (PRD §10):
    from arche.detect.ng import detect_nigerian_ids
    from arche.detect.presidio import PresidioPlugin  # requires [presidio] extra

Neural extraction is reached through :func:`arche.extract`, not through a
detector class::

    extract(text, backend="gliner")   # GLiNER v1,  arche-core[detect]
    extract(text, backend="gliner2")  # GLiNER 2.5, arche-core[detect2]

This block used to advertise ``from arche.detect.gliner import GLiNERDetector``.
That class has never existed -- ``arche/detect/gliner/__init__.py`` is a
licence header and nothing else -- so the line sent every reader who trusted it
into an ImportError.

----

v0.1 backward compat: this module is also CALLABLE. The v0.1 API exposed a
``detect()`` function (``from arche import detect``) for fine-grained entity
extraction. To keep that surface working through the v0.2 migration without
forcing every test to update its imports, the ``arche.detect`` module is
made callable - calling it forwards to ``arche.workflow.pipeline.detect``.

This dual nature (package + callable) is intentional and temporary. In v0.3
the callable trick is removed and the function relocates to a clearly-named
home (``arche.detect.entities`` or ``arche.workflow.detect``).
"""

from __future__ import annotations

import sys as _sys
from types import ModuleType as _ModuleType


class _CallableDetectModule(_ModuleType):
    """``arche.detect`` is both a package and
    callable — and unlike the removed ``arche.resolve`` shim, this one is
    KEPT deliberately (decision 2026-08-07): ``arche.detect(text)`` is the
    documented Level-2 workhorse API, and the callable module is what makes
    it work regardless of whether the name resolved to the subpackage or the
    lazy function first. Revisit only if the Level-2 function is renamed.
    """

    def __call__(self, *args, **kwargs):  # type: ignore[override]
        # Defer the import so we don't take a hard dependency on the pipeline
        # module at load time.
        from arche.workflow.pipeline import detect as _detect_fn

        return _detect_fn(*args, **kwargs)


_sys.modules[__name__].__class__ = _CallableDetectModule
