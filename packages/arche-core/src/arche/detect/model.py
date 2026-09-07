# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""A model proposes personal data; the statute decides what it means.

``Pipeline`` runs rule-based detector packages: checksummed identifiers, phone
prefixes, email syntax, a name lexicon. Those find what has a shape. A name
the lexicon has never seen, an address written as prose, a date of birth in
a sentence -- those need a model, and this module is where one runs.

The model is GLiNER2-PII (Fastino, Apache-2.0; ``arche-core[detect2]``): 42
personal-data labels, seven European languages, character-level spans. It is
used as a **proposer** and nothing more:

* its labels are mapped onto arche's ``PII-*`` categories, so the statute pack
  assigns the action and the citation exactly as it does for a rule detection;
* a proposal that overlaps a rule detection loses to it, except that a whole
  name proposed by the model absorbs the per-token names the lexicon emits --
  the lexicon says *Adesola* and *Okonkwo*, the model says *Adesola Okonkwo*,
  and one span over the name is the right shape for a redaction;
* labels arche has no category for are dropped here and named in
  :data:`UNMAPPED`, rather than invented into a category the statute has
  never heard of.

Nothing here is required. ``backend="basic"`` never imports this module and a
missing install under ``backend="auto"`` runs the rules alone and says so.
"""

from __future__ import annotations

import warnings
from collections.abc import Sequence

from arche.workflow._primitive import Detection

#: Detection backends a ``Pipeline`` understands. ``regex`` is an alias of
#: ``basic``; ``auto`` is ``gliner2-pii`` when installed and ``basic`` otherwise.
PIPELINE_BACKENDS: tuple[str, ...] = ("basic", "auto", "gliner2-pii")

#: GLiNER2-PII label -> arche category. The model's vocabulary is wider than
#: this; see :data:`UNMAPPED` for what is asked for but not carried through.
CATEGORY_FOR_LABEL: dict[str, str] = {
    "person": "PII-1-NAME", "full_name": "PII-1-NAME", "first_name": "PII-1-NAME",
    "middle_name": "PII-1-NAME", "last_name": "PII-1-NAME",
    "email": "PII-3-EMAIL",
    "phone_number": "PII-3-PHONE",
    "address": "PII-4-ADDRESS", "street_address": "PII-4-ADDRESS",
    "city": "PII-4-LOCATION", "state_or_region": "PII-4-LOCATION",
    "postal_code": "PII-4-LOCATION", "country": "PII-4-LOCATION",
    "date_of_birth": "PII-1-DOB",
    "government_id": "PII-2-NATIONAL_ID", "national_id_number": "PII-2-NATIONAL_ID",
    "passport_number": "PII-2-PASSPORT",
    "drivers_license_number": "PII-2-DRIVERS_LICENCE", "license_number": "PII-2-DRIVERS_LICENCE",
    "tax_id": "PII-2-TIN", "tax_number": "PII-2-TIN",
    "bank_account": "PII-5-BANK_ACCOUNT", "iban": "PII-5-BANK_ACCOUNT",
    "account_number": "PII-5-BANK_ACCOUNT", "routing_number": "PII-5-BANK_ACCOUNT",
    "payment_card": "PII-5-CARD", "card_number": "PII-5-CARD",
    "card_expiry": "PII-5-CARD", "card_cvv": "PII-5-CARD",
    "ip_address": "PII-8-IP_ADDRESS",
    "password": "PII-8-PASSWORD", "secret": "PII-8-PASSWORD", "api_key": "PII-8-PASSWORD",
    "access_token": "PII-8-PASSWORD", "recovery_code": "PII-8-PASSWORD",
}

#: Labels the model knows that arche deliberately does not turn into a
#: detection: usernames and account ids are identifiers of an account, not of
#: a person, and the date labels other than date of birth are not personal
#: data on their own. Listed so the omission is a decision, not an oversight.
UNMAPPED: tuple[str, ...] = (
    "username", "account_id", "sensitive_account_id",
    "sensitive_date", "document_date", "expiration_date", "transaction_date",
)

#: What the model is actually asked for. Deliberately the coarse labels: asked
#: for `person`, `first_name`, `last_name` and `full_name` together the model
#: returns all four over one name at lower confidence each (0.76 for the whole
#: name against 0.97 when asked for `person` alone, measured on the same
#: sentence), and `street_address` + `city` split an address the statute
#: treats as one span. Every label here has a category above; the finer labels
#: stay mapped so a caller who asks for them gets a category too.
LABELS_ASKED: tuple[str, ...] = (
    "person", "email", "phone_number", "address", "date_of_birth",
    "national_id_number", "passport_number", "drivers_license_number", "tax_id",
    "bank_account", "iban", "payment_card", "ip_address", "password",
)

_LABELS = list(LABELS_ASKED)


def resolve_backend(backend: str) -> str:
    """``regex`` -> ``basic``; reject anything a ``Pipeline`` cannot run."""
    from arche.extract import canonical_backend

    backend = canonical_backend(backend)
    if backend not in PIPELINE_BACKENDS:
        hint = ""
        if backend == "gliner2":
            hint = (" 'gliner2' is the general extractor behind arche.extract(); "
                    "for personal data the proposer is 'gliner2-pii'.")
        elif backend == "gliner":
            hint = " GLiNER v1 was removed in 0.9.0; 'gliner2-pii' is its replacement."
        raise ValueError(
            f"unknown detection backend {backend!r}; use one of "
            f"{', '.join(repr(b) for b in PIPELINE_BACKENDS)} ('regex' is accepted "
            f"for 'basic').{hint}"
        )
    return backend


def propose_pii(text: str, *, backend: str = "auto") -> tuple[list[Detection], str | None]:
    """Model-proposed personal data in ``text``, as unenriched detections.

    Returns ``(detections, model)``. ``model`` names the checkpoint that ran,
    or is ``None`` when nothing did -- ``basic``, or ``auto`` without the
    extra installed (a warning says so, once per process). An explicit
    ``gliner2-pii`` without the extra raises, naming it.
    """
    backend = resolve_backend(backend)
    if backend == "basic":
        return [], None
    try:
        from arche._models import get_gliner2  # noqa: F401  -- the install check
        from arche.config import get_config
        from arche.detect._gliner2 import propose

        cfg = get_config()
        spans = propose(text, _LABELS, model=cfg.gliner2_pii_model,
                        threshold=cfg.gliner2_pii_threshold)
        model = cfg.gliner2_pii_model
    except ImportError:
        if backend == "gliner2-pii":
            raise
        _warn_once()
        return [], None
    detections: list[Detection] = []
    for s in spans:
        category = CATEGORY_FOR_LABEL.get(s.label)
        if category is None or s.end <= s.start:
            continue
        detections.append(Detection(
            id=f"det:model:{s.label}:{s.start}:{s.end}",
            category=category,
            text=s.text,
            start=s.start,
            end=s.end,
            confidence=s.confidence,
            detector=f"model:{model}",
            identity_class="inferred",
            metadata={"label": s.label, "model": model},
        ))
    return detections, model


_warned = False


def _warn_once() -> None:
    global _warned
    if _warned:
        return
    _warned = True
    warnings.warn(
        "backend='auto' ran the basic detectors only: GLiNER2-PII is not installed, "
        "so names the lexicon does not hold and prose addresses were not proposed. "
        "Install it with: pip install 'arche-core[detect2]'",
        UserWarning,
        stacklevel=4,
    )


def merge(rules: Sequence[Detection], proposals: Sequence[Detection]) -> list[Detection]:
    """Rule detections plus the model proposals that do not contradict them.

    A proposal overlapping a validated detection is dropped -- the checksum
    outranks the model. The one exception is a name: a NAME span that overlaps
    only NAME spans keeps the **widest**, because a whole name and its parts
    are one finding at different granularities and the whole is the right one
    for a redaction. That rule also settles the model against itself, when it
    answers `person` and `last_name` over the same words.
    """
    kept = list(rules)
    for p in sorted(proposals, key=lambda d: (d.start, -d.end)):
        clashing = [r for r in kept if p.start < r.end and r.start < p.end]
        if not clashing:
            kept.append(p)
        elif p.category == "PII-1-NAME" and all(r.category == "PII-1-NAME" for r in clashing):
            widest = max(clashing, key=lambda r: r.end - r.start)
            if p.end - p.start > widest.end - widest.start:
                kept = [r for r in kept if r not in clashing]
                kept.append(p)
    kept.sort(key=lambda d: (d.start, d.end))
    return kept
