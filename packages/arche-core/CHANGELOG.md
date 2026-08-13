# Changelog

All notable changes to `arche-core` are documented here. Format loosely follows [Keep a Changelog](https://keepachangelog.com/) and the project uses [PEP 440](https://peps.python.org/pep-0440/) version identifiers.

## [Unreleased]

### Added — an experimental electronics product lane

`ENTITY_PACKS["product_electronics"]`, plus the primitives it is built from.
One call, no setup:

```python
from arche.resolve import crosswalk
crosswalk(abt, buy, entity="product_electronics", id_field="id")
```

Measured on [Leipzig Abt-Buy](https://dbs.uni-leipzig.de/research/projects/benchmark-datasets-for-entity-resolution)
(1,081 x 1,092, 1,097 true pairs, complete ground truth so false merges are
visible):

| | baseline, name only | `product_electronics` |
|---|---|---|
| precision | 0.7954 | **0.9707** |
| recall | 0.2197 | **0.6636** |
| F1 | 0.3443 | **0.7883** |
| false merges | 62 | **22** |

**The signal is rarity, and two mechanisms produce it.** With the rules that
actually ship, code-blocking alone reaches 0.8865 precision over 881 pairs and
the rarity filter lifts it to 0.9973 over 754. (Both over the full
cross-product; inside the union blocker's own candidate set the same two rows
are 856/0.8843 and 731/0.9973. They are different populations and are never
mixed into one series.)

**The frequency table does that work, not the stop list.** Two earlier drafts of
this entry got the attribution wrong in opposite directions, so here is the
end-to-end measurement instead of an argument — Abt-Buy, shipped pack, with
`stop_codes` on and with it emptied:

```text
stop_codes ON  (shipped)   TP 728  FP 22  P 0.9707  R 0.6636
stop_codes DISABLED        TP 728  FP 22  P 0.9707  R 0.6636
```

Byte-identical. On this benchmark the stop list contributes **nothing**, because
the table already scores `1080p` far below the gate: `16gb` at df 11 is **0.182**
against 1.0 for a code as rare as a unique one, and only the latter clears
`DISTINCTIVE_FLOOR` unaided.

What the stop list earns is the small-catalogue case the benchmark cannot show —
four records whose only shared code is a resolution give two false merges with
it off and none with it on. It is a floor for corpora too small to estimate
frequency from, not a substitute for estimating it.

**A calibration bug worth recording, because it made the lane worse than no
lane.** `TokenFrequencyTable.distinctiveness` is `min(1, -log10(rel_freq)/5)`,
calibrated for the million-token word corpora behind the place and person
tables. A code vocabulary is ~2,000 documents, so the rarest possible shared
code — one occurrence in each source — scored **0.6205**, below
`DISTINCTIVE_FLOOR` (0.75). The gate therefore demoted *every* true product
match and recall fell from 0.2197 to **0.0948**. The formula was not wrong; it
was being asked a question about a different distribution. `code_rarity` scores document frequency relative to what a
unique code looks like *in that corpus* (`min(1, baseline/df)`, where `baseline`
is twice the lower-quartile df). An earlier version anchored on the constant 2,
which made recall collapse from 0.6636 to 0.0419 on a catalogue where each
product is merely listed twice — the score has to be corpus-relative, not
absolute.

New public surface:

- `resolve._productcode.extract_product_code_candidates(text, category)` —
  *candidates*, deliberately not "model numbers". A regex cannot tell a
  manufacturer code from a retailer SKU from a spec; rarity does that later.
  Normalisation is most of the lane: raw-string matching finds a shared code on
  44.9% of true pairs, normalised on **71.2%**, because one source writes
  `SB97CS` and the other `SB-97Cs`.
- `kind: "code"` — rarity-weighted code agreement. `None` when either side has
  no candidate; **0.0**, not a veto, when both have codes and share none —
  18.6% of true pairs are in that position (accessories, bundles, retailer
  SKUs), so a conflict rule would refute them all.
- `kind: "spec"` — agreement on identity-bearing units, for use with
  `refutes_below`.
- `ProductCategory` / `register_category` — **the modularity seam.** Adding
  food, books or apparel is a category registration plus a benchmark, not a
  change to any comparator.

**Identity contract: a purchasable variant (SKU).** A 16GB and a 32GB player are
different products however alike their titles, which is why `spec` refutes
rather than merely scoring. That contract is data on the category
(`identity_units`), not a constant in a comparator, so a lane with different
semantics declares different units.

**Scope, stated rather than buried.** There is no generic `product` pack and
shipping one would overclaim. The evidence is a single electronics corpus, and
on Amazon-GoogleProducts — general merchandise — the lane barely helps and
**costs precision**:

| Amazon-Google | baseline | lane |
|---|---|---|
| precision | 0.4898 | 0.4863 |
| recall | 0.3338 | 0.3408 |
| F1 | 0.3971 | 0.4007 |
| false merges | 452 | 468 |

That is +9 true matches for +16 false ones — a marginal precision of **0.36** on
the pairs it changes. The F1 gain is real and it is not worth having. Reporting
only the F1 would have hidden it.

The rules that work here fail elsewhere by construction — Levi's `501` is
rejected twice by thresholds that exist to filter prices and years, `32x32`
looks like a model and is not, and reading `600mg` as a drug's model code would
be dangerous. The category is flagged `experimental=True` and a test asserts no
generic `product` pack exists.

Two further honest limits: the `spec` refutation rests on 47 of 1,097 true pairs
— all 47 agree, but that is a thin base — and the code frequency table is
self-calibrated over the two catalogues being matched rather than shipped, which
is u-probability estimation over the data at hand rather than a shipped asset.

### Added — place-name qualifier splitting

Sources disambiguate places by appending the containing region, and they do not
agree on how. On the [Leipzig Geographic Settlements
benchmark](https://dbs.uni-leipzig.de/research/projects/benchmark-datasets-for-entity-resolution)
— 3,054 records, 4 sources, complete ground truth — the same settlements are
written four ways:

```text
NYTimes   Petra (Jordan)      99.7% qualified
DBpedia   Cordoba, Spain      36.8% qualified
Freebase  savannah             0.0% qualified
GeoNames  Split                0.0% qualified
```

A name comparator reads the appended region as part of the identifying string.
The real pair NYTimes `Marseille (France)` against DBpedia `Marseille` scored
**0.661** against a 0.70 threshold — `placename` 0.900 and `tftoken` 0.533, both
diluted by a country name that is not part of the identity.

**The distinctiveness gate was clearing at 0.900 throughout.** This was a
representation failure, not a threshold one, and it is worth stating because the
tempting fix is to lower `DISTINCTIVE_FLOOR`. That constant is shared with the
person lane, where 0.70 lets two different people both named `Ibrahim Musa`
auto-merge — `test_coreference.test_s3_common_name_only_is_review` pins it.

Three additions, all opt-in:

- **`arche.split_place_name(name) -> (core, qualifier)`** — public.
  `('Petra', 'Jordan')`, `('Cordoba', 'Spain')`, `('Split', '')`. A qualifier is
  only reported when a non-empty core remains, so `(Jordan)` stays whole.
- **`kind: "qualifier"`** — a comparator on the appended region. Returns `None`
  when either side is unqualified, because three of the four sources leave most
  names unqualified and absence is missing evidence, not disagreement.
- **`strip_qualifier: true`** — a spec flag on any text comparator, making it
  judge the core name. Declare both on the same field, no record preprocessing:

```python
{"field": "name", "kind": "placename", "weight": 2.0, "strip_qualifier": True},
{"field": "name", "kind": "tftoken",   "weight": 2.0, "strip_qualifier": True},
{"field": "name", "kind": "qualifier", "weight": 1.0},
```

Measured on the benchmark, pooled across all six source pairs:

| | shipped pack | with the split |
|---|---|---|
| precision (pooled micro) | 0.9862 | 0.9733 |
| recall at auto-match | 0.7135 | 0.9205 |
| surfaced recall | 0.9654 | 0.9806 |
| **review queue** | 1,732 edges | **676 edges** |

Read the last two rows before the third. Auto-match recall moves 20 points, but
surfaced recall moves 1.5 — roughly 837 of the newly auto-matched pairs were
**already in the review queue**. This is an automation result, 61% less human
adjudication for the same evidence, not a discovery result. Precision pays 1.3
points for it, and the worst source pair pays 2.4.

**It ships off by default, and a test enforces that.** Enabling it changes Kano
not at all — facility names carry no qualifiers — and on London recovers nothing
while adding two more unlabelled auto-matches. The qualifier convention is a
property of the *source*, not of places, so it is a capability rather than a
default. Turning it on for a shipped pack moves that pack's published numbers.

**On the `spec` refutation.** It is exactly neutral on Abt-Buy — identical
precision, recall and counts with and without it. It earns its place from the
**identity contract** rather than from this corpus: under a purchasable-variant
reading a 16GB and a 32GB player are different products, and the refutation is
what makes that contract executable rather than decorative. Only 47 of 1,097
true pairs carry a comparable unit, so this corpus cannot test whether it helps,
and a test pins the neutrality so a future change that makes it *harmful* is
caught. An earlier measurement showed it costing one true match; that was the
`_SPEC` boundary bug refuting `F5C400300W` against `F5C400-300W`, now fixed.

Four robustness fixes from an adversarial review of this lane:

- **`compare_codes` fails loud without a table**, matching `tftoken`. It used to
  return 1.0, making `16gb` indistinguishable from `2595b002` — a silently worse
  answer rather than an error.
- **`code_rarity` reads `_as_counts()`**, not `_counts`. A table built from
  relative frequencies alone carries `_counts = None`, and reading it directly
  made *every* code score maximally rare with no error.
- **The code table is named in `pins`** as `codes@sha256:…`. It decides whether
  a shared code is identifying, so two runs with different tables can reach
  different verdicts on the same pair; an unpinned scoring input makes
  `decision_id` claim a reproducibility it does not have.
- **One table per declared category**, not one for the first `code` comparator
  found, and `register_category` refuses to shadow an existing name without
  `replace=True`.

`build_code_table` now warns when the typical code appears more than twice —
an applicability bound said out loud, since the lane was measured on catalogues
where a code appears once per source.

The qualifier is a **scored** signal rather than a `refutes_below` discriminator
on purpose: qualifiers are written at different granularities and in different
forms (`NY` against `New York`), and as a refutation it removed 13 false merges
while costing 17 true ones.

### Added — `refutes_below`, a declarable discriminator veto

Any comparator spec may now declare `"refutes_below": x`. When that comparator
applies and scores under `x`, the pair is demoted to `review` no matter how well
everything else agrees:

```python
{"field": "year", "kind": "date", "weight": 0.5, "refutes_below": 0.99}
```

**Why a weight could not already do this.** A weight is symmetric — it rewards
agreement by exactly as much as it punishes disagreement. Some attributes are
not symmetric: they disagree meaningfully and agree cheaply. A publication year
is the clean case, and DBLP–ACM makes it measurable because the Leipzig mapping
is *complete*, so false merges are visible for the first time in this project.
Year agrees on **2,224 of 2,224** true pairs and separates 213 of 391 false
merges. Raising its weight makes precision **worse**:

| `year` weight (against 7.0 on title + authors) | Precision | Recall |
|---|---|---|
| 0.5 | 0.8500 | 0.9960 |
| 2.0 | 0.8761 | 0.9987 |
| 7.0 | 0.6531 | 0.9996 |
| 25.0 | 0.6531 | 0.9996 |

Thousands of unrelated papers share a year, so turning the field up turns up the
noise it sits in. Declared as a refutation instead, on the same declaration:

```text
baseline (year scored)     P=0.8500  R=0.9960   (TP 2215, FP 391)
year refutes_below 0.99    P=0.9506  R=0.9960   (TP 2215, FP 115)
```

**276 false merges removed, zero true matches lost.** Reproduce with
`uv run python data/scripts/benchmark_leipzig.py`.

This generalises the geographic veto rather than inventing anything, and keeps
its rules:

- **Demotes to `review`, never `no_match`.** A refutation says a human must
  look, not that the answer is no. Note this is strictly better than what a
  heavy weight does — a heavy weight pushes the pair under the floor and the
  edge is *dropped*, so the reviewer never sees the conflict at all.
- **A missing value never refutes.** Absent evidence refutes nothing, exactly
  as absent coordinates cannot fire `veto_km`.
- **Refutation and scoring stay orthogonal.** `weight` is unchanged by the
  flag; pair with `"weight": 0.0` for a discriminator that refutes and never
  confirms.
- **The conflict is named in the evidence** as `<field>_conflict`, because a
  demotion a reviewer cannot explain is indistinguishable from a bug.
- **Out-of-range thresholds raise** rather than silently always- or
  never-firing, both of which read as a tuning choice rather than a typo.

Before this, arche had exactly two vetoes: `veto_km`, which requires
coordinates, and `id_conflict`, hardcoded to the field name `national_id`.
Neither was reachable from a declaration, so the gap blocked publications
(year), products (model, pack size), charge points (connector) and people (date
of birth) identically.

**No shipped pack declares `refutes_below` yet**, and a test enforces that.
Turning it on for `place`, `person` or `artist` changes those packs' published
numbers, so it is a separate and separately-measured decision rather than a side
effect of adding the mechanism.

### Added — phrase distinctiveness, shipped in the wheel

The gate asks whether two names share something *rare*, and it asked that of
**tokens**. That is right where the identifying part of a name is one rare word:
``Karfi Health Post`` clears on ``karfi`` at 0.93. It is wrong where identity
lives in a phrase of ordinary words. Every token of ``London Bridge Hospital``
is common — ``london`` 0.69, ``bridge`` 0.61, ``hospital`` 0.35 — so two records
of that hospital 30 m apart with byte-identical names were routed to ``review``.

A bigram frequency table now ships alongside the unigram one and the corpus
separates the two cases with no curation at all:

```text
general hospital  0.486     london bridge  0.921
primary health    0.322     kings college  0.967
health post       0.349     king george    0.766
```

`TokenFrequencyTable.phrase_distinctiveness` returns the rarity of the rarest
**shared** phrase, and the gate combines it with the token measure using `max`,
so it can only recover a pair and never demote one.

Four guards, each closing a failure this codebase has already hit once:

- **Only phrases the corpus has actually seen may speak.** Membership is tested
  against the raw counts, not `rel_freq(g) > floor` — `rel_freq` clamps at the
  unknown floor, so a genuinely rare phrase and an unseen one return the same
  number. The first version used the clamped test and silently discarded
  `london bridge`, which is real and sits below the floor.
- **The phrase table must share its unigram table's tokenisation.** Loading
  raises otherwise: a phrase assembled under one rule cannot be looked up in
  counts accumulated under another.
- **A runtime-built table is silent.** Phrase evidence requires
  `population_scale`, so a small corpus cannot clear the gate on noise.
- **The phrase table is named in the pin**, which now reads
  `shipped:place@sha256:…+phrases@sha256:…`. It is a scoring input, so a rebuild
  changes decision ids rather than results silently.

Measured, shipped configuration:

| | before | after |
|---|---|---|
| London hospitals, 86 labelled pairs | 73 auto-matched | **82 (95.3%)** |
| routed to review | 12 | 3 |
| Kano GRID3 x OpenStreetMap | 564 match, 88.1% LGA | 566 match, **88.1% LGA** |

The three pairs still abstaining are the ones that should:

- `Memorial Hospital` against `Memorial Hospital, Woolwich` — that stem appears
  four times in each source, and `memorial hospital` as a phrase scores 0.554.
- `Nuffield Health Highgate Hospital` against `Highgate Private Hospital` —
  brand substitution, which belongs in an alias field rather than a comparator.
- `St Mary's Hospital` against a byte-identical `St Mary's Hospital`. This one
  is worth spelling out, because an identical string abstaining looks like a
  bug and is not. The rarest shared token is `marys` at 0.716 and the rarest
  shared phrase is `marys hospital` at 0.704, both under the 0.75 floor —
  `st` alone has 10,651 occurrences in the place corpus, and London has more
  than one St Mary's Hospital. The gate is refusing to let a shared location
  manufacture a merge on a name that does not identify anything, which is the
  same rule that stops two `General Hospital` records merging. It costs a true
  pair, and the pair goes to review rather than being lost.

The base wheel grows from 2.46 MB to 2.93 MB.

**A known risk, stated rather than buried.** Phrase rarity makes *containment*
errors easier to trip, because a shared phrase is distinctive even when the two
records are at different granularities. Among the auto-matches are
`King's College Hospital Emergency Department` against `King's College Hospital`
and `Charing Cross Hospital` against `Charing Cross Hospital Medical School` —
a department and a medical school, neither of which is the hospital.

We are **not** suppressing them, and the reason is that this corpus cannot
adjudicate the class: `Caterham Dene Hospital & Minor Injuries Unit` and
`Moorfields Eye Hospital (City Road campus)` are labelled *true* while the two
above are unlabelled, so a token-subset rule learned here would fit label noise
and would also route three known-true pairs to review. Containment needs its own
relation labels and its own verdict; until then it is a documented limitation of
auto-match on this domain, not a solved problem.

### Fixed — the gate and the frequency table could silently disagree about what a token is

`resolve/_gate.py` kept its own `_TOKEN_RE`, duplicating the one in
`resolve/_tokenfreq.py`, under a docstring asserting the two "match". Nothing
enforced that. Editing one and not the other raised nothing and warned nothing:
the table counted one vocabulary while the gate looked up another, so a
tokenisation change could appear simply not to work while the suite stayed
green. We hit exactly that while developing the change below, twice.

There is now **one tokeniser**, and the rule is a property of the *table* rather
than of a call site. `TokenFrequencyTable` carries `token_rule`, serialises it,
reads legacy payloads as `plain`, and **refuses to `merge` across rules** —
counts accumulated under one tokenisation do not mean the same thing under
another. `_gate` and `weighted_token_sim` both take the rule from the table they
were handed.

`packages/arche-core/tests/test_token_rules.py` pins all of it, including that
`_gate` no longer defines a token regex at all.

### Added — `possessive` tokenisation rule, and the place table rebuilt under it

`Queen's` tokenised as `queen` + a bare `s`, so `Queens Hospital` and
`Queen's Hospital` shared nothing but `hospital` (distinctiveness 0.35) and were
routed to `review` despite a name similarity of 0.987.

The new rule emits the joined form **alongside** the originals —
`queen`, `s`, `queens` — never instead. Two alternatives were measured on a
London hospital benchmark (OpenStreetMap x Wikidata, 86 labelled pairs, with the
table rebuilt under each rule so no query hit counts accumulated differently):

| rule | auto-matched | vs baseline |
|---|---|---|
| `plain` (previous behaviour) | 72 / 86 | — |
| strip the possessive entirely | 71 / 86 | **1 worse**, 0 recovered |
| emit alongside (`possessive`) | 74 / 86 | 2 recovered, 0 lost |

Stripping recovers nothing because `Queens` and `Queen's` still reduce to
different tokens; it only deletes a token that was never the deciding one.
Folding — emitting `queens` *instead* — was rejected for demoting
`St Mary Hospital` against `St Mary's Hospital` from 0.683 to 0.504.

**Additivity is not free, and the first version of this change broke it.**
`weighted_token_sim` is a ratio, so an extra token on one side only inflates the
union and lowers the score: `St Mary Hospital` vs `St Mary's Hospital` fell
0.763 to 0.563. The comparator now scores under both the table's rule and
`plain` and takes the better, which makes the rule additive by construction
rather than by argument. The shipped `place` table is rebuilt under
`possessive`; its content version changes, so every `decision_id` computed
against it changes, which is correct and intended.

Measured effect, shipped configuration: **London 73 -> 75 of 86 auto-matched**;
**Kano GRID3 x OpenStreetMap unchanged** at 564 matches and 88.1% LGA agreement.

Two limits worth stating rather than burying. The London figure is an
auto-match rate over a *tag-bearing positive subset* — the labels come from
OpenStreetMap `wikidata=` tags, only 91 of 226 records carry one, and an absent
tag means *unlabelled*, not *non-match*. It is not a recall measurement and
there is no precision instrument for that corpus yet. And additivity is
guaranteed **within a table**: rebuilding shifts the denominator for every
token, so whether a migration demotes anything is a benchmark question, not an
invariant.

## [0.3.0a2] — 2026-08

A security fix and the documentation corrections it turned up. No new features.

### Fixed — `EgressGuard` emitted detected values in clear when spans overlapped

**This is a security defect in the component whose entire purpose is to stop
exactly that, and it affects `0.3.0a1`.** Anyone using `arche.guard.EgressGuard`
should upgrade.

`_project` replaced detected spans right-to-left and skipped any span that
overlapped one it had already consumed. It sorted by `(start, end)` descending,
which reaches the *innermost* span first, so the **container** was the span
that got skipped — and the part of it outside the inner span was never
replaced. The docstring claimed the opposite ("the outer, earlier-consumed span
wins"); the code did not do that.

This was not a corner case. The shipped Nigerian detector set produces nested
spans on any ordinary address, where `PII-4-ADDRESS` contains `PII-4-LOCATION`:

```text
in    Janet Okafor lives at 12 Awolowo Road, Ikoyi, Lagos.
0.3.0a1  Janet [NAME:…] lives at 12 Awolowo Road, Ikoyi, [LOCATION:…].
0.3.0a2  Janet [NAME:…] lives at [ADDRESS:…].
```

Two things made it hard to notice. The street address crossed the boundary in
clear, and `PII-4-ADDRESS` was **absent from `GuardedProjection.fields`
entirely**, so nothing downstream could tell that a detection had been dropped.
Severity also inverted: under NDPA-2023 `ADDRESS` generalises while `LOCATION`
is retained, so the span discarded was the more restricted one.

Overlapping detections are now grouped into disjoint regions and each region is
replaced exactly once — the same resolution `policy.engine` already applied to
redaction. Within a region the **action** comes from the most restrictive member
(the safety property) and the **label** from the widest (an address containing a
name is still an address). The token is derived from the whole region's text
rather than one detection's, because the region is what leaves.

`GuardedField` gains **`covers`**, a tuple of every category absorbed into the
region, so a collapsed region stays auditable. Existing fields are unchanged and
the dataclass remains backward compatible.

Six regression tests were added, including an end-to-end one that runs the real
pipeline and asserts no detection's text survives in the projection. The prior
tests covered only disjoint spans, which is why this passed for a full release.

### Fixed — `extract_places_llm(config=...)` never reached the provider

`llm/spatial.py` called `providers.complete(messages, config)`. The signature is
`complete(config, messages)`. Every call through the `config=` path handed the
provider a list where the configuration belonged and failed on the first
attribute access, so the documented "bring your own LLM" route for spatial role
extraction did not work at all.

`llm/declarative.py` and `llm/extraction.py` both call it correctly, so this was
one transposition rather than a pattern.

It survived a release because the entire spatial test suite passes
`complete_fn=`, which bypasses the provider module. Three tests now cover the
`config=` path — argument order, the model pin, and the mutually-exclusive
argument check — and the first of them fails against the old code.

### Added — Huduma Namba detection (`PII-2-HUDUMA`)

Closes the gap the README correction above exposed. A Huduma Namba was
previously matched by the NHIF pattern and reported as `PII-2-NHIF`:
mislabelled, not missed, so a caller filtering on NHIF silently received Huduma
numbers and a caller looking for Huduma found nothing.

Detection is **cue-anchored by design**. The NIIMS number has no check digit and
its 8-12 character range overlaps both NHIF (8-9 digits) and the National ID
(7-8 digits), so a bare number genuinely does not say which of the three it is.
Matching bare digits as HUDUMA would have inverted the bug rather than fixed it,
and started mislabelling NHIF numbers instead. The pattern fires only where the
text says "Huduma", which is the same evidence a person uses and the only
evidence present — hence 0.88 confidence against 0.40-0.45 for the bare-digit
patterns.

Added to both the jurisdiction detector (`detect.ke.ids`) and the pan-African
fallback (`detect._africa.ids`) so the two cannot diverge, ordered ahead of the
bare-digit patterns. `PII-2-HUDUMA` maps to `mask` at `high` tier in the Kenya
DPA pack, and `HUDUMA` joins the foundational identity classes — it is the NIIMS
identity, not a sector-specific functional id. The `PII-2-NATIONAL_ID` rationale
no longer claims to cover Huduma.

Ten tests, including the ones that pin what it must *not* do: no bare number is
claimed as a Huduma Namba, and the cue is word-bounded so "shuduma" does not
trigger it.

### Fixed — documentation that overstated what exists

Found while auditing our own claims for the above.

- **`roadmap.md` said the MCP server was "built but unpublished"** and described
  its security behaviour in detail — offsets not raw PII, no reveal option on
  any agent path, fails closed without a statute. **No MCP code has ever existed
  in this repository.** All three claims are corrected in place rather than
  quietly deleted, because asserting security properties of software that was
  never written is the more serious error of the two.
- **The PyPI front page claimed independence we explicitly disclaim.** The
  package README said the Kano crosswalk gives "88.2% agreement with
  **independently-recorded** administrative boundaries" and linked to a page
  whose first paragraph says "**It is not independent validation**" and reports
  88.1%. Corrected to state the weak label, the shared lineage, and that the
  figure is a consistency check.
- **"Six statute packs at v1.0"** — six packs ship; three are `v1.0` and three
  are `v0.1-scaffold`. The README now says which are which.
- **"~310KB base"** — the base wheel is **~2.5 MB** and has been for some time;
  the place frequency table added 1.2 MB of it. Also corrected in the roadmap,
  which said ~1.3 MB and "1,456 tests" against an actual 1,561.
- **Huduma Namba was listed as a detected government ID.** It is declared in
  `jurisdictions.kenya` with a validator but has **no pattern in the detector
  set**, so a Huduma number is matched by the NHIF pattern and reported as
  `PII-2-NHIF` — mislabelled rather than merely missed. Removed from the
  coverage table and named as a gap.
- **"~500 cities"** in the detection-layer notes — the gazetteer holds 102
  cities and 134 aliases (236 lookup keys).
- **`pyproject.toml` listed five workspace members that are not on disk**
  (`arche-mcp`, `arche-graph`, `arche-live`, `api`, `demo`).
- **`data/scripts/build_bridge_file.py` imported `arche_mcp`** and raised
  `ImportError` on every run. The handler it wanted was lifted into core as
  `resolve.reconcile` with the same signature.

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
