# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""A place request: a verified endpoint passes, a contest asks, weak evidence refuses."""
from __future__ import annotations

import datetime as dt

import arche
import pytest
from arche.addr.request import (
    MasterSheet,
    Nominatim,
    Policy,
    resolve_place_request,
    spatial_mentions,
    time_window,
)

TEXT = ("Send my package tomorrow from 123 Maple Street to the blue gate behind "
        "Elim Pharmacy, 124 Elim Streat.")
NOW = dt.date(2026, 9, 13)


@pytest.fixture()
def sheet() -> MasterSheet:
    return MasterSheet([
        {"id": "gci:address:001", "name": "123 Maple Street",
         "address": "123 Maple Street, Ikeja", "lat": 6.60, "lon": 3.35},
        {"id": "gci:address:124e", "name": "124 Elim Street",
         "address": "124 Elim Street, Ikeja", "lat": 6.6010, "lon": 3.3510},
        {"id": "gci:address:124m", "name": "124 Elm Street",
         "address": "124 Elm Street, Ikeja", "lat": 6.6300, "lon": 3.3800},
        {"id": "gci:poi:elim", "name": "Elim Pharmacy",
         "address": "122 Elim Street", "lat": 6.6011, "lon": 3.3511},
    ])


class TestTheMention:
    def test_the_destination_carries_role_relation_reference_access_and_a_typo(self):
        by_role = {m.action_role: m for m in spatial_mentions(TEXT)}
        d = by_role["destination"]
        assert d.relation_kind == "behind"
        assert d.reference_text == "Elim Pharmacy"
        assert d.access_hint == "blue gate"
        assert (d.street_number, d.street) == ("124", "Elim Streat")
        assert d.street_suffix_known is False
        assert "relation:behind" in d.evidence and "access_hint" in d.evidence

    def test_the_origin_is_a_plain_parsed_address(self):
        by_role = {m.action_role: m for m in spatial_mentions(TEXT)}
        o = by_role["origin"]
        assert (o.street_number, o.street) == ("123", "Maple Street")
        assert o.relation_kind is None and o.access_hint is None
        assert o.street_suffix_known is True

    def test_it_is_the_public_type(self):
        assert all(isinstance(m, arche.SpatialMention) for m in spatial_mentions(TEXT))


class TestTheTimeWindow:
    @pytest.mark.parametrize("phrase,date,conf", [
        ("tomorrow", "2026-09-14", "high"),
        ("today", "2026-09-13", "high"),
        ("day after tomorrow", "2026-09-15", "high"),
        ("on Tuesday", "2026-09-15", "high"),      # 2026-09-13 is a Sunday
        ("next Tuesday", "2026-09-22", "medium"),
    ])
    def test_relative_phrases(self, phrase, date, conf):
        w = time_window(f"deliver it {phrase} please", now=NOW)
        assert (w.date, w.confidence) == (date, conf)

    def test_no_phrase_means_no_date_not_today(self):
        assert time_window("deliver it", now=NOW).date is None


class TestTheRequestedExperience:
    def test_the_example_end_to_end(self, sheet):
        r = arche.resolve_place_request(TEXT, action="create_delivery", sources=[sheet], now=NOW)
        d = r.to_dict()
        assert d["time_window"] == {"date": "2026-09-14", "confidence": "high",
                                    "phrase": "tomorrow"}
        # A high-confidence endpoint passes through.
        assert d["origin"]["status"] == "verified"
        assert d["origin"]["place_id"] == "gci:address:001"
        assert "street-number match" in d["origin"]["evidence"]
        # A close contest through a typo becomes one short question, with the
        # runner-up shown and the landmark named.
        assert d["destination"]["status"] == "clarification_required"
        ids = [c["place_id"] for c in d["destination"]["candidates"]]
        assert ids[:2] == ["gci:address:124e", "gci:address:124m"]
        assert "nearby landmark match" in d["destination"]["candidates"][0]["evidence"]
        assert d["destination"]["question"] == \
            "Is the destination 124 Elim Street, next to Elim Pharmacy?"
        # The action is blocked until the destination is confirmed.
        assert d["request"]["status"] == "blocked_pending_destination_confirmation"

    def test_a_clean_destination_is_verified_and_the_request_is_ready(self, sheet):
        r = resolve_place_request("Deliver from 123 Maple Street to 124 Elim Street.",
                                  action="create_delivery", sources=[sheet], now=NOW)
        assert r.destination.status == "verified"
        assert r.destination.chosen.place_id == "gci:address:124e"
        assert r.status == "ready"

    def test_weak_evidence_is_an_honest_refusal(self, sheet):
        r = resolve_place_request("Deliver from 123 Maple Street to 9 Nowhere Road.",
                                  action="create_delivery", sources=[sheet], now=NOW)
        assert r.destination.status == "refused"
        assert r.status == "blocked_destination_refused"

    def test_a_missing_endpoint_is_missing_not_guessed(self, sheet):
        r = resolve_place_request("Deliver to 124 Elim Street.", action="create_delivery",
                                  sources=[sheet], now=NOW)
        assert r.origin.status == "missing"
        assert r.status == "blocked_origin_missing"

    def test_the_typo_policy_can_be_turned_off(self, sheet):
        r = resolve_place_request(TEXT, action="create_delivery", sources=[sheet], now=NOW,
                                  policy=Policy(confirm_typo_matches=False))
        # Without the typo rule the landmark-backed candidate clears the bar.
        assert r.destination.status == "verified"

    def test_no_sources_means_every_endpoint_is_refused(self):
        r = resolve_place_request(TEXT, action="create_delivery", sources=[], now=NOW)
        assert r.origin.status == "refused" and r.destination.status == "refused"


