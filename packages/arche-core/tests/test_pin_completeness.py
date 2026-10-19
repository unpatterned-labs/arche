# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""A shipped input that changes a verdict has to be named in the pin.

`reconcile` states the rule for the code-frequency table: "An input that
changes a decision has to be named in the pin, or ``decision_id`` claims a
reproducibility it does not have." Two shipped assets did not follow it.

Measured 2026-10-18, before the fix: flipping every relation in
``legal_form_compat.yaml`` to 0.99 moved ``Zenith Bank Plc`` against ``Zenith
Bank Limited`` from ``review`` (0.9444) to ``match`` (0.9989) -- and the pins
came out **byte-identical**. The decision id did move, because the evidence is
hashed, so nothing could be silently altered and keep its address. What was
lost is provenance: two runs disagreeing on a verdict were indistinguishable by
configuration, and neither was reproducible from its pins.

The second half of this file guards the other direction. Evidence is hashed
into ``decision_id``, and `share_artifact` masks every string value inside it,
so a string in the evidence makes the pack unverifiable the moment it is
shared. The legal-form lane briefly carried ``form_a`` / ``form_b`` verbatim.
"""

from __future__ import annotations

import pytest
from arche.resolve import reconcile

_PLC = [{"id": "a", "name": "Zenith Bank Plc", "city": "Lagos"}]
_LTD = [{"id": "b", "name": "Zenith Bank Limited", "city": "Lagos"}]


def _edge(list_a, list_b, **kw):
    result = reconcile(list_a, list_b, id_field="id", **kw)
    cross = [m for m in result["matches"] if m["a_id"] != m["b_id"]]
    assert cross, "expected the pair to be compared"
    return cross[0], result["pins"]


class TestShippedAssetsArePinned:
    def test_the_legal_form_tables_are_named(self):
        """Both assets the organisation lane decides with appear in the pin."""
        _, pins = _edge(_PLC, _LTD, entity="organisation")
        assets = pins.get("data_assets")
        assert assets, "organisation pins must carry data_assets"
        assert "legal_form" in assets
        assert "type_tokens:organization" in assets
        # Digests, not labels. A pin that names a domain without naming the
        # bytes cannot tell two vocabularies apart.
        assert assets["legal_form"].startswith("legal_form@")
        assert len(assets["legal_form"].split("@")[-1]) >= 16
        assert len(assets["type_tokens:organization"]) >= 16

    def test_a_lane_without_legal_forms_does_not_pin_them(self):
        """Scoped to what was read, so an unrelated edit cannot move the pin.

        A pin that changes for reasons the run had nothing to do with teaches
        people to ignore it, which costs more than the pin was worth.
        """
        _, pins = _edge(
            [{"id": "a", "name": "Ikpeyan Primary Health Center",
              "lat": 6.9, "lon": 5.9}],
            [{"id": "b", "name": "Ikpeyan Health Center",
              "lat": 6.9, "lon": 5.9}],
            entity="place",
        )
        assets = pins.get("data_assets") or {}
        assert "legal_form" not in assets, (
            "the place lane declares no legal_form comparator, so pinning the "
            "legal-form tables would make its pin move when they are edited")

    def test_the_pin_is_a_function_of_the_asset_not_the_pair(self):
        """Two different organisation pairs pin the same assets."""
        _, first = _edge(_PLC, _LTD, entity="organisation")
        _, second = _edge(
            [{"id": "c", "name": "Kijani Tea Exporters Ltd", "city": "Nairobi"}],
            [{"id": "d", "name": "Kijani Tea Exporters LLP", "city": "Nairobi"}],
            entity="organisation",
        )
        assert first["data_assets"] == second["data_assets"]


class TestEvidenceCarriesNoText:
    """Strings in the evidence cost the pack its verifiability when shared."""

    @pytest.mark.parametrize("entity,left,right", [
        ("organisation", _PLC, _LTD),
        ("organisation",
         [{"id": "a", "name": "Kijani Tea Exporters Ltd", "city": "Nairobi"}],
         [{"id": "b", "name": "Kijani Tea Exporters Limited", "city": "Nairobi"}]),
    ])
    def test_every_evidence_value_is_a_number(self, entity, left, right):
        edge, _ = _edge(left, right, entity=entity)
        text = {k: v for k, v in edge["evidence"].items() if isinstance(v, str)}
        assert not text, (
            f"evidence carries string values {text}. Evidence is hashed into "
            "decision_id and share_artifact replaces every string inside it, "
            "so this makes the shared pack unverifiable. Record the "
            "measurement, not the value -- the value is in the record."
        )

    def test_the_conflict_is_still_reported(self, ):
        """Dropping the labels must not drop the signal."""
        edge, _ = _edge(_PLC, _LTD, entity="organisation")
        evidence = edge["evidence"]
        assert "name_legal_form" in evidence, "the comparator must still score"
        assert evidence["name_legal_form"] < 1.0, (
            "Plc against Limited is a form disagreement and must score below 1")
        assert edge["decision"] == "review", (
            "a form conflict with no agreeing identifier demotes to review")


class TestEveryShippedTableNamesItsBytes:
    """A pin that names a domain cannot tell a rebuilt table from its predecessor.

    `_shipped_tf_pin` appends `@{table.version}` when a table has one. Four
    shipped tables -- artist, english, name (person) and organisation --
    declared no version inside their data file, so an organisation run pinned
    the bare label `shipped:organisation`. A token table is both a comparator
    input and a blocking key, so a rebuild changes which pairs are proposed as
    well as how they score; a pin that cannot see the change is not provenance.

    Fixed 2026-10-18 by deriving the version from the content at load time when
    the file declares none. A declared version still wins, so no decision
    already scored against `place` or `organisation_gb` moves.
    """

    @pytest.mark.parametrize("domain,declared", [
        ("place", "sha256:c94f20a1c2dfba18"),
        ("organisation_gb", "sha256:505fce72d9fa6d5f"),
    ])
    def test_a_declared_version_is_never_overwritten(self, domain, declared):
        """The build's own identifier wins, or existing ids move for nothing."""
        from arche.resolve._tokenfreq import TokenFrequencyTable

        assert TokenFrequencyTable.default(domain=domain).version == declared

    @pytest.mark.parametrize("domain", ["organisation", "person", "artist"])
    def test_a_table_without_one_derives_it(self, domain):
        from arche.resolve._tokenfreq import TokenFrequencyTable

        version = TokenFrequencyTable.default(domain=domain).version
        assert version and version.startswith("sha256:")
        assert len(version.split(":")[-1]) == 16

    def test_the_pin_carries_the_digest(self):
        """The whole point: an organisation run names the bytes it scored with."""
        _, pins = _edge(_PLC, _LTD, entity="organisation")
        assert pins["tf"].startswith("shipped:organisation@sha256:"), pins["tf"]

    def test_a_rebuilt_table_gets_a_different_version(self):
        """Otherwise the digest is decoration."""
        from arche.resolve._tokenfreq import TokenFrequencyTable

        base = {"format": 1, "unknown_floor": 5e-05, "token_rule": "plain",
                "total": 100, "counts": {"ltd": 50, "kijani": 1}}
        rebuilt = {**base, "counts": {"ltd": 50, "kijani": 2}}
        first = TokenFrequencyTable.from_dict(base).version
        second = TokenFrequencyTable.from_dict(rebuilt).version
        assert first and second and first != second

    def test_a_cosmetic_key_does_not_pretend_to_be_a_new_table(self):
        """The digest covers what changes scoring, not the whole file."""
        from arche.resolve._tokenfreq import TokenFrequencyTable

        base = {"format": 1, "unknown_floor": 5e-05, "token_rule": "plain",
                "total": 100, "counts": {"ltd": 50}}
        annotated = {**base, "built_at": "2026-10-18", "note": "rebuild"}
        assert (TokenFrequencyTable.from_dict(base).version
                == TokenFrequencyTable.from_dict(annotated).version)
