# The same clinic, three spellings

*How much of a national facility reconciliation is actually a hard problem. Measured, on public Nigerian data, with the notebooks to reproduce it.*

---

A country's health system runs on a **Master Facility List**: the canonical answer to *where are our clinics, and which record is which?* It decides where vaccines ship, how coverage is measured, and whether a results-based payment is real.

In most of the majority world it is quietly broken. Not because the data is missing, because the lists don't line up. The official registry says one thing, GRID3 says another, OpenStreetMap a third. Each has its own spelling, its own coordinates, its own idea of which facility is which.

This is a funded, named problem. The WHO runs a Geolocated Health Facilities Data initiative for it. GRID3 is spending $20.3M with Nigeria and DRC in focus. A peer-reviewed reconciliation in Senegal triangulated 16 datasets into one list and needed **three rounds of manual expert verification** to do it.

We ran the reconciliation for one Nigerian state and measured where the work actually is. The answer surprised us, and it changed what we think the product is.

## What a broken list costs, in things that are not data

That sentence about vaccines, coverage and payment is doing a lot of work, so it is worth unpacking before the measurements start. A master facility list is not a reference document. It is the thing that decides who gets sent what.

Follow each kind of error into what it does after it leaves the spreadsheet.

| What the list gets wrong | What happens next |
|---|---|
| **One clinic recorded twice** | its allocation splits across two part-orders, and neither arrives whole |
| **One clinic recorded twice** | it counts twice in the denominator, so district coverage reads worse than it is |
| **Two clinics merged into one** | one of them stops existing administratively and is supplied for nobody |
| **A clinic in no list at all** | never allocated, never counted, never missed |
| **Coordinates wrong by kilometres** | an outreach team spends a morning at a junction |
| **Tier mislabelled** | a health post is tasked with a service it has no staff or cold chain for |

None of those is a data quality problem in the sense that phrase usually carries. Each one is a delivery that did not happen, and the last column is where the cost actually lands.

## One of these gets noticed and one does not

Look at rows one and four again, because they fail in opposite directions and only one of them generates a complaint.

**A duplicate is eventually loud.** Somebody receives two deliveries, or a finance officer queries a payment made twice for the same facility, or a supervisor visits and finds a clinic that is already stocked. It produces a query, the query produces a correction, and the correction is logged as a data fix.

**An omission is silent.** A facility absent from the master list is not under-supplied in a way that raises a ticket. It is invisible, and invisibility does not complain. The people it serves experience it as *there are never vaccines here*, which they reasonably take to be a fact about their clinic rather than a fact about a row missing from a file in Abuja.

Which produces the rule this whole reconciliation runs on:

> **The failure that nobody reports is the one that compounds.** A tool tuned only against the errors that generate complaints will get steadily better at duplicates and never learn that it is dropping facilities.

That asymmetry is also why a matcher that guesses is worse here than one that refuses. Guessing produces both failures at once: it merges clinics that are not the same, and it silently drops the pairs it could not see. Refusing produces a queue, and a queue is at least a list of things somebody can look at.

Keep the two directions in mind through the numbers below. Almost every design decision in the rest of this post is an attempt to buy down the silent one without inflating the loud one.

## The setup

Two lists for Kano State, both public:

| Source | Records | What it is |
|---|---|---|
| **GRID3** | 1,723 | Gates/FCDO-funded geospatial reference data |
| **OpenStreetMap** | 685 named | Crowd-mapped via the Overpass API |

We deliberately did **not** use Nigeria's official registry (NHFR, mirrored on HDX) as the comparison. More on why in a moment.

!!! warning "Correction, August 2026"

    An earlier version of this post called the OpenStreetMap comparison *independent validation*. It is not. OSM's health facilities for Kano carry the same lineage as GRID3, and we can now show that from the data. Every number below still holds as a **consistency check** between two views of the same territory; none of it is evidence that the matcher is right about the world. The section [Our own circularity, caught with Overture](#our-own-circularity-caught-with-overture) has the measurement, and [the place benchmark](../about/place-benchmark.md) has the test that catches it in ten lines.

## Result: most of it isn't a hard problem

Running `reconcile(osm, grid3, entity="place")` compared 1,180,255 possible pairs, blocked them down to 39,701 actually scored. A 96.6% reduction, and finished in **21 seconds on a laptop, offline**.

