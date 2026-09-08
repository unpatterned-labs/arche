# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""`arche attest keygen` and `arche attest verify`: the auditor's two commands."""

from __future__ import annotations

import json

from arche.cli import main


def test_keygen_then_verify_roundtrip(tmp_path, capsys):
    key = tmp_path / "k.pem"
    assert main(["attest", "keygen", str(key)]) == 0
    out = capsys.readouterr().out
    did = next(line.split()[1] for line in out.splitlines() if line.startswith("did:key"))
    assert did.startswith("did:key:z") and key.exists()

    from arche.attest import attest, signing_key
    inputs = {"a": {"name": "x"}, "b": {"name": "x"}}
    response = {"identity": "same_entity", "decision_id": "dec:sha256:" + "ab" * 32}
    env = attest("compare", inputs, response, keypair=signing_key(key))
    (tmp_path / "env.json").write_text(json.dumps({**response, "attestation": env}), encoding="utf-8")
    (tmp_path / "in.json").write_text(json.dumps(inputs), encoding="utf-8")
    (tmp_path / "resp.json").write_text(json.dumps(response), encoding="utf-8")

    rc = main(["attest", "verify", str(tmp_path / "env.json"), "--inputs", str(tmp_path / "in.json"),
               "--response", str(tmp_path / "resp.json"), "--public-key", did, "--json"])
    report = json.loads(capsys.readouterr().out)
    assert rc == 0 and report["ok"] and report["trusted"]
    assert report["decision_ids"] == ["dec:sha256:" + "ab" * 32]

    # Without a pinned key: valid, said plainly not to be trusted.
    rc = main(["attest", "verify", str(tmp_path / "env.json")])
    text = capsys.readouterr().out
    assert rc == 0 and "trusted         False" in text and "authorship not" in text

    # An edited response fails, and says which side.
    (tmp_path / "resp.json").write_text(json.dumps({**response, "identity": "different"}),
                                        encoding="utf-8")
    rc = main(["attest", "verify", str(tmp_path / "env.json"), "--response",
               str(tmp_path / "resp.json")])
    text = capsys.readouterr().out
    assert rc == 1 and "NOT OK" in text and "response" in text


def test_keygen_refuses_to_overwrite(tmp_path, capsys):
    key = tmp_path / "k.pem"
    assert main(["attest", "keygen", str(key)]) == 0
    assert main(["attest", "keygen", str(key)]) == 2
    assert "--force" in capsys.readouterr().err
    assert main(["attest", "keygen", str(key), "--force"]) == 0
