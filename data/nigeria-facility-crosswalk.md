# The same clinic, three spellings: reconciling Nigeria's health facilities in the open

*How arche matches African health-facility names that generic tools get wrong — and, just as important, when it refuses to.*

---

A country's health system runs on a Master Facility List: the canonical answer to "where are our clinics, and which record is which?" It decides where vaccines ship, how coverage is measured, and whether a results-based payment is real. And in most of the majority world it is quietly broken — not because the data doesn't exist, but because the *lists don't line up*.

The official registry says one thing. OpenStreetMap says another. The DHIS2 org-unit tree, the last survey round, the immunization program's spreadsheet — each has its own spelling, its own coordinates, its own idea of which facility is which. This is a known, funded problem: the WHO's Geolocated Health Facilities Data initiative exists to fix it, GRID3 (Gates + FCDO) is spending $20.3M on it with Nigeria and DRC in focus, and OpenHIE ships a dedicated Facility Reconciliation Tool. A peer-reviewed study in Senegal triangulated 16 datasets down to one facility list — and needed **three rounds of manual expert verification** to do it.

The hard part isn't the plumbing. It's the *matching*: deciding that "An Nur Specialist Hospital" and "Al Noury Specialist Hospital" are the same place, that "Kirya Health Post" and "Zaura Health Post" are not, and that the "RAHAMA CHEMIST" someone mapped is a pharmacy the government registry never listed. On African names, with no clean registry to anchor to, that judgement is exactly what generic tools get wrong.

## Why generic fuzzy-matching fails here

Reach for an off-the-shelf fuzzy match — token-sort similarity over the full names, a threshold, done — and you fail in both directions at once.

It **over-merges**: two "Central Dispensary" three kilometres apart share every token, so they score high and get wrongly fused. It **under-matches**: "An Nur" and "Al Noury" are the same Arabic name transliterated two ways, but character-for-character they barely overlap, so the true match is missed. And it drowns in noise: "Primary Health Centre" appears in half the names, so the shared type token inflates every score and the *distinctive* part — the place name — gets lost.

None of this is a reason to build another matching engine. Probabilistic record linkage is a solved, commodity problem; Splink (from the UK Ministry of Justice) is excellent and free. The gap isn't the engine. It's the **calibration for African data** that no generic engine ships.

## What arche does

arche is the African entity-context layer for record linkage — the comparators, vocabularies, and calibration that make an existing engine work on African names, addresses, and facilities. It plugs into Splink, DHIS2, and OpenHIE. It doesn't replace them.

For this task it does three small, honest things on top of the same Fellegi-Sunter core arche uses to resolve *people*:

1. **Strip the type, keep the name.** A vocabulary pack maps "Primary Health Centre", "Primary Health Care Centre", "Health Post", "Dispensary" (and their Nigerian variants) to canonical tokens, so the matcher compares "Karfi" against "Karfi" instead of letting a shared "Health Centre" carry the score. The same pack classifies a mislabelled "RAHAMA CHEMIST" as a pharmacy.
2. **Use geography as a supporting signal, never a crutch.** Coordinates block the search and nudge confidence — but a shared coordinate can't drag a weak name to a match. Two different facilities that happen to sit on the same GPS point stay unmatched.
3. **Calibrate the comparator to the entity class.** Facility names are compared with string similarity, *not* arche's person-name equivalence lexicon — because "the engine is shared, but the comparator is calibrated per class" is the whole idea. Treating a place like a person is how you get false matches.

Every decision is auditable: a probability, the per-factor breakdown, and a plain-English reason ("name 100%; 0.1 km apart; type match").

## The experiment: HFR vs OpenStreetMap, three states

We reconciled two **genuinely independent** public sources for three Nigerian states:

- the **Nigeria Health Facility Registry** (the official Master Facility List, via the Humanitarian Data Exchange mirror — CC BY), and
- **OpenStreetMap** health facilities via the Overpass API (ODbL) — crowd-mapped, and *not* derived from the government registry.

Independence matters. The registry is compiled partly from GRID3, so GRID3 isn't an independent check on it. OpenStreetMap is. Matching them is a real reconciliation, not a pre-merged softball.

