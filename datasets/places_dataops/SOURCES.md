# Place frequency table — sources and attribution

`packages/arche-core/src/arche/resolve/_data/place_frequencies.json.gz` is a
derived work. Every source below is CC0, CC-BY, or CC-BY-IGO, and **attribution
is a condition of the licence, not a courtesy**. The same list is embedded in
the artefact's own `provenance` block, so it travels with the file.

Rebuild: `python datasets/places_dataops/build_place_frequencies.py`

## Sources

| Source | Licence | What it contributes |
|---|---|---|
| [GeoNames](https://download.geonames.org/export/dump/) per-country dumps (20 countries) | CC-BY-4.0 | Settlement names — the vocabulary that makes distinctive residuals rare — plus the sparse facility feature codes |
| [Wikidata](https://query.wikidata.org/) via SPARQL, by entity class | CC0-1.0 | Hospitals, clinics, health centres, doctors' surgeries, substations, power stations, solar and wind farms, schools, universities. The only source that can be asked for a *class* of place in a given country |
| [WRI Global Power Plant Database](https://github.com/wri/global-power-plant-database) | CC-BY-4.0 | ~34,900 power plants across 167 countries |
| GRID3 / NHFR Nigeria health facilities v2 | CC-BY | 51,022 Nigerian facilities, 37 states |
| Nigeria Health Facility Registry (Kano, Edo, Ondo) via [HDX](https://data.humdata.org/dataset/nigeria-health-facilities) | CC-BY | Registry naming conventions and alternate names |

Countries in the GeoNames stratum: GB, IE, NG, GH, SN, CI, CM, KE, TZ, UG, RW,
ET, ZA, ZM, ZW, MW, EG, MA, IN, BR.

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
