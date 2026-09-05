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
canonical record, and `resolve.compare` for the decision. The value is that
they compose *here*, once, rather than in every user's first notebook.
"""

from __future__ import annotations

import contextlib
import glob as _glob
import json
import os
import re
import time
from collections.abc import Iterable, Mapping
from contextlib import contextmanager, nullcontext
from dataclasses import dataclass, field
from itertools import combinations
from pathlib import Path
from typing import Any

from arche.doc._progress import Event, ProgressHandler, Timing, _Run, resolve_handler

__all__ = ["DocumentReport", "Event", "ProgressHandler", "resolve_documents"]

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


# Explicit document labels are a useful local extraction signal for commercial
# documents.  They become *proposed* fields for a reviewer, never a claim or
# an entity link by themselves.  The narrow vocabulary keeps this a transparent
# document adapter rather than an attempt to infer arbitrary relationships.
_LABELLED_IDENTITY_FIELDS = {
    "supplier": "supplier_name",
    "distributor": "distributor_name",
    "estate": "estate_name",
    "registration id": "registration_id",
    "registration number": "registration_id",
    "registration no": "registration_id",
    "country": "country",
    "origin": "country",
}
_LABELLED_IDENTITY_RE = re.compile(
    r"^\s*(?P<label>supplier|distributor|estate|registration\s+id|"
    r"registration\s+number|registration\s+no|country|origin)\s*:\s*"
    r"(?P<value>\S(?:.*\S)?)\s*$",
    re.IGNORECASE | re.MULTILINE,
)


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
    # transformers writes some notices straight to stderr, bypassing both
    # `logging` and `warnings` — "Asking to truncate to max_length..." is the
    # one GliNER triggers on every long document. Its own verbosity switch is
    # the only thing that silences it. Wrapped because the import is optional
    # and its API has moved between versions; failing to quiet a library must
    # never fail the run.
    with contextlib.suppress(Exception):
        from transformers.utils import logging as _hf_logging

        _hf_logging.set_verbosity_error()
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
    #: doc -> field -> "document" | "metadata". Which layer produced each value,
    #: because a name read from the body and a name asserted by a PDF header are
    #: not equally trustworthy.
    record_provenance: dict[str, dict[str, str]] = field(default_factory=dict)
    #: doc -> the document's self-described metadata, masked on export.
    metadata: dict[str, Any] = field(default_factory=dict)
    #: doc -> what produced its parse: artifact hash, parser and version, text
    #: digest. Enters every decision's pins, so a decision derived from a
    #: document can be re-verified rather than only re-run.
    provenance: dict[str, dict[str, Any]] = field(default_factory=dict)
    errors: dict[str, str] = field(default_factory=dict)
    jurisdiction: str = ""
    entity: str = ""
    #: doc -> the inferred jurisdiction and why, when `jurisdiction="auto"`.
    jurisdictions: dict[str, Any] = field(default_factory=dict)
    #: doc -> (declared, inferred) when an explicit jurisdiction disagrees with
    #: the document's own evidence. Surfacing this turns "you said NG, the
    #: evidence says GB" from 36 mystery detections into one warning.
    jurisdiction_conflicts: dict[str, tuple[str, str]] = field(default_factory=dict)
    #: Where the time went. Progress answers "is it stuck?" during a run;
    #: this answers "what was slow?" afterwards.
    timing: Timing = field(default_factory=Timing)
    #: Proposed identity fields and their source spans. Values remain in the
    #: caller-owned report and are masked by :meth:`review` by default.
    review_fields: dict[str, dict[str, dict[str, object]]] = field(default_factory=dict)

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
                    f"{show(rec.get(f, '')) if rec.get(f) else '-':<22}"
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

    def to_rows(self, reveal: bool = False) -> tuple[list[str], list[list[str]]]:
        """``(header, rows)`` — one row per document, every value a string.

        This is the primitive the other tabular exports are built on, and it is
        public because it is the seam: pandas, Excel, BigQuery and Google Sheets
        are each three lines of your own code on top of it, with no dependency
        and no authentication story for this library to own.

            header, rows = report.to_rows()
            pandas.DataFrame(rows, columns=header)
            worksheet.update([header] + rows)      # any gspread-like client

        Columns are sorted, so a diff between two runs shows what changed rather
        than that the dict order moved. Masked unless ``reveal``.
        """
        show = (lambda v: str(v)) if reveal else _mask
        record_fields = sorted({k for rec in self.records.values() for k in rec})
        header = (["document", "jurisdiction", "producer_family"]
                  + record_fields + ["detections", "parse_seconds"])
        rows: list[list[str]] = []
        for doc, rec in self.records.items():
            proposal = self.jurisdictions.get(doc) or {}
            meta = self.metadata.get(doc) or {}
            timing = self.timing.per_document.get(doc, {})
            rows.append([
                doc,
                str(proposal.get("country") or ""),
                str(meta.get("producer_family") or ""),
                *[show(rec[f]) if rec.get(f) else "" for f in record_fields],
                ";".join(f"{k}={v}" for k, v in
                         sorted((self.detections.get(doc) or {}).items())),
                f"{timing.get('parse', 0.0):.2f}",
            ])
        return header, rows

    def to_csv(self, path: str | os.PathLike | None = None, *,
               reveal: bool = False) -> str | Path:
        """CSV of :meth:`to_rows`. Returns the text, or the path if one is given.

        Written ``utf-8-sig`` so Excel opens it with the right encoding rather
        than mangling every non-ASCII name — which, for this project's data, is
        most of them.
        """
        import csv as _csv
        import io as _io

        header, rows = self.to_rows(reveal)
        buffer = _io.StringIO(newline="")
        writer = _csv.writer(buffer, lineterminator="\n")
        writer.writerow(header)
        writer.writerows(rows)
        text = buffer.getvalue()
        if path is None:
            return text
        out = Path(path)
        out.write_text(text, encoding="utf-8-sig")
        return out

    def to_json(self, reveal: bool = False, indent: int = 2) -> str:
        """The whole report as JSON — records, verdicts, and what was skipped."""
        return json.dumps(
            {"jurisdiction": self.jurisdiction,
             "entity": self.entity,
             "records": self.to_dicts(reveal),
             "decisions": self.decisions,
             "timing": self.timing.to_dict(),
             "errors": self.errors},
            indent=indent, default=str,
        )

    def review(self, *, reveal: bool = False) -> dict[str, Any]:
        """A masked, application-renderable review artifact.

        The safe hand-off point for a review pane or an agent: the fields each
        document proposed (with their spans), every verdict, and the documents
        nothing linked. Values are masked unless ``reveal=True``. It asserts no
        claim and treats no extracted value as accepted evidence; pass a
        ``store=`` to :func:`resolve_documents` if the decisions should outlive
        this report.
        """
        show = (lambda value: value) if reveal else _mask
        fields = [
            {
                "document": document,
                "field": field_name,
                "value": show(field["value"]),
                "source": field["source"],
                "confidence": field["confidence"],
                "span": field["span"],
            }
            for document, document_fields in sorted(self.review_fields.items())
            for field_name, field in sorted(document_fields.items())
        ]
        return {
            "entity": self.entity,
            "proposed_fields": fields,
            "decisions": list(self.decisions),
            "unlinked": self.unlinked(),
            "errors": dict(self.errors),
        }

    def unlinked(self) -> list[str]:
        """Documents no verdict tied to anything: the open questions."""
        linked = {
            document
            for row in self.decisions
            if row["identity"] == "same_entity"
            for document in (row["a"], row["b"])
        }
        return [document for document in self.records if document not in linked]


    def save_json(self, path: str | os.PathLike, reveal: bool = False) -> Path:
        out = Path(path)
        out.write_text(self.to_json(reveal), encoding="utf-8")
        return out

    def __str__(self) -> str:  # so `print(report)` does the useful thing
        return self.table()


def _write_if_absent(items, get_item, write_items, label: str) -> None:
    """Write immutable records once, refusing an accidental identifier collision."""
    missing = []
    for item in items:
        identifier = next(
            value
            for name, value in vars(item).items()
            if name.endswith("_id") and isinstance(value, str)
        )
        existing = get_item(identifier)
        if existing is None:
            missing.append(item)
        elif existing != item:
            raise ValueError(f"{label} {identifier!r} already exists with different content")
    if missing:
        write_items(missing)


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


def _record_from_metadata(info) -> dict[str, Any]:
    """Fields the document states about itself, needing no model.

    `author='Condor Flugdienst GmbH'` is a high-confidence issuer identity
    sitting in the PDF header — the same field the entity extractor otherwise
    guesses at from body text, available for free and more reliably.

    It is still a *claim*: metadata is trivially forged. It is used the way any
    other unverified evidence is used, and `report.record_provenance` records
    that it came from metadata rather than from the document body.
    """
    out: dict[str, Any] = {}
    if getattr(info, "author", ""):
        out["organisation"] = info.author
    return out


def _record_from_text(text: str, jurisdiction: str | None,
                      inferred: bool = False,
                      extraction_backend: str = "auto") -> tuple[dict, dict]:
    """A canonical record plus a detection census, using only arche's own layers.

    Identifiers come from the **detectors**, which validate check digits, and
    names and places from the **extractor**. Neither is a pattern the caller
    has to write, and neither is guessed from capitalisation.
    """
    from arche import Pipeline
    from arche.extract import extract

    record: dict[str, Any] = {}
    census: dict[str, int] = {}

    # An inferred jurisdiction with no pack gets the conservative floor —
    # otherwise "detecting the right country" silently stops redacting.
    kwargs = {"on_uncovered": "baseline"} if inferred else {}
    result = Pipeline(jurisdiction=jurisdiction, **kwargs).process(text)
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
        entities = list(extract(text, backend=extraction_backend))
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


def _labelled_identity_fields(text: str) -> dict[str, dict[str, object]]:
    """Return transparent supplier-document fields with their text spans.

    A shipment document often labels the parties more precisely than a generic
    entity extractor can. The result is deliberately review-pending: a label
    such as ``Supplier:`` is a statement in one document, not proof of a
    supplier relationship or a stable entity identity.
    """
    fields: dict[str, dict[str, object]] = {}
    for match in _LABELLED_IDENTITY_RE.finditer(text):
        label = " ".join(match.group("label").lower().split())
        field_name = _LABELLED_IDENTITY_FIELDS[label]
        if field_name in fields:
            continue
        value_start, value_end = match.span("value")
        fields[field_name] = {
            "value": match.group("value"),
            "source": "document_label",
            "confidence": 0.9,
            "span": [value_start, value_end],
        }
    return fields


def _candidate_id(candidate: Mapping[str, Any], index: int) -> str:
    """Return the caller's stable candidate handle without inventing one."""
    value = candidate.get("entity_id") or candidate.get("id")
    if not isinstance(value, str) or not value:
        raise ValueError(
            f"candidate {index} needs a non-empty 'entity_id' or 'id'; "
            "candidate identity must be caller-supplied"
        )
    return value


