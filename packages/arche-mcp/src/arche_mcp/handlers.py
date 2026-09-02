# Copyright 2026 unpatterned.org
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Tool logic for the arche MCP server — pure functions, no MCP dependency.

Kept separate from ``server.py`` (the FastMCP registration) so the guarantees
below are unit-testable without an MCP client. Every handler returns plain
dicts and **never echoes raw PII**: detections return offsets (the caller
already has the text), ``guarded_scan`` returns hashed IDs, comparisons return
ids and numeric evidence.

Three things changed when this moved into the arche repository, and each was a
condition of publishing rather than a tidy-up.

**``compare_files`` is gone.** It took two agent-supplied filesystem paths, read
them, and wrote an HTML report to a third agent-supplied path — defaulting to
overwriting ``arche-report.html`` beside the caller's input. MCP has no
capability or consent model for filesystem writes, so an agent-callable
arbitrary local read-and-write is exactly the primitive a server should not
offer. The filesystem-touching twin already exists in the right place: the
``arche compare`` CLI, where a person sees the command before it runs.

**No private imports.** This module used to reach into ``arche.cli._load_records``
and ``arche.resolve._matcher.compare_names``. Publishing freezes whatever you
import, and a version pin does not help because a *patch* release can rename a
private name. Both now have public homes.

