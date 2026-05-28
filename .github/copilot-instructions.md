# Copilot / agent instructions for `arche`

This file is the routing index for AI coding agents working in this repo.
The canonical, work-area-specific guidance lives under `.github/instructions/`.
Re-read the relevant file before major edits, releases, or PR-ready summaries.

## Canonical source
- Files under `.github/instructions/*.instructions.md` are canonical for repository-specific conventions.
- If guidance conflicts, prefer the most specific matching `.instructions.md` file.
- For one-shot tasks (new feature, bug fix, release, etc.), see `.github/prompts/*.prompt.md`.

## Task routing
- For **onboarding / first-touch** in any package, read `.github/instructions/onboarding.instructions.md`.
- For **`arche-core` Python code** (the published SDK), read `.github/instructions/arche-core-python.instructions.md`.
- For **detection / per-country / lexicon** work (`arche.detect.*`, `arche.addr`), read `.github/instructions/detection-layer.instructions.md`.
- For **policy / statute / governance** work (`arche.policy`, `statutes/*.yaml`, jurisdiction packs), read `.github/instructions/policy-and-statutes.instructions.md`.
- For **sign / credentials / verifiability** (`arche.sign`, `arche.credentials`), read `.github/instructions/signing-and-credentials.instructions.md`.
- For **tests** in `packages/arche-core/tests/`, read `.github/instructions/testing.instructions.md`.
- For **release / PyPI publish**, read `.github/instructions/release-arche-core.instructions.md`.
- For **PR hygiene / commits / scope discipline**, read `.github/instructions/repo-workflow.instructions.md`.

## Project defaults
- **Project**: `arche` — the open-source identity workflow framework by Unpatterned Labs. The repo is a `uv` workspace; the published Python package is `arche-core` under `packages/arche-core/`. Sibling packages: `arche-mcp`, `api/` (FastAPI), `web/` (Next.js 14), `demo/` (Streamlit).
- **Tagline**: *African-first, globally pluggable. Detect → Resolve → Link → Verify → Govern.*
- **v0.2 public API**: `from arche import Pipeline, Result, Detection` plus the Level-2 workhorses `detect`, `match`, `link`, `resolve` (legacy), and `resolve_places` / `list_places`. The v0.1 surface is lazy-loaded (PEP 562 `__getattr__`) for backward compat; new code should not extend it.
- **Stack**: Python 3.11+ • dataclasses + pydantic v2 • rapidfuzz / jellyfish / phonenumbers / networkx / h3 / cryptography (base install) • GLiNER + Splink + Presidio (opt-in extras).
- **Always use `uv`**: `uv sync --all-packages` to refresh the workspace; `uv run <command>` to execute scripts/tests; `uv run pytest packages/arche-core/tests` to run the SDK suite.
- **Architectural principle (Karpathy)**: simplicity first, surgical changes, no speculative abstractions. Restate the goal as a verifiable check before editing. Detailed coding standards live in the instruction files above; do not duplicate them here.
