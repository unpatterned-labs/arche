# Copyright 2026 unpatterned.org
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""File ingestion — extract clean text from any supported file format.

Simpler and more focused than unstructured.io: no chunking, no partitioning,
just clean text extraction from files so they can be fed into the identity
resolution pipeline.

Supported formats:
    - PDF (requires ``pymupdf``: ``pip install arche-core[pdf]``)
    - DOCX (requires ``python-docx``: ``pip install arche-core[docx]``)
    - TXT, CSV, JSON — built-in, no extra dependencies
    - Images (requires ``pytesseract`` + Tesseract binary)

Usage:
    from arche.ingest import extract_text
    text = extract_text("report.pdf")
    text = extract_text("patient_records.docx")
    text = extract_text("notes.txt")
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

_log = logging.getLogger("arche")

# ═══════════════════════════════════════════════════════════════════════════════
# FORMAT REGISTRY
# ═══════════════════════════════════════════════════════════════════════════════

_TEXT_EXTENSIONS = {".txt", ".text", ".log", ".md", ".rst"}
_DATA_EXTENSIONS = {".csv", ".tsv", ".json", ".jsonl"}
_PDF_EXTENSIONS = {".pdf"}
_DOCX_EXTENSIONS = {".docx"}
_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".tiff", ".tif", ".bmp", ".webp"}


def _normalize_whitespace(text: str) -> str:
    """Collapse runs of whitespace and normalize newlines.

    Preserves paragraph structure (double newlines) but removes trailing
    whitespace on each line and collapses 3+ consecutive newlines to 2.
    """
    # Normalize line endings
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    # Strip trailing whitespace on each line
    text = re.sub(r"[ \t]+$", "", text, flags=re.MULTILINE)
    # Collapse 3+ newlines to 2 (preserve paragraph breaks)
    text = re.sub(r"\n{3,}", "\n\n", text)
    # Strip leading/trailing whitespace
    return text.strip()


# ═══════════════════════════════════════════════════════════════════════════════
# FORMAT EXTRACTORS
# ═══════════════════════════════════════════════════════════════════════════════


def _extract_pdf(path: Path) -> str:
    """Extract text from a PDF file using pymupdf (fitz).

    Raises:
        ImportError: If pymupdf is not installed.
    """
    try:
        import fitz  # pymupdf
    except ImportError:
        raise ImportError(
            "PDF extraction requires pymupdf. "
            "Install with: pip install arche-core[pdf]"
        ) from None

    pages: list[str] = []
    with fitz.open(str(path)) as doc:
        for page in doc:
            page_text = page.get_text()
            if page_text:
                pages.append(page_text)

    return "\n".join(pages)


def _extract_docx(path: Path) -> str:
    """Extract text from a DOCX file using python-docx.

    Extracts all paragraph text. Tables and headers are included as
    paragraphs by python-docx.

    Raises:
        ImportError: If python-docx is not installed.
    """
    try:
        from docx import Document
    except ImportError:
        raise ImportError(
            "DOCX extraction requires python-docx. "
            "Install with: pip install arche-core[docx]"
        ) from None

    doc = Document(str(path))
    paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
    return "\n".join(paragraphs)


def _extract_plaintext(path: Path) -> str:
    """Read a plain text file (TXT, CSV, JSON, etc.) as-is."""
    return path.read_text(encoding="utf-8")


def _extract_image(path: Path) -> str:
    """Extract text from an image using pytesseract OCR.

    Raises:
        ImportError: If pytesseract or PIL is not installed.
        RuntimeError: If the Tesseract binary is not found.
    """
    try:
        import pytesseract
        from PIL import Image
    except ImportError:
        raise ImportError(
            "Image OCR requires pytesseract and Pillow. "
            "Install with: pip install pytesseract Pillow\n"
            "You also need the Tesseract binary: "
            "https://github.com/tesseract-ocr/tesseract"
        ) from None

    try:
        img = Image.open(path)
        text: str = pytesseract.image_to_string(img)
        return text
    except Exception as exc:
        if "tesseract" in str(exc).lower():
            raise RuntimeError(
                "Tesseract binary not found. Install it from: "
                "https://github.com/tesseract-ocr/tesseract"
            ) from exc
        raise


# ═══════════════════════════════════════════════════════════════════════════════
# PUBLIC API
# ═══════════════════════════════════════════════════════════════════════════════


def extract_text(source: str | Path) -> str:
    """Extract clean text from any supported file format.

    Detects the format from the file extension and delegates to the
    appropriate extractor. Returns a clean text string with normalized
    whitespace suitable for feeding into the entity extraction pipeline.

    Args:
        source: Path to the file to extract text from. Can be a string
            or ``pathlib.Path``.

    Returns:
        Extracted text with normalized whitespace. Empty string for
        empty files.

    Raises:
        FileNotFoundError: If the file does not exist.
        ValueError: If the file extension is not supported.
        ImportError: If a required optional dependency is not installed
            (pymupdf for PDF, python-docx for DOCX, pytesseract for images).

    Examples:
        >>> text = extract_text("report.pdf")
        >>> text = extract_text(Path("records.docx"))
        >>> text = extract_text("notes.txt")
    """
    path = Path(source)

    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")

    suffix = path.suffix.lower()

    if suffix in _PDF_EXTENSIONS:
        raw = _extract_pdf(path)
    elif suffix in _DOCX_EXTENSIONS:
        raw = _extract_docx(path)
    elif suffix in _TEXT_EXTENSIONS | _DATA_EXTENSIONS:
        raw = _extract_plaintext(path)
    elif suffix in _IMAGE_EXTENSIONS:
        raw = _extract_image(path)
    else:
        supported = sorted(
            _TEXT_EXTENSIONS | _DATA_EXTENSIONS | _PDF_EXTENSIONS
            | _DOCX_EXTENSIONS | _IMAGE_EXTENSIONS
        )
        raise ValueError(
            f"Unsupported file format: '{suffix}'. "
            f"Supported extensions: {', '.join(supported)}"
        )

    _log.debug("Extracted %d chars from %s (%s)", len(raw), path.name, suffix)
    return _normalize_whitespace(raw)
