# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Credentials over reconcile decisions: what must verify, and what must not."""

from __future__ import annotations

import base64
import json

import pytest
from arche.credentials import (
    CredentialError,
    build_credential,
    criterion_digest,
    issue,
    sign_label,
    verify_credential,
)
from arche.resolve import reconcile
from arche.sign import generate_keypair, sign

CRITERION = criterion_digest("Site: the same production site. A company is operated_by a site.")
SITE = {"id": "s1", "name": "Kestrel Baking - Bolton", "address": "Moss Lane, Bolton BL4 8NB"}
COMPANY = {"id": "01234567", "name": "KESTREL BAKING LIMITED",
           "address": "Moss Lane, Bolton, BL4 8NB"}


def _run(relation="operated_by", b=COMPANY):
    out = reconcile([SITE], [b], entity="organisation", id_field="id", relation=relation)
    return out["matches"][0], out["pins"]


def _cred(level="machine", label=None, **kw):
    edge, pins = _run()
    return build_credential(
        edge, pins, subject={"scheme": "example-sites", "id": "s1"},
        obj={"scheme": "gb-companies-house", "id": "01234567"},
        level=level, issuer=kw.pop("issuer", ISSUER.did_key), criterion=CRITERION,
        label_jws=label, **kw)


ISSUER = generate_keypair()
REVIEWER = generate_keypair()


def _payload(token):
    seg = token.split(".")[1]
    return json.loads(base64.urlsafe_b64decode(seg + "=" * (-len(seg) % 4)))


def _resign(cred):
    return sign(cred, ISSUER.private_key, kid=ISSUER.did_key, typ="vc+jwt")


class TestRoundTrip:
    def test_machine_credential_verifies_and_is_trusted_with_the_issuer_key(self):
        edge, _ = _run()
        assert edge["decision"] == "match"
        token = issue(_cred(), ISSUER)
        check = verify_credential(token, issuer_key=ISSUER.public_key)
        assert check.ok and check.issuer_trusted, check.problems
        assert check.credential["type"] == ["VerifiableCredential", "OperatorCredential"]

    def test_without_a_supplied_key_it_verifies_but_is_not_trusted(self):
        check = verify_credential(issue(_cred(), ISSUER))
        assert check.ok and not check.issuer_trusted

    def test_carries_ids_and_numbers_never_names_or_addresses(self):
        text = json.dumps(_cred())
        for raw in ("Kestrel", "KESTREL", "Moss Lane", "BL4"):
            assert raw not in text

    def test_adjudicated_credential_checks_the_reviewer(self):
        edge, pins = _run()
        did = build_credential(edge, pins, subject={"scheme": "x", "id": "s1"},
                               obj={"scheme": "y", "id": "01234567"}, level="machine",
                               issuer=ISSUER.did_key, criterion=CRITERION
                               )["credentialSubject"]["decision"]["decisionId"]
        label = sign_label(REVIEWER, decision_id=did, label="operated_by", criterion=CRITERION)
        token = issue(_cred("adjudicated", label), ISSUER)
        check = verify_credential(token, issuer_key=ISSUER.public_key,
                                  reviewer_keys={REVIEWER.did_key: REVIEWER.public_key})
        assert check.ok and check.label_valid and check.label_trusted, check.problems
        untrusted = verify_credential(token, issuer_key=ISSUER.public_key)
        assert untrusted.ok and untrusted.label_trusted is False

    def test_a_reviewer_can_issue_a_non_identity_credential(self):
        edge, pins = _run()
        did = edge["decision_id"]
        label = sign_label(REVIEWER, decision_id=did, label="none_of_these",
                           criterion=CRITERION)
        cred = _cred("adjudicated", label)
        assert cred["type"][1] == "NonIdentityCredential"
        assert verify_credential(issue(cred, ISSUER), issuer_key=ISSUER.public_key).ok


