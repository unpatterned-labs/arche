# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""arche — the identity workflow framework.

African-first, globally pluggable. Compose detection, resolution, linking,
verification, and governance into production identity pipelines.

Lifecycle (five user-facing steps)::

    Detect   →   Resolve   →   Link        →   Verify              →   Govern
    arche.       arche.        arche-          arche.sign +            arche.policy +
    detect       resolve       adapters        arche.credentials       arche.graph.audit
                               (v0.2.0a2:
                                arche.link)


    from arche import Pipeline

    pipeline = Pipeline(
        jurisdiction="NG",
        statute="NDPA-2023",
    )
    result = pipeline.process(
        "Customer Adesola Okonkwo, NIN 12345678901, phone 0803 555 7890."
    )
    print(result.redacted_text)
    # -> "Customer NAME_..., NIN [NIN], phone PHONE_..."

    from arche.detect.ng.ids import detect_nigerian_ids
    from arche.detect.za.ids import detect_south_african_ids
    from arche.detect.ng.phones import normalize_ng_phone, validate_ng_phone

    from arche.policy import load_statute, apply_policy, list_available_statutes
    statute = load_statute("NDPA-2023")  # or POPIA, KENYA-DPA, GHANA-DPA

Migration from v0.1: the legacy callable-module shim ``arche.resolve(text)``
is removed as of v0.3.0a1 — ``Pipeline.process()`` is the replacement, and
``arche.resolve`` is purely the facade package (``resolve.compare``,
``resolve.reconcile``). Other v0.1 names remain importable through the 0.3
line as a deprecated surface; their removal is targeted for v0.4.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# v0.2.0a2 — places surface (eager)
# ---------------------------------------------------------------------------
# Added 2026-05-24 per docs/ceo-plans/2026-05-24-places-resolver.md §5 + §16.3.
# Eager because these are v0.2 primitives (no DeprecationWarning to defer).
from typing import TYPE_CHECKING

from ._version import __version__

# ---------------------------------------------------------------------------
# v0.2 PRD §10.1 surface (eager — the recommended public API)
# ---------------------------------------------------------------------------
from .workflow import Detection, Pipeline, Result

if TYPE_CHECKING:
    from .resolve.places import PlaceResolver


def resolve_places(
    text: str,
    jurisdiction: str | None = None,
    *,
    resolver: PlaceResolver | None = None,
):
    """Resolve nearby places from a free-text query under jurisdictional law.

    Returns a typed :class:`PlaceReport` with places, compliance block,
    workflow trace, and ``save_receipt()`` for verifiable JWS audit.

    Example::

        from arche import resolve_places

        report = resolve_places(
            "My mum lives near St Thomas' Hospital in SW1 — find her a dentist."
        )
        for place in report.places:
            print(place.name, place.distance_m, "m away")
        report.save_receipt("audit.jws")

    If ``jurisdiction`` is None, it's inferred from the text (UK postcodes,
    country names, etc.). Raises :class:`JurisdictionInferenceError` if no
    jurisdiction can be inferred — never silently defaults.

    v0.1 ships with FIXTURES only by default. Set ``DEMO_LIVE_API=true`` env
    to enable live OSM/NHS/openchargemap calls (stub in v0.1 — see spec §4.4).
    """
    from .resolve.places import _run_anchored
    return _run_anchored(text=text, jurisdiction=jurisdiction, resolver=resolver)


def list_places(
    category: str,
    jurisdiction: str = "GB",
    *,
    near: str | None = None,
    limit: int = 50,
    cursor: str | None = None,
    resolver: PlaceResolver | None = None,
):
    """Directory query: list every instance of `category` in `jurisdiction`.

    Returns a typed :class:`PlaceDirectoryReport` with paginated results,
    same compliance + trace shape as :func:`resolve_places`.

    Example::

        from arche import list_places

        report = list_places(category="physiotherapy", jurisdiction="GB")
        for clinic in report.results:
            print(clinic.name, clinic.address)
        if report.next_cursor:
            more = list_places("physiotherapy", cursor=report.next_cursor)

    Supported categories in v0.1: physiotherapy, dentist, ev_charger.
    """
    from .resolve.places import _run_directory
    return _run_directory(
        category=category, jurisdiction=jurisdiction,
        near=near, limit=limit, cursor=cursor, resolver=resolver,
    )

