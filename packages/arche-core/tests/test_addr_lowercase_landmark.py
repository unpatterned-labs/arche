# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Landmarks written without capitals.

`arche-direction-and-5-year-vision.md` §2 explains the moat by listing what a
generic parser does not know, and one of the four items is that *"behind the
mosque" is an address*. That exact string returned `None`.

The cause was narrow and the vocabulary was not at fault. `_classify_anchor`
already knew `mosque` is religious; it was simply never reached, because the
landmark had to begin with a capital letter and `the central mosque` does not.
`behind Central Mosque` worked, `behind the central mosque` did not, and
informal addresses are written the second way.

The fix could not be to drop the capital requirement. `_ANCHOR_PREPOSITIONS`
contains `after` and `before`, which are ordinary English, so admitting any
lowercase words after them turns *"after the meeting"* into an address. A
lowercase landmark is therefore accepted only when it ends in a word naming a
kind of place, drawn from the same vocabulary `_classify_anchor` keys on.

So this file is half recall and half precision, and the precision half is the
one that must not regress: a missed landmark is recoverable, a sentence misread
as an address is not.
"""

from __future__ import annotations

import pytest
from arche.addr import parse_address
from arche.addr.parse import extract_anchor


class TestTheDocumentedExample:
    """The string the project's own positioning uses. It returned None."""

    def test_behind_the_central_mosque_is_an_address(self):
        anchor, kind = extract_anchor("behind the central mosque, Karfi, Kano State")
        assert anchor == "behind the central mosque"
        assert kind == "religious"

    def test_and_it_survives_the_whole_parser(self):
        """`extract_anchor` and `parse_address` are separate paths over one
        regex. Fixing the first without the second would fix nothing a caller
        of `parse_address` could see."""
        parsed = parse_address("behind the central mosque, Karfi, Kano State")
        assert parsed is not None
        assert parsed.components.anchor == "behind the central mosque"
        assert parsed.components.anchor_type == "religious"

    def test_the_bare_form_works_too(self):
        assert extract_anchor("behind the mosque, Karfi") is not None

    def test_the_docs_sentence_parses(self):
        """From `how-to/extract-places-with-roles.md`, verbatim."""
        parsed = parse_address(
            "The workshop is behind the central mosque, Ungwan Rimi, Kaduna")
        assert parsed is not None
        assert parsed.components.anchor_type == "religious"
        assert parsed.components.city == "Kaduna"


@pytest.mark.parametrize("text", [
    "behind the central mosque, Karfi",
    "behind the mosque, Karfi",
    "near the junction, Wuse",
    "opposite the market, Ikeja",
    "beside the church, Kaduna",
    "in front of the hospital, Kano",
    "across from the roundabout, Accra",
    "next to the school, Nairobi",
    "behind the filling station, Madina, Accra",
])
def test_lowercase_landmarks_parse(text):
    assert extract_anchor(text) is not None, text


@pytest.mark.parametrize("text", [
    "after the meeting we will talk",
    "before the deadline",
    "near the end of the year",
    "behind the scenes",
    "after the merger closed",
    "we met after the bank holiday",
    "before the market opens tomorrow",
    "after the school year ends",
    "near the park bench she left it",
    "behind the curve on adoption",
])
def test_ordinary_english_is_not_an_address(text):
    """The half that matters more.

    `after` and `before` are prepositions in the anchor vocabulary *and* the
    commonest words in English narrative. Three of these contain a real landmark
    noun — `bank`, `market`, `school`, `park` — and are still rejected, because
    the noun must end the phrase. That trailing lookahead is the whole guard.
    """
    assert extract_anchor(text) is None, text


class TestCapitalisedLandmarksAreUnaffected:
    """The pre-existing branch is tried first and must behave identically."""

    @pytest.mark.parametrize("text,expected", [
        ("behind Central Mosque, Karfi", "behind Central Mosque"),
        ("opposite Shoprite, Lekki Phase 1, Lagos", "opposite Shoprite"),
        ("behind the Total filling station, Madina, Accra",
         "behind the Total filling station"),
    ])
    def test_unchanged(self, text, expected):
        anchor, _ = extract_anchor(text)
        assert anchor == expected


class TestTheKnownLimit:
    """Stated rather than hidden.

    Requiring the landmark noun to end the phrase is what rejects "after the
    bank holiday". The same rule means a trailing modifier is not absorbed. This
    is a deliberate trade, and it is a test so that anyone who later widens the
    rule sees what they are trading away.
    """

    def test_a_trailing_modifier_is_not_picked_up(self):
        assert extract_anchor("behind the big market square, Kano") is None

    def test_but_capitalising_it_works_as_it_always_did(self):
        assert extract_anchor("behind the Big Market Square, Kano") is not None


def test_contributor_added_nouns_reach_the_lowercase_branch():
    """The noun alternation is built after `_merge_address_tokens()` runs.

    If it were built before, a place type added through `address_tokens.yaml`
    would classify correctly and never match, which is the same split between
    vocabulary and matcher that caused the original bug.
    """
    from pathlib import Path as _Path

    from arche.addr import parse as module
    source = _Path(module.__file__).read_text(encoding="utf-8")
    assert source.index("_merge_address_tokens()") < source.index("_ANCHOR_NOUN_RE = ")