class TestNominatimIsOptInAndOffline:
    def test_offline_answers_nothing_rather_than_failing(self, monkeypatch):
        monkeypatch.setenv("ARCHE_OFFLINE", "1")
        (m,) = [m for m in spatial_mentions(TEXT) if m.action_role == "origin"]
        assert Nominatim().candidates(m) == []

    def test_a_stubbed_hit_becomes_a_candidate_with_evidence(self, monkeypatch):
        src = Nominatim()
        monkeypatch.setattr(src, "_get", lambda params: [{
            "osm_type": "way", "osm_id": 42, "display_name": "123 Maple Street, Ikeja, Lagos",
            "lat": "6.6", "lon": "3.35",
            "address": {"house_number": "123", "road": "Maple Street"}}])
        (m,) = [m for m in spatial_mentions(TEXT) if m.action_role == "origin"]
        (c,) = src.candidates(m)
        assert c.place_id == "osm:way:42"
        assert {"street-number match", "street match"} <= set(c.evidence)
        assert c.confidence >= 0.9


class TestTheReceipt:
    """P1.4: a resolved endpoint is a decision -- an id, a ledger row, explain, replay."""

    def test_every_endpoint_has_an_id_with_its_own_prefix(self, sheet):
        r = resolve_place_request(TEXT, action="create_delivery", sources=[sheet], now=NOW)
        for ep in r.endpoints.values():
            assert ep.decision_id and ep.decision_id.startswith("plc:sha256:")
        assert r.origin.decision_id != r.destination.decision_id

    def test_the_same_reading_against_the_same_sheet_is_the_same_id(self, sheet):
        a = resolve_place_request(TEXT, action="create_delivery", sources=[sheet], now=NOW)
        b = resolve_place_request(TEXT, action="create_delivery", sources=[sheet], now=NOW)
        assert a.destination.decision_id == b.destination.decision_id

    def test_a_changed_sheet_changes_the_id_even_when_the_status_does_not(self, sheet):
        a = resolve_place_request(TEXT, action="create_delivery", sources=[sheet], now=NOW)
        more = MasterSheet([*sheet.records, {"id": "gci:address:124y", "name": "124 Elim Street",
                                             "address": "124 Elim Street, Yaba",
                                             "lat": 6.51, "lon": 3.38}])
        b = resolve_place_request(TEXT, action="create_delivery", sources=[more], now=NOW)
        assert a.destination.status == b.destination.status == "clarification_required"
        assert a.destination.decision_id != b.destination.decision_id
        assert a.destination.pins["sources"] != b.destination.pins["sources"]

    def test_a_changed_policy_changes_the_id(self, sheet):
        a = resolve_place_request(TEXT, action="create_delivery", sources=[sheet], now=NOW)
        b = resolve_place_request(TEXT, action="create_delivery", sources=[sheet], now=NOW,
                                  policy=Policy(verified_at=0.9))
        assert a.origin.decision_id != b.origin.decision_id

    def test_the_span_is_not_in_the_id(self, sheet):
        a = resolve_place_request(TEXT, action="create_delivery", sources=[sheet], now=NOW)
        b = resolve_place_request("Please " + TEXT, action="create_delivery",
                                  sources=[sheet], now=NOW)
        assert a.destination.decision_id == b.destination.decision_id

    def test_recorded_explained_and_replayed(self, sheet, tmp_path):
        pytest.importorskip("duckdb")
        ledger = arche.attach(f"duckdb:///{tmp_path / 'l.duckdb'}")
        r = resolve_place_request(TEXT, action="create_delivery", sources=[sheet], now=NOW,
                                  store=ledger)
        d = ledger.decision(r.destination.decision_id)
        assert d.verb == "place" and d.identity == "clarification_required" and d.action == "ask"
        assert d.factors["gci:address:124e"] == 1.0
        o = ledger.decision(r.origin.decision_id)
        assert o.identity == "verified" and o.action == "gci:address:001"

        why = ledger.explain(r.destination.decision_id)
        assert why["verb"] == "place" and why["role"] == "destination"
        assert why["read"]["reference_text"] == "Elim Pharmacy"
        assert why["why"] == "Is the destination 124 Elim Street, next to Elim Pharmacy?"
        assert [c["place_id"] for c in why["candidates"]][:2] == \
            ["gci:address:124e", "gci:address:124m"]

        rp = ledger.replay(r.destination.decision_id)
        assert rp.reproduced is True and rp.changed == {}

    def test_recording_twice_is_idempotent(self, sheet, tmp_path):
        pytest.importorskip("duckdb")
        ledger = arche.attach(f"duckdb:///{tmp_path / 'l.duckdb'}")
        resolve_place_request(TEXT, action="create_delivery", sources=[sheet], now=NOW,
                              store=ledger)
        again = ledger.record_place_request(
            resolve_place_request(TEXT, action="create_delivery", sources=[sheet], now=NOW),
            sources=[sheet], now=NOW)
        assert len(again) == 2

    def test_a_live_geocoder_is_recorded_as_unreplayable(self, sheet, tmp_path, monkeypatch):
        pytest.importorskip("duckdb")
        monkeypatch.setenv("ARCHE_OFFLINE", "1")
        ledger = arche.attach(f"duckdb:///{tmp_path / 'l.duckdb'}")
        r = resolve_place_request(TEXT, action="create_delivery",
                                  sources=[sheet, Nominatim()], now=NOW, store=ledger)
        assert "nominatim:" in r.origin.pins["sources"][1]
        with pytest.raises(ValueError, match="re-verified from its signed receipt"):
            ledger.replay(r.origin.decision_id)


