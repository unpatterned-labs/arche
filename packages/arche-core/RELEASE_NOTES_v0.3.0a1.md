# arche-core v0.3.0a1 — *Know what's real*

**Released:** 2026-08
**PyPI:** `pip install arche-core==0.3.0a1`
**Tests:** 1,466 passing · 3 skipped · **License:** Apache 2.0

> [!WARNING]
> **Status:** alpha, not beta. This is the first alpha of the 0.3 line and it
> opens the breaking-change window. Of the four published beta criteria, one is
> met, one is partially met, two are open. Do not use `arche-core` with real
> personal data until you have completed your own legal, privacy, and security
> review.

---

## What this is

**The open engine for messy, multilingual data.** Find the entities, resolve
who they actually are, protect them under the law that applies, and sign every
decision.

Two catalogue rows read *Damini Ogulu* and *Burna Boy*. Three clinic registers
read *Fatima Abdullahi*, *Fatuma Abdullahi*, *F. Abdulahi*. And two sanctioned
men share the name Khalid Mehmood, the same country and the same programme,
with different fathers and different national IDs.

Two of those are one entity wearing different names. One is two entities
wearing the same name. Software that gets the first two right by loosening its
matching gets the third one catastrophically wrong. Holding all three at once
is the job.

```python
from arche import resolve

decision = resolve.pairwise("Fatima Abdullahi, NIN 12345678901",
                            "Fatuma Abdullahi, NIN 12345678901")

decision.identity      # 'review'   — high score, but not distinctive enough to merge
decision.score         # 0.9999
decision.decision_id   # 'dec:sha256:a5fde8c138c6157f00c0396ce63f6…'
```

That `review` on a 0.9999 score is not a bug. Sharing an ID is strong evidence;
the gate wants *distinctive* evidence before it will call two references the
same entity, and it abstains rather than guessing. **Abstention is the
product.**

---

## What's new since v0.2.0a3

### Resolution is now a first-class surface

The previous release described `resolve` as a power-user workflow. It is now
half the product.

- **`resolve.pairwise()`** scores one pair and returns a `CoReferenceDecision`
  — `identity` is `same_entity` / `review` / `different`.
- **`resolve.crosswalk()`** runs a whole table and returns `matches`, `count`,
  `blocking`, and `pins`.
- **`resolve.reconcile()`** and **`resolve.sign_edges()`** close the loop.

### Union blocking closes a measured recall cliff

Candidate generation used to block on geography alone. On true pairs whose
coordinates disagreed, recall fell off a cliff — and in real African facility
data a large share of true matches sit well beyond two kilometres, because one
team measured at the gate and the other at the junction.

`union_candidate_pairs` now ORs spatial cells, rare shared tokens, and shared
identifiers. `blocking_recall()` measures the result. A dropped pair is
unrecoverable, so this was a ceiling on every number downstream of it.

