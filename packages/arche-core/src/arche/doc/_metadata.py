# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Document metadata: who made this file, with what, and when.

``ParsedDocument.metadata`` was an empty dict. Every real PDF in this repo
carries the fields it was meant to hold, so this was data being discarded
rather than data that was missing::

    invoice_12_ak.pdf   author='Condor Flugdienst GmbH'   producer='iText 5.5.1'
    invoice_10.pdf      creator='Hyperion SQR Production Reporting'
    Monzo statement     creator='Chromium'  producer='Skia/PDF m145'
    Invoice-PEDHCF      producer='WeasyPrint 65.1'

Three things follow, and each is worth more than the metadata itself.

**The issuer arrives for free.** ``author='Condor Flugdienst GmbH'`` is a
high-confidence organisation with no model and no extraction — the same field
the entity extractor is otherwise guessing at from body text.

**The producer is a provenance signal.** ``Chromium``/``Skia`` means a human
printed this from a browser; ``WeasyPrint`` means a server rendered it from
HTML; ``iText``, ``Crystal Reports``, ``PDFlib`` and ``Hyperion`` mean an
enterprise reporting system emitted it. Those imply very different degrees of
trust in the contents, and none of it needs a cryptographic manifest.

**Metadata is itself personal data.** ``Title`` on the bank statement carries an
account fragment and a date range; ``Subject`` on the flight confirmation
carries a real booking reference. It is masked like any other value and it is
scanned by the detectors like any other text — before this, a card number in a
PDF ``Title`` was invisible to redaction.

A hard caveat that belongs on every surface here: **metadata is a claim, not a
verification.** ``producer`` and ``author`` are trivially forged by anyone who
can write a PDF. Read it as what the file says about itself.

Backends
--------
``pypdfium2`` first, because it arrives with ``docling``'s PDF support — anyone
who can call :func:`arche.doc.parse` on a PDF already has it, so this module
adds **no dependency**. ``pymupdf`` is used when present (the ``[pdf]`` extra),
because it additionally exposes the PDF version and the XMP packet. With
neither, an empty :class:`DocumentMetadata` is returned and nothing raises: a
file we cannot introspect is a file with no metadata, not an error.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal

__all__ = [
    "ContentCredentials",
    "DocumentMetadata",
    "Producer",
    "classify_producer",
    "read_metadata",
]

# `D:20250327055703+01'00'` — the PDF date syntax, which is nearly but not
# quite ISO-8601. The timezone offset is kept because it is a (weak) clue about
# where a document was produced.
# `Z` carries no digits after it, unlike `+01'00'`, so the offset group has to
# allow the bare form or a UTC timestamp parses as naive.
_PDF_DATE = re.compile(
    r"D?:?\s*(\d{4})(\d{2})?(\d{2})?(\d{2})?(\d{2})?(\d{2})?"
    r"(?:(Z)|([+-])(\d{2})'?(\d{2})?'?)?"
)

