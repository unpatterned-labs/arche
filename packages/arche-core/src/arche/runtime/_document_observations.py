# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Adapters from Arche document parsing into immutable runtime observations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

from ._models import Observation

if TYPE_CHECKING:
    from arche.doc.parse import ParsedDocument


@dataclass(frozen=True)
class DocumentIngestion:
    """Value-free parser or OCR result that may enter a ResolutionCase.

    The application retains the artifact and extracted text. Arche keeps the
    hashes and parser pins needed to make later field Evidence reviewable.
    """

    source_record_id: str
    text_sha256: str
    parser: str
    ocr: bool | None
    artifact_sha256: str | None = None
    parser_version: str | None = None
    page_count: int | None = None

    def __post_init__(self) -> None:
        if not all(
            isinstance(value, str) and value
            for value in (self.source_record_id, self.text_sha256, self.parser)
        ):
            raise ValueError("document ingestion needs source_record_id, text_sha256, and parser")
        if self.artifact_sha256 is not None and (
            not isinstance(self.artifact_sha256, str) or not self.artifact_sha256
        ):
            raise ValueError("document ingestion artifact_sha256 must be a non-empty string")
        if self.parser_version is not None and (
            not isinstance(self.parser_version, str) or not self.parser_version
        ):
            raise ValueError("document ingestion parser_version must be a non-empty string")
        if self.ocr is not None and not isinstance(self.ocr, bool):
            raise ValueError("document ingestion ocr must be true, false, or unknown")
        if self.page_count is not None and (
            isinstance(self.page_count, bool)
            or not isinstance(self.page_count, int)
            or self.page_count < 1
        ):
            raise ValueError("document ingestion page_count must be a positive integer")


def document_ingestion_from_parsed_document(
    document: ParsedDocument,
    *,
    source_record_id: str | None = None,
) -> DocumentIngestion:
    """Normalize an existing :class:`ParsedDocument` without retaining its text."""
    provenance = dict(document.provenance)
    text_sha256 = provenance.get("text_sha256")
    parser = provenance.get("parser")
    if (
        not isinstance(text_sha256, str)
        or not text_sha256
        or not isinstance(parser, str)
        or not parser
    ):
        raise ValueError(
            "parsed document needs text_sha256 and parser provenance before it can "
            "enter the entity runtime"
        )
    return DocumentIngestion(
        source_record_id=source_record_id or document.source,
        artifact_sha256=provenance.get("artifact_sha256"),
        text_sha256=text_sha256,
        parser=parser,
        parser_version=provenance.get("parser_version"),
        ocr=provenance.get("ocr"),
        page_count=document.num_pages,
    )


def observation_from_document_ingestion(
    ingestion: DocumentIngestion,
    *,
    observation_id: str,
    source_id: str,
    recorded_at: datetime,
) -> Observation:
    """Adapt one parser/OCR result to an immutable runtime Observation."""
    document_provenance = {
        "artifact_sha256": ingestion.artifact_sha256,
        "text_sha256": ingestion.text_sha256,
        "parser": ingestion.parser,
        "parser_version": ingestion.parser_version,
        "ocr": ingestion.ocr,
        "page_count": ingestion.page_count,
    }
    digest = ingestion.artifact_sha256 or ingestion.text_sha256
    return Observation(
        observation_id=observation_id,
        source_id=source_id,
        source_record_id=ingestion.source_record_id,
        recorded_at=recorded_at,
        content_hash=f"sha256:{digest}",
        provenance={"kind": "document_ingestion", "document": document_provenance},
    )


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
    return observation_from_document_ingestion(
        document_ingestion_from_parsed_document(document),
        observation_id=observation_id,
        source_id=source_id,
        recorded_at=recorded_at,
    )
