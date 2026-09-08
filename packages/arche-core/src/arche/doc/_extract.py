# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Schema-driven extraction: a document in, a validated object out.

    from pydantic import BaseModel
    from arche.doc import parse, extract

    class Invoice(BaseModel):
        invoice_number: str
        total: str

    parsed = parse("invoice.pdf")
    result = extract(Invoice, document=parsed)

    result.data.total                      # typed, validated
    result.fields["total"].span            # where it came from
    result.unresolved                      # what the schema wanted and we lacked

No API key, no account, no network. pydantic is already a required dependency,
so this adds **nothing** to the wheel.

Why the fields carry evidence
-----------------------------
The obvious design returns a dict of values. That is what most extractors do,
and it throws away the only thing that makes a value defensible: where it came
from. `FieldEvidence` keeps the span, the page, the confidence and — most
usefully — the *source*, because a value read by a check-digit-validated
detector and a value guessed by a model are not equally trustworthy, and a
reviewer needs to see which one they are looking at.

`unresolved` is the other half of that honesty. A schema field arche could not
fill is named, rather than silently defaulted or hallucinated. An extractor that
always returns a full object is not confident, it is unfalsifiable.

Where the values come from
--------------------------
Local, in order of trustworthiness, and never from a model unless asked:

1. **Detectors** — email, phone, identifiers. Structure-validated, so a match is
   strong evidence.
2. **Document metadata** — `author` is an issuer identity sitting in the PDF
   header, needing no model at all.
3. **The entity extractor** — names, organisations, places. Recognised rather
   than validated, so weaker, and carries a confidence.
4. **An LLM**, only under ``backend="llm"``, and only for fields the first three
   could not fill. Its proposals are validated by the schema like any other.

That ordering is the point. Collapsing it is how a pattern-matched
"identifier" that is really a formatting coincidence ends up treated as proof.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Generic, Literal, TypeVar

from pydantic import BaseModel, ValidationError

__all__ = ["Extraction", "FieldEvidence", "From", "extract"]

T = TypeVar("T", bound=BaseModel)

#: Where a value came from, weakest last.
Source = Literal["detector", "metadata", "extractor", "llm", "default"]


@dataclass(frozen=True)
class From:
    """Bind a schema field to a specific source.

        class Invoice(BaseModel):
            issuer: Annotated[str, From("metadata:author")]
            email: Annotated[str, From("detector:EMAIL")]

    Use it when the automatic mapping guesses wrong. ``"detector:EMAIL"``,
    ``"metadata:author"``, ``"extractor:ORGANIZATION"``.
    """

    spec: str

    @property
    def source(self) -> str:
        return self.spec.split(":", 1)[0]

    @property
    def key(self) -> str:
        return self.spec.split(":", 1)[-1]


@dataclass(frozen=True)
class FieldEvidence:
    """One filled field, and why it holds that value."""

    value: Any
    source: Source = "extractor"
    confidence: float = 0.0
    span: tuple[int, int] | None = None
    page: int | None = None
    detail: str = ""

    def __str__(self) -> str:
        where = f" @{self.span[0]}:{self.span[1]}" if self.span else ""
        return f"{self.value!r} ({self.source}, conf {self.confidence:.2f}{where})"


