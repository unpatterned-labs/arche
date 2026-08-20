# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Every Python example in the published docs is executed here.

This project keeps being bitten by the same thing: a documented claim that was
true when it was written and quietly stopped being true. A benchmark row that
described a different measurement, a `40% -> 0%` figure with nothing behind it,
a person pack whose examples predated the comparator they showed. Prose does not
fail a build, so it drifts, and the only fix that holds is executing it.

**A page is a session.** Blocks run concatenated, in order, exactly as a reader
would paste them. That is what makes a later block able to use a name an earlier
one defined, and it is why a page whose first block does not run fails as a
whole rather than one line at a time.

Two escape hatches, both explicit, because a marker somebody has to type is a
marker somebody has to justify:

    <!-- docs-test: fragment -->   shape only, never executed
    <!-- docs-test: skip -->       real, but needs network, a key, or minutes

Only *published* pages are covered. `mkdocs.yml` excludes most of the tree as
unrevalidated working material, and testing pages nobody can read would spend
the budget in the wrong place. The exclusion list is parsed rather than copied,
so publishing a page automatically puts it under test. That is the point: the
gate on publishing a page is that its examples run.
"""

from __future__ import annotations

import re
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
DOCS = REPO / "docs-site" / "docs"
MKDOCS = REPO / "docs-site" / "mkdocs.yml"

# A block preceded by one of these comments is not executed.
_FRAGMENT = re.compile(r"<!--\s*docs-test:\s*fragment\s*-->\s*```python\n(.*?)```", re.S)
_SKIP = re.compile(r"<!--\s*docs-test:\s*skip\s*-->\s*```python\n(.*?)```", re.S)
_BLOCK = re.compile(r"```python\n(.*?)```", re.S)


def _exclusion_rules() -> tuple[list[str], set[str]]:
    """The excluded prefixes, and the individual pages published back out.

    `exclude_docs` is gitignore syntax, so a `!page.md` line re-includes one
    file from an excluded directory. Parsed rather than duplicated here, so a
    page cannot be published without landing under this test.
    """
    text = MKDOCS.read_text(encoding="utf-8")
    m = re.search(r"^exclude_docs:\s*\|\s*\n((?:[ \t]+\S.*\n)+)", text, re.M)
    if not m:
        return [], set()
    prefixes, reincluded = [], set()
    for entry in m.group(1).split():
        if entry.startswith("#"):
            continue
        if entry.startswith("!"):
            reincluded.add(entry[1:])
        else:
            prefixes.append(entry)
    return prefixes, reincluded


def _published_pages() -> list[Path]:
    if not DOCS.is_dir():
        return []
    prefixes, reincluded = _exclusion_rules()
    out = []
    for p in sorted(DOCS.rglob("*.md")):
        rel = str(p.relative_to(DOCS)).replace("\\", "/")
        if rel not in reincluded and any(rel.startswith(e) for e in prefixes):
            continue
        if _BLOCK.search(p.read_text(encoding="utf-8")):
            out.append(p)
    return out


def _session(page: Path) -> tuple[str, int, int]:
    """The page's executable blocks, concatenated. Also how many were left out."""
    text = page.read_text(encoding="utf-8")
    exempt = {m.group(1) for m in _FRAGMENT.finditer(text)}
    exempt |= {m.group(1) for m in _SKIP.finditer(text)}
    parts, skipped = [], 0
    for m in _BLOCK.finditer(text):
        src = m.group(1)
        if src in exempt:
            skipped += 1
            continue
        line = text[: m.start()].count("\n") + 1
        parts.append(f"# --- {page.name}:{line}\n{src}")
    return "\n".join(parts), len(parts), skipped


PAGES = _published_pages()


@pytest.mark.skipif(not PAGES, reason="docs-site not present in this checkout")
@pytest.mark.parametrize("page", PAGES, ids=lambda p: str(p.relative_to(DOCS)).replace("\\", "/"))
def test_published_python_examples_run(page: Path) -> None:
    source, count, skipped = _session(page)
    if not count:
        pytest.skip(f"all {skipped} block(s) marked fragment or skip")

    with tempfile.TemporaryDirectory() as td:
        script = Path(td) / "page.py"
        script.write_text(source, encoding="utf-8")
        # Run somewhere disposable. A how-to that writes a review pack to
        # `data/review_packs/...` should be executed as written rather than
        # softened into a fragment, and the only cost of doing that is a
        # directory nobody wanted in the repo. Relative paths land here instead.
        proc = subprocess.run(
            [sys.executable, str(script)],
            capture_output=True, text=True, timeout=600, cwd=td,
        )

    if proc.returncode != 0:
        tail = "\n".join(proc.stderr.strip().splitlines()[-12:])
        pytest.fail(
            f"{page.relative_to(DOCS)}: {count} block(s) run as one session, "
            f"exited {proc.returncode}.\n"
            f"The '# --- page.md:N' comments in the traceback give the block.\n\n"
            f"{tail}\n\n"
            "If the block is illustrative rather than runnable, put "
            "<!-- docs-test: fragment --> directly above it."
        )


def test_the_marker_is_not_being_used_to_hide_everything() -> None:
    """A test everyone can silence is not a test.

    No threshold here is principled; this is a smoke alarm for the failure mode
    where a page starts failing and the fix is to mark its blocks exempt.
    """
    total = exempt = 0
    for page in PAGES:
        _, count, skipped = _session(page)
        total += count + skipped
        exempt += skipped
    if total and exempt / total > 0.5:
        pytest.fail(
            f"{exempt} of {total} published examples are marked fragment or "
            "skip. The marker is for blocks that genuinely cannot run, not for "
            "quieting this test."
        )
