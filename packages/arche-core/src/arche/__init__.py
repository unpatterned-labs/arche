"""arche -- are these the same thing?

Four verbs answer the pairwise question over records, text and documents --
``compare``, ``reconcile``, ``dedupe``, ``find`` -- and ``resolve_documents``
asks it of a folder of files. ``attach`` opens a ledger so a decision can be
looked up, explained and replayed by its ``decision_id``::

    import arche

    ledger = arche.attach("duckdb:///decisions.duckdb")
    receipt = arche.compare(text_a, text_b, entity="person", jurisdiction="NG",
                            backend="regex", store=ledger)
    ledger.explain(receipt.decision_id)

``Pipeline`` is the detection primitive underneath: detectors, a statute and
the redaction it requires::

    from arche import Pipeline

    result = Pipeline(jurisdiction="NG").process(
        "Customer Adesola Okonkwo, NIN 12345678901, phone 0803 555 7890."
    )
    print(result.redacted_text)

The v0.1 surface (``ArchePipeline``, ``resolve_entities``, ``detect_pii``,
``locate``, the in-memory audit log, ``arche.graph``, ``arche.attest`` and the
SD-JWT credentials) was removed in 0.8.0; the changelog lists every name.
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
# surface (eager — the recommended public API)
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
    # --- ledger -------------------------------------------------------------
    # DuckDB loads only when attach() is called, so `import arche` stays within
    # its cold-import budget.
    "attach": (".ledger", "attach"),
    "Ledger": (".ledger", "Ledger"),
    # --- config -----------------------------------------------------------
    "configure": (".config", "configure"),
    "get_config": (".config", "get_config"),
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
    # --- llm --------------------------------------------------------------
    "LLMConfig": (".llm", "LLMConfig"),
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
    # --- the tightened vocabulary -------------------------------------
    "Receipt": (".resolve.coreference", "Receipt"),
    "CoReferenceDecision": (".resolve.coreference", "Receipt"),
    "compare": (".resolve", "compare"),
    "reconcile": (".resolve", "reconcile"),
    "dedupe": (".resolve", "dedupe"),
    "find": (".resolve", "find"),
    "describe": (".resolve", "describe"),
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
    """PEP 562 lazy attribute access.

    Every name in ``_LAZY`` imports on first use so that ``import arche``
    stays inside its cold-import budget; a ``_DEPRECATED`` name warns once.
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
    """Expose the lazy names to auto-complete without forcing their import."""
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
    "resolve",
    "resolve_places",
    "list_places",
    # v0.3.0a1 — spatial role labeling (place-lane-v0.1)
    "extract_places",
    # Versioning
    "__version__",
]
