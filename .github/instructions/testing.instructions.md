---
applyTo:
  - "packages/arche-core/tests/**/*.py"
  - "packages/arche-core/src/**/*.py"
---

# Testing (`arche-core`)

## Expectations
- **Any behavioural change ships with test updates.** No exceptions.
- **Targeted first, broad second.** Run the test file nearest the change, then the full suite.
- **Tests are deterministic.** No clock-based assertions without freezing time, no network without mocking, no shared mutable global state across tests.
- **Tests document intent.** A failing test name should tell you what the system was supposed to do, not what the code does.

## Commands
```bash
# Full arche-core suite (what CI runs)
uv run pytest packages/arche-core/tests -q --tb=short

# Single file
uv run pytest packages/arche-core/tests/test_jurisdiction_nigeria.py -q

# Single test
uv run pytest packages/arche-core/tests/test_pipeline.py::test_pipeline_NG_pipeline_emits_redacted -q

# With coverage (local only)
uv run pytest packages/arche-core/tests --cov=arche --cov-report=term-missing
```

The CI invocation is in `.github/workflows/arche-core-tests.yml` — keep local and CI in sync.

## Where to put new tests
- `tests/test_pipeline.py` — anything that calls `Pipeline.process(text)` end-to-end.
- `tests/test_jurisdiction_<country>.py` — new statute mappings, new per-country detectors going through `Pipeline`.
- `tests/test_african.py` — pan-African detector regressions (cross-cutting `_africa/` module).
- `tests/test_extract.py` — `extract()` / `detect()` Level-2 API regressions.
- `tests/test_resolve.py` / `test_resolve_v2.py` — `resolve_entities`, the matcher.
- `tests/test_ids_validators.py` — checksum / length / prefix validators.
- `tests/test_protect.py` — `detect_pii`, `redact`, Presidio integration.
- `tests/test_governance.py` — v0.1 governance shim (do not extend; this is deprecation-window only).
- `tests/test_review.py` — `ReviewQueue` (v0.1 surface; do not extend).
- `tests/test_models.py` — pydantic model parity with dataclass `types.py`.
- `tests/test_h3.py` / `test_graph.py` — geo cells and NetworkX views.
- `tests/test_llm.py` — LLM proposer (`backend="auto+llm"`).
- New module → new file (`tests/test_<module>.py`). Keep one file per src module.

## Fixtures
- `conftest.py` provides shared fixtures (jurisdiction-loaded `Pipeline`, fake key material, sample text). Read it before writing new ones.
- Names and IDs in fixtures are realistic but **never real**. Use generated UUIDs, well-known fake NINs (`12345678901`), composed names (`"Fatima Abdullahi"`).
- If a fixture needs disk state (persisted `ReviewQueue` JSON, statute YAML override), use `tmp_path` — never write into the repo.

## What to test for each layer
- **Detect**: span positions (`start`, `end`), category string, confidence, country attribution. Test the negative case (text without the entity should yield zero detections).
- **Policy**: `policy_outcomes[i].action`, `policy_outcomes[i].statute_reference`, redacted text shape. Test the *unmapped category* case to confirm it stays unredacted with the documented default.
- **Sign**: round-trip (`sign(payload) → verify(jws)`) returns the same payload. Test verification failure on tampered payload, wrong key, expired envelope.
- **Pipeline**: smoke test per jurisdiction. Check `result.metadata["statute_id"]`, `result.metadata["pipeline_version"]`, audit log entry count.

## Definition of done (testing)
- Behavioural changes include matching test updates or additions.
- Targeted tests for touched areas pass.
- Full `uv run pytest packages/arche-core/tests` passes.
- PR description reports commands run + pass/fail.
- No `xfail` or `skip` introduced without a one-line reason in the PR.
