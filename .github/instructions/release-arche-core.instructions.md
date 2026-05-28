---
applyTo:
  - "packages/arche-core/pyproject.toml"
  - "packages/arche-core/src/arche/_version.py"
  - "packages/arche-core/README.md"
  - "CHANGELOG.md"
---

# Releasing `arche-core` to PyPI

## Versioning
- The single source of truth for the version is `packages/arche-core/pyproject.toml` line `version = "..."`.
- `packages/arche-core/src/arche/_version.py` must match exactly. Both are bumped in the same commit.
- We follow **SemVer + PEP 440**:
  - `0.2.0a1` → `0.2.0a2` (alpha) — fast iteration, breaking changes allowed.
  - `0.2.0a*` → `0.2.0b1` (beta) — feature complete, no breaking changes.
  - `0.2.0b*` → `0.2.0rc1` (release candidate) — bug fixes only.
  - `0.2.0rc*` → `0.2.0` (release).
  - Once `0.2.0` is shipped, every breaking change goes to `0.3.0`; everything else is `0.2.x`.
- The v0.1 backward-compat shim is removed in **v0.3**. Anything in `arche/__init__.py`'s `_LAZY` dict goes away then; flag the user-visible impact in the `0.3.0a1` CHANGELOG.

## Pre-flight checklist
Before bumping version:
- [ ] `uv sync --all-packages` clean — no resolver errors.
- [ ] `uv run ruff check packages/arche-core` clean.
- [ ] `uv run pytest packages/arche-core/tests -q` — all green. **Do not ship with skipped tests unless documented in the CHANGELOG.**
- [ ] `packages/arche-core/README.md` reflects the actual public API. Every `from arche import X` example resolves.
- [ ] `CHANGELOG.md` has a section for the new version, populated.
- [ ] Wheel size sanity-checked: `uv build packages/arche-core && ls -lh packages/arche-core/dist/` — base wheel should be under ~5MB. Heavy extras live in optional-dependencies.

## Build and publish
```bash
# From the repo root
cd packages/arche-core

# 1. Clean previous artefacts
rm -rf dist build *.egg-info

# 2. Build sdist + wheel
uv build

# 3. Smoke-install the wheel into a throwaway venv
uv venv /tmp/arche-smoke
uv pip install --python /tmp/arche-smoke/bin/python dist/arche_core-<version>-py3-none-any.whl
/tmp/arche-smoke/bin/python -c "from arche import Pipeline; print(Pipeline(jurisdiction='NG').process('NIN 12345678901').redacted_text)"

# 4. Publish to TestPyPI first (recommended for any non-trivial release)
uv publish --publish-url https://test.pypi.org/legacy/ dist/*

# 5. Verify install from TestPyPI
uv pip install --index-url https://test.pypi.org/simple/ --extra-index-url https://pypi.org/simple/ arche-core==<version>

# 6. Publish to real PyPI
uv publish dist/*

# 7. Tag the release
git tag arche-core-v<version>
git push origin arche-core-v<version>
```

## Things that go wrong at publish time
- **`Repository` URL mismatch** in `pyproject.toml`. Currently `https://github.com/unpatterned-labs/arche` — keep it in sync with the actual repo location on every rename.
- **Missing classifiers**. Every supported Python in `requires-python` must have a matching `Programming Language :: Python :: X.Y` classifier.
- **Stale lockfile**. `uv.lock` at the workspace root is committed. If you bump a dependency, commit the lockfile change with the same PR.
- **CLI dangling**. `packages/arche-core/src/arche/cli.py` exists but is **intentionally NOT shipped as a console script in v0.2.0a1+** — see the comment in `pyproject.toml` near `[project.urls]`. Do not re-add `[project.scripts]` until the v0.2-aware CLI lands in `v0.2.0a2+`.

## Post-release
- Tag the release on GitHub (`gh release create arche-core-v<version> --notes-from-tag`).
- Bump the development version one alpha forward (e.g. `0.2.0a2 → 0.2.0a3.dev0`) on the next commit so `pip install` from main doesn't masquerade as the released version.
- Announce in the relevant channels (Discord, the unpatterned.org changelog page) if the release is user-visible.

## Reference
- The `.github/workflows/arche-core-budget.yml` workflow audits the wheel install size on every PR — if it fails, the release will too. Fix the size before bumping version.
- The `.github/workflows/arche-core-tests.yml` matrix is 3 Pythons × 3 OSes. A release that fails on `windows-latest` or `macos-latest` is not a release.
