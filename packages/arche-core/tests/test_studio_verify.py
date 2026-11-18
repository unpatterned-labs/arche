# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Studio's Verify recomputes both id contracts.

It used to apply only the pairwise one (`dec:`), so every signed reconcile
edge (`xwd:`) -- including the one its own "Sign one to try" button makes --
came back "Identifier cannot be recomputed", when the signed payload carries
exactly what the id is hashed over. The check that catches an id lifted from a
more favourable decision never ran on the decisions people actually sign.
"""

from __future__ import annotations

from arche._studio import _verify
from arche.ids import EDGE_SCHEMA, edge_decision_id
from arche.resolve import reconcile
from arche.resolve.reconcile import sign_edges
from arche.sign import generate_keypair
from arche.sign import sign as jws_sign

_A = [{"id": "a", "name": "Karfi Health Post", "lat": "12.0421", "lon": "8.5231"}]
_B = [{"id": "b", "name": "Karfi Primary Health Centre", "lat": "12.0605",
       "lon": "8.5188"}]


def _signed_edge():
    kp = generate_keypair()
    result = reconcile(_A, _B, entity="place", id_field="id")
    signed = sign_edges(result, private_key=kp.private_key, kid=kp.did_key)
    assert signed, "the demo pair should produce a signable edge"
    return kp, result, signed[0]


def test_a_signed_reconcile_edge_recomputes():
    _, _, edge = _signed_edge()
    report = _verify({"jws": edge["jws"]})
    assert report["signature"]["valid"] is True
    assert report["recompute"]["possible"] is True
    assert report["recompute"]["contract"] == "reconcile edge"
    assert report["recompute"]["agrees"] is True
    assert report["recompute"]["recomputed"] == edge["decision_id"]


def test_an_id_lifted_from_another_decision_is_caught():
    # Validly signed, so the signature check passes -- which is exactly why
    # the recompute has to exist: the claimed id addresses different evidence.
    kp, result, _ = _signed_edge()
    edge = dict(result["matches"][0])
    payload = {"schema": EDGE_SCHEMA, **edge, "pins": result["pins"]}
    payload["score"] = 0.9999
    token = jws_sign(payload, kp.private_key, kid=kp.did_key, typ="arche+jws")
    report = _verify({"jws": token})
    assert report["signature"]["valid"] is True
    assert report["recompute"]["possible"] is True
    assert report["recompute"]["agrees"] is False


def test_the_engine_and_the_verifier_share_one_contract():
    _, result, _ = _signed_edge()
    edge = result["matches"][0]
    assert edge_decision_id(edge, result["pins"]) == edge["decision_id"]


def test_an_unknown_shape_is_still_reported_not_passed():
    kp = generate_keypair()
    token = jws_sign({"hello": "world"}, kp.private_key, kid=kp.did_key)
    report = _verify({"jws": token})
    assert report["recompute"]["possible"] is False
