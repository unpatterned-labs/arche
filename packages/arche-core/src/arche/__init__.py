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

Quickstart (v0.2, PRD §10.1)::

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

Per-country detectors (PRD §6.1)::

    from arche.detect.ng.ids import detect_nigerian_ids
    from arche.detect.za.ids import detect_south_african_ids
    from arche.detect.ng.phones import normalize_ng_phone, validate_ng_phone

Statute files (PRD §6.4)::

    from arche.policy import load_statute, apply_policy, list_available_statutes
    statute = load_statute("NDPA-2023")  # or POPIA, KENYA-DPA, GHANA-DPA

Migration from v0.1: the legacy ``resolve()`` function still works through
the callable-module shim on ``arche.resolve`` (forwarding to
``arche.workflow.pipeline.resolve``). ``Pipeline.process()`` is the v0.2
replacement and the recommended path for new code. The v0.1 surface is
removed in v0.3.
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
# v0.1 surface (lazy — PEP 562 __getattr__)
# ---------------------------------------------------------------------------
# The v0.1 names below remain importable as ``from arche import <name>`` for
# backward compatibility through the v0.2.x series. They are loaded on first
# access instead of at ``import arche`` time so that:
#
#   1. ``import arche`` stays silent (no DeprecationWarnings emitted by
#      transitive shim modules: signal, enrich, audit, pipeline, etc.).
#   2. Cold-import time is minimised — PRD NFR-PERF-1 target <1000 ms.
#   3. The v0.2 ``__all__`` discipline is honoured: IDE auto-complete and
#      ``from arche import *`` surface only the framework primitives.
#
# Each entry maps an exposed name to (submodule, attribute_name).

_LAZY: dict[str, tuple[str, str]] = {
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
    "extract_text": (".workflow._ingest", "extract_text"),
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
    # Retargeted to .workflow._review (real location); see note above.
    "ReviewCandidate": (".workflow._review", "ReviewCandidate"),
    "ReviewQueue": (".workflow._review", "ReviewQueue"),
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
    "JurisdictionProfile": (".types", "JurisdictionProfile"),
    "MatchDecision": (".types", "MatchDecision"),
    "SensitiveSpan": (".types", "SensitiveSpan"),
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
# __all__: the recommended v0.2 PRD §10.1 surface.
# ---------------------------------------------------------------------------
# The v0.1 names listed in ``_LAZY`` above remain importable for backward
# compatibility but are intentionally absent from ``__all__`` so
# ``from arche import *`` and IDE auto-complete favour the v0.2 framework
# primitive. The v0.1 surface is removed in v0.3.
__all__ = [
    # PRD §10.1 — the v0.2 framework primitive
    "Pipeline",
    "Result",
    "Detection",
    # Level 2 API kept in __all__ because it's the workhorse path
    "detect",
    "match",
    "link",
    "resolve",
    # v0.2.0a2 — places (spec §5 + §16.3)
    "resolve_places",
    "list_places",
    # Versioning
    "__version__",
]
