---
mode: agent
description: Fix a bug in arche-core. Root-cause-first; no fixes without a reproducing test.
---

# Bug fix workflow

Iron law: **no fixes without a reproducing test**. If you can't reproduce it, you don't understand it. If you don't understand it, your "fix" is a guess.

## 1. Reproduce
- Write a failing test **first** in the appropriate `packages/arche-core/tests/test_*.py`.
- The test must fail for the reason described in the bug report, not for some incidental other reason.
- Run `uv run pytest packages/arche-core/tests/test_<file>.py::test_<your_repro> -v` — confirm it's red.

## 2. Diagnose
- Identify the **specific module and line range** where the bug originates. Not "somewhere in resolve" — `arche/resolve/_matcher.py:142-158`.
- State the **why** in one sentence: what assumption did the original author make that doesn't hold?
- Decide the layer: is this a detection bug (category, span, confidence)? a policy bug (statute mapping)? a signing bug (envelope shape, kid encoding)? a workflow bug (pipeline composition)?

## 3. Minimal patch
- Smallest change that makes the test green and does not regress neighbouring tests.
- Do not "while I'm here" refactor. Do not rename. Do not reformat.
- If the bug exposes a structural problem that needs a real refactor, file a follow-up issue and ship the minimal patch in this PR.

## 4. Validate
- Run the new test alone — green.
- Run the file's full test set — green.
- Run the layer's full test set (e.g. all `test_jurisdiction_*.py` if you touched policy) — green.
- Run the full `uv run pytest packages/arche-core/tests` — green.

## 5. Guard against recurrence
- The reproducing test from step 1 **stays** as the regression guard.
- If the bug came from a class of mistakes (e.g. forgetting to register a `MatchReason` enum, missing category in a statute YAML), add a check that would have caught the class — not just this instance.

## 6. Summarise in the PR
- One sentence: what was broken, who saw it.
- One sentence: root cause (the assumption that didn't hold).
- One sentence: fix (the smallest change that holds).
- Test evidence: commands run + outcomes.

## Anti-patterns to avoid
- "Catch and ignore" — never. If something can fail, either handle it explicitly (with a logged warning + actionable next step) or let it raise.
- "Add a flag to opt out of the buggy path" — almost never. Fix the path.
- "Bump the version number to force re-install" — never. That's not a fix.
