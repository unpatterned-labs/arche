---
applyTo:
  - "**"
---

# Repository workflow and change hygiene

## Principles
- **Surgical changes only.** Every changed line should trace to the request. No drive-by refactors, no unrelated formatting, no opportunistic renames.
- **Simplicity first** (Karpathy). Minimum code; no speculative abstractions or unrequested flexibility. If in doubt, leave it out and add a one-line TODO with a date.
- **Keep interfaces explicit and behaviour readable.** Avoid black-box side effects, lazy magic, and clever metaclass tricks. PEP-562 `__getattr__` on `arche.__init__` is the one tolerated exception, because it carries the v0.1 deprecation shim.
- **No drift across the five-layer mental model.** Detection, resolution, linking, verification, governance — each layer is its own module. A "convenient" cross-import that violates that boundary is almost always a smell.

## Branching and PRs
- Branch from `main` for new work. Name branches by intent: `feat/<scope>`, `fix/<scope>`, `chore/<scope>`, `docs/<scope>`.
- Keep diffs focused. If a change starts touching three packages, stop and split.
- PR titles use Conventional Commits: `type(scope): summary` (e.g. `feat(detect): add NHI national insurance pattern for ZA`).
- PR description must include:
  1. **Why** the change exists (link the issue / RFC / CEO plan if one exists).
  2. **What** changed in one sentence per affected layer.
  3. **Test evidence** — `uv run pytest packages/arche-core/tests` output snippet, or the targeted file you ran.
  4. **Public-API impact** — does this change anything importable from `arche`? If yes, flag it explicitly.

## Commits
- One logical change per commit. Avoid 800-line "WIP" commits on `main`.
- Use Conventional Commits: `type(scope): summary` under 72 chars.
- Body explains the *why* and any trade-offs, not the *what* (the diff says what).
- Do not skip pre-commit hooks (`--no-verify`) unless explicitly asked.

## Public-API discipline (`packages/arche-core/src/arche/__init__.py`)
- The eager `__all__` is the **v0.2 recommended surface**. Adding to it is a deliberate act — discuss in the PR first.
- The `_LAZY` dict carries the **v0.1 backward-compat surface**. Do not add new names to it. Removing a name from it is a breaking change; bump the alpha/beta accordingly and call it out in `CHANGELOG.md`.
- New public names default to **lower-case, function-form** unless the thing is genuinely a stateful class. The user-facing 3-line target is `import → call → inspect result`.

## Non-goals
- Do not refactor `arche.workflow.pipeline` or `arche.resolve._matcher` opportunistically. Both are load-bearing for the v0.1 shim; structural changes need an RFC.
- Do not add dependencies to `pyproject.toml` `[project] dependencies` without a written justification. Base install stays under 100MB. Heavy capabilities go in `[project.optional-dependencies]`.
- Do not modify `_version.py` or `pyproject.toml`'s `version` outside of a release commit. See `release-arche-core.instructions.md`.

## Definition of done
- `uv run ruff check packages/arche-core` passes.
- `uv run pytest packages/arche-core/tests` passes (or the deliberately-skipped subset is documented in the PR).
- Public-API changes are reflected in `packages/arche-core/README.md` and `CHANGELOG.md`.
- New behaviour has a test. No exceptions.
