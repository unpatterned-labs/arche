# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""The token-frequency pin has to name the table, not just assert one existed.

A frequency table decides which tokens are rare. Rarity is a comparator input
AND a blocking key, so two different tables reach different verdicts on the same
pair. `reconcile.py` states that rule and follows it for shipped tables, which
pin as `shipped:place@sha256:...`.

Two paths did not follow it:

* a caller's own table pinned as the word `provided`
* a self-calibrated table, built from the two lists being linked, pinned as the
  word `self-calibrated`

Both are corpus-dependent by construction, so two runs that disagreed about a
pair could pin identically. `decision_id` is derived from the pins, so it claimed
a reproducibility it did not have.

The fix does not remove the batch dependence, which is a real property of
self-calibration and not a bug. It makes it **visible**: two decisions carrying
different tf digests were scored against different vocabularies and were never
expected to agree.
"""

from __future__ import annotations

import pytest
from arche.resolve import reconcile
from arche.resolve._tokenfreq import TokenFrequencyTable

# Partial overlap, so the shared token's rarity decides the score. Two identical
# strings score 1.0 whatever the corpus and cannot show this.
_A = {"id": "a", "name": "Ngozi Adeyemi"}
_B = {"id": "b", "name": "Ngozi Adeyemi Bello"}
_RARE = [{"id": f"r{i}", "name": f"Fatima Bakare {i}"} for i in range(12)]
_COMMON = [{"id": f"c{i}", "name": f"Tunde Adeyemi {i}"} for i in range(12)]


def _run(extra):
    res = reconcile([_A] + extra, [_B] + extra, entity="person", id_field="id")
    edge = next(e for e in res["matches"]
                if e["a_id"] == "a" and e["b_id"] == "b")
    return res["pins"]["tf"], edge


class TestSelfCalibrated:

    def test_the_corpus_really_does_change_the_decision(self):
        """The premise. Without this the pin would be solving nothing."""
        _, rare = _run(_RARE)
        _, common = _run(_COMMON)
        assert rare["decision"] == "match"
        assert common["decision"] == "review"

    def test_so_the_two_runs_must_not_pin_identically(self):
        """They did, as the bare string `self-calibrated`."""
        rare_pin, _ = _run(_RARE)
        common_pin, _ = _run(_COMMON)
        assert rare_pin != common_pin

    def test_the_pin_names_a_digest(self):
        pin, _ = _run(_RARE)
        assert pin.startswith("self-calibrated@sha256:")
        assert len(pin.split(":")[-1]) == 64

    def test_the_same_corpus_pins_the_same_way(self):
        """A digest that moved between identical runs would be worthless."""
        assert _run(_RARE)[0] == _run(_RARE)[0]

    def test_decision_ids_differ_when_the_vocabulary_did(self):
        _, rare = _run(_RARE)
        _, common = _run(_COMMON)
        assert rare["decision_id"] != common["decision_id"]


class TestProvidedTable:

    _SPEC = [
        {"field": "name", "kind": "name", "weight": 2.0},
        {"field": "name", "kind": "tftoken", "weight": 2.0},
    ]

    def _pin(self, tf):
        res = reconcile([_A], [_B], id_field="id", comparators=self._SPEC, tf=tf)
        return res["pins"]["tf"]

    def test_two_different_tables_pin_differently(self):
        one = TokenFrequencyTable.from_corpus(["Ngozi Adeyemi", "Fatima Bakare"])
        two = TokenFrequencyTable.from_corpus(
            [f"Tunde Adeyemi {i}" for i in range(12)])
        assert self._pin(one) != self._pin(two)

    def test_the_pin_names_a_digest(self):
        tf = TokenFrequencyTable.from_corpus(["Ngozi Adeyemi", "Fatima Bakare"])
        assert self._pin(tf).startswith("provided@sha256:")


class TestShippedTablesAreUnchanged:
    """They already named a digest. This fix must not disturb them."""

    def test_place_still_pins_its_shipped_table(self):
        res = reconcile([{"id": "a", "name": "Kano Central Clinic"}],
                        [{"id": "b", "name": "Kano Central Clinic"}],
                        entity="place", id_field="id")
        assert res["pins"]["tf"].startswith("shipped:place@sha256:")


class TestTheComparatorPin:

    def test_is_a_full_digest(self):
        """Was truncated to 16 hex characters, in a field named for a sha256.

        64 bits is fine against accident and not against anyone who wants two
        comparator sets to pin alike. A pin that can be collided on purpose
        cannot answer "which configuration produced this decision".
        """
        res = reconcile([{"id": "a", "name": "Kano Central Clinic"}],
                        [{"id": "b", "name": "Kano Central Clinic"}],
                        entity="place", id_field="id")
        assert len(res["pins"]["comparators_sha256"]) == 64

    def test_different_comparators_pin_differently(self):
        base = [{"field": "name", "kind": "name", "weight": 2.0}]
        heavier = [{"field": "name", "kind": "name", "weight": 3.0}]
        pins = []
        for spec in (base, heavier):
            res = reconcile([_A], [_B], id_field="id", comparators=spec)
            pins.append(res["pins"]["comparators_sha256"])
        assert pins[0] != pins[1]


@pytest.mark.parametrize("entity", ["person", "place"])
def test_every_run_pins_something_for_tf(entity):
    """A tftoken comparator without a tf pin is an unnamed scoring input."""
    res = reconcile([{"id": "a", "name": "Kano Central Clinic"}],
                    [{"id": "b", "name": "Kano Central Clinic"}],
                    entity=entity, id_field="id")
    assert res["pins"].get("tf")
