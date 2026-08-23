# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""The three nouns in the place lane, and why they are not interchangeable.

`concepts/drafts/place-identity.md` states the model: *"A place reference is
not the place … `Karfi Health Post` and `Karfi Primary Health Centre` are two
references whose disagreement is history, not noise."*

`arche/resolve/places.py` contradicted it. A class called `PlaceEntity` held a
text span — a span, the text at it, a confidence, and nothing else. No identity,
no coordinates, no source. It was a *reference*, wearing the name of the thing
it refers to, and it was the first type a reader met when opening the place
lane. A name that teaches the opposite of the model is expensive, because
nobody reads the draft first.

Its sibling `PlaceRecord` had the opposite problem: the right name and a
docstring that said "a resolved place", which promises the facility itself. Its
fields say otherwise — `source` and `raw_redacted` exist precisely because this
is what *one registry* asserted, and two registries disagree about the same
facility routinely.

This file exists because that module had no tests at all, which is how a
documented public name and its own docstring drifted apart without anything
noticing.
"""

from __future__ import annotations

import warnings

import pytest


@pytest.fixture(autouse=True)
def _quiet():
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        yield


class TestTheNamesMatchWhatTheyHold:

    def test_a_reference_carries_no_identity(self):
        """The argument for the rename, as an assertion about the fields.

        If a `PlaceReference` ever gains an `id` or a `source`, it has stopped
        being a reference and this test should fail so somebody has to think
        about what it became.
        """
        from arche.resolve.places import PlaceReference
        fields = set(PlaceReference.__dataclass_fields__)
        assert fields == {"span", "text", "kind", "confidence"}
        assert not fields & {"id", "source", "coords", "address"}

    def test_a_record_carries_its_provenance(self):
        """The reason `PlaceRecord` keeps its name. It has a source, because it
        is one source's assertion — not the facility."""
        from arche.resolve.places import PlaceRecord
        fields = set(PlaceRecord.__dataclass_fields__)
        assert {"id", "source", "coords", "raw_redacted"} <= fields

    def test_there_is_no_place_type(self):
        """Deliberately absent. A `Place` promises a registry, and then
        `Karfi Health Post` -> `Karfi Primary Health Centre` becomes a merge
        conflict instead of an upgrade with a date."""
        from arche.resolve import places
        assert not hasattr(places, "Place")

    def test_detect_returns_references_not_entities(self):
        """The method that produces them says what they are."""
        from arche.resolve.places import PlaceReference, PlaceResolver
        found = PlaceResolver().detect(
            "find me a dentist near St Thomas' Hospital in SW1")
        assert found, "the fixture query should detect something"
        assert all(isinstance(x, PlaceReference) for x in found)


class TestTheOldNameStillWorks:
    """arche-core is on PyPI and `PlaceEntity` was the documented import.

    Removing it outright would break somebody's code to fix somebody else's
    confusion. It resolves, and it says why it should not be used.
    """

    def test_it_still_imports(self):
        from arche.resolve.places import PlaceEntity
        assert PlaceEntity is not None

    def test_it_is_the_same_class_not_a_copy(self):
        """An alias that drifted from its target would be worse than the
        original problem."""
        from arche.resolve.places import PlaceEntity, PlaceReference
        assert PlaceEntity is PlaceReference

    def test_it_warns(self):
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            from arche.resolve import places
            _ = places.PlaceEntity
        assert any(issubclass(w.category, DeprecationWarning) for w in caught)

    def test_the_warning_says_what_to_use_and_why(self):
        """A deprecation that only says "deprecated" makes the reader go
        looking. This one carries the reason and the replacement."""
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            from arche.resolve import places
            _ = places.PlaceEntity
        message = str(caught[0].message)
        assert "PlaceReference" in message
        assert "not an entity" in message
        assert "0.8.0" in message, "a deprecation with no horizon never ends"

    def test_it_is_not_advertised(self):
        """It resolves; it is not a name to reach for."""
        from arche.resolve import places
        assert "PlaceEntity" not in places.__all__
        assert "PlaceReference" in places.__all__

    def test_an_unknown_attribute_still_raises_normally(self):
        """Module `__getattr__` must not swallow real typos into something
        confusing."""
        from arche.resolve import places
        with pytest.raises(AttributeError, match="has no attribute"):
            _ = places.PlaceElephant


class TestTheDocstringsAgreeWithTheFields:
    """The specific failure being fixed: a name or a docstring saying one thing
    while the fields say another, with no test to notice."""

    def test_the_reference_docstring_does_not_call_it_an_entity(self):
        from arche.resolve.places import PlaceReference
        doc = PlaceReference.__doc__ or ""
        assert "reference to* a place, not the place" in doc

    def test_the_record_docstring_no_longer_claims_to_be_a_resolved_place(self):
        from arche.resolve.places import PlaceRecord
        doc = PlaceRecord.__doc__ or ""
        assert "One source's assertion" in doc
        assert "A resolved place." not in doc

    def test_the_module_docstring_teaches_the_three_nouns(self):
        from arche.resolve import places
        doc = places.__doc__ or ""
        for noun in ("PlaceReference", "PlaceRecord", "no Place type"):
            assert noun in doc, noun


def test_placemention_is_a_different_thing_and_keeps_its_name():
    """`arche.addr.roles.PlaceMention` is not this. It is a span that
    additionally carries a spatial role and the cue that decided it, which is
    why the rename went to `reference` rather than colliding on `mention`.
    """
    from arche.addr.roles import PlaceMention
    from arche.resolve.places import PlaceReference
    assert PlaceMention is not PlaceReference
    assert "role" in set(PlaceMention.__dataclass_fields__)
    assert "role" not in set(PlaceReference.__dataclass_fields__)