> **Caveat, stated up front.** The recovery is driven substantially by *rare
> token* blocking, not geography. It will degrade on registries full of
> "General Hospital" and "Primary Health Centre". The published figures are
> from an internal evaluation set; a runnable benchmark is
> [criterion 2](#beta-criteria) and is not yet shipped. Treat the numbers as
> ours until you can run them yourself.

### Declare your own schema

One YAML declares *your* fields and annotates each with an arche role. From
that single file arche generates the comparators, the masking, the JSON Schema
your LLM extracts into, the validation, and a content-hash pin that enters
every decision id. Your fields come out unchanged, plus provenance. No schema
registry, ever.

```bash
arche schema validate fisheries.decl.yaml
# valid: fisheries-landings@1.2.0:sha256:28f13195e89a25e3
```

### Bring any LLM — the engine grades it

Models propose; the engine decides. The integration surface is one callable:

```python
from arche.llm.declarative import extract_declared

ex = extract_declared(text, decl, complete_fn=my_model, model="my-model@2026-08")
ex.violations   # ["undeclared field 'captain_ssn'"] — excluded, never coerced
```

A hallucinated field becomes a **violation**, not a value. Unparseable output
fails loud. And `grade_pairs()` measures the model's judgment against the
deterministic engine, counting `review` as an honest abstention rather than a
miss:

```text
agreement_rate  : 0.6666666666666666
divergences     : 1
Divergence(engine='different', judge='same', score=0.0843,
           evidence={'name': 1.0, 'national_id': 0.0, 'name_tf': 1.0})
```

That divergence is the two men named Khalid Mehmood. A name-only judge said
`same`; the engine said `different` and showed *why* — a perfect name match
next to a direct ID contradiction. `openai`, `anthropic`, `ollama` and
`litellm` are supported via `LLMConfig`, or bring your own client as a plain
function.

### Spatial role labeling, with the referee in the box

arche now labels which address in "pick up from X and send it to Y" is the
origin and which is the destination, and returns the linguistic cue that
decided it. When cues conflict, or a sentence says *don't* deliver there, it
answers `unknown` rather than guessing — an agent that flips pickup and
drop-off has a much worse day than one that asks.

A **54-sentence labelled gold set ships inside the wheel** with a
refusal-aware scorer, so you can grade *your* extractor, including your LLM, on
the same set, with over-guessing priced as its own number:

```python
from arche.addr import load_gold, grade_places
grade_places(load_gold(), your_output)
```

### Attestation

`attest()` signs a decision together with the exact representation that
produced it — engine version, thresholds, blocking strategy, table provenance,
your declaration pin. Anyone can then verify the only honest claim available
about entities that have histories: *given this evidence and this
representation, this was the decision.*

### The artist pack — proof that a new entity type is data, not code

38 equivalence groups across 112 name forms: Wizkid, Burna Boy, Rema, Tems,
Davido, Asake, Ayra Starr, Amaarae, Tyla, Fela Kuti, Sarkodie, Diamond
Platnumz, Angelique Kidjo and more.

Two lessons are baked into that pack. The **Tyla** group is hand-corrected,
because a name-only catalogue search returns a UK artist of the same name
rather than the South African star — *names describe, identifiers distinguish*.
And with a frequency table self-calibrated on a small catalogue, *DJ Spinall*
and *DJ Snake* look like a match, because a toy corpus thinks "DJ" is rare;
with a population-scale table they correctly do not. Representation, shipped as
data you can read and correct, is the whole thesis.

---

## Security

### `verify()` no longer trusts the key a token names for itself

**This is a breaking change, deliberately.**

`allow_did_key_from_kid` defaulted to `True`, so `verify(token)` with no key
decoded the public key from the token's own `kid`. Since the signer chooses
`kid`, anyone could sign a payload with their own keypair, self-assert the
matching `kid`, and get `valid=True` — with nothing in the result to say that
nothing had been authenticated. The module docstring taught exactly that call.

```python
verify(forged)                                # now False — no trusted key
verify(forged, public_key=issuer.public_key)  # False — correct rejection

lenient = verify(forged, allow_did_key_from_kid=True)
lenient.valid       # True   — the signature does match the key
lenient.trusted     # False  — but the signer chose that key
lenient.key_source  # 'self-asserted'
```

`VerificationResult` gains `key_source` and `trusted`. **`valid` answers "does
this signature match this key"; only `trusted` answers "and did that key come
from somewhere I control".** The same two fields are on `VerifyExtractResult`,
`AttestationVerifyResult`, and `SDJWTVerifyResult`.

Offline envelope verification still works exactly as documented — a recipient
with no pinned key can still check an envelope with no resolver and no network
call. What changed is that the result now reports `signature_trusted=False` in
that case, instead of being indistinguishable from a verified issuer.

**If you have code written against the old default, it was not verifying
issuers, and it needs a key.**

See [SECURITY.md](../../SECURITY.md), new in this release, for the reporting
process and the full contract.

---

## Also fixed

- **Attestations no longer claim reproducibility they do not have.**
  `reproducible` was computed from the *signing mode*, so every JWS attestation
  claimed `True` — including ones built from LLM extractions whose own pin
  recorded `reproducible: false`, putting both claims in the same signed
  artifact. Now derived from the decision's pins.
- **`statute_at_signing` no longer double-prefixes the version.** Statute packs
  store `version: v1.0` and the envelope builder prepended another `v`, so
  every signed envelope carried `NDPA-2023@vv1.0`. The round-trip test had
  pinned the malformed string, which is why it survived.
- **The package version is single-sourced.** `pyproject.toml` declared
  `0.2.0a3` while `arche.__version__` reported `0.3.0a1`; the wheel would have
  gone out under the previous release's number.
- **`dir(arche.llm)` shows the LLM API**, and `HarnessReport` / `Divergence`
  are importable from the package that returns them.
- **PyPI metadata** — the `Documentation` URL pointed at a host that does not
  resolve.

---

## Breaking changes

| Change | What to do |
|---|---|
| `verify()` requires a trusted key | Pass `public_key=` or `resolver=`; or `allow_did_key_from_kid=True` for integrity-only checks |
| The v0.1 callable shim `arche.resolve(text)` is removed | Use `Pipeline.process()` |
| `statute_at_signing` format corrected | Envelopes signed by 0.2.x carry `@vv1.0`; new ones carry `@v1.0` |
| `reproducible` is derived, not assumed | No action unless you asserted it was always `True` for JWS |

The `arche.detect(text)` callable is **kept deliberately** — it is the
documented Level-2 workhorse, not a compat shim. Remaining v0.1 lazy names stay
importable through the 0.3 line; removal is targeted for v0.4.

---

## Install

```bash
pip install arche-core
```

Or with `uv`:

```bash
uv add arche-core
```

| Extra | Adds |
|---|---|
| `arche-core[doc]` | docling for PDF / DOCX / PPTX / XLSX / HTML ingest |
| `arche-core[doc-ocr]` | RapidOCR for scanned documents |
| `arche-core[detect]` | GLiNER2-PII via ONNX runtime |
| `arche-core[presidio]` | Microsoft Presidio recognizer plugin |
| `arche-core[resolve]` | Splink + DuckDB |
| `arche-core[geo]` | shapely + duckdb for polygon joins |
| `arche-core[llm]` | openai + anthropic SDKs |
| `arche-core[litellm]` | litellm, for 100+ backends |

The base install pulls no ML dependencies and works offline. Note that
`[detect]` downloads a model from HuggingFace on first use.

Six statute packs ship in the wheel — NDPA-2023, POPIA, Kenya DPA, Ghana DPA,
GDPR, HIPAA Safe Harbor — along with the artist pack, both frequency tables,
and the places gold set.

---

## Beta criteria

We mark arche **beta** when these are true. Revisions are made in the open
rather than by quietly re-checking a box.

| # | Criterion | Status |
|---|---|---|
| 1 | Every shipped statute pack carries a complete category mapping with cited sections and a declared `review_status` | ✅ **Met** |
| 2 | The **Africa Address Benchmark v0.1** is published with ground-truth parses and cross-tool baselines | ⬜ Open |
| 3 | The v0.1 backward-compat surface is removed | ⚠️ **Partially met** |
| 4 | At least one **production deployment** running cleanly for ≥90 days, documented as an open case study | ⬜ Open |

**Criterion 1 was revised this release** — from "POPIA, Kenya DPA and Ghana DPA
reach v1.0 after structured DPA consultation" to the wording above. Two things
forced it: the product ships six packs now rather than four, and our own labels
were incoherent — GDPR and HIPAA shipped as `v1.0` with no external review
while three complete African packs sat at `v0.1-scaffold`. Completeness and
review are now separate declared axes. `version` is a claim about our work;
`review_status` is a claim about the world. **All six packs declare
`self-reviewed`; none claims regulator review, and the loader rejects any pack
that claims it without naming a reviewer.**

**Criterion 3 is honestly partial.** The callable shims are gone; deleting the
whole lazy v0.1 surface in the same release would break alpha users twice in
one step.

We would rather be held to a concrete criterion than praised for a vague one.

---

## What's not in this release

- **No MCP server.** `arche-mcp` is not published and no server code lives in
  this repository. Documentation that described MCP tools in the present tense
  has been corrected. It is the next release's focus.
- **No registry adapters.** Resolving against authoritative registries is a
  proven *pattern* (artist → MBID → keyed `entity_id` → attest), not a shipped
  integration.
- **No published benchmark.** Criterion 2. Until it ships, our comparative
  numbers are ours.
- **No regulator-reviewed statute pack.** All six are `self-reviewed`. We track
  this per pack and pursue it continuously.
- **`Pipeline(address_parsing=True)` is a no-op** — call
  `arche.addr.parse_addresses()` directly meanwhile.
- **`Pipeline` does not detect email addresses.** `arche.detect.detect_emails`
  works standalone but is not in the default chain, so emails survive
  redaction. Pass an explicit `detectors` list if you need them.

---

## Contributing

New in this release: [`CONTRIBUTING.md`](../../CONTRIBUTING.md) with real build
and test instructions, [`CODE_OF_CONDUCT.md`](../../CODE_OF_CONDUCT.md),
[`SECURITY.md`](../../SECURITY.md), and issue templates — including one for
**data corrections**, which need no code at all.

If you know a naming convention, an orthography, an ID format, or a statute
from the inside, that knowledge is the product. Corrections to existing data
are as valuable as additions.

---

## Credits

`arche-core` is built by [Unpatterned Labs](https://unpatterned.org) with
contributions from the broader African open-source community. The
[Pan-African PII Taxonomy](../../datasets/pan-african-pii-taxonomy/) is
CC-BY-4.0 and welcomes external review.

Calibrated on the world's hardest identity data, and built for how the world
actually writes names and addresses everywhere.

---

## Links

- **Repository:** https://github.com/unpatterned-labs/arche
- **Documentation:** https://unpatterned-labs.github.io/arche/
- **PyPI:** https://pypi.org/project/arche-core/
- **Issues:** https://github.com/unpatterned-labs/arche/issues
- **Changelog:** [CHANGELOG.md](./CHANGELOG.md)
- **Roadmap:** https://unpatterned-labs.github.io/arche/concepts/roadmap/

---

— Dennis Irorere, on behalf of Unpatterned Labs
