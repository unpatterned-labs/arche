# Changelog

All notable changes to `arche-core` are documented here. Format loosely follows [Keep a Changelog](https://keepachangelog.com/) and the project uses [PEP 440](https://peps.python.org/pep-0440/) version identifiers.

## [0.5.0a1] — 2026-08-21

**A Splink backend, a date comparator in the `person` pack, honest pins, and a way to export a match result for review.**

Prepared as `0.4.0a5` and released as `0.5.0a1`. `0.4.0a5` was never published, so nothing points at it. The minor version moved because `crosswalk` gained a replaceable scorer, which changes what the library is rather than only what it scores: arche now has a matcher it does not own, and says so.

### Added — `crosswalk(backend="splink")`, an adapter and not a better matcher

Splink beats arche's own matcher, so `crosswalk` can now hand the scoring to it and keep everything arche puts around a score: evidence, refusal, pins, decision ids, and the review pack. The result shape is unchanged, so `review_pack`, `crosswalk_report` and arche studio work against a Splink run without knowing.

```python
crosswalk(register, survey, backend="splink",
          splink_settings=my_settings,   # a SettingsCreator you wrote
          threshold=0.99)
```

**Both arguments are required, and that is the whole design.** An earlier version inferred a Splink configuration from an arche comparator pack. It was measured on three datasets and was wrong in a different way on each: no `datetime_format`, so the date comparison trained nothing; blocking rules added without costing them, so `occupation` alone put 639M pairs in one block and the run was killed by the operating system; coordinates coerced to strings, so DuckDB refused `radians(VARCHAR)`.

Fixing all three left the deeper problem. A derived configuration **orders pairs about as well as a hand-written one and cannot calibrate them**. Calibration comes from `probability_two_random_records_match`, a prior about how many true matches the corpus holds, and nothing in a list of records states it. On Febrl 4 one derived run measures recall 0.8952 at `p >= 0.5` and 0.5448 at `p >= 0.99`, either side of arche's own engine at 0.8382, with the same edges in the same order. Without labels you cannot know which threshold you are on.

So arche does not invent a configuration. `splink_settings="derive"` still reaches the old path, warns, and says why.

`threshold=` is required for the same reason: a Splink probability has no portable scale. At `p >= 0.99` the hand-written Nigerian recipe merges nothing at all, while Febrl 4 merges 4,765 true pairs. Splink's own `predict()` has no default either.

**What the adapter is worth, stated as a fidelity result rather than a win:**

| Febrl 4, no `soc_sec_id` | true | false | precision | recall |
| --- | ---: | ---: | ---: | ---: |
| arche's own engine | 4,191 | 42 | 0.9901 | 0.8382 |
| adapter, `p >= 0.99` | 4,765 | 0 | 1.0000 | 0.9530 |
| the same recipe run directly | 4,767 / 4,764 | 0 | 1.0000 | 0.9534 / 0.9528 |

On the Nigerian school register the adapter and the hand recipe both reach 190 true of 200 at 0 false of 400, against arche's 146 and 2. The adapter costs nothing and gains nothing against the recipe it wraps. That is the claim: it is the same scorer, with a decision layer attached.

**Pins.** A trained scorer is a function of the data it saw and the settings it was given, so both are named: `model_sha256`, `corpus_sha256`, `blocking_sha256`, `lambda` (the prior that sets the probability scale), `settings` (`caller` or `derived`), `training` (`caller` or `default`), and the Splink and DuckDB versions. No `tf` pin, because Splink applies term frequency inside its own comparisons and naming one would claim an input the decision never used.

**The gate is off by default here.** It consumes per-comparator evidence and Splink emits one probability, so turning it on recomputes arche's name evidence to overrule a model that already priced name evidence. That is two correlated rules and it has not been measured. `gate=True` is available.

**Failures raise.** `SplinkBackendError`, never a quiet fall back to another algorithm.

### Fixed — two integrity claims that were weaker than their wording

Both found by an outside review of the review path, and both are the same shape as the pin faults above: the code did something narrower than the sentence describing it.

**A review pack's digest covered its decision ids and nothing else.** `decision_ids_sha256` notices a row added or a row dropped, and misses every edit inside a row. Every name in a pack could be rewritten, a decision flipped, the evidence rewritten, and the digest still matched, while the guide beside it said an edited pack is visible.

The manifest now also carries `content_sha256` over every column the matcher wrote, computed by `arche.report.pack_content_digest` and recomputable from the CSV alone, which is the point: a reviewer who was not there can read the pack and check it. The four review columns are excluded deliberately, because a reviewer filling them in is the pack being used rather than altered, and a digest that moved when somebody did their job would be checked once and then ignored. Rows are sorted first, so re-sorting a pack in a spreadsheet is not an alarm.

`decision_ids_sha256` stays, named for what it is. Membership and content are different questions and both are worth answering.

**A signed pack proved how many of each outcome, not which.** `sign_pack_manifest` signed the pack digest, the row count, and a tally: `{"same_entity": 180, "different": 180}`. Two adjudications that disagree on every single decision produce identical counts, so they produced an identical signed payload and an identical signature. It attested that somebody marked 180 rows one way without saying which 180.

`sign_adjudication` replaces it. The thing hashed is a ledger, one row per decision id carrying the outcome, the reviewer and the reason, sorted by decision id, and its `outcomes_sha256` goes inside the signed body. That is what binds a decision to its outcome. The ledger is returned in full alongside, so `verify_adjudication` can recompute the digest and catch a swapped ledger under a valid signature.

It signs the content digest rather than the id digest, so a pack whose names were edited after signing no longer verifies.

**What this still does not establish is who reviewed.** `reviewer` is a string somebody typed and `marked_at` comes from the local clock. The signature proves the ledger has not changed since it was signed, by the holder of one key. It does not prove the names in it are real people or that the times are true, and the studio README says so where it talks about putting the tool behind an auth proxy.

### Fixed — `blocking_sha256` identified nothing

It hashed `str()` of the Splink rule objects, which yields `<...BlockingRule object at 0x7f...>`. The pin therefore changed on every run and matched nothing, including itself. It now comes from the saved model's SQL, with a regression test that runs the same input twice.

### Fixed — two pins that claimed more reproducibility than they delivered

Both found by an outside review of the resolve lane, and both are the same fault: the code states a rule in its own comments and then does not follow it.

**`comparators_sha256` was truncated to 16 hex characters.** Sixty-four bits is fine against accident and not fine against anyone who wants two comparator sets to pin identically, and the field is named for a digest it was not holding. A pin exists so a third party can check which configuration produced a decision, and a pin that can be collided on purpose cannot do that. It is now the full digest.

**A self-calibrated table pinned as the word `self-calibrated`.** This is the one that matters, because self-calibration is the default for `person` and for any pack without a shipped table: the table is built *from the two lists being linked*, so the same pair scored in two different batches is scored against two different vocabularies.

That is not a bug. It is what self-calibration means, and the docstring says so. The bug was that the pin did not admit it. Measured on one pair, `Ngozi Adeyemi` against `Ngozi Adeyemi Bello`:

| batch | tftoken | score | decision |
| --- | ---: | ---: | --- |
| among twelve unrelated names | 0.627 | 0.7135 | `match` |
| among twelve other Adeyemis | 0.522 | 0.6608 | `review` |

Same records, same comparators, different answer, and before this fix **both runs pinned identically**. `decision_id` is derived from the pins, so it asserted that two decisions which disagreed were the same decision.

The pin is now `self-calibrated@sha256:...` over the table's canonical form. The batch dependence is unchanged and still real; it is now visible. Two decisions carrying different tf digests were scored against different vocabularies and were never expected to agree.

**A caller's own token-frequency table pinned as the word `provided`.** A frequency table decides which tokens are rare, and rarity is both a comparator input and a blocking key, so two different tables reach different verdicts on the same pair. `reconcile.py` already says exactly this, and follows it for shipped tables, which pin as `shipped:place@sha256:...`. A supplied table got one word, so two runs that could not agree pinned identically. It now pins as `provided@sha256:...` over the table's canonical form, or `provided@<version>` when it carries one. A table that cannot be serialised still pins as `provided`, which reads as what it is: not identified.

**Decision ids move for every `crosswalk` call**, because both values are inputs to the id. Nothing about how a pair is scored changed.

### Changed — the Splink backend no longer fails quietly

`resolve_entities(use_splink=True)` caught bare `Exception` and returned fuzzy results in the same shape, with nothing in the return value saying the algorithm had changed. For a library whose claim is auditable decisions that is the worst available behaviour: the caller cannot see it, and the output cannot be distinguished from a run that went as intended.

A missing Splink install still falls back, because not installing an optional extra is a configuration choice rather than a failure, and it now says so at `INFO` rather than silently. Every other error propagates. A caller who wants fuzzy matching asks for it with `use_splink=False`.

### Fixed — a record whose tokens are all common now gets a blocking key

The rare-token blocker skipped any token whose occurrences would cost more than `pair_cap` pairs. That is right on its own: nobody wants to block on `clinic`. But a record whose tokens were **all** over the bound then received no key at all, and was never compared with anything.

Measured on Splink's `historical_50k`, 50,578 records of real UK people: arche generated 246,903 candidate pairs and missed 155,692 true ones. **27,055 of the misses had character-for-character identical names** — `nicholas jackson` against `nicholas jackson`, same date of birth, never proposed, because `nicholas` and `jackson` are each too common to block on. The rare-token blocker was discarding the common-name case the rest of the engine exists to adjudicate.

Records whose tokens are all over the bound are now also keyed on **pairs** of those tokens. Two common tokens together are not common, which is why every mature blocking scheme keys on conjunctions. The same cost bound applies to the pair key, so nothing unbounded is admitted.

On `historical_50k` the recall ceiling, the best any threshold could reach, goes **0.4878 to 0.5699** for 12.8% more candidate pairs. Splink's ceiling on the same data is 0.6593, so this closes about half the gap and does not close it.

**It moves a published number.** Abt-Buy goes from TP 728 / FP 22 to **TP 741 / FP 22**: thirteen more true matches and not one more false one, so precision is 0.9707 to 0.9712 and recall 0.6636 to 0.6755. The figures in the `0.4.0a1` section below were true for that release and are left as they were.

Blocking is slower for it. On the 50k dedupe, 109s to 218s.

### Fixed — `orthography` now reaches `crosswalk`

An orthography pack describes how one language spells one name several ways, so `Muhammadu` and `Muhammad` count as one token rather than two rare ones. It was opt-in on `shared_name_distinctiveness` and `TokenFrequencyTable.weighted_token_sim` and defaulted to `None` on both, and nothing threaded it through `reconcile`. No pack ever reached a `crosswalk` call, so the gain measured in the place benchmark came from binding the comparator by hand and the shipped path did not have it.

Declare it on the comparator, alongside `strip_type` and `strip_qualifier`:

```python
{"field": "name", "kind": "tftoken", "weight": 2.0, "orthography": "hausa"}
```

It reaches both places that consult it: the token similarity, and the distinctive-signal gate. On `Muhammadu Bello Clinic` against `Muhammad Bello Clinic` that moves the token score from 0.380 to 0.645 and the decision from `review` to `match`.

**No shipped pack declares it**, and there is a test asserting that. Every published pack number was measured without it, and turning it on for a pack is a separate decision with its own measurement. Nothing moves unless you ask.

### Added — `arche.report.review_pack`, a crosswalk result as an adjudication pack

`crosswalk_report` produces an artifact to read. This produces one to work: the two files `tools/arche-studio` opens, from any `crosswalk` result.

```python
from arche.report import review_pack

review_pack(result, records_a, records_b,
            out_dir="data/review_packs/register_x_survey",
            sides=("register", "survey"), entity="person", reveal=True)
```

Writes `pack.csv` and `manifest.json`. Columns are `decision_id`, `decision`, `score`, `distinctive_max`, an optional `distance_km`, then each side under its own prefix, then `evidence` as JSON, then the four columns a reviewer fills. The prefixes are how the studio works out which fields belong to which record without being configured, so a prefix containing an underscore is refused rather than silently mis-splitting every column.

Only `match` and `review` rows are written by default. A queue of pairs the engine already rejected is not a queue; pass `decisions=` to include them.

**Masked by default, like the report it sits beside.** Values pass through the masking allowlist and record ids shaped like national identifiers are refused outright. A masked pack is also close to useless for the thing a pack is for, since nobody can judge two people whose names are both redacted, so `reveal=True` is the normal call and the manifest records which one you produced. The point is that revealing is a decision somebody made rather than a default nobody saw.

The manifest carries the engine `pins`, so a pack opened months later still says which comparator set produced its decisions, and `decision_ids_sha256`, which is what the studio's integrity digest is checked against.

### Changed — the `person` pack can now see a date of birth

`ENTITY_PACKS["person"]` declared name, a token-frequency view of the name, `national_id`, `phone`, `email` and `address`. It did not declare a date of birth, which is close to the most common identifier in person linkage. On any source without an id, phone, email or address, the pack was therefore a name-only matcher, and it was not looking at a birth date even when handed one.

Reproducing [Jared Parrish's R `RecordLinkage` tutorial](https://rstudio-pubs-static.s3.amazonaws.com/1203076_6c678b417f564183a8708e3b4720c6c0.html) made the cost visible. Against 294 true pairs and 8 true non-matches, the shipped pack scored **219 true and 14 false**, less precise than the deterministic exact match it was being compared with. Every one of those 14 was two different children sharing a name and holding different birthdays.

The pack now declares `{"field": "birth_date", "kind": "date", "weight": 2.0}`. On the same set that is **265 true and 1 false**, precision 0.9399 to 0.9962, recall 0.7449 to 0.9014.

Weighted like a name rather than like `national_id`, because a birthday is strongly identifying without being unique. Weight 3.0 scored better again (274 true, recall 0.9320) and was not taken: tuning a shipped default until it peaks on one synthetic benchmark is how a number stops surviving real data.

**No refutation.** A date is exactly the asymmetric signal `refutes_below` was built for, and declaring it here measured precision 1.0000 against 0.9962. It is still not declared. `test_discriminator_veto.py` guards established packs against acquiring refutation as a side effect of some other change, and this is some other change. Callers who want it pass `comparators=` with `"refutes_below": 0.5`.

### Changed — `compare_dates` reads dates instead of comparing digits

The old implementation stripped non-digits and tested equality, so `6/28/2016` scored **0.0** against `2016-06-28`: the same day, written the way two different systems write it. Any pack refuting on that would have refuted every true pair between two sources that disagreed about date order, which is most pairs of real sources. That had to be fixed before the pack could carry a date at all.

Reading is anchored on the four-digit year, the only component that identifies itself; the other two are month and day in whichever order makes a real date. So `2016-06-28`, `6/28/2016`, `28/6/2016` and `2016-28-06` all read as one day with nobody declaring a locale.

Where a date is genuinely ambiguous both readings are kept, and agreement on either is agreement. `6/7/2016` against `7/6/2016` scores 1.0, because the strings do not say which is meant and inventing a disagreement is worse than withholding one. A date with no four-digit year is unreadable on purpose: `03/04/05` has six meanings.

Precision is part of the reading. A bare `1994` is a date known to the year, not a broken date, and comparing it against `1994-03-02` at day precision would manufacture a disagreement out of a difference in what each source recorded. Comparison happens at the coarser of the two precisions, which is what keeps the DBLP-ACM publication-year discriminator behaving as it did.

One keying slip now scores 0.35 rather than 0.0: within one day, or exactly one of year/month/day different. Of the 12 true pairs whose dates disagree in the Parrish set, the shapes are the ones you would predict, `2017-01-01` against `2016-12-31` and `2018-11-19` against `2018-11-29`. A flat 0.0 dropped those pairs below the candidate threshold and out of the result, where a reviewer could not see them; 0.35 keeps them visible without letting them confirm.

**This grading has a cost, and it is visible in the one false merge left.** `JORGE TORRES 2016-02-23` matched a different `JORGE TORRES 2016-10-23`: one component out, so 0.35 rather than 0.0, so the pair stayed above the threshold instead of vanishing. Under the old digit comparison it would have scored 0.0 and been dropped. Grading near misses means some of them are near misses between two different people, and this is the trade being made rather than a bug. The pack's true match for that record is a register row reading `GORGE`.

**Unreadable is not disagreement.** `compare_dates` still returns 0.0 for an unparseable string, because two callers pre-check both sides and need a float. The `date` comparator *kind* returns `None` instead, so it drops out of the weighted mean and cannot fire `refutes_below`. A record is not punished for a format nobody promised.

**Decision ids.** The `person` pack gained a comparator, so its `comparators_sha256` moves from `b412742f3b961d45` to `8d1e03d23fa6b8a6` and every person decision id changes. Packs that do not declare a `date` comparator are unaffected. The `pairwise` path also sees the new grading, so a pair whose dates are one slip apart scores differently there too.

## [0.4.0a4] — 2026-08-19

**Benchmarks, documentation, and one change to how places are matched.**

`0.4.0a3` was prepared and never shipped. It was scoped and written up as a documentation release, and then a matching change landed in the same tree. Its changelog would have been false, so the version was skipped rather than rewritten. It was never published and never tagged, so nothing points at it.

### Changed — administrative disagreement is now weighed against distance

`compare_containment` treated a state-level disagreement as total refutation however far apart the two records were. That is right in the interior of a country and wrong at every border, where boundary files carry 100 m to 1 km of positional error and one school can be recorded on either side of a line.

Disagreement at the coarsest level now returns a neutral score discounted by distance: it falls linearly from a small positive value at zero separation to exactly zero at `BOUNDARY_UNCERTAINTY_KM`, defaulting to **1.0 km**. Beyond the band nothing changes. The default comes from the stated positional accuracy of national boundary layers (GADM, OSM relations, COD-AB), not from any pair this was tested on.

The ramp is linear with a hard floor rather than an exponential decay, because `_score_pair` raises its conflict flag on exactly `0.0`. An exponential never reaches zero, so there would be no distance at which prior behaviour resumed.

A new `postcode` comparator applies the same reasoning to postal codes, with a 0.1 km band sized for a UK unit postcode. It is **not in any shipped pack** and refutes only through the existing `refutes_below` mechanism.

**What this cannot do:** the discount can withhold refutation, never manufacture a merge. The distinctive-signal gate is untouched, and the discounted value sits below the score a genuinely shared `admin1` earns, so a discounted disagreement can never read as agreement.

**Decision ids.** The shipped `place` pack is unchanged, so `comparators_sha256` is stable and unaffected decisions keep their ids. Ids move only where a containment comparator applies, the coarsest level disagrees, both sides carry coordinates, and the separation is inside the band.

**Measured, including where it costs.** On 400 same-name cross-state Nigerian school pairs, the change costs one false merge (0 to 1) at the 720 m pair the benchmark's own labels cannot adjudicate, and leaves the Enugu reconciliation untouched at 436 matches either way. It is a correctness claim, not a metric win, and the numbers are in `data/nigeria_school_false_merges_result.json`.

**Separately worth knowing:** supplying `admin_path` at all costs 81 of 517 Enugu matches, a 15.7% drop, from LGA-level disagreements dragging the weighted mean. That is existing behaviour rather than a regression, and it is recorded here because anyone adding admin data expecting a free precision gain should see it first.

Every published accuracy number was audited against something that runs. Three of the five did not survive contact with their own evidence, one is now known to be unverifiable, and the corrections are below.

Compared member by member against the published `0.4.0a2` wheel, three source files differ: `_version.py`, and the two below. No matching logic changed, so the same inputs still produce the same `decision_id`.

### Changed — two user-visible strings that contained an em-dash

Both are cosmetic and both are listed because they are visible to users, which makes "no behaviour changed" the wrong description however small they are.

- `doc/_documents.py` printed an em-dash in the extracted-records table where a field was empty. It now prints a hyphen. The four pages that show that table were updated in the same change, because the alternative was documentation that no longer matched the output.
- `sign/jws.py` had an em-dash inside the "no trusted key available" hint. The sentence is reworded; the guidance is identical.

`0.4.0a2` went to the index carrying an uncorrected frequency claim. That is why this release exists: a PyPI long description cannot be edited in place, and the front page of the package was the last place the old number still stood.

### Changed — a results row that claimed more than it had earned

The name-frequency row in the README is now labelled **an ablation, not a benchmark**. It reports 40% false merges falling to 0% against the same engine with the frequency signal switched off. That self-ablation is the cleanest baseline in the table and the weakest evidence in it, for one reason: the 60 negatives were built around the exact failure the signal exists to fix, so passing is close to guaranteed by construction. It shows the signal is wired up, not that it generalises.

It is also the only row that cannot be re-run from this repository. The organisation lane ships `bench_organisation.py` and the result file it produced, so anyone can check the 0.9493 themselves. The ablation ships neither the set nor the script, and the document the research notes cite for it does not exist in this repo or in its history.

The table header changed from `Benchmark` to `What`, because it was listing an internal ablation alongside public benchmarks under a word only some of them had earned.

This correction missed `0.4.0a2`, which had already been published. A PyPI long description cannot be edited in place, so the uncorrected row stays on the index under that version until the next release supersedes it.

### Added — `datasets/names_dataops/bench_name_frequency.py`

The frequency claim is now re-runnable, and re-running it changed every number in it. The benchmark links two lists drawn from the North Carolina voter register: **1,114 observed negatives** (real people sharing a surname, differing in first name and birth year, so duplicate registrations cannot be mislabelled) and 1,500 constructed positives. Three arms — the `person` pack without its `tftoken` comparator, the shipped default, and the pack with the population table loaded explicitly. Deterministic under a fixed seed; the register is fetched at run time and never vendored, because it holds real names and addresses.

| arm | false merges | precision | recall | F1 |
|---|---|---|---|---|
| frequency-blind | 7,705 | 0.162 | 0.990 | 0.278 |
| shipped default | 41 | 0.946 | 0.480 | 0.637 |
| population table | 24 | 0.963 | 0.412 | 0.577 |

The old claim was wrong in both directions. The benefit is far larger than 40% → 0% suggested: a frequency-blind matcher run across two lists does not confuse the occasional pair, it links nearly everything to nearly everything. And "recall held at 1.00" was simply false — measured on same-person pairs differing only by a dropped middle name, recall is **0.480**.

The run **fails one of its three pre-declared criteria** and is published that way. The failing criterion asks the frequency-aware arm to stay within 10 points of the blind arm's recall, which is a bad criterion, because the blind arm reaches 0.990 recall at 0.162 precision by merging almost everything. The criterion is left failing rather than rewritten into a pass; the recall cost it points at is real either way.

### Known — the `person` pack does not load its shipped population table

`_PACK_TF_DOMAIN` maps `artist`, `place` and `organisation` to shipped frequency tables. `person` is absent, so `crosswalk(entity="person")` self- calibrates over the two lists being linked and never reads `name_frequencies.json.gz`, despite that table shipping in the wheel and reporting `population_scale=True`. This is the same defect the `organisation` pack was given a map entry to fix.

It is recorded rather than fixed because the benchmark does not support calling it a regression: the self-calibrated default scores **F1 0.637** against the population table's **0.577** on this data, trading 1.7 points of precision for 7 points of recall. Changing the mapping would change `decision_id` values for every person-pack decision, so it needs its own evidence rather than an assumption.

### Added — `datasets/names_dataops/bench_febrl.py`

The Febrl 4 claim — precision 1.0, 87.7% auto-resolved, 96.2% surfaced, carried since v0.1 — now runs. It reproduces **exactly**: all three figures land on the published values.

What it reproduces is the point. Febrl ships `soc_sec_id`, a near-unique synthetic identifier, and with that field in play the engine is substantially joining on a key rather than resolving names. Withhold it and the same pipeline scores precision **0.921** with 282 false merges, auto-resolving 65.7% instead of 87.7%. The number was never wrong. The configuration simply stopped travelling with it, while the prose around it described a representation engine working at scale.

The script declares the name-and-address configuration as its headline and **fails two of its three pre-declared criteria**, published that way, because those criteria asked the harder configuration to hit the easier one's figures.

### Changed — Leipzig 0.9506 is not the out-of-the-box number

`data/scripts/benchmark_leipzig.py` now writes a committed result file, and it records both configurations. Out of the box the pipeline scores precision **0.8500** with 391 false merges. The published **0.9506** requires the caller to declare `refutes_below` on `year`. Both are real; only one was quoted, with an em dash in the baseline column implying there was nothing to compare against.

### Known — the multilingual result cannot be re-run

`47/48` against Presidio's `37/48` has been quoted since v0.2. The 48-case set is not in this repository and nothing here computes the number. It is now labelled unverified in the README and in `the-whole-picture` rather than left sitting beside four figures that can be checked. The same applies to the 58-pair name-equivalence set.

Rebuilding it is tracked work. Until then it is an assertion, and it is marked as one.

### Changed — the README's documentation links now point only at pages that will survive

The docs are being reorganised along the lines Splink uses: a user guide that answers questions people have *while using the tool*, with the essays about what identity is moving to a personal site where they belong. Several concept pages will not survive that move.

A PyPI long description cannot be edited in place, so any link baked into this release is permanent. Three of the six pointed at pages scheduled to move (`sameness-and-similarity`, `arche-in-practice`, `entities`) and have been repointed at Quickstart, How it works, and Re-verify a decision, which are staying and are more useful on a package front page anyway. Every remaining doc link in this wheel's metadata resolves to a page that survives the reorganisation.

---

## [0.4.0a2] — 2026-08-16

**Metadata only. No behaviour changed.**

That is stated first because it is checkable and because a version bump usually implies otherwise. A fresh build was compared member by member against the published `0.4.0a1` wheel, with newlines normalised so a Windows build could be compared against a Linux one. Of 151 files, exactly two differ: `METADATA`, and `_version.py`, which holds the version string and therefore cannot not change in a version bump. Every other code and data file is byte-identical.

The bump exists because a package description, its keywords and its long description are part of what PyPI serves and cannot be corrected in place once a version is published.

### Changed — how the package describes itself

The project is positioned as what it is: entity resolution for messy data from sources that never agreed on identifiers, covering people, places, organisations and products, and reading documents as well as records. Africa is described as where the calibration is deepest rather than as the limit of where the engine runs, because the organisation frequency table is built from company registrations across 65 jurisdictions and the product work is benchmarked on US retail catalogues.

The README now covers work that shipped in `0.4.0a1` and went undocumented on the front page: the five entity packs, `resolve_documents` as a first-class entry point, extraction provenance, and how a third party re-checks a signed decision. It also corrects a figure that would have been wrong in public, where the Leipzig DBLP–ACM result was about to be quoted as an F1 when 0.9506 is the **precision** (recall 0.9960, 115 false merges visible under a complete mapping).

### Removed — a keyword advertising software that does not exist

`MCP` was listed among the package keywords. There is no MCP server in this package and none in the wheel. The roadmap had already corrected the same claim elsewhere; the index entry was the last place it survived.

---

## [0.4.0a1] — 2026-08-15

The document lane, the product lane, and the `EgressGuard` security fix that `0.3.0a2` was going to carry before it was superseded.


### Added — an experimental organisation entity lane

`ENTITY_PACKS["organisation"]` (`"organization"` accepted for the same pack) — companies, cooperatives, unions and institutional bodies. Built for cross-party supplier reconciliation in cocoa, coffee and tea chains, where the aggregation node differs by commodity (society, washing station, factory or estate) but its shape does not: a named site, operated by a legal entity, aggregating from many smallholders.

**Identity contract:** the legal or institutional party, as it would be named on a document evidencing a transaction. Sameness of *site*, membership, ownership, management, certificate or payment destination is **not** sameness of party — each of those is a relationship, and belongs in an edge rather than a merge.

**First accuracy number, on a public labelled set with pre-declared criteria.** Measured on ER_Magellan Fodors-Zagats (946 labelled pairs, 110 positives) — business listings from two restaurant guides, the closest organisation-shaped task in a public, baselined entity-matching suite:

| | precision | recall | F1 | false merges | missed |
|---|---|---|---|---|---|
| **`organisation` pack** | 0.9626 | 0.9364 | **0.9493** | **4** | 7 |
| `person` pack | 0.9863 | 0.6545 | 0.7869 | 1 | 38 |
| token-sort baseline | 0.8333 | 0.9545 | 0.8898 | 21 | 5 |

The three criteria were written down before the run and all pass: **+0.1624** F1 over the `person` pack (needed +0.10), **+0.0595** over token-sort (needed +0.05), and **4 false merges against token-sort's 21**. The token-sort comparison is the meaningful one — a fivefold reduction in false merges while gaining F1 — because "beats the person pack on organisations" only establishes the pack is genuinely calibrated rather than renamed. The margin on criterion 2 is thin and is reported as such.

**What this number is not.** 946 pairs is small; the set is near-saturated (published learned baselines report ~100 F1); and it is Anglophone US restaurant listings. **It says nothing whatever about African organisation names** and must never be cited as if it did. The benchmark that would settle that is OpenSanctions Pairs — 755,540 analyst-labelled pairs, 31 countries, cross-script names — which is CC-BY-NC and requires a purchased licence for commercial use.

The benchmark data is fetched, never vendored: neither Magellan nor DeepMatcher states redistribution terms for the data (the code is BSD), so `datasets/organisations_dataops/bench_organisation.py` ships and the data does not.

**A population frequency table ships with it**, closing the gap the first draft of this entry declared open. Built from GLEIF LEI Level 1 data (**CC0 1.0**, a public domain dedication) — 52,875 organisation name forms across a census of 20 African jurisdictions plus a shallow sample of 45 more. `Central Cooperative Society` in two districts now scores `distinctive_max` 0.138 and routes to review, where it previously merged at 1.0; a genuinely rare shared name (`Kuapa Kokoo Farmers Union`) still matches at 0.808, so this discriminates on rarity rather than merely becoming more conservative.

**The table has two halves, and the curated one is where African calibration lives.** `_data/organisation_tokens.yaml` is hand-editable and applied last, so a curated entry always beats a measured count — the same mechanism as `place_tokens.yaml`, for the same reason. It is not a convenience: GLEIF counts `farmers` **once** in 52,875 organisation names, because LEI registration follows financial-market participation and cooperatives do not register LEIs. Measured alone the table concludes `farmers` is a rare, identifying token, which would let two unrelated `X Farmers Cooperative Society` records clear the distinctiveness gate on that word. No larger pull fixes it; someone who has read a supplier list has to assert it. Editing the YAML is a data change, and rebuilding reuses a cached corpus, so it takes seconds and no network.

The one rule the file must obey, enforced by tests in both directions: never mark a distinctive proper name generic. `kuapa`, `sefwi`, `gicherori` and `kericho` are exactly the tokens that must stay rare — they are what tells one cooperative from another. A commodity word (`cocoa`) is generic; a place word (`sefwi`) is not.

Stated plainly because it bounds what may be claimed: this table knows **corporate** naming and knows **nothing** about West African cooperative naming — LEI lists 51 entities for Côte d'Ivoire, the world's largest cocoa producer. It must never be cited as evidence for a claim about African organisation names. See `datasets/organisations_dataops/SOURCES.md` for the full licence comparison, including why Open Food Facts (ODbL, share-alike propagates to derived databases) cannot be vendored while Trase (CC BY, attribution only) can and is the planned second table.

Two supporting primitives, both additive and opt-in, so no existing pack's published numbers move:

- **`kind: "category"`** — a closed-vocabulary categorical comparator (normalised exact match). Deliberately **not** a distinctive kind: two records agreeing they are both a `SITE` is not evidence they are the *same* site. Its purpose is the site-versus-operator discriminator, the largest false-merge risk in supply-chain data — `Nyeri Hill Factory` and `Nyeri Hill Tea Factory Co Ltd` share a name *and* a coordinate, so name, token and geo signals all point the wrong way at once, and only a declared `entity_class` refutes them.
- **`strip_type: "<domain>"`** on a comparator spec — removes recognised type tokens before comparison, so a name comparator judges `Kuapa Kokoo` rather than letting a shared `Cooperative Union Ltd` carry the score. Unlike `normalize_type_token`, it strips *every* recognised form rather than the longest one, because organisation names stack them where facility names do not.

The `organization` type vocabulary grows from 4 forms to 21, covering cooperative/union/SACCO/licensed-buying-company/estate/factory/washing-station/mill plus European legal forms, so a counterparty's own records normalise on the same footing as the African ones they are joined to.

### Added — extraction provenance on document decisions

A decision derived from a document now records what produced it — `artifact_sha256`, `parser`, `parser_version`, `text_sha256`, `ocr` — on `ParsedDocument.provenance` and `DocumentReport.provenance`. These enter the pins **before** `decision_id` is hashed, so the id moves when the input bytes, the parser version, the rendering, or the OCR setting moves.

Previously such a decision could be *re-run approximately but never re-verified*: the signature covered the verdict while saying nothing about the extraction behind it. A signed wrong merge with opaque extraction provenance is worse than an unsigned heuristic, because it lends institutional legitimacy to something the reader cannot inspect.

`artifact_sha256` and `text_sha256` are **full, untruncated** SHA-256 digests in lowercase hex, so `sha256sum` / `shasum -a 256` / `Get-FileHash` reproduce them exactly. (A pre-release build truncated them to 32 hex chars, which made the standard tools disagree with a field named `sha256` — the one wrong answer it must never give.) This changes `decision_id` for every document-derived decision relative to that build.

New guide: [Re-verify a decision](https://unpatterned-labs.github.io/arche/how-to/re-verify-a-decision/), covering all three lanes and what a recipient of a signed decision should check.

### Added — an experimental electronics product lane

`ENTITY_PACKS["product_electronics"]`, plus the primitives it is built from. One call, no setup:

```python
from arche.resolve import crosswalk
crosswalk(abt, buy, entity="product_electronics", id_field="id")
```

Measured on [Leipzig Abt-Buy](https://dbs.uni-leipzig.de/research/projects/benchmark-datasets-for-entity-resolution) (1,081 x 1,092, 1,097 true pairs, complete ground truth so false merges are visible):

| | baseline, name only | `product_electronics` |
|---|---|---|
| precision | 0.7954 | **0.9707** |
| recall | 0.2197 | **0.6636** |
| F1 | 0.3443 | **0.7883** |
| false merges | 62 | **22** |

**The signal is rarity, and two mechanisms produce it.** With the rules that actually ship, code-blocking alone reaches 0.8865 precision over 881 pairs and the rarity filter lifts it to 0.9973 over 754. (Both over the full cross-product; inside the union blocker's own candidate set the same two rows are 856/0.8843 and 731/0.9973. They are different populations and are never mixed into one series.)

**The frequency table does that work, not the stop list.** Two earlier drafts of this entry got the attribution wrong in opposite directions, so here is the end-to-end measurement instead of an argument — Abt-Buy, shipped pack, with `stop_codes` on and with it emptied:

```text
stop_codes ON  (shipped)   TP 728  FP 22  P 0.9707  R 0.6636
stop_codes DISABLED        TP 728  FP 22  P 0.9707  R 0.6636
```

Byte-identical. On this benchmark the stop list contributes **nothing**, because the table already scores `1080p` far below the gate: `16gb` at df 11 is **0.182** against 1.0 for a code as rare as a unique one, and only the latter clears `DISTINCTIVE_FLOOR` unaided.

What the stop list earns is the small-catalogue case the benchmark cannot show — four records whose only shared code is a resolution give two false merges with it off and none with it on. It is a floor for corpora too small to estimate frequency from, not a substitute for estimating it.

**A calibration bug worth recording, because it made the lane worse than no lane.** `TokenFrequencyTable.distinctiveness` is `min(1, -log10(rel_freq)/5)`, calibrated for the million-token word corpora behind the place and person tables. A code vocabulary is ~2,000 documents, so the rarest possible shared code — one occurrence in each source — scored **0.6205**, below `DISTINCTIVE_FLOOR` (0.75). The gate therefore demoted *every* true product match and recall fell from 0.2197 to **0.0948**. The formula was not wrong; it was being asked a question about a different distribution. `code_rarity` scores document frequency relative to what a unique code looks like *in that corpus* (`min(1, baseline/df)`, where `baseline` is twice the lower-quartile df). An earlier version anchored on the constant 2, which made recall collapse from 0.6636 to 0.0419 on a catalogue where each product is merely listed twice — the score has to be corpus-relative, not absolute.

New public surface:

- `resolve._productcode.extract_product_code_candidates(text, category)` — *candidates*, deliberately not "model numbers". A regex cannot tell a manufacturer code from a retailer SKU from a spec; rarity does that later. Normalisation is most of the lane: raw-string matching finds a shared code on 44.9% of true pairs, normalised on **71.2%**, because one source writes `SB97CS` and the other `SB-97Cs`.
- `kind: "code"` — rarity-weighted code agreement. `None` when either side has no candidate; **0.0**, not a veto, when both have codes and share none — 18.6% of true pairs are in that position (accessories, bundles, retailer SKUs), so a conflict rule would refute them all.
- `kind: "spec"` — agreement on identity-bearing units, for use with `refutes_below`.
- `ProductCategory` / `register_category` — **the modularity seam.** Adding food, books or apparel is a category registration plus a benchmark, not a change to any comparator.

**Identity contract: a purchasable variant (SKU).** A 16GB and a 32GB player are different products however alike their titles, which is why `spec` refutes rather than merely scoring. That contract is data on the category (`identity_units`), not a constant in a comparator, so a lane with different semantics declares different units.

**Scope, stated rather than buried.** There is no generic `product` pack and shipping one would overclaim. The evidence is a single electronics corpus, and on Amazon-GoogleProducts — general merchandise — the lane barely helps and **costs precision**:

| Amazon-Google | baseline | lane |
|---|---|---|
| precision | 0.4898 | 0.4863 |
| recall | 0.3338 | 0.3408 |
| F1 | 0.3971 | 0.4007 |
| false merges | 452 | 468 |

That is +9 true matches for +16 false ones — a marginal precision of **0.36** on the pairs it changes. The F1 gain is real and it is not worth having. Reporting only the F1 would have hidden it.

The rules that work here fail elsewhere by construction — Levi's `501` is rejected twice by thresholds that exist to filter prices and years, `32x32` looks like a model and is not, and reading `600mg` as a drug's model code would be dangerous. The category is flagged `experimental=True` and a test asserts no generic `product` pack exists.

Two further honest limits: the `spec` refutation rests on 47 of 1,097 true pairs — all 47 agree, but that is a thin base — and the code frequency table is self-calibrated over the two catalogues being matched rather than shipped, which is u-probability estimation over the data at hand rather than a shipped asset.

### Added — place-name qualifier splitting

Sources disambiguate places by appending the containing region, and they do not agree on how. On the [Leipzig Geographic Settlements benchmark](https://dbs.uni-leipzig.de/research/projects/benchmark-datasets-for-entity-resolution) — 3,054 records, 4 sources, complete ground truth — the same settlements are written four ways:

```text
NYTimes   Petra (Jordan)      99.7% qualified
DBpedia   Cordoba, Spain      36.8% qualified
Freebase  savannah             0.0% qualified
GeoNames  Split                0.0% qualified
```

A name comparator reads the appended region as part of the identifying string. The real pair NYTimes `Marseille (France)` against DBpedia `Marseille` scored **0.661** against a 0.70 threshold — `placename` 0.900 and `tftoken` 0.533, both diluted by a country name that is not part of the identity.

**The distinctiveness gate was clearing at 0.900 throughout.** This was a representation failure, not a threshold one, and it is worth stating because the tempting fix is to lower `DISTINCTIVE_FLOOR`. That constant is shared with the person lane, where 0.70 lets two different people both named `Ibrahim Musa` auto-merge — `test_coreference.test_s3_common_name_only_is_review` pins it.

Three additions, all opt-in:

- **`arche.split_place_name(name) -> (core, qualifier)`** — public. `('Petra', 'Jordan')`, `('Cordoba', 'Spain')`, `('Split', '')`. A qualifier is only reported when a non-empty core remains, so `(Jordan)` stays whole.
- **`kind: "qualifier"`** — a comparator on the appended region. Returns `None` when either side is unqualified, because three of the four sources leave most names unqualified and absence is missing evidence, not disagreement.
- **`strip_qualifier: true`** — a spec flag on any text comparator, making it judge the core name. Declare both on the same field, no record preprocessing:

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

Read the last two rows before the third. Auto-match recall moves 20 points, but surfaced recall moves 1.5 — roughly 837 of the newly auto-matched pairs were **already in the review queue**. This is an automation result, 61% less human adjudication for the same evidence, not a discovery result. Precision pays 1.3 points for it, and the worst source pair pays 2.4.

**It ships off by default, and a test enforces that.** Enabling it changes Kano not at all — facility names carry no qualifiers — and on London recovers nothing while adding two more unlabelled auto-matches. The qualifier convention is a property of the *source*, not of places, so it is a capability rather than a default. Turning it on for a shipped pack moves that pack's published numbers.

**On the `spec` refutation.** It is exactly neutral on Abt-Buy — identical precision, recall and counts with and without it. It earns its place from the **identity contract** rather than from this corpus: under a purchasable-variant reading a 16GB and a 32GB player are different products, and the refutation is what makes that contract executable rather than decorative. Only 47 of 1,097 true pairs carry a comparable unit, so this corpus cannot test whether it helps, and a test pins the neutrality so a future change that makes it *harmful* is caught. An earlier measurement showed it costing one true match; that was the `_SPEC` boundary bug refuting `F5C400300W` against `F5C400-300W`, now fixed.

Four robustness fixes from an adversarial review of this lane:

- **`compare_codes` fails loud without a table**, matching `tftoken`. It used to return 1.0, making `16gb` indistinguishable from `2595b002` — a silently worse answer rather than an error.
- **`code_rarity` reads `_as_counts()`**, not `_counts`. A table built from relative frequencies alone carries `_counts = None`, and reading it directly made *every* code score maximally rare with no error.
- **The code table is named in `pins`** as `codes@sha256:…`. It decides whether a shared code is identifying, so two runs with different tables can reach different verdicts on the same pair; an unpinned scoring input makes `decision_id` claim a reproducibility it does not have.
- **One table per declared category**, not one for the first `code` comparator found, and `register_category` refuses to shadow an existing name without `replace=True`.

`build_code_table` now warns when the typical code appears more than twice — an applicability bound said out loud, since the lane was measured on catalogues where a code appears once per source.

The qualifier is a **scored** signal rather than a `refutes_below` discriminator on purpose: qualifiers are written at different granularities and in different forms (`NY` against `New York`), and as a refutation it removed 13 false merges while costing 17 true ones.

### Added — `refutes_below`, a declarable discriminator veto

Any comparator spec may now declare `"refutes_below": x`. When that comparator applies and scores under `x`, the pair is demoted to `review` no matter how well everything else agrees:

```python
{"field": "year", "kind": "date", "weight": 0.5, "refutes_below": 0.99}
```

**Why a weight could not already do this.** A weight is symmetric — it rewards agreement by exactly as much as it punishes disagreement. Some attributes are not symmetric: they disagree meaningfully and agree cheaply. A publication year is the clean case, and DBLP–ACM makes it measurable because the Leipzig mapping is *complete*, so false merges are visible for the first time in this project. Year agrees on **2,224 of 2,224** true pairs and separates 213 of 391 false merges. Raising its weight makes precision **worse**:

| `year` weight (against 7.0 on title + authors) | Precision | Recall |
|---|---|---|
| 0.5 | 0.8500 | 0.9960 |
| 2.0 | 0.8761 | 0.9987 |
| 7.0 | 0.6531 | 0.9996 |
| 25.0 | 0.6531 | 0.9996 |

Thousands of unrelated papers share a year, so turning the field up turns up the noise it sits in. Declared as a refutation instead, on the same declaration:

```text
baseline (year scored)     P=0.8500  R=0.9960   (TP 2215, FP 391)
year refutes_below 0.99    P=0.9506  R=0.9960   (TP 2215, FP 115)
```

**276 false merges removed, zero true matches lost.** Reproduce with `uv run python data/scripts/benchmark_leipzig.py`.

This generalises the geographic veto rather than inventing anything, and keeps its rules:

- **Demotes to `review`, never `no_match`.** A refutation says a human must look, not that the answer is no. Note this is strictly better than what a heavy weight does — a heavy weight pushes the pair under the floor and the edge is *dropped*, so the reviewer never sees the conflict at all.
- **A missing value never refutes.** Absent evidence refutes nothing, exactly as absent coordinates cannot fire `veto_km`.
- **Refutation and scoring stay orthogonal.** `weight` is unchanged by the flag; pair with `"weight": 0.0` for a discriminator that refutes and never confirms.
- **The conflict is named in the evidence** as `<field>_conflict`, because a demotion a reviewer cannot explain is indistinguishable from a bug.
- **Out-of-range thresholds raise** rather than silently always- or never-firing, both of which read as a tuning choice rather than a typo.

Before this, arche had exactly two vetoes: `veto_km`, which requires coordinates, and `id_conflict`, hardcoded to the field name `national_id`. Neither was reachable from a declaration, so the gap blocked publications (year), products (model, pack size), charge points (connector) and people (date of birth) identically.

**No shipped pack declares `refutes_below` yet**, and a test enforces that. Turning it on for `place`, `person` or `artist` changes those packs' published numbers, so it is a separate and separately-measured decision rather than a side effect of adding the mechanism.

### Added — phrase distinctiveness, shipped in the wheel

The gate asks whether two names share something *rare*, and it asked that of **tokens**. That is right where the identifying part of a name is one rare word: ``Karfi Health Post`` clears on ``karfi`` at 0.93. It is wrong where identity lives in a phrase of ordinary words. Every token of ``London Bridge Hospital`` is common — ``london`` 0.69, ``bridge`` 0.61, ``hospital`` 0.35 — so two records of that hospital 30 m apart with byte-identical names were routed to ``review``.

A bigram frequency table now ships alongside the unigram one and the corpus separates the two cases with no curation at all:

```text
general hospital  0.486     london bridge  0.921
primary health    0.322     kings college  0.967
health post       0.349     king george    0.766
```

`TokenFrequencyTable.phrase_distinctiveness` returns the rarity of the rarest **shared** phrase, and the gate combines it with the token measure using `max`, so it can only recover a pair and never demote one.

Four guards, each closing a failure this codebase has already hit once:

- **Only phrases the corpus has actually seen may speak.** Membership is tested against the raw counts, not `rel_freq(g) > floor` — `rel_freq` clamps at the unknown floor, so a genuinely rare phrase and an unseen one return the same number. The first version used the clamped test and silently discarded `london bridge`, which is real and sits below the floor.
- **The phrase table must share its unigram table's tokenisation.** Loading raises otherwise: a phrase assembled under one rule cannot be looked up in counts accumulated under another.
- **A runtime-built table is silent.** Phrase evidence requires `population_scale`, so a small corpus cannot clear the gate on noise.
- **The phrase table is named in the pin**, which now reads `shipped:place@sha256:…+phrases@sha256:…`. It is a scoring input, so a rebuild changes decision ids rather than results silently.

Measured, shipped configuration:

| | before | after |
|---|---|---|
| London hospitals, 86 labelled pairs | 73 auto-matched | **82 (95.3%)** |
| routed to review | 12 | 3 |
| Kano GRID3 x OpenStreetMap | 564 match, 88.1% LGA | 566 match, **88.1% LGA** |

The three pairs still abstaining are the ones that should:

- `Memorial Hospital` against `Memorial Hospital, Woolwich` — that stem appears four times in each source, and `memorial hospital` as a phrase scores 0.554.
- `Nuffield Health Highgate Hospital` against `Highgate Private Hospital` — brand substitution, which belongs in an alias field rather than a comparator.
- `St Mary's Hospital` against a byte-identical `St Mary's Hospital`. This one is worth spelling out, because an identical string abstaining looks like a bug and is not. The rarest shared token is `marys` at 0.716 and the rarest shared phrase is `marys hospital` at 0.704, both under the 0.75 floor — `st` alone has 10,651 occurrences in the place corpus, and London has more than one St Mary's Hospital. The gate is refusing to let a shared location manufacture a merge on a name that does not identify anything, which is the same rule that stops two `General Hospital` records merging. It costs a true pair, and the pair goes to review rather than being lost.

The base wheel grows from 2.46 MB to 2.93 MB.

**A known risk, stated rather than buried.** Phrase rarity makes *containment* errors easier to trip, because a shared phrase is distinctive even when the two records are at different granularities. Among the auto-matches are `King's College Hospital Emergency Department` against `King's College Hospital` and `Charing Cross Hospital` against `Charing Cross Hospital Medical School` — a department and a medical school, neither of which is the hospital.

We are **not** suppressing them, and the reason is that this corpus cannot adjudicate the class: `Caterham Dene Hospital & Minor Injuries Unit` and `Moorfields Eye Hospital (City Road campus)` are labelled *true* while the two above are unlabelled, so a token-subset rule learned here would fit label noise and would also route three known-true pairs to review. Containment needs its own relation labels and its own verdict; until then it is a documented limitation of auto-match on this domain, not a solved problem.

### Fixed — the gate and the frequency table could silently disagree about what a token is

`resolve/_gate.py` kept its own `_TOKEN_RE`, duplicating the one in `resolve/_tokenfreq.py`, under a docstring asserting the two "match". Nothing enforced that. Editing one and not the other raised nothing and warned nothing: the table counted one vocabulary while the gate looked up another, so a tokenisation change could appear simply not to work while the suite stayed green. We hit exactly that while developing the change below, twice.

There is now **one tokeniser**, and the rule is a property of the *table* rather than of a call site. `TokenFrequencyTable` carries `token_rule`, serialises it, reads legacy payloads as `plain`, and **refuses to `merge` across rules** — counts accumulated under one tokenisation do not mean the same thing under another. `_gate` and `weighted_token_sim` both take the rule from the table they were handed.

`packages/arche-core/tests/test_token_rules.py` pins all of it, including that `_gate` no longer defines a token regex at all.

### Added — `possessive` tokenisation rule, and the place table rebuilt under it

`Queen's` tokenised as `queen` + a bare `s`, so `Queens Hospital` and `Queen's Hospital` shared nothing but `hospital` (distinctiveness 0.35) and were routed to `review` despite a name similarity of 0.987.

The new rule emits the joined form **alongside** the originals — `queen`, `s`, `queens` — never instead. Two alternatives were measured on a London hospital benchmark (OpenStreetMap x Wikidata, 86 labelled pairs, with the table rebuilt under each rule so no query hit counts accumulated differently):

| rule | auto-matched | vs baseline |
|---|---|---|
| `plain` (previous behaviour) | 72 / 86 | — |
| strip the possessive entirely | 71 / 86 | **1 worse**, 0 recovered |
| emit alongside (`possessive`) | 74 / 86 | 2 recovered, 0 lost |

Stripping recovers nothing because `Queens` and `Queen's` still reduce to different tokens; it only deletes a token that was never the deciding one. Folding — emitting `queens` *instead* — was rejected for demoting `St Mary Hospital` against `St Mary's Hospital` from 0.683 to 0.504.

**Additivity is not free, and the first version of this change broke it.** `weighted_token_sim` is a ratio, so an extra token on one side only inflates the union and lowers the score: `St Mary Hospital` vs `St Mary's Hospital` fell 0.763 to 0.563. The comparator now scores under both the table's rule and `plain` and takes the better, which makes the rule additive by construction rather than by argument. The shipped `place` table is rebuilt under `possessive`; its content version changes, so every `decision_id` computed against it changes, which is correct and intended.

Measured effect, shipped configuration: **London 73 -> 75 of 86 auto-matched**; **Kano GRID3 x OpenStreetMap unchanged** at 564 matches and 88.1% LGA agreement.

Two limits worth stating rather than burying. The London figure is an auto-match rate over a *tag-bearing positive subset* — the labels come from OpenStreetMap `wikidata=` tags, only 91 of 226 records carry one, and an absent tag means *unlabelled*, not *non-match*. It is not a recall measurement and there is no precision instrument for that corpus yet. And additivity is guaranteed **within a table**: rebuilding shifts the denominator for every token, so whether a migration demotes anything is a benchmark question, not an invariant.

## [0.3.0a2] — never published

**This version does not exist on PyPI and never will.** It was versioned, changelogged and merged, then superseded by `0.4.0a1` before it was tagged. The section is kept rather than deleted because `SECURITY.md` pointed readers at it for a period, and a changelog that quietly loses a version its own advisory cited is worse than one that admits the gap.

Everything below shipped in **`0.4.0a1`**.

A security fix and the documentation corrections it turned up. No new features.

### Fixed — `EgressGuard` emitted detected values in clear when spans overlapped

**This is a security defect in the component whose entire purpose is to stop exactly that, and it affects `0.3.0a1`.** Anyone using `arche.guard.EgressGuard` should upgrade.

`_project` replaced detected spans right-to-left and skipped any span that overlapped one it had already consumed. It sorted by `(start, end)` descending, which reaches the *innermost* span first, so the **container** was the span that got skipped — and the part of it outside the inner span was never replaced. The docstring claimed the opposite ("the outer, earlier-consumed span wins"); the code did not do that.

This was not a corner case. The shipped Nigerian detector set produces nested spans on any ordinary address, where `PII-4-ADDRESS` contains `PII-4-LOCATION`:

```text
in    Janet Okafor lives at 12 Awolowo Road, Ikoyi, Lagos.
0.3.0a1  Janet [NAME:…] lives at 12 Awolowo Road, Ikoyi, [LOCATION:…].
0.3.0a2  Janet [NAME:…] lives at [ADDRESS:…].
```

Two things made it hard to notice. The street address crossed the boundary in clear, and `PII-4-ADDRESS` was **absent from `GuardedProjection.fields` entirely**, so nothing downstream could tell that a detection had been dropped. Severity also inverted: under NDPA-2023 `ADDRESS` generalises while `LOCATION` is retained, so the span discarded was the more restricted one.

Overlapping detections are now grouped into disjoint regions and each region is replaced exactly once — the same resolution `policy.engine` already applied to redaction. Within a region the **action** comes from the most restrictive member (the safety property) and the **label** from the widest (an address containing a name is still an address). The token is derived from the whole region's text rather than one detection's, because the region is what leaves.

`GuardedField` gains **`covers`**, a tuple of every category absorbed into the region, so a collapsed region stays auditable. Existing fields are unchanged and the dataclass remains backward compatible.

Six regression tests were added, including an end-to-end one that runs the real pipeline and asserts no detection's text survives in the projection. The prior tests covered only disjoint spans, which is why this passed for a full release.

### Fixed — `extract_places_llm(config=...)` never reached the provider

`llm/spatial.py` called `providers.complete(messages, config)`. The signature is `complete(config, messages)`. Every call through the `config=` path handed the provider a list where the configuration belonged and failed on the first attribute access, so the documented "bring your own LLM" route for spatial role extraction did not work at all.

`llm/declarative.py` and `llm/extraction.py` both call it correctly, so this was one transposition rather than a pattern.

It survived a release because the entire spatial test suite passes `complete_fn=`, which bypasses the provider module. Three tests now cover the `config=` path — argument order, the model pin, and the mutually-exclusive argument check — and the first of them fails against the old code.

### Added — Huduma Namba detection (`PII-2-HUDUMA`)

Closes the gap the README correction above exposed. A Huduma Namba was previously matched by the NHIF pattern and reported as `PII-2-NHIF`: mislabelled, not missed, so a caller filtering on NHIF silently received Huduma numbers and a caller looking for Huduma found nothing.

Detection is **cue-anchored by design**. The NIIMS number has no check digit and its 8-12 character range overlaps both NHIF (8-9 digits) and the National ID (7-8 digits), so a bare number genuinely does not say which of the three it is. Matching bare digits as HUDUMA would have inverted the bug rather than fixed it, and started mislabelling NHIF numbers instead. The pattern fires only where the text says "Huduma", which is the same evidence a person uses and the only evidence present — hence 0.88 confidence against 0.40-0.45 for the bare-digit patterns.

Added to both the jurisdiction detector (`detect.ke.ids`) and the pan-African fallback (`detect._africa.ids`) so the two cannot diverge, ordered ahead of the bare-digit patterns. `PII-2-HUDUMA` maps to `mask` at `high` tier in the Kenya DPA pack, and `HUDUMA` joins the foundational identity classes — it is the NIIMS identity, not a sector-specific functional id. The `PII-2-NATIONAL_ID` rationale no longer claims to cover Huduma.

Ten tests, including the ones that pin what it must *not* do: no bare number is claimed as a Huduma Namba, and the cue is word-bounded so "shuduma" does not trigger it.

### Fixed — documentation that overstated what exists

Found while auditing our own claims for the above.

- **`roadmap.md` said the MCP server was "built but unpublished"** and described its security behaviour in detail — offsets not raw PII, no reveal option on any agent path, fails closed without a statute. **No MCP code has ever existed in this repository.** All three claims are corrected in place rather than quietly deleted, because asserting security properties of software that was never written is the more serious error of the two.
- **The PyPI front page claimed independence we explicitly disclaim.** The package README said the Kano crosswalk gives "88.2% agreement with **independently-recorded** administrative boundaries" and linked to a page whose first paragraph says "**It is not independent validation**" and reports 88.1%. Corrected to state the weak label, the shared lineage, and that the figure is a consistency check.
- **"Six statute packs at v1.0"** — six packs ship; three are `v1.0` and three are `v0.1-scaffold`. The README now says which are which.
- **"~310KB base"** — the base wheel is **~2.5 MB** and has been for some time; the place frequency table added 1.2 MB of it. Also corrected in the roadmap, which said ~1.3 MB and "1,456 tests" against an actual 1,561.
- **Huduma Namba was listed as a detected government ID.** It is declared in `jurisdictions.kenya` with a validator but has **no pattern in the detector set**, so a Huduma number is matched by the NHIF pattern and reported as `PII-2-NHIF` — mislabelled rather than merely missed. Removed from the coverage table and named as a gap.
- **"~500 cities"** in the detection-layer notes — the gazetteer holds 102 cities and 134 aliases (236 lookup keys).
- **`pyproject.toml` listed five workspace members that are not on disk** (`arche-mcp`, `arche-graph`, `arche-live`, `api`, `demo`).
- **`data/scripts/build_bridge_file.py` imported `arche_mcp`** and raised `ImportError` on every run. The handler it wanted was lifted into core as `resolve.reconcile` with the same signature.

## [0.3.0a1] — 2026-08

First alpha of the 0.3 (beta) line. The published beta criteria (DPA-consulted statute packs at v1.0, the Africa Address Benchmark with cross-tool baselines, a 90-day production deployment) remain the gate for `v0.3.0` proper; this alpha opens the line and its breaking-change window.

### Changed — statute pack maturity, stated honestly

- **Every pack now declares its maturity in two independent fields.** `NDPA-2023`, `GDPR` and `HIPAA Safe Harbor` ship at `version: v1.0`. `POPIA`, `Kenya DPA` and `Ghana DPA` remain `version: v0.1-scaffold`: they carry complete category mappings, but the version bump is held until their cited sections have had a second reading. Previously the label meant two different things depending on the file — GDPR / HIPAA were already `v1.0` with no external review, while three packs with equally complete mappings sat at `v0.1-scaffold`. `review_status` (below) is what disentangles those two meanings; `version` alone never could.
- **New `review_status` field on every pack**, orthogonal to `version`: `version` means *complete and stable* (our work); `review_status` means *who vouches for the mappings* (a fact about the world). Values are `self-reviewed` (arche's own reading of the cited sections) or `regulator-reviewed`. The loader **fails closed**: a pack claiming `regulator-reviewed` without a `reviewed_by` is rejected, because a claim about regulator engagement is the one claim this product must never fudge. All six shipped packs are `self-reviewed`; none claims regulator review. Exposed as `Statute.review_status` / `.reviewed_by` / `.reviewed_on`.
- **Beta criterion revised** accordingly — from "POPIA, Kenya DPA and Ghana DPA reach v1.0 after structured DPA consultation" to "every shipped statute pack carries a complete category mapping with cited sections and a declared review status." Regulator review is now tracked per pack and sought continuously, rather than gating a release. Revised in the open rather than quietly re-checked. Of the four criteria: **one met, one partially met, two open** — the roadmap tracks each one.

### Changed — the roadmap is a living document again

- **`concepts/roadmap.md` rewritten for v0.3.0a1.** It had drifted a full positioning behind: it described a 980-test v0.2.0a3 whose lead was African PII detection, listed `resolve` / `sign` / places as "power-user workflows, not the lead pitch", and described the statute packs before `review_status` existed to say who vouches for them. It now covers what actually ships (resolve, declare, the LLM lane, spatial roles and the referee, detect + govern, attest). No MCP server ships in this release — `arche-mcp` is not published and no server code lives in this repository; documentation that describes MCP tools in the present tense is being corrected. The roadmap tracks the beta criteria with per-criterion status, separates **in flight** work into the two live tracks, states each **gated** item with the prerequisite that gates it, and records three direction changes with their reasons — a roadmap that never logs its own reversals is a wish list. Status vocabulary (shipped / in flight / gated / not committed) is defined at the top and used consistently.
- **Beta criterion 3 corrected to *partially met*.** The v0.3.0a1 notes first marked it done on the strength of the callable-shim removal, but the criterion as published requires deleting the whole PEP 562 lazy v0.1 surface — which we deliberately did not do, to avoid breaking alpha users twice in one release. The callable shims are gone; the remaining legacy names are deprecated with removal targeted for v0.4.

### Removed (breaking)

- **The v0.1 callable-module shim `arche.resolve(text)`.** Promised for v0.3 since the v0.2 migration; calling the module now raises `TypeError`. `arche.resolve` is purely the facade package (`resolve.pairwise`, `resolve.crosswalk`); `Pipeline.process()` is the composition-pattern replacement. The `arche.detect(text)` callable is **kept deliberately** — it is the documented Level-2 workhorse, not a compat shim. Remaining v0.1 lazy names stay importable through the 0.3 line; their removal is targeted for v0.4. `ResolvedEntity` keeps its name (decision 2026-08-07).

### Added

- **Resolution became a first-class surface.** `resolve.pairwise()` scores a single pair and returns a `CoReferenceDecision` (`identity` is one of `same_entity` / `review` / `different`); `resolve.crosswalk()` runs a whole table and returns `matches`, `count`, `blocking` and `pins`; `resolve.reconcile()` and `resolve.sign_edges()` close the loop.
- **Union blocking.** Candidate generation ORs spatial cells, rare shared tokens, and shared identifiers (`union_candidate_pairs`) rather than blocking on geography alone. `blocking_recall()` measures the result.
- **Declare your own schema.** One YAML declares your fields and annotates each with an arche role; `Declaration` generates the comparators, the masking, the JSON Schema your LLM extracts into, and a content-hash pin that enters every decision id. Driven from the CLI with `arche schema validate` and `arche schema gen`.
- **The LLM lane.** `extract_declared()` reads messy text into a declared schema with hallucinated fields recorded as violations rather than values; `grade_pairs()` and `grade_extractions()` score a model's judgment with `review` counted as an honest abstention rather than an error.
- **Spatial role labeling.** `extract_places()` labels which address in a sentence is the origin and which is the destination and returns the linguistic cue that decided it. Conflicting cues, missing cues, and negated cues all yield `role="unknown"` at floor confidence rather than a guess. A 22-case labelled gold set ships inside the wheel (`load_gold()`) with a refusal-aware scorer (`grade_places()`), so the same set grades your own extractor, including your LLM.
- **Attestation.** `attest()` and `verify_attestation()` sign a decision together with the exact representation that produced it — engine version, thresholds, blocking strategy, table provenance, declaration pin.
- **The artist entity pack** — 38 equivalence groups across 112 name forms, demonstrating that a new entity type is data rather than new code.
- **`arche compare`** — the CLI front door, masked by default, with `--demo` requiring no data of your own.

### Fixed

- **`statute_at_signing` no longer double-prefixes the version.** Statute packs store `version: v1.0`, and the envelope builder prepended a second `v`, so every signed envelope carried `NDPA-2023@vv1.0`. Now `NDPA-2023@v1.0`. The round-trip test had pinned the malformed string, which is why it survived; the assertion has been corrected.
- **Attestations no longer claim reproducibility they do not have.** `reproducible` was computed as `mode == "jws"` — a fact about the signing format, not about the decision. So a decision built from an LLM extraction was signed as `reproducible: True` even though its own `extraction` pin recorded `reproducible: false`, putting both claims inside the same signed artifact. It is now derived from the decision's pins: any pin declaring itself non-reproducible makes the attestation say so. SD-JWT remains non-reproducible regardless, since salted disclosure digests are not byte-stable. Surfaced while verifying the bring-your-own-LLM path end to end.
- **`dir(arche.llm)` now shows the LLM API.** Everything except `LLMConfig` loads lazily through the module's `__getattr__`, and Python's default module `dir()` reads `__dict__` — so the module advertised `LLMConfig` alongside `Any`, `annotations`, `dataclass` and `field`, and none of the actual functions. Invisible to tab-completion and unhelpful at a REPL. `__dir__` now returns the curated public surface plus the submodules, deterministically regardless of what has been imported.
- **`HarnessReport` and `Divergence` are importable from `arche.llm`.** `grade_pairs()` returns a `HarnessReport` whose `divergences` are `Divergence` objects, but neither type could be imported from the package that returns them, so callers could not annotate against them. `DeclaredExtraction`, `build_messages` and `build_places_messages` were likewise reachable or useful but unlisted; `__all__` and the lazy-import map are now generated from one table so they cannot drift apart.
- **PyPI project metadata.** The `Documentation` URL pointed at `docs.unpatterned.org`, which does not resolve; it now points at the published site. `Changelog` and `Issues` links added.
- **The package version is single-sourced.** `pyproject.toml` declared `0.2.0a3` while `arche.__version__` reported `0.3.0a1`, so the built wheel would have gone out under the previous release's number. Version is now read from `src/arche/_version.py` and the two cannot drift again.

### Changed — geography can now refuse (breaking for the place pack)

- **The place pack gained a geographic veto, `veto_km: 10.0`.** Distance was a weighted signal at 1.0 against name+tftoken's combined 4.0, so it could be outvoted: two Kano facilities sharing a common Hausa name merged **143 km apart** with the geo comparator scoring 0.000. Distance is a physical constraint, not a preference, and it now demotes an otherwise-matching pair to `review`.

Benchmarked on GRID3 × OpenStreetMap (Kano, 685 × 1,723), scored against LGA agreement — a label both sources carry independently and neither derives from the other:

  | veto | same-LGA | diff-LGA | precision | matches >10 km |
  |---|---|---|---|---|
  | none | 481 | 134 | 78.2% | 73 |
  | 50 km | 481 | 110 | 81.4% | 49 |
  | 25 km | 481 | 77 | 86.2% | 16 |
  | **10 km** | **479** | **64** | **88.2%** | **0** |

Shipped defaults now resolve 545 matches at **88.2% LGA precision**, with nothing matched beyond 9 km and **170 pairs moved into review** carrying `geo_conflict_km` as evidence.

It demotes to `review`, never `no_match` — the asymmetry is the point. Being too strict costs a human glance; being too loose costs a clinic its allocation. Records without usable coordinates are never vetoed, because absent evidence refutes nothing.

- **`arche.resolve._orthography` — orthographic keying for name tokens.** A settlement written `Mai Tsidau` in one registry and `Maitsidau` in another shared no token, so the distinctiveness gate never fired and the true match was dropped. `_data/orthography.yaml` ships a Hausa pack: adjacent-token boundary collapsing, nasal assimilation (`n → m` before `b`/`p`), and ten curated equivalence groups. On Kano it recovers 13 real pairs (`Yan Gwarzo`/`Yangwarzo`, `Kafin Maiko`/`Kafinmaiko`, `Sanbauna`/`Sambauna`) with **zero demotions**.

Strictly additive by construction: `max(literal, keyed)`. An earlier wiring computed the Jaccard over keys *instead of* literal tokens and recovered 13 pairs while demoting 79 — the benchmark caught it. Vowel alternations (`Ririwai`/`Riruwai`) are recorded in the pack as `known_gaps` rather than guessed at; resolving them needs a Hausa speaker, not a pattern.

Off by default (`orthography=None`) on `weighted_token_sim` and `shared_name_distinctiveness`, because it changes scores.

### Changed — `Pipeline` now detects email addresses by default (breaking)

- **`emails` joins the default detector set.** It was opt-in, on the stated grounds that adding it "would change existing callers' detections, policy outcomes and redacted text". That was true, and it was the wrong trade.

An email address is PII under **all six** shipped statute packs — each maps `PII-3-EMAIL` to `tokenize` or `mask` with a citation — and `Pipeline` is the redaction path. A redaction pipeline that returns email addresses in the clear, by default, is not a compatible behaviour worth preserving.

  ```text
  before  'Contact Fatima Abdullahi at fatima.abdullahi@example.ng about NIN 12345678901.'
  after   'Contact NAME_099000a2 NAME_e38a0fcd at EMAIL_b07216d6 about NIN [NIN].'
  ```

Callers who need the previous output can narrow explicitly with `Pipeline(detectors=[...])`.

### Fixed — redaction leaked plaintext on overlapping detections

- **`apply_policy` spliced each detection independently**, in reverse start order. That is correct only for disjoint spans. Detectors nest routinely — a NAME inside an ADDRESS, a LOCATION inside an ADDRESS — and the second splice then applied original-text offsets to an already-resized string.

On ordinary Nigerian address text, with the shipped detector set and no options, that produced:

  ```text
  'Plot 5 Ibrahim Taiwo Road, behind the Total filling station, Kano.'
      ->  '[ADDRESS]o Road, [ADDRESS].'        # 'o Road' leaked
  '12 Adeola Odeku Street, Victoria Island, Lagos.'
      ->  '[ADDRESS], Lagos.'                  # 'Lagos' survived inside a masked span
  ```

`detections` and `policy_outcomes` were correct throughout; only the rewritten string was wrong, which is the worst shape for this class of bug — the output looks redacted.

Overlapping spans are now grouped and each group replaced once. The **action** comes from the most restrictive member (`drop > mask > tokenize > generalize
  > audit > retain`), because letting the outer span win would emit a
generalized address still containing a NIN the pack said to mask, and letting the inner win would leave the rest of the address in clear. The **label** comes from the widest member, because an address containing a name is still an address.

Every detection still gets its own outcome, in input order, with its own category, action and citation. Disjoint spans — the common case — are unaffected.

### Security

- **`sign.verify()` no longer trusts the key a token names for itself.** `allow_did_key_from_kid` defaulted to `True`, so `verify(token)` with no key fell back to decoding the public key from the token's own `kid`. Since the signer chooses `kid`, anyone could sign a payload with their own keypair, self-assert the matching `kid`, and get `valid=True` — with no way to tell from the result that nothing had been authenticated. The module docstring taught exactly that call.

**This is a breaking change, deliberately.** `verify(token)` with no `public_key` and no `resolver` now returns `valid=False` and an error naming both options. Callers who want the keyless offline path opt in with `allow_did_key_from_kid=True`.

`VerificationResult` gains two fields so the question is answerable at all: `key_source` (`"pinned"` / `"resolver"` / `"self-asserted"`) and `trusted`, which is True only for the first two. **`valid` answers "does this signature match this key"; only `trusted` answers "and did that key come from somewhere I control".** `VerifyExtractResult`, `AttestationVerifyResult` and `SDJWTVerifyResult` carry the same two fields.

`VerifyExtractWorkflow`, `verify_attestation()` and `verify_sd_jwt()` opt in explicitly, so **offline envelope verification still works exactly as documented** — a recipient with no pinned key can still check an envelope with no resolver and no network call. What changed is that the result now reports `signature_trusted=False` in that case, instead of being indistinguishable from a verified issuer.

Five regression tests now pin this contract. The suite previously had none: every signing test called the bare form, so the behaviour was asserted as correct rather than caught.

### Known issues

- **`Pipeline(address_parsing=True)` is currently a no-op** — `result.addresses` stays empty. Call `arche.addr.parse_addresses()` directly meanwhile.
- **`Pipeline` does not detect email addresses.** `arche.detect.detect_emails` works standalone but is not in the default detector chain, so emails survive redaction. Pass an explicit `detectors` list if you need them.

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

The v0.1 surface (~50 names: `extract`, `detect_pii`, `resolve_entities`, `to_html`, etc.) remains importable via PEP 562 lazy attribute access on `arche`, with `DeprecationWarning` on first use. Removed in v0.3.

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
