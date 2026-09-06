# Changelog

All notable changes to `arche-mcp` are documented here. Format loosely follows [Keep a Changelog](https://keepachangelog.com/) and the project uses [PEP 440](https://peps.python.org/pep-0440/) version identifiers.

`arche-mcp` is versioned independently of `arche-core` and deliberately does not mirror its number. Matching versions would read as lockstep, and users would assume the pairing is required forever.

## [0.1.0a1] — unreleased

**First release from the arche repository. Ten tools, one removed, jurisdiction inferred rather than configured.**

**The ledger.** With `ARCHE_LEDGER=duckdb:///FILE` the server remembers: `compare_records` records every edge it returns, and eight tools appear — `decision`, `explain`, `replay`, `entities`, `path`, `cases`, `observe`, `resolve`. Registered only when configured, so an unconfigured server shows no tool that can only fail. Value policy is stricter than the CLI's: there is no reveal; entities come back as field names, records as labels, decisions as factors and pins. `capabilities()["ledger"]` says whether it is on.

Requires `arche-core>=0.8.0,<0.9.0`. The bound is closed on purpose: `uvx arche-mcp` re-resolves on every run, so the ceiling moves by a release of this package rather than by whatever `arche-core` publishes next.

The package existed before this in a separate repository and was never published. Its version there was `0.1.0a3`; starting at `0.1.0a1` here rather than continuing that line, because reusing numbers that never shipped invents a history.

### The tools

| tool | what it answers |
| --- | --- |
| `capabilities` | what this installation can actually do |
| `infer_jurisdiction` | which law governs this document, and is there a pack for it |
| `plan_protection` | what could this pipeline find, and what could it not |
| `describe_pack` | which record fields an entity pack reads |
| `detect_pii` | personal data as offsets, with citations |
| `detect_entities` | named entities as typed offsets |
| `guarded_scan` | redact to hashed IDs, fail-closed |
| `compare_records` | reconcile two record lists |
| `check_name_equivalence` | are these two names the same person's |
| `extract_places` | place mentions with their spatial role |

### Removed — `compare_files`

It took two agent-supplied filesystem paths, read them, and wrote an HTML report to a third agent-supplied path, defaulting to overwriting `arche-report.html` beside the caller's input data.

The read reach was weak — `_load_records` requires a JSON list of objects, so most credential files raise rather than parse. The **write** reach was not. `out` was unbounded, so an agent could write to any path the process could write. The content was constrained to HTML; the path was not, and overwriting an arbitrary file with HTML is a destructive primitive regardless of the bytes.

MCP has no capability or consent model for filesystem writes. An agent-callable arbitrary local read-and-write is the primitive a server should not offer, and the filesystem-touching twin already exists in the right place: the `arche compare` CLI, where a person sees the command before it runs.

### Added — the jurisdiction flow

`ARCHE_JURISDICTION` was the only way to say which law applied: one setting, applied to every document alike. That works for a single-jurisdiction deployment and cannot work on a mixed stream.

`infer_jurisdiction` reads the document instead — identifiers, registrars, regulators, currency, phone shapes — and returns the proposal with its evidence, its margin, and its runner-up. It abstains rather than guessing.

It also returns `policy_available`, and that field is why the tool is usable. Without it an agent receives `country="US", confidence=1.0, abstained=false`, calls `guarded_scan`, and is refused for having no statute, which reads as a bug rather than the designed boundary it is. When no pack governs, `policy_reason` says why — sometimes because none ships, sometimes because no such law exists — and `policy_alternatives` names what to pass instead.

`plan_protection` answers the same question about detectors, *before* a document is handed over. It reports which categories the statute governs that nothing installed can find, and separately which have a detector built for somewhere else.

### Changed — configuration is a ceiling, not a default

Moving jurisdiction from a setting to an argument otherwise hands the choice of governing law to the agent, and an agent that can choose its statute can choose a weaker one. So `ARCHE_JURISDICTION` and `ARCHE_STATUTE` now set the strictest policy the server will operate under: a per-call argument may narrow and cannot override. Unset, the caller chooses, which is the mixed-stream case.

### Changed — `check_name_equivalence` returns a band

It returned `{equivalent: bool}` at a hardcoded 0.85. A boolean at a fixed threshold has no way to say "close, and not close enough to assert", which is the state most interesting pairs are in. Now `match` / `review` / `no_match` with the score and the thresholds, matching arche's vocabulary everywhere else.

### Changed — `compare_records` takes an entity pack

`entity="person"` instead of hand-written comparators. Note this routes through `crosswalk` rather than `reconcile`: entity packs contain `tftoken` comparators that price how ordinary a shared word is, and those need a frequency table `reconcile` does not build. Passing a pack straight to `reconcile` looked right and raised on every pack that weighs rarity, which is all of them.

### Changed — nothing is silent

`detect_pii` and `guarded_scan` both carry a coverage block. `count: 0` from a pipeline with no detector for the locale is indistinguishable from a clean document, and that ambiguity is the failure this surface most needs not to reproduce.

`detect_entities` reports `ner_backend_installed`, because without a NER backend it finds pattern-shaped identifiers and no personal names at all, and returns an empty list rather than an error.

Every tool that returns offsets says which text they index. `guarded_scan`'s redacted output has different offsets from the original — replacement tokens are a different length — so slicing one with the other returns the wrong span, and a shifted window can expose an adjacent value.

### Fixed — no private imports from arche-core

The handlers reached into `arche.cli._load_records` and `arche.resolve._matcher.compare_names`. Publishing freezes whatever you import, and a version pin does not protect a private name because a patch release can rename it. Both now have public homes in `arche-core` 0.6.0a1: `arche.resolve.compare_names` and `arche.review.read_records`.

### Fixed — the MCP SDK moved

The server was written against `mcp.server.fastmcp`, which the SDK removed in 2.0. It imported cleanly in its old repository only because that repository's lock held an SDK generation behind; a fresh install resolved `mcp>=1.0` to 2.0 and could not import. Now `mcp.server.MCPServer`, pinned `mcp>=2.0,<3`. The decorator API is unchanged.

### The arche-core pin

`arche-core>=0.6.0a1,<0.7.0`, and both bounds matter. The floor is hard: this package imports `arche.coverage`, `arche.policy.statute_for`, `arche.resolve.compare_names` and `arche.review.read_records`, none of which exist in 0.5.0a1. The ceiling is the point. `uvx arche-mcp` re-resolves on every invocation, so an open pin means the hour a breaking arche-core alpha is published, every existing user's next run breaks at once, with no action by them and none by us. A closed bound turns that into a release chore we control.
