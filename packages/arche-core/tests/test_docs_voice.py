# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""The published documentation keeps its voice.

Three rules the site was rewritten to on 2026-09-20, held here so a later
page cannot drift back: no em-dashes anywhere on a published page (commas,
colons and full stops do the work); every page has exactly one H1 and it is
the first line of content; and every task page shows its first runnable
example on the first screen, because a reader who has to scroll to find out
what the page does has already left.

The published set is read from ``exclude_docs`` in ``mkdocs.yml`` through the
same parser the example test uses, so publishing a page puts it under these
rules in the same commit.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from tests.test_docs_examples import DOCS, _exclusion_rules

_FENCE = re.compile(r"^```(python|sh|bash|text|json|yaml)", re.M)
_FIRST_SCREEN_LINES = 40
# Section index pages and essays open with prose; everything else opens with
# a thing to run.
_PROSE_FIRST = {"index.md", "contributing.md"}
_PROSE_DIRS = ("writing/",)


def _published() -> list[Path]:
    if not DOCS.is_dir():
        return []
    prefixes, reincluded = _exclusion_rules()
    out = []
    for p in sorted(DOCS.rglob("*.md")):
        rel = str(p.relative_to(DOCS)).replace("\\", "/")
        if rel not in reincluded and any(rel.startswith(e) for e in prefixes):
            continue
        out.append(p)
    return out


def _rel(p: Path) -> str:
    return str(p.relative_to(DOCS)).replace("\\", "/")


pytestmark = pytest.mark.skipif(not DOCS.is_dir(), reason="docs-site not checked out")


@pytest.mark.parametrize("page", _published(), ids=_rel)
def test_no_em_dash(page: Path):
    text = page.read_text(encoding="utf-8")
    hits = [i + 1 for i, line in enumerate(text.splitlines()) if "—" in line]
    assert not hits, (f"{_rel(page)}: em-dash on line(s) {hits[:5]}; "
                      "use a comma, a colon or a full stop")


@pytest.mark.parametrize("page", _published(), ids=_rel)
def test_one_h1_first(page: Path):
    text = page.read_text(encoding="utf-8")
    body = re.sub(r"\A---\n.*?\n---\n", "", text, count=1, flags=re.S)   # front matter
    body = re.sub(r"\A(<!--.*?-->\s*)+", "", body, flags=re.S)             # leading comments
    prose = re.sub(r"^```.*?^```", "", body, flags=re.S | re.M)   # a `# ` in a fence is a comment
    h1s = re.findall(r"^# .+$", prose, re.M)
    if page.name == "index.md" and page.parent == DOCS:
        assert "<h1>" in body, "the landing page carries its H1 in the hero"
        return
    assert len(h1s) == 1, f"{_rel(page)}: expected one H1, found {len(h1s)}"
    first = next((ln for ln in body.splitlines() if ln.strip()), "")
    assert first.startswith("# "), f"{_rel(page)}: the H1 is not the first line of content"


def test_every_public_name_is_on_the_python_api_page():
    """The 1.x promise, from the documentation side.

    `__all__` is what the package recommends and `reference/python-api.md` is
    what the site documents; at the 1.0 freeze they were made the same list.
    A name added to one and not the other is the drift this catches: an
    undocumented public name is a promise nobody can read, and a documented
    name that is not public is a promise nobody can use.
    """
    import arche

    page = DOCS / "reference" / "python-api.md"
    if not page.is_file():
        pytest.skip("the API page is not in this checkout")
    text = page.read_text(encoding="utf-8")
    missing = [n for n in sorted(arche.__all__) if n not in text]
    assert not missing, (
        f"public but undocumented: {missing}. Add each to "
        "docs-site/docs/reference/python-api.md, or take it out of __all__.")


@pytest.mark.parametrize("page", _published(), ids=_rel)
def test_first_example_on_the_first_screen(page: Path):
    rel = _rel(page)
    if page.name in _PROSE_FIRST or rel.startswith(_PROSE_DIRS):
        return
    if page.parent == DOCS and page.name == "index.md":
        return
    head = "\n".join(page.read_text(encoding="utf-8").splitlines()[:_FIRST_SCREEN_LINES])
    assert _FENCE.search(head), (
        f"{rel}: no code fence in the first {_FIRST_SCREEN_LINES} lines; a task page shows "
        f"its first example before the first heading")


# ---------------------------------------------------------------------------
# The configuration itself
# ---------------------------------------------------------------------------
#
# Every block below was deleted from `mkdocs.yml` in one commit and nothing
# noticed. A `re.S` regex rewriting the `exclude_docs` comment matched to end
# of file and took the rest with it: the stylesheet, the redirects, the
# markdown extensions, the nav and the social links. `mkdocs build --strict`
# passed, because MkDocs requires none of them: it falls back to a default
# theme, an alphabetical sidebar and no redirects, and calls that a clean
# build. The site was plain Material with every old URL broken, and the only
# signal was that it looked wrong to a human who happened to open it.

#: block -> what the site loses without it, for the failure message.
_REQUIRED_BLOCKS = {
    "theme": "everything",
    "extra_css": "the design system",
    "plugins": "search and every redirect",
    "markdown_extensions": "code copy, admonitions and tables",
    "nav": "the curated sidebar",
    "extra": "the social links",
}


def _mkdocs_text() -> str:
    from tests.test_docs_examples import MKDOCS

    if not MKDOCS.is_file():
        pytest.skip("mkdocs.yml is not in this checkout")
    return MKDOCS.read_text(encoding="utf-8")


@pytest.mark.parametrize("block", sorted(_REQUIRED_BLOCKS))
def test_the_site_config_still_has_its_blocks(block: str):
    text = _mkdocs_text()
    assert re.search(rf"^{block}:", text, re.M), (
        f"mkdocs.yml has no `{block}:` block. A strict build passes without "
        f"it and the site quietly loses {_REQUIRED_BLOCKS[block]}.")


def test_every_retired_page_still_has_a_redirect():
    """A URL that was published keeps answering.

    The pages retired for the 1.0 site are gone from the tree; `redirect_maps`
    is the only thing standing between an old link and a 404, and it is a hand
    written list. This checks the list still names what it named.
    """
    text = _mkdocs_text()
    block = re.search(r"redirect_maps:\s*\n((?:\s{8,}\S.*\n)+)", text)
    assert block, "mkdocs.yml has no redirect_maps; every pre-1.0 URL 404s"
    targets = []
    sources = []
    for line in block.group(1).splitlines():
        source, _, target = line.strip().partition(": ")
        sources.append(source)
        targets.append(target)
    for expected in ("getting-started/quickstart.md", "reference/decision-contract.md",
                     "guides/review-log.md", "blog/what-a-name-list-is-worth.md"):
        assert expected in sources, f"{expected} lost its redirect"
    for target in targets:
        assert (DOCS / target).is_file(), f"redirect points at a page that does not exist: {target}"