@dataclass
class Extraction(Generic[T]):
    """A validated schema instance plus the evidence behind every field."""

    data: T | None
    fields: dict[str, FieldEvidence] = field(default_factory=dict)
    unresolved: list[str] = field(default_factory=list)
    document: str = ""
    schema_name: str = ""
    errors: list[str] = field(default_factory=list)
    #: What proposed the model-sourced fields: the backend asked for, and the
    #: checkpoint that actually ran (``None`` when none did).
    backend: str = "basic"
    model: str | None = None
    #: The declaration this was extracted into, when there was one.
    declaration: Any = None

    @property
    def record(self) -> dict[str, Any]:
        """The filled fields as a plain ``{field: value}`` record."""
        return {k: v.value for k, v in self.fields.items()}

    def reference(self, record_id: str = ""):
        """The record as a canonical :class:`~arche.canonical.Reference`.

        Declared roles and restrictions apply, so this is what to hand to
        ``compare(..., schema=)``. Only for a declaration-driven extraction.
        """
        if self.declaration is None:
            raise ValueError("reference() needs a declaration-driven extraction "
                             "(arche.extract(text, schema=...))")
        record = dict(self.record)
        if record_id:
            record[self.declaration.id_field] = record_id
        ref, _violations = self.declaration.validate_record(record)
        return ref

    def pins(self) -> dict[str, Any]:
        """Provenance for a decision built on this extraction.

        Merged into ``compare(..., extra_pins=...)`` these enter the decision
        hash: what proposed the fields, under which declaration, and whether
        the extraction step re-runs to the same bytes -- true for the rules,
        false the moment a model proposed anything.
        """
        return {"extraction": {
            "backend": self.backend,
            "model": self.model,
            "declaration": self.declaration.pin() if self.declaration is not None else None,
            "sources": {k: v.source for k, v in self.fields.items()},
            "reproducible": self.model is None,
        }}

    def to_dict(self, reveal: bool = False) -> dict[str, Any]:
        """Values and their provenance. Masked unless ``reveal``."""
        def show(value: Any) -> Any:
            text = str(value)
            if reveal or len(text) <= 4:
                return value
            return text[:4] + "*" * (len(text) - 4)

        return {
            "document": self.document,
            "schema": self.schema_name,
            "data": {k: show(v.value) for k, v in self.fields.items()},
            "evidence": {
                k: {"source": v.source, "confidence": round(v.confidence, 3),
                    "span": list(v.span) if v.span else None, "page": v.page}
                for k, v in self.fields.items()
            },
            "unresolved": self.unresolved,
            "errors": self.errors,
        }

    def __bool__(self) -> bool:
        return self.data is not None


# Schema field name (or alias, or words from its description) -> the detector
# category that answers it. Matched on the normalised name, so `invoice_email`,
# `billingEmail` and `email` all reach the same place.
_FIELD_HINTS: dict[str, tuple[str, ...]] = {
    "email": ("EMAIL",),
    "phone": ("PHONE",), "telephone": ("PHONE",), "mobile": ("PHONE",),
    "nationalid": ("NIN", "BVN", "NATIONAL-ID", "SSN"),
    "passport": ("PASSPORT",),
    "address": ("ADDRESS",),
}
_META_HINTS: dict[str, str] = {
    "issuer": "author", "vendor": "author", "supplier": "author",
    "author": "author", "publisher": "author", "title": "title",
    "subject": "subject", "producer": "producer",
}
_ENTITY_HINTS: dict[str, tuple[str, ...]] = {
    "name": ("PERSON",), "customer": ("PERSON",), "recipient": ("PERSON",),
    "person": ("PERSON",),
    "organisation": ("ORG", "ORGANIZATION"), "organization": ("ORG", "ORGANIZATION"),
    "company": ("ORG", "ORGANIZATION"), "merchant": ("ORG", "ORGANIZATION"),
    "location": ("LOCATION", "LOC"), "city": ("LOCATION", "LOC"),
    "country": ("LOCATION", "LOC"), "place": ("LOCATION", "LOC"),
    "date": ("DATE",), "amount": ("MONEY",), "total": ("MONEY",),
    "price": ("MONEY",), "currency": ("MONEY",),
}


