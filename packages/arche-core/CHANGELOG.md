# Changelog

All notable changes to `arche-core` are documented here. Format loosely follows [Keep a Changelog](https://keepachangelog.com/) and the project uses [PEP 440](https://peps.python.org/pep-0440/) version identifiers.

## [0.3.0a1] — 2026-08

First alpha of the 0.3 (beta) line. The published beta criteria
(DPA-consulted statute packs at v1.0, the Africa Address Benchmark with
cross-tool baselines, a 90-day production deployment) remain the gate for
`v0.3.0` proper; this alpha opens the line and its breaking-change window.

### Changed — statute pack maturity, stated honestly

- **All six statute packs are now `version: v1.0`** (NDPA-2023, POPIA, Kenya
  DPA, Ghana DPA, GDPR, HIPAA Safe Harbor). POPIA / Kenya DPA / Ghana DPA
  were labelled `v0.1-scaffold` while carrying complete category mappings —
  and GDPR / HIPAA were already `v1.0` with no external review, so the label
  meant two different things depending on the file.
- **New `review_status` field on every pack**, orthogonal to `version`:
  `version` means *complete and stable* (our work); `review_status` means
  *who vouches for the mappings* (a fact about the world). Values are
  `self-reviewed` (arche's own reading of the cited sections) or
  `regulator-reviewed`. The loader **fails closed**: a pack claiming
  `regulator-reviewed` without a `reviewed_by` is rejected, because a claim
  about regulator engagement is the one claim this product must never fudge.
  All six shipped packs are `self-reviewed`; none claims regulator review.
  Exposed as `Statute.review_status` / `.reviewed_by` / `.reviewed_on`.
- **Beta criterion revised** accordingly — from "POPIA, Kenya DPA and Ghana
  DPA reach v1.0 after structured DPA consultation" to "every shipped statute
  pack carries a complete category mapping with cited sections and a declared
  review status." Regulator review is now tracked per pack and sought
  continuously, rather than gating a release. Revised in the open rather than
  quietly re-checked: 2 of 4 beta criteria are now met.

### Changed — the roadmap is a living document again

- **`concepts/roadmap.md` rewritten for v0.3.0a1.** It had drifted a full
  positioning behind: it described a 980-test v0.2.0a3 whose lead was African
  PII detection, listed `resolve` / `sign` / places as "power-user workflows,
  not the lead pitch", carried "no MCP server" as an explicit non-commitment
  (we ship one), and reported three statute packs as `v0.1-scaffold`. It now
  covers what actually ships (resolve, declare, the LLM lane, spatial roles
  and the referee, detect + govern, attest and the agent surface), tracks the
  beta criteria with per-criterion status, separates **in flight** work into
  the two live tracks, states each **gated** item with the prerequisite that
  gates it, and records three direction changes with their reasons — a
  roadmap that never logs its own reversals is a wish list. Status vocabulary
  (shipped / in flight / gated / not committed) is defined at the top and
  used consistently.
- **Beta criterion 3 corrected to *partially met*.** The v0.3.0a1 notes first
  marked it done on the strength of the callable-shim removal, but the
  criterion as published requires deleting the whole PEP 562 lazy v0.1
  surface — which we deliberately did not do, to avoid breaking alpha users
  twice in one release. The callable shims are gone; the remaining legacy
  names are deprecated with removal targeted for v0.4.

### Removed (breaking)

- **The v0.1 callable-module shim `arche.resolve(text)`.** Promised for
  v0.3 since the v0.2 migration; calling the module now raises `TypeError`.
  `arche.resolve` is purely the facade package (`resolve.pairwise`,
  `resolve.crosswalk`); `Pipeline.process()` is the composition-pattern
  replacement. The `arche.detect(text)` callable is **kept deliberately** —
  it is the documented Level-2 workhorse, not a compat shim. Remaining v0.1
  lazy names stay importable through the 0.3 line; their removal is targeted
  for v0.4. `ResolvedEntity` keeps its name (decision 2026-08-07).

### Added
  
  
  ## [0.2.0a3] — 2026-05-28

  ### Changed

  - **PyPI metadata corrected.** `description` and `keywords` in pyproject.toml were still carrying the old "identity workflow framework" positioning; rewritten to match the v0.2 tagline ("African PII detection that cites the law it enforces"). v0.2.0a2 is yanked from PyPI for the same reason, its summary actively misrepresented the project.   
  > African PII detection that cites the law it enforces. Government IDs, names, phones, addresses for NG/KE/ZA/GH — grounded in NDPA, POPIA, Kenya DPA, Ghana DPA. Composes with Presidio, GLiNER, and Splink.
  - **Classifiers refreshed.** Added Financial / Legal / IT audiences, Security + Text Processing topics, OS Independent, Typing :: Typed. Dropped Scientific/Engineering :: AI, it drew the wrong audience for a rule-based PII library.
  - Keywords scrubbed of `identity-resolution`, `entity-resolution`, `digital-public-infrastructure`, `workflow-framework`, `DPI`, `identity-workflows` (all v0.1 framings); replaced with PII / data-protection / per-jurisdiction terms.
  - **Authors field** now uses `{name = "Dennis Irorere", email = "connect@unpatterned.org"}` instead of bare `{name = "unpatterned.org"}`, so PyPI's contact link points somewhere real.


## [0.2.0a2] — 2026-05-28

> **Headline.** `arche-core` is now **African PII detection that cites the law it enforces**. v0.2.0a2 makes that real: every `Pipeline.process()` detection ships with a sensitivity tier and the specific statute section that classifies it, mapped to one of six closed actions under NDPA, POPIA, Kenya DPA, or Ghana DPA. Plus an MVP address parser (633 LOC), a web-fetch ingest helper, a places resolver, and the deletion of every DPI-adapter and FHIR stub that was promising but unimplemented. The wheel is a ~310KB base install, 980 tests passing, no mandatory ML deps.

### Added

- **`arche.addr.parse_addresses` and `Address` types**: 633-line address parser MVP covering Nigerian and South African landmark-anchored formats, with jurisdiction inference and a compiled-in gazetteer. Wired into  `Pipeline` via the `"addr"` package.
- **`arche.ingest.from_url`**: SSRF-guarded HTTP fetch helper for ingesting text from public URLs. Uses `httpx` with tight redirect / timeout controls.
- **`arche.resolve_places` and `arche.list_places`**: new public functions for jurisdictional place lookup with verifiable JWS audit receipts. 
- **`Detection.sensitivity_tier` and `Detection.regulatory_citation`**: every detection emitted by `Pipeline.process()` now carries both. Tier is one of `high` / `moderate` / `low`. Citation is the actual statute section (e.g. `"NDPA-2023 s.30, NIMC Act s.27"`).
- **`SensitivityTier` enum** at `arche.types`.
- **`arche.detect.ip`** — IPv4 / IPv6 / private-range / Tor exit detection.
- **`arche.detect.digital_id`** — decentralized identifier (DID) and verifiable credential reference detection. Emits the new `PII-2-DID` category.
- **`PII-4-LOCATION`, `PII-2-DID`, `PII-5-CRYPTO_WALLET`** taxonomy categories, with statute mappings in NDPA-2023.
- **Shared `_lexicon_detect` helper** for name / location / address lexicon detectors — collapses three near-duplicate implementations into one.
- **Names, locations, addr, ip, digital_id** wired into `Pipeline`'s default detector chain. `Pipeline(jurisdiction="NG").process(text)` now runs all of them by default.


### Fixed

- Linter cleanup across the package (ruff + import organization).
- Stray `demo/demo/` directory artefact removed.
- Three dead-code blocks deleted (unused legacy helpers).

### Public API surface

Recommended for v0.2 (in `__all__`):

```python
from arche import (
    # PRD 10.1 framework primitive
    Pipeline, Result, Detection,
    # Level-2 workhorses
    detect, match, link, resolve,
    # v0.2.0a2 places surface
    resolve_places, list_places,
    # version
    __version__,
)
```

The v0.1 surface (~50 names: `extract`, `detect_pii`, `resolve_entities`,
`to_html`, etc.) remains importable via PEP 562 lazy attribute access on
`arche`, with `DeprecationWarning` on first use. Removed in v0.3.

### Stats

- 980 tests passing, 3 skipped, 0 failed (`uv run pytest packages/arche-core/tests`)
- Base wheel: 310 KB (`arche_core-0.2.0a2-py3-none-any.whl`)
- Source tarball: 325 KB
- Python: 3.11, 3.12, 3.13 supported
- CI matrix: Linux / macOS / Windows × Python 3.11 / 3.12 / 3.13

## [0.2.0a1] — prior

Initial v0.2 alpha. Highlights:

- `Pipeline`, `Result`, `Detection` — the v0.2 framework primitive (PRD §10.1).
- Statute-grounded policy engine (`arche.policy`) with NDPA, POPIA, Kenya DPA, and Ghana DPA mappings.
- Verifiability substrate (`arche.sign`, `arche.credentials`): Ed25519 + JWS envelope, did:key, SD-JWT-VC.
- v0.1 backward-compatibility shim: every v0.1 name remains importable through PEP 562 lazy attribute access on `arche`. Removed in v0.3.
