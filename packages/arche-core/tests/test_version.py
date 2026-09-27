"""The version is a release decision, so changing it must touch a test."""

import importlib.metadata as metadata

import pytest
from arche import __version__

#: Bump deliberately, in the same commit as the changelog section it names.
VERSION = "0.10.0"


def test_version():
    assert __version__ == VERSION


def test_the_changelog_has_a_section_for_it():
    """A version with no changelog entry is a release nobody can read.

    Skipped when the changelog is not beside the package, so an installed wheel
    can still run its own tests.
    """
    from pathlib import Path

    changelog = Path(__file__).resolve().parents[1] / "CHANGELOG.md"
    if not changelog.is_file():
        pytest.skip("CHANGELOG.md is not in this checkout")
    assert f"## [{VERSION}]" in changelog.read_text(encoding="utf-8"), (
        f"CHANGELOG.md has no `## [{VERSION}]` section"
    )


def test_the_wheel_metadata_agrees():
    """`pyproject.toml` single-sources the version from `_version.py` so these
    two can never disagree. They did once, and the package shipped the 0.3 line
    under the 0.2 number.

    An editable install caches its metadata, so this also catches a stale
    environment: it failed on the 1.0.0rc1 bump until the package was
    reinstalled, which is exactly the state that would ship the wrong number.
    """
    try:
        installed = metadata.version("arche-core")
    except metadata.PackageNotFoundError:
        pytest.skip("arche-core is not installed in this environment")
    assert installed == __version__, (
        f"arche.__version__ is {__version__} and the installed metadata says "
        f"{installed}. Reinstall the package: `uv sync --reinstall-package arche-core`."
    )