class TestTamperingFails:
    def test_a_changed_pin(self):
        cred = _cred()
        cred["credentialSubject"]["decision"]["pins"]["thresholds"] = {"match": 0.1}
        check = verify_credential(_resign(cred), issuer_key=ISSUER.public_key)
        assert check.signature_valid and not check.decision_id_ok and not check.ok

    def test_a_changed_subject(self):
        cred = _cred()
        cred["credentialSubject"]["object"]["id"] = "99999999"
        check = verify_credential(_resign(cred), issuer_key=ISSUER.public_key)
        assert not check.ok

    def test_an_edited_token_without_resigning(self):
        token = issue(_cred(), ISSUER)
        head, body, sig = token.split(".")
        cred = _payload(token)
        cred["credentialSubject"]["claim"] = "same_as"
        forged = base64.urlsafe_b64encode(json.dumps(cred).encode()).decode().rstrip("=")
        assert not verify_credential(f"{head}.{forged}.{sig}",
                                     issuer_key=ISSUER.public_key).signature_valid

    def test_another_key_claiming_the_issuer(self):
        mallory = generate_keypair()
        token = sign(_cred(), mallory.private_key, kid=mallory.did_key, typ="vc+jwt")
        assert not verify_credential(token).ok
        assert not verify_credential(token, issuer_key=ISSUER.public_key).signature_valid

    def test_raising_the_level_without_a_label(self):
        cred = _cred()
        cred["credentialSubject"]["decision"]["level"] = "adjudicated"
        assert not verify_credential(_resign(cred), issuer_key=ISSUER.public_key).ok

    def test_relabelling_a_claim_the_reviewer_did_not_make(self):
        edge, _ = _run()
        label = sign_label(REVIEWER, decision_id=edge["decision_id"], label="none_of_these",
                           criterion=CRITERION)
        cred = _cred("adjudicated", label)
        cred["credentialSubject"]["claim"] = "operated_by"
        cred["type"][1] = "OperatorCredential"
        assert not verify_credential(_resign(cred), issuer_key=ISSUER.public_key).ok

    def test_expired(self):
        token = issue(_cred(valid_until="2027-01-01T00:00:00Z"), ISSUER)
        check = verify_credential(token, issuer_key=ISSUER.public_key,
                                  now="2027-06-01T00:00:00Z")
        assert not check.current and not check.ok


class TestRefusesToBuild:
    def test_a_machine_credential_over_a_review(self):
        # The country words refute (UK site vs an Irish company): review.
        site = {**SITE, "name": "Kestrel Baking UK - Bolton"}
        other = {**COMPANY, "name": "KESTREL BAKING (IRELAND) LIMITED"}
        out = reconcile([site], [other], entity="organisation", id_field="id",
                        relation="operated_by")
        edge, pins = out["matches"][0], out["pins"]
        assert edge["decision"] != "match"
        with pytest.raises(CredentialError, match="asserts a link"):
            build_credential(edge, pins, subject={"scheme": "x", "id": "s1"},
                             obj={"scheme": "y", "id": "01234567"}, level="machine",
                             issuer=ISSUER.did_key, criterion=CRITERION)

    def test_a_label_for_another_decision_or_criterion(self):
        wrong_id = sign_label(REVIEWER, decision_id="xwd:sha256:00", label="operated_by",
                              criterion=CRITERION)
        with pytest.raises(CredentialError, match="different decision"):
            _cred("adjudicated", wrong_id)
        edge, _ = _run()
        wrong_crit = sign_label(REVIEWER, decision_id=edge["decision_id"],
                                label="operated_by", criterion=criterion_digest("other"))
        with pytest.raises(CredentialError, match="different criterion"):
            _cred("adjudicated", wrong_crit)

    def test_a_reviewer_relation_the_run_did_not_decide(self):
        edge, _ = _run()
        label = sign_label(REVIEWER, decision_id=edge["decision_id"], label="same_as",
                           criterion=CRITERION)
        with pytest.raises(CredentialError, match="run decided"):
            _cred("adjudicated", label)

    def test_cannot_tell_asserts_nothing(self):
        edge, _ = _run()
        label = sign_label(REVIEWER, decision_id=edge["decision_id"], label="cannot_tell",
                           criterion=CRITERION)
        with pytest.raises(CredentialError, match="asserts nothing"):
            _cred("adjudicated", label)

    def test_attested_needs_a_resolvable_issuer_and_fresh_references(self):
        edge, _ = _run()
        label = sign_label(REVIEWER, decision_id=edge["decision_id"], label="operated_by",
                           criterion=CRITERION)
        with pytest.raises(CredentialError, match="resolvable identity"):
            _cred("attested", label)
        with pytest.raises(CredentialError, match="snapshot dates"):
            _cred("attested", label, issuer="did:web:attest.example.org")

    def test_an_edge_carrying_raw_fields(self):
        edge, pins = _run()
        with pytest.raises(CredentialError, match="must not"):
            build_credential({**edge, "a_name": "Kestrel"}, pins,
                             subject={"scheme": "x", "id": "s1"},
                             obj={"scheme": "y", "id": "01234567"}, level="machine",
                             issuer=ISSUER.did_key, criterion=CRITERION)

    def test_ids_that_are_not_the_decided_pair(self):
        edge, pins = _run()
        with pytest.raises(CredentialError, match="a_id/b_id"):
            build_credential(edge, pins, subject={"scheme": "x", "id": "s2"},
                             obj={"scheme": "y", "id": "01234567"}, level="machine",
                             issuer=ISSUER.did_key, criterion=CRITERION)
