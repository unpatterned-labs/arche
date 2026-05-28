---
mode: agent
description: Add a new feature to arche-core (a new detector, statute mapping, signing primitive, or workflow).
---

# New feature workflow

Use this when adding net-new behaviour to `arche-core`. For bug fixes, use `bugfix.prompt.md`. For renaming/restructuring, use `refactor-safe.prompt.md`.

## 1. Scope confirmation
Before any edit, restate:
- **What is being added** in one sentence.
- **What layer** it belongs to (`detect`, `resolve`, `policy`, `sign`, `credentials`, `workflow`).
- **Which existing module** it lives in or beside. New modules need a justification — defaults are *extend a neighbour*, not *create a new file*.
- **Verifiable success criterion** — the test name and the assertion shape. If you can't write this, the scope is not clear enough.

## 2. Context review
Read in this order:
1. `.github/instructions/arche-core-python.instructions.md` (style).
2. The most specific layer instruction file (`detection-layer`, `policy-and-statutes`, `signing-and-credentials`).
3. The two nearest modules to where the code will live.
4. The existing test file you'll extend (or the nearest sibling).

## 3. Design
- Sketch the public signature first. One function, lower-case, three positional + optional keyword-only params at most. If you need more, the abstraction is wrong.
- Decide whether the new name appears in `arche.__init__.__all__` (v0.2 surface) or stays module-local. Default: module-local.
- Identify which existing tests will need to keep passing.

## 4. Implement
- Surgical edits — every changed line traces to step 1.
- Top-of-file imports; function-local only for lazy / extras / cycle-break.
- If the feature depends on a new optional package, add it under `[project.optional-dependencies]` with a comment explaining the gate. Do **not** add to base `dependencies`.

## 5. Test
- Add a happy-path test.
- Add the negative case (no input → no output, malformed input → actionable error).
- For African-context features: add a test using a non-Latin / tonal-mark / mixed-language example.
- Run `uv run pytest packages/arche-core/tests/test_<your_area>.py -q` first, then the full suite.

## 6. Report
PR description includes:
- One sentence: what the feature does, who's the consumer.
- The new public API (if any), exact signature.
- Test commands run + outcomes.
- Anything you considered and explicitly rejected ("considered adding X, didn't, because Y").

## Constraints
- British or American English; pick one per file.
- No emojis in code, docstrings, or commit messages unless the user explicitly requested them.
- Karpathy: simplicity first, surgical changes, no speculative abstractions.
- Cite the existing similar feature if there is one — uniformity > novelty.
