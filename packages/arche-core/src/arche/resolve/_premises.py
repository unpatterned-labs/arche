# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Does an address name the same premises?

A street number is the most identifying part of an address and the least of its
text, so a similarity over the whole string cannot carry it. Measured on the
`address` comparator::

    Unit 4, Trafford Park Industrial Estate   vs  Unit 9, Trafford Park ...
        address similarity 0.992
    An der Gehespitz 50, 63263 Neu-Isenburg   vs  ... 63263 Neu Isenburg
        address similarity 0.990

Different premises scoring HIGHER than one premises written two ways. The
distributions overlap -- same-premises pairs run 0.867 to 1.000 and
different-premises pairs reach 0.992 -- so **no `refutes_below` value on that
score separates them.** The digit carrying the identity is a rounding error in
the string carrying the score.

That is why this is a comparator rather than a threshold.
"""

from __future__ import annotations

import re

#: Words that introduce a premises designator, and the designator itself.
#:
#: A regex rather than `arche.addr.parse_address`, which recovers
#: `street_number` for `12 Zaria Road` and `221B Baker Street` and returns
#: nothing at all for `Unit 4, ...` or `Plot 88, ...` -- most of the industrial
#: and market-stall addressing this lane actually meets.
_PREMISES_WORD = (
    r"(?:unit|plot|suite|ste|apt|apartment|flat|block|floor|fl|room|rm|shop|"
    r"stall|kiosk|house|no|number|#)"
)
_PREMISES = re.compile(
    # `Unit 4`, `Plot 88`, `Suite 300B`, `No. 12`, `#5`
    rf"(?<![A-Za-z0-9]){_PREMISES_WORD}\s*\.?\s*([0-9]+[A-Za-z]?)"
    # or a leading street number: `12 Zaria Road`, `221B Baker Street`
    rf"|^\s*([0-9]+[A-Za-z]?)(?=[\s,])",
    re.I,
)


#: A number closing the first segment, for street-number-last conventions.
_TRAILING_NUMBER = re.compile(r"(?<![A-Za-z0-9])([0-9]{1,4}[A-Za-z]?)\s*$")


def premises_designator(address: str) -> str | None:
    """The identifying number in an address, or None if it carries none.

    Returns a normalised designator -- `4`, `88`, `221b` -- from either an
    explicit form (`Unit 4`, `Plot 88`, `Suite 300`) or a leading street number
    (`12 Zaria Road`). Case-folded so `221B` and `221b` agree.

    None means "this address does not state a premises", which is a different
    thing from two premises disagreeing and must not be scored as one.
    """
    if not address:
        return None
    text = str(address)[:400]
    for match in _PREMISES.finditer(text):
        found = match.group(1) or match.group(2)
        if found:
            return found.lower()
    # German and Dutch word order puts the number after the street: `An der
    # Gehespitz 50, 63263 Neu-Isenburg`. Only the FIRST comma-delimited segment
    # is searched, so the postcode in `63263 Neu-Isenburg` cannot be mistaken
    # for a premises. Returning None here was safe but left those addresses
    # with no protection at all, which is most of continental Europe.
    first = text.split(",")[0].strip()
    trailing = _TRAILING_NUMBER.search(first)
    if trailing and not first.replace(" ", "").isdigit():
        return trailing.group(1).lower()
    return None


def compare_premises(address_a: str, address_b: str) -> float | None:
    """Do two addresses name the same premises?

    ``0.0`` when both state one and they differ, ``1.0`` when they agree, and
    ``None`` when either is silent -- the same contract every other refuting
    comparator here follows, because an absent field is missing evidence and
    never a disagreement.

    Pair it with ``refutes_below`` at weight 0.0. A matching number is weak
    evidence on its own (every street has a number 12); a differing one is
    strong evidence against. That asymmetry is exactly what a weight cannot
    express and what a refutation is for.
    """
    left = premises_designator(address_a)
    right = premises_designator(address_b)
    if left is None or right is None:
        return None
    return 1.0 if left == right else 0.0


__all__ = ["compare_premises", "premises_designator"]
