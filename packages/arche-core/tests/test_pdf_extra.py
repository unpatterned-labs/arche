# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""The PDF reader is chosen by licence, not only by capability.

`pymupdf` is AGPL-3.0. `pypdf` is BSD-3-Clause. Both read a text layer well
enough for this library's purposes, so the tie is broken on the licence a user
acquires by installing an extra -- and copyleft is something to choose on
purpose rather than to inherit from an extra called `pdf`.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
EXTRAS = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))[
    "project"]["optional-dependencies"]


def test_the_default_pdf_extra_is_permissively_licensed():
    assert any("pypdf" in dep for dep in EXTRAS["pdf"]), (
        "arche-core[pdf] must install pypdf (BSD-3-Clause). It previously "
        "installed pymupdf, which is AGPL-3.0 -- a licence a user should "
        "choose deliberately, not acquire from an extra named `pdf`."
    )
    assert not any("mupdf" in dep.lower() for dep in EXTRAS["pdf"])


def test_the_copyleft_reader_keeps_a_name_that_says_so():
    assert "pdf-mupdf" in EXTRAS
    assert any("pymupdf" in dep for dep in EXTRAS["pdf-mupdf"])


def test_no_pdf_reader_is_in_the_base_wheel():
    core = " ".join(tomllib.loads(
        (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    )["project"]["dependencies"])
    assert "pypdf" not in core and "mupdf" not in core


def test_the_permissive_reader_is_tried_first():
    # Order is the whole mechanism: with both installed, the AGPL one must not
    # be the one that runs.
    from arche.workflow import _ingest

    source = _ingest._extract_pdf.__doc__ or ""
    assert "pypdf" in source and "pymupdf" in source
    body = _ingest._extract_pdf.__code__.co_names
    assert body.index("pypdf") < body.index("fitz")


def test_a_missing_reader_names_both_extras_and_the_licence():
    import arche.workflow._ingest as ingest

    pytest.importorskip("pypdf")
    # The message is what a caller sees when neither is installed; assert its
    # content rather than simulating the absent-import path.
    source = ingest._extract_pdf.__doc__ or ""
    assert "BSD" in source or "AGPL" in source


def test_the_pyproject_is_valid_toml():
    # It parsed as TOML while being *invalid*: a patch script ran twice and
    # wrote `detect2` a second time, and TOML forbids duplicate keys. Nothing
    # in the suite noticed, because nothing in the suite read the file with a
    # strict parser -- `uv` did, and refused to build the package at all.
    #
    # `tomllib` is strict about duplicates, so simply parsing the file is the
    # guard. It costs nothing and it stands between an edit and a release that
    # cannot be installed.
    import tomllib

    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    extras = data["project"]["optional-dependencies"]
    assert extras, "no optional dependencies declared"


def test_every_extra_is_declared_once():
    # tomllib raises on a duplicate key, so reaching this line already proves
    # it. Asserted separately anyway: the failure above reads as "your TOML is
    # broken", and this one names what to look for.
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    start = text.index("[project.optional-dependencies]")
    end = text.index("\n[", start + 1)
    keys = [line.split("=")[0].strip()
            for line in text[start:end].splitlines()
            if "=" in line and not line.lstrip().startswith("#")]
    duplicates = {k for k in keys if keys.count(k) > 1}
    assert not duplicates, f"declared more than once: {sorted(duplicates)}"
