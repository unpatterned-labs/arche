# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""One reader for the GLiNER 2 response shape.

Both GLiNER 2.5 (the general extractor) and GLiNER2-PII (the personal-data
proposer) answer ``extract_entities`` with spans grouped BY label::

    {"entities": {"organization": [{"text": ..., "confidence": ...,
                                    "start": ..., "end": ...}],
                  "person": []}}

``include_confidence`` and ``include_spans`` are always requested, because
without them the model returns bare strings, and a mention with no offsets
cannot be cited back to the document it came from. A span that arrives
without offsets anyway is skipped rather than faked: an uncitable mention is
worse than a missing one, because it looks like evidence.

:mod:`arche.extract` turns these spans into entities; :mod:`arche.detect.model`
turns them into statute-governed detections. Neither parses the shape itself.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Span:
    """One model-proposed span: the label it was asked for and where it sits."""

    label: str
    text: str
    start: int
    end: int
    confidence: float


def propose(text: str, labels: list[str] | dict[str, str], *, model: str | None = None,
            threshold: float = 0.5) -> list[Span]:
    """Ask a GLiNER 2 model for ``labels`` in ``text``.

    ``labels`` is a list of label names, or a ``{label: description}`` mapping
    -- the description is what lets a caller's own field name (``vessel_id``)
    mean one thing rather than every code on the page. Returned spans carry
    the label (the key), not the description.

    ``model`` is a Hugging Face name or local path; ``None`` means the
    configured general model. Raises ``ImportError`` -- naming the extra --
    when ``gliner2[local]`` is not installed.
    """
    from arche._models import get_gliner2

    extractor = get_gliner2(model)
    result = extractor.extract_entities(
        text, labels, threshold=threshold, include_confidence=True, include_spans=True,
    )
    out: list[Span] = []
    for label, spans in (result or {}).get("entities", {}).items():
        for span in spans or []:
            if not isinstance(span, dict):
                continue
            start, end = span.get("start"), span.get("end")
            if start is None or end is None:
                continue
            out.append(Span(
                label=str(label).lower(),
                text=str(span.get("text", text[int(start):int(end)])),
                start=int(start),
                end=int(end),
                confidence=float(span.get("confidence", 0.0)),
            ))
    out.sort(key=lambda s: (s.start, s.end))
    return out
