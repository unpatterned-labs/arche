# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Answers over MCP carry an attestation when the server has a signing key.

The wrapper is tested directly against a tool function: the server module
reads ``ARCHE_SIGNING_KEY`` once at import, so the key is patched in rather
than the module reloaded, and the claims are the ones that matter -- the
envelope verifies against the server's did:key, binds the arguments the
agent actually passed, and is absent when no key is configured.
"""

from __future__ import annotations

import pytest
from arche.attest import verify_attestation
from arche.sign import generate_keypair


@pytest.fixture(scope="module")
def server():
    """Imported here, not at module scope.

    ``arche.mcp.server`` reads ``ARCHE_HASH_KEY`` once, at import. pytest
    imports every test module during collection, before a single test runs, so
    a top-level import here would fix that read before the studio tests get to
    set the key -- and two tests over in arche-core, which assert the server
    picked the key up, would fail for a reason that has nothing to do with
    them. Import order is load-bearing in this package; keep it inside the
    fixture.
    """
    import importlib

    return importlib.import_module("arche.mcp.server")


@pytest.fixture()
def keyed(monkeypatch, server):
    key = generate_keypair()
    monkeypatch.setattr(server, "_SIGNING_KEY", key)
    return key


def _tool_body(text: str, jurisdiction: str | None = None) -> dict:
    return {"count": 1, "jurisdiction": jurisdiction, "decision_id": "dec:sha256:" + "ab" * 32}


class TestWithAKey:
    def test_the_answer_carries_a_verifiable_envelope(self, keyed, server):
        wrapped = server._attesting(_tool_body)
        answer = wrapped("Ada called 0803 555 0111", jurisdiction="NG")
        env = answer.pop("attestation")
        assert env["tool"] == "_tool_body"
        assert env["signer"] == keyed.did_key
        assert env["caller"] is None  # stdio knows no caller
        assert env["decision_ids"] == ["dec:sha256:" + "ab" * 32]
        check = verify_attestation(
            env, inputs={"text": "Ada called 0803 555 0111", "jurisdiction": "NG"},
            response=answer, public_key=keyed.public_key)
        assert check.ok and check.trusted

    def test_positional_and_keyword_arguments_hash_the_same(self, keyed, server):
        wrapped = server._attesting(_tool_body)
        a = wrapped("t", "NG")["attestation"]["inputs_sha256"]
        b = wrapped(text="t", jurisdiction="NG")["attestation"]["inputs_sha256"]
        assert a == b

    def test_the_tool_signature_survives_for_schema_generation(self, keyed, server):
        """The tool's own parameters, plus the one the SDK injects.

        `ctx` is keyword-only and annotated `Context`, which is how the SDK
        knows to pass the request and to leave it out of the tool's schema.
        Everything before it is the tool's own signature, unchanged, which is
        what the schema is built from.
        """
        import inspect

        wrapped = server._attesting(_tool_body)
        params = inspect.signature(wrapped).parameters
        assert list(params)[:-1] == list(inspect.signature(_tool_body).parameters)
        assert params["ctx"].kind is inspect.Parameter.KEYWORD_ONLY
        assert wrapped.__name__ == "_tool_body"

    def test_the_caller_comes_from_the_proxy_header(self, keyed, server):
        """Who asked, when the transport can say.

        Over streamable HTTP the request headers reach the tool, so a proxy
        that authenticates names the person and the envelope carries it. The
        header is the same one `arche serve` reads, so one auth front answers
        for both surfaces.
        """
        class _Ctx:
            headers = {"X-Arche-Caller": "ada@clinic.example", "accept": "text/event-stream"}

        wrapped = server._attesting(_tool_body)
        answer = wrapped("t", ctx=_Ctx())
        assert answer["attestation"]["caller"] == "ada@clinic.example"

    def test_stdio_has_no_caller_and_does_not_invent_one(self, keyed, server):
        class _Stdio:
            headers = None

        wrapped = server._attesting(_tool_body)
        assert wrapped("t", ctx=_Stdio())["attestation"]["caller"] is None
        assert wrapped("t")["attestation"]["caller"] is None

    def test_an_empty_header_is_not_a_caller(self, keyed, server):
        class _Ctx:
            headers = {"x-arche-caller": "   "}

        wrapped = server._attesting(_tool_body)
        assert wrapped("t", ctx=_Ctx())["attestation"]["caller"] is None

    def test_the_caller_is_not_hashed_into_the_inputs(self, keyed, server):
        """`ctx` is transport, not argument.

        The inputs hash is what an auditor recomputes from the arguments the
        agent says it sent; a header the agent never saw must not be in it.
        """
        class _Ctx:
            headers = {"x-arche-caller": "ada@clinic.example"}

        wrapped = server._attesting(_tool_body)
        with_header = wrapped("t", ctx=_Ctx())["attestation"]
        without = wrapped("t")["attestation"]
        assert with_header["inputs_sha256"] == without["inputs_sha256"]
        assert with_header["caller"] != without["caller"]

    def test_a_non_dict_answer_is_left_alone(self, keyed, server):
        wrapped = server._attesting(lambda: "plain")
        assert wrapped() == "plain"

    def test_capabilities_names_the_signer(self, keyed, server):
        assert server.capabilities()["attestation"] == {"signer": keyed.did_key}


class TestWithoutAKey:
    def test_the_answer_is_unchanged(self, monkeypatch, server):
        monkeypatch.setattr(server, "_SIGNING_KEY", None)
        wrapped = server._attesting(_tool_body)
        assert wrapped is _tool_body
        assert "attestation" not in wrapped("t")

    def test_every_registered_tool_went_through_the_wrapper(self, server):
        """A tool registered with the bare decorator would answer unattested
        while the server claims to attest everything."""
        import re
        from pathlib import Path
        source = Path(server.__file__).read_text(encoding="utf-8")
        assert not re.search(r"^\s*@mcp\.tool\(\)", source, re.M)
        assert source.count("@_tool") == 18  # every tool, the ledger ones included