| Outcome | OSM records | Share |
|---|---|---|
| Resolved to a GRID3 facility | 521 | 76.1% |
| Sent to human review | 111 | 16.2% |
| No plausible candidate | 53 | 7.7% |

*(Those are the shipped v0.3.0a1 defaults. The geographic veto described below moved eleven records from the first row to the second after this post first ran.)*

And before any of that, a plain dictionary lookup on exact names already solved a large share of the list.

**Read those numbers honestly.** The majority of a reconciliation needs no product at all. Anyone selling you a platform for the exact-match segment is selling you a `dict`. The value is concentrated in one place: the boundary between "safe to merge" and "a human needs to look at this".

## Why naive matching fails in both directions at once

Reach for off-the-shelf fuzzy matching. Token-sort similarity, a threshold, done, and you fail twice.

**It over-merges.** Two `Central Dispensary` records three kilometres apart share every token, score 100, and get wrongly fused.

**It under-matches.** `An Nur` and `Al Noury` are the same Arabic name transliterated two ways. Character-for-character they barely overlap, so the true match is missed.

And a third problem hides underneath: `Health Post` appears in half the names, so the shared *type* token inflates every score while the distinctive part, the place name, gets drowned out.

A single threshold cannot fix this. Raise it and you lose the transliterations; lower it and you merge distinct clinics. The comparison has to know that `Health Post` is a type and `Tsalle` is a name.

## Distance has to be able to refuse

One thing we got wrong first time round. Geography was a *scored* signal in the place pack, weighted 1.0 against name and token-frequency's combined 4.0. A weighted signal can be outvoted, and it was: two Kano facilities sharing a common Hausa name merged **143 km apart**, with the geo comparator itself scoring 0.000. The names were confident enough to drown it out.

v0.3.0a1 adds `veto_km` to the place pack. Beyond the threshold, distance stops being a preference and becomes a constraint. Two properties are deliberate: it demotes to `review` and never to `no_match`, because distance says a human must look rather than that the answer is no; and records without usable coordinates are never vetoed, because you cannot refute a claim on evidence you do not have.

Swept against LGA agreement, which both sources record independently:

| veto | matches | same-LGA | diff-LGA | LGA agreement | matches over 10 km |
|---|---|---|---|---|---|
| none | 636 | 497 | 137 | 78.4% | 72 |
| 50 km | 594 | 481 | 110 | 81.4% | 49 |
| 25 km | 561 | 481 | 77 | 86.2% | 16 |
| **10 km** | **564** | **495** | **67** | **88.1%** | **0** |

Loosening from 10 km to 25 km buys back two same-LGA matches and lets in thirteen cross-LGA ones. That is a bad trade when a veto costs a human glance and a wrong merge costs a clinic its allocation. At the shipped setting the furthest matched pair is 8.97 km apart, and 170 pairs carry `geo_conflict_km` into the review queue as the stated reason.

It is not free. `Aminu kano teaching hospital AKTH` and `Aminu Kano Teaching Hospital` sit 10.06 km apart in one of the crosswalks, six metres over the threshold, and are obviously the same hospital. A large urban campus can be recorded at its gate, its main block or its administrative address, and a threshold tuned on rural point features is the wrong shape for that. We have not fixed it, and we would rather say so than quietly widen the threshold around one example.

## The records that matter

Here is what arche scored well and **still refused to merge**:

| OSM | GRID3 | Distance | Score |
|---|---|---|---|
| Gurduba Health Post | Gurduba Primary Health Care | 0.38 km | 0.698 |
| Lambu Primary Health Centre | Lambu Basic Health Center | 0.04 km | 0.695 |
| Dawaki General Hospital | Dawakin Kudu General Hospital | 0.02 km | 0.693 |
| Tsalle Health Post | Tsalle Primary Health Care Center | 0.00 km | 0.691 |
| Jibga Fulani Health Post | Jibga Health Post | 2.64 km | 0.686 |

Every one of these has a fluent, confident, wrong answer available:

- A **health post** and a **primary health care centre** are different tiers of care, with different staffing and different vaccine allocations.
- **Dawakin Kudu** is a different Local Government Area from **Dawaki**. Twenty metres apart on the map, different administrative units on paper.
- **Jibga Fulani Health Post** may serve a distinct community from **Jibga Health Post**, and they sit 2.6 km apart.

A system optimising for match rate merges all five and looks excellent on a dashboard. In a Master Facility List, a wrong merge is not a lower score. **it is a clinic disappearing from the national list and losing its allocation.**

