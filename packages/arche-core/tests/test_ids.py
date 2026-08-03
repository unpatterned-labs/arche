# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Golden-vector + property tests for content-addressed ids (`arche.ids`).

Locks the reproducibility contract (§5.1): canonical JSON with no raw floats,
NFKD normalisation, keyless reproducible ids, and a keyed HMAC entity_id.
"""

import pytest
from arche.canonical import Reference
from arche.ids import (
    canonical_json,
    content_hash,
    decision_id,
    document_content_id,
    entity_id,
    identity_binding_key,
    reference_id,
)

# ── canonical_json: the reproducibility contract ─────────────────────────────


def test_canonical_json_golden_string():
    # GOLDEN: sorted keys, compact, floats as fixed 4dp STRINGS, bool/null lower.
    got = canonical_json({"b": 1, "a": 0.417, "z": [True, None], "m": "Adébáyò"})
    assert got == '{"a":"0.4170","b":1,"m":"Adébáyò","z":[true,null]}'


def test_canonical_json_has_no_raw_floats():
    # Any float -> a 4dp string; a raw float token must never appear.
    s = canonical_json({"score": 0.70831234, "bits": -4.3})
    assert '"0.7083"' in s and '"-4.3000"' in s
    assert "0.70831234" not in s


def test_canonical_json_rounds_to_4dp_so_tiny_diffs_collapse():
    # The heart of reproducibility: differences beyond 4dp vanish.
    assert canonical_json({"x": 0.41700001}) == canonical_json({"x": 0.4170})


def test_canonical_json_key_order_independent():
    assert canonical_json({"a": 1, "b": 2}) == canonical_json({"b": 2, "a": 1})


def test_canonical_json_rejects_unhashable_type():
    with pytest.raises(TypeError):
        canonical_json({"bad": {1, 2, 3}})  # a set is not canonicalizable


# ── document_content_id: known-hash golden vector ────────────────────────────


def test_document_content_id_golden():
    # sha256("hello") is a fixed, well-known value — a true external lock.
    assert document_content_id("hello") == (
        "doc:sha256:2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"
    )


def test_content_hash_prefix_shape():
    h = content_hash({"a": 1}, prefix="ref")
    assert h.startswith("ref:sha256:") and len(h.split(":")[-1]) == 64


# ── reference_id ─────────────────────────────────────────────────────────────


def _ref(**fields):
    return Reference.from_record(fields)


def test_reference_id_deterministic_and_normalised():
    a = _ref(full_name="Fatima Abdullahi", national_id="NIN 123")
    b = _ref(full_name="fátima  abdullahi", national_id="NIN 123")  # diacritics/space
    # NFKD-normalised attributes -> the two records address identically.
    assert reference_id(a) == reference_id(b)
    assert reference_id(a).startswith("ref:sha256:")


def test_reference_id_differs_by_source_system():
    base = {"full_name": "Ada Obi"}
    a = Reference.from_record(base)
    a.source_system = "clinic"
    b = Reference.from_record(base)
    b.source_system = "vaccination"
    assert reference_id(a) != reference_id(b)


# ── identity_binding_key ─────────────────────────────────────────────────────


def test_binding_key_prefers_strongest_identifier():
    ref = _ref(full_name="Ada", phone="0803 123 4567", national_id="NIN-77x")
    # national_id outranks phone; value alnum-normalised.
    assert identity_binding_key(ref) == ("national_id", "nin77x")


def test_binding_key_email_is_text_normalised():
    ref = _ref(full_name="Ada", email="Ada.Obi@Example.COM")
    assert identity_binding_key(ref) == ("email", "ada.obi@example.com")


def test_binding_key_none_when_no_exact_identifier():
    assert identity_binding_key(_ref(full_name="Ada Obi", address="12 Bello Way")) is None


# ── entity_id: keyed HMAC pseudonym (C3) ─────────────────────────────────────


def test_entity_id_is_keyed_and_stable_per_key():
    binding = ("national_id", "nin123")
    k1, k2 = b"1" * 32, b"2" * 32
    assert entity_id(binding, key=k1) == entity_id(binding, key=k1)   # stable
    assert entity_id(binding, key=k1) != entity_id(binding, key=k2)   # not cross-linkable
    assert entity_id(binding, key=k1).startswith("ent:hmac:")


def test_entity_id_is_not_a_bare_hash_of_the_id():
    # A keyed pseudonym must differ from an unkeyed content hash of the same value
    # (that unkeyed hash is what C3 forbids as brute-forceable).
    binding = ("national_id", "nin123")
    bare = content_hash({"id_type": "national_id", "value": "nin123"}, prefix="x")
    assert entity_id(binding, key=b"k" * 32).split(":")[-1] != bare.split(":")[-1]


def test_entity_id_requires_a_strong_key():
    with pytest.raises(ValueError):
        entity_id(("national_id", "nin123"), key=b"")        # empty
    with pytest.raises(ValueError, match="32 bytes"):
        entity_id(("national_id", "nin123"), key=b"short")   # < 32 bytes


def test_binding_family_links_national_id_and_nin():
    # "national_id" and "nin" are the same family -> same entity_id (M1 fix).
    from arche.ids import identity_binding_key
    na = _ref(national_id="NIN-5")
    nb = _ref(nin="NIN-5")
    assert identity_binding_key(na) == identity_binding_key(nb) == ("national_id", "nin5")
    key = b"k" * 32
    assert entity_id(identity_binding_key(na), key=key) == entity_id(identity_binding_key(nb), key=key)


# ── keyed ids (C1): PII-derived ids must be un-brute-forceable when shared ────


def test_reference_id_keyed_differs_from_keyless_and_by_key():
    ref = _ref(national_id="12345678901")
    keyless = reference_id(ref)
    keyed1 = reference_id(ref, key=b"1" * 32)
    keyed2 = reference_id(ref, key=b"2" * 32)
    assert keyless.startswith("ref:sha256:")
    assert keyed1.startswith("ref:hmac-sha256:")
    assert keyed1 != keyless           # keying changes the digest
    assert keyed1 != keyed2            # a different issuer key is unlinkable
    # An attacker without the key cannot recompute the keyed id from the value.
    assert reference_id(ref, key=b"1" * 32) == keyed1  # holder recomputes; deterministic


def test_decision_id_keyed_is_per_issuer():
    a = decision_id(**_decision_kwargs(), key=b"1" * 32)
    b = decision_id(**_decision_kwargs(), key=b"2" * 32)
    assert a.startswith("dec:hmac-sha256:") and a != b
    assert decision_id(**_decision_kwargs(), key=b"1" * 32) == a  # reproducible per issuer


# ── decision_id: reproducible, keyless ───────────────────────────────────────


def _decision_kwargs(**over):
    base = dict(
        reference_id_a="ref:sha256:aaa",
        reference_id_b="ref:sha256:bbb",
        decision="same_entity",
        factors={"name": 0.9012, "national_id": 1.0},
        gate={"distinctive_cleared": True, "clearing_signal": "national_id"},
        vetoes={"id_conflict": False},
        jurisdiction="NG",
        pins={"engine": "arche@0.2", "tf_sha": "abc", "thresholds": {"match": 0.85}},
    )
    base.update(over)
    return base


def test_decision_id_deterministic():
    assert decision_id(**_decision_kwargs()) == decision_id(**_decision_kwargs())


def test_decision_id_reproducible_under_subprecision_float_noise():
    # Two runs whose sims differ beyond 4dp must yield the SAME decision_id.
    a = decision_id(**_decision_kwargs(factors={"name": 0.90123456, "national_id": 1.0}))
    b = decision_id(**_decision_kwargs(factors={"name": 0.9012, "national_id": 1.0}))
    assert a == b


def test_decision_id_changes_with_decision_and_order():
    assert decision_id(**_decision_kwargs()) != decision_id(
        **_decision_kwargs(decision="review")
    )
    swapped = _decision_kwargs(
        reference_id_a="ref:sha256:bbb", reference_id_b="ref:sha256:aaa"
    )
    assert decision_id(**_decision_kwargs()) != decision_id(**swapped)


def test_decision_id_changes_with_pins():
    # Pinning matters: a different tf table / engine version is a different decision.
    assert decision_id(**_decision_kwargs()) != decision_id(
        **_decision_kwargs(pins={"engine": "arche@0.3", "tf_sha": "abc",
                                 "thresholds": {"match": 0.85}})
    )