# Producer/creator string -> (family, tool). Ordered: the first match wins, so
# the more specific patterns come first. This is data rather than code on
# purpose — the same convention the detector and statute packs follow — and it
# is versioned so a change to it is visible in a pin.
PRODUCER_RULES_VERSION = "2026.08.1"
_PRODUCER_RULES: tuple[tuple[str, str, str], ...] = (
    (r"skia/pdf|chromium|chrome|headless", "browser-print", "Chromium"),
    (r"quartz|coregraphics|safari", "browser-print", "Safari/Quartz"),
    (r"weasyprint", "html-renderer", "WeasyPrint"),
    (r"wkhtmltopdf", "html-renderer", "wkhtmltopdf"),
    (r"prince", "html-renderer", "PrinceXML"),
    (r"puppeteer|playwright", "html-renderer", "Headless browser"),
    (r"itext", "enterprise-report", "iText"),
    (r"crystal", "enterprise-report", "Crystal Reports"),
    (r"pdflib", "enterprise-report", "PDFlib"),
    (r"hyperion|sqr", "enterprise-report", "Hyperion SQR"),
    (r"jasper", "enterprise-report", "JasperReports"),
    (r"telerik|kendo", "enterprise-report", "Telerik"),
    (r"sap|crystal|oracle", "enterprise-report", "SAP/Oracle"),
    (r"microsoft.*word|word for", "office", "Microsoft Word"),
    (r"microsoft.*excel", "office", "Microsoft Excel"),
    (r"powerpoint", "office", "Microsoft PowerPoint"),
    (r"libreoffice|openoffice", "office", "LibreOffice"),
    (r"pages|numbers|keynote", "office", "Apple iWork"),
    (r"acrobat|adobe.*distiller|adobe pdf", "authoring", "Adobe Acrobat"),
    (r"indesign|illustrator|photoshop", "authoring", "Adobe Creative"),
    (r"ghostscript", "authoring", "Ghostscript"),
    (r"latex|pdftex|xetex|luatex", "authoring", "TeX"),
    (r"reportlab", "library", "ReportLab"),
    (r"fpdf|tcpdf|dompdf|mpdf", "library", "PHP PDF library"),
    (r"pypdf|pikepdf|pdfkit", "library", "Python PDF library"),
    (r"scanner|scanjet|epson|canon.*scan|xerox|ricoh", "scanner", "Scanner"),
    (r"tesseract|abbyy|omnipage", "scanner", "OCR"),
)

#: Producer families, coarsest to most machine-generated. Documented as a
#: vocabulary because downstream code and docs both refer to it.
PRODUCER_FAMILIES = (
    "browser-print", "html-renderer", "enterprise-report", "office",
    "authoring", "library", "scanner", "unknown",
)


@dataclass(frozen=True)
class Producer:
    """What produced the file, as the file claims.

    ``family`` is the useful part: it separates "a person printed this from a
    browser" from "a server rendered it" from "an enterprise reporting system
    emitted it". Forgeable, like everything else here.
    """

    raw: str = ""
    family: str = "unknown"
    tool: str = ""
    version: str = ""

    def __bool__(self) -> bool:
        return bool(self.raw)


def classify_producer(raw: str) -> Producer:
    """Map a producer/creator string onto a family and a tool name.

    ``'Skia/PDF m145'`` -> ``browser-print`` / ``Chromium`` / ``m145``.
    Unrecognised strings keep their raw text and a family of ``unknown`` — a
    tool we have not seen is not a tool that does not exist.
    """
    text = (raw or "").strip()
    if not text:
        return Producer()
    lowered = text.lower()
    version = ""
    found = re.search(r"\b(?:v|m)?(\d+(?:\.\d+){1,3}|m\d+)\b", text)
    if found:
        version = found.group(0)
    for pattern, family, tool in _PRODUCER_RULES:
        if re.search(pattern, lowered):
            return Producer(raw=text, family=family, tool=tool, version=version)
    return Producer(raw=text, family="unknown", tool=text.split()[0], version=version)


@dataclass(frozen=True)
class ContentCredentials:
    """C2PA / content-credential provenance, when a document carries any.

    Shipped as a **type with an honest empty state**, not as a reader. No PDF
    available to this project carries a manifest — XMP is zero bytes in all of
    them — so a reader could be written but not demonstrated, and an untestable
    trust feature is worse than none. The reader is gated on holding real
    documents that carry manifests.

    ``ai_generated`` is a tri-state on purpose. ``None`` means *unknown*, and
    absence of a manifest can only ever produce ``None``: a document with no
    content credentials is not thereby human-authored, and saying otherwise
    would be the most dangerous possible reading of this field.
    """

    status: Literal["absent", "present", "unverified", "invalid"] = "absent"
    manifests: tuple[dict[str, Any], ...] = ()
    ai_generated: bool | None = None
    detail: str = ""

    def explain(self) -> str:
        if self.status == "absent":
            return (
                "No content credentials found. Absence is not evidence of "
                "tampering, and not evidence of human authorship — most "
                "documents in circulation carry no manifest at all."
            )
        if self.status == "invalid":
            return f"Content credentials present but did not validate: {self.detail}"
        if self.status == "unverified":
            return (
                "Content credentials present but not verified — arche read the "
                "manifest without checking its signature chain."
            )
        return f"Content credentials present and read: {self.detail}"