def _normalise(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


def _binding(model_field: Any) -> From | None:
    """An explicit ``From(...)`` on the field, if the author gave one."""
    for item in getattr(model_field, "metadata", ()) or ():
        if isinstance(item, From):
            return item
    return None


def _hint_keys(field_name: str, model_field: Any) -> list[str]:
    """Candidate lookup keys: the field name, its alias, and description words."""
    keys = [_normalise(field_name)]
    alias = getattr(model_field, "alias", None)
    if alias:
        keys.append(_normalise(alias))
    description = getattr(model_field, "description", None) or ""
    keys.extend(_normalise(word) for word in description.split())
    return [k for k in keys if k]


def _lookup(keys: list[str], table: dict[str, Any]) -> Any | None:
    """Match a hint table on exact name or suffix.

    Schema authors qualify their fields — `billing_email`, `billingEmail`,
    `invoice_email` — and all of them mean the same source as `email`. Suffix
    matching handles that without a synonym list to maintain.

    Suffix rather than substring on purpose: `billingemail` ends with `email`
    and should match, while `emailed_at` merely contains it and should not.
    """
    for key in keys:
        if key in table:
            return table[key]
    for key in keys:
        for hint, value in table.items():
            if len(key) > len(hint) and key.endswith(hint):
                return value
    return None


def extract(
    schema: Any,
    *,
    document: Any = None,
    text: str | None = None,
    jurisdiction: str = "NG",
    backend: str = "local",
    entity_backend: str = "auto",
    llm: Any = None,
) -> Extraction[T]:
    """Fill ``schema`` from a document, and say where every value came from.

    ``schema`` is a pydantic model class, or a :class:`~arche.declare.Declaration`
    (from :func:`arche.schema`). With a declaration the user's field names are
    the labels a GLiNER 2 model is asked for -- ``vessel_id`` with its
    description, not "an identifier" -- so the model proposes straight into
    the caller's fields, and the declared ``kind`` says which validator
    outranks it: a phone, an email, an address or an identifier arche has a
    validator for is taken from the validated detection first, and a field
    arche has no validator for (an IMO number, a licence code) is the model's
    to propose, with the evidence saying so.

    ``document`` may be a path, or a :class:`~arche.doc.parse.ParsedDocument`
    (which also supplies metadata). ``text`` skips parsing entirely.

    ``backend="local"`` uses only detectors, metadata and the entity extractor —
    no network, no key. ``backend="llm"`` additionally offers the *unresolved*
    fields to a model; its proposals are validated by the schema like any other
    value, and are marked ``source="llm"`` so a reviewer can see which they are.

    ``entity_backend`` is passed to :func:`arche.extract.extract` for the
    local entity-extraction stage. It defaults to ``"auto"`` for compatibility;
    pass ``"basic"`` for deterministic, air-gapped extraction.

    Returns an :class:`Extraction`. If the schema cannot be satisfied,
    ``data`` is ``None``, ``errors`` explains why, and ``fields`` still carries
    everything that *was* found — a failed validation should not throw away the
    evidence that got you there.
    """
    if backend not in ("local", "llm"):
        raise ValueError(f"unknown extract backend {backend!r}; use 'local' or 'llm'")

    parsed = None
    source_name = ""
    if text is None:
        if document is None:
            raise ValueError("extract() needs document= or text=")
        if hasattr(document, "text"):
            parsed = document
        else:
            from arche.doc.parse import parse as _parse

            parsed = _parse(str(document))
        text = parsed.text
        source_name = Path(str(getattr(parsed, "source", ""))).name
    elif document is not None:
        source_name = Path(str(document)).name

    decl = None
    if hasattr(schema, "labels") and hasattr(schema, "model") and not isinstance(schema, type):
        decl = schema
        schema = decl.model()
        if jurisdiction == "NG" and decl.jurisdiction not in ("", "default"):
            jurisdiction = decl.jurisdiction

    from arche.extract import canonical_backend

    entity_backend = canonical_backend(entity_backend)
    info = getattr(parsed, "info", None)
    found, model_name = _gather(text or "", info, jurisdiction, entity_backend,
                                decl.labels() if decl is not None else None)

    fields: dict[str, FieldEvidence] = {}
    unresolved: list[str] = []
    # The generic extractor cannot say which of two declared `name` fields a
    # PERSON belongs to, so that fallback is only allowed for a kind one field
    # declares. Two `name` fields and no model means two unresolved fields,
    # not the same person filled into both.
    kind_counts: dict[str, int] = {}
    if decl is not None:
        for f in decl.fields.values():
            if f.role != "ignore" and f.kinds:
                kind_counts[f.kinds[0]] = kind_counts.get(f.kinds[0], 0) + 1
    for name, model_field in schema.model_fields.items():
        if decl is not None:
            fdecl = decl.fields[name]
            unambiguous = kind_counts.get(fdecl.kinds[0] if fdecl.kinds else "", 0) == 1
            evidence = _fill_declared(fdecl, found, generic_fallback=unambiguous,
                                      entity=decl.entity)
        else:
            evidence = _fill(name, model_field, found)
        if evidence is None:
            unresolved.append(name)
        else:
            fields[name] = evidence

    if unresolved and backend == "llm" and llm is not None:
        _fill_with_llm(schema, unresolved, text or "", llm, fields)
        unresolved = [n for n in unresolved if n not in fields]

    result: Extraction[T] = Extraction(
        data=None, fields=fields, unresolved=unresolved,
        document=source_name, schema_name=schema.__name__,
        backend=entity_backend, model=model_name, declaration=decl,
    )
    try:
        result.data = schema(**{k: v.value for k, v in fields.items()})
    except ValidationError as exc:
        # Keep the evidence. A schema that did not validate is still a record
        # of what was found, and throwing it away makes the failure unreadable.
        result.errors = [
            f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}"
            for err in exc.errors()
        ]
    return result