# ---------------------------------------------------------------------------
# Lazily-loaded surface (PEP 562 __getattr__)
# ---------------------------------------------------------------------------
# `_LAZY` does ONE job: defer an import until the name is first touched. It is
# not a deprecation list, and the comment here used to say it was — which made
# "old, going away in v0.4" and "current, just not imported yet" impossible to
# tell apart from the outside. Thirteen names sat in `_LAZY` *and* in
# `__all__`, so the package simultaneously recommended them and described them
# as scheduled for removal, while emitting no warning either way.
#
# The two jobs are now separate:
#
#   `_LAZY`        name -> (submodule, attribute). Deferred import. Says
#                  nothing about whether the name is going away.
#   `_DEPRECATED`  name -> what to use instead. Emits DeprecationWarning on
#                  first access, once, naming the replacement.
#
# A name may be in both (deferred AND superseded), but a name in `_DEPRECATED`
# must NOT be in `__all__` — recommending what you are deleting is the defect
# this split exists to prevent, and `tests/test_public_surface.py` enforces it.
#
# Names are loaded on first access rather than at ``import arche`` time so that:
#
#   1. ``import arche`` stays silent (no DeprecationWarnings emitted by
#      transitive shim modules: signal, enrich, audit, pipeline, etc.).
#   2. Cold-import time is minimised — PRD NFR-PERF-1 target <1000 ms.
#   3. The v0.2 ``__all__`` discipline is honoured: IDE auto-complete and
#      ``from arche import *`` surface only the framework primitives.
#
# Each entry maps an exposed name to (submodule, attribute_name).

