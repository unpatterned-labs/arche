# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""`arche.attest`: a signed envelope over one answer.

The claims worth pinning: the envelope binds tool, inputs, response and
decision ids; an edit to any of them is caught; a key the verifier did not
supply is valid but never trusted; nothing in the envelope is a value.
"""

from __future__ import annotations

import json

import pytest

from arche.attest import (
    ATTESTATION_SCHEMA,
    attest,
    decision_ids_in,
    signing_key,
    verify_attestation,
)
from arche.sign import generate_keypair

INPUTS = {"a": {"name": "Adaeze Okonkwo", "phone": "+2348031234567"},
          "b": {"name": "Adaeze Okonkwo", "phone": "0803 123 4567"}}
DID = "dec:sha256:" + "ab" * 32
RESPONSE = {"identity": "same_entity", "score": 1.0, "decision_id": DID,
            "nested": [{"decision_id": "xwd:sha256:" + "cd" * 32}, {"decision_id": "not-an-id"}]}


@pytest.fixture(scope="module")
def key():
    return generate_keypair()


class TestTheEnvelope:
    def test_binds_the_four_things(self, key):
        env = attest("compare", INPUTS, RESPONSE, keypair=key, caller="svc:billing")
        assert env["schema"] == ATTESTATION_SCHEMA
        assert env["tool"] == "compare"
        assert env["caller"] == "svc:billing"
        assert env["signer"] == key.did_key
        assert env["decision_ids"] == sorted([DID, "xwd:sha256:" + "cd" * 32])
        assert env["jws"].count(".") == 2

    def test_carries_no_value(self, key):
        env = attest("compare", INPUTS, RESPONSE, keypair=key)
        dumped = json.dumps(env)
        assert "Adaeze" not in dumped and "0803" not in dumped

    def test_decision_ids_are_found_wherever_they_sit(self):
        assert decision_ids_in({"decision_ids": [DID, "junk"], "x": {"decision_id": DID}}) == [DID]
        assert decision_ids_in({"decision_id": "not-an-id"}) == []
        assert decision_ids_in("just a string") == []

    def test_the_caller_may_name_the_ids(self, key):
        env = attest("t", {}, {}, keypair=key, decision_ids=[DID, DID])
        assert env["decision_ids"] == [DID]

    def test_a_reserialised_response_hashes_the_same(self, key):
        env = attest("compare", INPUTS, RESPONSE, keypair=key)
        again = json.loads(json.dumps(RESPONSE))  # key order and float form may differ
        assert verify_attestation(env, response=again, public_key=key.public_key).response_match


class TestVerifying:
    def test_pinned_key_is_trusted_and_ok(self, key):
        env = attest("compare", INPUTS, RESPONSE, keypair=key)
        check = verify_attestation(env, inputs=INPUTS, response=RESPONSE, public_key=key.public_key)
        assert check.ok and check.valid and check.trusted
        assert check.inputs_match is True and check.response_match is True
        assert check.signer == key.did_key and check.tool == "compare"
        assert check.problems == []

    def test_a_did_key_string_pins_too(self, key):
        env = attest("t", {}, {}, keypair=key)
        assert verify_attestation(env, public_key=key.did_key).trusted

    def test_self_asserted_is_valid_but_never_trusted(self, key):
        env = attest("compare", INPUTS, RESPONSE, keypair=key)
        check = verify_attestation(env, inputs=INPUTS, response=RESPONSE)
        assert check.ok and check.valid
        assert check.trusted is False

    def test_the_wrong_key_fails(self, key):
        env = attest("t", INPUTS, RESPONSE, keypair=key)
        other = generate_keypair()
        check = verify_attestation(env, public_key=other.public_key)
        assert not check.valid and not check.ok
        assert check.problems and "signature" in check.problems[0]

    def test_an_edited_response_is_caught(self, key):
        env = attest("compare", INPUTS, RESPONSE, keypair=key)
        edited = {**RESPONSE, "identity": "different"}
        check = verify_attestation(env, inputs=INPUTS, response=edited, public_key=key.public_key)
        assert check.valid and check.inputs_match is True
        assert check.response_match is False and not check.ok
        assert any("response" in p for p in check.problems)

    def test_edited_inputs_are_caught(self, key):
        env = attest("compare", INPUTS, RESPONSE, keypair=key)
        edited = {**INPUTS, "b": {"name": "Someone Else"}}
        check = verify_attestation(env, inputs=edited, public_key=key.public_key)
        assert check.inputs_match is False and not check.ok

    def test_the_plain_fields_cannot_be_rewritten_around_the_jws(self, key):
        """The readable fields repeat the signed body; a reader may trust the
        wrong one, so a disagreement between them is itself a failure."""
        env = attest("compare", INPUTS, RESPONSE, keypair=key)
        forged = {**env, "tool": "deidentify", "decision_ids": []}
        check = verify_attestation(forged, public_key=key.public_key)
        assert not check.valid
        assert check.tool == "compare"  # what was signed, not what was written
        assert len([p for p in check.problems if "envelope field" in p]) == 2

    def test_no_jws_is_not_valid(self):
        check = verify_attestation({"tool": "t"})
        assert not check.valid and check.problems == ["no jws in the envelope"]

    def test_unsupplied_sides_are_none_not_false(self, key):
        env = attest("t", INPUTS, RESPONSE, keypair=key)
        check = verify_attestation(env, public_key=key.public_key)
        assert check.inputs_match is None and check.response_match is None and check.ok

    def test_as_dict_is_json(self, key):
        env = attest("t", INPUTS, RESPONSE, keypair=key)
        json.dumps(verify_attestation(env, public_key=key.public_key).as_dict())


class TestTheKey:
    def test_none_when_nothing_is_configured(self, monkeypatch):
        monkeypatch.delenv("ARCHE_SIGNING_KEY", raising=False)
        assert signing_key() is None

    def test_loaded_from_the_env_var(self, tmp_path, monkeypatch, key):
        from arche.sign import save_private_key
        path = tmp_path / "k.pem"
        save_private_key(key, path)
        monkeypatch.setenv("ARCHE_SIGNING_KEY", str(path))
        assert signing_key().did_key == key.did_key
        assert signing_key(path).did_key == key.did_key

    def test_a_missing_file_names_keygen(self, tmp_path):
        with pytest.raises(FileNotFoundError, match="arche attest keygen"):
            signing_key(tmp_path / "nope.pem")