def _gather(
    text: str,
    info: Any,
    jurisdiction: str,
    entity_backend: str,
    labels: dict[str, str] | None = None,
) -> tuple[dict[str, list[FieldEvidence]], str | None]:
    """Everything the local layers found, keyed by source, and the model that ran.

    With ``labels`` (a declaration's ``{field: description}``) a fourth source,
    ``declared``, holds what the model proposed for each field by name.
    """
    out: dict[str, list[FieldEvidence]] = {
        "detector": [], "metadata": [], "extractor": [], "declared": [],
    }
    model_name: str | None = None

    from arche import Pipeline

    for detection in getattr(Pipeline(jurisdiction=jurisdiction).process(text),
                             "detections", []):
        category = str(getattr(detection, "category", "")).rsplit("-", 1)[-1].upper()
        out["detector"].append(FieldEvidence(
            value=getattr(detection, "text", ""), source="detector",
            confidence=float(getattr(detection, "confidence", 0.0) or 0.0),
            span=(getattr(detection, "start", 0), getattr(detection, "end", 0)),
            detail=category,
        ))

    if info is not None:
        for key, value in (info.text_values() if hasattr(info, "text_values") else {}).items():
            out["metadata"].append(FieldEvidence(
                value=value, source="metadata", confidence=1.0, detail=key,
            ))

    try:
        from arche.extract import extract as extract_entities

        for entity in extract_entities(text, backend=entity_backend):
            out["extractor"].append(FieldEvidence(
                value=str(getattr(entity, "text", "")), source="extractor",
                confidence=float(getattr(entity, "confidence", 0.0) or 0.0),
                detail=str(getattr(entity, "entity_type", "")).upper(),
            ))
    except Exception:  # noqa: BLE001 — extraction is best-effort, never fatal
        pass

    if labels and entity_backend != "basic":
        from arche.config import get_config
        from arche.detect._gliner2 import propose

        try:
            cfg = get_config()
            spans = propose(text, labels, threshold=cfg.gliner2_threshold)
            model_name = cfg.gliner2_model
        except ImportError:
            if entity_backend != "auto":
                raise
            _warn_no_model_once()
            spans = []
        for s in spans:
            out["declared"].append(FieldEvidence(
                value=s.text, source="extractor", confidence=s.confidence,
                span=(s.start, s.end), detail=f"proposed by the model for {s.label}",
            ))
    return out, model_name


_warned_no_model = False


def _warn_no_model_once() -> None:
    global _warned_no_model
    if _warned_no_model:
        return
    _warned_no_model = True
    import warnings

    warnings.warn(
        "extract(schema=...) with backend='auto' had no model to ask for your "
        "fields: only the validators ran, so fields with no validator stay "
        "unresolved. Install one with: pip install 'arche-core[detect2]'",
        UserWarning, stacklevel=4,
    )


#: Declared ``kind`` -> the detector categories that answer it. These carry a
#: validator, which is why they outrank a model proposal for the same field.
_KIND_DETECTOR: dict[str, tuple[str, ...]] = {
    "phone": ("PHONE",),
    "email": ("EMAIL",),
    "address": ("ADDRESS",),
}
#: ``id_family`` (or a field named after one) -> the validated categories of
#: that family. A family absent here has no validator in arche, and the field
#: is the model's to propose.
_FAMILY_DETECTOR: dict[str, tuple[str, ...]] = {
    "nin": ("NIN",), "bvn": ("BVN",), "passport": ("PASSPORT",),
    "national_id": ("NIN", "NATIONAL_ID", "SA_ID", "KENYA_ID", "GHANA_CARD", "HUDUMA"),
    "ghana_card": ("GHANA_CARD",), "huduma": ("HUDUMA",), "sa_id": ("NATIONAL_ID",),
    "kenya_id": ("NATIONAL_ID",), "tin": ("TIN", "TAX_REFERENCE", "KRA_PIN"),
    "kra_pin": ("KRA_PIN",), "rc": ("RC",), "drivers_licence": ("DRIVERS_LICENCE",),
    "pvc": ("PVC",), "nhif": ("NHIF",), "ssnit": ("SSNIT",),
}
#: Declared kinds with no validator: the model's answer for the field first,
#: then the generic extractor's nearest entity type. A `name` is resolved by
#: what the declaration says it is *of* (see :func:`_name_types`), because a
#: supplier's name filled with the person who signed the email is the wrong
#: answer with a confident source.
_KIND_ENTITY: dict[str, tuple[str, ...]] = {
    "placename": ("LOCATION",), "containment": ("LOCATION",), "date": ("DATE",),
}
#: Entities whose `name` is a person's. Anything else -- a supplier, a facility,
#: a catch lot, a company -- names an organisation or a thing, and the basic
#: extractor's PERSON spans must not stand in for it.
_PERSON_ENTITIES = frozenset({
    "person", "people", "individual", "customer", "patient", "citizen", "client",
    "contact", "staff", "employee", "artist", "author", "beneficiary", "applicant",
})


