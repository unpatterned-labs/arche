# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Detection layer - find PII and identifiers in unstructured text.

Per Stage 1 PRD §4. Composed of per-country detector packages (ng/, ke/, za/,
gh/) for government identifiers with check-digit validation, plus optional
backends (gliner/, presidio/) for soft-PII detection in multiple languages.

The base install ships rule-based detectors for all four launch jurisdictions.
GLiNER2-PII and Microsoft Presidio are opt-in via `arche-core[detect]` and
`arche-core[presidio]` respectively.

Public API (PRD §10):
    from arche.detect.ng import detect_nigerian_ids
    from arche.detect.gliner import GLiNERDetector  # requires [detect] extra
    from arche.detect.presidio import PresidioPlugin  # requires [presidio] extra

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
    """``arche.detect`` is both a package (for v0.2 PRD §6.1 imports) and
    callable (for v0.1 ``from arche import detect`` backward compat).

    Removed in v0.3 once the v0.1 ``detect()`` function is renamed.
    """

    def __call__(self, *args, **kwargs):  # type: ignore[override]
        # Defer the import so we don't take a hard dependency on the pipeline
        # module at load time.
        from arche.workflow.pipeline import detect as _detect_fn

        return _detect_fn(*args, **kwargs)


_sys.modules[__name__].__class__ = _CallableDetectModule
