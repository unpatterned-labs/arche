# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Which categories a statute governs that no configured detector can find.

The gap this closes
-------------------
A statute pack and a detector set are chosen independently, and nothing
compared them. So this was possible::

    EgressGuard(Pipeline(jurisdiction="GB"), key=...).guarded(
        "Jane Smith lives in Manchester, SW1A 1AA, tel 07700 900123.")

    -> redacted_text identical to the input, fields == [], statute UK-GDPR

Four fail-closed teeth, all satisfied, and the personal data went to the model
anyway. The teeth check **boundary conditions** — is there a policy, is the
provider allowed, is the transfer permitted, did anything raise. None of them
asks the prior question: *could this pipeline have found the thing the statute
told it to protect?*

For a non-African jurisdiction the answer is often no. `_default_detectors`
deliberately runs cross-cutting detectors only outside Africa, because an
African ID regex would confidently mislabel a foreign identifier. That is the
right call and it is documented at the point it happens. What was missing is
that the *result* looked identical to a clean document. Zero findings meant
either "nothing here" or "nothing here that anything installed can see", and no
caller could tell which.

What this module answers, and what it does not
----------------------------------------------
It compares two exactly-known sets: the categories a statute maps, and the
categories the configured detector packages can emit. It reports the difference.

**It is about capability, not recall.** `covered` means a detector for that
category ran, not that it found everything. A name detector calibrated on West
African names runs for `GB` and reports `PII-1-NAME` as covered, and it will
still miss names it does not know. Category coverage is a floor on honesty, not
a guarantee of completeness, and describing it as more than that would repeat
the mistake it exists to fix.

Why it is derived rather than declared
--------------------------------------
The per-country category lists come from the detector packages' own pattern
tables (`NG_PATTERNS` and its siblings), through the same
``PII-2-{id_type}`` construction the pipeline uses. A hand-written list would
drift the first time somebody added an identifier, and drifting the wrong way
here means silently claiming coverage that does not exist.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover
    from arche.workflow._primitive import Pipeline

# Categories the cross-cutting detector packages emit. Small, stable, and
# checked against reality by `test_coverage.py`, which probes each package and
# fails if one emits a category not claimed here.
CROSS_CUTTING_CATEGORIES: dict[str, frozenset[str]] = {
    "names": frozenset({"PII-1-NAME"}),
    "emails": frozenset({"PII-3-EMAIL"}),
    "locations": frozenset({"PII-4-LOCATION"}),
    "addr": frozenset({"PII-4-ADDRESS"}),
    "ip": frozenset({"PII-8-IP_ADDRESS"}),
    "digital_id": frozenset({"PII-2-DID", "PII-5-CRYPTO_WALLET"}),
    "core": frozenset({"PII-3-PHONE"}),
    "phones": frozenset({"PII-3-PHONE"}),
}

# Country ID packs, and where each keeps its pattern table. The categories are
# read out of these tables rather than listed here.
_COUNTRY_ID_PACKS: dict[str, tuple[str, str]] = {
    "ng": ("arche.detect.ng.ids", "NG_PATTERNS"),
    "ke": ("arche.detect.ke.ids", "KE_PATTERNS"),
    "za": ("arche.detect.za.ids", "ZA_PATTERNS"),
    "gh": ("arche.detect.gh.ids", "GH_PATTERNS"),
}

#: The multi-country pack is the union of the per-country ones.
_AFRICA_PACK = "africa"


def _country_categories(pack: str) -> frozenset[str]:
    """Read one country pack's categories out of its own pattern table.

    Mirrors the pipeline's own construction: an entry's ``id_type`` becomes
    ``PII-2-{id_type}``. Returns empty rather than raising when the module is
    not importable, because a coverage report that crashes is worse than one
    that under-claims — and under-claiming is the safe direction.
    """
    import importlib

    module_name, table_name = _COUNTRY_ID_PACKS[pack]
    try:
        table = getattr(importlib.import_module(module_name), table_name, None)
    except ImportError:  # pragma: no cover - depends on install extras
        return frozenset()
    if not isinstance(table, dict):  # pragma: no cover - defensive
        return frozenset()
    return frozenset(
        f"PII-2-{spec['id_type']}"
        for spec in table.values()
        if isinstance(spec, dict) and spec.get("id_type")
    )