class TestTheRelationUsed:
    """P1.2: a landmark that says which way it faces turns `behind` into geometry."""

    @pytest.fixture()
    def corner(self) -> MasterSheet:
        # Elim Pharmacy faces north. 12 Back Lane is 55 m due south (behind it),
        # 7 Front Road 55 m due north (in front), 3 Side Close 55 m due east.
        return MasterSheet([
            {"id": "poi", "kind": "landmark", "name": "Elim Pharmacy",
             "lat": 6.6000, "lon": 3.3500, "front_bearing": 0},
            {"id": "back", "name": "12 Back Lane", "lat": 6.5995, "lon": 3.3500},
            {"id": "front", "name": "7 Front Road", "lat": 6.6005, "lon": 3.3500},
            {"id": "side", "name": "3 Side Close", "lat": 6.6000, "lon": 3.3505},
        ])

    @staticmethod
    def _ask(sheet, phrase):
        r = resolve_place_request(f"Send it from 7 Front Road to {phrase}.",
                                  action="create_delivery", sources=[sheet], now=NOW)
        return r.destination

    def test_behind_puts_the_far_side_first_and_counts_the_front_against(self, corner):
        ep = self._ask(corner, "behind Elim Pharmacy")
        ids = [c.place_id for c in ep.candidates]
        assert ids[0] == "back" and ids[-1] == "front"
        assert "relation geometry agrees" in ep.candidates[0].evidence
        assert "relation geometry disagrees" in ep.candidates[-1].evidence
        assert ep.status == "clarification_required"     # an informal address is a question
        assert ep.question == "Is the destination 12 Back Lane, next to Elim Pharmacy?"

    @pytest.mark.parametrize("phrase, first", [
        ("opposite Elim Pharmacy", "front"),
        ("in front of Elim Pharmacy", "front"),
        ("next to Elim Pharmacy", "side"),
        ("beside Elim Pharmacy", "side"),
    ])
    def test_each_relation_names_its_side(self, corner, phrase, first):
        assert self._ask(corner, phrase).candidates[0].place_id == first

    def test_near_says_nothing_about_a_side(self, corner):
        ep = self._ask(corner, "near Elim Pharmacy")
        assert not any("geometry" in e for c in ep.candidates for e in c.evidence)

    def test_without_a_bearing_the_relation_is_proximity_only(self, corner):
        rows = [dict(r) for r in corner.records]
        rows[0].pop("front_bearing")
        ep = self._ask(MasterSheet(rows), "behind Elim Pharmacy")
        assert not any("geometry" in e for c in ep.candidates for e in c.evidence)
        assert {c.evidence for c in ep.candidates} == {("nearby landmark match",)}

    def test_a_written_address_outranks_a_relation_that_disagrees(self, corner):
        ep = self._ask(corner, "7 Front Road behind Elim Pharmacy")
        assert ep.status == "verified" and ep.chosen.place_id == "front"
        assert "relation geometry disagrees" in ep.chosen.evidence

    def test_geometry_is_in_the_receipt(self, corner):
        a = self._ask(corner, "behind Elim Pharmacy")
        rows = [dict(r) for r in corner.records]
        rows[0]["front_bearing"] = 180
        b = self._ask(MasterSheet(rows), "behind Elim Pharmacy")
        assert a.decision_id != b.decision_id and b.candidates[0].place_id == "front"


