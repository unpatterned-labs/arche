"""The documented version matches the released one, once there is a release.

The site deploys on every push to `main`, and the package is released by a
separate manual workflow. So there is a window where the two disagree on
purpose: during `1.0.0rc1` the recommended install is still the last stable
version, and a docs page claiming `1.0.0` before it exists would be wrong in the
more damaging direction.

This test therefore **sleeps during a prerelease and bites on a final one**. Cut
`1.0.0rc1` and it skips; cut `1.0.0` and it fails until the pages that quote a
version are updated, which is the step that would otherwise be remembered or
not.

It checks the pages that name a version a reader will *act* on, an image tag to
pull or an install to verify, and deliberately not prose that happens to mention
an old release.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from arche import __version__

REPO = Path(__file__).resolve().parents[3]

#: Pages that quote the current version somewhere a reader will copy it.
DOCUMENTED = (
    "docs-site/docs/get-started/install.md",
    "docs-site/docs/get-started/docker.md",
    "deploy/README.md",
)

#: A PEP 440 prerelease suffix: a, b, rc, dev, post.
_PRERELEASE = re.compile(r"(a|b|rc|\.dev|\.post)\d*$")

#: Any released version of this package, as it appears in prose or a tag.
_A_VERSION = re.compile(r"\b\d+\.\d+\.\d+(?:(?:a|b|rc)\d+)?\b")


def _is_prerelease(version: str) -> bool:
    return bool(_PRERELEASE.search(version))


@pytest.mark.skipif(
    _is_prerelease(__version__),
    reason=f"{__version__} is a prerelease; the docs still describe the last stable "
           "release, which is correct until this one is published",
)
@pytest.mark.parametrize("page", DOCUMENTED)
def test_the_docs_quote_this_version(page: str):
    path = REPO / page
    if not path.is_file():
        pytest.skip(f"{page} is not in this checkout")
    text = path.read_text(encoding="utf-8")

    quoted = set(_A_VERSION.findall(text))
    if not quoted:
        pytest.skip(f"{page} quotes no version")
    stale = {v for v in quoted if v != __version__ and not _is_prerelease(v)}
    assert not stale, (
        f"{page} quotes {sorted(stale)} but the package is {__version__}. A reader "
        "copies an image tag or checks an install against these, so they are not "
        "prose. Update them in the release commit."
    )
