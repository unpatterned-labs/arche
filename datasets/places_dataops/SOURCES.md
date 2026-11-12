# Place frequency table — sources and attribution

`packages/arche-core/src/arche/resolve/_data/place_frequencies.json.gz` is a
derived work. Every source below is CC0, CC-BY, or CC-BY-IGO, and **attribution
is a condition of the licence, not a courtesy**. The same list is embedded in
the artefact's own `provenance` block, so it travels with the file.

Rebuild: `python datasets/places_dataops/build_place_frequencies.py`

**`--prune-min` now defaults to 3, which is what the committed artefact was always built with.** Measured 2026-11-09: from the same source cache and the same strata, the builder at the old default of 2 produces 374,089 tokens and a 2.3 MB table, where the committed `place_frequencies.json.gz` holds 160,373 and 1.2 MB. At 3 it reproduces that file exactly — stamp `sha256:c94f20a1c2dfba18`, counts and curated block identical.

That mattered more than wheel size. The rebuild command above takes no flags, so running it as documented silently produced a *different* table under a different `version`, and that stamp travels into `pins` and therefore into `decision_id`. Anyone who rebuilt from the documented command got decision ids that did not correspond to the shipped table, with nothing to indicate it. The default now matches the artefact, and the one-line command reproduces it; verified.

## Sources