`review` is not the system failing. It is the system telling you exactly where a human is genuinely required, and there are far fewer of those than the raw residue suggested: 111 records, not 685.

## A finding about GRID3 and HDX

We originally intended to compare GRID3 against Nigeria's official registry as mirrored on the Humanitarian Data Exchange. One measurement stopped us.

**34,541 of GRID3's 51,022 national records. 68%. Carry `facility_name_source: NHFR_2024`.** In Kano it is 1,426 of 1,723, and every one of those also carries an `nhfr_facility_code`.

NHFR is the Nigeria Health Facility Registry: the thing HDX mirrors. GRID3's names largely *come from* the registry, and the registry is compiled partly from GRID3. Comparing the two measures agreement between two views with a shared ancestor, not independent validation. Where both sides carry the same facility code, it isn't entity resolution at all; it's a key join.

That has a practical consequence worth stating plainly: **"GRID3 is the master data" is a governance claim, not a technical one.** Which list wins when they disagree belongs to the ministry, not the matcher. What a reconciliation engine can honestly supply is the disagreement itself. Kept rather than erased, with the evidence attached.

OpenStreetMap is crowd-mapped, so we used it instead. That was the mistake.

## Our own circularity, caught with Overture

We found the GRID3/HDX problem, wrote it up, and then failed to apply the same question to our own replacement. Here is the measurement we should have run first, and it takes two lines.

Take the pairs the matcher agreed on and look at the distance between their coordinates. Independent field surveys of the same building do not agree exactly. Handheld GPS error is 3 to 10 metres in good conditions, worse under tree cover or beside a wall. Two teams, two devices, two visits, and you expect tens of metres of disagreement, distributed.

**The GRID3 × OSM matches have a median separation of 0.000 km, and 332 of 564 of them, 59%, are at exactly zero.** No pair of independent surveys produces that. OSM's health facilities for Kano were imported from the same lineage as GRID3, most likely the registry both draw on.

To check that rather than infer it, we pulled Overture Maps, which publishes per-feature source lineage. Of its 358 named health places in the Kano bounding box: **354 from Meta, 3 from Microsoft, 1 from Foursquare. Zero OpenStreetMap, zero GRID3, zero NHFR.** Independence stated in the data instead of assumed.

Running the identical crosswalk against both sources gives two completely different signatures:

| | OpenStreetMap | Overture |
|---|---|---|
| records | 685 | 358 |
| matched | 521 | 37 |
| coverage | 76.1% | 10.3% |
| median distance | 0.000 km | 0.050 km |
| at exactly 0.00 km | 319 (59%) | 3 (8%) |

The genuinely independent source agrees on **fewer** facilities and agrees **less precisely** about where they are. That is not the matcher performing worse. It is what honest disagreement between two observations looks like.

Which means the 88.1% figure in the veto sweep above is a **consistency check, not validation.** It is a sound basis for choosing a threshold. It is not evidence that the matcher is right about the world, and the earlier version of this post said it was.

The coverage gap is a finding rather than a defect. GRID3 is overwhelmingly rural primary health centres and health posts; Meta's place data covers named, signed, commercial facilities, which skews urban. An independent source can validate the urban tier and says almost nothing about the rural network, which is exactly where a national facility list matters most. Knowing that is more useful than a precision score.

The full method, the caveats, and a `looks_derived()` helper you can point at any two datasets are in the place benchmark.

## The same engine, applied to people

Facilities are one entity type. The second notebook runs the identical gate over three unrelated PDFs. A bank statement, a payslip, and an invoice from three organisations that never coordinated on a format.

All three describe one person. No shared customer number, no national ID, the same address written in three different field orders, and a middle name present in one document and dropped in the others.

Every pair came back **`review`**, with `address = 1.00` but name similarity between 0.54 and 0.80.

That is the correct answer. A bank that auto-merges two customer records on name and address alone will eventually show one person another person's transactions, which under GDPR is a reportable breach. The system that says *"very likely, but look at this one"* is the one you want holding that decision.

## So can a frontier model just do this?

We ran it rather than arguing about it. Thirty pairs sampled from the crosswalk with a fixed seed. 15 arche called `match`, 15 it sent to `review`. Put to `gpt-4o-mini` with both names, both coordinates, the distance, and the stakes spelled out. The results were not what we expected.

