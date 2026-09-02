# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Adapters from Arche document parsing into immutable runtime observations."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from ._models import Observation

if TYPE_CHECKING:
    from arche.doc.parse import ParsedDocument


def observation_from_document(
    document: ParsedDocument,
    *,
    observation_id: str,
    source_id: str,
    recorded_at: datetime,
) -> Observation:
    """Represent one parsed document as an immutable runtime Observation.

    The document parser's artifact and rendering hashes remain attached as
    provenance. This function neither trusts extracted text as a claim nor
    performs resolution; callers must derive Evidence before it can influence
    entity memory or a decision.

    Parameters:
        document: A document already parsed by :mod:`arche.doc`.
        observation_id: Caller-owned opaque identifier for the observation.
        source_id: The policy-controlled source identifier for this document.
        recorded_at: Time at which the parsed result entered the runtime.

    Returns:
        An immutable observation carrying document-parser provenance.

    Raises:
        ValueError: If the document carries neither an artifact nor text hash.
    """
    document_provenance = dict(document.provenance)
    digest = document_provenance.get("artifact_sha256") or document_provenance.get(
        "text_sha256"
    )
    if not isinstance(digest, str) or not digest:
        raise ValueError(
            "parsed document needs artifact_sha256 or text_sha256 provenance before "
            "it can enter the entity runtime"
        )
    return Observation(
        observation_id=observation_id,
        source_id=source_id,
        source_record_id=document.source,
        recorded_at=recorded_at,
        content_hash=f"sha256:{digest}",
        provenance={"document": document_provenance},
    )
