---
applyTo:
  - "**"
---

# Onboarding (Stage 0)

Read this once when you first touch the repo or come back after a long gap. Then route to the more specific instruction files.

## Mental model
- **`arche-core`** (in `packages/arche-core/`) is the published Python SDK. It is the canonical product of this repo. Everything else either consumes it (`api/`, `web/`, `demo/`, `arche-mcp/`) or feeds it (`datasets/`).
- **The five-step identity lifecycle**: `Detect → Resolve → Link → Verify → Govern`. Each step is its own module: `arche.detect`, `arche.resolve`, `arche.link` (Stage 2), `arche.sign` + `arche.credentials`, `arche.policy` + `arche.graph.audit`.
- **`Pipeline` is the v0.2 primitive.** It composes detect + statute policy + audit for one jurisdiction. The v0.1 `resolve()` god-function still works through a lazy deprecation shim but is not the recommended path.

## Source layout (only the parts you usually touch)
- `packages/arche-core/src/arche/__init__.py` — public surface; eager v0.2 names + PEP-562 lazy v0.1 names.
- `packages/arche-core/src/arche/workflow/_primitive.py` — `Pipeline`, `Result`, `Detection`.
- `packages/arche-core/src/arche/detect/` — per-country detectors (`ng/`, `ke/`, `za/`, `gh/`), the pan-African fallback (`_africa/`), and cross-cutting detectors (`names/`, `locations/`, `phones.py`, `ip/`, `digital_id/`).
- `packages/arche-core/src/arche/policy/` — `load_statute`, `apply_policy`, statute YAML loader. Statute files live in `packages/arche-core/src/arche/policy/_data/`.
- `packages/arche-core/src/arche/sign/` — Ed25519 + did:key + JWS envelope. `arche.credentials` builds SD-JWT-VC on top.
- `packages/arche-core/src/arche/resolve/` — `classical.py` (in-memory fuzzy + Fellegi-Sunter), `_matcher.py` (`IdentityMatcher`, jurisdiction priors), `places.py` (the `resolve_places` / `list_places` v0.2.0a2 surface).
- `packages/arche-core/tests/` — 414+ tests; one file per module convention.
- `packages/arche-core/pyproject.toml` — the source of truth for version, dependencies, and optional extras.

## First commands
```bash
uv sync --all-packages                                    # install all workspace members
uv run pytest packages/arche-core/tests -q --tb=short     # what CI runs
uv run ruff check packages/arche-core                     # lint
```

## When to stop and read another file
- About to edit Python in `packages/arche-core/src/arche/` → `arche-core-python.instructions.md`
- About to add or change a detector or lexicon → `detection-layer.instructions.md`
- About to change a statute YAML or policy mapping → `policy-and-statutes.instructions.md`
- About to add tests → `testing.instructions.md`
- About to bump version and publish → `release-arche-core.instructions.md`

## What this repo is NOT (do not drift)
- Not a hosted product. The hosted SaaS is **Plehthore**, a separate repo. Do not add web UI, billing, or auth here.
- Not a place for speculative abstractions. The Karpathy guidelines (in `CLAUDE.md`) apply: minimum code, surgical changes, no flexibility we haven't been asked for.
- Not a FHIR adapter. The `arche-adapters` package was removed (`b927c8c`); DPI integrations are Stage 2 work in a sibling repo.
