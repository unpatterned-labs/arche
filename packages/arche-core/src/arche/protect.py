# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Find the personal data in a text, and make a copy you can hand on.

Two verbs over one detection run::

    from arche import detect_pii, deidentify

    note = "Patient Casey Example (NIN 12345678901) called from 0803 555 7890."

    for d in detect_pii(note, jurisdiction="NG"):
        print(d.category, (d.start, d.end), d.regulatory_citation)

    safe = deidentify(note, jurisdiction="NG")
    print(safe.text)          # Patient Casey Example (NIN [NIN]) called from PHONE_...
    print(safe.decision_id)   # red:sha256:... -- look it up, explain it, replay it

Both are :class:`arche.Pipeline` with the choices made: the statute that
governs the jurisdiction decides what counts as personal data and what
happens to each span (``mask``, ``tokenize``, ``drop``), and every detection
carries the section it was decided under. The pipeline's ``backend=`` selects
what proposes the spans the rules cannot see (``basic``, ``auto``,
``gliner2-pii``; see :mod:`arche.detect.model`).

**The jurisdiction is never guessed silently.** Pass one, or let it be
inferred from the text's own evidence -- a postcode, a registrar, a currency;
when the evidence is thin the call refuses and names the statutes it does
have, because a redaction made under the wrong law is a redaction that looks
finished and is not. A jurisdiction no pack covers gets arche's baseline
floor, which says in every citation that it is not the law of any country.

**A redaction is a decision.** :attr:`Deidentified.decision_id` is a content
hash over the spans, their actions and citations, and the pins -- the
detectors, the model, the statute and its version. Same text, same
installation, same id. Pass ``store=`` and the ledger keeps it beside the
matches: ``ledger.explain(id)`` says which span was masked under which
section, ``ledger.replay(id)`` runs the detectors again and reports whether
the same spans would be found today.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from arche.ids import content_hash
from arche.workflow._primitive import Detection, Pipeline, Result

#: How a span is rendered. ``statute`` lets the pack choose per category; the
#: other three apply one action to every span the statute governs.
METHODS: tuple[str, ...] = ("statute", "mask", "token", "drop")
_ENGINE_ACTION = {"mask": "mask", "token": "tokenize", "drop": "drop"}

#: Which `person`-pack field a tokenised category lands in for :meth:`Deidentified.record`.
_SLOT_FOR_CATEGORY: dict[str, str] = {
    "PII-1-NAME": "name",
    "PII-3-PHONE": "phone",
    "PII-3-EMAIL": "email",
    "PII-4-ADDRESS": "address",
    "PII-1-DOB": "dob",
    **{f"PII-2-{kind}": "national_id" for kind in (
        "NIN", "BVN", "NATIONAL_ID", "GHANA_CARD", "HUDUMA", "PASSPORT", "SA_ID",
        "KENYA_ID", "PVC", "DRIVERS_LICENCE", "NID", "NIDA", "CNI", "CNIE", "BI",
    )},
}


class JurisdictionRequiredError(ValueError):
    """The text did not say where it is from, and arche will not guess."""


