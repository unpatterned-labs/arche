# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""The package must not recommend and delete the same name.

``_LAZY`` used to do two jobs at once. Its comment described it as "the v0.1
surface ... removal targeted for v0.4", but most of what sat in it was current
API placed there for deferred import speed. The two states were
indistinguishable from outside, and thirteen names were in ``_LAZY`` *and*
``__all__`` at the same time -- recommended by autocomplete and by
``from arche import *``, described in the source as scheduled for deletion, and
emitting no warning either way. A caller following the curated list was being
pointed at names the package intended to remove.

The jobs are now separate. ``_LAZY`` defers an import and claims nothing about
a name's future; ``_DEPRECATED`` names a replacement and warns once. The tests
below hold the line between them, because the failure they prevent is one that
reappears every time somebody adds a name in a hurry.
"""

from __future__ import annotations

import importlib
import warnings

import pytest

import arche
from arche import _DEPRECATED, _LAZY

def _uncached(name: str):
    """Access ``arche.<name>`` with the PEP 562 cache cleared first.

    ``__getattr__`` writes each resolved name into ``arche.__dict__`` so later
    accesses skip it -- which is what makes the warning fire once rather than
    on every attribute access. ``importlib.reload`` does NOT undo that:
    reload re-executes the module body into the *existing* dict, so a name
    another test already touched stays cached and ``__getattr__`` never runs.
    Popping the name is the only thing that actually restores first-access
    conditions, and a test that skips this passes alone and silently stops
    guarding anything once the suite grows.
    """
    arche.__dict__.pop(name, None)
    return getattr(arche, name)


# ---------------------------------------------------------------------------
# The invariant
# ---------------------------------------------------------------------------


def test_nothing_is_recommended_and_deprecated_at_once():
    overlap = sorted(set(arche.__all__) & set(_DEPRECATED))
    assert not overlap, (
        f"{overlap} are in __all__ (recommended to every caller, surfaced by "
        "IDE autocomplete and `from arche import *`) and in _DEPRECATED "
        "(scheduled for removal) simultaneously. Pick one: if the name is "
        "going away, take it out of __all__; if it is staying, take it out of "
        "_DEPRECATED."
    )


def test_every_deprecation_names_its_replacement():
    for name, replacement in _DEPRECATED.items():
        assert replacement and isinstance(replacement, str), (
            f"{name} is marked deprecated with no replacement. A warning that "
            "does not say what to use instead just moves the problem to the "
            "caller."
        )


def test_every_deprecated_name_is_still_reachable():
    # Deprecated means "we would rather you did not", never "it broke".
    for name in _DEPRECATED:
        assert getattr(arche, name, None) is not None


def test_the_named_replacements_actually_resolve():
    # A replacement that does not import is worse than no advice: the caller
    # follows it, hits an ImportError, and trusts the next warning less.
    for name, target in _DEPRECATED.items():
        module_path, _, attribute = target.rpartition(".")
        module = importlib.import_module(module_path)
        assert hasattr(module, attribute), (
            f"{name} points at {target}, which does not exist"
        )


# ---------------------------------------------------------------------------
# The warning behaves
# ---------------------------------------------------------------------------


def test_a_deprecated_name_warns_and_names_the_replacement():
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        _uncached("CoReferenceDecision")
    messages = [str(w.message) for w in caught
                if issubclass(w.category, DeprecationWarning)]
    assert messages, "no DeprecationWarning raised"
    assert "arche.resolve.coreference.Receipt" in messages[0]


def test_a_current_lazy_name_stays_silent():
    # The whole point of the split. `extract_places` is in `_LAZY` for import
    # speed and is current, recommended API; warning on it would train callers
    # to filter DeprecationWarnings, which is how a real deprecation gets
    # missed later.
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        _uncached("extract_places")
    assert not [w for w in caught
                if issubclass(w.category, DeprecationWarning)]


def test_importing_arche_is_silent():
    # `import arche` must not warn, or every downstream test suite that runs
    # with -W error::DeprecationWarning fails on the import line.
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        importlib.reload(arche)
    assert not [w for w in caught
                if issubclass(w.category, DeprecationWarning)]


# ---------------------------------------------------------------------------
# The tightened vocabulary is reachable
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name", ["attach", "compare", "reconcile", "dedupe", "Receipt"]
)
def test_the_new_names_are_exported_and_recommended(name):
    assert hasattr(arche, name)
    assert name in arche.__all__
    assert name in _LAZY


def test_receipt_and_its_old_spelling_are_one_class():
    # A plain alias, not a subclass: `isinstance` written against either
    # spelling has to keep agreeing, in caller code we cannot see.
    from arche.resolve.coreference import CoReferenceDecision, Receipt

    assert Receipt is CoReferenceDecision
    assert Receipt.__name__ == "Receipt"


def test_the_rename_did_not_reach_the_wire_format():
    # The guarantee from `test_receipt_schema.py`, asserted from the other
    # side: renaming a Python class must not move a decision address. Stated
    # here too because this is the file somebody edits when adding a name, and
    # it is the moment the mistake would be made.
    decision = arche.compare("Adebayo Oluwaseun", "Adebayo Oluwaseun")
    assert type(decision).__name__ == "Receipt"
    assert decision.decision_id.startswith("dec:sha256:")


def test_the_four_verbs_are_the_surface():
    # One question each, and an agent picking between four named questions
    # picks correctly. Picking between eight overlapping ones -- `pairwise`,
    # `match`, `crosswalk`, `link`, `resolve_entities`, `resolve_places`,
    # `resolve_identity_records`, `group_by_identity` -- is what this branch
    # was for.
    import arche

    for verb in ("compare", "reconcile", "dedupe", "find"):
        assert callable(getattr(arche, verb)), f"{verb} is not callable"
        assert verb in arche.__all__, f"{verb} is not recommended"


def test_arche_extract_is_callable_whichever_way_it_resolved():
    # `arche.extract` is a module AND a verb. Importing any name out of the
    # submodule rebinds the package attribute from the lazily-resolved function
    # to the module object -- so without the callable-module shim, an unrelated
    # import elsewhere in the process makes `extract(text)` raise TypeError.
    # Two files in this suite trigger exactly that.
    import arche
    from arche.extract import Entity  # noqa: F401  -- the rebinding import

    assert callable(arche.extract)
    from arche import extract

    assert callable(extract)


# ---------------------------------------------------------------------------
# The ratchet
# ---------------------------------------------------------------------------

#: The curated surface, frozen. Not a maximum -- an exact set, so that ADDING a
#: name fails this test as loudly as removing one.
#:
#: That is the point. `__all__` is what IDE autocomplete offers and what
#: `from arche import *` binds, so a name landing in it by accident is how a
#: library ends up with eight ways to ask three questions. Changing this set is
#: allowed and expected; doing it without noticing is not.
_FROZEN_SURFACE = {
    # The vocabulary this branch settled: four questions, two conveniences,
    # the noun they hand back, and the pipeline primitives.
    "attach", "compare", "reconcile", "dedupe", "find", "describe",
    "Receipt", "Pipeline", "Result", "Detection", "DocumentReport",
    "__version__",
    # The place lane. Domain helpers rather than vocabulary -- they read as
    # what they are and none of them competes with the four verbs.
    "compare_geo", "compare_place_qualifiers", "extract_places", "list_places",
    "load_type_vocab", "normalize_type_token", "resolve_places",
    "split_place_name",
    # `match` resolves to arche.resolve._matcher.match -- a different engine
    # from `compare`, not an older spelling of it; it stays until someone runs
    # the comparison. `detect` and `resolve` are the subpackages.
    "detect", "match", "read_metadata", "resolve",
    "resolve_documents", "to_match_record",
}


def test_the_public_surface_is_exactly_what_we_chose():
    current = set(arche.__all__)
    added = sorted(current - _FROZEN_SURFACE)
    removed = sorted(_FROZEN_SURFACE - current)
    assert not added and not removed, (
        f"__all__ changed. Added: {added}. Removed: {removed}. This is the "
        "list IDE autocomplete offers and `from arche import *` binds, so a "
        "name arriving here by accident is how the surface drifts back. If "
        "the change is deliberate, update _FROZEN_SURFACE and say why."
    )


def test_the_four_verbs_do_not_have_rivals_in_the_surface():
    # The specific drift this guards: a fifth spelling of a question that
    # already has a verb. `pairwise` and `crosswalk` were exactly that, and
    # they are now deprecated rather than recommended.
    from arche.resolve import _DEPRECATED as resolve_deprecated

    assert not set(arche.__all__) & set(resolve_deprecated), (
        "a deprecated spelling is being recommended in __all__"
    )
