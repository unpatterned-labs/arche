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
- **`02_same_person_across_documents.ipynb`** — three PDFs, one person, with masking on by default.

Every number in this post comes from executing those notebooks.

## What we took from it

The shape of the problem is not "match more". It is:

1. **Most of it is free.** Say so, rather than charging for a dictionary.
2. **A chunk is automatable** — word order, transliteration, a dropped type suffix.
3. **A small remainder needs judgement**, and the honest job of a tool is to draw that third line accurately and hand over the evidence.

The 100 review cases are the product. They are also the part that currently costs three rounds of expert verification, and the only part anyone would pay to make faster.

---

*`arche-core` is Apache-2.0. It is pre-beta: APIs may change between alpha releases, and you should complete your own legal, privacy and security review before using it with real personal data. The facility data is CC-BY (GRID3) and ODbL (OpenStreetMap).*
