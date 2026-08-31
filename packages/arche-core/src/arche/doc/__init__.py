# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""arche.doc — document ingest layer (docling-backed, optional).

Per the verifiability roadmap locked decision (2026-06-02): arche
integrates [docling](https://github.com/docling-project/docling) (LF AI
Foundation, MIT) as the document parser rather than rolling its own.
``docling`` covers PDF / DOCX / PPTX / XLSX / HTML / image inputs and
exposes a unified ``DoclingDocument`` with layout, tables, code, and
formulas. arche wraps this in a small ``ParsedDocument`` adapter so the
public surface doesn't couple to docling's evolving API.

Tiered install — install only what you need:

- ``pip install arche-core[doc]``    — digital PDFs, DOCX, PPTX, XLSX
- ``pip install arche-core[doc-ocr]`` — adds easyocr for scanned PDFs / images
- ``pip install arche-core[doc-vlm]`` — adds a VLM backend for messy scans

Public API::

    from arche.doc import parse, ParsedDocument

    doc = parse("intake-form.pdf")
    print(doc.text)         # linearized text for downstream detection
    print(doc.markdown)     # structured markdown for human review
    print(doc.tables)       # extracted tables (list[list[list[str]]])

Or compose with the v0.2 Pipeline::

    from arche.workflow import Pipeline
    pipeline = Pipeline(jurisdiction="NG")
    result = pipeline.process_file("intake-form.pdf")
    # -> Detection + policy on the OCR'd text
"""

from arche.doc.parse import (
    DOC_FEATURE_AVAILABLE,
    DoclingNotInstalledError,
    ParsedDocument,
    parse,
)

from arche.doc._documents import DocumentReport, resolve_documents  # noqa: E402
from arche.doc._extract import Extraction, FieldEvidence, From, extract  # noqa: E402
from arche.doc._metadata import DocumentMetadata, read_metadata  # noqa: E402
from arche.doc._residence import (  # noqa: E402
    ResidenceCheck,
    assess_residence,
)

__all__ = [
    "DocumentMetadata",
    "DocumentReport",
    "Extraction",
    "FieldEvidence",
    "From",
    "extract",
    "read_metadata",
    "resolve_documents",
    "ResidenceCheck",
    "assess_residence",
    "parse",
    "ParsedDocument",
    "DoclingNotInstalledError",
    "DOC_FEATURE_AVAILABLE",
]
