# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""The studio has a hash key, so `guarded_scan` can actually run there.

`arche_mcp.server` reads `ARCHE_HASH_KEY` once, at import. The studio dispatches
MCP tools in-process, so the server inherits the studio's own environment -- and
nobody exports a hash key before running a local demo. `guarded_scan`, the
flagship tool, therefore refused every call made through the Chat tab:

    {"denied": true,
     "reason": "no hash key configured, so tokens could not be stable and the
                guard refuses rather than inventing one (set ARCHE_HASH_KEY)"}

From the outside that is indistinguishable from arche being strict, which is why
it survived a working demo. The tool that exists to show the guard working could
not be shown working.

**The refusal is correct and is asserted here too.** A token is worth something
only if the same value hashes the same way next week, so a server with no key
must decline rather than invent one; a per-process ephemeral key would produce
tokens that silently stop correlating, which is worse than an error. What was
wrong was leaving a machine that has durable storage with no key on it.

So these tests pin both halves: no key still refuses, and the studio always has
one. Plus the thing that makes a persisted secret dangerous -- whether git can
see it.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[3]
_STUDIO = _REPO / "tools" / "arche-studio"

pytestmark = pytest.mark.skipif(
    not (_STUDIO / "serve.py").exists(),
    reason="arche-studio is not present in this checkout",
)


@pytest.fixture(scope="module")
def studio():
    sys.path.insert(0, str(_STUDIO))
    try:
        spec = importlib.util.spec_from_file_location(
            "arche_studio_serve_hashkey", _STUDIO / "serve.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        yield module
    finally:
        sys.path.remove(str(_STUDIO))


class TestTheKeyItself:

    def test_it_is_created_on_first_run(self, studio, tmp_path, monkeypatch):
        path = tmp_path / "hash.key"
        monkeypatch.setattr(studio, "HASH_KEY_PATH", path)
        key = studio._studio_hash_key()
        assert path.exists()
        assert key and key == path.read_text(encoding="utf-8").strip()

    def test_it_is_reused_rather_than_regenerated(self, studio, tmp_path, monkeypatch):
        """The whole point. A key that changes per run is an ephemeral key with a
        file next to it, and the tokens stop correlating just as quietly."""
        monkeypatch.setattr(studio, "HASH_KEY_PATH", tmp_path / "hash.key")
        assert studio._studio_hash_key() == studio._studio_hash_key()

    def test_an_existing_key_is_never_overwritten(self, studio, tmp_path, monkeypatch):
        path = tmp_path / "hash.key"
        path.write_text("a-key-that-already-correlates-things", encoding="utf-8")
        monkeypatch.setattr(studio, "HASH_KEY_PATH", path)
        assert studio._studio_hash_key() == "a-key-that-already-correlates-things"

    def test_it_is_not_guessable(self, studio, tmp_path, monkeypatch):
        monkeypatch.setattr(studio, "HASH_KEY_PATH", tmp_path / "hash.key")
        assert len(studio._studio_hash_key()) >= 32

    def test_it_lives_beside_the_signing_key_not_under_packs(self, studio):
        """`/api/pack?id=...` reads any file inside the pack directory and hands
        it back over HTTP. That is why the signing key moved out, and the hash
        key must not undo the move."""
        assert studio.HASH_KEY_PATH.parent == studio.KEY_PATH.parent
        assert studio.PACKS not in studio.HASH_KEY_PATH.parents


class TestWhatTheServerSees:

    def test_importing_the_studio_configures_the_key(self, studio):
        assert os.environ.get("ARCHE_HASH_KEY")

    def test_the_mcp_server_picked_it_up(self, studio):
        """Module-level, read once at import, which is why ordering matters."""
        from arche_mcp import server

        assert server._HASH_KEY

    def test_guarded_scan_no_longer_refuses(self, studio):
        """The regression, end to end, through the real dispatcher."""
        from arche_mcp.server import mcp

        result = asyncio.run(mcp.call_tool("guarded_scan", {
            "text": "Ada called from 0803 555 0111.",
            "jurisdiction": "NG", "provider": "openai"}))
        out = json.loads("".join(c.text for c in result.content
                                 if getattr(c, "text", None)))
        assert out["denied"] is False, out.get("reason")
        assert "0803" not in out["redacted_text"]

    def test_an_operator_key_still_wins(self):
        """`setdefault`, not assignment. Studio is a demo surface and must not
        override a key someone chose for this environment -- doing so would break
        correlation with every token issued outside it.

        A subprocess, because the assignment happens once, at import.
        """
        done = subprocess.run(
            [sys.executable, "-c",
             "import sys, os; sys.path.insert(0, sys.argv[1]);"
             " import serve; print(os.environ['ARCHE_HASH_KEY'])",
             str(_STUDIO)],
            capture_output=True, text=True, cwd=_REPO,
            env={**os.environ, "ARCHE_HASH_KEY": "chosen-by-the-operator"})
        assert done.returncode == 0, done.stderr[-2000:]
        assert "chosen-by-the-operator" in done.stdout

    def test_no_key_still_refuses(self):
        """The behaviour that was never wrong. Asserted so that a later "fix"
        inventing a key on the fly fails here instead of shipping."""
        from arche_mcp.handlers import guarded_scan

        out = guarded_scan("Ada called from 0803 555 0111.", key="",
                           jurisdiction="NG")
        assert out["denied"] is True
        assert "hash key" in out["reason"]


@pytest.mark.skipif(not (_REPO / ".git").exists(), reason="not a git checkout")
class TestGitCannotSeeIt:
    """A persisted secret is only safe while the ignore rule still covers it.

    These rules previously named `data/review_packs/_studio_key.pem`, and stayed
    there after the state directory moved to `data/_studio/`. That left the
    signing key unignored for as long as it took to notice -- which was until a
    second key was added beside it. Nothing had been committed, because nothing
    under the new path had been added yet. A rule naming a path it no longer
    covers reads as protection and provides none.
    """

    @pytest.mark.parametrize("name", ["hash.key", "key.pem", "state.sqlite3"])
    def test_studio_state_is_ignored(self, name):
        rel = f"data/_studio/{name}"
        done = subprocess.run(["git", "check-ignore", "-q", rel],
                              cwd=_REPO, capture_output=True)
        assert done.returncode == 0, (
            f"{rel} is not ignored. It holds a private key and would be "
            f"committed by `git add data/`.")

    def test_nothing_under_it_is_already_tracked(self):
        done = subprocess.run(["git", "ls-files", "data/_studio"],
                              cwd=_REPO, capture_output=True, text=True)
        assert not done.stdout.strip(), f"already committed: {done.stdout.strip()}"