class TestWhichNumber:
    """A street with no number is a missing field, not a contest between three of a dozen doors."""

    @pytest.fixture()
    def street(self) -> MasterSheet:
        return MasterSheet([
            {"id": "m7", "name": "7 Marina", "lat": 6.45, "lon": 3.40},
            {"id": "a12", "name": "12 Awolowo Way", "lat": 6.60, "lon": 3.35},
            {"id": "a30", "name": "30 Awolowo Way", "lat": 6.60, "lon": 3.35},
            {"id": "a45", "name": "45 Awolowo Way", "lat": 6.60, "lon": 3.35},
            {"id": "a58", "name": "58 Awolowo Way", "lat": 6.60, "lon": 3.35},
            {"id": "e14", "name": "14 Elim Street", "lat": 6.61, "lon": 3.36},
            {"id": "e20", "name": "20 Elim Street", "lat": 6.61, "lon": 3.36},
            {"id": "l16", "name": "16 Elm Street", "lat": 6.61, "lon": 3.36},
        ])

    def test_a_bare_street_asks_for_the_number(self, street):
        r = resolve_place_request("Send it from 7 Marina to Awolowo Way.",
                                  action="create_delivery", sources=[street], now=NOW)
        ep = r.destination
        assert ep.status == "clarification_required" and ep.question_kind == "number"
        assert ep.question == "Which number on Awolowo Way is the destination?"
        assert ep.to_dict()["question_kind"] == "number"
        assert all("street match" in c.evidence for c in ep.candidates)

    def test_a_misspelt_bare_street_with_a_confusable_neighbour_asks_both(self, street):
        r = resolve_place_request("Send it from 7 Marina to Elim Streat.",
                                  action="create_delivery", sources=[street], now=NOW)
        ep = r.destination
        assert ep.question_kind == "number"
        assert ep.question == ("Which number is the destination, and is it Elim Street "
                               "or Elm Street?")

    def test_one_door_on_the_street_is_a_confirm_question_not_a_number(self, street):
        rows = [r for r in street.records if r["id"] in ("m7", "a12")]
        r = resolve_place_request("Send it from 7 Marina to Awolowo Way.",
                                  action="create_delivery", sources=[MasterSheet(rows)], now=NOW)
        assert r.destination.question_kind == "confirm"
        assert r.destination.question == "Is the destination 12 Awolowo Way?"

    def test_the_question_kind_is_in_the_receipt(self, street):
        r = resolve_place_request("Send it from 7 Marina to Awolowo Way.",
                                  action="create_delivery", sources=[street], now=NOW)
        rows = [r for r in street.records if r["id"] in ("m7", "a12")]
        one = resolve_place_request("Send it from 7 Marina to Awolowo Way.",
                                    action="create_delivery", sources=[MasterSheet(rows)],
                                    now=NOW)
        assert r.destination.decision_id != one.destination.decision_id

