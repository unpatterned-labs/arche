# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Which columns an entity pack actually reads.

The question a caller asks before handing records to `crosswalk` — *will it use
my `occupation` column?* — had no answer anywhere. The packs are a module-level
dict of comparator dicts, so the answer was derivable but nobody had derived it,
and the alternative was prose that goes stale: the `person` pack gained a date
comparator in 0.5.0a1 and any hand-written list of its fields was wrong the day
that landed.

So the substance of this file is not that `describe_pack` returns something
plausible. It is that what it returns is **the pack itself**, checked against
`ENTITY_PACKS` rather than against a copy of the expected answer. A test that
hard-coded the field list would rot in exactly the way the docs did.
"""

from __future__ import annotations

import pytest
from arche.resolve import COMPARATOR_NOTES, ENTITY_PACKS, describe_pack, describe_packs


def _declared_fields(entity: str) -> set[str]:
    """Every column name the pack's comparators name, read straight off it."""
    names: set[str] = set()
    for comparator in ENTITY_PACKS[entity]:
        if comparator.get("kind") == "geo":
            names.add(comparator.get("lat", "lat"))
            names.add(comparator.get("lon", "lon"))
        elif comparator.get("field"):
            names.add(comparator["field"])
    return names


@pytest.mark.parametrize("entity", sorted(ENTITY_PACKS))
class TestItDescribesThePackAndNotACopyOfIt:

    def test_every_declared_field_is_reported(self, entity):
        assert set(describe_pack(entity)["field_names"]) == _declared_fields(entity)

    def test_every_comparator_kind_has_a_note(self, entity):
        """A field listed without a reason is a field list, which is what this
        replaces. An unexplained kind means the lexicon needs a line."""
        for comparator in ENTITY_PACKS[entity]:
            assert comparator["kind"] in COMPARATOR_NOTES, comparator["kind"]

    def test_no_field_is_listed_twice(self, entity):
        fields = [f["field"] for f in describe_pack(entity)["fields"]]
        assert len(fields) == len(set(fields))

    def test_the_heaviest_field_comes_first(self, entity):
        """A reader scanning the list should meet the field that matters most."""
        weights = [f["weight"] for f in describe_pack(entity)["fields"]]
        assert weights == sorted(weights, reverse=True)


class TestTheThingsWorthSayingOutLoud:

    def test_a_field_used_by_two_comparators_is_one_entry(self):
        """`name` is compared twice in the person pack — once as a name and once
        for how rare its words are. That is one column to a caller."""
        name = next(f for f in describe_pack("person")["fields"]
                    if f["field"] == "name")
        assert set(name["kinds"]) == {"name", "tftoken"}

    def test_and_its_weight_is_the_sum(self, ):
        name = next(f for f in describe_pack("person")["fields"]
                    if f["field"] == "name")
        assert name["weight"] == 4.0

    def test_geo_is_reported_as_the_pair_of_columns_it_is(self):
        """It does not use `field`, and a caller needs both column names."""
        fields = {f["field"] for f in describe_pack("place")["fields"]}
        assert "lat + lon" in fields
        assert {"lat", "lon"} <= set(describe_pack("place")["field_names"])

    def test_a_refuting_field_says_so(self):
        """Asymmetric: it can pull a pair down into review and never up.

        Worth surfacing, because it is the one place where filling a column in
        can make a pair score *worse*.
        """
        entity_class = next(f for f in describe_pack("organisation")["fields"]
                            if f["field"] == "entity_class")
        assert entity_class["refutes"] is True

    def test_nothing_in_the_person_pack_refutes(self):
        """Guarded elsewhere too, and asserted here because the description
        would be actively misleading if it claimed otherwise."""
        assert not any(f["refutes"] for f in describe_pack("person")["fields"])

    def test_the_date_comparator_shows_up(self):
        """The specific thing that made a hand-written list wrong."""
        assert "birth_date" in describe_pack("person")["field_names"]

    def test_an_unknown_pack_lists_the_real_ones(self):
        with pytest.raises(ValueError, match="available:"):
            describe_pack("spacecraft")

    def test_describe_packs_covers_all_of_them(self):
        assert set(describe_packs()) == set(ENTITY_PACKS)


class TestIgnoredNotRejected:
    """The claim the description makes about everything else.

    If `crosswalk` actually errored on an unknown field, the studio would be
    telling people something false. It does not, and this is the test that keeps
    that true.
    """

    def test_an_unknown_field_does_not_raise(self):
        from arche.resolve import reconcile
        records = [{"id": "1", "name": "Amara Patel", "occupation": "nurse"}]
        reconcile(records, records, entity="person", id_field="id")

    def test_and_does_not_change_the_score(self):
        """The stronger claim, and the one that makes it worth saying."""
        from arche.resolve import reconcile
        bare = [{"id": "1", "name": "Amara Patel"},
                {"id": "2", "name": "Amara Patel"}]
        extra = [{**r, "occupation": "nurse", "favourite_colour": "blue"}
                 for r in bare]
        assert ([m["score"] for m in reconcile(bare, bare, entity="person",
                                               id_field="id")["matches"]]
                == [m["score"] for m in reconcile(extra, extra, entity="person",
                                                  id_field="id")["matches"]])

    def test_the_description_says_so(self):
        assert describe_pack("person")["ignores_everything_else"] is True
