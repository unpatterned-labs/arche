# Place resolution at scale: two countries, 50k records, one engine

*A field guide, written the way the work actually happens. You maintain place data; it disagrees with everyone else's place data. By the end of this page you will have crosswalked Nigeria's national health-facility register against OpenStreetMap, linked the UK food-hygiene register to the map of Leeds, and deduplicated a 46,000-row national registry against itself — and you'll be able to read every number the engine gives you.*

All data is public and licensed for reuse: the [Nigeria Health Facility Register](https://data.humdata.org/dataset/nigeria-health-facilities) (eHealth Africa/NMoH via HDX, CC-BY), the [UK Food Hygiene Rating Scheme](https://ratings.food.gov.uk/open-data) (Food Standards Agency, OGL v3), and [OpenStreetMap](https://www.openstreetmap.org) via Overpass (ODbL). The runnable version is `notebooks/place_resolution_at_scale.ipynb`.

## The setup

Four datasets, one shape — a name and a coordinate is all the engine needs:

| dataset | records | source |
|---|---|---|
| Nigeria HFR (national register) | **46,146** geocoded facilities (1,561 in Kano) | HDX |
| OpenStreetMap, Kano health amenities | 165 | Overpass |
| UK FHRS, Leeds establishments | **5,799** geocoded | FSA open data |
| OpenStreetMap, Leeds food places | 1,115 | Overpass |

```python
from arche import resolve

# records are plain dicts: {"id": ..., "name": ..., "lat": ..., "lon": ...}
out = resolve.crosswalk(list_a, list_b, entity="place")
```

That one call is the whole API. `entity="place"` selects the canned place comparators (fuzzy name + token distinctiveness + geo proximity); H3 spatial blocking keeps big lists fast; the distinctive-signal gate keeps the merges safe.

## Step 0 — the trap every new user hits

Run the smallest possible example and read it carefully, because it teaches the engine's most important idea:

```text
HFR-001 <-> OSM-77  review  score=0.578  {'name': 0.837, 'name_tftoken': 0.15, 'geo': 0.949}
```

Same facility, ~60 m apart — and the engine says **`review`**. The evidence explains why: the fuzzy name comparator *does* see "Karfi Primary Health Centre" ≈ "Karfi PHC" (`name: 0.837`), the coordinates agree (`geo: 0.949`) — but `name_tftoken`, the **distinctiveness** comparator, is weak. It asks *how rare are the tokens these names share?* — and rarity is measured against a corpus. With no `tf=` supplied it self-calibrates over the records you passed, and **a two-record corpus cannot tell the engine that "Karfi" is rare**. Weak distinctive proof → the safe verdict is `review`, never a silent merge. ([Every field decoded here](../how-to/read-crosswalk-output.md).)

Hold that thought and add data.

## Step 1 — Nigeria: HFR ↔ OpenStreetMap, Kano state

```python
kano = resolve.crosswalk(hfr_kano, osm_kano, entity="place")
```

**1,561 × 165 records in 1.4 seconds:**

```text
decisions: {'match': 111, 'review': 54}
blocking:  {'candidate_pairs': 2937, 'reduction_ratio': 0.9886}
```

Reading it: of 257,565 possible pairs, H3 blocking scored only **2,937** (98.9% skipped — facilities kilometres apart can't be the same clinic). 111 pairs cleared to `match` — the clean ones are unambiguous:

```text
Gwarmai Health Post          <-> Gwarmai Health Post       1.0  {'name': 1.0, 'name_tftoken': 1.0, 'geo': 1.0}
```

And the toy example's pair, revisited with a real corpus, teaches **two** lessons:

```text
Karfi Health Post <-> Karfi Primary Health Centre  review  0.651  {'name': 0.834, 'name_tftoken': 0.465, 'geo': 0.657}
```

1. **Distinctiveness rose with the corpus** — `name_tftoken` jumped from ~0.15 to **0.47**: with 1,700 real names, "Karfi" is now measurably rare. That's exactly why the clean pairs above could clear.
2. **And this pair *should* stay in review.** The register says *Health Post*; the map says *Primary Health Centre*; they're 600 m apart. Plausibly one facility, plausibly **two different facilities in one town** — precisely the case a human must adjudicate, and precisely what the review queue is for. A tool that auto-merged it would be dangerous, not smart.

The third number is the coverage story: **only 110 of 165 OSM facilities matched confidently, and ~93% of the register has no confident map counterpart** — a *measured* coverage gap, which is itself the deliverable for mapping programmes.

## Step 2 — UK: FHRS ↔ OpenStreetMap, Leeds

Different country, different domain, different naming culture — **the identical call**:

```python
leeds = resolve.crosswalk(fhrs_leeds, osm_leeds, entity="place")
```

```text
decisions: {'match': 962, 'review': 926}
blocking:  {'candidate_pairs': 1959586, 'reduction_ratio': 0.6969}
```

962 confident links between the hygiene register and the map (`Black Sheep Coffee <-> Black Sheep Coffee 0.9999`, …). Note the blocking ratio: only ~70% skipped, versus 98.9% in Kano — **a dense city centre packs many establishments into each H3 cell**, so more neighbours must be scored. Same engine, honest cost profile per geography. This is the entity- and region-agnostic claim made concrete: nothing changed between Nigeria and the UK except the data.

## Step 3 — Scale: dedupe the full national register

The question changes — *does the 46,146-row register contain duplicate records of the same facility?* — but the engine doesn't:

```python
dd = resolve.crosswalk(hfr, hfr, entity="place", threshold=0.85)
dups = [m for m in dd["matches"] if m["a_id"] < m["b_id"] and m["decision"] == "match"]
```

```text
46,146 × 46,146 = 2.1B possible pairs
H3 blocking scored 869,078 candidate pairs (99.96% skipped) in ~3 minutes
likely duplicate records found: 177
```

The duplicates it surfaces are the kind humans miss and string-sorting never finds:

```text
Oghe Community Hospital        | Community Hospital Oghe        | Ezeagu    0.9936
Model Clinic Paiko             | Paiko Model Clinic             | Paikoro   0.99
Parklande Specialist Hospital  | Parklande Specialist Hospital  | Surulere  0.9816
```

Word-order swaps and exact re-entries — 177 registry rows that are very likely the same real-world facility twice.

## What you should take away

- **One call, three jobs, two countries.** Crosswalk, link, dedupe — only the data changed.
- **`review` is the product working.** A match requires a *distinctive* signal (a rare shared name token — never geography alone) to clear the gate; everything plausible-but-unproven is surfaced, not silently merged. On real registries, the review queue *is* the deliverable.
- **Distinctiveness needs a population.** Toy examples land in review because a 4-row corpus can't measure rarity; give the engine a real corpus (or `tf="default"` for the shipped population table) and it rewards you.
- **Scale is a blocking story.** 2.1B pairs → 869k scored. If your records have coordinates, you get this for free; without them, pass `block=None` and keep lists moderate.
- The output carries **ids and numeric evidence only — never raw values**. Rendering values (masked by default) is `arche.render`'s job.

**Next steps:** [read crosswalk output field-by-field](../how-to/read-crosswalk-output.md) · resolve *people* with signable decisions via `resolve.pairwise` (the resolution-attestation notebook) · bring your own schema with explicit `comparators=`.
