# Changelog

All notable changes to `arche-core` are documented here. Format loosely follows [Keep a Changelog](https://keepachangelog.com/) and the project uses [PEP 440](https://peps.python.org/pep-0440/) version identifiers.

## [0.3.0a1] — 2026-08

First alpha of the 0.3 (beta) line. The published beta criteria
(DPA-consulted statute packs at v1.0, the Africa Address Benchmark with
cross-tool baselines, a 90-day production deployment) remain the gate for
`v0.3.0` proper; this alpha opens the line and its breaking-change window.

### Changed — statute pack maturity, stated honestly

- **Every pack now declares its maturity in two independent fields.**
  `NDPA-2023`, `GDPR` and `HIPAA Safe Harbor` ship at `version: v1.0`.
  `POPIA`, `Kenya DPA` and `Ghana DPA` remain `version: v0.1-scaffold`:
  they carry complete category mappings, but the version bump is held until
  their cited sections have had a second reading. Previously the label meant
  two different things depending on the file — GDPR / HIPAA were already
  `v1.0` with no external review, while three packs with equally complete
  mappings sat at `v0.1-scaffold`. `review_status` (below) is what
  disentangles those two meanings; `version` alone never could.
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
  quietly re-checked. Of the four criteria: **one met, one partially met, two
  open** — the roadmap tracks each one.

### Changed — the roadmap is a living document again

- **`concepts/roadmap.md` rewritten for v0.3.0a1.** It had drifted a full
  positioning behind: it described a 980-test v0.2.0a3 whose lead was African
  PII detection, listed `resolve` / `sign` / places as "power-user workflows,
  not the lead pitch", and described the statute packs before `review_status`
  existed to say who vouches for them. It now
  covers what actually ships (resolve, declare, the LLM lane, spatial roles
  and the referee, detect + govern, attest). No MCP server ships in this
  release — `arche-mcp` is not published and no server code lives in this
  repository; documentation that describes MCP tools in the present tense is
  being corrected. The roadmap tracks the
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

- **Resolution became a first-class surface.** `resolve.pairwise()` scores a
  single pair and returns a `CoReferenceDecision` (`identity` is one of
  `same_entity` / `review` / `different`); `resolve.crosswalk()` runs a whole
  table and returns `matches`, `count`, `blocking` and `pins`;
  `resolve.reconcile()` and `resolve.sign_edges()` close the loop.
- **Union blocking.** Candidate generation ORs spatial cells, rare shared
  tokens, and shared identifiers (`union_candidate_pairs`) rather than
  blocking on geography alone. `blocking_recall()` measures the result.
- **Declare your own schema.** One YAML declares your fields and annotates
  each with an arche role; `Declaration` generates the comparators, the
  masking, the JSON Schema your LLM extracts into, and a content-hash pin
  that enters every decision id. Driven from the CLI with
  `arche schema validate` and `arche schema gen`.
- **The LLM lane.** `extract_declared()` reads messy text into a declared
  schema with hallucinated fields recorded as violations rather than values;
  `grade_pairs()` and `grade_extractions()` score a model's judgment with
  `review` counted as an honest abstention rather than an error.
- **Spatial role labeling.** `extract_places()` labels which address in a
  sentence is the origin and which is the destination and returns the
  linguistic cue that decided it. Conflicting cues, missing cues, and negated
  cues all yield `role="unknown"` at floor confidence rather than a guess.
  A 22-case labelled gold set ships inside the wheel
  (`load_gold()`) with a refusal-aware scorer (`grade_places()`), so the same
  set grades your own extractor, including your LLM.
- **Attestation.** `attest()` and `verify_attestation()` sign a decision
  together with the exact representation that produced it — engine version,
  thresholds, blocking strategy, table provenance, declaration pin.
- **The artist entity pack** — 38 equivalence groups across 112 name forms,
  demonstrating that a new entity type is data rather than new code.
- **`arche compare`** — the CLI front door, masked by default, with
  `--demo` requiring no data of your own.

### Fixed

- **`statute_at_signing` no longer double-prefixes the version.** Statute
  packs store `version: v1.0`, and the envelope builder prepended a second
  `v`, so every signed envelope carried `NDPA-2023@vv1.0`. Now
  `NDPA-2023@v1.0`. The round-trip test had pinned the malformed string,
  which is why it survived; the assertion has been corrected.
- **Attestations no longer claim reproducibility they do not have.**
  `reproducible` was computed as `mode == "jws"` — a fact about the signing
  format, not about the decision. So a decision built from an LLM extraction
  was signed as `reproducible: True` even though its own `extraction` pin
  recorded `reproducible: false`, putting both claims inside the same signed
  artifact. It is now derived from the decision's pins: any pin declaring
  itself non-reproducible makes the attestation say so. SD-JWT remains
  non-reproducible regardless, since salted disclosure digests are not
  byte-stable. Surfaced while verifying the bring-your-own-LLM path end to
  end.
- **`dir(arche.llm)` now shows the LLM API.** Everything except `LLMConfig`
  loads lazily through the module's `__getattr__`, and Python's default module
  `dir()` reads `__dict__` — so the module advertised `LLMConfig` alongside
  `Any`, `annotations`, `dataclass` and `field`, and none of the actual
  functions. Invisible to tab-completion and unhelpful at a REPL. `__dir__`
  now returns the curated public surface plus the submodules, deterministically
  regardless of what has been imported.
- **`HarnessReport` and `Divergence` are importable from `arche.llm`.**
  `grade_pairs()` returns a `HarnessReport` whose `divergences` are
  `Divergence` objects, but neither type could be imported from the package
  that returns them, so callers could not annotate against them.
  `DeclaredExtraction`, `build_messages` and `build_places_messages` were
  likewise reachable or useful but unlisted; `__all__` and the lazy-import map
  are now generated from one table so they cannot drift apart.
- **PyPI project metadata.** The `Documentation` URL pointed at
  `docs.unpatterned.org`, which does not resolve; it now points at the
  published site. `Changelog` and `Issues` links added.
- **The package version is single-sourced.** `pyproject.toml` declared
  `0.2.0a3` while `arche.__version__` reported `0.3.0a1`, so the built wheel
  would have gone out under the previous release's number. Version is now
  read from `src/arche/_version.py` and the two cannot drift again.

### Changed — geography can now refuse (breaking for the place pack)

- **The place pack gained a geographic veto, `veto_km: 10.0`.** Distance was a
  weighted signal at 1.0 against name+tftoken's combined 4.0, so it could be
  outvoted: two Kano facilities sharing a common Hausa name merged **143 km
  apart** with the geo comparator scoring 0.000. Distance is a physical
  constraint, not a preference, and it now demotes an otherwise-matching pair
  to `review`.

  Benchmarked on GRID3 × OpenStreetMap (Kano, 685 × 1,723), scored against LGA
  agreement — a label both sources carry independently and neither derives from
  the other:

  | veto | same-LGA | diff-LGA | precision | matches >10 km |
  |---|---|---|---|---|
  | none | 481 | 134 | 78.2% | 73 |
  | 50 km | 481 | 110 | 81.4% | 49 |
  | 25 km | 481 | 77 | 86.2% | 16 |
  | **10 km** | **479** | **64** | **88.2%** | **0** |

  Shipped defaults now resolve 545 matches at **88.2% LGA precision**, with
  nothing matched beyond 9 km and **170 pairs moved into review** carrying
  `geo_conflict_km` as evidence.

  It demotes to `review`, never `no_match` — the asymmetry is the point. Being
  too strict costs a human glance; being too loose costs a clinic its
  allocation. Records without usable coordinates are never vetoed, because
  absent evidence refutes nothing.

- **`arche.resolve._orthography` — orthographic keying for name tokens.**
  A settlement written `Mai Tsidau` in one registry and `Maitsidau` in another
  shared no token, so the distinctiveness gate never fired and the true match
  was dropped. `_data/orthography.yaml` ships a Hausa pack: adjacent-token
  boundary collapsing, nasal assimilation (`n → m` before `b`/`p`), and ten
  curated equivalence groups. On Kano it recovers 13 real pairs
  (`Yan Gwarzo`/`Yangwarzo`, `Kafin Maiko`/`Kafinmaiko`, `Sanbauna`/`Sambauna`)
  with **zero demotions**.

  Strictly additive by construction: `max(literal, keyed)`. An earlier wiring
  computed the Jaccard over keys *instead of* literal tokens and recovered 13
  pairs while demoting 79 — the benchmark caught it. Vowel alternations
  (`Ririwai`/`Riruwai`) are recorded in the pack as `known_gaps` rather than
  guessed at; resolving them needs a Hausa speaker, not a pattern.

  Off by default (`orthography=None`) on `weighted_token_sim` and
  `shared_name_distinctiveness`, because it changes scores.

### Changed — `Pipeline` now detects email addresses by default (breaking)

- **`emails` joins the default detector set.** It was opt-in, on the stated
  grounds that adding it "would change existing callers' detections, policy
  outcomes and redacted text". That was true, and it was the wrong trade.

  An email address is PII under **all six** shipped statute packs — each maps
  `PII-3-EMAIL` to `tokenize` or `mask` with a citation — and `Pipeline` is the
  redaction path. A redaction pipeline that returns email addresses in the
  clear, by default, is not a compatible behaviour worth preserving.

  ```text
  before  'Contact Fatima Abdullahi at fatima.abdullahi@example.ng about NIN 12345678901.'
  after   'Contact NAME_099000a2 NAME_e38a0fcd at EMAIL_b07216d6 about NIN [NIN].'
  ```

  Callers who need the previous output can narrow explicitly with
  `Pipeline(detectors=[...])`.

### Fixed — redaction leaked plaintext on overlapping detections

- **`apply_policy` spliced each detection independently**, in reverse start
  order. That is correct only for disjoint spans. Detectors nest routinely — a
  NAME inside an ADDRESS, a LOCATION inside an ADDRESS — and the second splice
  then applied original-text offsets to an already-resized string.

  On ordinary Nigerian address text, with the shipped detector set and no
  options, that produced:

  ```text
  'Plot 5 Ibrahim Taiwo Road, behind the Total filling station, Kano.'
      ->  '[ADDRESS]o Road, [ADDRESS].'        # 'o Road' leaked
  '12 Adeola Odeku Street, Victoria Island, Lagos.'
      ->  '[ADDRESS], Lagos.'                  # 'Lagos' survived inside a masked span
  ```

  `detections` and `policy_outcomes` were correct throughout; only the
  rewritten string was wrong, which is the worst shape for this class of bug —
  the output looks redacted.

  Overlapping spans are now grouped and each group replaced once. The **action**
  comes from the most restrictive member (`drop > mask > tokenize > generalize
  > audit > retain`), because letting the outer span win would emit a
  generalized address still containing a NIN the pack said to mask, and letting
  the inner win would leave the rest of the address in clear. The **label**
  comes from the widest member, because an address containing a name is still
  an address.

  Every detection still gets its own outcome, in input order, with its own
  category, action and citation. Disjoint spans — the common case — are
  unaffected.

### Security

- **`sign.verify()` no longer trusts the key a token names for itself.**
  `allow_did_key_from_kid` defaulted to `True`, so `verify(token)` with no
  key fell back to decoding the public key from the token's own `kid`. Since
  the signer chooses `kid`, anyone could sign a payload with their own
  keypair, self-assert the matching `kid`, and get `valid=True` — with no
  way to tell from the result that nothing had been authenticated. The
  module docstring taught exactly that call.

  **This is a breaking change, deliberately.** `verify(token)` with no
  `public_key` and no `resolver` now returns `valid=False` and an error
  naming both options. Callers who want the keyless offline path opt in with
  `allow_did_key_from_kid=True`.

  `VerificationResult` gains two fields so the question is answerable at all:
  `key_source` (`"pinned"` / `"resolver"` / `"self-asserted"`) and `trusted`,
  which is True only for the first two. **`valid` answers "does this
  signature match this key"; only `trusted` answers "and did that key come
  from somewhere I control".** `VerifyExtractResult`, `AttestationVerifyResult`
  and `SDJWTVerifyResult` carry the same two fields.

  `VerifyExtractWorkflow`, `verify_attestation()` and `verify_sd_jwt()` opt in
  explicitly, so **offline envelope verification still works exactly as
  documented** — a recipient with no pinned key can still check an envelope
  with no resolver and no network call. What changed is that the result now
  reports `signature_trusted=False` in that case, instead of being
  indistinguishable from a verified issuer.

  Five regression tests now pin this contract. The suite previously had none:
  every signing test called the bare form, so the behaviour was asserted as
  correct rather than caught.

### Known issues

- **`Pipeline(address_parsing=True)` is currently a no-op** — `result.addresses`
  stays empty. Call `arche.addr.parse_addresses()` directly meanwhile.
- **`Pipeline` does not detect email addresses.** `arche.detect.detect_emails`
  works standalone but is not in the default detector chain, so emails survive
  redaction. Pass an explicit `detectors` list if you need them.

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
