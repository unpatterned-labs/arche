# Contributing to arche

Thanks for considering it. This document covers how to get the project
running, what we look for in a change, and the few rules that are specific to
a project that handles identity data.

By participating you agree to the [Code of Conduct](./CODE_OF_CONDUCT.md).

## Getting set up

You need Python 3.11+ and [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/unpatterned-labs/arche
cd arche
uv sync
```

Run the tests:

```bash
uv run pytest packages/arche-core/tests -q
```

You should see roughly 1,458 passing and 3 skipped. The three skips are
optional heavy dependencies (`shapely`, `docling`) that the base install
deliberately does not pull in — they are not failures.

Lint:

```bash
uv run ruff check packages/arche-core/src
```

Build the documentation site:

```bash
uvx --with-requirements docs-site/requirements.txt mkdocs build --strict -f docs-site/mkdocs.yml
```

`--strict` is what CI runs. It fails on broken internal links and missing nav
entries, so build locally before opening a docs PR.

## Where things live

| Path | What it is |
|---|---|
| `packages/arche-core/src/arche/` | The library |
| `packages/arche-core/tests/` | The test suite |
| `docs-site/docs/` | The published documentation site |
| `datasets/` | Name equivalences, taxonomies, and the data packs |
| `examples/` | Runnable end-to-end scripts |

Inside the library, the substrates are `detect` (find things), `resolve` (work
out what they refer to), `policy` (what the statute says), `sign` and `attest`
(prove what was decided), and `workflow` (compositions of the above).
[How arche works](https://unpatterned-labs.github.io/arche/concepts/how-it-works/)
is the orientation doc worth reading first.

## Rules specific to this project

**Never commit real personal data.** Not in tests, fixtures, issues, PR
descriptions, or commit messages. Synthetic values only. This is the one rule
we will revert a merged commit over.

**A claim in the docs must be reproducible from the repository.** If you add a
number — an accuracy figure, a recall percentage, a benchmark result — ship the
script or dataset that produces it, or do not make the claim. Documentation
that says more than the code does is the specific failure mode this project
exists to avoid, and we have shipped it before.

**Paste real output, not idealised output.** If an example prints something,
run it and paste what it actually printed.

**Abstention is a feature, not a bug.** `review` and `unknown` are correct
answers when the evidence does not support a verdict. A change that increases
match rates by lowering the bar for calling two records the same entity is a
regression, even if a metric goes up. Two people who share a name are not one
person.

**Statute packs cite their sections.** A new or changed mapping in
`policy/statutes/*.yaml` needs the specific section it comes from. Do not set
`review_status: regulator-reviewed` without naming a reviewer — the loader
rejects it, deliberately.

## Making a change

1. Open an issue first for anything substantial, so you do not build something
   we were about to change underneath you. Small fixes can go straight to a PR.
2. Branch from `main`.
3. Write a test. For a bug fix, write the test that fails first, so we know it
   catches the thing.
4. Run the tests and the linter.
5. Update the CHANGELOG under the unreleased heading if the change is
   user-visible.
6. Open the PR and fill in the template.

### A note on tests

Assert the contract, not the current output. We shipped a bug for a full
release because a test asserted `"NDPA-2023@vv1.0"` with the comment
`# version field as stored` — it pinned the malformed string in place instead
of catching it. If you find yourself writing an assertion that encodes
behaviour you would not defend in a design review, that is the bug.

## Adding a new entity type or data pack

Most of the interesting contributions look like this, and most of them are
data rather than code. A new name-equivalence group, a new ID format, a new
address convention, a correction to something we got wrong. These are very
welcome, especially from people who know the convention first-hand.

Include the source of the knowledge where you can — a standards document, a
registry, an official format specification, or a plain statement that this is
how it is done where you are, which is also valid evidence. Corrections to
existing data are as valuable as additions.

## AI-assisted contributions

AI-assisted contributions are allowed, but contributors remain fully
responsible for their work.

Before submitting AI-assisted code, ensure that:

- you understand the code;
- the code is compatible with this project's license;
- no private or confidential data was used improperly;
- the change is tested;
- security-sensitive logic received careful human review;
- material AI assistance is disclosed in the pull request.

See [AI_POLICY.md](./AI_POLICY.md) for the full policy.

## Security

Do not open a public issue for a security vulnerability. See
[SECURITY.md](./SECURITY.md) for how to report one privately.

## Licence

The framework is Apache-2.0. Dataset licensing differs and is documented in
[LICENSING.md](./LICENSING.md) and the individual dataset cards. Contributions
are accepted under the licence of the thing you are contributing to.
