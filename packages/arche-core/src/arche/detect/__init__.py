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
"""

from __future__ import annotations