@dataclass(frozen=True)
class DocumentMetadata:
    """What a document says about itself.

    Every field is a **claim by the file**, never a verification. ``producer``
    and ``author`` are trivially forged by anyone who can write a PDF.
    """

    title: str = ""
    author: str = ""
    subject: str = ""
    keywords: str = ""
    creator: str = ""
    producer: Producer = field(default_factory=Producer)
    created: datetime | None = None
    modified: datetime | None = None
    tz_offset_minutes: int | None = None
    page_count: int | None = None
    pdf_version: str = ""
    encrypted: bool = False
    xmp: str = ""
    credentials: ContentCredentials = field(default_factory=ContentCredentials)
    backend: str = "none"
    rules_version: str = PRODUCER_RULES_VERSION

    #: Fields whose values are free text from the document and may carry
    #: personal data — the bank statement's `Title` holds an account fragment,
    #: the flight confirmation's `Subject` a booking reference.
    TEXT_FIELDS = ("title", "author", "subject", "keywords", "creator")

    def text_values(self) -> dict[str, str]:
        """The free-text fields, for detection and masking.

        These go through the same detectors as the document body. Before this,
        a card number in a PDF ``Title`` was invisible to redaction.
        """
        return {name: getattr(self, name) for name in self.TEXT_FIELDS
                if getattr(self, name)}

    def to_dict(self, reveal: bool = False) -> dict[str, Any]:
        """A plain dict. Free-text fields are masked unless ``reveal``."""
        def show(value: str) -> str:
            if reveal or not value:
                return value
            return value[:4] + "*" * max(0, len(value) - 4)

        return {
            **{name: show(getattr(self, name)) for name in self.TEXT_FIELDS},
            "producer_family": self.producer.family,
            "producer_tool": self.producer.tool,
            "producer_version": self.producer.version,
            "created": self.created.isoformat() if self.created else None,
            "modified": self.modified.isoformat() if self.modified else None,
            "tz_offset_minutes": self.tz_offset_minutes,
            "page_count": self.page_count,
            "pdf_version": self.pdf_version,
            "encrypted": self.encrypted,
            "credentials": self.credentials.status,
            "ai_generated": self.credentials.ai_generated,
            "backend": self.backend,
            "rules_version": self.rules_version,
        }

    def __bool__(self) -> bool:
        return bool(self.title or self.author or self.creator or self.producer)


def _parse_pdf_date(raw: str) -> tuple[datetime | None, int | None]:
    """PDF's `D:YYYYMMDDHHmmSS+HH'mm'` into a datetime and a TZ offset.

    Returns ``(None, None)`` on anything unparseable rather than raising —
    a malformed date is a missing date, not a failure to read the file.
    """
    text = (raw or "").strip()
    if not text:
        return None, None
    match = _PDF_DATE.match(text)
    if not match:
        return None, None
    year, month, day, hour, minute, second, zulu, sign, off_h, off_m = match.groups()
    try:
        parts = [int(year), int(month or 1), int(day or 1),
                 int(hour or 0), int(minute or 0), int(second or 0)]
        offset_minutes: int | None = None
        tzinfo = None
        if zulu:
            offset_minutes, tzinfo = 0, timezone.utc
        elif sign in ("+", "-"):
            offset_minutes = int(off_h or 0) * 60 + int(off_m or 0)
            if sign == "-":
                offset_minutes = -offset_minutes
            tzinfo = timezone(timedelta(minutes=offset_minutes))
        return datetime(*parts, tzinfo=tzinfo), offset_minutes
    except (TypeError, ValueError):
        return None, None


