# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Caller-owned document parser and OCR execution boundary."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from ._document_observations import DocumentIngestion, document_ingestion_from_parsed_document

if TYPE_CHECKING:
    from arche.doc.parse import ParsedDocument


@dataclass(frozen=True)
class DocumentIngestionRequest:
    """Caller-managed document input for one permitted extraction action."""

    source: str | Path
    source_record_id: str
    do_ocr: bool | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.source_record_id, str) or not self.source_record_id:
            raise ValueError("document ingestion request needs a source_record_id")
        if self.do_ocr is not None and not isinstance(self.do_ocr, bool):
            raise ValueError("document ingestion request do_ocr must be true, false, or unknown")


class DocumentIngestionExecutor(Protocol):
    """Application-owned parser/OCR executor for one document action."""

    executor_id: str

    def ingest(self, request: DocumentIngestionRequest) -> DocumentIngestion:
        """Parse caller-managed input and return only value-free provenance."""


class DoclingDocumentIngestionExecutor:
    """Opt-in adapter from :func:`arche.doc.parse` to ``DocumentIngestion``."""

    executor_id = "arche.doc.parse"

    def __init__(
        self,
        parse_document: Callable[[str | Path, bool | None], ParsedDocument] | None = None,
    ) -> None:
        self._parse_document = parse_document

    def ingest(self, request: DocumentIngestionRequest) -> DocumentIngestion:
        """Run Docling/OCR only in the caller's process and discard text afterward."""
        if self._parse_document is None:
            from arche.doc import parse

            document = parse(request.source, do_ocr=request.do_ocr)
        else:
            document = self._parse_document(request.source, request.do_ocr)
        return document_ingestion_from_parsed_document(
            document,
            source_record_id=request.source_record_id,
        )
