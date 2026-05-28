---
mode: agent
description: Cut a release of arche-core and publish to PyPI.
---

# Release `arche-core`

Follow this end-to-end when shipping a new version. The full reference is `.github/instructions/release-arche-core.instructions.md`.

## 1. Decide the version
- Current: read `packages/arche-core/src/arche/_version.py` and `packages/arche-core/pyproject.toml`.
- Pick the next: alpha bump (`0.2.0a1 → 0.2.0a2`), beta promotion, RC, or release. See the SemVer table in the instructions file.

## 2. Pre-flight (all must be green)
```bash
uv sync --all-packages
uv run ruff check packages/arche-core
uv run pytest packages/arche-core/tests -q --tb=short
```
If any step is red: **stop**. Fix or revert. Do not ship red.

## 3. Update the version
- Edit `packages/arche-core/pyproject.toml` line `version = "<new>"`.
- Edit `packages/arche-core/src/arche/_version.py` `__version__ = "<new>"`.
- Edit `CHANGELOG.md`: move "Unreleased" entries under a new `## [<new>] - YYYY-MM-DD` heading.
- Verify `packages/arche-core/README.md` install instructions are still accurate (`pip install arche-core` examples resolve).

## 4. Build
```bash
cd packages/arche-core
rm -rf dist build *.egg-info
uv build
ls -lh dist/
```
Expect: `arche_core-<new>-py3-none-any.whl` and `arche_core-<new>.tar.gz`. Base wheel should be under ~5MB.

## 5. Smoke test the wheel
```bash
uv venv /tmp/arche-smoke
uv pip install --python /tmp/arche-smoke/bin/python packages/arche-core/dist/arche_core-<new>-py3-none-any.whl
/tmp/arche-smoke/bin/python -c "
from arche import Pipeline
r = Pipeline(jurisdiction='NG').process('Fatima Abdullahi, NIN 12345678901, BVN 22100987654')
assert any(d.category == 'PII-2-NIN' for d in r.detections), 'NIN not detected'
assert any(d.category == 'PII-2-BVN' for d in r.detections), 'BVN not detected'
print('smoke ok:', r.redacted_text)
"
```

## 6. Publish to TestPyPI first
```bash
uv publish --publish-url https://test.pypi.org/legacy/ packages/arche-core/dist/*
```
Then verify install from TestPyPI works on a clean venv. Only after TestPyPI is green proceed to step 7.

## 7. Publish to real PyPI
```bash
uv publish packages/arche-core/dist/*
```

## 8. Tag and push
```bash
git add packages/arche-core/pyproject.toml packages/arche-core/src/arche/_version.py CHANGELOG.md
git commit -m "release(arche-core): v<new>"
git tag arche-core-v<new>
git push origin main
git push origin arche-core-v<new>
```

## 9. Post-release
- Create the GitHub release: `gh release create arche-core-v<new> --notes-from-tag`.
- Bump the dev version forward by one alpha to prevent main from masquerading as the release. Commit and push.
- Announce in the unpatterned.org changelog and relevant channels if the release is user-visible.

## Stop-the-line conditions
- Wheel size > ~5MB → investigate before publishing.
- CI on Windows or macOS red → fix before publishing.
- A test was skipped without explanation → un-skip or document in the CHANGELOG; do not ship silently-skipped behaviour.
- `pyproject.toml` `Repository` URL is stale (e.g. wrong org name) → fix before publishing or it ships broken metadata.
- The CLI script (`[project.scripts]`) is back in `pyproject.toml` without the v0.2-aware CLI actually being implemented → remove it; the v0.1 CLI was intentionally dropped.
