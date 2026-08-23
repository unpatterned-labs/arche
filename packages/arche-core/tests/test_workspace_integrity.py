# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Every workspace member git can see has the manifest that makes it a package.

CI failed with:

    error: Workspace member `/home/runner/work/arche/arche/packages/arche-mcp`
    is missing a `pyproject.toml`

The file was on disk and had been for days. `.gitignore` carried a bare
`pyproject.toml` rule — unanchored, so it matches at every depth — and
`packages/arche-mcp/pyproject.toml` was silently skipped when the package was
committed. `git add` said nothing. `git status` showed nothing. The local
checkout worked perfectly because the file was right there.

The root and `arche-core` manifests were unaffected, which is what made it hard
to see: **gitignore does not apply to files already in the index.** Both were
tracked before the rule existed, so the rule had never bitten anything and
looked harmless.

That is the shape worth guarding. A rule that has never caused a problem is not
a rule that cannot, and the first thing it breaks is the next thing added.

These tests read the workspace declaration and ask git what it can see, so they
fail in the repository rather than on a clean checkout somewhere else.
"""

from __future__ import annotations

import pathlib
import subprocess
import tomllib

import pytest

REPO = pathlib.Path(__file__).resolve().parents[3]


def _members() -> list[str]:
    config = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))
    return config["tool"]["uv"]["workspace"]["members"]


def _tracked(rel: str) -> bool:
    done = subprocess.run(["git", "ls-files", "--error-unmatch", rel],
                          cwd=REPO, capture_output=True)
    return done.returncode == 0


def _ignored(rel: str) -> bool:
    done = subprocess.run(["git", "check-ignore", "-q", rel],
                          cwd=REPO, capture_output=True)
    return done.returncode == 0


pytestmark = pytest.mark.skipif(
    not (REPO / ".git").exists(),
    reason="not a git checkout, so there is nothing to ask git about",
)


@pytest.mark.parametrize("member", _members())
class TestEveryMemberIsARealPackage:

    def test_the_directory_exists(self, member):
        """A member that is not a directory is a claim about what ships. The
        root pyproject's own comment says so, and this enforces it."""
        assert (REPO / member).is_dir(), (
            f"{member} is declared as a workspace member and is not on disk")

    def test_its_manifest_exists(self, member):
        assert (REPO / member / "pyproject.toml").exists(), (
            f"{member} has no pyproject.toml, so `uv sync` cannot resolve it")

    def test_its_manifest_is_tracked(self, member):
        """The failure that reached CI. On disk is not enough — a clean
        checkout gets what git has, and git had nothing."""
        rel = f"{member}/pyproject.toml"
        assert _tracked(rel), (
            f"{rel} exists locally and is NOT in git. A clean checkout will "
            f"fail with 'Workspace member ... is missing a pyproject.toml'. "
            f"Run: git add -f {rel}")

    def test_its_manifest_is_not_ignored(self, member):
        """Tracked files ignore .gitignore, so a tracked-but-ignored manifest
        works today and disappears the moment anyone re-adds it."""
        rel = f"{member}/pyproject.toml"
        assert not _ignored(rel), (
            f"{rel} is matched by a .gitignore rule. It survives only because "
            f"it is already in the index, and will vanish from any fresh clone "
            f"of a repo where someone removes and re-adds it.")


class TestTheRuleThatCausedIt:

    def test_a_new_package_manifest_would_be_addable(self, tmp_path):
        """The regression, phrased as the thing that failed.

        Not a real directory — `git check-ignore` answers about paths, so a
        hypothetical one is enough and leaves nothing behind.
        """
        done = subprocess.run(
            ["git", "check-ignore", "-q", "packages/arche-future/pyproject.toml"],
            cwd=REPO, capture_output=True)
        assert done.returncode != 0, (
            "a new workspace member's pyproject.toml would be ignored, exactly "
            "as arche-mcp's was")

    def test_the_root_manifest_and_lock_are_visible(self):
        for rel in ("pyproject.toml", "uv.lock"):
            assert _tracked(rel), f"{rel} is not tracked"
            assert not _ignored(rel), (
                f"{rel} is ignored and survives only by already being tracked")

    def test_uv_can_read_the_workspace_from_what_git_has(self):
        """The end-to-end version. Everything `uv sync --all-packages` needs
        must be in the index, not merely on this machine."""
        missing = [m for m in _members()
                   if not _tracked(f"{m}/pyproject.toml")]
        assert not missing, (
            f"these members have no tracked manifest and will break a clean "
            f"checkout: {missing}")
