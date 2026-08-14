# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Document parsing via docling — the optional ``arche-core[doc]`` extra.

The base ``arche-core`` install does NOT pull docling. Calling
``arche.doc.parse(...)`` without the extra raises
:class:`DoclingNotInstalledError` with the precise install command,
in keeping with the lightweight-by-default commitment (BP §7.4
"Helpful failure modes").

``ParsedDocument`` is a thin adapter over docling's ``DoclingDocument``
that exposes only the surface arche needs:

- ``text``      — linearized plain text (what Pipeline consumes)
- ``markdown``  — structured markdown for human review
- ``json``      — full structured representation
- ``tables``    — extracted tables as ``list[list[list[str]]]``
- ``num_pages`` — page count (None for non-paginated inputs)

We intentionally do not expose docling's internal Pydantic types here.
Coupling to those would tie our public API to docling's evolving spec.
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from arche.doc._metadata import DocumentMetadata, read_metadata

# Probe for docling availability at import time. We don't import its
# heavy classes (DocumentConverter) — those load eagerly. We just check
# the module exists. The actual import happens inside ``parse()``.
try:
    import docling  # noqa: F401

    DOC_FEATURE_AVAILABLE = True
except ImportError:
    DOC_FEATURE_AVAILABLE = False


class DoclingNotInstalledError(RuntimeError):
    """Raised when ``arche.doc.parse`` is called without ``docling`` installed.

    Per BP §7.4, the message names the exact extra to install.
    """

    def __init__(self) -> None:
        super().__init__(
            "arche.doc requires docling. Install with:\n"
            "    pip install arche-core[doc]\n"
            "For scanned-document OCR support:\n"
            "    pip install arche-core[doc-ocr]"
        )


# ---------------------------------------------------------------------------
# ParsedDocument adapter
# ---------------------------------------------------------------------------

@dataclass
class ParsedDocument:
    """arche's view of a parsed document.

    Attributes
    ----------
    source:
        The original path/URL/identifier passed to ``parse()``.
    text:
        Linearized plain text suitable for downstream detection.
    markdown:
        Markdown rendering with layout structure preserved.
    json:
        Full structured representation (docling's serialized form).
    tables:
        Extracted tables as nested lists of cell strings.
    num_pages:
        Page count for paginated inputs (PDF, PPTX); ``None`` otherwise.
    metadata:
        Source metadata (title, author, language, etc.) extracted by docling.
    provenance:
        What produced this parse: the input artifact's hash, the parser and its
        version, the configuration that changes output, and a digest of the
        rendered text. See :attr:`provenance` for why each is load-bearing.
    """

    source: str
    text: str
    markdown: str = ""
    json: dict[str, Any] = field(default_factory=dict)
    tables: list[list[list[str]]] = field(default_factory=list)
    num_pages: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    #: Extraction provenance — see :func:`_extraction_provenance` for why a
    #: signature over a document-derived decision is worth little without it.
    provenance: dict[str, Any] = field(default_factory=dict)

    @property
    def info(self) -> DocumentMetadata:
        """The typed view of :attr:`metadata` — producer, author, dates.

        ``metadata`` stays the single source of truth (a plain dict, as it has
        always been, now populated) and this is a derived view, so the two can
        never disagree. Sources with no readable metadata return an empty
        :class:`~arche.doc._metadata.DocumentMetadata`, never ``None``.

        Read every field as a *claim by the file*: ``producer`` and ``author``
        are trivially forged by anyone who can write a PDF.
        """
        cached = self.metadata.get("_info")
        if isinstance(cached, DocumentMetadata):
            return cached
        return read_metadata(self.source)

    def __len__(self) -> int:
        return len(self.text)


# ---------------------------------------------------------------------------
# parse() — the public entry point
# ---------------------------------------------------------------------------