We picked three states on purpose: **Kano** in the north (Hausa names, densely mapped), **Edo** around Benin City, and **Ondo** around Akure (both southern, different naming, sparser data). Same pipeline, no per-state tuning. The whole thing is a public-data notebook you can re-run.

## Three states, three lessons

**Kano — the clean case, and where it beats naive.** With 685 OSM facilities against 1,561 in the registry, arche auto-matched at **~99% precision** on a labelled sample. But precision alone flatters a well-mapped state. The real result is the **160 hard-name matches a token-sort baseline misses** — transliteration and spelling variants that are obvious to a human and invisible to character overlap:

```
An Nur Specialist Hospital              ==  Al Noury Specialist Hospital
Gyaranya Health Post                    ==  Geranya Health Post
Ba'Awa Health Post                      ==  Baawa Basic Health Center
Sheikh Muhammed Jidda General Hospital  ==  Sheik Jiddah General Hospital
```

(These four are *confident auto-matches*. Heavier variants — "Sambauna" ⇄ "Sanbauna", "Kofar Chiri" ⇄ "Kafir Chiri" — arche deliberately routes to review rather than auto-confirm. More on that restraint below.)

**Edo — graceful under mess.** Benin City's OpenStreetMap is dominated by *private* clinics, pharmacies, and dental practices the government registry doesn't list. So arche routed **63% of pairs to review** — "Valif Pharmacy" is near a health centre, but it isn't that health centre, and arche says so instead of inventing a match. Restraint is the product. A tool that reports a confident 90% match rate on data like this is lying to you; a tool that hands you a short review queue and a clean set of confident matches is doing the job.

**Ondo — the coverage gap *is* the finding.** After clipping OpenStreetMap to Ondo's actual administrative boundary — an earlier rectangular bounding box had bled 119 facilities in from neighbouring states, a good reminder to use admin polygons, not boxes — Ondo had **about thirteen mapped OSM health facilities for the entire state**. You cannot reconcile what nobody has mapped. That absence, not a match rate, is the honest result. It is also precisely the majority-world data-infrastructure gap that makes all of this necessary: the intelligence layer inside the world's data tools was calibrated somewhere else, and the map runs out exactly where the need is greatest.

## What we're not claiming

The number that travels isn't "99%." It's the *behaviour*: high precision where the data is clean, an honest review queue where it's messy, and a visible gap where it's absent. And a few things stated plainly, because the point of an open method is that you can check it:

- The labels behind the 99% are **analyst judgements by name and location, not a registry-expert gold standard.** A ministry or a domain expert labelling the sample is the next step to a certified number, and the sample ships with the code for exactly that.
- **Kano is the easy end.** It's unusually well-mapped. The southern states are the honest boundary of what works today.
- These are two public snapshots (the registry is ~2020, OpenStreetMap is live), so some non-matches are *time*, not naming.

## Why open, and why this matters

The matching logic here is deliberately open — the comparators, the vocabulary pack, the crosswalks, the benchmark. Open is the strategy, not charity: it's how a calibration layer becomes the default thing sitting under DHIS2, OpenHIE, and GRID3 pipelines, feeding the engines the ecosystem already runs. The maintained, verified, continuously-corrected facility graph is the part worth paying for; the code that produces it should be inspectable by everyone whose decisions depend on it.

Health facilities are one entity class. The same engine, differently calibrated, reconciles people (with the data-protection law that governs each field), organizations, and places. But the wedge is concrete: a country that can finally line up its facility lists — with an explanation and an audit trail for every match, and an honest flag on every one it can't confirm.

## Try it

Everything is public and reproducible. From the arche repo (the facility comparators — `compare_geo`, `normalize_type_token`, `load_type_vocab` — are on `main` and ship in the next `arche-core` release):

```
uv sync
uv run python notebooks/fetch_facility_data.py Kano      # + Edo, Ondo
uv run python notebooks/build_crosswalk.py Kano
uv run python notebooks/evaluate_crosswalk.py
```

The full analysis is in `notebooks/nigeria_facility_crosswalk.ipynb`. Data: Nigeria Health Facility Registry via HDX (CC BY); OpenStreetMap © OpenStreetMap contributors (ODbL).

*arche is built by [unpatterned](https://unpatterned.org) — the open entity-intelligence layer for the majority world.*