**The model is genuinely better than arche at one thing.** It correctly merged four pairs arche refused, all of them Hausa word-boundary variants: `Sarigarin` / `Sari Girin`, `Maitsidau` / `Mai Tsidau`, `Riruwai` / `Ririwai`. At identical coordinates these are the same facility. arche's comparator treats a space as a token boundary, so the shared name contributes nothing and the distinctiveness gate never fires. **That is a real gap in arche, found by running this comparison**, and it's a data fix for the place pack, not an architectural one.

We shipped that fix. `resolve/_data/orthography.yaml` is an inspectable Hausa rule pack: adjacent-token boundary collapsing, nasal assimilation (`n` becomes `m` before `b` or `p`), and ten curated equivalence groups. Threaded through the Kano crosswalk it promotes **13 pairs from `review` to `match` with zero demotions and no edge's score falling**. `Yangwarzo` / `Yan Gwarzo`, `Kafinmaiko` / `Kafin Maiko`, `Sanbauna` / `Sambauna`, `Unguwar Malam Amadu` / `Unguwar Mallam Ahmadu`. It is additive by construction, taking `max(literal, keyed)`, because the first version computed the similarity over keys *instead of* literal tokens and that recovered 13 pairs while demoting 79.

Note which of the model's four wins are *not* in that list. `Riruwai` / `Ririwai` and `Sarigarin` / `Sari Girin` are vowel alternations, and they are recorded in the YAML under `known_gaps` and deliberately left unhandled. Whether `gari` and `girin` are one morpheme with a vowel alternation or two words is a question about Hausa, not about string distance, and a rule loose enough to fold those vowels would also merge genuinely distinct settlement names. That needs a Hausa speaker. The model guessed and happened to be right; we would rather write the gap down than guess with it.

**And it fails in a way no amount of scale fixes.** On five pairs with *identical facility names at essentially identical coordinates*, the model returned `unsure` or `different`. One of them at 0.90 confidence:

| arche | LLM | Pair | Distance |
|---|---|---|---|
| match 1.000 | **different** (0.90) | Alfindi Health Post vs Alfindi Health Post | 0.00 km |
| match 1.000 | unsure (0.80) | Kurugu Health Post vs Kurugu Health Post | 0.00 km |
| match 0.998 | unsure (0.70) | Yanchibi Health Post vs Yanchibi Health Post | 0.02 km |

There is no reading of the evidence under which those are different facilities. The model invented a distinction because it was asked a question, and producing an answer is what it does. Its confidence score carried no signal that these verdicts were less reliable than any other.

It also **never once hedged** on the review set. Every pair arche declined to decide got a confident verdict.

And it isn't a stable function. Asked the same question five times at `temperature = 0`, it gave **two different answers**. arche returned the same content-addressed `decision_id` all five times. You cannot attest what you cannot replay.

### Which implies an architecture, not a winner

Neither should be the whole system:

1. **arche blocks and gates**. 1.2M possible pairs down to 40k scored, the unambiguous majority resolved deterministically, the rest refused. Nothing expensive has happened yet.
2. **The review queue routes to the model**. ~111 pairs, not 40,000. Asked only where a human would otherwise be needed, and its recall on name variants is exactly what helps there.
3. **The model proposes; it never merges.** Its verdict is evidence with a measured reliability, not a decision.
4. **A human confirms**, and the adjudication is signed.

The cost difference is the argument for that ordering. At the measured 164 tokens per pair, running a mid-tier model over every pair in a national crosswalk is **$68,107**. Running it over the review queue only is **$9,944**, and a cheap model on the queue is under $500. The deterministic gate is what makes the expensive, non-replayable component affordable to use at all.

## Two things the notebooks show that we would rather they didn't

Both are real, both are in the shipped release, and both are documented as known issues.

**Jurisdiction is not cosmetic.** Running a UK bank statement through the Nigerian statute pack reported dozens of `PII-2-TIN` detections. Nigerian Tax Identification Numbers that were really transaction reference numbers matching the same shape. Switching to the GDPR pack made them vanish. A detector without a jurisdiction is a regex with opinions.

**Check what your redaction missed.** On a test sentence containing a name and an email address, `Pipeline.process()` returned zero detections and handed back the input unchanged. `detect_emails()` finds the address perfectly on its own. It simply isn't in `Pipeline`'s default detector chain in v0.3.0a1. The habit that catches this in seconds: print the detections. If the list is empty, nothing was redacted.