_LAZY: dict[str, tuple[str, str]] = {
    # --- vNext runtime -----------------------------------------------------
    # The runtime module itself remains dependency-light; DuckDB loads only
    # when attach() is called, preserving the base package cold-import budget.
    "attach": (".runtime", "attach"),
    # --- audit (v0.1 in-memory; v0.2 SQLite lives at arche.graph.audit) ----
    "AuditEntry": (".audit", "AuditEntry"),
    "AuditLog": (".audit", "AuditLog"),
    "get_audit_log": (".audit", "get_audit_log"),
    # --- config -----------------------------------------------------------
    "configure": (".config", "configure"),
    "get_config": (".config", "get_config"),
    # --- ensemble ---------------------------------------------------------
    "detect_sensitive_spans": (".ensemble", "detect_sensitive_spans"),
    "extract_identity_evidence": (".ensemble", "extract_identity_evidence"),
    "format_tagged_text": (".ensemble", "format_tagged_text"),
    # --- extract / ingest -------------------------------------------------
    "Entity": (".extract", "Entity"),
    "extract": (".extract", "extract"),
    "extract_places": (".addr.roles", "extract_places"),
    "extract_text": (".workflow._ingest", "extract_text"),
    # Additive canonical vocabulary. ``Entity`` above stays the *reference*
    # (mention) for back-compat; the canonical *resolved* Entity is reached
    # via ``from arche.canonical import Entity`` and is intentionally NOT
    # exported here as ``Entity`` so it never clobbers ``extract.Entity``.
    "EntityReference": (".canonical", "EntityReference"),
    "Attribute": (".canonical", "Attribute"),
    "IdentityAttribute": (".canonical", "IdentityAttribute"),
    "ProvenanceCitation": (".canonical", "ProvenanceCitation"),
    # --- llm + locate -----------------------------------------------------
    "LLMConfig": (".llm", "LLMConfig"),
    "Location": (".locate", "Location"),
    "locate": (".locate", "locate"),
    # --- models (v2 pydantic surface) -------------------------------------
    "IdentityEvidenceModel": (".models", "IdentityEvidenceModel"),
    "IdentityRecordModel": (".models", "IdentityRecordModel"),
    "JurisdictionProfileModel": (".models", "JurisdictionProfileModel"),
    "MatchDecisionModel": (".models", "MatchDecisionModel"),
    "SensitiveSpanModel": (".models", "SensitiveSpanModel"),
    # --- match ------------------------------------------------------------
    # Resolves to the real module (.resolve._matcher). The legacy
    # `arche.match` deprecation shim was removed; `from arche import match`
    # and friends route here directly.
    "IdentityMatcher": (".resolve._matcher", "IdentityMatcher"),
    "JurisdictionPriors": (".resolve._matcher", "JurisdictionPriors"),
    "MatchScore": (".resolve._matcher", "MatchScore"),
    "match": (".resolve._matcher", "match"),
    "to_match_record": (".resolve._matcher", "to_match_record"),
    "compare_geo": (".resolve._matcher", "compare_geo"),
    "normalize_type_token": (".resolve._matcher", "normalize_type_token"),
    "load_type_vocab": (".resolve._matcher", "load_type_vocab"),
    "split_place_name": (".resolve._matcher", "split_place_name"),
    "resolve_documents": (".doc._documents", "resolve_documents"),
    "DocumentReport": (".doc._documents", "DocumentReport"),
    "read_metadata": (".doc._metadata", "read_metadata"),
    "compare_place_qualifiers": (".resolve._matcher", "compare_place_qualifiers"),
    # --- pipeline (v0.1 callables) ----------------------------------------
    # Retargeted to .workflow.pipeline (real location); see note above.
    # NOTE: `resolve_fhir` was removed in v0.2.0a3 along with the
    # arche-adapters package — no FHIR surface in arche-core anymore.
    "ArchePipeline": (".workflow.pipeline", "ArchePipeline"),
    "IdentityGraph": (".workflow.pipeline", "IdentityGraph"),
    "ResolutionResult": (".workflow.pipeline", "ResolutionResult"),
    "detect": (".workflow.pipeline", "detect"),
    "link": (".workflow.pipeline", "link"),
    # --- relate -----------------------------------------------------------
    # Resolves to the real module (.resolve._relate); the .relate shim was
    # removed.
    "EntityRelationship": (".resolve._relate", "EntityRelationship"),
    "IdentityCluster": (".resolve._relate", "IdentityCluster"),
    "extract_relationships": (".resolve._relate", "extract_relationships"),
    "group_by_identity": (".resolve._relate", "group_by_identity"),
    # --- protect ----------------------------------------------------------
    "PIIDetection": (".protect", "PIIDetection"),
    "detect_pii": (".protect", "detect_pii"),
    "redact": (".protect", "redact"),
    # --- resolve (also a callable package via _CallableResolveModule) -----
    "ResolvedEntity": (".resolve", "ResolvedEntity"),
    "resolve_entities": (".resolve", "resolve_entities"),
    "resolve_identity_records": (".resolve", "resolve_identity_records"),
    # --- review -----------------------------------------------------------
    # ReviewQueue/ReviewCandidate removed from the public surface in v0.2.0a2.
    # The MPI human-review workflow is internal v0.1 plumbing with no v0.2
    # consumer (no README, demo/, api/, or web/ usage). Still importable from
    # the canonical location: ``from arche.workflow._review import ReviewQueue``.
    # --- visualize --------------------------------------------------------
    # Resolves to the real module (.workflow._format); the .visualize shim
    # was removed.
    "evidence_to_csv": (".workflow._format", "evidence_to_csv"),
    "evidence_to_html": (".workflow._format", "evidence_to_html"),
    "format_evidence_table": (".workflow._format", "format_evidence_table"),
    "format_summary": (".workflow._format", "format_summary"),
    "format_table": (".workflow._format", "format_table"),
    "print_table": (".workflow._format", "print_table"),
    "to_csv": (".workflow._format", "to_csv"),
    "to_dot": (".workflow._format", "to_dot"),
    "to_graph_html": (".workflow._format", "to_graph_html"),
    "to_html": (".workflow._format", "to_html"),
    # --- types ------------------------------------------------------------
    "IdentityEvidence": (".types", "IdentityEvidence"),
    "IdentityRecord": (".types", "IdentityRecord"),
    # --- the tightened vocabulary -------------------------------------
    "Receipt": (".resolve.coreference", "Receipt"),
    "CoReferenceDecision": (".resolve.coreference", "Receipt"),
    "compare": (".resolve", "compare"),
    "reconcile": (".resolve", "reconcile"),
    "dedupe": (".resolve", "dedupe"),
    "find": (".resolve", "find"),
    "describe": (".resolve", "describe"),
    "report": (".report", "report"),
    "JurisdictionProfile": (".types", "JurisdictionProfile"),
    "MatchDecision": (".types", "MatchDecision"),
    "SensitiveSpan": (".types", "SensitiveSpan"),
}


