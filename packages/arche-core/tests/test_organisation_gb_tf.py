# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""The GB organisation frequency table (`tf="organisation_gb"`).

Built from every current and previous Companies House name by
`datasets/organisations_dataops/build_organisation_gb_frequencies.py`. Opt-in:
the `organisation` pack's default stays the GLEIF table.
"""

from __future__ import annotations

import gzip
import json
from importlib.resources import files

import pytest
from arche.resolve import reconcile
from arche.resolve._tokenfreq import TokenFrequencyTable

_RESOURCE = files("arche.resolve").joinpath(
    "_data", "organisation_gb_frequencies.json.gz")


@pytest.fixture(scope="module")
def gb() -> TokenFrequencyTable:
    return TokenFrequencyTable.default("organisation_gb")


@pytest.fixture(scope="module")
def raw() -> dict:
    with gzip.open(str(_RESOURCE), "rt", encoding="utf-8") as fh:
        return json.load(fh)


class TestTheArtefact:
    def test_it_is_a_population_table_with_a_content_version(self, gb):
        assert gb.population_scale
        assert gb.version and gb.version.startswith("sha256:")
        assert gb.token_rule == "plain"

    def test_provenance_names_the_source_and_its_licence(self, raw):
        prov = raw["provenance"]
        (src,) = prov["sources"]
        assert src["licence"] == "OGL-UK-3.0"
        assert "Open Government Licence v3.0" in src["attribution"]
        assert "Companies House" in src["attribution"]
        assert len(src["input_sha256"]) == 64
        assert src["records"]["current"] > 5_000_000
        assert src["records"]["previous"] > 500_000

    def test_the_vocabulary_cap_is_recorded_and_lossless(self, gb, raw):
        cap = raw["provenance"]["vocabulary_cap"]
        assert cap["vocabulary_kept"] == gb.vocabulary_size
        assert cap["vocabulary_kept"] < cap["vocabulary_full"]
        # The floor equals the cap, so a dropped token reads as rarity 1.0,
        # which is what it scored before the cap (distinctiveness saturates
        # below rel_freq 1e-5).
        assert raw["unknown_floor"] == cap["min_rel_freq"] == 1e-5
        assert gb.distinctiveness("zzqxnotaword") == 1.0

    def test_it_stays_small(self):
        with gzip.open(str(_RESOURCE), "rb") as fh:
            assert len(fh.read()) < 2_000_000


class TestWhatTheRegisterKnows:
    @pytest.mark.parametrize("token", ["limited", "ltd", "services", "holdings"])
    def test_corporate_boilerplate_is_common(self, gb, token):
        assert gb.distinctiveness(token) < 0.5

    @pytest.mark.parametrize("token", ["academy", "learning", "education"])
    def test_register_common_words_are_commoner_than_gleif_says(self, gb, token):
        gleif = TokenFrequencyTable.default("organisation")
        assert gb.distinctiveness(token) < gleif.distinctiveness(token)

    @pytest.mark.parametrize("token", ["romero", "painsley", "kuapa"])
    def test_distinctive_names_stay_rare(self, gb, token):
        assert gb.distinctiveness(token) >= 0.95


class TestPinsAndDecisions:
    def _run(self, a, b, tf):
        return reconcile([{"id": "a", "name": a}], [{"id": "b", "name": b}],
                         entity="organisation", tf=tf, backend="arche")

    def test_the_string_selected_table_is_pinned_by_its_bytes(self, gb):
        pins = self._run("Acme Ltd", "Acme Limited", "organisation_gb")["pins"]
        assert pins["tf"] == f"shipped:organisation_gb@{gb.version}"

    def test_the_gleif_string_pin_now_names_its_bytes_too(self):
        """Superseded on 2026-10-18, deliberately.

        This test used to assert `shipped:organisation` exactly, because the
        GLEIF table declares no `version` and leaving it that way kept every
        decision id already scored under it stable. That was the right trade
        while the alternative was only tidiness.

        It stopped being the right trade for two reasons. The guarantee was
        already void: pinning the shipped data assets (`data_assets`) moved
        every organisation id in the same session, so there was no stability
        left to protect. And the thing the bare label hides is not cosmetic --
        a token frequency table is a BLOCKING key as well as a comparator
        input, so a rebuilt GLEIF table proposes a different candidate set and
        can reach a different verdict while pinning identically to the table
        it replaced. A pin that cannot distinguish those is not provenance.

        Tables that declare a version still use it, so `organisation_gb` and
        `place` are untouched; only tables that had none gain a derived one.
        """
        pins = self._run("Acme Ltd", "Acme Limited", "organisation")["pins"]
        assert pins["tf"].startswith("shipped:organisation@sha256:")
        # Still the GLEIF table, not the GB one.
        assert not pins["tf"].startswith("shipped:organisation_gb")

    def test_two_distinct_academies_no_longer_match(self):
        """The Exp 000 case: GLEIF says `match` at 0.703, GB says `review`."""
        a, b = "THE ROMERO CATHOLIC ACADEMY", "THE PAINSLEY CATHOLIC ACADEMY"
        (gleif,) = self._run(a, b, "organisation")["matches"]
        (gb,) = self._run(a, b, "organisation_gb")["matches"]
        assert gleif["decision"] == "match"
        assert gb["decision"] == "review"
        assert gb["score"] < gleif["score"]

    def test_one_name_written_twice_still_matches(self):
        (edge,) = self._run("THE ROMERO CATHOLIC ACADEMY", "ROMERO CATHOLIC ACADEMY",
                            "organisation_gb")["matches"]
        assert edge["decision"] == "match"