def _from_pypdfium2(path: str) -> dict[str, Any] | None:
    try:
        import pypdfium2 as pdfium
    except ImportError:
        return None
    try:
        doc = pdfium.PdfDocument(path)
    except Exception:  # noqa: BLE001 — an unreadable file has no metadata
        return None
    try:
        keys = ("Title", "Author", "Subject", "Keywords", "Creator",
                "Producer", "CreationDate", "ModDate")
        raw = {}
        for key in keys:
            try:
                value = doc.get_metadata_value(key)
            except Exception:  # noqa: BLE001
                value = None
            if value:
                raw[key] = value
        raw["_page_count"] = len(doc)
        return raw
    finally:
        with_close = getattr(doc, "close", None)
        if callable(with_close):
            with_close()


def _from_pymupdf(path: str) -> dict[str, Any] | None:
    try:
        import fitz
    except ImportError:
        return None
    try:
        doc = fitz.open(path)
    except Exception:  # noqa: BLE001
        return None
    try:
        info = {k: v for k, v in (doc.metadata or {}).items() if v}
        raw = {
            "Title": info.get("title", ""), "Author": info.get("author", ""),
            "Subject": info.get("subject", ""), "Keywords": info.get("keywords", ""),
            "Creator": info.get("creator", ""), "Producer": info.get("producer", ""),
            "CreationDate": info.get("creationDate", ""),
            "ModDate": info.get("modDate", ""),
            "_page_count": doc.page_count,
            "_pdf_version": info.get("format", ""),
            "_encrypted": bool(getattr(doc, "is_encrypted", False)),
        }
        try:
            raw["_xmp"] = doc.xref_xml_metadata() or ""
        except Exception:  # noqa: BLE001
            raw["_xmp"] = ""
        return {k: v for k, v in raw.items() if v not in ("", None)}
    finally:
        with_close = getattr(doc, "close", None)
        if callable(with_close):
            with_close()


def read_metadata(source: str | Path, *, backend: str | None = None) -> DocumentMetadata:
    """Read a document's self-described metadata.

    ``backend`` forces ``"pypdfium2"`` or ``"pymupdf"``; by default both are
    tried in that order and the results merged, preferring whichever produced a
    value. A file neither backend can open yields an empty
    :class:`DocumentMetadata` with ``backend="none"`` — never an exception.

    >>> read_metadata("invoice.pdf").producer.family   # doctest: +SKIP
    'enterprise-report'
    """
    path = str(source)
    readers = {"pypdfium2": _from_pypdfium2, "pymupdf": _from_pymupdf}
    order = [backend] if backend else ["pypdfium2", "pymupdf"]

    merged: dict[str, Any] = {}
    used: list[str] = []
    for name in order:
        reader = readers.get(name or "")
        if reader is None:
            raise ValueError(
                f"unknown metadata backend {name!r}; use 'pypdfium2' or 'pymupdf'"
            )
        raw = reader(path)
        if raw:
            used.append(name)
            for key, value in raw.items():
                merged.setdefault(key, value)
    if not merged:
        return DocumentMetadata(backend="none")

    created, tz_offset = _parse_pdf_date(str(merged.get("CreationDate", "")))
    modified, _ = _parse_pdf_date(str(merged.get("ModDate", "")))
    # The producer field is the better provenance signal, but plenty of tools
    # only populate Creator (Crystal Reports, Hyperion), so fall back.
    producer_raw = str(merged.get("Producer") or merged.get("Creator") or "")

    return DocumentMetadata(
        title=str(merged.get("Title", "")),
        author=str(merged.get("Author", "")),
        subject=str(merged.get("Subject", "")),
        keywords=str(merged.get("Keywords", "")),
        creator=str(merged.get("Creator", "")),
        producer=classify_producer(producer_raw),
        created=created,
        modified=modified,
        tz_offset_minutes=tz_offset,
        page_count=merged.get("_page_count"),
        pdf_version=str(merged.get("_pdf_version", "")),
        encrypted=bool(merged.get("_encrypted", False)),
        xmp=str(merged.get("_xmp", "")),
        credentials=ContentCredentials(),  # see the class docstring: gated
        backend="+".join(used),
    )