| Source | Licence | What it contributes |
|---|---|---|
| [GeoNames](https://download.geonames.org/export/dump/) per-country dumps (20 countries) | CC-BY-4.0 | Settlement names — the vocabulary that makes distinctive residuals rare — plus the sparse facility feature codes |
| [Wikidata](https://query.wikidata.org/) via SPARQL, by entity class | CC0-1.0 | Hospitals, clinics, health centres, doctors' surgeries, substations, power stations, solar and wind farms, schools, universities. The only source that can be asked for a *class* of place in a given country |
| [WRI Global Power Plant Database](https://github.com/wri/global-power-plant-database) | CC-BY-4.0 | ~34,900 power plants across 167 countries |
| [GRID3 NGA Health Facilities v2.0](https://doi.org/10.7916/kv1n-0743) (CIESIN, Columbia University, 2024) | CC-BY-4.0 | 51,022 Nigerian facilities, 37 states. Superseded upstream by v4.0, which is **not vendored and not yet a stratum** — see "Adopting GRID3 v4.0 is a separate change" |
| Nigeria Health Facility Registry (Kano, Edo, Ondo) via [HDX](https://data.humdata.org/dataset/nigeria-health-facilities) | CC-BY | Registry naming conventions and alternate names |

Countries in the GeoNames stratum: GB, IE, NG, GH, SN, CI, CM, KE, TZ, UG, RW,
ET, ZA, ZM, ZW, MW, EG, MA, IN, BR.

Per-file attribution for the GRID3 release in `data/`, including the citation CC BY requires, is in `data/GRID3_NGA_health_facilities_SOURCES.md`. That file also carries the attribution and fetch recipe for v4.0.

## Adopting GRID3 v4.0 is a separate change

CIESIN superseded v2.0 with [v4.0](https://doi.org/10.7916/pjpv-9q55) — 70,235 facilities against 51,022. The data is deliberately **not** vendored here and no builder reads it: 21.6 MB of CSV that nothing loads would sit in git history permanently, so it arrives with the change that reads it. `data/GRID3_NGA_health_facilities_SOURCES.md` holds the attribution and a fetch recipe that reproduces the exact file these measurements were taken from. The analysis below is the work already done, so that the change, when it is made, is one deliberate step rather than a rediscovery.

**It should replace v2.0, not join it.** The obvious move on a new release is to add it as another stratum, and that would be wrong: the two releases are not independent corpora. 44,941 of v2.0's 51,022 records are carried into v4.0 as the same facilities, so running both hands one source two full-mass strata in a merge that exists precisely to stop one corpus setting the vocabulary. The "Nigerian health registries alone" failure recorded under "How the merge works" is the same bug, and this is the shape it would come back in.

**Replacement costs almost nothing measurable.** Against v2.0, v4.0's `facility_name` column adds **8,897 distinct tokens** and **+37.6% occurrence mass**. It drops 2,909 of v2.0's 32,114 distinct tokens, but those carry **1.65% of v2.0's occurrence mass**, only 11 of them occur 5 times or more and 3 occur 10 times or more — and reading the list is enough: `prmary`, `cent`, `ernal`, `mayernity`, `medcenter`, `hearth`, `convolescence`, `quaters`. They are the misspellings v4.0's name-cleaning step corrected, and `--prune-min` would drop most of them anyway.

The 27,068 whole *names* present in v2.0 and absent from v4.0 look alarming and are not, for the same reason: this table counts tokens, and respelling a name changes the name without changing the vocabulary.

**`alt_name` must not be read.** v4.0 ships a second name column and it is unusable: of 28,188 non-empty values, 24,989 are the strings `Yes` or `No`, 214 are the ownership values `Private`/`Public` leaked from another column, and most of the ~2,800 remainder are generic facility types rather than alternate names. Feeding it in would make `no` and `yes` common place tokens.

What adoption buys beyond vocabulary: FCT coverage goes 652 → 1,047; `state_standard`/`lga_standard`/`ward_standard` carry standardised admin names; and `unique_id` is a **stable** key — every `grid3v2_` token in a 2,000-record sample of v3.0 reappears unchanged in v4.0, so a v4→v5 crosswalk will exist, which v2.0's `globalid` never offered.

### What the rebuild will cost, measured rather than guessed

The swap was built and measured on 2026-11-09, `--offline` against this cache so the GeoNames, Wikidata and WRI strata stay byte-identical and the whole difference is attributable to GRID3. The resulting tables were **not** kept. What they did:

- `place_frequencies.json.gz` → 162,203 tokens, stamp `sha256:594bba92bdbe3370`; `place_bigrams.json.gz` → 60,573 phrases, stamp `sha256:8ebd745a7b2f0a8e`.
- The scores barely move and nothing crosses a gate. No generic token moved more than 0.017, the highest sits at 0.6146 against the 0.75 floor, and no distinctive residual fell below it. Every phrase-table figure moved by at most 0.006. Across the suite, no test asserting a *verdict* changed.
- But both stamps travel into `decision_id`, and **six tests and six docs-site pages quote the old figures as prose**: `0.564` → `0.565`, `0.927` → `0.929`, `0.6373` → `0.6367`. `test_similarity_vs_distinctiveness.py` says in its own header that it should break loudly rather than assert numbers the engine no longer produces, so that breakage is the guard working and the documents are what need updating. `CHANGELOG.md` records `place sha256:c94f20a1c2dfba18` as untouched; that entry is history and wants superseding, not editing.
- One of those is not a number. `TestAnUnseenTokenIsAssumedRare` moves 0.860 → **1.0** because v4.0 contains a facility named *"Bidems Victory Hopsital."*, so `hopsital` becomes a **measured** token where it used to be unseen. The test exists to document that an unseen token is assumed rare; that case now demonstrates measured-rare instead, which needs a decision about what the test should say rather than a new constant.

That is why the adoption is its own change: there the doc updates are the point of the diff, not collateral.

### v2.0 is not going anywhere

Whatever happens to the stratum, the file stays on disk. It is pinned by two recorded benchmark results, one of them by sha256, and `data/GRID3_NGA_health_facilities_SOURCES.md` says which.

## The adjudicated duplicate set that cannot be used

v4.0 is a harmonised layer, and `input_data_record_ids` names the input records merged into each facility. 37,611 facilities (53.55%) merge two or more. Of those, **1,371 merge two or more records from inside `grid3v2` alone** — the register this table is built from — covering 2,814 v2.0 rows and implying 1,523 same-source duplicate pairs. That reads like a gift: a duplicate set adjudicated by the publisher, over records arche already ships, which is exactly what a place-lane benchmark is short of.

It cannot be used, and the reason is worth recording so nobody spends a second week on it.

**The ids are random by construction.** Release notes §2.2: *"A unique identifier was created by combining the source data acronym (e.g. `nphcda`) with a randomly generated 10-character alphanumeric string."* They are minted during harmonisation and no column of v2.0 derives them. Checked rather than taken on trust: the 155,330 observed tokens are uniform over `0-9A-F` to within 0.4%, and no hash of any v2.0 field reproduces one — 15 field variants against 11 digest functions in both hex cases, 0 hits in 4,000 records.

**The fallbacks do not reach either.** `nhfr_facility_code` is carried by **2** of the 1,371 merge groups. Coordinates do better but not enough: only 435 groups (31.7%) have a coordinate that matches exactly one v2.0 row, and a merged facility keeps only *one* set of coordinates, so even those 435 identify the surviving record and never its absorbed partner. Forcing the partner by elimination within a (state, LGA) cell works in **3** of 543 cells; the median cell offers 29 candidate rows, and in 34 cells there are fewer unmatched rows than partners needed, which says the elimination model is unsound there rather than merely ambiguous.

**And the circularity is the real barrier, not the ids.** Picking which second v2.0 row joined each group means matching on name and geography — which is the thing a benchmark is supposed to adjudicate. Labels produced that way cannot falsify the matcher that produced them, which is the principle `data/er_bench/places/SOURCES.md` already states. The same argument disposes of the other registers: GRID3 publishes the harmonised output and the minted input ids, but never the input records keyed by those ids, so no source's merge groups can be turned into labelled pairs.

What v4.0 *does* offer is weaker and honest about it: `flag1`..`flag6` mark roughly 11,000 records as clustering with another point within 50 m or 100 m, and both members are present in v4.0 with full attributes. That is proximity, not adjudicated identity — candidate generation, not ground truth.

## What is deliberately excluded

**OpenStreetMap.** ODbL's share-alike would propagate into this derived
database and encumber the pack, which is exactly what the provenance firewall
(`arche.adapters._evidence.may_enter_packs`) exists to prevent. OSM is still
used as *evidence* in benchmarks; it never enters a shipped asset.

Also excluded, and worth recording so nobody re-litigates them:

- **World-POI** (arXiv:2510.21342) — CC-BY-NC-SA-4.0, non-commercial.
- **GeoLM** — CC-BY-NC-2.0.
- **FSQ OS Places** — Apache-2.0 on the data, but access is now gated behind
  sharing contact details and permitting marketing use of your organisation's
  name and logo.
- **Overture Places** — CDLA-Permissive-2.0 / Apache-2.0 and genuinely suitable
  (it contains no OSM data, so no share-alike), but neither licence class
  exists in `LICENCE_CLASSES` today, so the firewall classifies it `unknown`
  and refuses it. Adding those two classes would unblock the best remaining
  source for this table.

## How an abbreviation is priced

An abbreviation names a **concept**, so the builder counts that concept across
the corpus under *both* spellings — the expansion as a contiguous phrase and
the abbreviation as a token — sums them into one canonical descriptor, and
gives the abbreviation that frequency.

The rule this replaced took the *minimum over the expansion's token counts*,
which was wrong in a way worth recording: a generic phrase containing one
uncommon word handed its abbreviation that word's rarity, so `HEP` for "hydro
electric power" would have read as distinctive enough to merge on.

Two abbreviations may share an expansion — `ctr` and `cntr` are both "centre" —
and an occurrence of the phrase credits every descriptor that claims it. The
first implementation mapped a phrase to a single descriptor, which let whichever
entry parsed last take the whole count while the other stayed rare. Both now
land at 0.41.

Where the corpus cannot supply enough evidence, the entry is reported rather
than assigned a near-zero frequency that would read as rare. See "Known gaps".

## How the merge works

Each source is counted as its own stratum, then all strata are scaled to equal
mass before summing. Without that step the largest stratum sets the vocabulary
and a smaller one's generic words keep reading as rare — which is the bug this
table exists to fix, relocated rather than removed. It is visible in the build:
with Nigerian health registries alone, UK `surgery` scored 0.80 and
`substation` 0.95, both above the 0.75 distinctiveness floor.

Pruning drops tokens seen fewer than `--prune-min` times, counted on *raw*
occurrence across strata rather than scaled mass, so a rare token from a small
stratum is not preferentially discarded.

## Known gaps

- **Four descriptors could not be priced from the corpus** and are asserted as
  generic instead: `chc`, `mch`, `nhs`, `hep`. The builder reports these under
  `low_evidence` — the concept exists and is generic, but the sources do not
  spell it out as a contiguous phrase often enough to measure (registries write
  "Hydroelectric" as one word, and almost never write out "maternal and child
  health"). Asserting genericness in `generic_tokens` is the documented
  escalation; it is visible in the diff and in the artefact's `curated` block.
- **UK health coverage is Wikidata-shaped**, not registry-shaped. NHS ODS and
  the FHRS API both refuse automated access from this environment, so UK
  vocabulary comes from ~10,000 Wikidata labels rather than a national list.
  `surgery` (0.42) and `practice` (0.47) are now safely below the floor, but a
  proper UK stratum would be a real improvement.
- **No Kenyan, Ghanaian or South African registry stratum.** HDX carries CC-BY
  health facility lists for Kenya, Malawi, Zimbabwe, South Sudan and Ethiopia,
  several as XLSX. Adding them is straightforward and would widen the African
  registry vocabulary beyond Nigeria.
