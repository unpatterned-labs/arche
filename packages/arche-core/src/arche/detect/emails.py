# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Cross-cutting email-address detector.

Emits canonical :class:`~arche.workflow.Detection` records with category
``PII-3-EMAIL`` (already mapped by every shipped statute, e.g. GDPR Art 4(1) /
ePrivacy). Deliberately **not** part of ``Pipeline``'s default detector set —
adding it there would change every existing caller's detections, policy
outcomes, and redacted text. Opt in explicitly::

    Pipeline(jurisdiction="DE", detectors=[..., "emails"]).process(text)

or use the resolution path (``coref_from_pipeline``), which includes it by
default because email is a distinctive co-reference signal.
"""

from __future__ import annotations

import re

from arche.workflow._primitive import Detection

# Pragmatic RFC-5322 subset: dotted local part (+tags), dotted domain with a
# 2-24 char alpha TLD. Deliberately conservative — no quoted local parts or
# IP-literal domains (rare in documents, high false-positive cost).
_EMAIL_RE = re.compile(
    r"\b[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+(?:\.[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+)*"
    r"@"
    r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
    r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)*"
    r"\.[A-Za-z]{2,24}\b"
)


def detect_emails(text: str) -> list[Detection]:
    """Detect email addresses in ``text``.

    Returns canonical detections (category ``PII-3-EMAIL``); ``sensitivity_tier``
    and ``regulatory_citation`` are populated by Pipeline's statute enrichment
    when a statute is loaded.
    """
    out: list[Detection] = []
    for m in _EMAIL_RE.finditer(text):
        out.append(Detection(
            # Detector-qualified id: span-only ids collide when two detectors
            # fire on one span, which breaks policy-outcome lookups.
            id=f"det:email:{m.start()}:{m.end()}",
            category="PII-3-EMAIL",
            text=m.group(0),
            start=m.start(),
            end=m.end(),
            confidence=0.95,
            detector="rule:email",
            identity_class="functional",
        ))
    return out


__all__ = ["detect_emails"]
