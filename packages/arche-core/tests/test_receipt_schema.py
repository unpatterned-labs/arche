# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""The receipt vocabulary is versioned, and the version is frozen here.

``decision_id`` is a content hash over the evidence keys plus the pins. Rename
one of those keys and every receipt ever issued stops re-deriving: an id that
addressed a decision yesterday addresses nothing today, and a signature that
verified yesterday does not verify. That is the one property this library
sells, so the cost of breaking it has to be paid deliberately, once, and never
by accident.

``RECEIPT_SCHEMA`` records which vocabulary a receipt was issued under, so a
future rename bumps the version rather than rewriting history -- receipts
issued under 1 keep verifying under 1 forever, because the rules they were
issued under are named in the artifact instead of being implied by whatever
code happens to be installed.

The frozen id below is what makes that a property rather than an intention.
**If it fails, an evidence key, a gate key, a veto key or a pin name moved.**
That is not necessarily wrong, but it is never incidental: bump
``RECEIPT_SCHEMA``, re-freeze deliberately, and say so in the release notes.

It is frozen against a **fixed pins block**, not against a live one. The live
pins carry ``engine: arche-core@<version>``, so every release changes every
``decision_id`` whether or not the vocabulary moved -- a property that predates
this file. Freezing a live id would therefore fail on every version bump, and a
guard that cries wolf each release is one somebody eventually re-freezes
without reading. Holding the pins fixed isolates the thing actually under test:
the *key names*.
"""

from __future__ import annotations

import pytest

from arche.resolve import compare, reconcile
from arche.resolve.coreference import RECEIPT_SCHEMA

# ---------------------------------------------------------------------------
# The frozen fixtures
# ---------------------------------------------------------------------------

#: A receipt address computed over a FIXED evidence block and FIXED pins. It
#: changes if and only if a key name changes, which is the whole point: the
#: live ids move every release because the engine version is pinned into them.
FROZEN_FORMAT_ID = (
    "dec:sha256:ea137d052e2eebafe948a3f3cb8f3f9aa2a440bccd7c190ed9d352cc39987ea9"
)

#: The exact payload the id above is computed from. Written out rather than
#: built from a live call, so that reading this file tells you precisely which
#: names are being guarded.
FROZEN_PAYLOAD = {
    "reference_id_a": "ref:sha256:aaaa",
    "reference_id_b": "ref:sha256:bbbb",
    "decision": "same_entity",
    "factors": {"name": 1.0, "address": 0.8217, "national_id": 1.0},
    "gate": {"distinctive_max": 0.86, "distinctive_floor": 0.75},
    "vetoes": {},
    "jurisdiction": "NG",
    "pins": {
        "receipt_schema": 1,
        "engine": "arche-core@FROZEN",
        "comparator_lib": "jellyfish@FROZEN",
        "jurisdiction": "NG",
        "thresholds": {"match": 0.8, "review": 0.6, "distinctive_floor": 0.75},
        "tf": "default",
    },
}

#: One organisation pair carrying name + address + registration id, so the
#: frozen edge covers a receipt with several evidence keys rather than one.
FROZEN_CROSSWALK_ID = (
    "xwd:sha256:b68efe9b29445d67056dbcc7222694f41a4c318447824866ab27806e065ee878"
)

_ORG_A = {
    "id": "a",
    "name": "Karfi Agro Cooperative Society Ltd",
    "address": "12 Zaria Road, Kano",
}
_ORG_B = {
    "id": "b",
    "name": "Karfi Agro Co-operative Soc.",
    "address": "12 Zaria Rd, Kano State",
    "registration_id": "RC-889112",
}


def _edge():
    return reconcile(
        [_ORG_A], [_ORG_B], entity="organisation", id_field="id"
    )["matches"][0]


# ---------------------------------------------------------------------------
# The version exists and is declared
# ---------------------------------------------------------------------------


def test_schema_version_is_an_integer():
    # A string version invites "1.0" vs "1" vs "v1" drift in a field that is
    # hashed. An integer cannot be written two ways.
    assert isinstance(RECEIPT_SCHEMA, int)
    assert RECEIPT_SCHEMA >= 1


def test_every_receipt_declares_its_vocabulary():
    decision = compare("Adebayo Oluwaseun", "Adebayo Oluwaseun")
    assert decision.pins["receipt_schema"] == RECEIPT_SCHEMA


def test_the_version_is_hashed_not_merely_attached():
    # A version recorded beside the hash rather than inside it is decoration:
    # anyone could relabel a receipt without changing its id. Removing the pin
    # must therefore change the id.
    from arche.ids import decision_id

    base = {
        "reference_id_a": "ref:a",
        "reference_id_b": "ref:b",
        "decision": "same_entity",
        "factors": {"name": 1.0},
        "gate": {},
        "vetoes": {},
        "jurisdiction": "default",
    }
    with_version = decision_id(**base, pins={"receipt_schema": 1, "engine": "x"})
    without = decision_id(**base, pins={"engine": "x"})
    assert with_version != without


# ---------------------------------------------------------------------------
# The frozen ids
# ---------------------------------------------------------------------------


def test_the_receipt_key_vocabulary_is_frozen():
    from arche.ids import decision_id

    assert decision_id(**FROZEN_PAYLOAD) == FROZEN_FORMAT_ID, (
        "The receipt key vocabulary changed. Renaming a Python class or "
        "function must NOT reach this value -- if it did, an evidence key, a "
        "gate key, a veto key or a pin NAME moved with it. Bump "
        "RECEIPT_SCHEMA and re-freeze deliberately."
    )


def test_the_engine_version_is_pinned_into_every_receipt():
    # Why the test above holds the pins fixed. The live pins name the release
    # that issued the receipt, so ids move every version whether or not the
    # vocabulary did. That is deliberate -- a decision is only reproducible
    # against the code that made it -- and it is what makes a *live* frozen id
    # the wrong guard for a *format* claim.
    import arche

    decision = compare("Adebayo Oluwaseun", "Adebayo Oluwaseun")
    assert decision.pins["engine"] == f"arche-core@{arche.__version__}"


def test_crosswalk_edge_id_is_frozen():
    assert _edge()["decision_id"] == FROZEN_CROSSWALK_ID, (
        "The crosswalk edge format changed. See test_pairwise_receipt_id_is_"
        "frozen -- same rule, same remedy."
    )


# ---------------------------------------------------------------------------
# The wire names that must survive the Python rename
# ---------------------------------------------------------------------------


def test_reconcile_engine_pin_keeps_its_wire_name():
    # `crosswalk` was renamed to `reconcile` in the Python surface. This
    # string is not the Python surface: it is hashed into every edge ever
    # issued, so it stays as written. A future contributor "tidying" it to
    # match the new verb would invalidate every signed edge, which is why the
    # assertion names the intent rather than just the value.
    assert _edge() and reconcile(
        [_ORG_A], [_ORG_B], entity="organisation", id_field="id"
    )["pins"]["engine"] == "crosswalk.v1"


@pytest.mark.parametrize(
    "key", ["receipt_schema", "engine", "comparator_lib", "thresholds", "tf"]
)
def test_pairwise_pin_keys_are_stable(key):
    # The pin block's own key names are hashed too. Enumerated so that adding
    # a pin is a visible, deliberate act rather than a silent id change.
    assert key in compare("Adebayo Oluwaseun", "Adebayo Oluwaseun").pins