def detectable_categories(packages: list[str] | tuple[str, ...]) -> set[str]:
    """Every PII category the given detector packages are able to emit.

    An unknown package contributes nothing rather than raising. A caller who
    passes their own detector through ``Pipeline(detectors=[...])`` will see its
    categories reported as uncovered, which is the honest answer: this module
    cannot know what somebody else's detector emits.
    """
    found: set[str] = set()
    for pack in packages:
        if pack in CROSS_CUTTING_CATEGORIES:
            found |= CROSS_CUTTING_CATEGORIES[pack]
        elif pack in _COUNTRY_ID_PACKS:
            found |= _country_categories(pack)
        elif pack == _AFRICA_PACK:
            for country in _COUNTRY_ID_PACKS:
                found |= _country_categories(country)
    return found


def coverage(pipeline: Pipeline) -> dict[str, Any]:
    """What the statute governs, what the detectors can find, and the gap.

    Returns a dict with:

    ``verdict``
        ``"full"`` when every category the statute maps has a detector,
        ``"none"`` when not one does, ``"partial"`` in between, and
        ``"no-statute"`` when no policy is configured at all.

        Expect ``"partial"`` to be the normal answer, including for Nigeria.
        NDPA-2023 governs health, religion, biometric and device categories that
        arche ships no detector for. Saying so is the point.

    ``uncovered``
        The categories to worry about: the statute names them, nothing
        installed can find them. For ``GB`` this includes ``PII-2-NIN``, which
        is precisely the case that motivated this module.

    ``detector_packages``
        What actually ran, so a reader can see *why* — for a non-African
        jurisdiction this is the cross-cutting set with no national ID pack.
    """
    statute = pipeline._ensure_statute()
    # The packages that will actually RUN, not the ones requested. Reading
    # the requested list reported Nigerian ID categories as detectable for a
    # British pipeline that had already discarded that pack.
    packages = list(pipeline.effective_detectors())
    detectable = detectable_categories(packages)

    if statute is None:
        return {
            "verdict": "no-statute",
            "statute_id": None,
            "jurisdiction": getattr(pipeline, "jurisdiction", None),
            "detector_packages": packages,
            "detectable_categories": sorted(detectable),
            "governed": [],
            "covered": [],
            "uncovered": [],
            "note": "no statute configured, so nothing is governed and there is "
                    "nothing to be covered or uncovered",
        }

    governed = set(statute.policy_mappings)
    covered = governed & detectable
    uncovered = governed - detectable
    verdict = ("full" if not uncovered
               else "none" if not covered
               else "partial")

    return {
        "verdict": verdict,
        "statute_id": statute.statute_id,
        "jurisdiction": getattr(pipeline, "jurisdiction", None),
        "detector_packages": packages,
        "detectable_categories": sorted(detectable),
        "governed": sorted(governed),
        "covered": sorted(covered),
        "uncovered": sorted(uncovered),
        "note": _note(verdict, statute.statute_id, sorted(uncovered)),
    }


def _note(verdict: str, statute_id: str, uncovered: list[str]) -> str:
    """One sentence a person can act on, not a status word."""
    if verdict == "full":
        return (f"every category {statute_id} governs has a detector installed. "
                "This is about capability, not recall: a detector that ran may "
                "still have missed something.")
    if verdict == "none":
        return (f"no detector installed can find anything {statute_id} governs. "
                "A clean result from this pipeline means nothing was looked for.")
    shown = ", ".join(uncovered[:4])
    more = f" and {len(uncovered) - 4} more" if len(uncovered) > 4 else ""
    return (f"{len(uncovered)} categor{'y' if len(uncovered) == 1 else 'ies'} "
            f"{statute_id} governs ha{'s' if len(uncovered) == 1 else 've'} no "
            f"detector installed: {shown}{more}. A clean result does not mean "
            "those are absent, only that nothing looked for them.")


__all__ = ["CROSS_CUTTING_CATEGORIES", "coverage", "detectable_categories"]