**Nothing is silent.** ``guarded_scan`` returns a coverage block, and
``plan_protection`` exists so an agent can read it *before* committing a
document. A guard that finds nothing because no detector was installed for the
jurisdiction looks exactly like a clean document, and that is the failure this
surface most needs not to reproduce.
"""

from __future__ import annotations

from typing import Any

from arche.coverage import coverage as _coverage
from arche.extract import extract
from arche.guard import EgressGuard, GuardDenied
from arche.jurisdictions.infer import infer_jurisdiction as _infer_jurisdiction
from arche.policy import statute_for as _statute_for
from arche.resolve import ENTITY_PACKS, compare_names, reconcile
from arche.resolve import describe_pack as _describe_pack
from arche.resolve import describe_packs as _describe_packs
from arche.resolve import would_resolve as _would_resolve
from arche.workflow._primitive import Pipeline

#: Bands for `check_name_equivalence`, matching arche's decision vocabulary.
#: A bare boolean at a fixed threshold has no abstention, which is the shape
#: this project refuses everywhere else.
_MATCH_AT = 0.85
_REVIEW_AT = 0.70


# ── orientation ──────────────────────────────────────────────────────────────

def capabilities() -> dict[str, Any]:
    """What this installation can actually do.

    Exists so an agent does not have to discover a missing optional dependency
    by calling a tool and reading an exception. Cheap, pure, and the honest
    first call in any flow.
    """
    import importlib

    from arche.jurisdictions.infer import _SIGNALS
    from arche.policy import STATUTE_FOR_JURISDICTION, list_available_statutes

    def _installed(module: str) -> bool:
        """Actually import it.

        `importlib.util.find_spec` was the first attempt and it is the wrong
        question: it answers "is there a module here", not "does it work".
        A half-installed dependency whose own imports fail is findable and
        unusable, and this reported it as available — a capabilities call that
        overstates is the same failure as a coverage report that overstates,
        one layer out.

        Costs an import on first call. Worth it: the whole point of this tool
        is that an agent should not have to discover a broken extra by calling
        something else and reading a traceback.
        """
        try:
            importlib.import_module(module)
        except Exception:  # noqa: BLE001 — any failure means unusable
            return False
        return True

    return {
        "arche_core_version": _core_version(),
        "statutes_available": sorted(list_available_statutes()),
        "jurisdictions_with_a_statute": sorted(set(STATUTE_FOR_JURISDICTION)),
        "jurisdictions_inferable": sorted({c for _n, _t, c, _p in _SIGNALS}),
        "entity_packs": sorted(ENTITY_PACKS),
        "extras": {
            # `detect_entities` finds identifiers without this and no names.
            "detect": _installed("gliner"),
            # `compare_records` can use a Splink backend when present.
            "splink": _installed("splink"),
            # Document parsing for anything that is not plain text. Asks the
            # doc lane rather than the dependency, because `arche.doc` is the
            # thing that has to be able to use it and it already publishes the
            # answer.
            "doc": _doc_available(),
        },
    }


def _doc_available() -> bool:
    from arche.doc import DOC_FEATURE_AVAILABLE

    return bool(DOC_FEATURE_AVAILABLE)


def _core_version() -> str:
    from arche import _version
    return getattr(_version, "__version__", "unknown")


def infer_jurisdiction(text: str, *, min_confidence: float = 0.6,
                       min_margin: float = 0.15) -> dict[str, Any]:
    """Work out which jurisdiction governs a document, from evidence in it.

    The reason this tool exists rather than an ``ARCHE_JURISDICTION`` setting:
    a configured jurisdiction is the operator's guess, applied to every
    document alike. Inferring it makes the answer a property of the document,
    which is the only version that works on a mixed stream.

    Returns the proposal, the evidence behind it, **and whether a statute
    actually governs the result**. That last part is not decoration. Without it
    an agent receives ``country="US", confidence=1.0, abstained=false``, calls
    ``guarded_scan``, and is refused for having no statute — which reads as a
    bug rather than as the designed boundary it is.

    Abstains rather than guessing. An abstention is an answer: it means nothing
    in the document said where it came from.
    """
    inferred = _infer_jurisdiction(
        text, min_confidence=min_confidence, min_margin=min_margin)
    choice = _statute_for(inferred.country)
    return {
        "country": inferred.country,
        "confidence": round(float(inferred.confidence), 4),
        "margin": round(float(inferred.margin), 4),
        "runner_up": inferred.runner_up,
        "abstained": inferred.abstained,
        "reason": inferred.reason,
        "ruleset_version": inferred.ruleset_version,
        # Evidence samples can be a registration identifier, so the signal name
        # and count travel and the matched text does not.
        "evidence": [
            {"signal": e.signal, "tier": e.tier, "country": e.country,
             "count": e.count, "weight": e.weight, "source": e.source}
            for e in inferred.evidence
        ],
        "statute_id": choice.statute_id,
        "policy_available": choice.available,
        "policy_reason": choice.reason,
        "policy_alternatives": list(choice.alternatives),
    }


def plan_protection(*, jurisdiction: str | None = None,
                    statute: str | None = None) -> dict[str, Any]:
    """What this pipeline could and could not find, before you hand it anything.

    The tool that makes ``guarded_scan`` safe to act on. Coverage is otherwise
    only visible *after* a document has been processed, which is too late to
    decide whether processing it was a good idea.

    Read ``verdict`` and ``degraded_categories`` together. ``partial`` is the
    normal answer — including for Nigeria, where NDPA-2023 governs health,
    religion and biometric categories arche ships no detector for — so
    ``partial`` alone is not a reason to stop. ``degraded_categories`` is the
    sharper signal: a detector ran and was built for somewhere else.
    """
    return _coverage(Pipeline(jurisdiction=jurisdiction, statute=statute))


def describe_pack(entity: str) -> dict[str, Any]:
    """Which record fields an entity pack reads, and what it does with each.

    An agent mapping its own columns onto arche's needs this, because a field
    the pack does not name is **ignored, not rejected**: no error, no warning,
    no effect on the score. Silent and correct, and impossible to debug from
    the outside.
    """
    return _describe_pack(entity)


def describe_packs() -> dict[str, Any]:
    """Every entity pack, described. For choosing one."""
    return _describe_packs()


# ── detection ────────────────────────────────────────────────────────────────

def detect_pii(text: str, *, jurisdiction: str | None = None,
               statute: str | None = None) -> dict[str, Any]:
    """PII spans as offsets + category + legal citation + tier. No raw values.

    Carries the same coverage block ``guarded_scan`` does, because ``count: 0``
    is otherwise ambiguous between "this document is clean" and "nothing
    installed here can read this kind of document".
    """
    pipeline = Pipeline(jurisdiction=jurisdiction, statute=statute)
    result = pipeline.process(text)
    return {
        "detections": [
            {
                "category": d.category,
                "start": d.start,
                "end": d.end,
                "confidence": round(d.confidence, 4),
                "citation": d.regulatory_citation,
                "tier": getattr(d.sensitivity_tier, "value", None),
            }
            for d in result.detections
        ],
        "count": len(result.detections),
        "coverage": _coverage(pipeline),
    }


def detect_entities(text: str, *, entity_types: list[str] | None = None) -> dict[str, Any]:
    """Named entities (NER) as typed offset spans. No raw text echoed.

    Needs a NER backend (``arche-mcp[detect]``). Without one this finds
    identifiers by pattern and no personal names at all, so check
    ``capabilities()["extras"]["detect"]`` before trusting an empty result.
    """
    ents = extract(text, entity_types=entity_types)
    return {
        "entities": [
            {
                "type": e.entity_type,
                "start": e.start,
                "end": e.end,
                "confidence": round(e.confidence, 4),
                "source": e.source,
            }
            for e in ents
        ],
        "count": len(ents),
        "ner_backend_installed": capabilities()["extras"]["detect"],
    }


# ── guarded egress ───────────────────────────────────────────────────────────

def guarded_scan(text: str, *, key: str | bytes, jurisdiction: str | None = None,
                 statute: str | None = None, provider: str | None = None,
                 crosses_border: bool = False,
                 allowed_providers: list[str] | None = None,
                 transfer_basis: str | None = None) -> dict[str, Any]:
    """Fail-closed projection: redacted text + hashed IDs + citations, never raw PII.

    The flagship. Five teeth, all deny by default: no policy, disallowed
    provider, undeclared cross-border transfer, any exception, and no detector
    capable of finding anything the statute governs.

    **Read ``coverage`` even when ``denied`` is false.** A clean result from a
    pipeline with no detector for the locale is indistinguishable from a clean
    document, and this is the field that tells the two apart.

    The hashed token is stable for the same value across calls, so an agent can
    correlate an entity across documents without this server remembering
    anything between them.
    """
    if not key:
        return {
            "denied": True,
            "reason": "no hash key configured, so tokens could not be stable "
                      "and the guard refuses rather than inventing one "
                      "(set ARCHE_HASH_KEY)",
            "citation": None,
        }
    pipeline = Pipeline(jurisdiction=jurisdiction, statute=statute)
    guard = EgressGuard(
        pipeline,
        key=key, allowed_providers=allowed_providers, transfer_basis=transfer_basis,
    )
    try:
        proj = guard.guarded(text, provider=provider, crosses_border=crosses_border)
    except GuardDenied as exc:
        return {"denied": True, "reason": exc.reason, "citation": exc.citation,
                "coverage": _coverage(pipeline)}
    return {
        "denied": False,
        "redacted_text": proj.redacted_text,
        "fields": [
            {"category": f.category, "action": f.action, "token": f.token,
             "citation": f.citation, "tier": f.tier}
            for f in proj.fields
        ],
        "metadata": proj.metadata,
        "coverage": proj.coverage,
        # Offsets into `redacted_text` do NOT match offsets from `detect_pii` or
        # `extract_places`, which index the original. Replacement tokens differ
        # in length from what they replace. Slicing one with the other returns
        # the wrong span, and a shifted window can expose an adjacent value.
        "offsets_match_original": False,
    }


# ── resolution / comparison ──────────────────────────────────────────────────

def compare_records(list_a: list[dict], list_b: list[dict], *,
                    comparators: list[dict] | None = None,
                    entity: str | None = None,
                    backend: str | None = None,
                    threshold: float = 0.7,
                    review_margin: float = 0.15, id_field: str = "id",
                    distinctive_kinds: tuple[str, ...] = ("name", "id"),
                    distinctive_floor: float = 0.75) -> dict[str, Any]:
    """Reconcile two record lists. Ids and numeric evidence only, never raw PII.

    The safest tool in this set: pure in, pure out, no filesystem, no state.

    Pass ``entity`` to use a shipped pack (call ``describe_pack`` to see what it
    reads), or ``comparators`` to specify the comparison yourself::

        [{"field": "name", "kind": "name", "weight": 2.0},
         {"kind": "geo", "lat": "lat", "lon": "lon", "weight": 1.0}]

    Returns matches ``{a_id, b_id, score, decision, evidence, distinctive_max}``.
    A ``review`` decision is a real answer and usually the interesting one: it
    means the records agree without agreeing on anything distinctive.
    """
    if entity and comparators:
        raise ValueError(
            "pass entity= or comparators=, not both: they specify the same "
            "thing and one would silently win")
    if entity:
        if entity not in ENTITY_PACKS:
            raise ValueError(
                f"unknown entity pack {entity!r}; "
                f"available: {', '.join(sorted(ENTITY_PACKS))}")
        # `crosswalk`, not `reconcile`, and the difference is load-bearing.
        # Entity packs contain `tftoken` comparators, which price how ordinary
        # a shared word is and therefore need a frequency table. `reconcile`
        # does not build one and raises; `crosswalk` self-calibrates it over
        # the two lists being linked. Handing the pack straight to `reconcile`
        # looked right and failed on every pack that weighs rarity, which is
        # all of them.
        #
        # It also means an `entity=` call and a `comparators=` call differ in
        # more than convenience: `crosswalk` applies blocking defaults and a
        # self-calibrated `tf`, so the same pair can score differently in
        # different batches. That is a property of the engine, not of this
        # wrapper, and the pins in the result record which table was used.
        extra = {}
        if backend:
            # Splink refuses to run without a configuration, deliberately: a
            # match probability is a posterior whose scale moves with the
            # corpus, so there is no portable default. `derive` builds one from
            # the pack, warns that it is best-effort, and is the only way an
            # agent can reach the backend without writing Splink by hand.
            extra = {"backend": backend, "splink_settings": "derive"}
        return reconcile(
            list_a, list_b, entity=entity, id_field=id_field,
            threshold=threshold, review_margin=review_margin,
            distinctive_floor=distinctive_floor, **extra,
        )
    if not comparators:
        raise ValueError("pass entity= or comparators= to say how to compare")
    return reconcile(
        list_a, list_b, comparators,
        threshold=threshold, review_margin=review_margin, id_field=id_field,
        distinctive_kinds=distinctive_kinds, distinctive_floor=distinctive_floor,
        block=None,
    )


def why_unresolved(record_a: dict, record_b: dict, *,
                   entity: str) -> dict[str, Any]:
    """Why this pair was not resolved, and which field would resolve it.

    Call this after ``compare_records`` returns ``review``. That verdict says
    the evidence was insufficient; it does not say what would be sufficient,
    and without that an agent can only escalate or guess.

    Returns the gate that held the pair, the fields the pack could have read
    and did not receive -- ranked by what supplying them could achieve -- and
    the fields already present that cannot help however much they agree.

    Read ``will_not_help`` before retrying. When a pair is held by low
    distinctiveness, fetching a longer or cleaner version of the *same* field
    cannot rescue it: rarity is a fact about the population, so a better
    rendering of ``General Hospital`` is still ``General Hospital``.

    Effects, strongest first:

      hard_constraint     supplying it can cap the decision at review on its own
      decisive_for        an exact identifier; agreement here settles the pair
      can_prevent_match   disagreement holds the pair at review
      independent_signal  adds evidence without deciding anything alone

    No effect means "refutes". arche declines to assert sameness and never
    asserts difference, so nothing here promises a ``no_match``.

    Takes the two records rather than an edge, so one call answers the
    question. The pair is re-scored internally with the same pack.
    """
    if entity not in ENTITY_PACKS:
        raise ValueError(
            f"unknown entity pack {entity!r}; "
            f"available: {', '.join(sorted(ENTITY_PACKS))}")

    a = {"id": "a", **record_a}
    b = {"id": "b", **record_b}
    edges = reconcile([a], [b], entity=entity, id_field="id")["matches"]
    if not edges:
        return {
            "decision": "not_surfaced",
            "why": "the pair was not surfaced as a candidate at all, so there "
                   "is no verdict to explain. That is not a statement that the "
                   "records differ",
            "fields_present": [], "would_resolve": [], "will_not_help": [],
        }
    return _would_resolve(edges[0], a, b, entity=entity)


def check_name_equivalence(name_a: str, name_b: str) -> dict[str, Any]:
    """Are two names the same person's, African-name-aware?

    Returns a decision band rather than a boolean. A bare ``equivalent: true``
    at a fixed threshold has no way to say "close, and not close enough to
    assert", which is exactly the state most interesting pairs are in, and
    abstention is the vocabulary this project uses everywhere else.
    """
    similarity, _u = compare_names(name_a, name_b)
    decision = ("match" if similarity >= _MATCH_AT
                else "review" if similarity >= _REVIEW_AT
                else "no_match")
    return {
        "decision": decision,
        "score": round(similarity, 4),
        "bands": {"match": _MATCH_AT, "review": _REVIEW_AT},
    }


# ── places ───────────────────────────────────────────────────────────────────

def extract_places(text: str) -> dict:
    """Spatial role labeling over free text — offsets only, never address text.

    An address is personal data (arche's PII taxonomy lists street_address and
    postcode), so this surface returns spans, roles, canonical cue phrases from
    the shipped pack vocabulary, and component NAMES — the caller holds the
    source text and slices the offsets. No reveal option exists on this path.

    Offsets index the ORIGINAL text, not ``guarded_scan``'s redacted output.
    """
    from arche.addr.roles import extract_places as _extract
    from arche.addr.roles import load_role_pack

    mentions = _extract(text)
    return {
        "places": [m.to_dict(reveal=False) for m in mentions],
        "count": len(mentions),
        "pack": load_role_pack().pin,
        "offsets_match_original": True,
    }
