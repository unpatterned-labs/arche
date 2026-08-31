# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Co-reference decision core — resolve two references to one person.
This takes two :class:`~arche.canonical.Reference` records
(or two documents), decides whether they *co-refer*, and returns a
:class:`Receipt` whose :attr:`~Receipt.decision_id` is a
reproducible, keyless address of the decision.

The method:

* **Score** with Fellegi-Sunter (the matcher's ``compare_*`` functions and per
  jurisdiction m/u), **round-before-sum (C2):** every field similarity is rounded
  to 4dp *before* its log-odds contribution is recomputed and summed, so the
  signed decision is a pure function of the rounded evidence vector.
* **Gate** with the distinctive-signal rule (C4): a merge is only permitted when
  a genuinely distinctive signal clears — an exact strong identifier
  (national_id / phone / email), agreement on a *rare* name token, or DOB+name
  jointly. A high fuzzy-name similarity on *common* tokens does **not** clear the
  gate. This is why two records both named "Ibrahim Musa" land at ``review``.
* **Veto** on a hard identifier conflict: two different national IDs -> ``different``.

The reproducibility guarantee holds **from ``Reference`` onward** (H2):
:func:`coref_references` is deterministic; :func:`coref_documents` adds a
GliNER/regex extraction hop that is *provenance, not reproduction* — the document
content ids are recorded in ``pins["provenance"]`` but are **not** part of
``decision_id``.