def _decision_row(a: str, b: str, decision: Any, *, candidate: bool = False) -> dict[str, Any]:
    """Render a resolver result without promoting it to a durable receipt."""
    return {
        "a": a,
        "b": b,
        "identity": getattr(decision, "identity", ""),
        "score": round(float(getattr(decision, "score", 0.0)), 4),
        "factors": {
            key: round(value, 4) if isinstance(value, (int, float)) else value
            for key, value in dict(getattr(decision, "factors", {})).items()
        },
        "decision_id": getattr(decision, "decision_id", ""),
        **({"status": "proposed"} if candidate else {}),
    }


def resolve_documents(
    source: str | os.PathLike | Iterable[str | os.PathLike],
    *,
    entity: str = "person",
    jurisdiction: str = "auto",
    candidates: Iterable[Mapping[str, Any]] | None = None,
    max_candidate_pairs: int = 1_000,
    quiet: bool = True,
    progress: ProgressHandler | bool | str | None = True,
    extraction_backend: str = "auto",
    store: Any | None = None,
) -> DocumentReport:
    """Parse documents, propose fields, and resolve against records or each other.

    ``source`` may be a glob (``"docs/*.pdf"``), a directory, a single file, or
    any iterable of those.

    >>> report = resolve_documents("data/docs/*.pdf")     # doctest: +SKIP
    >>> print(report.table())                             # doctest: +SKIP
    >>> report.to_json()                                  # doctest: +SKIP

    Every stage is a shipped `arche` layer: :func:`arche.doc.parse` for text,
    :class:`arche.Pipeline` for statute-aware detection, :func:`arche.extract`
    for names and places, :class:`arche.canonical.Reference` for the record, and
    :func:`arche.resolve.compare` for the verdict. The caller writes no
    patterns and no field-mapping.

    ``quiet=True`` silences the third-party loggers underneath ``parse`` so the
    first thing you see is your result rather than an OCR engine banner. Pass
    ``quiet=False`` when you are debugging the parse itself.

    ``extraction_backend`` selects the entity extractor used after parsing.
    ``"auto"`` keeps the default model-assisted behaviour; ``"regex"`` is
    deterministic, air-gapped, and suitable for bounded CI or policy contexts.

    ``jurisdiction`` defaults to ``"auto"``: each document's own evidence — a
    postcode, a registrar's name, a currency, a company-form suffix — proposes a
    country, and a document whose evidence is thin or conflicting gets no
    statute rather than a guessed one. Pass a code to override; an explicit
    jurisdiction always wins, and any disagreement with the evidence is recorded
    in ``report.jurisdiction_conflicts`` rather than left silent.

    When a jurisdiction is *inferred* and no statute pack covers it, the
    conservative baseline floor applies. That is deliberate: detecting the right
    country would otherwise switch protection off, because a Pipeline with no
    statute returns text unredacted.

    Pass ``candidates`` to compare extracted document records against an
    explicit caller-owned registry, master-data export, or prior reviewed
    records. Each candidate needs an opaque ``entity_id`` or ``id``. Candidate
    comparisons are bounded by ``max_candidate_pairs``; provide a narrowed
    candidate set rather than relying on an accidental all-pairs run.

    Pass ``store=`` (a :class:`arche.ledger.Ledger` from :func:`arche.attach`)
    and every verdict is recorded with the record it was made from, so
    ``ledger.entities()`` shows which documents describe one thing and
    ``ledger.replay(decision_id)`` can make any verdict again later. Without a
    store the report is the only artifact.

    A document that cannot be parsed is recorded in ``report.errors`` and
    skipped, never raised — one unreadable scan in a folder of twenty should not
    cost you the other nineteen.
    """
    from arche import resolve
    from arche.canonical import Reference
    from arche.doc import parse

    if max_candidate_pairs < 0:
        raise ValueError("max_candidate_pairs must be non-negative")
    candidate_rows = None if candidates is None else list(candidates)
    if candidate_rows is not None and not all(isinstance(row, Mapping) for row in candidate_rows):
        raise TypeError("candidates must contain mapping records")

    report = DocumentReport(jurisdiction=jurisdiction, entity=entity)

    paths = _paths(source)
    run = _Run(resolve_handler(progress), total=len(paths))
    run.emit("start", message=f"resolving {len(paths)} document(s)")
    with (_quiet() if quiet else nullcontext()):
        _collect(report, paths, parse, jurisdiction, run, extraction_backend)

    run.emit("resolve", message="comparing records")
    _t = time.monotonic()

    refs = {doc: Reference.from_record(rec) for doc, rec in report.records.items()}
    if candidate_rows is not None:
        pair_count = len(refs) * len(candidate_rows)
        if pair_count > max_candidate_pairs:
            raise ValueError(
                f"document/candidate comparison would create {pair_count} pairs; "
                f"max_candidate_pairs is {max_candidate_pairs}. Narrow candidates first."
            )
        candidate_inputs: dict[str, Any] = {}
        for index, row in enumerate(candidate_rows, start=1):
            candidate_id = _candidate_id(row, index)
            if candidate_id in candidate_inputs:
                raise ValueError(f"candidate identifiers must be unique: {candidate_id!r}")
            candidate_record = dict(row)
            candidate_record.setdefault("id", candidate_id)
            candidate_inputs[candidate_id] = (
                candidate_record if entity != "person" else Reference.from_record(candidate_record)
            )
        for document, document_ref in refs.items():
            rows: list[dict[str, Any]] = []
            document_input = report.records[document] if entity != "person" else document_ref
            for candidate_id, candidate_input in candidate_inputs.items():
                extraction = {"extraction": {"document": report.provenance.get(document, {})}}
                decision = resolve.compare(
                    document_input, candidate_input, entity=entity, extra_pins=extraction,
                )
                row = _decision_row(document, candidate_id, decision, candidate=True)
                report.decisions.append(row)
                rows.append(row)
                if store is not None:
                    store.record_compare(
                        decision, document_input, candidate_input,
                        call={"entity": entity, "extra_pins": extraction},
                        source="document", caller_ids=(document, candidate_id),
                    )
    else:
        for a, b in combinations(sorted(refs), 2):
            # The extraction that produced these records goes INSIDE the decision
            # hash, not alongside it. Without it a document-derived decision can be
            # re-run approximately but never re-verified: a parser upgrade changes
            # the text, which changes the record, which changes the verdict, and
            # nothing would record that it had. Every cited span also indexes into
            # a specific rendering, so `text_sha256` is what makes a citation
            # checkable rather than merely plausible.
            extraction = {
                side: report.provenance.get(doc, {})
                for side, doc in (("a", a), ("b", b))
                if report.provenance.get(doc)
            }
            extraction = {"extraction": extraction} if extraction else None
            side_a = refs[a] if entity == "person" else report.records[a]
            side_b = refs[b] if entity == "person" else report.records[b]
            decision = resolve.compare(side_a, side_b, entity=entity, extra_pins=extraction)
            report.decisions.append(_decision_row(a, b, decision))
            if store is not None:
                call = {"entity": entity}
                if extraction:
                    call["extra_pins"] = extraction
                store.record_compare(
                    decision, side_a, side_b, call=call,
                    source="document", caller_ids=(a, b),
                )
    run.timing.resolve_s = time.monotonic() - _t
    report.timing = run.finish()
    run.emit("done", message=f"{len(report.records)} record(s), "
                             f"{len(report.decisions)} verdict(s)")
    return report


