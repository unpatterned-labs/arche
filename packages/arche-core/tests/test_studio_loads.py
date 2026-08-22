# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""The studio can still open a pack the library just wrote.

This exists because it did not. A line-based edit to `_load_pack` deleted the
line defining `ids`, every pack raised `NameError` on load, and the review queue
came up empty. The library tests were green throughout, because nothing anywhere
imported the studio.

That is the gap this closes. The studio is not shipped in the wheel and is not
covered by its own tests, so the one thing worth asserting from here is the
contract between them: `review_pack` writes it, `_load_pack` reads it, and a
change to either that breaks the other should fail a test rather than a user.

Deliberately a smoke test. It is not a substitute for testing the studio, and
anything about the HTTP surface, the SQLite store or the UI belongs elsewhere.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest
from arche.report import review_pack
from arche.resolve import crosswalk

_STUDIO = Path(__file__).resolve().parents[3] / "tools" / "arche-studio"

pytestmark = pytest.mark.skipif(
    not (_STUDIO / "serve.py").exists(),
    reason="arche-studio is not present in this checkout",
)

_A = [{"id": str(i), "name": n, "birth_date": d}
      for i, (n, d) in enumerate(
          [("Amara Patel", "2016-06-28"),
           ("Malik Okonkwo", "2017-08-18"),
           ("Ngozi Adeyemi", "1990-03-02")])]


@pytest.fixture(scope="module")
def studio():
    """Import serve.py without installing it. It imports `state` as a sibling."""
    sys.path.insert(0, str(_STUDIO))
    try:
        spec = importlib.util.spec_from_file_location(
            "arche_studio_serve", _STUDIO / "serve.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        yield module
    finally:
        sys.path.remove(str(_STUDIO))


@pytest.fixture
def pack(tmp_path, studio, monkeypatch):
    """A real pack, written by the library, inside the studio's pack directory."""
    monkeypatch.setattr(studio, "PACKS", tmp_path)
    res = crosswalk(_A, _A, entity="person", id_field="id")
    review_pack(res, _A, _A, out_dir=tmp_path / "p", entity="person",
                sides=("left", "right"), reveal=True)
    return "p/pack.csv"


def test_the_studio_can_load_a_pack_the_library_wrote(studio, pack):
    """The regression. This raised NameError and emptied the review queue."""
    loaded = studio._load_pack(pack)
    assert len(loaded["rows"]) == 3


def test_it_finds_the_pack_in_the_listing(studio, pack):
    listed = studio._packs()
    assert any(p["id"] == pack and p["rows"] == 3 for p in listed)


def test_the_two_sides_are_inferred_from_the_column_prefixes(studio, pack):
    """How the queue renders both records without being configured."""
    assert set(studio._load_pack(pack)["sides"]) == {"left", "right"}


def test_both_digests_are_present(studio, pack):
    """`content_digest` was the change that broke this. Assert it is there."""
    loaded = studio._load_pack(pack)
    assert len(loaded["content_digest"]) == 64
    assert len(loaded["digest"]) == 16


def test_the_content_digest_agrees_with_the_manifest(studio, pack):
    """The studio and the library must compute the same digest.

    Two implementations of one digest is how a pack starts failing its own
    integrity check for no reason.
    """
    loaded = studio._load_pack(pack)
    assert loaded["content_digest"] == loaded["manifest"]["content_sha256"]


def test_the_outcome_vocabulary_matches_the_library(studio):
    from arche.report import REVIEW_OUTCOMES
    assert tuple(studio._load_pack.__globals__["OUTCOMES"]) == tuple(REVIEW_OUTCOMES)


def test_a_pack_outside_the_pack_directory_is_refused(studio, pack):
    """Path traversal. The loader resolves and checks containment."""
    with pytest.raises(ValueError, match="escapes"):
        studio._load_pack("../../../etc/passwd")
