# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Tests for the Nominatim evidence adapter.

No network. Every test injects ``fetch=``, which is also how the adapter is
meant to be used against a recorded cassette.

The tests that matter are the boundaries: an adapter must not return a merge
decision, must not let ODbL data into the packs, and must not quietly become a
bulk geocoder against a donated service.
"""

from __future__ import annotations

import pytest

from arche.adapters import OPEN_LICENCE_CLASSES, ProviderEvidence
from arche.adapters.nominatim import NOMINATIM_LICENCE, NominatimError, verify_place

WHEN = "2026-08-08T12:00:00Z"
UA = "arche-tests/0.3 (connect@unpatterned.org)"

# Karfi, Bunkure LGA, Kano.
_KARFI = [
    {
        "display_name": "Karfi, Bunkure, Kano, Nigeria",
        "lat": "11.62192",
        "lon": "8.49279",
        "category": "place",
        "type": "village",
        "osm_id": 1234,
        "importance": 0.35,
    }
]


def _fetch(payload):
    def _f(url, params, headers):
        assert "User-Agent" in headers, "Nominatim policy requires a User-Agent"
        return payload

    return _f


class TestVerdicts:
    def test_nearby_gazetteer_hit_corroborates(self):
        ev = verify_place(
            "Karfi Health Post", 11.62192, 8.49279,
            retrieved_at=WHEN, user_agent=UA, fetch=_fetch(_KARFI),
        )
        assert ev.verdict == "corroborates"
        assert ev.detail["nearest_km"] < 0.1

    def test_distant_gazetteer_hit_contradicts(self):
        ev = verify_place(
            "Karfi Health Post", 12.9, 9.6,
            retrieved_at=WHEN, user_agent=UA, fetch=_fetch(_KARFI),
        )
        assert ev.verdict == "contradicts"
        assert ev.detail["nearest_km"] > 10

    def test_no_candidates_is_inconclusive_not_contradicts(self):
        """Silence is not disagreement.

        A gazetteer that has never heard of a rural health post says nothing
        about whether the merge is right.
        """
        ev = verify_place(
            "Nowhere Health Post", 11.6, 8.5,
            retrieved_at=WHEN, user_agent=UA, fetch=_fetch([]),
        )
        assert ev.verdict == "inconclusive"
        assert "no candidates" in ev.detail["reason"]

    def test_no_claimed_position_is_inconclusive(self):
        ev = verify_place("Karfi", retrieved_at=WHEN, user_agent=UA, fetch=_fetch(_KARFI))
        assert ev.verdict == "inconclusive"

    def test_tolerance_is_configurable(self):
        near = verify_place(
            "Karfi", 11.7, 8.5, retrieved_at=WHEN, user_agent=UA,
            tolerance_km=50, fetch=_fetch(_KARFI),
        )
        strict = verify_place(
            "Karfi", 11.7, 8.5, retrieved_at=WHEN, user_agent=UA,
            tolerance_km=1, fetch=_fetch(_KARFI),
        )
        assert near.verdict == "corroborates"
        assert strict.verdict == "contradicts"


class TestNotADecision:
    """An adapter may not have an opinion about identity."""

    def test_verdict_vocabulary_excludes_merge_language(self):
        ev = verify_place(
            "Karfi", 11.62, 8.49, retrieved_at=WHEN, user_agent=UA, fetch=_fetch(_KARFI)
        )
        assert ev.verdict in ("corroborates", "contradicts", "inconclusive")

    def test_evidence_has_no_score_or_decision_field(self):
        ev = verify_place(
            "Karfi", 11.62, 8.49, retrieved_at=WHEN, user_agent=UA, fetch=_fetch(_KARFI)
        )
        assert not hasattr(ev, "decision")
        assert not hasattr(ev, "score")


class TestProvenanceFirewall:
    def test_odbl_evidence_may_not_enter_packs(self):
        ev = verify_place(
            "Karfi", 11.62, 8.49, retrieved_at=WHEN, user_agent=UA, fetch=_fetch(_KARFI)
        )
        assert ev.licence == NOMINATIM_LICENCE
        assert ev.may_enter_packs is False
        assert NOMINATIM_LICENCE not in OPEN_LICENCE_CLASSES

    def test_an_unknown_licence_class_is_rejected(self):
        with pytest.raises(ValueError, match="licence class"):
            ProviderEvidence(
                provider="x", query="q", verdict="inconclusive",
                retrieved_at=WHEN, licence="whatever-i-like",
                response_sha256="0" * 64,
            )

    def test_pin_declares_the_decision_unreproducible(self):
        """A decision resting on a live API response cannot be world-replayed,
        and the pin must say so rather than imply determinism."""
        ev = verify_place(
            "Karfi", 11.62, 8.49, retrieved_at=WHEN, user_agent=UA, fetch=_fetch(_KARFI)
        )
        pin = ev.pin()
        assert pin["reproducible"] is False
        assert pin["provider"] == "nominatim"
        assert pin["retrieved_at"] == WHEN
        assert len(pin["response_sha256"]) == 64

    def test_response_hash_is_canonical(self):
        """Key order must not change the digest — the caller keeps the payload
        and the attestation pins the hash, so the two have to agree."""
        a = verify_place(
            "K", 1, 1, retrieved_at=WHEN, user_agent=UA,
            fetch=_fetch([{"lat": "1", "lon": "1", "display_name": "x"}]),
        )
        b = verify_place(
            "K", 1, 1, retrieved_at=WHEN, user_agent=UA,
            fetch=_fetch([{"display_name": "x", "lon": "1", "lat": "1"}]),
        )
        assert a.response_sha256 == b.response_sha256


class TestUsagePolicy:
    def test_missing_user_agent_is_refused(self):
        with pytest.raises(ValueError, match="user_agent is required"):
            verify_place("Karfi", retrieved_at=WHEN, user_agent="", fetch=_fetch(_KARFI))

    def test_whitespace_user_agent_is_refused(self):
        with pytest.raises(ValueError, match="user_agent is required"):
            verify_place("Karfi", retrieved_at=WHEN, user_agent="   ", fetch=_fetch(_KARFI))


class TestRobustness:
    def test_malformed_candidates_are_dropped_not_fatal(self):
        payload = [
            {"display_name": "good", "lat": "11.62", "lon": "8.49"},
            {"display_name": "bad", "lat": "not-a-number", "lon": "8.49"},
            {"display_name": "missing lon", "lat": "11.62"},
        ]
        ev = verify_place(
            "Karfi", 11.62, 8.49, retrieved_at=WHEN, user_agent=UA, fetch=_fetch(payload)
        )
        assert ev.detail["candidate_count"] == 1
        assert ev.verdict == "corroborates"

    def test_non_list_payload_raises_clearly(self):
        with pytest.raises(NominatimError, match="expected a JSON array"):
            verify_place(
                "Karfi", retrieved_at=WHEN, user_agent=UA,
                fetch=_fetch({"error": "rate limited"}),
            )


class TestEgress:
    def test_guard_is_consulted_before_anything_leaves(self):
        calls = []

        class _Guard:
            def check(self, value, *, provider):
                calls.append((value, provider))

        verify_place(
            "Karfi Health Post", 11.62, 8.49, retrieved_at=WHEN,
            user_agent=UA, guard=_Guard(), fetch=_fetch(_KARFI),
        )
        assert calls == [("Karfi Health Post", "nominatim")]

    def test_a_refusing_guard_prevents_the_request(self):
        sent = []

        class _Deny:
            def check(self, value, *, provider):
                raise PermissionError("statute forbids transfer")

        def _spy(url, params, headers):
            sent.append(url)
            return _KARFI

        with pytest.raises(PermissionError):
            verify_place(
                "Adesola Okonkwo, 12 Example Road", 11.6, 8.5,
                retrieved_at=WHEN, user_agent=UA, guard=_Deny(), fetch=_spy,
            )
        assert sent == [], "nothing may leave when the guard refuses"