Note on the distinctive gate (C4, one deliberate refinement of the literal
spec): :meth:`~TokenFrequencyTable.weighted_token_sim` is a self-normalising
Jaccard and returns ``1.0`` for two *identical* names — common or not — so a bare
``weighted_token_sim >= floor`` test would clear on a shared common name, exactly
the failure C4 warns about. The name-token clause therefore requires **both** a
high ``name_tf_sim`` **and** that a genuinely *distinctive* token be shared
(``distinctiveness >= floor``). That is what "agreement on a genuinely rare name
token" (plan §4) means operationally, and it makes the §4 worked example land at
``review``.
"""

from __future__ import annotations

import importlib
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from arche import ids
from arche.resolve._matcher import (
    JurisdictionPriors,
    _log_odds,
    _log_odds_to_probability,
    compare_addresses,
    compare_dates,
    compare_emails,
    compare_geo,
    compare_ids,
    compare_names,
    compare_phones,
    get_priors,
)
from arche.resolve._tokenfreq import TokenFrequencyTable

if TYPE_CHECKING:
    from arche.canonical import Reference
    
from arche.resolve._gate import (  # noqa: E402
    DISTINCTIVE_FLOOR as _DISTINCTIVE_FLOOR,
)
from arche.resolve._gate import (  # noqa: E402
    shared_name_distinctiveness as _shared_name_distinctiveness_impl,
)

# Canonical Reference attribute names -> the matcher's record fields. First value
# per target field wins (spec §5.1 "_reference_to_match_record").
_FIELD_MAP: dict[str, str] = {
    "full_name": "name",
    "name": "name",
    "phone": "phone",
    "phone_number": "phone",
    "national_id": "national_id",
    "nin": "national_id",
    # PERSON-id attributes from the detection bridge (canonical
    # PERSON_ID_CATEGORIES) also feed the matcher's id comparator. Non-person
    # ids (rc, tin, kra_pin, did, ...) are deliberately ABSENT: a company
    # registration number must never enter person-identity matching.
    "bvn": "national_id",
    "pvc": "national_id",
    "drivers_licence": "national_id",
    "ghana_card": "national_id",
    "passport": "national_id",
    "sa_id": "national_id",
    "kenya_id": "national_id",
    "nid": "national_id",
    "nida": "national_id",
    "cni": "national_id",
    "cnie": "national_id",
    "bi": "national_id",
    "kebele_id": "national_id",
    "ssnit": "national_id",
    "nhif": "national_id",
    "email": "email",
    "address": "address",
    "date": "dob",
    "dob": "dob",
    "date_of_birth": "dob",
    "lat": "lat",
    "lon": "lon",
}

# Fixed field order so the non-associative float sum is reproducible (H1).
_ORDERED_FIELDS: tuple[str, ...] = (
    "name", "phone", "national_id", "email", "address", "dob", "geo",
)

# Non-name, non-geo comparators (name returns its own u; geo needs lat/lon).
_COMPARATORS: dict[str, Callable[[Any, Any], float]] = {
    "phone": compare_phones,
    "national_id": compare_ids,
    "email": compare_emails,
    "address": compare_addresses,
    "dob": compare_dates,
}



# ── record adaptation ────────────────────────────────────────────────────────
def _reference_to_match_record(ref: Reference, decl=None) -> dict[str, Any]:
    """Map a canonical :class:`Reference`'s attributes to matcher record fields.

    ``full_name``/``name`` -> ``name``; ``phone``/``phone_number`` -> ``phone``;
    ``national_id``/``nin`` -> ``national_id``; ``email`` -> ``email``;
    ``address`` -> ``address``; ``date``/``dob``/``date_of_birth`` -> ``dob``;
    plus ``lat``/``lon`` when present. The **first** value seen per target field
    is kept (a reference obeys the unique-reference assumption, but may carry
    several surface forms of one attribute).

    With ``decl`` (a user declaration), the slot is chosen by the *declared
    kind* instead of the field name — so a ``vessel_id`` declared ``kind: id``
    lands in the ``national_id`` slot and inherits the exact-identifier gate
    and conflict veto. The slot is a slot, not a claim about the data; the
    user's field names survive untouched on the Reference itself.
    """
    record: dict[str, Any] = {}
    for attr in ref.attributes:
        if decl is not None:
            if decl.geo and attr.name == decl.geo.get("lat"):
                record.setdefault("lat", attr.value)
                continue
            if decl.geo and attr.name == decl.geo.get("lon"):
                record.setdefault("lon", attr.value)
                continue
            field_name = decl.slot_for(attr.name) or _FIELD_MAP.get(attr.name)
        else:
            field_name = _FIELD_MAP.get(attr.name)
        if field_name and field_name not in record and attr.value:
            if field_name == "address" and getattr(attr, "components", None):
                # Preserve parsed-address structure (landmark anchor included) —
                # compare_addresses depends on it; a flat string round-trip
                # would lose the anchor.
                record[field_name] = {"text": attr.value, **attr.components}
            else:
                record[field_name] = attr.value
    return record


def _is_placeholder_dob(dob: str) -> bool:
    """True for a DOB that is a placeholder, not a real date (H4).

    ``01-01`` (month-day only), ``0000-00-00`` / all-zeros, a year-only value
    (``<= 4`` digits), or an empty/undated string are treated as **missing** —
    neither agreement nor conflict. A full date (``>= 6`` digits) is real.
    """
    digits = re.sub(r"[^0-9]", "", dob or "")
    if not digits:
        return True
    if set(digits) == {"0"}:
        return True
    return len(digits) <= 4


def _drop_placeholder_dob(record: dict[str, str]) -> dict[str, str]:
    """Return ``record`` with a placeholder ``dob`` removed (treated as missing)."""
    dob = record.get("dob")
    if dob is not None and _is_placeholder_dob(dob):
        record = dict(record)
        record.pop("dob", None)
    return record


# ── distinctiveness helpers — shared gate toolkit (resolve/_gate.py) ─────────
_shared_name_distinctiveness = _shared_name_distinctiveness_impl


# ── the canonical Fellegi-Sunter scorer (round-before-sum, C2) ───────────────
@dataclass
class _ScoreResult:
    score: float
    total_bits: float
    factors: dict[str, float]
    field_weights: dict[str, dict[str, float]]
    name_tf_sim: float | None
    name_tf_distinct: float
    applied_fields: int


def _has_geo(record: dict[str, str]) -> tuple[float, float] | None:
    """Parse ``(lat, lon)`` from a record, or ``None`` if absent/unparseable."""
    lat, lon = record.get("lat"), record.get("lon")
    if lat is None or lon is None:
        return None
    try:
        return float(lat), float(lon)
    except (TypeError, ValueError):
        return None


def _score(
    rec_a: dict[str, str],
    rec_b: dict[str, str],
    priors: JurisdictionPriors,
    tf: TokenFrequencyTable,
) -> _ScoreResult:
    """Score two match records with Fellegi-Sunter, **round-before-sum (C2)**.

    For each field present in *both* records: compute its similarity, round it to
    4dp, recompute the log-odds ``bits`` from the *rounded* similarity, and sum in
    a fixed field order (H1). ``score`` is the sigmoid of that sum. ``name_tf_sim``
    (distinctiveness-weighted token similarity) is computed separately for the
    gate; it is reported in ``factors`` but does not add to the log-odds sum.
    """
    factors: dict[str, float] = {}
    field_weights: dict[str, dict[str, float]] = {}
    total = 0.0
    applied = 0

    field_mu = {
        "phone": (priors.phone_m, priors.phone_u),
        "national_id": (priors.national_id_m, priors.national_id_u),
        "email": (priors.email_m, priors.email_u),
        "address": (priors.address_m, priors.address_u),
        "dob": (priors.dob_m, priors.dob_u),
    }

    for name in _ORDERED_FIELDS:
        if name == "name":
            a, b = rec_a.get("name"), rec_b.get("name")
            if not (a and b):
                continue
            sim, u = compare_names(a, b, priors)
            m = priors.name_m
        elif name == "geo":
            ga, gb = _has_geo(rec_a), _has_geo(rec_b)
            if ga is None or gb is None:
                continue
            sim = compare_geo(ga[0], ga[1], gb[0], gb[1])
            m, u = priors.geo_m, priors.geo_u
        else:
            a, b = rec_a.get(name), rec_b.get(name)
            if not (a and b):
                continue
            sim = _COMPARATORS[name](a, b)
            m, u = field_mu[name]

        rounded = round(sim, 4)
        bits = _log_odds(rounded, m, u)
        total += bits
        factors[name] = rounded
        field_weights[name] = {
            "sim": rounded, "m": m, "u": u, "bits": round(bits, 4),
        }
        applied += 1

    name_tf_sim: float | None = None
    name_tf_distinct = 0.0
    na, nb = rec_a.get("name"), rec_b.get("name")
    if na and nb:
        name_tf_sim = round(tf.weighted_token_sim(na, nb), 4)
        name_tf_distinct = _shared_name_distinctiveness(na, nb, tf)
        factors["name_tf"] = name_tf_sim

    score = _log_odds_to_probability(total)
    return _ScoreResult(
        score=score,
        total_bits=total,
        factors=factors,
        field_weights=field_weights,
        name_tf_sim=name_tf_sim,
        name_tf_distinct=name_tf_distinct,
        applied_fields=applied,
    )


# ── the decision ─────────────────────────────────────────────────────────────
@dataclass
class Receipt:
    """A signed-ready co-reference decision between two references.

    Carries the two-axis outcome (:attr:`identity` / :attr:`action`), the numeric
    evidence (:attr:`score` / :attr:`factors` / :attr:`field_weights`), the gate
    and veto reasoning, and the content-addressed ids. ``decision_id`` is a pure,
    keyless function of the *rounded* evidence + pinned versions — re-run the same
    references and it reproduces byte-for-byte.

    :attr:`reference_a` / :attr:`reference_b` are retained for later rendering and
    are deliberately **not** part of ``decision_id`` (it hashes only the two
    ``reference_id`` strings, not the PII-bearing objects). :attr:`entity_id` is a
    keyed HMAC pseudonym present only when a distinctive exact identifier is shared
    *and* an ``entity_key`` was supplied (Tier-1); it is ``None`` for fuzzy-only
    matches (H3).
    """

    identity: str            # same_entity | review | different
    action: str              # merge | hold | no_op
    basis: str
    score: float
    factors: dict[str, float]
    field_weights: dict[str, dict[str, float]]
    explanation: str
    gate: dict[str, Any]
    vetoes: dict[str, Any]
    reference_id_a: str
    reference_id_b: str
    decision_id: str
    entity_id: str | None
    reference_a: Reference
    reference_b: Reference
    jurisdiction: str
    pins: dict[str, Any]

    def __repr__(self) -> str:  # PII-free: never dump the reference objects
        return (
            f"Receipt(identity={self.identity!r}, "
            f"action={self.action!r}, score={self.score:.4f}, "
            f"decision_id={self.decision_id!r})"
        )


#: The name this class carried until the vocabulary was tightened. Named after
#: the linguistics term for the relation it encodes rather than after the thing
#: a caller is handed, which is the rule the surface now follows: nouns are
#: named for what you get back.
#:
#: Kept as a plain alias rather than a subclass, so ``isinstance`` checks
#: written against either spelling keep agreeing. Renaming the class does not
#: touch ``decision_id``: that hash is computed over the evidence keys and the
#: pins, and neither is a Python symbol -- see ``tests/test_receipt_schema.py``,
#: which freezes an id precisely so a rename that DID reach the wire format
#: could not pass unnoticed.
CoReferenceDecision = Receipt


def _engine_version() -> str:
    """``arche-core@<version>`` (or ``arche-core`` if the version is unavailable)."""
    try:
        import arche

        return f"arche-core@{arche.__version__}"
    except Exception:
        return "arche-core"


def _detect_comparator_lib() -> str:
    """The pinned string-similarity backend, ``name@version``.

    Mirrors the matcher's ``jellyfish -> rapidfuzz`` preference so the pin records
    the backend that actually produced the similarities (C1). Falls back to the
    built-in exact comparator when neither is installed.
    """
    for lib in ("jellyfish", "rapidfuzz"):
        try:
            mod = importlib.import_module(lib)
        except ImportError:
            continue
        return f"{lib}@{getattr(mod, '__version__', 'unknown')}"
    return "exact@builtin"


#: The version of the receipt's *field vocabulary* — the names of the keys in
#: ``factors``, ``gate`` and ``vetoes``, not the values in them.
#:
#: Why this exists, and why it is worth one deliberate break to add it.
#: ``decision_id`` is a content hash over those keys plus these pins, so
#: renaming a key silently invalidates every receipt ever issued: the id stops
#: re-deriving and a signature that verified yesterday does not verify today.
#: That is the single property this library sells, and until now nothing
#: recorded which vocabulary a given receipt was issued under.
#:
#: With the version pinned, a receipt says so itself. A future rename bumps
#: this to 2; receipts issued under 1 keep verifying under 1 forever, because
#: the rules they were issued under are named in the artifact rather than
#: implied by whatever code happens to be installed.
#:
#: Adding it changes every ``decision_id`` exactly once. That is the cost, it
#: is paid here, and ``tests/test_receipt_schema.py`` freezes a fixture id so
#: it can never be paid twice by accident.
RECEIPT_SCHEMA = 1


def _build_pins(jurisdiction: str, priors: JurisdictionPriors) -> dict[str, Any]:
    """The pinned-versions block hashed into ``decision_id`` (§5.1)."""
    return {
        "receipt_schema": RECEIPT_SCHEMA,
        "engine": _engine_version(),
        "comparator_lib": _detect_comparator_lib(),
        "jurisdiction": jurisdiction,
        "thresholds": {
            "match": priors.match_threshold,
            "review": priors.review_threshold,
            "distinctive_floor": _DISTINCTIVE_FLOOR,
        },
        "tf": "default",
    }


def _build_explanation(factors: dict[str, float]) -> str:
    """A human-readable summary of the agreeing fields."""
    parts: list[str] = []
    if factors.get("national_id", 0.0) >= 0.99:
        parts.append("national ID match")
    if factors.get("phone", 0.0) >= 0.99:
        parts.append("phone match")
    if factors.get("email", 0.0) >= 0.99:
        parts.append("email match")
    if factors.get("name", 0.0) >= 0.80:
        parts.append(f"name similarity {factors['name']:.0%}")
    if factors.get("address", 0.0) >= 0.60:
        parts.append(f"address similarity {factors['address']:.0%}")
    if factors.get("dob", 0.0) >= 0.99:
        parts.append("DOB match")
    if factors.get("geo", 0.0) >= 0.60:
        parts.append("nearby location")
    return "; ".join(parts) if parts else "no strong agreeing signals"


def _corroborated(factors: dict[str, float]) -> bool:
    """Is there a second signal corroborating a lone clearing identifier? (H4)

    A merge on a single exact identifier is only released when another field
    genuinely agrees: name (>= 0.7), address (>= 0.6), an exact DOB, or a *second*
    exact identifier.
    """
    if factors.get("name", 0.0) >= 0.70:
        return True
    if factors.get("address", 0.0) >= 0.60:
        return True
    if factors.get("dob", 0.0) >= 0.99:
        return True
    exact_ids = [f for f in ("national_id", "phone", "email") if factors.get(f, 0.0) >= 0.99]
    return len(exact_ids) >= 2


def _decide_action(
    identity: str, signals: list[str], factors: dict[str, float]
) -> tuple[str, str]:
    """Map identity + gate signals to an ``(action, basis)`` (plan §4, H4)."""
    if identity != "same_entity":
        return "no_op", ""
    only_single_id = len(signals) == 1 and signals[0] in ("national_id", "phone", "email")
    if only_single_id and not _corroborated(factors):
        return "hold", "single_identifier"
    return "merge", "corroborated"


def coref_references(
    ref_a: Reference,
    ref_b: Reference,
    *,
    jurisdiction: str = "default",
    issuer_key: bytes | None = None,
    extra_pins: dict[str, Any] | None = None,
    decl=None,
) -> Receipt:
    """Decide whether two structured references co-refer (deterministic path).

    The reproducible core: no extraction, no model, no timestamp. Given the same
    two references, priors, pinned backend (and ``issuer_key``), it returns the
    same ``decision_id`` byte-for-byte (§5.1, H2).

    Parameters
    ----------
    ref_a, ref_b:
        The two records to compare. Order is meaningful (``a`` = first document).
    jurisdiction:
        Selects the m/u priors and thresholds (``"NG"``, ``"GH"``, ...).
    issuer_key:
        The issuer's secret (>= 32 bytes). **Supply it for any decision that will
        be shared/attested**: it keys ``reference_id`` / ``decision_id`` (so the
        PII-derived ids can't be brute-forced back to the source records) and,
        when the two references share a distinctive exact identifier, mints the
        Tier-1 :attr:`~Receipt.entity_id`. Without a key the ids are
        keyless — reproducible locally, but pseudonymous personal data, not safe
        to share openly.
    """
    if decl is not None and jurisdiction == "default":
        jurisdiction = decl.jurisdiction
    priors = get_priors(jurisdiction)
    tf = TokenFrequencyTable.default()

    rec_a = _drop_placeholder_dob(_reference_to_match_record(ref_a, decl=decl))
    rec_b = _drop_placeholder_dob(_reference_to_match_record(ref_b, decl=decl))
    result = _score(rec_a, rec_b, priors, tf)
    factors = result.factors

    # ── distinctive-signal gate (C4): gate on the tf token, never a common name.
    signals: list[str] = []
    if factors.get("national_id", 0.0) >= 0.99:
        signals.append("national_id")
    if factors.get("phone", 0.0) >= 0.99:
        signals.append("phone")
    if factors.get("email", 0.0) >= 0.99:
        signals.append("email")
    if (
        result.name_tf_sim is not None
        and result.name_tf_sim >= _DISTINCTIVE_FLOOR
        and result.name_tf_distinct >= _DISTINCTIVE_FLOOR
    ):
        signals.append("tftoken")
    if factors.get("dob", 0.0) >= 0.99 and factors.get("name", 0.0) >= 0.85:
        signals.append("dob+name")
    cleared = bool(signals)
    gate = {
        "distinctive_cleared": cleared,
        "clearing_signal": signals[0] if signals else None,
        "floor": _DISTINCTIVE_FLOOR,
    }

    # ── vetoes: a hard identifier conflict is decisive; others stay soft (MVP).
    id_conflict = "national_id" in factors and factors["national_id"] < 0.99
    vetoes = {"id_conflict": id_conflict}

    # ── identity axis (epistemic claim).
    score = result.score
    if id_conflict:
        identity = "different"
    elif (
        score >= priors.match_threshold
        and cleared
        and result.applied_fields >= 2
    ):
        identity = "same_entity"
    elif score >= priors.review_threshold or (
        score >= priors.match_threshold and not cleared
    ):
        identity = "review"
    else:
        identity = "different"

    # ── action axis (operational recommendation).
    action, basis = _decide_action(identity, signals, factors)

    explanation = _build_explanation(factors)

    reference_id_a = ids.reference_id(ref_a, key=issuer_key)
    reference_id_b = ids.reference_id(ref_b, key=issuer_key)
    pins = _build_pins(jurisdiction, priors)
    if decl is not None:
        # The declaration is representation: it decided what these records
        # looked like when compared, so it belongs INSIDE the decision hash.
        # Same records under a different declaration => different decision_id.
        pins["declaration"] = decl.pin()
    if extra_pins:
        # Caller-supplied provenance (source jurisdictions, document content
        # ids) enters the pins BEFORE decision_id is computed — an attested
        # provenance claim must be inside the hash, not appended after it.
        pins.update(extra_pins)
    the_decision_id = ids.decision_id(
        reference_id_a=reference_id_a,
        reference_id_b=reference_id_b,
        decision=identity,
        factors=factors,
        gate=gate,
        vetoes=vetoes,
        jurisdiction=jurisdiction,
        pins=pins,
        key=issuer_key,
    )

    # ── entity_id: Tier-1 keyed pseudonym only when a distinctive exact
    # identifier is shared on BOTH references (never fuzzy-only, H3).
    entity_identifier: str | None = None
    binding_a = ids.identity_binding_key(ref_a)
    binding_b = ids.identity_binding_key(ref_b)
    if issuer_key and binding_a is not None and binding_a == binding_b:
        entity_identifier = ids.entity_id(binding_a, key=issuer_key)

    return Receipt(
        identity=identity,
        action=action,
        basis=basis,
        score=round(score, 4),
        factors=factors,
        field_weights=result.field_weights,
        explanation=explanation,
        gate=gate,
        vetoes=vetoes,
        reference_id_a=reference_id_a,
        reference_id_b=reference_id_b,
        decision_id=the_decision_id,
        entity_id=entity_identifier,
        reference_a=ref_a,
        reference_b=ref_b,
        jurisdiction=jurisdiction,
        pins=pins,
    )


def coref_documents(
    doc_a: str,
    doc_b: str,
    *,
    jurisdiction: str = "default",
    backend: str = "auto",
    source_a: str = "doc_a",
    source_b: str = "doc_b",
    issuer_key: bytes | None = None,
) -> Receipt:
    """Decide whether two *documents* mention the same person.

    Extracts each document into a :class:`Reference`, then delegates to
    :func:`coref_references`. The extraction hop (GliNER/regex/LLM) is
    **provenance, not reproduction** (H2): the two ``document_content_id`` values
    are recorded in ``pins["provenance"]`` but are **not** hashed into
    ``decision_id`` — the deterministic guarantee starts at ``Reference``.

    Parameters
    ----------
    doc_a, doc_b:
        The two source documents.
    backend:
        Extraction backend passed to :func:`arche.extract.extract`
        (``"auto"`` / ``"gliner"`` / ``"regex"`` / ``"auto+llm"``).
    source_a, source_b:
        ``source_system`` labels recorded on each assembled reference (they make
        the two ``reference_id`` values differ even for identical attributes).
    """
    from arche.canonical import Reference
    from arche.extract import extract

    mentions_a = extract(doc_a, backend=backend)
    mentions_b = extract(doc_b, backend=backend)
    ref_a = Reference.from_mentions(mentions_a, source_system=source_a)
    ref_b = Reference.from_mentions(mentions_b, source_system=source_b)

    # Document provenance rides INSIDE the hashed pins: an attested provenance
    # claim must be under the signature, not appended after it. Reproducibility
    # still holds Reference-onward (H2) — re-running the same documents through
    # the same extractor reproduces the same pins; a different extraction is,
    # correctly, a different decision.
    return coref_references(
        ref_a, ref_b, jurisdiction=jurisdiction, issuer_key=issuer_key,
        extra_pins={"provenance": {
            "document_content_id_a": ids.document_content_id(doc_a),
            "document_content_id_b": ids.document_content_id(doc_b),
            "backend": backend,
        }},
    )


def resolution_pipeline(jurisdiction: str | None = None, **pipeline_kwargs: Any):
    """A :class:`~arche.workflow.Pipeline` configured for RESOLUTION input.

    Identical to a normal Pipeline for the jurisdiction, plus the cross-cutting
    ``emails`` detector — email is a distinctive co-reference signal, and this
    factory is where the plan's "email default-on in the resolution path" lives
    (it is deliberately NOT in the plain-Pipeline defaults, which would change
    existing callers' outputs). Use it to produce the ``Result``s you feed to
    :func:`coref_from_pipeline` / ``resolve.compare``::

        pipe = resolution_pipeline("NG")
        decision = coref_from_pipeline(pipe.process(doc_a), pipe.process(doc_b))
    """
    from arche.workflow._primitive import Pipeline

    pipe = Pipeline(jurisdiction=jurisdiction, **pipeline_kwargs)
    if "emails" not in pipe.detector_packages:
        pipe.detector_packages = [*pipe.detector_packages, "emails"]
    return pipe


def coref_from_pipeline(
    result_a: Any,
    result_b: Any,
    *,
    jurisdiction: str | None = None,
    issuer_key: bytes | None = None,
    source_a: str = "pipeline_a",
    source_b: str = "pipeline_b",
) -> Receipt:
    """Decide co-reference between two Pipeline ``Result``s — the
    compliance-aware flagship path (recon plan §3.1/§3.2).

    Bridges each ``Result`` through :meth:`Reference.from_detections` (statute
    citations travel with the data; statute-``drop``ped values become
    ``restricted`` — usable for matching, never disclosable), then resolves.

    Jurisdiction contract: when the two results carry the SAME jurisdiction it
    is used for the priors; when they DISAGREE an explicit ``jurisdiction=`` is
    **required** (fail loudly — silently picking one side would mis-prior the
    match). Both source jurisdictions and both document content ids are recorded
    in ``pins`` *before* ``decision_id`` is computed.
    """
    from arche.canonical import Reference

    jur_a = (getattr(result_a, "metadata", None) or {}).get("jurisdiction")
    jur_b = (getattr(result_b, "metadata", None) or {}).get("jurisdiction")
    if jurisdiction is None:
        if jur_a != jur_b:
            raise ValueError(
                f"the two results carry different jurisdictions ({jur_a!r} vs "
                f"{jur_b!r}); pass an explicit jurisdiction= for scoring"
            )
        jurisdiction = jur_a or "default"

    ref_a = Reference.from_detections(result_a, source_system=source_a)
    ref_b = Reference.from_detections(result_b, source_system=source_b)
    return coref_references(
        ref_a, ref_b, jurisdiction=jurisdiction, issuer_key=issuer_key,
        extra_pins={"provenance": {
            "source_jurisdictions": [jur_a, jur_b],
            "document_hash_a": getattr(result_a, "document_hash", "") or "",
            "document_hash_b": getattr(result_b, "document_hash", "") or "",
            "path": "pipeline",
        }},
    )


__all__ = [
    "Receipt",
    "coref_references",
    "coref_documents",
    "coref_from_pipeline",
    "resolution_pipeline",
]
