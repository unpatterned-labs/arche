# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""The `legal_entity` pack: a register's address supports, its name refutes.

The shapes are the ones CQC providers against Companies House produced (X16,
23 Nov 2026), with invented names.
"""

from __future__ import annotations

from arche.resolve import ENTITY_PACKS, reconcile
from arche.resolve._gate import rival_distinctive_tokens
from arche.resolve._tokenfreq import TokenFrequencyTable


def _decide(a: dict, b: dict, entity: str = "legal_entity") -> str | None:
    out = reconcile([{"id": "a", **a}], [{"id": "b", **b}], entity=entity, id_field="id")
    return out["matches"][0]["decision"] if out["matches"] else None


OFFICE = "12 High Street, London SW15 1AA"


class TestPack:
    def test_is_organisation_without_premises_plus_rival(self):
        org = [s for s in ENTITY_PACKS["organisation"] if s.get("kind") != "premises"]
        pack = ENTITY_PACKS["legal_entity"]
        assert pack[: len(org)] == org
        assert [s["kind"] for s in pack[len(org):]] == ["rival"]
        assert not any(s.get("kind") == "premises" for s in pack)

    def test_uses_the_organisation_frequency_table(self):
        out = reconcile([{"id": "a", "name": "Harbourline Care Ltd"}],
                        [{"id": "b", "name": "HARBOURLINE CARE LIMITED"}],
                        entity="legal_entity", id_field="id")
        assert "organisation" in str(out["pins"]["tf"])


class TestRegisteredOfficeDoesNotHold:
    def test_same_name_other_unit_matches(self):
        a = {"name": "Harbourline Care Ltd",
             "address": "Unit 53, Wenta Business Centre, Watford WD24 7ND"}
        b = {"name": "HARBOURLINE CARE LIMITED",
             "address": "Unit 44, Wenta Business Centre, Watford WD24 7ND"}
        assert _decide(a, b, "organisation") == "review"  # the hold X16 measured
        assert _decide(a, b) == "match"


class TestNameRefutes:
    def test_sister_companies_at_one_office_are_held(self):
        a = {"name": "Kestrel Dental Putney Ltd", "address": OFFICE}
        b = {"name": "KESTREL DENTAL WIMBLEDON LIMITED", "address": OFFICE}
        assert _decide(a, b, "organisation") == "match"  # the false merge
        assert _decide(a, b) == "review"

    def test_one_sided_distinctive_word_is_enough(self):
        a = {"name": "Quillan Robson Academy Ltd", "address": OFFICE}
        b = {"name": "QUILLAN ROBSON CARE LTD", "address": OFFICE}
        assert _decide(a, b, "organisation") == "match"
        assert _decide(a, b) == "review"

    def test_legal_form_and_case_do_not_refute(self):
        a = {"name": "Harbourline Care Ltd", "address": OFFICE}
        b = {"name": "HARBOURLINE CARE LIMITED", "address": OFFICE}
        assert _decide(a, b) == "match"


class TestRivalOptionsDefaultOff:
    """The register options leave the shipped `rival` exactly as it was."""

    def test_shared_brand_settles_it_by_default(self):
        tf = TokenFrequencyTable.default("organisation")
        a, b = "Kestrel Dental Putney", "Kestrel Dental Wimbledon"
        assert rival_distinctive_tokens(a, b, tf) is None
        assert rival_distinctive_tokens(a, b, tf, mutual=False, shared_overrides=False,
                                        ordinary_words=False) == 0.0

    def test_one_side_alone_is_quiet_by_default(self):
        tf = TokenFrequencyTable.default("organisation")
        a, b = "Quillan Robson Academy", "Quillan Robson"
        assert rival_distinctive_tokens(a, b, tf) is None
        assert rival_distinctive_tokens(a, b, tf, mutual=False, shared_overrides=False,
                                        ordinary_words=False) == 0.0
