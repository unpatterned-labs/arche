---
mode: agent
description: Refactor arche-core code without changing behaviour. Public-API-safe by default.
---

# Safe refactor workflow

Refactoring in `arche-core` is high-risk because of the v0.1 deprecation shim — the `_LAZY` dict in `arche/__init__.py` and the callable `arche.resolve` module are load-bearing for downstream users still on v0.1.

## 1. Establish invariants
Before any edit, list what must **not** change:
- Public API names (`arche.__init__.__all__` + every name in `_LAZY`).
- Behaviour reachable from `Pipeline.process(text)` for the four launch jurisdictions (NG, KE, ZA, GH).
- The shape of `Result` and `Detection` dataclasses.
- The JWS envelope schema (`ENVELOPE_SCHEMA_VERSION`).
- Statute YAML files in `arche/policy/_data/`.

If the refactor touches any of these, **stop**, and either reduce scope or convert this to a feature/RFC PR.

## 2. Document current protection
- Identify the tests that prove the invariants hold today.
- Run them once before any edit — record pass/fail counts. This is your baseline.
- If a critical invariant is **not** covered by tests, add the missing test **before** refactoring. Refactoring with no safety net is irresponsible.

## 3. Decompose
- Refactor in **small, independently-verifiable steps**. Each step is one logical change that keeps every test green.
- Mechanical first (renames, moves), behavioural-equivalent second (split a function, inline a helper), structural last (module reorganisation).
- Each step is one commit. The PR is the sum.

## 4. Execute
- Use IDE refactoring tools for renames — they are less error-prone than hand-edits.
- Cross-layer imports are usually the bug, not the cycle. If you find one, fix the layering instead of the import.
- Do not change public API names. If the rename is justified, add an alias on the old name with a `DeprecationWarning` and target removal at the next major.

## 5. Test after every step
- Targeted: the file you just changed.
- Layer: e.g. all `test_jurisdiction_*.py` if you touched `policy/`.
- Full: `uv run pytest packages/arche-core/tests` — must match the baseline from step 2 (same pass count, same skip count).

## 6. Demonstrate equivalence in the PR
- "Before" baseline counts.
- "After" counts.
- Note any **deliberate** behavioural change with a one-line justification (and a corresponding test update). Otherwise, equivalence is the contract.

## Hard rules
- **No new dependencies** in a refactor PR.
- **No public-API removals** in a refactor PR — even from the `_LAZY` shim. Deletions of shim entries are a breaking change, ship them separately with a CHANGELOG line.
- **No formatting churn** outside the refactored region. Run `ruff` over the touched files only.
- If the refactor exposes a bug, file a follow-up — do not silently fix it in this PR.
