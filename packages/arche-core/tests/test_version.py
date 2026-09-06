"""The version is a release decision, so changing it must touch a test."""

from arche import __version__


def test_version():
    assert __version__ == "0.8.0"
