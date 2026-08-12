# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Documents in, resolved entities out — the whole path in one call.

Why this exists
---------------
Before this, turning three PDFs into "are these the same person?" took thirteen
notebook cells, and four of them were the user writing regular expressions::

    ORG    = re.compile(r"\\b(ltd|limited|inc|llc|plc|gmbh|corp|bank)\\b", re.I)
    PERSON = re.compile(r"^[A-Z][a-z]+(?: [A-Z][a-z\\-']+){1,3}$")
    EMAIL  = re.compile(r"\\b([\\w.\\-]+@[\\w.\\-]+\\.\\w+)\\b")

Every one of those is a worse version of something `arche` already ships. The
email pattern misses quoted locals and plus-addressing that `detect_emails`
handles; the person pattern cannot see a Yoruba or Hausa name that does not fit
`Firstname Lastname`, which is the exact failure this project exists to fix; and
the organisation list is a hand-written stop list of English legal suffixes.

A user writing a regex against a document is a bug in *our* API, not in their
notebook. If extraction is the lead capability, the library has to own the whole
path from a file on disk to a signed decision — parsing, detection, extraction,
record assembly, resolution and the report — with nothing left for the caller to
reimplement badly.

What it does not do
-------------------
It does not invent a new matcher. `resolve_documents` composes the pieces that
already exist and are already tested: `doc.parse` for text, `Pipeline` for
statute-aware detection, `extract` for names and places, `Reference` for the
canonical record, and `resolve.pairwise` for the decision. The value is that
they compose *here*, once, rather than in every user's first notebook.
"""

from __future__ import annotations

import glob as _glob
import json
import os
from contextlib import contextmanager, nullcontext
from dataclasses import dataclass, field
from itertools import combinations
from pathlib import Path
from typing import Any, Iterable

__all__ = ["DocumentReport", "resolve_documents"]

# Extracted entity types that become record fields. Names and places come from
# the extractor; identifiers come from the detectors, which validate check
# digits rather than pattern-matching.
_NAME_TYPES = ("PERSON", "PER", "person")
_PLACE_TYPES = ("LOCATION", "LOC", "ADDRESS", "location", "address")
_ORG_TYPES = ("ORG", "ORGANIZATION", "ORGANISATION", "organization")

# Detection categories mapped onto canonical record fields. The category
# vocabulary is the statute packs' own, so this never guesses from a string.
_DETECTION_FIELDS = {
    "EMAIL": "email",
    "PHONE": "phone",
    "NIN": "national_id",
    "BVN": "national_id",
    "NATIONAL_ID": "national_id",
    "SSN": "national_id",
    "PASSPORT": "passport",
    "ADDRESS": "address",
}


# Third-party layers below `parse` are chatty: docling's table exporter,
# RapidOCR's engine banner, tqdm's notebook warning, HuggingFace's download
# notices. In a three-cell notebook that noise arrives *before* the answer and
# buries it. Quieting it is the library's job — a user should not have to know
# which loggers to silence to read their own result.
_NOISY_LOGGERS = ("docling", "docling_core", "docling_ibm_models", "RapidOCR",
                  "rapidocr", "huggingface_hub", "transformers", "filelock",
                  "PIL", "matplotlib", "urllib3", "onnxruntime")


@contextmanager
def _quiet():
    """Silence everything below INFO for the duration of the parse.

    Targeting loggers by name is not enough: RapidOCR installs its own handler
    and its records still reached the notebook after `getLogger("RapidOCR")` was
    raised to ERROR. `logging.disable` is the blunt instrument that actually
    works, and it is restored on the way out so a caller's own logging config
    survives the call.
    """
    import logging
    import warnings

    previous = logging.root.manager.disable
    logging.disable(logging.INFO)
    for name in _NOISY_LOGGERS:
        logging.getLogger(name).setLevel(logging.ERROR)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            yield
    finally:
        logging.disable(previous)


def _mask(value: str, keep: int = 4) -> str:
    """Redact a value while leaving it recognisable to a human reviewer."""
    text = str(value)
    if len(text) <= keep:
        return "*" * len(text)
    return text[:keep] + "*" * (len(text) - keep)


@dataclass
class DocumentReport:
    """Everything `resolve_documents` found, in three shapes.

    `records` for the data, `decisions` for the verdicts, and `table()` /
    `to_json()` / `to_dicts()` for looking at either. A report that can only be
    printed is not a report — the JSON is what goes into a ticket, a test
    fixture, or the next pipeline stage.
    """

    records: dict[str, dict[str, Any]] = field(default_factory=dict)
    decisions: list[dict[str, Any]] = field(default_factory=list)
    detections: dict[str, dict[str, int]] = field(default_factory=dict)
    errors: dict[str, str] = field(default_factory=dict)
    jurisdiction: str = ""
    entity: str = ""

    # ---------------------------------------------------------------- views

    def table(self, reveal: bool = False) -> str:
        """The extracted records and the verdicts, as aligned text.

        Values are masked unless `reveal=True`, so the default is safe to paste
        into an issue or a slide.
        """
        show = (lambda v: str(v)) if reveal else _mask
        lines: list[str] = []

        fields = [f for f in ("name", "email", "phone", "national_id",
                              "address", "organisation")
                  if any(f in r for r in self.records.values())]
        if fields:
            width = max((len(d) for d in self.records), default=8)
            width = min(max(width, 10), 38)
            header = f"{'document':<{width}}  " + "  ".join(
                f"{f:<22}" for f in fields
            )
            lines += ["EXTRACTED RECORDS", header, "-" * len(header)]
            for doc, rec in self.records.items():
                row = f"{doc[:width]:<{width}}  " + "  ".join(
                    f"{show(rec.get(f, '')) if rec.get(f) else '—':<22}"
                    for f in fields
                )
                lines.append(row)

        if self.decisions:
            lines += ["", "RESOLUTION",
                      f"{'document a':<28} {'document b':<28} "
                      f"{'verdict':<12} {'score':>7}",
                      "-" * 78]
            for d in self.decisions:
                lines.append(
                    f"{d['a'][:26]:<28} {d['b'][:26]:<28} "
                    f"{d['identity']:<12} {d['score']:>7.4f}"
                )

        if self.errors:
            lines += ["", "SKIPPED"]
            lines += [f"  {k}: {v}" for k, v in self.errors.items()]
        return "\n".join(lines) if lines else "no documents resolved"

    def to_dicts(self, reveal: bool = False) -> list[dict[str, Any]]:
        """One row per document, values masked unless `reveal`."""
        show = (lambda v: str(v)) if reveal else _mask
        return [
            {"document": doc,
             **{k: show(v) for k, v in rec.items()},
             "detections": self.detections.get(doc, {})}
            for doc, rec in self.records.items()
        ]

    def to_json(self, reveal: bool = False, indent: int = 2) -> str:
        """The whole report as JSON — records, verdicts, and what was skipped."""
        return json.dumps(
            {"jurisdiction": self.jurisdiction,
             "entity": self.entity,
             "records": self.to_dicts(reveal),
             "decisions": self.decisions,
             "errors": self.errors},
            indent=indent, default=str,
        )

    def save_json(self, path: str | os.PathLike, reveal: bool = False) -> Path:
        out = Path(path)
        out.write_text(self.to_json(reveal), encoding="utf-8")
        return out

    def __str__(self) -> str:  # so `print(report)` does the useful thing
        return self.table()


def _paths(source: str | os.PathLike | Iterable[str | os.PathLike]) -> list[Path]:
    """Accept a glob, a directory, a single file, or an iterable of any of those."""
    if isinstance(source, (str, os.PathLike)):
        text = str(source)
        if any(ch in text for ch in "*?["):
            return sorted(Path(p) for p in _glob.glob(text, recursive=True))
        path = Path(text)
        if path.is_dir():
            return sorted(p for p in path.iterdir()
                          if p.is_file() and not p.name.startswith("."))
        return [path]
    out: list[Path] = []
    for item in source:
        out.extend(_paths(item))
    return out


def _record_from_text(text: str, jurisdiction: str) -> tuple[dict, dict]:
    """A canonical record plus a detection census, using only arche's own layers.

    Identifiers come from the **detectors**, which validate check digits, and
    names and places from the **extractor**. Neither is a pattern the caller
    has to write, and neither is guessed from capitalisation.
    """
    from arche import Pipeline
    from arche.extract import extract

    record: dict[str, Any] = {}
    census: dict[str, int] = {}

    result = Pipeline(jurisdiction=jurisdiction).process(text)
    for det in getattr(result, "detections", []):
        category = str(getattr(det, "category", "") or "")
        census[category] = census.get(category, 0) + 1
        # Categories are namespaced by pack (`PII-4-EMAIL`); match the tail.
        tail = category.rsplit("-", 1)[-1].upper()
        field_name = _DETECTION_FIELDS.get(tail)
        value = getattr(det, "text", "") or ""
        if field_name and value and field_name not in record:
            record[field_name] = value

    try:
        entities = list(extract(text))
    except Exception:  # noqa: BLE001 — extraction is best-effort, never fatal
        entities = []

    def _best(types: tuple[str, ...], longest: bool = False):
        found = [e for e in entities
                 if str(getattr(e, "entity_type", "")) in types]
        if not found:
            return None
        key = (lambda e: len(str(getattr(e, "text", ""))))if longest else (
            lambda e: getattr(e, "confidence", 0.0))
        return str(getattr(max(found, key=key), "text", "")) or None

    for field_name, types, longest in (
        ("name", _NAME_TYPES, False),
        ("address", _PLACE_TYPES, True),
        ("organisation", _ORG_TYPES, False),
    ):
        if field_name in record:
            continue
        value = _best(types, longest)
        if value:
            record[field_name] = value
    return record, census


def resolve_documents(
    source: str | os.PathLike | Iterable[str | os.PathLike],
    *,
    entity: str = "person",
    jurisdiction: str = "NG",
    quiet: bool = True,
) -> DocumentReport:
    """Parse documents, extract one record each, and resolve them against each other.

    ``source`` may be a glob (``"docs/*.pdf"``), a directory, a single file, or
    any iterable of those.

    >>> report = resolve_documents("data/docs/*.pdf")     # doctest: +SKIP
    >>> print(report.table())                             # doctest: +SKIP
    >>> report.to_json()                                  # doctest: +SKIP

    Every stage is a shipped `arche` layer: :func:`arche.doc.parse` for text,
    :class:`arche.Pipeline` for statute-aware detection, :func:`arche.extract`
    for names and places, :class:`arche.canonical.Reference` for the record, and
    :func:`arche.resolve.pairwise` for the verdict. The caller writes no
    patterns and no field-mapping.

    ``quiet=True`` silences the third-party loggers underneath ``parse`` so the
    first thing you see is your result rather than an OCR engine banner. Pass
    ``quiet=False`` when you are debugging the parse itself.

    A document that cannot be parsed is recorded in ``report.errors`` and
    skipped, never raised — one unreadable scan in a folder of twenty should not
    cost you the other nineteen.
    """
    from arche import resolve
    from arche.canonical import Reference
    from arche.doc import parse

    report = DocumentReport(jurisdiction=jurisdiction, entity=entity)

    with (_quiet() if quiet else nullcontext()):
        _collect(report, _paths(source), parse, jurisdiction)

    refs = {doc: Reference.from_record(rec) for doc, rec in report.records.items()}
    for a, b in combinations(sorted(refs), 2):
        decision = resolve.pairwise(refs[a], refs[b], entity=entity)
        report.decisions.append({
            "a": a, "b": b,
            "identity": getattr(decision, "identity", ""),
            "score": round(float(getattr(decision, "score", 0.0)), 4),
            "factors": {k: (round(v, 4) if isinstance(v, (int, float)) else v)
                        for k, v in dict(getattr(decision, "factors", {})).items()},
            "decision_id": getattr(decision, "decision_id", ""),
        })
    return report


def _collect(report, paths, parse, jurisdiction) -> None:
    """Parse each document and assemble its record; one bad file is not fatal."""
    for path in paths:
        name = path.name
        try:
            text = parse(str(path)).text
        except Exception as exc:  # noqa: BLE001 — one bad file is not fatal
            report.errors[name] = f"{type(exc).__name__}: {exc}"
            continue
        if not (text or "").strip():
            report.errors[name] = "no extractable text (scanned image?)"
            continue
        record, census = _record_from_text(text, jurisdiction)
        if not record:
            report.errors[name] = "no identity attributes found"
            continue
        report.records[name] = record
        report.detections[name] = census
