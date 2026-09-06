# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Workflow layer - the detection primitive.

``Pipeline`` runs the detectors for a jurisdiction, applies its statute and
returns a ``Result`` of ``Detection`` spans with the redacted text::

    from arche.workflow import Pipeline, Result, Detection

The citizen-side DSAR workflow that used to live beside it was removed in
0.8.0.
"""

from arche.workflow._primitive import Detection, Pipeline, Result

__all__ = [
    "Pipeline",
    "Result",
    "Detection",
]
