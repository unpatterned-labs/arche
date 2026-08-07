# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""The role-cue pack loader contract: malformed packs fail loudly."""

from __future__ import annotations

import pytest
import yaml
from arche.addr.roles import RolePackError, load_gold, load_role_pack


def _write_pack(tmp_path, data):
    p = tmp_path / "pack.yaml"
    p.write_text(yaml.safe_dump(data), encoding="utf-8")
    return p


_MINIMAL = {
    "pack": "t", "version": "v0",
    "rules": [{"id": "r1", "role": "origin", "cues": ["from"]}],
}


class TestPackValidation:
    def test_minimal_pack_loads(self, tmp_path):
        pack = load_role_pack(_write_pack(tmp_path, _MINIMAL))
        assert pack.rules[0].id == "r1"

    @pytest.mark.parametrize("missing", ["pack", "version", "rules"])
    def test_missing_required_key(self, tmp_path, missing):
        data = {k: v for k, v in _MINIMAL.items() if k != missing}
        with pytest.raises(RolePackError, match=missing):
            load_role_pack(_write_pack(tmp_path, data))

    def test_unknown_role_rejected(self, tmp_path):
        data = {**_MINIMAL,
                "rules": [{"id": "r1", "role": "pickup", "cues": ["from"]}]}
        with pytest.raises(RolePackError, match="unknown role"):
            load_role_pack(_write_pack(tmp_path, data))

    def test_unknown_kind_rejected(self, tmp_path):
        data = {**_MINIMAL,
                "rules": [{"id": "r1", "kind": "fuzzy", "role": "origin",
                           "cues": ["from"]}]}
        with pytest.raises(RolePackError, match="unknown kind"):
            load_role_pack(_write_pack(tmp_path, data))

    def test_duplicate_rule_id_rejected(self, tmp_path):
        data = {**_MINIMAL, "rules": [
            {"id": "r1", "role": "origin", "cues": ["from"]},
            {"id": "r1", "role": "destination", "cues": ["to"]},
        ]}
        with pytest.raises(RolePackError, match="duplicate"):
            load_role_pack(_write_pack(tmp_path, data))

    def test_contradictory_cue_same_priority_rejected(self, tmp_path):
        data = {**_MINIMAL, "rules": [
            {"id": "r1", "role": "origin", "cues": ["from"], "priority": 50},
            {"id": "r2", "role": "destination", "cues": ["from"],
             "priority": 50},
        ]}
        with pytest.raises(RolePackError, match="contradict"):
            load_role_pack(_write_pack(tmp_path, data))

    def test_pair_rule_requires_join_and_roles(self, tmp_path):
        data = {**_MINIMAL,
                "rules": [{"id": "r1", "kind": "pair", "cues": ["between"],
                           "roles": ["origin", "destination"]}]}
        with pytest.raises(RolePackError, match="join"):
            load_role_pack(_write_pack(tmp_path, data))

    def test_intrinsic_source_is_closed(self, tmp_path):
        data = {**_MINIMAL,
                "rules": [{"id": "r1", "kind": "intrinsic", "role": "location",
                           "source": "my_own_words"}]}
        with pytest.raises(RolePackError, match="anchor_prepositions"):
            load_role_pack(_write_pack(tmp_path, data))

    def test_missing_cues_rejected(self, tmp_path):
        data = {**_MINIMAL, "rules": [{"id": "r1", "role": "origin"}]}
        with pytest.raises(RolePackError, match="cues"):
            load_role_pack(_write_pack(tmp_path, data))


class TestPin:
    def test_pin_stable_across_comment_edit(self, tmp_path):
        p1 = load_role_pack(_write_pack(tmp_path, _MINIMAL)).pin
        commented = dict(_MINIMAL)
        p = tmp_path / "pack2.yaml"
        p.write_text("# a comment\n" + yaml.safe_dump(commented),
                     encoding="utf-8")
        assert load_role_pack(p).pin == p1

    def test_pin_changes_on_priority_edit(self, tmp_path):
        p1 = load_role_pack(_write_pack(tmp_path, _MINIMAL)).pin
        changed = {**_MINIMAL, "rules": [
            {"id": "r1", "role": "origin", "cues": ["from"], "priority": 60},
        ]}
        p = tmp_path / "pack3.yaml"
        p.write_text(yaml.safe_dump(changed), encoding="utf-8")
        assert load_role_pack(p).pin != p1

    def test_shipped_pack_pin_shape(self):
        pin = load_role_pack().pin
        assert pin.startswith("arche.place_roles@v1:sha256:")
        assert len(pin.rsplit(":", 1)[1]) == 16


class TestGoldLoader:
    def test_shipped_gold_loads_and_self_validates(self):
        gold = load_gold()
        for s in gold:
            for p in s.places:
                assert s.text[p.span[0]:p.span[1]] == p.text

    def test_absent_fragment_raises(self, tmp_path, monkeypatch):
        import arche.addr.roles as roles_mod

        bad = tmp_path / "_eval"
        bad.mkdir()
        (bad / "broken.yaml").write_text(yaml.safe_dump({
            "sentences": [{"id": "x", "text": "no places here",
                           "places": [{"role": "origin", "text": "Lagos"}]}],
        }), encoding="utf-8")
        monkeypatch.setattr(
            roles_mod, "__file__", str(tmp_path / "roles.py"),
        )
        with pytest.raises(RolePackError, match="not found"):
            roles_mod.load_gold("broken")
