# The same clinic, three spellings

*How much of a national facility reconciliation is actually a hard problem — measured, on public Nigerian data, with the notebooks to reproduce it.*

---

A country's health system runs on a **Master Facility List**: the canonical answer to *where are our clinics, and which record is which?* It decides where vaccines ship, how coverage is measured, and whether a results-based payment is real.

In most of the majority world it is quietly broken. Not because the data is missing — because the lists don't line up. The official registry says one thing, GRID3 says another, OpenStreetMap a third. Each has its own spelling, its own coordinates, its own idea of which facility is which.

This is a funded, named problem. The WHO runs a Geolocated Health Facilities Data initiative for it. GRID3 is spending $20.3M with Nigeria and DRC in focus. A peer-reviewed reconciliation in Senegal triangulated 16 datasets into one list and needed **three rounds of manual expert verification** to do it.

We ran the reconciliation for one Nigerian state and measured where the work actually is. The answer surprised us, and it changed what we think the product is.

## The setup

Two lists for Kano State, both public:

| Source | Records | What it is |
|---|---|---|
| **GRID3** | 1,723 | Gates/FCDO-funded geospatial reference data |
| **OpenStreetMap** | 685 named | Crowd-mapped via the Overpass API |

We deliberately did **not** use Nigeria's official registry (NHFR, mirrored on HDX) as the comparison. More on why in a moment.

## Result: most of it isn't a hard problem

Running `crosswalk(osm, grid3, entity="place")` compared 1,180,255 possible pairs, blocked them down to 39,701 actually scored — a 96.6% reduction — and finished in **21 seconds on a laptop, offline**.

| Outcome | OSM records | Share |
|---|---|---|
| Resolved to a GRID3 facility | 532 | 77.7% |
| Sent to human review | 100 | 14.6% |
| No plausible candidate | 53 | 7.7% |

And before any of that, a plain dictionary lookup on exact names already solved a large share of the list.

**Read those numbers honestly.** The majority of a reconciliation needs no product at all. Anyone selling you a platform for the exact-match segment is selling you a `dict`. The value is concentrated in one place: the boundary between "safe to merge" and "a human needs to look at this".

## Why naive matching fails in both directions at once

Reach for off-the-shelf fuzzy matching — token-sort similarity, a threshold, done — and you fail twice.

**It over-merges.** Two `Central Dispensary` records three kilometres apart share every token, score 100, and get wrongly fused.

**It under-matches.** `An Nur` and `Al Noury` are the same Arabic name transliterated two ways. Character-for-character they barely overlap, so the true match is missed.

And a third problem hides underneath: `Health Post` appears in half the names, so the shared *type* token inflates every score while the distinctive part — the place name — gets drowned out.

A single threshold cannot fix this. Raise it and you lose the transliterations; lower it and you merge distinct clinics. The comparison has to know that `Health Post` is a type and `Tsalle` is a name.

## The 100 records that matter

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
- **Dawakin Kudu** is a different Local Government Area from **Dawaki** — twenty metres apart on the map, different administrative units on paper.
- **Jibga Fulani Health Post** may serve a distinct community from **Jibga Health Post**, and they sit 2.6 km apart.

A system optimising for match rate merges all five and looks excellent on a dashboard. In a Master Facility List, a wrong merge is not a lower score — **it is a clinic disappearing from the national list and losing its allocation.**

`review` is not the system failing. It is the system telling you exactly where a human is genuinely required, and there are far fewer of those than the raw residue suggested: 100 records, not 685.

## A finding about GRID3 and HDX

We originally intended to compare GRID3 against Nigeria's official registry as mirrored on the Humanitarian Data Exchange. One measurement stopped us.

**34,541 of GRID3's 51,022 national records — 68% — carry `facility_name_source: NHFR_2024`.** In Kano it is 1,426 of 1,723, and every one of those also carries an `nhfr_facility_code`.

NHFR is the Nigeria Health Facility Registry: the thing HDX mirrors. GRID3's names largely *come from* the registry, and the registry is compiled partly from GRID3. Comparing the two measures agreement between two views with a shared ancestor — not independent validation. Where both sides carry the same facility code, it isn't entity resolution at all; it's a key join.

That has a practical consequence worth stating plainly: **"GRID3 is the master data" is a governance claim, not a technical one.** Which list wins when they disagree belongs to the ministry, not the matcher. What a reconciliation engine can honestly supply is the disagreement itself — kept rather than erased, with the evidence attached.

OpenStreetMap is crowd-mapped and not derived from the registry, which is why the numbers above use it.

## The same engine, applied to people

Facilities are one entity type. The second notebook runs the identical gate over three unrelated PDFs — a bank statement, a payslip, and an invoice from three organisations that never coordinated on a format.

All three describe one person. No shared customer number, no national ID, the same address written in three different field orders, and a middle name present in one document and dropped in the others.

Every pair came back **`review`**, with `address = 1.00` but name similarity between 0.54 and 0.80.

That is the correct answer. A bank that auto-merges two customer records on name and address alone will eventually show one person another person's transactions — which under GDPR is a reportable breach. The system that says *"very likely, but look at this one"* is the one you want holding that decision.

## So can a frontier model just do this?

We ran it rather than arguing about it. Thirty pairs sampled from the crosswalk
with a fixed seed — 15 arche called `match`, 15 it sent to `review` — put to
`gpt-4o-mini` with both names, both coordinates, the distance, and the stakes
spelled out. The results were not what we expected.