@dataclass(frozen=True)
class Deidentified:
    """A copy of a text with its personal data removed, and the decision that made it."""

    #: The masked text.
    text: str
    #: What was found, with category, offsets, confidence and citation.
    detections: tuple[Detection, ...]
    #: What was done to each detection, in the same order.
    outcomes: tuple[Any, ...]
    #: Content-addressed id over spans, actions, citations and pins.
    decision_id: str
    #: sha256 of the input text -- the document the spans index into.
    document_hash: str
    jurisdiction: str | None
    statute: str | None
    #: ``basic``, ``auto`` or ``gliner2-pii``; ``pins["model"]`` names what ran.
    backend: str
    #: ``statute``, ``mask``, ``token`` or ``drop``.
    method: str
    pins: dict[str, Any] = field(default_factory=dict)
    coverage: dict[str, Any] = field(default_factory=dict)

    @property
    def count(self) -> int:
        return len(self.detections)

    def spans(self) -> list[dict[str, Any]]:
        """The value-free account of the redaction: no text, only where and why."""
        by_id = {o.detection_id: o for o in self.outcomes}
        out = []
        for d in self.detections:
            o = by_id.get(d.id)
            out.append({
                "category": d.category,
                "start": d.start,
                "end": d.end,
                "confidence": round(float(d.confidence), 4),
                "action": o.action if o is not None else None,
                "citation": d.regulatory_citation,
                "detector": d.detector,
            })
        return out

    def by_category(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for d in self.detections:
            counts[d.category] = counts.get(d.category, 0) + 1
        return dict(sorted(counts.items()))

    def record(self) -> dict[str, str]:
        """The tokens as a record, so two masked copies can still be compared.

        A ``tokenize`` outcome replaces a value with a keyed digest that is the
        same for the same value under the same ``salt``. Gathered by field --
        ``national_id``, ``phone``, ``email``, ``name``, ``address`` -- those
        digests are a record the ``person`` pack can compare exactly, without
        either side ever holding the value: two notes about one person link
        on ``national_id`` because their tokens are equal, and the receipt's
        evidence names the field, never the number. Masked (``[NIN]``) and
        dropped spans carry no identity and are left out, which is why
        ``method="token"`` is the one that makes a copy linkable.
        """
        by_id = {o.detection_id: o for o in self.outcomes}
        fields: dict[str, list[str]] = {}
        for d in self.detections:
            o = by_id.get(d.id)
            if o is None or o.action != "tokenize" or not o.applied_value:
                continue
            slot = _SLOT_FOR_CATEGORY.get(d.category)
            if slot is None:
                continue
            fields.setdefault(slot, []).append(o.applied_value)
        return {slot: " ".join(values) for slot, values in fields.items()}

    def __repr__(self) -> str:  # never the text: a repr in a log is an egress
        return (f"Deidentified(count={self.count}, statute={self.statute!r}, "
                f"method={self.method!r}, decision_id={self.decision_id[:26]!r}...)")


def _pipeline(text: str, jurisdiction: str | None, statute: str | None,
              backend: str) -> tuple[Pipeline, dict[str, Any]]:
    """The pipeline for this call, and how its jurisdiction was arrived at."""
    source: dict[str, Any]
    if jurisdiction is None and statute is None:
        from arche.jurisdictions.infer import infer_jurisdiction

        inferred = infer_jurisdiction(text)
        if inferred.abstained or not inferred.country:
            from arche.policy import STATUTE_FOR_JURISDICTION

            have = ", ".join(f"{k} ({v})" for k, v in sorted(STATUTE_FOR_JURISDICTION.items()))
            raise JurisdictionRequiredError(
                "the text does not say which jurisdiction governs it, and arche will "
                "not guess: a redaction under the wrong statute looks finished and is "
                f"not. Pass jurisdiction=... -- packs exist for {have} -- or statute=."
            )
        jurisdiction = inferred.country
        source = {"jurisdiction_source": "inferred",
                  "jurisdiction_confidence": round(float(inferred.confidence), 4)}
    else:
        source = {"jurisdiction_source": "given"}
    pipe = Pipeline(jurisdiction=jurisdiction, statute=statute, backend=backend,
                    on_uncovered="baseline")
    return pipe, source


def detect_pii(text: str, jurisdiction: str | None = None, *, backend: str = "auto",
               statute: str | None = None) -> list[Detection]:
    """The personal data in ``text``: category, offsets, confidence, citation.

    ``jurisdiction`` picks the statute (``"NG"`` -> NDPA-2023, ``"ZA"`` ->
    POPIA, ...); ``None`` infers it from the text and refuses when it cannot.
    ``backend`` is what proposes the spans the rules cannot see; ``"auto"``
    uses GLiNER2-PII when ``arche-core[detect2]`` is installed and the rules
    alone otherwise. Values are on the detections -- this is the caller's own
    text -- but never in their ``repr``.
    """
    pipe, _ = _pipeline(text, jurisdiction, statute, backend)
    return list(pipe.process(text).detections)


def deidentify(text: str, jurisdiction: str | None = None, *, backend: str = "auto",
               method: str = "statute", statute: str | None = None,
               salt: str = "", store: Any | None = None) -> Deidentified:
    """A copy of ``text`` with its personal data removed, as a decision.

    ``method="statute"`` (default) lets the pack decide per category -- NDPA
    masks a national id and tokenises a phone. ``"mask"``, ``"token"`` and
    ``"drop"`` apply one rendering to every governed span; the citations stay
    the statute's. ``salt`` keys the tokens so two deployments never mint the
    same token for the same value. ``store=`` records the decision in a
    ledger under its ``decision_id``.
    """
    if method not in METHODS:
        raise ValueError(f"method must be one of {METHODS}, got {method!r}")
    pipe, source = _pipeline(text, jurisdiction, statute, backend)
    if salt:
        pipe.tokenize_salt = salt
    result: Result = pipe.process(text)
    detections = list(result.detections)
    if method == "statute":
        redacted, outcomes = result.redacted_text, list(result.policy_outcomes)
    else:
        from arche.policy import apply_policy

        loaded = pipe._ensure_statute()
        redacted, outcomes = apply_policy(text, detections, loaded, tokenize_salt=salt,
                                          action_override=_ENGINE_ACTION[method])
    from arche import __version__
    from arche.coverage import coverage

    pins = {
        "engine": f"arche-core@{__version__}",
        "receipt_schema": "arche.deidentify.v1",
        "backend": pipe.backend,
        "model": result.metadata.get("model"),
        "detectors": list(pipe.effective_detectors()),
        "statute": pipe.statute_id,
        "statute_version": result.metadata.get("statute_version"),
        "jurisdiction": pipe.jurisdiction,
        "method": method,
        **source,
    }
    by_id = {o.detection_id: o for o in outcomes}
    spans = [
        {"category": d.category, "start": d.start, "end": d.end,
         "confidence": float(d.confidence),
         "action": by_id[d.id].action if d.id in by_id else None,
         "citation": d.regulatory_citation}
        for d in detections
    ]
    decision_id = content_hash(
        {"schema": "arche.deidentify.v1", "document": result.document_hash,
         "spans": spans, "pins": pins},
        prefix="red",
    )
    deid = Deidentified(
        text=redacted,
        detections=tuple(detections),
        outcomes=tuple(outcomes),
        decision_id=decision_id,
        document_hash=result.document_hash,
        jurisdiction=pipe.jurisdiction,
        statute=pipe.statute_id,
        backend=pipe.backend,
        method=method,
        pins=pins,
        coverage=coverage(pipe),
    )
    if store is not None:
        store.record_deidentify(
            deid, text,
            call={"jurisdiction": jurisdiction, "backend": backend, "method": method,
                  "statute": statute, "salt": salt},
        )
    return deid


__all__ = ["Deidentified", "JurisdictionRequiredError", "METHODS", "deidentify", "detect_pii"]