We would rather publish that than have you find it.

## Reproduce it

Both notebooks run offline on data already in the repository. No API key, no network call, no model download.

```bash
git clone https://github.com/unpatterned-labs/arche
cd arche && uv sync
jupyter lab examples/notebooks/
```

- **`01_facility_reconciliation.ipynb`**. The GRID3 × OpenStreetMap crosswalk above, step by step, written for someone who has never done entity resolution. Exports the review queue as CSV.
- **`02_same_person_across_documents.ipynb`**. Three PDFs, one person, using docling for layout-aware extraction and GLiNER for entity recognition. Masking on by default.
- **`03_llm_vs_arche.ipynb`**. The head-to-head above. Needs `OPENAI_API_KEY` in `.env` and costs a few cents.

Every number in this post is reproducible from this repository. The notebooks cover the crosswalk, the person case and the head-to-head; the veto sweep, the orthography measurement and the independence test are scripts you can paste from the place benchmark, which also runs offline apart from the Overture pull.

### A note on the document stack

Notebook 2 measures `docling` against a plain text-layer extractor on the same file: **28,927 characters in 98 seconds versus 16,520 in 0.1 seconds.** docling reconstructs table structure rather than reading the text layer in storage order, which is why it recovers 75% more from a payslip. Use it when the document has structure you need. Statements, invoices, payslips, forms, and a text-layer extractor when you only need prose.

For names, `arche-core[detect]` (GLiNER) separates `PERSON` from `ORGANIZATION` at 0.99 confidence on these documents. A layout heuristic cannot: `United States` and `Pay Summary` are shaped exactly like a name, and no amount of regex tuning fixes that. The notebook shows the heuristic failing first, because the failure is the argument for the model.

## What we took from it

The shape of the problem is not "match more". It is:

1. **Most of it is free.** Say so, rather than charging for a dictionary.
2. **A chunk is automatable**. Word order, transliteration, a dropped type suffix.
3. **A small remainder needs judgement**, and the honest job of a tool is to draw that third line accurately and hand over the evidence.

The 111 review cases are the product. They are also the part that currently costs three rounds of expert verification, and the only part anyone would pay to make faster.

And a fourth, which we learned by getting it wrong: **check where your validation source came from before you quote a number off it.** We spotted the circularity in GRID3 versus HDX, published that finding, and then benchmarked against a source with the same problem. Two lines of arithmetic on the matched distances would have caught it. They now live in the place benchmark, and running them on our own work is the only reason this post has a correction rather than a claim.

---

*`arche-core` is Apache-2.0. It is pre-beta: APIs may change between alpha releases, and you should complete your own legal, privacy and security review before using it with real personal data. The facility data is CC-BY (GRID3) and ODbL (OpenStreetMap); Overture Maps place data is CDLA-Permissive-2.0 with Foursquare rows under Apache-2.0.*

## Acknowledgements

This problem was identified, funded and worked on by other people long before we touched it.

The WHO's Geolocated Health Facilities Data initiative exists to fix exactly this. [GRID3](https://grid3.org/) has spent substantial Gates and FCDO funding on Nigerian and DRC facility data, and their published lists are what made this work possible. [OpenHIE](https://ohie.org/) ships a dedicated Facility Reconciliation Tool, which is prior art for the workflow rather than a competitor to it.

[OpenStreetMap](https://www.openstreetmap.org/) contributors mapped the facilities on the other side of every comparison here, voluntarily.

[Splink](https://moj-analytical-services.github.io/splink/) is excellent, free, and the right tool if your problem is the inference half. The gap this post is about is calibration data, not estimation.

## Notes

1. The consequence table is structural rather than a record of specific incidents. Each row is what a duplicate, an omission or a bad coordinate does to an allocation process, not a claim that a named facility suffered it on a named date.
2. The labels behind the accuracy figures are analyst judgements by name and location, not a registry-expert gold standard. A ministry or a domain expert adjudicating the sample is the step that would turn these into certified numbers, and the sample ships with the code so that is possible.
3. Kano and London report recall, not a false-merge rate, because neither has a complete mapping. When a benchmark with complete ground truth first arrived, measured precision was 0.85 against the ~0.95 the recall figures had implied.
4. Restraint is the result worth quoting from this work, not the headline percentage. A tool reporting a confident 90% match rate on Edo's data would be lying.
