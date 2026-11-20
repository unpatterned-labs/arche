# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""The `site` pack: organisation evidence plus a refute-only postcode.

A name says who; a postcode says where. The cases below are the shapes the
Co-op Food Tier 1 list produced against Open Supply Hub (20 Nov 2026), with
invented names.
"""

from __future__ import annotations

from arche.resolve import ENTITY_PACKS, reconcile


def _decide(a: dict, b: dict, entity: str = "site") -> str | None:
    out = reconcile([{"id": "a", **a}], [{"id": "b", **b}], entity=entity, id_field="id")
    return out["matches"][0]["decision"] if out["matches"] else None


ONE_COMPANY_BOLTON = {"name": "Kestrel Baking Ltd - Bolton", "address": "Moss Lane, Bolton",
                      "postcode": "BL4 8NB"}
ONE_COMPANY_SPALDING = {"name": "Kestrel Baking Ltd", "address": "Pinchbeck Road, Spalding",
                        "postcode": "PE12 6EZ"}


class TestPack:
    def test_is_organisation_plus_postcode(self):
        site, org = ENTITY_PACKS["site"], ENTITY_PACKS["organisation"]
        assert site[: len(org)] == org
        assert site[len(org):] == [{"field": "postcode", "kind": "postcode",
                                    "weight": 0.0, "refutes_below": 0.3}]

    def test_organisation_does_not_read_postcodes(self):
        # A registered office is legitimately elsewhere; a postcode does not
        # separate two records of one legal entity.
        assert not any(s.get("kind") == "postcode" for s in ENTITY_PACKS["organisation"])

    def test_uses_the_organisation_frequency_table(self):
        out = reconcile([{"id": "a", **ONE_COMPANY_BOLTON}],
                        [{"id": "b", **ONE_COMPANY_SPALDING}], entity="site", id_field="id")
        assert "organisation" in str(out["pins"]["tf"])


class TestPostcodeRefutes:
    def test_one_company_two_districts_is_held(self):
        assert _decide(ONE_COMPANY_BOLTON, ONE_COMPANY_SPALDING, "organisation") == "match"
        assert _decide(ONE_COMPANY_BOLTON, ONE_COMPANY_SPALDING) == "review"

    def test_a_site_named_only_by_its_town(self):
        a = {"name": "Andover", "address": "5 Pioneer Road, Andover", "postcode": "SP11 8EZ"}
        b = {"name": "Andover", "address": "Millway Road, Andover", "postcode": "SP10 3EX"}
        assert _decide(a, b, "organisation") == "match"  # the false merge
        assert _decide(a, b) == "review"

    def test_same_postcode_written_two_ways_still_matches(self):
        a = {**ONE_COMPANY_SPALDING, "postcode": "PE12 6EZ"}
        b = {**ONE_COMPANY_SPALDING, "postcode": "pe126ez"}
        assert _decide(a, b) == "match"

    def test_same_district_other_unit_is_not_a_refutation(self):
        # Neighbouring units of one estate share a district; a site's two
        # records often differ only in the unit (inward) code.
        a = {**ONE_COMPANY_SPALDING, "postcode": "PE12 6EZ"}
        b = {**ONE_COMPANY_SPALDING, "postcode": "PE12 6PP"}
        assert _decide(a, b) == "match"

    def test_missing_postcode_is_missing_evidence(self):
        a = dict(ONE_COMPANY_SPALDING)
        b = {k: v for k, v in ONE_COMPANY_SPALDING.items() if k != "postcode"}
        assert _decide(a, b) == "match"
        assert _decide({**a, "postcode": ""}, {**a, "postcode": "PE12 6EZ"}) == "match"

    def test_never_creates_a_match(self):
        # Same postcode, different businesses: agreement on place is not
        # agreement on identity, and a weight-0 comparator adds nothing.
        a = {"name": "Harrow Fresh Produce", "address": "Long Lane", "postcode": "PE12 6PP"}
        b = {"name": "Linden Flowers Ltd", "address": "Long Lane", "postcode": "PE12 6PP"}
        assert _decide(a, b, "organisation") == _decide(a, b)