def _collect(report, paths, parse, jurisdiction, run, extraction_backend="auto") -> None:
    """Parse each document and assemble its record; one bad file is not fatal.

    One bad file is not fatal. A missing parser is, and the difference matters:
    without ``docling`` every document fails identically and the report comes
    back with zero records and N copies of one install error. Read from
    outside, that is indistinguishable from a folder of documents containing
    nothing -- the failure mode this library exists to refuse. So the absent
    parser is raised rather than reported per-document.
    """
    from arche.doc.parse import DoclingNotInstalledError

    for index, path in enumerate(paths, 1):
        name = path.name
        run.emit("parse", document=name, index=index, message="parsing")
        _t = time.monotonic()
        try:
            parsed = parse(str(path))
            text = parsed.text
            run.stage(name, "parse", time.monotonic() - _t)
        except DoclingNotInstalledError:
            # Not this document's fault, and no later document will fare
            # better. Raising here says so once, loudly, instead of N times
            # quietly inside a report that otherwise reads as "found nothing".
            raise
        except Exception as exc:  # noqa: BLE001 — one bad file is not fatal
            report.errors[name] = f"{type(exc).__name__}: {exc}"
            continue
        if not (text or "").strip():
            report.errors[name] = "no extractable text (scanned image?)"
            continue
        run.emit("detect", document=name, index=index, message="detecting + extracting")
        _t = time.monotonic()
        doc_jurisdiction, inferred = _resolve_jurisdiction(
            jurisdiction, text, getattr(parsed, "info", None), name, report,
        )
        record, census = _record_from_text(
            text,
            doc_jurisdiction,
            inferred,
            extraction_backend,
        )
        labelled_fields = _labelled_identity_fields(text)
        for field_name, labelled_field in labelled_fields.items():
            record.setdefault(field_name, labelled_field["value"])
        if "supplier_name" in labelled_fields:
            supplier_name = labelled_fields["supplier_name"]["value"]
            record.setdefault("name", supplier_name)
            record.setdefault("organisation", supplier_name)
        run.stage(name, "detect", time.monotonic() - _t)
        # Metadata fills only what the body did not, so a name read from the
        # document always beats a name asserted by its header.
        for key, value in _record_from_metadata(getattr(parsed, "info", None)).items():
            if key not in record:
                record[key] = value
                report.record_provenance.setdefault(name, {})[key] = "metadata"
        for key in record:
            report.record_provenance.setdefault(name, {}).setdefault(key, "document")
        if not record:
            report.errors[name] = "no identity attributes found"
            continue
        review_fields = dict(labelled_fields)
        for field_name, value in record.items():
            review_fields.setdefault(
                field_name,
                {
                    "value": value,
                    "source": report.record_provenance.get(name, {}).get(field_name, "document"),
                    "confidence": 0.0,
                    "span": None,
                },
            )
        report.review_fields[name] = review_fields
        report.records[name] = record
        report.detections[name] = census
        info = getattr(parsed, "info", None)
        if info:
            report.metadata[name] = info.to_dict(reveal=True)
        extraction = getattr(parsed, "provenance", None)
        if extraction:
            report.provenance[name] = dict(extraction)


def _resolve_jurisdiction(requested: str, text: str, info: Any, name: str,
                          report: DocumentReport) -> tuple[str | None, bool]:
    """Which jurisdiction to process this document under, and whether we inferred it.

    An explicit code always wins. Inference still runs alongside it, because a
    silent disagreement between what the caller declared and what the document
    says is exactly how 36 phantom tax numbers appeared on a British bank
    statement — recorded now, instead of discovered later.
    """
    import warnings as _warnings

    from arche.jurisdictions.infer import infer_jurisdiction

    proposal = infer_jurisdiction(text, metadata=info)
    report.jurisdictions[name] = proposal.to_dict()

    if requested and requested.lower() != "auto":
        declared = requested.upper()
        if proposal.country and proposal.country != declared:
            report.jurisdiction_conflicts[name] = (declared, proposal.country)
            _warnings.warn(
                f"{name}: processing under declared jurisdiction {declared!r}, "
                f"but the document's own evidence indicates {proposal.country!r} "
                f"({proposal.reason}). The declared value wins; see "
                "report.jurisdiction_conflicts.",
                UserWarning, stacklevel=3,
            )
        return declared, False
    return proposal.country, bool(proposal.country)