def _name_types(fdecl: Any, entity: str) -> tuple[str, ...]:
    if fdecl.kinds and fdecl.kinds[0] in ("name", "tftoken"):
        return ("PERSON",) if entity.lower() in _PERSON_ENTITIES else ("ORGANIZATION",)
    return _KIND_ENTITY.get(fdecl.kinds[0] if fdecl.kinds else "", ())


def _pick_exact(candidates: list[FieldEvidence], wanted: tuple[str, ...]) -> FieldEvidence | None:
    matches = [c for c in candidates if c.detail in wanted]
    return max(matches, key=lambda c: c.confidence) if matches else None


def _fill_declared(fdecl: Any, found: dict[str, list[FieldEvidence]], *,
                   generic_fallback: bool = True, entity: str = "") -> FieldEvidence | None:
    """One declared field, from the most trustworthy source that can answer it.

    A validator that exists outranks the model; a family arche has no
    validator for is the model's to propose, and ``detail`` says which. The
    generic extractor's nearest entity type is the last resort, and only when
    ``generic_fallback`` says the field is the only one of its kind.
    """
    kind = fdecl.kinds[0] if fdecl.kinds else ""
    proposed = _pick_exact(found["declared"], (f"proposed by the model for {fdecl.name}",))

    validated: tuple[str, ...] = ()
    if kind == "id":
        family = (fdecl.id_family or fdecl.name).lower()
        validated = _FAMILY_DETECTOR.get(family, ())
    else:
        validated = _KIND_DETECTOR.get(kind, ())
    if validated:
        hit = _pick_exact(found["detector"], validated)
        if hit is not None:
            return hit
    if proposed is not None:
        return proposed
    wanted = _name_types(fdecl, entity) if generic_fallback else ()
    if wanted:
        hit = _pick_exact(found["extractor"], wanted)
        if hit is not None:
            return hit
    return None


def _pick(candidates: list[FieldEvidence], wanted: tuple[str, ...]) -> FieldEvidence | None:
    """The highest-confidence candidate whose detail matches one of ``wanted``."""
    matches = [c for c in candidates if any(w in c.detail for w in wanted)]
    return max(matches, key=lambda c: c.confidence) if matches else None


def _fill(name: str, model_field: Any,
          found: dict[str, list[FieldEvidence]]) -> FieldEvidence | None:
    """One schema field, from the most trustworthy source that can answer it."""
    binding = _binding(model_field)
    if binding is not None:
        candidates = found.get(binding.source, [])
        return _pick(candidates, (binding.key.upper(),))

    keys = _hint_keys(name, model_field)
    # Ordered by trustworthiness. Detectors are structure-validated, so a hit
    # there beats a model's guess; metadata is a claim by the file but a
    # precise one; the entity extractor is recognition, and weakest.
    wanted = _lookup(keys, _FIELD_HINTS)
    if wanted:
        hit = _pick(found["detector"], wanted)
        if hit:
            return hit
    meta_key = _lookup(keys, _META_HINTS)
    if meta_key:
        hit = _pick(found["metadata"], (meta_key,))
        if hit:
            return hit
    wanted = _lookup(keys, _ENTITY_HINTS)
    if wanted:
        hit = _pick(found["extractor"], wanted)
        if hit:
            return hit
    return None


def _fill_with_llm(schema: type[BaseModel], unresolved: list[str], text: str,
                   llm: Any, fields: dict[str, FieldEvidence]) -> None:
    """Offer only the unfilled fields to a model.

    Deliberately narrow: the model never revisits a field a validated detector
    already answered, so it cannot overwrite structure-checked evidence with a
    plausible guess. Anything it returns is marked ``source="llm"`` and still
    has to survive the schema.
    """
    descriptions = {
        n: (getattr(schema.model_fields[n], "description", "") or n)
        for n in unresolved
    }
    try:
        proposed = llm(text=text, fields=descriptions)
    except Exception:  # noqa: BLE001 — a model failure must not fail extraction
        return
    for name, value in (proposed or {}).items():
        if name in unresolved and value not in (None, ""):
            fields[name] = FieldEvidence(
                value=value, source="llm", confidence=0.0,
                detail="proposed by model, validated by schema",
            )