#: Superseded names, each pointing at what replaced it.
#:
#: Deliberately small. A name earns a line here only when a replacement exists
#: and has been checked to do the same job — `arche.match` is NOT listed, for
#: example, because it resolves to ``arche.resolve._matcher.match``, a
#: different engine from ``arche.resolve.compare``, and telling people to swap
#: one for the other before that is verified would be worse than saying
#: nothing. An empty line here is honest; a guessed one is not.
_DEPRECATED: dict[str, str] = {
    "CoReferenceDecision": "arche.resolve.coreference.Receipt",
}


def __getattr__(name: str):
    """PEP 562 lazy attribute access for the v0.1 backward-compat surface.

    The v0.1 shim modules (signal, enrich, audit, pipeline, ...) emit
    ``DeprecationWarning`` on import. Lazy-loading them defers those
    warnings to first-use, so ``import arche`` itself remains silent.
    """
    target = _LAZY.get(name)
    if target is None:
        raise AttributeError(f"module 'arche' has no attribute {name!r}")
    if name in _DEPRECATED:
        import warnings

        # Once per name, not once per access: the value is cached into
        # globals() below, so __getattr__ does not run again for it.
        warnings.warn(
            f"arche.{name} is superseded by {_DEPRECATED[name]}; it still "
            "works and will be removed in a future release",
            DeprecationWarning,
            stacklevel=2,
        )
    from importlib import import_module

    module = import_module(target[0], package=__name__)
    value = getattr(module, target[1])
    # Cache on the package module so subsequent accesses skip __getattr__.
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    """Expose v0.1 names via auto-complete without forcing their import."""
    return sorted(set(globals()) | _LAZY.keys())


# ---------------------------------------------------------------------------
# __all__: the recommended public API 
# ---------------------------------------------------------------------------
# The v0.1 names listed in ``_LAZY`` above remain importable for backward
# compatibility but are intentionally absent from ``__all__`` so
# ``from arche import *`` and IDE auto-complete favour the v0.2 framework
# primitive. Removal of the remaining v0.1 names is targeted for v0.4; the
# only v0.3 removal is the ``arche.resolve()`` callable shim (2026-08-07).
__all__ = [
    "attach",
    "Pipeline",
    # The pairwise question and what it hands back.
    "compare",
    "reconcile",
    "dedupe",
    "find",
    "describe",
    "report",
    "Receipt",
    "Result",
    "Detection",
    "detect",
    "match",
    "to_match_record",
    "compare_geo",
    "normalize_type_token",
    "load_type_vocab",
    "split_place_name",
    "compare_place_qualifiers",
    "resolve_documents",
    "DocumentReport",
    "read_metadata",
    "link",
    "resolve",
    "resolve_places",
    "list_places",
    # v0.3.0a1 — spatial role labeling (place-lane-v0.1)
    "extract_places",
    # Versioning
    "__version__",
]