def _extraction_provenance(source: str, text: str, do_ocr: bool | None) -> dict[str, Any]:
    """What has to be recorded for a decision made from this parse to be checkable.

    A signature over a document-derived decision is worth very little on its
    own: it proves the verdict was not altered, while saying nothing about the
    extraction that produced it. Without the facts below such a decision can be
    **re-run approximately, never re-verified** — and a signed wrong merge with
    opaque extraction provenance is worse than an unsigned heuristic, because it
    lends institutional legitimacy to something the reader cannot inspect.

    Four facts, each because omitting it breaks a different thing:

    ``artifact_sha256``
        The exact bytes. A filename is not an identity — two files called
        `invoice.pdf` are not the same document, and the same file renamed is.
    ``parser`` / ``parser_version``
        A parser upgrade changes the text, which changes the record, which
        changes the verdict. A decision that does not name its parser cannot
        explain why it differs from the same decision made last year.
    ``text_sha256``
        Every span in the evidence indexes into *this* rendering. Without it a
        citation silently points at the wrong characters after any re-parse,
        which is worse than pointing at nothing.
    ``ocr``
        Changes the text for the same bytes, so it belongs with the parser.

    Best-effort by design: a URL, an unreadable file, or a missing version
    yields the fields it can and omits the rest. Failing to record provenance
    must never fail a parse — but the absence is then visible in the pins
    rather than silently assumed.

    Both digests are **full, untruncated SHA-256** in lowercase hex, unlike the
    16-hex internal tags elsewhere in the codebase. The difference is who
    recomputes them: an internal tag is only ever compared against itself, while
    ``artifact_sha256`` exists so that someone who was sent the file can run
    ``sha256sum`` (or ``Get-FileHash``, or ``shasum -a 256``) and get the same
    string. A truncated digest under a name that says ``sha256`` fails that
    check and reads as "this is not the file", which is the one wrong answer
    this field must never give.
    """
    import hashlib

    out: dict[str, Any] = {
        "parser": "docling",
        "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "ocr": do_ocr,
    }
    with contextlib.suppress(Exception):
        from importlib.metadata import version as _pkg_version

        out["parser_version"] = _pkg_version("docling")
    with contextlib.suppress(Exception):
        path = Path(source)
        if path.is_file():
            digest = hashlib.sha256()
            with open(path, "rb") as fh:
                for chunk in iter(lambda: fh.read(1 << 20), b""):
                    digest.update(chunk)
            out["artifact_sha256"] = digest.hexdigest()
    return out


def parse(
    source: str | Path,
    *,
    do_ocr: bool | None = None,
) -> ParsedDocument:
    """Parse a document via docling.

    Parameters
    ----------
    source:
        Path to a file (``str`` or ``Path``), a URL, or any input docling
        recognizes (PDF, DOCX, PPTX, XLSX, HTML, image).
    do_ocr:
        Force OCR on / off. When ``None`` (default), docling's default
        policy applies: digital text is preferred when present, OCR
        fallback for scanned regions. Requires ``arche-core[doc-ocr]``.

    Raises
    ------
    DoclingNotInstalledError
        When ``docling`` isn't installed.
    """
    if not DOC_FEATURE_AVAILABLE:
        raise DoclingNotInstalledError()

    # Import inside the function so we never pay the cost on `import arche`.
    from docling.document_converter import DocumentConverter

    converter = DocumentConverter()

    source_str = str(source)
    result = converter.convert(source_str)
    doc = result.document  # DoclingDocument

    text = doc.export_to_text() if hasattr(doc, "export_to_text") else ""
    markdown = doc.export_to_markdown() if hasattr(doc, "export_to_markdown") else ""
    try:
        as_json = doc.export_to_dict() if hasattr(doc, "export_to_dict") else {}
    except Exception:
        as_json = {}

    # Extract tables in a docling-version-tolerant way
    tables: list[list[list[str]]] = []
    for table in getattr(doc, "tables", []) or []:
        rows: list[list[str]] = []
        # docling tables have a .data attribute or .export_to_dataframe()
        if hasattr(table, "export_to_dataframe"):
            try:
                df = table.export_to_dataframe()
                rows = [[str(c) for c in r] for r in df.values.tolist()]
            except Exception:
                rows = []
        elif hasattr(table, "data"):
            data = table.data
            rows = [
                [str(getattr(cell, "text", cell)) for cell in row]
                for row in (data.table_cells if hasattr(data, "table_cells") else [])
            ]
        if rows:
            tables.append(rows)

    # What the file says about itself: title, author, producer, dates. This was
    # an empty dict for the whole life of the module while every real PDF in
    # the repo carried the fields it was meant to hold — data discarded, not
    # data missing. `author` in particular is an issuer identity available with
    # no model at all. Best-effort: a source we cannot introspect (a URL, a
    # format with no metadata, a missing backend) yields an empty dict and
    # never raises, because failing to read metadata must not fail a parse.
    metadata: dict[str, Any] = {}
    with contextlib.suppress(Exception):
        info = read_metadata(source_str)
        if info:
            metadata = info.to_dict(reveal=True)
            metadata["_info"] = info

    num_pages: int | None = None
    if hasattr(doc, "pages") and doc.pages is not None:
        try:
            num_pages = len(doc.pages)
        except TypeError:
            num_pages = None

    return ParsedDocument(
        source=source_str,
        text=text,
        provenance=_extraction_provenance(source_str, text, do_ocr),
        markdown=markdown,
        json=as_json,
        tables=tables,
        num_pages=num_pages,
        metadata=metadata,
    )
