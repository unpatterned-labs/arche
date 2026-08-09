<!--
Thanks for the contribution. Delete any section that does not apply.
For a security fix, see SECURITY.md first — do not describe an unpatched
vulnerability in a public PR.
-->

## What this changes

<!-- One or two sentences. What is different after this merges? -->

## Why

<!-- The problem this solves. Link the issue if there is one: Closes #123 -->

## How it was verified

<!--
Not "I ran the tests" — what did you actually observe? Paste the real output.
If you fixed a bug, show the test that fails without the change.
-->

```
```

## Checklist

- [ ] `uv run pytest packages/arche-core/tests -q` passes
- [ ] `uv run ruff check packages/arche-core/src` is clean
- [ ] Tests cover the change, and a bug fix has a test that fails without it
- [ ] CHANGELOG updated if this is user-visible
- [ ] Docs updated if this changes documented behaviour
- [ ] **No real personal data** in code, tests, fixtures, commit messages, or
      this description

## If this touches documentation

- [ ] Every code snippet was executed, and the pasted output is what it
      actually printed
- [ ] `mkdocs build --strict` passes
- [ ] Any number claimed is reproducible from something in this repository

## If this touches resolution, policy, or signing

- [ ] Abstention is preserved — this does not turn a `review` into a match by
      lowering the bar for calling two records the same entity
- [ ] Any new statute mapping cites its specific section
- [ ] Anything that enters a signature is deterministic across runs
- [ ] Breaking changes to signed output or verification are called out
      explicitly above

## AI assistance

<!--
Per AI_POLICY.md: disclose material AI assistance. This is not a mark against
the contribution — it is allowed and normal. State what was assisted and
confirm you understand and have reviewed the result.
-->
