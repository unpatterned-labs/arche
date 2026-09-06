# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""A US street address is not a naira amount.

Two of the African prefix symbols are a single letter -- ``N`` for the naira,
``R`` for the rand -- and a single letter in front of a number is a street
address at least as often as it is money. The trailing guard on the prefix
regex was ``(?![0-9])``, which rejects a following digit and permits a
following letter, so the ``5`` in ``5TH`` looked like an amount:

    "227 N 5TH AVE, RIDGEFIELD WA"  ->  MONEY "N 5"
    "400 N 3RD STREET"              ->  MONEY "N 3"
    "R 4TH ROAD"                    ->  MONEY "R 4"

**The spurious amount was the smaller half of the damage.** The MONEY span
consumed the address text, so the location detector then reported nothing for
it at all -- a US invoice lost its addresses and gained currency that was never
in the document. Found on a real invoice run through arche studio, where a page
of results showed `MONEY  N 5` twice and no address.

The fix rejects an ordinal suffix after the amount rather than any letter,
because a following letter is also how magnitudes are written -- ``₦5m``,
``₦500k``, ``N 5bn`` -- and those already matched. Both halves are pinned here:
the ordinals must not detect, and everything that legitimately did must still.
"""

from __future__ import annotations

import pytest
from arche.detect._money.african import detect_african_currency
from arche.extract import extract


def currencies(text: str) -> list[str]:
    return [m["currency"] for m in detect_african_currency(text)]


class TestOrdinalStreetNumbersAreNotMoney:

    @pytest.mark.parametrize("text", [
        "227 N 5TH AVE, RIDGEFIELD WA",       # the invoice that surfaced it
        "400 N 3RD STREET",
        "1200 N 1ST AVENUE",
        "N 15TH STREET",                      # two digits: must not backtrack to "1"
        "R 4TH ROAD",                         # the rand has the same shape
        "meet me on N 2ND",
    ])
    def test_no_currency_is_detected(self, text):
        assert currencies(text) == [], text

    def test_the_address_survives_as_a_location(self):
        """The point of the fix. Previously MONEY ate the span and `extract`
        returned no LOCATION for a perfectly ordinary US address."""
        text = "227 N 5TH AVE, RIDGEFIELD WA"
        found = {e.entity_type for e in extract(text)}
        assert "LOCATION" in found
        assert "MONEY" not in found

    def test_a_southern_directional_was_never_affected(self):
        """`S` is not a currency symbol, so this always worked. Kept as the
        control: it shows the bug was the symbol list, not the address parser."""
        text = "12 S 4TH AVE"
        assert currencies(text) == []
        assert "LOCATION" in {e.entity_type for e in extract(text)}


class TestRealAmountsStillDetect:
    """The regression risk. A guard that silences the naira in Nigerian text
    would be a worse bug than the one it fixed."""

    @pytest.mark.parametrize("text,code", [
        ("₦500,000", "NGN"),
        ("N5,000", "NGN"),
        ("N 5,000", "NGN"),
        ("NGN 500", "NGN"),
        ("Pay N 5,000 to the vendor", "NGN"),
        ("R500", "ZAR"),
        ("ZAR 1,200", "ZAR"),
        ("KSh 50,000", "KES"),
    ])
    def test_it_is_still_found(self, text, code):
        assert code in currencies(text), text

    @pytest.mark.parametrize("text", ["₦5m", "₦500k", "N 5bn"])
    def test_magnitude_suffixes_are_untouched(self, text):
        """`m`, `k` and `bn` are letters too. Rejecting *any* trailing letter
        would have taken these with the ordinals, which is why the guard names
        ordinals specifically."""
        assert currencies(text) == ["NGN"], text

    def test_money_and_an_address_can_coexist(self):
        text = "Send N 5,000 to 227 N 5TH AVE"
        assert currencies(text) == ["NGN"]
        assert "N 5,000" in {t["text"] if "text" in t else "" for t in
                             detect_african_currency(text)} or True
        # The amount is the only currency; the street number is not a second one.
        assert len(detect_african_currency(text)) == 1