**The model is genuinely better than arche at one thing.** It correctly merged
four pairs arche refused, all of them Hausa word-boundary variants:
`Sarigarin` / `Sari Girin`, `Maitsidau` / `Mai Tsidau`, `Riruwai` / `Ririwai`.
At identical coordinates these are the same facility. arche's comparator treats
a space as a token boundary, so the shared name contributes nothing and the
distinctiveness gate never fires. **That is a real gap in arche, found by
running this comparison** — and it's a data fix for the place pack, not an
architectural one.

**And it fails in a way no amount of scale fixes.** On five pairs with
*identical facility names at essentially identical coordinates*, the model
returned `unsure` or `different` — one of them at 0.90 confidence:

| arche | LLM | Pair | Distance |
|---|---|---|---|
| match 1.000 | **different** (0.90) | Alfindi Health Post vs Alfindi Health Post | 0.00 km |
| match 1.000 | unsure (0.80) | Kurugu Health Post vs Kurugu Health Post | 0.00 km |
| match 0.998 | unsure (0.70) | Yanchibi Health Post vs Yanchibi Health Post | 0.02 km |

There is no reading of the evidence under which those are different
facilities. The model invented a distinction because it was asked a question,
and producing an answer is what it does. Its confidence score carried no signal
that these verdicts were less reliable than any other.

It also **never once hedged** on the review set. Every pair arche declined to
decide got a confident verdict.

And it isn't a stable function. Asked the same question five times at
`temperature = 0`, it gave **two different answers**. arche returned the same
content-addressed `decision_id` all five times. You cannot attest what you
cannot replay.

### Which implies an architecture, not a winner

Neither should be the whole system:

1. **arche blocks and gates** — 1.2M possible pairs down to 40k scored, the
   unambiguous majority resolved deterministically, the rest refused. Nothing
   expensive has happened yet.
2. **The review queue routes to the model** — ~100 pairs, not 40,000. Asked
   only where a human would otherwise be needed, and its recall on name
   variants is exactly what helps there.
3. **The model proposes; it never merges.** Its verdict is evidence with a
   measured reliability, not a decision.
4. **A human confirms**, and the adjudication is signed.

The cost difference is the argument for that ordering. At the measured 164
tokens per pair, running a mid-tier model over every pair in a national
crosswalk is **$68,107**. Running it over the review queue only is **$9,944** —
and a cheap model on the queue is under $500. The deterministic gate is what
makes the expensive, non-replayable component affordable to use at all.

## Two things the notebooks show that we would rather they didn't

Both are real, both are in the shipped release, and both are documented as known issues.

**Jurisdiction is not cosmetic.** Running a UK bank statement through the Nigerian statute pack reported dozens of `PII-2-TIN` detections — Nigerian Tax Identification Numbers that were really transaction reference numbers matching the same shape. Switching to the GDPR pack made them vanish. A detector without a jurisdiction is a regex with opinions.

**Check what your redaction missed.** On a test sentence containing a name and an email address, `Pipeline.process()` returned zero detections and handed back the input unchanged. `detect_emails()` finds the address perfectly on its own — it simply isn't in `Pipeline`'s default detector chain in v0.3.0a1. The habit that catches this in seconds: print the detections. If the list is empty, nothing was redacted.

We would rather publish that than have you find it.

## Reproduce it

Both notebooks run offline on data already in the repository. No API key, no network call, no model download.

```bash
git clone https://github.com/unpatterned-labs/arche
cd arche && uv sync
jupyter lab examples/notebooks/
```

- **`01_facility_reconciliation.ipynb`** — the GRID3 × OpenStreetMap crosswalk above, step by step, written for someone who has never done entity resolution. Exports the review queue as CSV.
- **`02_same_person_across_documents.ipynb`** — three PDFs, one person, using docling for layout-aware extraction and GLiNER for entity recognition. Masking on by default.
- **`03_llm_vs_arche.ipynb`** — the head-to-head above. Needs `OPENAI_API_KEY` in `.env` and costs a few cents.

Every number in this post comes from executing those notebooks.

### A note on the document stack

Notebook 2 measures `docling` against a plain text-layer extractor on the same
file: **28,927 characters in 98 seconds versus 16,520 in 0.1 seconds.** docling
reconstructs table structure rather than reading the text layer in storage
order, which is why it recovers 75% more from a payslip. Use it when the
document has structure you need — statements, invoices, payslips, forms — and a
text-layer extractor when you only need prose.

For names, `arche-core[detect]` (GLiNER) separates `PERSON` from
`ORGANIZATION` at 0.99 confidence on these documents. A layout heuristic
cannot: `United States` and `Pay Summary` are shaped exactly like a name, and
no amount of regex tuning fixes that. The notebook shows the heuristic failing
first, because the failure is the argument for the model.

## What we took from it

The shape of the problem is not "match more". It is:

1. **Most of it is free.** Say so, rather than charging for a dictionary.
2. **A chunk is automatable** — word order, transliteration, a dropped type suffix.
3. **A small remainder needs judgement**, and the honest job of a tool is to draw that third line accurately and hand over the evidence.

The 100 review cases are the product. They are also the part that currently costs three rounds of expert verification, and the only part anyone would pay to make faster.

---

*`arche-core` is Apache-2.0. It is pre-beta: APIs may change between alpha releases, and you should complete your own legal, privacy and security review before using it with real personal data. The facility data is CC-BY (GRID3) and ODbL (OpenStreetMap).*
