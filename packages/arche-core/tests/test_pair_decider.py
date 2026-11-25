# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0
"""PairDecider: features, thresholds and pins, with a stub cross-encoder."""

from __future__ import annotations

import json
import math

import pytest
from arche.resolve import PairDecider
from arche.resolve.decider import DECIDER_SCHEMA

SPEC = {
    "schema": DECIDER_SCHEMA,
    "features": ["cross_encoder_logit", "log1p_km", "admin2_agree", "coordinates_missing"],
    "weights": [1.0, -2.5, 4.0, -1.9, -0.2],
    "thresholds": {"located": {"lo": 0.14, "hi": 0.97}, "hidden": {"lo": 0.04, "hi": 0.96}},
    "admin2_aliases": {"fct|municipal area council": "abuja municipal area council"},
}


def decider(logit: float = 3.0) -> PairDecider:
    return PairDecider(SPEC, logit_fn=lambda texts: [logit] * len(texts))


def rec(name="Kubwa PHC", admin2="Bwari", lat=9.15, lon=7.33, admin1="Fct"):
    return {"name": name, "admin1": admin1, "admin2": admin2, "lat": lat, "lon": lon}


def test_same_point_same_admin2_matches():
    d = decider().decide([(rec(), rec())])[0]
    assert d.outcome == "match" and d.located
    assert d.features["log1p_km"] == 0.0 and d.features["admin2_agree"] == 1.0


def test_missing_point_is_not_read_as_zero_km():
    located = decider().decide([(rec(), rec())])[0]
    hidden = decider().decide([(rec(), rec(lat=None, lon=None))])[0]
    assert not hidden.located and hidden.features["coordinates_missing"] == 1.0
    assert hidden.probability < located.probability
    assert hidden.thresholds == SPEC["thresholds"]["hidden"]


def test_distance_lowers_the_probability():
    near = decider().decide([(rec(), rec())])[0]
    far = decider().decide([(rec(), rec(lat=9.40))])[0]
    assert far.features["log1p_km"] == pytest.approx(math.log1p(27.8), abs=0.05)
    assert far.probability < near.probability


def test_alias_makes_admin2_agree():
    a = rec(admin2="Abuja Municipal Area Council")
    b = rec(admin2="Municipal Area Council")
    assert decider().decide([(a, b)])[0].features["admin2_agree"] == 1.0
    assert decider().decide([(b, a)])[0].features["admin2_agree"] == 0.0  # alias rewrites b only


def test_low_logit_rejects():
    assert decider(-8.0).decide([(rec(), rec(name="Other"))])[0].outcome == "reject"


def test_pins_name_the_spec():
    d = decider().decide([(rec(), rec())])[0]
    assert d.pins["decider_spec"].startswith("sha256:")
    other = PairDecider({**SPEC, "weights": [1.0, -2.0, 4.0, -1.9, -0.2]}, logit_fn=lambda t: [0.0])
    assert other.pins["decider_spec"] != d.pins["decider_spec"]


def test_rejects_wrong_schema_and_weight_count():
    with pytest.raises(ValueError):
        PairDecider({**SPEC, "schema": "x"})
    with pytest.raises(ValueError):
        PairDecider({**SPEC, "weights": [1.0]})


def test_load_checks_the_cross_encoder_digest(tmp_path):
    (tmp_path / "cross_encoder").mkdir()
    (tmp_path / "cross_encoder" / "config.json").write_text("{}")
    (tmp_path / "decider.json").write_text(json.dumps({**SPEC, "cross_encoder_sha256": "sha256:0"}))
    with pytest.raises(ValueError, match="differ"):
        PairDecider.load(tmp_path)
