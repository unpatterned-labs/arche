# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

r"""Two things a public repository must not ship, held mechanically.

Both of these were found in tracked files on 2026-10-05, and neither was
something a reader of the diff would have questioned, which is why they are
tests rather than a note.

**No absolute local path in a tracked file.** A provenance manifest carried
three ``C:\Users\<name>\AppData\Local\Temp\...`` paths, written by the generator
that built it, and a run-metadata file pointed at a sibling repository by its
full local path. The digest beside each one already proved which bytes the
sample was; the directory proved nothing and disclosed a maintainer's
filesystem. A repository that reads as an ordinary open-source project does not
hand out its author's home directory.

**No revealed review pack in the directory the studio reads by default.**
``data/review_packs/`` is the default for ``arche studio`` and the directory the
review guide tells a reader to pass. Three revealed packs were sitting in it,
one of them a customer pilot with live email addresses in 65 rows. They were
correctly gitignored, so nothing reached git -- and that is exactly why this
needs its own test: ignoring a pack keeps it out of the repository and does
nothing to stop it being rendered on screen in front of an audience. The two
failures are independent and only one of them had a guard.

**On the scope of the first pattern**, because three attempts to widen it all
failed and the next person will want to try. It matches a *user directory*
only, not any drive path. Matching a drive letter plus a separator hits the
``s://`` in every https URL; making the separator optional hits Python format
specifiers like ``{k:24}`` and ``{p:.4f}``; requiring a backslash still hits
``"A:\n"``, where the source bytes are a letter, a colon, a backslash and an n.
Each draft reported dozens to hundreds of files, all noise. A check that cries
wolf gets deleted, so this one stays narrow and catches the case that actually
matters: disclosure. An example command that says ``C:\tmp\out`` is a
portability wart rather than a disclosure, and is not worth a guard that
behaves like those three.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
REVIEW_PACKS = REPO / "data" / "review_packs"

# A Windows user directory, a macOS one, a Linux one. Deliberately not matching
# bare ``/usr`` or ``/etc``: those appear legitimately in prose about containers
# and are not disclosures about one machine. See the module docstring for why
# this is not broader.
_ABSOLUTE_LOCAL = re.compile(
    r"(?:[A-Za-z]:[\\/]{1,2}Users[\\/]{1,2}[^\s\"'<>|]+"
    r"|/home/[A-Za-z0-9._-]+/"
    r"|/Users/[A-Za-z0-9._-]+/)"
)

# Paths that may legitimately carry one, each with its reason. An exception has
# to be named here rather than handled by loosening the pattern, so that the
# next reader can see what was excused and judge whether it still should be.
_ALLOWED: dict[str, str] = {
    # A quoted CI failure message. The path is GitHub Actions' runner layout,
    # not anybody's machine, and the test it documents exists because of that
    # exact error text.
    "packages/arche-core/tests/test_workspace_integrity.py":
        "quotes a GitHub Actions runner path from the CI error it guards",
    # This file's own docstring, which has to show the shape it forbids.
    "packages/arche-core/tests/test_repository_hygiene.py":
        "documents the pattern it enforces, including a bad path as an example",
}

# Text extensions only. A PDF or a parquet file may contain such a byte run
# incidentally and reading every binary to check is not worth the runtime.
_TEXT_SUFFIXES = {
    ".py", ".pyi", ".md", ".txt", ".json", ".jsonl", ".yaml", ".yml", ".toml",
    ".cfg", ".ini", ".csv", ".tsv", ".html", ".css", ".js", ".ts", ".sh",
    ".ipynb", ".gitignore", ".gitattributes", "",
}


def _tracked_files() -> list[Path]:
    """Every file git tracks, which is the exact set that ships."""
    try:
        out = subprocess.run(
            ["git", "ls-files", "-z"], cwd=REPO, capture_output=True,
            text=True, timeout=120, check=True,
        ).stdout
    except (OSError, subprocess.SubprocessError) as exc:  # pragma: no cover
        pytest.skip(f"git is not usable here: {exc}")
    return [REPO / name for name in out.split("\0") if name]


def test_no_tracked_file_carries_an_absolute_local_path() -> None:
    """A tracked file must not disclose anybody's home or temp directory."""
    offenders: list[str] = []
    for path in _tracked_files():
        if path.suffix.lower() not in _TEXT_SUFFIXES:
            continue
        rel = path.relative_to(REPO).as_posix()
        if rel in _ALLOWED:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for found in _ABSOLUTE_LOCAL.findall(text):
            offenders.append(f"{rel}: {found}")

    assert not offenders, (
        "These tracked files carry an absolute local path, which discloses a "
        "maintainer's filesystem and is rule 4 of this repository:\n  "
        + "\n  ".join(sorted(set(offenders)))
        + "\n\nIf a path is genuinely needed, write a relative one. If a "
        "provenance record needs to identify a file, its basename plus a "
        "sha256 says which file and which bytes without naming a directory. "
        "If an exception is truly justified, add it to _ALLOWED with the "
        "reason rather than loosening the pattern."
    )


@pytest.mark.skipif(not REVIEW_PACKS.is_dir(),
                    reason="no review pack directory in this checkout")
def test_the_default_pack_directory_holds_nothing_revealed() -> None:
    """`arche studio` renders every pack it finds, so the default must be safe.

    Revealed packs go in their own directory and are opened explicitly:

        arche studio --packs data/private_packs
    """
    revealed = sorted(
        child.name for child in REVIEW_PACKS.iterdir()
        if child.is_dir() and child.name.lower().startswith(
            ("confidential", "private", "revealed", "pilot"))
    )
    assert not revealed, (
        "These revealed packs are in the directory `arche studio` reads by "
        "default, so they are rendered beside the example packs to whoever is "
        f"watching: {revealed}. Being gitignored does not help -- that keeps "
        "them out of the repository, not off the screen. Move them to "
        "`data/private_packs/` and open them with `--packs` when you need them."
    )
